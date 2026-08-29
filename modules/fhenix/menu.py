"""Fhenix — выбор крана внутри проекта.

Хаб из двух пунктов: собственного состояния у него нет, поэтому ModuleMenu
здесь избыточен — достаточно списка пунктов из UI-набора.
"""
from __future__ import annotations

from modules.ui import BACK_KEY, MenuItem, SubMenu, ui

FHENIX_SUBMENU = SubMenu(
    key="fhenix",
    label="Fhenix",
    description="",
    icon="🟢",
    items=[
        MenuItem(key="ghost_faucet", label="Ghost Faucet",
                 description="тестовый ETH сети Sepolia", icon="🚰"),
        MenuItem(key="alchemy_faucet", label="Alchemy Faucet",
                 description="тестовый ETH сети Base Sepolia", icon="🚰"),
        MenuItem(key=BACK_KEY, label="Назад", description="", icon="←"),
    ],
)


def fhenix_menu() -> None:
    """Главное меню проекта Fhenix."""
    while True:
        action = ui.show_items("🟢 Fhenix — выберите кран",
                               FHENIX_SUBMENU.items)
        if action in (None, BACK_KEY):
            return

        if action == "ghost_faucet":
            from modules.fhenix.ghost_faucet import run_ghost_faucet

            run_ghost_faucet()
        elif action == "alchemy_faucet":
            from modules.fhenix.alchemy_faucet import run_alchemy_faucet

            run_alchemy_faucet()


__all__ = ["fhenix_menu", "FHENIX_SUBMENU"]
