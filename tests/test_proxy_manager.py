"""Юнит-тесты разделяемого парсера прокси ``modules.proxy_manager.parse_proxy``.

``parse_proxy`` — единственная точка, через которую весь проект должен
превращать строку прокси в URL для requests. От её корректности зависит,
уйдёт трафик через прокси или молча через реальный IP пользователя, поэтому
здесь закреплены все поддерживаемые форматы и поведение на мусоре.
"""

from __future__ import annotations

import pytest

import modules.proxy_manager as pm
from modules.proxy_manager import parse_proxy


class _Recorder:
    """Заглушка логгера: копит warning-сообщения для проверок."""

    def __init__(self):
        self.warnings = []

    def warning(self, msg):
        self.warnings.append(msg)

    # parse_proxy пользуется только warning, но пусть info/error не падают.
    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


# --- Валидные форматы: результат должен сохранять схему и все credentials ---

@pytest.mark.parametrize(
    "raw, expected",
    [
        # host:port без схемы -> по умолчанию http (историческое поведение)
        ("1.2.3.4:8080", "http://1.2.3.4:8080"),
        # user:pass@host:port без схемы -> http
        ("user:pass@1.2.3.4:8080", "http://user:pass@1.2.3.4:8080"),
        # явная схема http/https сохраняется как есть
        ("http://1.2.3.4:8080", "http://1.2.3.4:8080"),
        ("https://1.2.3.4:8080", "https://1.2.3.4:8080"),
        ("http://user:pass@host.example.com:3128",
         "http://user:pass@host.example.com:3128"),
        ("https://user:pass@host.example.com:3128",
         "https://user:pass@host.example.com:3128"),
        # socks4/socks5 больше не превращаются в http://socks5://...
        ("socks5://host:1080", "socks5://host:1080"),
        ("socks4://host:1080", "socks4://host:1080"),
        ("socks5://user:pass@host:1080", "socks5://user:pass@host:1080"),
        ("socks4://user:pass@host:1080", "socks4://user:pass@host:1080"),
        ("socks5h://user:pass@host:1080", "socks5h://user:pass@host:1080"),
        # хостнейм (резидентские прокси), а не только IPv4
        ("gate.provider.io:9999", "http://gate.provider.io:9999"),
    ],
)
def test_valid_formats(raw, expected):
    """Все поддерживаемые форматы разбираются без потери схемы и данных."""
    assert parse_proxy(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        # пароль с ':'
        ("user:p:ss@host:1080", "http://user:p:ss@host:1080"),
        # пароль с '@'
        ("user:p@ss@host:1080", "http://user:p@ss@host:1080"),
        # пароль сразу с ':' и '@', плюс схема socks5
        ("socks5://user:p@:ss@host:1080", "socks5://user:p@:ss@host:1080"),
    ],
)
def test_password_with_special_chars(raw, expected):
    """Пароли с ':' и '@' не должны ломать разбор credentials/адреса."""
    assert parse_proxy(raw) == expected


def test_whitespace_is_trimmed():
    """Ведущие/хвостовые пробелы не мешают разбору."""
    assert parse_proxy("  1.2.3.4:8080  ") == "http://1.2.3.4:8080"


def test_socks5_round_trip_is_stable():
    """Повторный прогон результата через parse_proxy ничего не портит."""
    once = parse_proxy("socks5://user:pass@host:1080")
    assert parse_proxy(once) == once


# --- Пустой вход: это «прокси не задан», а не ошибка (логировать не нужно) ---

@pytest.mark.parametrize("raw", [None, "", "   "])
def test_empty_input_returns_none_without_warning(raw, monkeypatch):
    """Пустое значение возвращает None и НЕ засоряет лог предупреждениями."""
    rec = _Recorder()
    monkeypatch.setattr(pm, "logger", rec)
    assert parse_proxy(raw) is None
    assert rec.warnings == []


