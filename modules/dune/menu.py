"""Меню modules.dune — выбор проекта Dune Analytics."""
from __future__ import annotations

from modules.dune.base.menu import base_menu
from modules.ui import ui
from modules.ui.menu_model import BACK_KEY, MenuItem

_PROJECTS = [
    MenuItem("base", "Base Network Analytics",
             "чекер кошельков по публичному дашборду", icon="🟦"),
    MenuItem(BACK_KEY, "Назад", icon="←"),
]


def dune_menu() -> None:
    """Меню выбора проекта внутри Dune."""
    while True:
        choice = ui.show_items("🟦 Dune Analytics — выберите проект", _PROJECTS)
        if choice in (None, BACK_KEY):
            return
        if choice == "base":
            base_menu()


__all__ = ["dune_menu"]
