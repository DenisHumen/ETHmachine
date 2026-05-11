import unicodedata
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# Стиль красного бейджа — совпадает с уровнем ERROR в modules/simple_logger.py
_BADGE_RED = "\033[41m\033[97;1m {text} \033[0m"

# Целевая визуальная ширина колонки "иконка + label" (в ячейках терминала)
_LABEL_COLUMN_WIDTH = 35


def _visual_width(s: str) -> int:
    """Приблизительная ширина строки в ячейках терминала.

    Учитывает, что emoji и East-Asian-Wide символы занимают 2 клетки,
    а variation selectors (️ и т.п.) — 0. ljust() оперирует
    кол-вом codepoint'ов, поэтому без этой функции menu items с emoji
    разной структуры (с VS-16 и без) выглядят сдвинутыми.
    """
    width = 0
    for ch in s:
        if ch in ('️', '︎') or unicodedata.combining(ch):
            continue
        cp = ord(ch)
        if (
            unicodedata.east_asian_width(ch) in ('W', 'F')
            or 0x2300 <= cp <= 0x27BF
            or 0x2B00 <= cp <= 0x2BFF
            or 0x1F000 <= cp <= 0x1FFFF
        ):
            width += 2
        else:
            width += 1
    return width


def _pad_label(icon: str, label: str) -> str:
    raw = f"{icon} {label}"
    pad = max(1, _LABEL_COLUMN_WIDTH - _visual_width(raw))
    return raw + ' ' * pad


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
    badge: Optional[str] = None          # Бейдж в красной рамке (как в логере) — например "ПАУЗА"

    def get_choice_text(self) -> str:
        padded_label = _pad_label(self.icon, self.label)
        if self.badge:
            badge = _BADGE_RED.format(text=self.badge)
            return f"{padded_label}🌟 {badge} {self.description}"
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
        return f"{_pad_label(self.icon, self.label)}🌟 {self.description}"

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
    'twitter',
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
    'projects_menu': MenuItem(
        key='projects_menu',
        label='PROJECTS',
        description='Автоматизация проектов',
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
        MenuItem(key='zksync_lite', label='zkSync Lite', description='Балансы zkSync Lite (lite.zksync.io)', icon='🟪', enabled=True),
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
        MenuItem(key='collectors', label='Collectors', description='Сборщик балансов на main кошелек', icon='🧹', enabled=True),
        MenuItem(key='transfer_wallets_to_wallets_call', label='Transfer Wallets to Wallets', description='Отправить нативные токены между кошельками', icon='🔄', enabled=True),
        MenuItem(key='transfer_erc20_tokens_call', label='Transfer ERC20 Tokens', description='Отправить ERC20 токены между кошельками', icon='💎', enabled=True),
        MenuItem(key='relay_bridge', label='Relay Bridge', description='Мост между сетями через Relay Link', icon='🌉', enabled=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
    ]
)

COLLECTORS_SUBMENU = SubMenu(
    key='collectors',
    label='Выберите действие',
    description='',
    items=[
        MenuItem(key='eth_collectors', label='ETH Collectors', description='Сборщик ETH', icon='💲', enabled=True),
        MenuItem(key='sol_collectors', label='SOL Collectors', description='Сборщик SOL (WIP)', icon='💲', enabled=True, is_wip=True),
        MenuItem(key='back', label='Back', description='Назад', icon='🔙', enabled=True),
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
    label='Выберите проект',
    description='',
    icon='🎮',
    qmark='🎮',
    items=[
        MenuItem(key='xstocks', label='xStocks DeFi', description='Register, GM, Referrals, Points', icon='🟢', enabled=True, badge='ПАУЗА'),
        MenuItem(key='neura_stat', label='Neura', description='Статистика по ETHmachine', icon='🟢', enabled=True, requires_os='windows'),
        MenuItem(key='dune', label='Dune', description='Аналитика и проверка кошельков через Dune Analytics', icon='🟢', enabled=True),
        MenuItem(key='fhenix', label='Fhenix', description='Кран ghostchain (Sepolia) и др.', icon='🔥', enabled=True),
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
        MenuItem(key='generate_wallets', label='Generate Wallets', description='Генерация кошельков', icon='🪙', enabled=True),
        MenuItem(key='ETH_convert_tool', label='ETH/SOL convert tool', description='Конвертация мнемоники/priv_key в wallet_address/priv_key', icon='🛠️', enabled=True),
        MenuItem(key='password_generator', label='Password Generator', description='Генерация паролей по заданым параметра в "config/config.py"', icon='🔑', enabled=True),
        MenuItem(key='nickname_generator', label='Nickname Generator', description='Генерация человечески выглядящих никнеймов', icon='🎭', enabled=True),
        MenuItem(key='fullname_generator', label='Fullname Generator', description='Генерация имён и фамилий (RU/UA/ENG)', icon='👤', enabled=True),
        MenuItem(key='check_proxy', label='Check Proxy', description='Проверить прокси', icon='🛠️', enabled=True),
        MenuItem(key='check_age_discord', label='Check age discord', description='Проверить возраст аккаунта Discord', icon='🗂️', enabled=True),
        MenuItem(key='email_checker', label='Email IMAP Checker', description='Проверить почтовые аккаунты через IMAP', icon='📧', enabled=True),
        MenuItem(key='pinterest_downloader', label='Pinterest Downloader', description='Скачать рандомные картинки из Pinterest', icon='📌', enabled=True),
        MenuItem(key='swap_all_polygon_zkevm_to_base', label='Swap All Polygon zkEVM → Base USDC', description='Свап всех токенов с Polygon zkEVM в USDC на Base через Layerswap', icon='💱', enabled=True),
        MenuItem(key='swap_all_zksync_era_to_base', label='Swap All zkSync Era → Base USDC', description='Свап USDC/USDT с zkSync Era в USDC на Base через Rhino.fi', icon='💱', enabled=True),
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


def _wrap_title(text: str):
    """Превращает строку с ANSI escape-кодами в FormattedText, который
    questionary/prompt_toolkit отрисует с правильными цветами.

    Просто `ANSI(text)` не работает: в текущей версии questionary `Choice`
    приводит неизвестный тип через `str()` и в меню печатается literal
    `ANSI('...')`. Поэтому сразу разворачиваем в список `(style, text)`
    кортежей через `to_formatted_text` — он наследник `list`, который
    `Choice` принимает как готовый FormattedText.
    """
    if '\033' not in text:
        return text
    try:
        from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    except ImportError:
        return text
    return to_formatted_text(ANSI(text))


def build_choices(items: list) -> list:
    from questionary import Choice
    return [Choice(_wrap_title(item.get_choice_text()), item.key) for item in items if item.enabled]


def build_submenu_choices(submenu: SubMenu) -> list:
    from questionary import Choice
    return [Choice(_wrap_title(item.get_choice_text()), item.key) for item in submenu.get_enabled_items()]