# --- Мусор: None + обязательное предупреждение с указанием причины ---

@pytest.mark.parametrize(
    "raw",
    [
        "notaproxy",              # нет порта
        "host:notaport",          # порт не число
        "user:pass@host",         # у адреса нет порта
        "user@host:1080",         # в credentials нет ':'
        ":secret@host:1080",      # пустой логин
        "ftp://host:1080",        # неизвестная/непроксируемая схема
        "socks6://host:1080",     # несуществующая socks-схема
    ],
)
def test_malformed_returns_none_and_warns(raw, monkeypatch):
    """Любой непустой мусор -> None, но с предупреждением в логе (не молча)."""
    rec = _Recorder()
    monkeypatch.setattr(pm, "logger", rec)
    assert parse_proxy(raw) is None
    assert rec.warnings, f"ожидали warning для {raw!r}, а лог пуст"


def test_warning_masks_credentials(monkeypatch):
    """В предупреждении не должно светиться login:password (только host:port)."""
    rec = _Recorder()
    monkeypatch.setattr(pm, "logger", rec)
    # некорректный порт, чтобы гарантированно уйти в ветку с warning
    parse_proxy("secretuser:secretpass@host:notaport")
    joined = " ".join(rec.warnings)
    assert "secretpass" not in joined
    assert "secretuser" not in joined


def test_get_proxy_dict_uses_parser():
    """get_proxy_dict оборачивает результат parse_proxy в http/https-словарь."""
    d = pm.get_proxy_dict("socks5://user:pass@host:1080")
    assert d == {
        "http": "socks5://user:pass@host:1080",
        "https": "socks5://user:pass@host:1080",
    }
    # мусор -> None, а не словарь с None-значениями
    assert pm.get_proxy_dict("notaproxy") is None


# --- mask_proxy: в лог не должно утечь ничего, кроме host:port ---

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("user:pass@host:8080", "host:8080"),
        # пароль с '@': split('@')[1] отдавал кусок пароля вместо адреса
        ("user:p@ss@host:8080", "host:8080"),
        ("http://user:p@ss@host:8080", "host:8080"),
        # без credentials маскировать нечего
        ("socks5://host:1080", "socks5://host:1080"),
        (None, "None"),
    ],
)
def test_mask_proxy_leaves_only_address(raw, expected):
    """mask_proxy отдаёт только host:port, даже если пароль содержит '@'."""
    assert pm.mask_proxy(raw) == expected


# --- Потребители общего парсера ---

def test_discord_get_proxy_dict_survives_colon_in_password():
    """Discord-модуль больше не падает на пароле с ':' (использует общий парсер)."""
    from modules.discord.discord_age import get_proxy_dict as discord_get_proxy_dict

    url = "http://user:p:ss@1.2.3.4:8080"
    assert discord_get_proxy_dict("user:p:ss@1.2.3.4:8080") == {"http": url, "https": url}
    # схема socks5 доживает до requests, а не превращается в http://socks5://...
    assert discord_get_proxy_dict("socks5://u:p@h:1080")["http"] == "socks5://u:p@h:1080"


def test_email_imap_proxy_is_declared_unsupported():
    """IMAP-чекер не делает вид, что использует прокси, и не трогает urllib.

    Раньше setup_proxy_socket ставил глобальный urllib-опенер, которого
    imaplib не читает: логин в почту уходил с реального IP, а в лог писалось
    «Используем прокси». Тест фиксирует, что обман убран.
    """
    import modules.email.email_imap_checker as mod

    checker = mod.EmailChecker()
    cfg = checker.parse_proxy("user:pass@1.2.3.4:8080")
    assert cfg is not None
    # Прокси не применяется: метод отвечает «нет», а не True.
    assert checker.setup_proxy_socket(cfg) is False
    # Глобальное состояние urllib не трогаем — модуль его больше не импортирует.
    assert not hasattr(mod, "urllib")
