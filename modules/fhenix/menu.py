"""Fhenix submenu — выбор модуля внутри проекта."""
from colorama import Fore, Style
from questionary import select

from config.menu_config import SubMenu, MenuItem, build_submenu_choices


FHENIX_SUBMENU = SubMenu(
    key='fhenix',
    label='Fhenix — выберите модуль',
    description='',
    icon='🟢',
    qmark='🟢',
    pointer='👉',
    items=[
        MenuItem(key='ghost_faucet', label='Ghost Faucet (Sepolia)',
                 description='Запрос крана на ghostchain.io/faucet/ethereum-sepolia',
                 icon='🚰', enabled=True),
        MenuItem(key='alchemy_faucet', label='Alchemy Faucet (Base Sepolia)',
                 description='Запрос крана на alchemy.com/faucets/base-sepolia',
                 icon='🚰', enabled=True),
        MenuItem(key='back', label='Назад', description='', icon='🔙', enabled=True),
    ],
)


def fhenix_menu():
    """Главное меню проекта Fhenix."""
    while True:
        action = select(
            "🟢 Fhenix — выберите модуль:",
            choices=build_submenu_choices(FHENIX_SUBMENU),
            qmark=FHENIX_SUBMENU.qmark,
            pointer=FHENIX_SUBMENU.pointer,
        ).ask()

        if action is None or action == 'back':
            return

        if action == 'ghost_faucet':
            from modules.fhenix.ghost_faucet import run_ghost_faucet
            run_ghost_faucet()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        elif action == 'alchemy_faucet':
            from modules.fhenix.alchemy_faucet import run_alchemy_faucet
            run_alchemy_faucet()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
