from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict, Any


@dataclass
class MenuItem:
    key: str                              # Уникальный ключ действия
    label: str                            # Отображаемое название
    description: str                      # Описание (после 🌟)
    icon: str = "▶️"                      # Иконка
    enabled: bool = True                  # Включен/выключен
    handler: Optional[Callable] = None   # Функция-обработчик (опционально)
    requires_os: Optional[str] = None    # Требуемая ОС (windows/linux/macos)
    is_wip: bool = False                 # В разработке (показывает предупреждение)
    
    def get_choice_text(self) -> str:
        padded_label = f"{self.icon} {self.label}".ljust(35)
        return f"{padded_label}🌟 {self.description}"


@dataclass
class SubMenu:
    key: str
    label: str
    description: str
    icon: str = "📁"
    enabled: bool = True
    items: List[MenuItem] = field(default_factory=list)
    qmark: str = '🛠️'
    pointer: str = '👉'
    
    def get_choice_text(self) -> str:
        padded_label = f"{self.icon} {self.label}".ljust(35)
        return f"{padded_label}🌟 {self.description}"
    
    def get_enabled_items(self) -> List[MenuItem]:
        return [item for item in self.items if item.enabled]


# =============================================================================
# ГЛАВНОЕ МЕНЮ
# =============================================================================

MAIN_MENU_CONFIG = {
    'title': "Что вы хотите сделать?",
    'qmark': '🛠️',
    'pointer': '👉',
}

# Порядок отображения пунктов главного меню (можно менять местами)
MAIN_MENU_ORDER = [
    'check_balances',
    'transactions',
    'claimer',
    'twitter',
    'project_stats',
    'projects_menu',
    'CEX_menu',
    'miscellaneous',
    'backup_menu',
    'info',
    'exit',
]

# =============================================================================
# ОПРЕДЕЛЕНИЕ ВСЕХ ПУНКТОВ МЕНЮ
# =============================================================================

MENU_ITEMS = {
    # -------------------------------------------------------------------------
    # ГЛАВНОЕ МЕНЮ
    # -------------------------------------------------------------------------
    'check_balances': MenuItem(
        key='check_balances',
        label='BALANCES',
        description='Проверить балансы нативка/токены',
        icon='💲',
        enabled=True,
    ),
    'transactions': MenuItem(
        key='transactions',
        label='TRANSACTIONS',
        description='Транзакции между кошельками',
        icon='🚀',
        enabled=True,
    ),
    'twitter': MenuItem(
        key='twitter',
        label='Twitter',
        description='Сбор данных по твиттерам',
        icon='🐦',
        enabled=True,
    ),
    'project_stats': MenuItem(
        key='project_stats',
        label='Check project stats',
        description='Проверка статистики по проектам',
        icon='📊',
        enabled=True,
    ),
    'projects_menu': MenuItem(
        key='projects_menu',
        label='PROJECTS',
        description='Автоматизация проектов (Neura и др.)',
        icon='🎮',
        enabled=True,
    ),
    'CEX_menu': MenuItem(
        key='CEX_menu',
        label='CEX',
        description='Функционал CEX',
        icon='🏦',
        enabled=True,
    ),
    'miscellaneous': MenuItem(
        key='miscellaneous',
        label='Tools',
        description='Разные удобные инструменты',
        icon='🧰',
        enabled=True,
    ),
    'backup_menu': MenuItem(
        key='backup_menu',
        label='Backup',
        description='Локальные и SFTP бэкапы',
        icon='💾',
        enabled=True,
    ),
    'info': MenuItem(
        key='info',
        label='INFO',
        description='Информация о всех пунктах',
        icon='📖',
        enabled=True,
    ),
    'exit': MenuItem(
        key='exit',
        label='Exit',
        description='Выход из программы',
        icon='❌',
        enabled=True,
    ),
    
    # -------------------------------------------------------------------------
    # Отключенные пункты (раскомментируйте чтобы включить)
    # -------------------------------------------------------------------------
    'selenium_profile': MenuItem(
        key='selenium_profile',
        label='Selenium Profile',
        description='Профиль Selenium',
        icon='🔍',
        enabled=False,  # Выключен
    ),
    'faucets': MenuItem(
        key='faucets',
        label='Faucets',
        description='Краны',
        icon='🚰',
        enabled=False,  # Выключен
    ),
    'claimer': MenuItem(
        key='claimer',
        label='Claimer',
        description='Клейм наград Zora Protocol (Base/Zora)',
        icon='💰',
        enabled=True,
    ),
}

# =============================================================================
# ПОДМЕНЮ: BALANCES
# =============================================================================

