"""Pharos Testnet — минимальное меню.

Testnet-фаза завершена. Оставлен только Claim Checker — проверка результатов
https://claim.pharos.xyz/ (eligibility / allocation).
"""
from questionary import select

from config.menu_config import SubMenu, MenuItem, build_submenu_choices
from modules.pharos_claim.menu import claim_checker_menu


PHAROS_MENU = SubMenu(
    key="pharos",
    label="Pharos Testnet",
    description="Проверка результатов claim.pharos.xyz",
    icon="🟢",
    qmark="🟢",
    pointer="👉",
    items=[
        MenuItem(
            key="claim_checker",
            label="Claim Checker",
            description="Проверка результатов claim.pharos.xyz",
            icon="🏆",
        ),
        MenuItem(key="back", label="Назад", description="", icon="🔙"),
    ],
)


def pharos_menu() -> None:
    """Главное меню Pharos — вызывается из main.py (projects_menu)."""
    while True:
        action = select(
            "Pharos Testnet — выберите действие:",
            choices=build_submenu_choices(PHAROS_MENU),
            qmark=PHAROS_MENU.qmark,
            pointer=PHAROS_MENU.pointer,
        ).ask()

        if action is None or action == "back":
            return
        if action == "claim_checker":
            claim_checker_menu()
