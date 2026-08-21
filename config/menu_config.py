"""Состав меню ETHmachine.

Это конфиг, а не код отрисовки: здесь только описание пунктов. Внешний вид
(цвета, выравнивание, рамки) живёт в ``modules/ui`` — правьте его там,
если хотите поменять оформление сразу везде.

Что можно менять здесь безопасно:
  • ``enabled=False`` — скрыть пункт из меню;
  • порядок элементов в списках ``items`` — порядок в меню;
  • ``MAIN_MENU_ORDER`` — порядок разделов главного меню;
  • ``label`` / ``description`` / ``icon`` — подписи.

Что менять нельзя: значения ``key`` — по ним ``main.py`` понимает, какой
модуль запускать.
"""

from __future__ import annotations

from typing import List

# Модель и отрисовка пунктов — общие для всего проекта.
from modules.ui.menu_model import (  # noqa: F401  (реэкспорт публичного API)
    BACK_KEY, MenuItem, SubMenu, label_column_width, render_items,
)

__all__ = [
    "MenuItem", "SubMenu", "BACK_KEY",
    "MAIN_MENU_CONFIG", "MAIN_MENU_ORDER", "MENU_ITEMS",
    "BALANCES_SUBMENU", "ETH_BALANCES_SUBMENU", "SOL_BALANCES_SUBMENU",
    "TRANSACTIONS_SUBMENU", "COLLECTORS_SUBMENU",
    "TWITTER_SUBMENU", "PROJECTS_SUBMENU",
    "CEX_SUBMENU", "OKX_SUBMENU", "BINANCE_SUBMENU", "BITGET_SUBMENU",
    "MEXC_SUBMENU", "TOOLS_SUBMENU", "GENERATE_WALLETS_SUBMENU",
    "ETH_WALLETS_SUBMENU", "SOL_WALLETS_SUBMENU", "CONVERT_TOOL_SUBMENU",
    "DISCORD_OS_SUBMENU", "RUST_IMPL_SUBMENU", "WALLET_COUNT_OPTIONS",
    "get_enabled_main_menu_items",
    "all_submenus",
]

def _back() -> MenuItem:
    """Отдельный объект на каждое меню — чтобы правки одного не влияли на другие."""
    return MenuItem(key=BACK_KEY, label="Назад", description="", icon="←")


# =============================================================================
# ГЛАВНОЕ МЕНЮ
# =============================================================================

MAIN_MENU_CONFIG = {
    "title": "Что делаем?",
    "qmark": "",
    "pointer": "",
}

# Порядок разделов главного меню — меняйте местами как удобно.
MAIN_MENU_ORDER = [
    "check_balances",
    "transactions",
    "twitter",
    "projects_menu",
    "CEX_menu",
    "miscellaneous",
    "backup_menu",
    "info",
    "exit",
]

MENU_ITEMS = {
    "check_balances": MenuItem(
        key="check_balances", label="Balances", icon="💰",
        description="Нативные токены, ERC-20, DeFi-позиции",
    ),
    "transactions": MenuItem(
        key="transactions", label="Transactions", icon="🚀",
        description="Переводы между кошельками, сборщики, мосты",
    ),
    "twitter": MenuItem(
        key="twitter", label="Twitter", icon="🐦",
        description="Проверка аккаунтов и выполнение заданий",
    ),
    "projects_menu": MenuItem(
        key="projects_menu", label="Projects", icon="🎮",
        description="Автоматизация активностей в проектах",
    ),
    "CEX_menu": MenuItem(
        key="CEX_menu", label="CEX", icon="🏦",
        description="Вывод средств, балансы, субаккаунты",
    ),
    "miscellaneous": MenuItem(
        key="miscellaneous", label="Tools", icon="🧰",
        description="Генераторы, конвертеры, чекеры",
    ),
    "backup_menu": MenuItem(
        key="backup_menu", label="Backup", icon="💾",
        description="Локальные и SFTP бэкапы, live-синхронизация",
    ),
    "info": MenuItem(
        key="info", label="Info", icon="📖",
        description="Справка по всем пунктам меню",
    ),
    "exit": MenuItem(
        key="exit", label="Exit", icon="❌",
        description="Выход из программы",
    ),

    # ── Отключено: включите enabled=True, когда функционал будет готов ──
    "selenium_profile": MenuItem(
        key="selenium_profile", label="Selenium Profile", icon="🔍",
        description="Управление профилями браузера",
        enabled=False, is_wip=True,
    ),
    "faucets": MenuItem(
        key="faucets", label="Faucets", icon="🚰",
        description="Тестовые краны",
        enabled=False, is_wip=True,
    ),
}

# =============================================================================
# BALANCES
# =============================================================================

