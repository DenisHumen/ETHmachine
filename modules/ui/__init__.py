"""Терминальный UI-набор ETHmachine.

Единый источник внешнего вида для всех модулей: цвета, рамки, меню,
запросы ввода. Модуль не должен собирать ANSI-строки и рамки сам —
иначе интерфейс расползается и ломается на разных терминалах.

Типовое использование в меню модуля::

    from modules.ui import ui

    while True:
        action = ui.menu("Мой модуль", [
            ("🤖 Авто-режим", "auto"),
            ("📊 Статистика", "stats"),
            ("← Назад",       "back"),
        ])
        if action in (None, "back"):
            return
        ...
        ui.pause()
"""

from __future__ import annotations

from modules.ui import components, menu_model, prompts, text, theme
from modules.ui.components import (
    bullet_list, header, info_panel, key_values, panel, rule, stats_panel,
)
from modules.ui.menu_model import (
    BACK_KEY, MenuItem, SubMenu, label_column_width, render_items,
)
from modules.ui.menu_model import show as show_items
from modules.ui.prompts import (
    ask_int, ask_text, choose, confirm, confirm_or_back, menu, pause,
    print_lines,
)
from modules.ui.text import (
    fit, pad, shorten_address, strip_ansi, truncate, visual_width, wrap,
)
from modules.ui.theme import GLYPHS, badge, gradient, panel_width


class _UI:
    """Фасад: ``from modules.ui import ui`` — и всё под рукой."""

    # ── ввод ──
    menu = staticmethod(menu)
    choose = staticmethod(choose)
    confirm = staticmethod(confirm)
    confirm_or_back = staticmethod(confirm_or_back)
    ask_int = staticmethod(ask_int)
    ask_text = staticmethod(ask_text)
    pause = staticmethod(pause)
    show_items = staticmethod(show_items)

    # ── блоки ──
    header = staticmethod(header)
    panel = staticmethod(panel)
    info_panel = staticmethod(info_panel)
    stats_panel = staticmethod(stats_panel)
    key_values = staticmethod(key_values)
    bullet_list = staticmethod(bullet_list)
    rule = staticmethod(rule)
    badge = staticmethod(badge)
    gradient = staticmethod(gradient)
    print_lines = staticmethod(print_lines)

    # ── текст ──
    fit = staticmethod(fit)
    pad = staticmethod(pad)
    truncate = staticmethod(truncate)
    wrap = staticmethod(wrap)
    visual_width = staticmethod(visual_width)
    shorten_address = staticmethod(shorten_address)

    glyphs = GLYPHS
    theme = theme


ui = _UI()

__all__ = [
    "ui", "theme", "text", "components", "prompts", "menu_model",
    "MenuItem", "SubMenu", "BACK_KEY",
    "menu", "choose", "confirm", "confirm_or_back", "ask_int", "ask_text", "pause",
    "print_lines", "show_items", "render_items", "label_column_width",
    "header", "panel", "info_panel", "stats_panel", "key_values",
    "bullet_list", "rule", "badge", "gradient", "panel_width",
    "fit", "pad", "truncate", "wrap", "visual_width", "strip_ansi",
    "shorten_address", "GLYPHS",
]
