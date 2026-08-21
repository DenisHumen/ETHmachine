"""Каркас меню модуля: состав пунктов, служебные экраны, подтверждения."""

from __future__ import annotations

import pytest

from modules.ui import text
from modules.ui.menu_model import BACK_KEY, render_items
from modules.ui.module_menu import (
    INFO_KEY, RESET_KEY, STATS_KEY, MenuAction, ModuleMenu,
)


def _menu(**kwargs) -> ModuleMenu:
    defaults = dict(
        title="Тестовый модуль",
        actions=[
            MenuAction("run", "Запуск", lambda: None, "сделать дело", icon="▶️"),
        ],
    )
    defaults.update(kwargs)
    return ModuleMenu(**defaults)


def _keys(menu: ModuleMenu) -> list[str]:
    return [item.key for item in menu._items()]


def test_back_is_always_last():
    assert _keys(_menu())[-1] == BACK_KEY


def test_service_items_appear_only_when_configured():
    plain = _menu()
    assert STATS_KEY not in _keys(plain)
    assert INFO_KEY not in _keys(plain)
    assert RESET_KEY not in _keys(plain)

    full = _menu(stats=lambda: {"total": 0}, info={"Раздел": ["строка"]},
                 reset=lambda: None)
    keys = _keys(full)
    assert STATS_KEY in keys and INFO_KEY in keys and RESET_KEY in keys


def test_disabled_actions_are_hidden():
    menu = _menu(actions=[
        MenuAction("a", "Видимый", lambda: None),
        MenuAction("b", "Скрытый", lambda: None, enabled=False),
    ])
    assert "b" not in _keys(menu)


def test_rendered_menu_columns_align():
    menu = _menu(
        actions=[
            MenuAction("a", "Коротко", lambda: None, "описание"),
            MenuAction("b", "Существенно длиннее название", lambda: None, "описание"),
        ],
        stats=lambda: {"total": 0}, info={"x": ["y"]}, reset=lambda: None,
    )
    widths = {
        text.visual_width(text.strip_ansi(label).split("│", 1)[0])
        for label, _ in render_items(menu._items())
        if "│" in text.strip_ansi(label)
    }
    assert len(widths) == 1, f"колонка разъехалась: {sorted(widths)}"


def test_stats_screen_renders(capsys):
    menu = _menu(stats=lambda: {"pending": 2, "arrived": 5, "total": 7},
                 stats_title="db/example.db")
    menu._show_stats()
    out = text.strip_ansi(capsys.readouterr().out)
    assert "db/example.db" in out and "pending" in out and "7" in out


def test_stats_screen_explains_missing_table(capsys):
    """Незапускавшийся модуль — не ошибка, а пустая база."""
    import sqlite3

    def boom():
        raise sqlite3.OperationalError("no such table: demo_tasks")

    _menu(stats=boom)._show_stats()
    out = text.strip_ansi(capsys.readouterr().out)
    assert "ещё не запускался" in out
    assert "no such table" not in out, "пользователю показали внутреннюю ошибку SQLite"


def test_stats_screen_reports_real_errors(capsys):
    def boom():
        raise RuntimeError("диск отвалился")

    _menu(stats=boom)._show_stats()
    out = text.strip_ansi(capsys.readouterr().out)
    assert "диск отвалился" in out


def test_info_accepts_callable_and_mapping(capsys):
    _menu(info={"Раздел": ["из словаря"]})._show_info()
    assert "из словаря" in text.strip_ansi(capsys.readouterr().out)

    _menu(info=lambda: {"Раздел": ["из функции"]})._show_info()
    assert "из функции" in text.strip_ansi(capsys.readouterr().out)


def test_reset_requires_confirmation(monkeypatch, capsys):
    """Очистка базы без подтверждения недопустима."""
    called: list[bool] = []
    menu = _menu(reset=lambda: called.append(True))

    monkeypatch.setattr("modules.ui.prompts.confirm", lambda *a, **k: False)
    menu._do_reset()
    assert not called, "база очищена без подтверждения"
    assert "Отменено" in text.strip_ansi(capsys.readouterr().out)

    monkeypatch.setattr("modules.ui.prompts.confirm", lambda *a, **k: True)
    menu._do_reset()
    assert called == [True]


def test_action_confirm_blocks_handler(monkeypatch):
    ran: list[str] = []
    menu = _menu(actions=[
        MenuAction("danger", "Опасное", lambda: ran.append("x"),
                   confirm="Точно?", pause_after=False),
    ])

    answers = iter(["danger", BACK_KEY])
    monkeypatch.setattr("modules.ui.prompts.menu", lambda *a, **k: next(answers))
    monkeypatch.setattr("modules.ui.prompts.confirm", lambda *a, **k: False)
    menu.run()
    assert ran == [], "действие выполнилось несмотря на отказ в подтверждении"


def test_run_dispatches_and_exits(monkeypatch):
    ran: list[str] = []
    menu = _menu(actions=[
        MenuAction("run", "Запуск", lambda: ran.append("run"), pause_after=False),
    ])

    answers = iter(["run", BACK_KEY])
    monkeypatch.setattr("modules.ui.prompts.menu", lambda *a, **k: next(answers))
    menu.run()
    assert ran == ["run"]


def test_run_exits_on_ctrl_c_at_menu(monkeypatch):
    """Ctrl+C в самом меню возвращает в родительское меню, а не роняет программу."""
    monkeypatch.setattr("modules.ui.prompts.menu", lambda *a, **k: None)
    _menu().run()  # не должно бросить


def test_keyboard_interrupt_inside_action_is_contained(monkeypatch, capsys):
    def interrupted():
        raise KeyboardInterrupt

    menu = _menu(actions=[
        MenuAction("run", "Запуск", interrupted, pause_after=False),
    ])
    answers = iter(["run", BACK_KEY])
    monkeypatch.setattr("modules.ui.prompts.menu", lambda *a, **k: next(answers))
    menu.run()  # не должно вылететь наружу
    assert "Прервано пользователем" in text.strip_ansi(capsys.readouterr().out)