BALANCES_SUBMENU = SubMenu(
    key="check_balances", label="Balances", icon="💰",
    description="Где смотрим балансы",
    items=[
        MenuItem(key="ETH", label="EVM-сети", icon="Ξ",
                 description="Ethereum и совместимые сети"),
        MenuItem(key="SOL", label="Solana", icon="◎",
                 description="Нативный SOL и SPL-токены"),
        MenuItem(key="Eclipse", label="Eclipse", icon="🌘",
                 description="Балансы в сети Eclipse"),
        MenuItem(key="debank_checker", label="DeBank Checker", icon="🏦",
                 description="Все токены во всех сетях через DeBank"),
        MenuItem(key="debank_protocols", label="DeBank Protocols", icon="🔗",
                 description="DeFi-позиции: стейкинг, лендинг, LP"),
        MenuItem(key="zksync_lite", label="zkSync Lite", icon="🟪",
                 description="Балансы на lite.zksync.io"),
        _back(),
    ],
)

ETH_BALANCES_SUBMENU = SubMenu(
    key="eth_balances", label="EVM-сети", icon="Ξ",
    description="Что проверяем",
    items=[
        MenuItem(key="check_wallet_balances_eth", label="Балансы кошельков",
                 icon="💰", description="Нативный токен выбранной сети"),
        MenuItem(key="check_token_balances", label="Балансы токенов",
                 icon="💎", description="ERC-20 из config/token_address_erc20.py"),
        _back(),
    ],
)

SOL_BALANCES_SUBMENU = SubMenu(
    key="sol_balances", label="Solana", icon="◎",
    description="Что проверяем",
    items=[
        MenuItem(key="check_wallet_balances_sol", label="Балансы кошельков",
                 icon="💰", description="Нативный SOL"),
        MenuItem(key="check_token_balances_sol", label="Балансы токенов",
                 icon="💎", description="SPL-токены", is_wip=True),
        _back(),
    ],
)

# =============================================================================
# TRANSACTIONS
# =============================================================================

TRANSACTIONS_SUBMENU = SubMenu(
    key="transactions", label="Transactions", icon="🚀",
    description="Что отправляем",
    items=[
        MenuItem(key="collectors", label="Collectors", icon="🧹",
                 description="Собрать балансы на главный кошелёк"),
        MenuItem(key="transfer_wallets_to_wallets_call",
                 label="Перевод нативных токенов", icon="🔄",
                 description="Между кошельками из data/data.csv"),
        MenuItem(key="transfer_erc20_tokens_call",
                 label="Перевод ERC-20", icon="💎",
                 description="Токены между кошельками"),
        MenuItem(key="transfer_kava_to_cex_call",
                 label="KAVA → биржа", icon="🌊",
                 description="Нативный KAVA на CEX (kava1 bech32 → 0x)"),
        MenuItem(key="relay_bridge", label="Relay Bridge", icon="🌉",
                 description="Мост между сетями через Relay Link"),
        _back(),
    ],
)

COLLECTORS_SUBMENU = SubMenu(
    key="collectors", label="Collectors", icon="🧹",
    description="Откуда собираем",
    items=[
        MenuItem(key="eth_collectors", label="EVM-сети", icon="Ξ",
                 description="Собрать нативные токены и ERC-20"),
        MenuItem(key="sol_collectors", label="Solana", icon="◎",
                 description="Собрать SOL", is_wip=True),
        _back(),
    ],
)

# =============================================================================
# TWITTER
# =============================================================================

TWITTER_SUBMENU = SubMenu(
    key="twitter", label="Twitter", icon="🐦",
    description="Что делаем с аккаунтами",
    items=[
        # Раньше здесь было два пункта — «Check» и «Info», — но оба вызывали
        # одну и ту же функцию. Оставлен один.
        MenuItem(key="twitter_check", label="Проверка аккаунтов", icon="🔍",
                 description="Валидность токенов, статус, подписчики, био"),
        MenuItem(key="twitter_task", label="Выполнение заданий", icon="✅",
                 description="Лайки, репосты, комментарии с прогрессом в БД"),
        _back(),
    ],
)

# =============================================================================
# PROJECTS
# =============================================================================

PROJECTS_SUBMENU = SubMenu(
    key="projects_menu", label="Projects", icon="🎮",
    description="Выберите проект",
    items=[
        MenuItem(key="xstocks", label="xStocks DeFi", icon="📈",
                 description="Регистрация, GM, рефералы, поинты",
                 badge="ПАУЗА", badge_style="warn"),
        MenuItem(key="neura_stat", label="Neura", icon="🧠",
                 description="Статистика по аккаунтам",
                 requires_os="windows"),
        MenuItem(key="dune", label="Dune Analytics", icon="📊",
                 description="Проверка кошельков по дашбордам Dune"),
        MenuItem(key="fhenix", label="Fhenix", icon="🔐",
                 description="Краны ghostchain и Alchemy (Sepolia)"),
        MenuItem(key="litvm_testnet", label="LiteForge Testnet", icon="⚒️",
                 description="Кран zkLTC, мост, свапы, NFT, домены"),
        MenuItem(key="sahara", label="Sahara AI", icon="🏜️",
                 description="Клейм Knowledge Drop и вывод на биржу"),
        MenuItem(key="safepal_x1", label="SafePal X1", icon="🔑",
                 description="Проверка права на клейм аппаратного кошелька"),
        _back(),
    ],
)