BALANCES_SUBMENU = SubMenu(
    key='check_balances',
    label='Выберите блокчейн',
    description='',
    icon='💲',
    items=[
        MenuItem(key='ETH', label='ETH', description='Ethereum и EVM сети', icon='💲', enabled=True),
        MenuItem(key='SOL', label='SOL', description='Solana', icon='💲', enabled=True),
        MenuItem(key='Eclipse', label='Eclipse', description='Eclipse Network', icon='💲', enabled=True),
        MenuItem(key='debank_checker', label='DeBank Checker', description='Проверка всех балансов через DeBank', icon='🏦', enabled=True),
        MenuItem(key='debank_protocols', label='DeBank Protocols', description='Проверка DeFi-позиций (стейкинг, лендинг, locked)', icon='🔗', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

ETH_BALANCES_SUBMENU = SubMenu(
    key='eth_balances',
    label='Выберите действие для ETH',
    description='',
    items=[
        MenuItem(key='check_wallet_balances_eth', label='Check Wallets Balances', description='Проверка балансов кошельков', icon='💲', enabled=True),
        MenuItem(key='check_token_balances', label='Check Token Balances', description='Проверка балансов токенов', icon='💲', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

SOL_BALANCES_SUBMENU = SubMenu(
    key='sol_balances',
    label='Выберите действие для SOL',
    description='',
    items=[
        MenuItem(key='check_wallet_balances_sol', label='Check Wallets Balances', description='Проверка балансов кошельков', icon='💲', enabled=True),
        MenuItem(key='check_token_balances_sol', label='Check Token Balances', description='Проверка балансов токенов (WIP)', icon='💲', enabled=True, is_wip=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# ПОДМЕНЮ: TRANSACTIONS
# =============================================================================

TRANSACTIONS_SUBMENU = SubMenu(
    key='transactions',
    label='Выберите действие',
    description='',
    icon='🚀',
    items=[
        MenuItem(key='drainers', label='Drainers', description='Сборщик балансов на main кошелек', icon='🧹', enabled=True),
        MenuItem(key='transfer_wallets_to_wallets_call', label='Transfer Wallets to Wallets', description='Отправить нативные токены между кошельками', icon='🔄', enabled=True),
        MenuItem(key='transfer_erc20_tokens_call', label='Transfer ERC20 Tokens', description='Отправить ERC20 токены между кошельками', icon='💎', enabled=True),
        MenuItem(key='relay_bridge', label='Relay Bridge', description='Мост между сетями через Relay Link', icon='🌉', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

DRAINERS_SUBMENU = SubMenu(
    key='drainers',
    label='Выберите действие',
    description='',
    items=[
        MenuItem(key='eth_drainers', label='ETH Drainers', description='Сборщик ETH', icon='💲', enabled=True),
        MenuItem(key='sol_drainers', label='SOL Drainers', description='Сборщик SOL (WIP)', icon='💲', enabled=True, is_wip=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# ПОДМЕНЮ: CLAIMER
# =============================================================================

CLAIMER_SUBMENU = SubMenu(
    key='claimer',
    label='Выберите проект для клейма',
    description='',
    icon='💰',
    qmark='💰',
    items=[
        MenuItem(key='zora_claimer', label='Zora Claimer', description='Клейм наград Zora Protocol (Base/Zora сети)', icon='💎', enabled=True),
        MenuItem(key='back', label='Назад', description='', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# ПОДМЕНЮ: TWITTER
# =============================================================================

TWITTER_SUBMENU = SubMenu(
    key='twitter',
    label='Выберите действие с Twitter',
    description='',
    icon='🐦',
    items=[
        MenuItem(key='twitter_check', label='Twitter Check', description='Проверка аккаунтов Twitter', icon='🐦', enabled=True),
        MenuItem(key='twitter_info', label='Twitter Info', description='Получение информации Twitter', icon='🐦', enabled=True),
        MenuItem(key='twitter_task', label='Twitter Task', description='Выполнение заданий Twitter', icon='🐦', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# ПОДМЕНЮ: PROJECTS
# =============================================================================

PROJECTS_SUBMENU = SubMenu(
    key='projects_menu',
    label='Выберите проект для автоматизации',
    description='',
    icon='🎮',
    qmark='🎮',
    items=[
        MenuItem(key='neura', label='Neura Protocol', description='Сбор пульсов и клейм задач', icon='🔮', enabled=True),
        MenuItem(key='pharos', label='Pharos Testnet', description='Faucet, Check-in, Квесты', icon='🔮', enabled=True),
        MenuItem(key='back', label='Назад', description='', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# ПОДМЕНЮ: CEX
# =============================================================================

CEX_SUBMENU = SubMenu(
    key='CEX_menu',
    label='Выберите биржу',
    description='',
    icon='🏦',
    items=[
        MenuItem(key='OKX', label='OKX', description='Работа с OKX', icon='💲', enabled=True),
        MenuItem(key='Binance', label='Binance', description='Работа с Binance', icon='💲', enabled=True),
        MenuItem(key='Bitget', label='Bitget', description='Работа с Bitget', icon='💲', enabled=True),
        MenuItem(key='MEXC', label='MEXC', description='Работа с MEXC', icon='💲', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

OKX_SUBMENU = SubMenu(
    key='OKX',
    label='Выберите действие',
    description='',
    items=[
        MenuItem(key='withdraw_from_okx', label='Withdraw from OKX', description='Вывод с OKX', icon='💲', enabled=True),
        MenuItem(key='get_balances_okx', label='Get Balances from OKX', description='Получить балансы с OKX', icon='💲', enabled=True),
        MenuItem(key='subaccount_collector_okx', label='Subaccount collector OKX', description='Сборщик субаккаунтов OKX', icon='💲', enabled=True),
        MenuItem(key='spot_trade_okx', label='Auto spot trade OKX', description='Спотовая торговля на бирже', icon='💲', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

BINANCE_SUBMENU = SubMenu(
    key='Binance',
    label='Выберите действие',
    description='',
    items=[
        MenuItem(key='withdraw_from_binance', label='Withdraw from Binance', description='Вывод с Binance', icon='💲', enabled=True),
        MenuItem(key='get_balances_binance', label='Get Balances from Binance', description='Получить балансы с Binance', icon='💲', enabled=True),
        MenuItem(key='subaccount_collector_binance', label='Subaccount collector Binance', description='Сборщик субаккаунтов', icon='💲', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

BITGET_SUBMENU = SubMenu(
    key='Bitget',
    label='Выберите действие',
    description='',
    items=[
        MenuItem(key='withdraw_from_bitget', label='Withdraw from Bitget', description='Вывод с Bitget', icon='💲', enabled=True),
        MenuItem(key='get_balances_bitget', label='Get Balances from Bitget', description='Получить балансы с Bitget (WIP)', icon='💲', enabled=True, is_wip=True),
        MenuItem(key='subaccount_collector_bitget', label='Subaccount collector Bitget', description='Сборщик субаккаунтов Bitget', icon='💲', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

MEXC_SUBMENU = SubMenu(
    key='MEXC',
    label='Выберите действие',
    description='',
    items=[
        MenuItem(key='withdraw_from_mexc', label='Withdraw from MEXC', description='Вывод с MEXC', icon='💲', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# ПОДМЕНЮ: TOOLS (MISCELLANEOUS)
# =============================================================================

TOOLS_SUBMENU = SubMenu(
    key='miscellaneous',
    label='Выберите действие',
    description='',
    icon='🧰',
    items=[
        MenuItem(key='check_gas_price', label='Check Gas Price', description='Проверить цену газа', icon='⛽', enabled=True),
        MenuItem(key='generate_wallets', label='Generate Wallets', description='Генерация кошельков', icon='🪙', enabled=True),
        MenuItem(key='ETH_convert_tool', label='ETH/SOL convert tool', description='Конвертация мнемоники/priv_key в wallet_address/priv_key', icon='🛠️', enabled=True),
        MenuItem(key='password_generator', label='Password Generator', description='Генерация паролей по заданым параметра в "config/config.py"', icon='🔑', enabled=True),
        MenuItem(key='nickname_generator', label='Nickname Generator', description='Генерация человечески выглядящих никнеймов', icon='🎭', enabled=True),
        MenuItem(key='fullname_generator', label='Fullname Generator', description='Генерация имён и фамилий (RU/UA/ENG)', icon='👤', enabled=True),
        MenuItem(key='check_proxy', label='Check Proxy', description='Проверить прокси', icon='🛠️', enabled=True),
        MenuItem(key='last_transactions', label='Last Transactions', description='Проверить последние транзакции', icon='🗂️', enabled=True),
        MenuItem(key='check_age_discord', label='Check age discord', description='Проверить возраст аккаунта Discord', icon='🗂️', enabled=True),
        MenuItem(key='email_checker', label='Email IMAP Checker', description='Проверить почтовые аккаунты через IMAP', icon='📧', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# ПОДМЕНЮ: GENERATE WALLETS
# =============================================================================

GENERATE_WALLETS_SUBMENU = SubMenu(
    key='generate_wallets',
    label='Выберите тип генерации кошельков',
    description='',
    icon='🪙',
    items=[
        MenuItem(key='eth_wallets', label='ETH Кошельки', description='Генерация ETH кошельков', icon='⚡', enabled=True),
        MenuItem(key='sol_wallets', label='SOL Кошельки', description='Генерация SOL кошельков', icon='☀️', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

ETH_WALLETS_SUBMENU = SubMenu(
    key='eth_wallets',
    label='Выберите тип генерации ETH кошельков',
    description='',
    icon='⚡',
    items=[
        MenuItem(key='generate', label='Генерация кошельков', description='Сгенерировать кошельки', icon='🪙', enabled=True),
        MenuItem(key='nice_generate', label='Генерация красивых кошельков', description='Сгенерировать красивые кошельки', icon='✨', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

SOL_WALLETS_SUBMENU = SubMenu(
    key='sol_wallets',
    label='Выберите тип генерации SOL кошельков',
    description='',
    icon='☀️',
    items=[
        MenuItem(key='generate', label='Генерация кошельков', description='Сгенерировать кошельки', icon='🪙', enabled=True),
        MenuItem(key='nice_generate', label='Генерация красивых кошельков', description='Сгенерировать красивые кошельки', icon='✨', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# ПОДМЕНЮ: CONVERT TOOL
# =============================================================================

CONVERT_TOOL_SUBMENU = SubMenu(
    key='ETH_convert_tool',
    label='Выберите операцию конвертации',
    description='',
    icon='🛠️',
    items=[
        MenuItem(key='eth_mnemonic_to_privkey', label='ETH >> Mnemonic to Private Key', description='Конвертировать мнемонику в приватный ключ', icon='⚡', enabled=True),
        MenuItem(key='eth_privkey_to_wallet', label='ETH >> Private Key to Wallet', description='Конвертировать приватный ключ в адрес кошелька', icon='⚡', enabled=True),
        MenuItem(key='sol_mnemonic_to_privkey', label='SOL >> Mnemonic to Private Key', description='Конвертировать мнемонику в приватный ключ', icon='☀️', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# ПОДМЕНЮ: PROJECT STATS
# =============================================================================

PROJECT_STATS_SUBMENU = SubMenu(
    key='project_stats',
    label='Выберите действие (статистика по проектам)',
    description='',
    icon='📊',
    items=[
        MenuItem(key='neura_stat', label='Neura', description='Статистика по ETHmachine', icon='📊', enabled=True, requires_os='windows'),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# КОЛИЧЕСТВО КОШЕЛЬКОВ (общий выбор для генераторов)
# =============================================================================

WALLET_COUNT_OPTIONS = [
    {'value': 1, 'label': '1'},
    {'value': 10, 'label': '10'},
    {'value': 100, 'label': '100'},
    {'value': 1000, 'label': '1000'},
    {'value': 5000, 'label': '5000'},
    {'value': 10000, 'label': '10000'},
    {'value': 'manual', 'label': 'Ввести вручную'},
    {'value': 'back', 'label': 'Back'},
]

# =============================================================================
# DISCORD OS SUBMENU
# =============================================================================

DISCORD_OS_SUBMENU = SubMenu(
    key='check_age_discord',
    label='Выберите способ проверки возраста аккаунта Discord',
    description='',
    items=[
        MenuItem(key='windows', label='Windows', description='Windows', icon='💲', enabled=True),
        MenuItem(key='macos', label='MacOS', description='MacOS', icon='💲', enabled=True),
        MenuItem(key='linux', label='Linux', description='Linux', icon='💲', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

# =============================================================================
# RUST IMPLEMENTATION SUBMENU
# =============================================================================

RUST_IMPL_SUBMENU = SubMenu(
    key='rust_impl',
    label='Реализация',
    description='',
    icon='⚙️',
    items=[
        MenuItem(key='python', label='Python (медленно, стабильно)', description='Без зависимостей', icon='🐍', enabled=True),
        MenuItem(key='rust', label='Rust (быстро, требует Cargo)', description='10-100x быстрее', icon='🦀', enabled=True),
        MenuItem(key='back', label='Назад', description='', icon='←', enabled=True),
    ]
)


# =============================================================================
# УТИЛИТЫ ДЛЯ РАБОТЫ С МЕНЮ
# =============================================================================

def get_enabled_main_menu_items() -> list:
    result = []
    for key in MAIN_MENU_ORDER:
        if key in MENU_ITEMS and MENU_ITEMS[key].enabled:
            result.append(MENU_ITEMS[key])
    return result


def build_choices(items: list) -> list:
    from questionary import Choice
    return [Choice(item.get_choice_text(), item.key) for item in items if item.enabled]


def build_submenu_choices(submenu: SubMenu) -> list:
    from questionary import Choice
    return [Choice(item.get_choice_text(), item.key) for item in submenu.get_enabled_items()]
