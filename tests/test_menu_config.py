"""Целостность меню: ключи, обработчики, выравнивание, тексты.

Меню — единственная точка входа пользователя, поэтому рассинхрон между
``config/menu_config.py`` и ``main.py`` ломает продукт молча: пункт есть,
а нажатие ничего не делает.
"""

from __future__ import annotations

import ast
import re

import pytest

from config import menu_config as mc
from tests.conftest import PROJECT_ROOT

ALL_SUBMENUS = [
    getattr(mc, name)
    for name in dir(mc)
    if isinstance(getattr(mc, name), mc.SubMenu)
]


def _main_py_source() -> str:
    return (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")


def _string_literals(source: str) -> set[str]:
    """Все строковые литералы main.py — надёжнее регулярок по `case '...'`."""
    tree = ast.parse(source)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_submenus_discovered():
    assert len(ALL_SUBMENUS) >= 10


@pytest.mark.parametrize("submenu", ALL_SUBMENUS, ids=lambda s: s.key)
def test_submenu_keys_are_unique(submenu: mc.SubMenu):
    keys = [item.key for item in submenu.items]
    duplicates = {k for k in keys if keys.count(k) > 1}
    assert not duplicates, f"дубли ключей в {submenu.key}: {duplicates}"


@pytest.mark.parametrize("submenu", ALL_SUBMENUS, ids=lambda s: s.key)
def test_submenu_has_back_item(submenu: mc.SubMenu):
    assert any(item.key == "back" for item in submenu.items), (
        f"в подменю {submenu.key} нет пункта 'Назад' — пользователь окажется в тупике"
    )


@pytest.mark.parametrize("submenu", ALL_SUBMENUS, ids=lambda s: s.key)
def test_back_item_is_last(submenu: mc.SubMenu):
    assert submenu.items[-1].key == "back", (
        f"'Назад' в {submenu.key} должен быть последним пунктом"
    )


def test_every_enabled_key_is_handled_in_main():
    """Каждый включённый ключ меню должен встречаться в main.py или в меню модуля."""
    literals = _string_literals(_main_py_source())
    # Ключи, которые обрабатываются внутри собственных меню модулей.
    handled_elsewhere = {"back"}

    unhandled: list[str] = []
    for submenu in ALL_SUBMENUS:
        for item in submenu.get_enabled_items():
            if item.key in handled_elsewhere or item.key in literals:
                continue
            unhandled.append(f"{submenu.key}.{item.key}")
    for key, item in mc.MENU_ITEMS.items():
        if item.enabled and key not in literals:
            unhandled.append(f"MENU_ITEMS.{key}")

    assert not unhandled, f"пункты меню без обработчика: {unhandled}"


def test_main_menu_order_matches_defined_items():
    unknown = [k for k in mc.MAIN_MENU_ORDER if k not in mc.MENU_ITEMS]
    assert not unknown, f"MAIN_MENU_ORDER ссылается на несуществующие пункты: {unknown}"


@pytest.mark.parametrize("submenu", ALL_SUBMENUS, ids=lambda s: s.key)
def test_menu_column_is_aligned(submenu: mc.SubMenu):
    """Колонка названий одинаковой ширины у всех пунктов подменю."""
    from modules.ui import render_items
    from modules.ui.text import strip_ansi, visual_width

    widths = set()
    for label, _ in render_items(submenu.items):
        plain = strip_ansi(label)
        if "│" not in plain:
            continue  # пункт без описания — колонка не рисуется
        widths.add(visual_width(plain.split("│", 1)[0]))
    assert len(widths) <= 1, (
        f"колонка названий в {submenu.key} разъехалась: {sorted(widths)}"
    )


@pytest.mark.parametrize("submenu", ALL_SUBMENUS, ids=lambda s: s.key)
def test_rendered_items_have_no_dangling_separator(submenu: mc.SubMenu):
    """Пункт без описания не должен заканчиваться висящим разделителем."""
    from modules.ui import render_items
    from modules.ui.text import strip_ansi

    dangling = [
        key for label, key in render_items(submenu.items)
        if strip_ansi(label).rstrip().endswith("│")
    ]
    assert not dangling, f"висящий разделитель в {submenu.key}: {dangling}"


@pytest.mark.parametrize("submenu", ALL_SUBMENUS, ids=lambda s: s.key)
def test_labels_are_not_absurdly_long(submenu: mc.SubMenu):
    """Слишком длинное название съедает место под описание."""
    from modules.ui.text import visual_width

    long_labels = [
        (item.key, visual_width(item.label_cell()))
        for item in submenu.items
        if visual_width(item.label_cell()) > 42
    ]
    assert not long_labels, f"слишком длинные пункты в {submenu.key}: {long_labels}"


def test_no_double_spaces_in_descriptions():
    bad: list[str] = []
    for submenu in ALL_SUBMENUS:
        for item in submenu.items:
            if "  " in item.description.strip():
                bad.append(f"{submenu.key}.{item.key}")
    assert not bad, f"двойные пробелы в описаниях: {bad}"


def test_descriptions_do_not_reference_missing_config_files():
    """Описания не должны ссылаться на несуществующие файлы конфигурации."""
    referenced = set()
    pattern = re.compile(r"config/[\w/]+\.py")
    for submenu in ALL_SUBMENUS:
        for item in submenu.items:
            referenced.update(pattern.findall(item.description))
    missing = [p for p in sorted(referenced) if not (PROJECT_ROOT / p).exists()]
    assert not missing, f"описания меню ссылаются на несуществующие файлы: {missing}"