# =============================================================================
# CEX
# =============================================================================

CEX_SUBMENU = SubMenu(
    key="CEX_menu", label="CEX", icon="🏦",
    description="Выберите биржу",
    items=[
        MenuItem(key="OKX", label="OKX", icon="⬛",
                 description="Вывод, балансы, субаккаунты, спот"),
        MenuItem(key="Binance", label="Binance", icon="🟨",
                 description="Вывод, балансы, субаккаунты"),
        MenuItem(key="Bitget", label="Bitget", icon="🟦",
                 description="Вывод, субаккаунты"),
        MenuItem(key="MEXC", label="MEXC", icon="🟩",
                 description="Вывод средств"),
        _back(),
    ],
)

OKX_SUBMENU = SubMenu(
    key="OKX", label="OKX", icon="⬛",
    description="Что делаем",
    items=[
        MenuItem(key="withdraw_from_okx", label="Вывод средств", icon="📤",
                 description="На адреса из data/data.csv"),
        MenuItem(key="get_balances_okx", label="Балансы", icon="💰",
                 description="Основной аккаунт"),
        MenuItem(key="subaccount_collector_okx", label="Сбор с субаккаунтов",
                 icon="🧹", description="Перевод на основной аккаунт"),
        MenuItem(key="spot_trade_okx", label="Спотовая торговля", icon="📈",
                 description="Автоматические сделки по конфигу"),
        _back(),
    ],
)

BINANCE_SUBMENU = SubMenu(
    key="Binance", label="Binance", icon="🟨",
    description="Что делаем",
    items=[
        MenuItem(key="withdraw_from_binance", label="Вывод средств", icon="📤",
                 description="На адреса из data/data.csv"),
        MenuItem(key="get_balances_binance", label="Балансы", icon="💰",
                 description="Основной аккаунт и субаккаунты"),
        MenuItem(key="subaccount_collector_binance", label="Сбор с субаккаунтов",
                 icon="🧹", description="Перевод на основной аккаунт"),
        _back(),
    ],
)

BITGET_SUBMENU = SubMenu(
    key="Bitget", label="Bitget", icon="🟦",
    description="Что делаем",
    items=[
        MenuItem(key="withdraw_from_bitget", label="Вывод средств", icon="📤",
                 description="На адреса из data/data.csv"),
        MenuItem(key="get_balances_bitget", label="Балансы", icon="💰",
                 description="Основной аккаунт", is_wip=True),
        MenuItem(key="subaccount_collector_bitget", label="Сбор с субаккаунтов",
                 icon="🧹", description="Перевод на основной аккаунт"),
        _back(),
    ],
)

MEXC_SUBMENU = SubMenu(
    key="MEXC", label="MEXC", icon="🟩",
    description="Что делаем",
    items=[
        MenuItem(key="withdraw_from_mexc", label="Вывод средств", icon="📤",
                 description="На адреса из data/data.csv"),
        _back(),
    ],
)

# =============================================================================
# TOOLS
# =============================================================================

TOOLS_SUBMENU = SubMenu(
    key="miscellaneous", label="Tools", icon="🧰",
    description="Выберите инструмент",
    items=[
        MenuItem(key="generate_wallets", label="Генерация кошельков", icon="🪙",
                 description="EVM и Solana, включая красивые адреса"),
        MenuItem(key="ETH_convert_tool", label="Конвертер ключей", icon="🔀",
                 description="Мнемоника ↔ приватный ключ ↔ адрес"),
        MenuItem(key="password_generator", label="Генератор паролей", icon="🔑",
                 description="Параметры в config/modules/cfg_password.py"),
        MenuItem(key="nickname_generator", label="Генератор никнеймов", icon="🎭",
                 description="Правдоподобные ники под регистрации"),
        MenuItem(key="fullname_generator", label="Генератор имён", icon="👤",
                 description="Имена и фамилии: RU / UA / ENG"),
        MenuItem(key="check_proxy", label="Проверка прокси", icon="🛰️",
                 description="Доступность, скорость, геолокация"),
        MenuItem(key="check_age_discord", label="Возраст Discord", icon="🗂️",
                 description="Дата регистрации аккаунтов по токенам"),
        MenuItem(key="email_checker", label="Проверка почт", icon="📧",
                 description="Валидация ящиков по IMAP"),
        MenuItem(key="pinterest_downloader", label="Загрузка с Pinterest",
                 icon="📌", description="Случайные картинки под аватарки"),
        MenuItem(key="swap_all_polygon_zkevm_to_base",
                 label="Polygon zkEVM → Base", icon="💱",
                 description="Все токены в USDC через Layerswap"),
        MenuItem(key="swap_all_zksync_era_to_base",
                 label="zkSync Era → Base", icon="💱",
                 description="USDC/USDT в USDC через Rhino.fi"),
        _back(),
    ],
)

