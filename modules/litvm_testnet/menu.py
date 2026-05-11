"""LiteForge testnet (litvm_testnet) — submenu проекта, список пресетов."""
from colorama import Fore, Style
from questionary import select

from config.menu_config import SubMenu, MenuItem, build_submenu_choices


# Пресеты внутри проекта. Сюда добавляются новые активности (swap, bridge,
# контракты, daily-action и т.п.) — для каждого свой `key` и соответствующая
# ветка в `litvm_testnet_menu()` ниже.
LITVM_TESTNET_SUBMENU = SubMenu(
    key='litvm_testnet',
    label='LiteForge — выберите пресет',
    description='',
    icon='🟢',
    qmark='🟢',
    pointer='👉',
    items=[
        MenuItem(
            key='faucet',
            label='Faucet (zkLTC)',
            description='Запрос крана на liteforge.hub.caldera.xyz',
            icon='🚰',
            enabled=True,
        ),
        MenuItem(
            key='bridge',
            label='Bridge (Sepolia ⇄ LiteForge)',
            description='Перенос zkLTC между сетями через ERC20Inbox',
            icon='🌉',
            enabled=True,
        ),
        MenuItem(key='back', label='Назад', description='', icon='🔙', enabled=True),
    ],
)


def litvm_testnet_menu() -> None:
    """Главное меню проекта LiteForge — выбор пресета."""
    while True:
        action = select(
            "🟢 LiteForge testnet — выберите пресет:",
            choices=build_submenu_choices(LITVM_TESTNET_SUBMENU),
            qmark=LITVM_TESTNET_SUBMENU.qmark,
            pointer=LITVM_TESTNET_SUBMENU.pointer,
        ).ask()

        if action is None or action == 'back':
            return

        if action == 'faucet':
            from modules.litvm_testnet.faucet import run_litvm_faucet
            run_litvm_faucet()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        elif action == 'bridge':
            from modules.litvm_testnet.bridge import run_litvm_bridge
            run_litvm_bridge()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
