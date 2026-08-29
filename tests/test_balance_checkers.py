"""Регрессии чекеров балансов (modules/eth).

Ловим две ошибки, из-за которых пользователь получал неверный отчёт:
  1. локальный парсер прокси молча терял `host:port` — запрос уходил с реального IP;
  2. при «Продолжить незавершённые задачи» уже посчитанные кошельки
     попадали в result.csv как «ERROR: Not processed» с нулевым балансом.

Сеть не используется: RPC-вызовы не делаются, БД подменяется заглушкой.
"""

from __future__ import annotations

import csv

import pytest

from modules.eth import eth_get_balances, eth_get_token_balance, oklink_balance_checker


PROXY_MODULES = [eth_get_balances, eth_get_token_balance]


@pytest.mark.parametrize("module", PROXY_MODULES)
def test_proxy_without_auth_is_not_dropped(module):
    """`host:port` без user:pass обязан превращаться в прокси, а не в None."""
    proxy_dict = module.make_proxy_dict("1.2.3.4:8080")

    assert proxy_dict is not None, "прокси без авторизации потерян — запрос уйдёт напрямую"
    assert proxy_dict["http"] == proxy_dict["https"]
    assert "1.2.3.4:8080" in proxy_dict["http"]


@pytest.mark.parametrize("module", PROXY_MODULES)
def test_proxy_with_auth_still_works(module):
    """Основной формат `user:pass@host:port` продолжает работать как раньше."""
    proxy_dict = module.make_proxy_dict("user:pass@1.2.3.4:8080")

    assert proxy_dict is not None
    assert proxy_dict["http"] == "http://user:pass@1.2.3.4:8080"


@pytest.mark.parametrize("module", PROXY_MODULES + [oklink_balance_checker])
def test_empty_proxy_gives_none(module):
    """Пустая строка — это «без прокси», а не ошибка."""
    parser = getattr(module, "make_proxy_dict", None) or module._make_proxy_dict
    assert parser("") is None
    assert parser(None) is None


def test_oklink_proxy_with_scheme_is_not_double_prefixed():
    """Строка со схемой не должна превращаться в `http://http://...`."""
    proxy_dict = oklink_balance_checker._make_proxy_dict("http://user:pass@1.2.3.4:8080")

    assert proxy_dict is not None
    assert proxy_dict["http"] == "http://user:pass@1.2.3.4:8080"


def test_oklink_proxy_without_auth_is_not_dropped():
    """`_make_proxy_dict` импортируют планировщики swap_all_* — контракт общий."""
    proxy_dict = oklink_balance_checker._make_proxy_dict("1.2.3.4:8080")

    assert proxy_dict == {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}


# ── слияние с БД при возобновлении ──────────────────────────────────────────

DB_ROWS = [
    {"wallet_address": "0xAAA", "balance": "1.5", "status": "completed"},
    {"wallet_address": "0xBBB", "balance": None, "status": "failed"},
]


@pytest.mark.parametrize("module", [eth_get_balances, eth_get_token_balance])
def test_merge_keeps_previously_completed_wallets(module, monkeypatch):
    """Успех прошлого прогона остаётся в отчёте, хотя в этом прогоне его не считали."""
    monkeypatch.setattr(module, "get_all_results", lambda *_: list(DB_ROWS))

    fresh = {"0xBBB": {"wallet": "0xBBB", "balance": 2.0, "success": True, "error": None}}
    merged = module.merge_with_db_results(fresh, "native_balance", "Ethereum")

    assert merged["0xAAA"]["success"] is True
    assert merged["0xAAA"]["balance"] == 1.5
    # свежий результат приоритетнее сохранённого
    assert merged["0xBBB"]["balance"] == 2.0


@pytest.mark.parametrize("module", [eth_get_balances, eth_get_token_balance])
def test_merge_survives_broken_db(module, monkeypatch):
    """Недоступная БД не должна ронять экспорт — отчёт строится по текущему прогону."""
    def boom(*_):
        raise RuntimeError("нет таблицы")

    monkeypatch.setattr(module, "get_all_results", boom)

    fresh = {"0xAAA": {"wallet": "0xAAA", "balance": 1.0, "success": True, "error": None}}
    assert module.merge_with_db_results(fresh, "native_balance", "Ethereum") == fresh


def test_resume_does_not_write_false_errors(tmp_path, monkeypatch):
    """result.csv после resume: старый кошелёк — OK, а не «ERROR: Not processed»."""
    monkeypatch.setattr(eth_get_balances, "project_root", tmp_path)
    monkeypatch.setattr(eth_get_balances, "get_all_results", lambda *_: list(DB_ROWS))

    wallets = ["0xAAA", "0xBBB"]
    fresh = {"0xBBB": {"wallet": "0xBBB", "balance": 2.0, "success": True, "error": None}}

    report = eth_get_balances.merge_with_db_results(fresh, "native_balance", "Ethereum")
    eth_get_balances.save_results(report, wallets, "Ethereum", "ETH")

    with open(tmp_path / "result" / "result.csv", encoding="utf-8") as f:
        rows = {r["wallet"]: r for r in csv.DictReader(f)}

    assert rows["0xAAA"]["status"] == "OK"
    assert rows["0xAAA"]["balance"] == "1.5"
    assert rows["0xBBB"]["status"] == "OK"
