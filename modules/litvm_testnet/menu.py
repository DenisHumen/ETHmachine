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
        MenuItem(
            key='lester_minter',
            label='Lester Minter (ERC-20 фабрика)',
            description='Деплой случайных ERC-20 на lester-labs.com/launch',
            icon='🪙',
            enabled=True,
        ),
        MenuItem(
            key='midas',
            label='Midas Prediction Market',
            description='Регистрация, faucets, check-in, ставки на midashand.xyz',
            icon='🎯',
            enabled=True,
        ),
        MenuItem(
            key='aynilabs',
            label='Aynilabs (wrap zkLTC)',
            description='',
            icon='🪙',
            enabled=True,
            badge='Сайт с низким функционалом, будет добавлен новый как только появится на сайте',
            badge_style='yellow',
        ),
        MenuItem(
            key='onmi',
            label='Onmi.fun (meme-coin launchpad)',
            description='Создание мем-токенов на bonding-curve (createTokenAndBuy)',
            icon='🪙',
            enabled=True,
        ),
        MenuItem(
            key='onmi_trade',
            label='Onmi.fun · Wallet trading (buy/sell)',
            description='Случайные buy/sell мем-токенов между кошельками (live look)',
            icon='🎲',
            enabled=True,
        ),
        MenuItem(
            key='onmi_swap',
            label='Onmi.fun · Swap (graduated tokens)',
            description='UniswapV2-style свапы graduated мем-токенов (random-walk)',
            icon='💱',
            enabled=True,
        ),
        MenuItem(
            key='onmi_liquidity',
            label='Onmi.fun · Liquidity (add / withdraw all)',
            description='Маленькие LP-добавления + одна кнопка вывести всё',
            icon='💧',
            enabled=True,
        ),
        MenuItem(
            key='zns_bio',
            label='ZNS.bio · Регистрация .lit доменов',
            description='Регистрация случайных никнеймов в TLD .lit на ZNS Connect',
            icon='🪪',
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
        elif action == 'lester_minter':
            from modules.litvm_testnet.lester_minter import run_litvm_minter
            run_litvm_minter()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        elif action == 'midas':
            from modules.litvm_testnet.midas import run_litvm_midas
            run_litvm_midas()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        elif action == 'aynilabs':
            from modules.litvm_testnet.aynilabs import run_litvm_aynilabs
            run_litvm_aynilabs()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        elif action == 'onmi':
            from modules.litvm_testnet.onmi import run_litvm_onmi
            run_litvm_onmi()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        elif action == 'onmi_trade':
            from modules.litvm_testnet.onmi.trade import run_litvm_onmi_trade
            run_litvm_onmi_trade()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        elif action == 'onmi_swap':
            from modules.litvm_testnet.onmi.swap import run_litvm_onmi_swap
            run_litvm_onmi_swap()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        elif action == 'onmi_liquidity':
            from modules.litvm_testnet.onmi.liquidity import run_litvm_onmi_liquidity
            run_litvm_onmi_liquidity()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
        elif action == 'zns_bio':
            from modules.litvm_testnet.zns_bio import run_litvm_zns_bio
            run_litvm_zns_bio()
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