GENERATE_WALLETS_SUBMENU = SubMenu(
    key="generate_wallets", label="Генерация кошельков", icon="🪙",
    description="Какие кошельки генерируем",
    items=[
        MenuItem(key="eth_wallets", label="EVM-кошельки", icon="Ξ",
                 description="Приватный ключ, адрес, мнемоника"),
        MenuItem(key="sol_wallets", label="Solana-кошельки", icon="◎",
                 description="Приватный ключ и адрес"),
        _back(),
    ],
)

ETH_WALLETS_SUBMENU = SubMenu(
    key="eth_wallets", label="EVM-кошельки", icon="Ξ",
    description="Тип генерации",
    items=[
        MenuItem(key="generate", label="Обычная генерация", icon="🪙",
                 description="Быстро, адреса случайные"),
        MenuItem(key="nice_generate", label="Красивые адреса", icon="✨",
                 description="Подбор по маске из config/modules/cfg_nice_address.py"),
        _back(),
    ],
)

SOL_WALLETS_SUBMENU = SubMenu(
    key="sol_wallets", label="Solana-кошельки", icon="◎",
    description="Тип генерации",
    items=[
        MenuItem(key="generate", label="Обычная генерация", icon="🪙",
                 description="Быстро, адреса случайные"),
        MenuItem(key="nice_generate", label="Красивые адреса", icon="✨",
                 description="Подбор по маске из config/modules/cfg_nice_address.py"),
        _back(),
    ],
)

CONVERT_TOOL_SUBMENU = SubMenu(
    key="ETH_convert_tool", label="Конвертер ключей", icon="🔀",
    description="Что во что переводим",
    items=[
        MenuItem(key="eth_mnemonic_to_privkey", label="EVM: мнемоника → ключ",
                 icon="Ξ", description="BIP-39 / BIP-44"),
        MenuItem(key="eth_privkey_to_wallet", label="EVM: ключ → адрес",
                 icon="Ξ", description="Массовое преобразование"),
        MenuItem(key="sol_mnemonic_to_privkey", label="Solana: мнемоника → ключ",
                 icon="◎", description="Массовое преобразование"),
        _back(),
    ],
)

DISCORD_OS_SUBMENU = SubMenu(
    key="check_age_discord", label="Возраст Discord", icon="🗂️",
    description="Ваша операционная система",
    items=[
        MenuItem(key="windows", label="Windows", icon="🪟", description=""),
        MenuItem(key="macos", label="macOS", icon="🍎", description=""),
        MenuItem(key="linux", label="Linux", icon="🐧", description=""),
        _back(),
    ],
)

RUST_IMPL_SUBMENU = SubMenu(
    key="rust_impl", label="Реализация генератора", icon="⚙️",
    description="Чем подбирать адреса",
    items=[
        MenuItem(key="python", label="Python", icon="🐍",
                 description="Медленнее, работает без дополнительных программ"),
        MenuItem(key="rust", label="Rust", icon="🦀",
                 description="В 10–100 раз быстрее, требуется Cargo"),
        _back(),
    ],
)

# Количество кошельков — общий выбор для генераторов.
WALLET_COUNT_OPTIONS = [
    {"value": 1, "label": "1"},
    {"value": 10, "label": "10"},
    {"value": 100, "label": "100"},
    {"value": 1000, "label": "1 000"},
    {"value": 5000, "label": "5 000"},
    {"value": 10000, "label": "10 000"},
    {"value": "manual", "label": "Ввести вручную"},
    {"value": BACK_KEY, "label": "Назад"},
]


# =============================================================================
# УТИЛИТЫ
# =============================================================================

def all_submenus() -> List[SubMenu]:
    """Все объявленные здесь подменю — используется тестами и справкой."""
    return [value for value in globals().values() if isinstance(value, SubMenu)]


def get_enabled_main_menu_items() -> List[MenuItem]:
    """Пункты главного меню в порядке ``MAIN_MENU_ORDER``."""
    return [
        MENU_ITEMS[key]
        for key in MAIN_MENU_ORDER
        if key in MENU_ITEMS and MENU_ITEMS[key].enabled
    ]

