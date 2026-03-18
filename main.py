import os
import time
import json
import csv
import platform
import sys

# Проверка зависимостей (только stdlib — работает на чистом Python)
from modules.requirements_checker import check_requirements
if not check_requirements():
    input("\nНажмите Enter для выхода...")
    sys.exit(1)

# Импортируем центральный логгер ПЕРВЫМ - он настраивает все цвета
from modules.simple_logger import logger

from colorama import Fore, Style, init
init(autoreset=True)

from questionary import Choice, select

from config.networks import get_mainnet_networks, get_testnet_networks
from config.modules.cfg_backup import DISPLAY_LIST_BACKUPS
from config.menu_config import (
    MAIN_MENU_CONFIG, MENU_ITEMS, 
    get_enabled_main_menu_items, build_choices, build_submenu_choices,
    BALANCES_SUBMENU, ETH_BALANCES_SUBMENU, SOL_BALANCES_SUBMENU,
    TRANSACTIONS_SUBMENU, DRAINERS_SUBMENU,
    CLAIMER_SUBMENU,
    TWITTER_SUBMENU, PROJECTS_SUBMENU,
    CEX_SUBMENU, OKX_SUBMENU, BINANCE_SUBMENU, BITGET_SUBMENU, MEXC_SUBMENU,
    TOOLS_SUBMENU, GENERATE_WALLETS_SUBMENU, ETH_WALLETS_SUBMENU, SOL_WALLETS_SUBMENU,
    CONVERT_TOOL_SUBMENU, DISCORD_OS_SUBMENU, RUST_IMPL_SUBMENU,
    PROJECT_STATS_SUBMENU, WALLET_COUNT_OPTIONS,
)

from modules.backup import create_backup, list_backups, backup_menu
from modules.backup.backup_manager import BackupManager

neura_statistics = None
neura_load_error = None
if platform.system().lower() == 'windows':
    try:
        from modules.statistics.neura_stats import neura_statistics
    except ImportError as e:
        neura_load_error = str(e)
        print(Fore.YELLOW + f"⚠️  Не удалось загрузить модуль Neura Statistics: {neura_load_error}")
        neura_statistics = None
    except Exception as e:
        neura_load_error = str(e)
        print(Fore.YELLOW + f"⚠️  Не удалось загрузить модуль Neura Statistics: {e}")
        neura_statistics = None

# =============================================================================
# ИМПОРТЫ ФУНКЦИОНАЛЬНЫХ МОДУЛЕЙ
# =============================================================================

from modules.config_validator import validate_configuration
from modules.data_manager import select_data_file
from modules.info import info
from modules.eth.eth_get_balaces import check_wallet_balances_menu
from modules.eth.eth_get_token_balance import check_token_balance_menu
from modules.password_generator import password_generator_menu
from modules.get_gas_price import check_all_gas_prices

from modules.twitter.twitter_check import run_twitter_check
from modules.twitter.twitter_task_runner import run_twitter_tasks
from modules.discord.discord_age import check_discord_accounts
from modules.email.email_imap_checker import run_email_checker

from modules.cex.okx.okx_SubAccount import check_okx_subaccounts_and_balances, get_balances_okx
from modules.cex.okx.okx_withdraw import okx_withdraw
from modules.cex.okx.okx_SpotTrade import start_okx_spot_trading
from modules.cex.binance.binance_withdraw import binance_withdraw
from modules.cex.binance.binance_SubAccount import get_balances_binance, subaccount_collector_binance
from modules.cex.bitget.bitget_SubAccount import check_bitget_subaccounts_and_balances
from modules.cex.bitget.bitget_withdraw import bitget_withdraw
from modules.cex.mexc.mexc_withdraw import mexc_withdraw
from modules.GitHub.check_version import check_version

from modules.check_proxy import check_proxy_menu
from modules.eth.eth_wallet_generator import eth_generate_wallets
from modules.eth.eth_nice_address.python.eth_nice_address import eth_generate_nice_wallets
from modules.eth.eth_nice_address.eth_nice_address_rust_wrapper import run_rust_generator, check_cargo_installed
from modules.eth.eth_mnemonic_to_privkey import process_mnemonics
from modules.eth.eth_private_key_to_wallet_address import process_private_keys
from modules.eth.eth_drainers import eth_drainers
from modules.eth.eth_last_tx import check_last_transactions
from modules.relay_link.relay_link import main as relay_bridge_main

from modules.sol.sol_wallet_generator import sol_generate_wallets
from modules.sol.sol_nice_address import sol_generate_nice_wallets
from modules.sol.sol_mnemonic_to_privkey import sol_process_mnemonics
from modules.sol.eclipse_get_balances import eclipse_balance_checker
from modules.sol.sol_get_balances import solana_balance_checker

from modules.debank.debank_checker import debank_checker_menu
from modules.debank.debank_protocol_checker import debank_protocol_menu
from modules.neura.menu import neura_menu
from modules.pharos.menu import pharos_menu
from modules.eth.transfer_wallets_to_wallets import run_transfer
from modules.claim.zora_claimer.menu import claimer_menu

mainnet_rpc_urls = get_mainnet_networks()
testnet_rpc_urls = get_testnet_networks()


# =============================================================================
# УТИЛИТЫ
# =============================================================================

def get_os_type() -> str:
    """Определяет тип операционной системы"""
    system = platform.system().lower()
    if system == 'windows':
        return 'windows'
    elif system == 'darwin':
        return 'macos'
    else:
        return 'linux'


def check_and_create_files():
    """Проверяет и создает необходимые файлы и директории"""
    required_files = [
        'result/result.csv',
        'config/cex_settings.py',
        'data/transfer_token.csv',
        'data/twitter/twitters.csv',
        'data/twitter/twitter_task.csv',
        'result/twitter/result.csv',
    ]
    required_directories = [
        'result',
        'data',
        'db',
        'result/twitter',
        'data/twitter',
        'backups',
        'log',
        'result/discord',
        'result/email'
    ]

    for directory in required_directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(Fore.GREEN + f"Directory created: {directory}")

    for file in required_files:
        if not os.path.exists(file):
            with open(file, 'w', encoding='utf-8') as f:
                _write_default_file_content(f, file)
            print(Fore.GREEN + f"File created: {file}")

    # Автосоздание data/data.csv с заголовками
    from modules.data_manager import _ensure_data_file
    _ensure_data_file()


def _write_default_file_content(f, file_path: str):
    """Записывает содержимое по умолчанию для файла"""
    if 'result.csv' in file_path:
        f.write('address,balance,network\n')
    elif 'transaction_count_result.csv' in file_path:
        f.write('address,transaction_count,network\n')
    elif 'cex_settings.py' in file_path:
        f.write(_get_default_cex_settings())
    elif 'transfer_token.csv' in file_path:
        f.write('from_wallet,to_wallet,amount\n')
    elif 'data/twitter/twitters.csv' in file_path:
        f.write('nickname,auth_token,ct0,proxy\n')
    elif 'data/twitter/twitter_task.csv' in file_path:
        f.write('link,type,value\n')


def _get_default_cex_settings() -> str:
    """Возвращает содержимое по умолчанию для cex_settings.py"""
    return '''# Конфигурация для множественных аккаунтов бирж
# Для каждой биржи можно настроить несколько аккаунтов

# OKX Configuration
# https://www.okx.com/ru/account/my-api
OKX_EU_TYPE = 0  # включите это, если депозиты приходят на Трейдинг аккаунт, вместо Спотового аккаунта

OKX_ACCOUNTS = [
    {
        'name': 'OKX Main',
        'api_key': '',
        'api_secret': '',
        'passphrase': '',
        'type': OKX_EU_TYPE,
        'enabled': False,
    },
]

# Binance Configuration
# https://www.binance.com/en/my/settings/api-management
BINANCE_ACCOUNTS = [
    {
        'name': 'Binance Main',
        'api_key': '',
        'api_secret': '',
        'enabled': False,
    },
]

# Bitget Configuration
# https://www.bitget.com/ru/support/articles/360033773814
BITGET_ACCOUNTS = [
    {
        'name': 'Bitget Main',
        'api_key': '',
        'api_secret': '',
        'passphrase': '',
        'enabled': False,
    },
]

# MEXC Configuration
# https://www.mexc.com/ru-RU/user/openapi
MEXC_ACCOUNTS = [
    {
        'name': 'MEXC Main',
        'api_key': '',
        'api_secret': '',
        'enabled': False,
    },
]
'''


def show_menu(title: str, choices: list, qmark: str = '🛠️', pointer: str = '👉'):
    """Отображает меню и возвращает выбор пользователя"""
    return select(title, choices=choices, qmark=qmark, pointer=pointer).ask()


def show_wip_message(feature_name: str = "Функционал"):
    """Показывает сообщение о функционале в разработке"""
    print(Fore.RED + f"\n\t{feature_name} в разработке, скоро будет доступен!\n")
    time.sleep(2)


def show_exit_animation():
    """Показывает анимацию выхода"""
    animation = ["👋", "👋🙂", "👋🙂🚀", "👋🙂🚀💸", "👋🙂🚀💸✨", "👋🙂🚀💸✨🦾", "👋🙂🚀💸✨🦾\n"]
    for frame in animation:
        print(Fore.GREEN + f"\r{frame}", end='', flush=True)
        time.sleep(0.1)
    print(Fore.GREEN + "\n\t❤️‍🔥 Спасибо за использование ETHmachine!")
    print(Fore.GREEN + "\t❤️‍🔥 Если есть вопросы и предложения то в тг https://t.me/DenisHumen")
    print(Fore.GREEN + "\t❤️‍🔥 GitHub 🌟 - https://github.com/DenisHumen\n\n")


def print_welcome_message():
    """Выводит приветственное сообщение"""
    print(
        Fore.GREEN + "\nWelcome to ETHmachine! 🌟 \n ERC20  🌟 - "
        + Fore.MAGENTA + "0xa24fbbd57720ec580395aedba3ad37f6a6067727"
        + Fore.GREEN + " \n TG     🌟 - "
        + Fore.MAGENTA + "https://t.me/DenisHumen"
        + Fore.GREEN + " \n GitHub 🌟 - "
        + Fore.MAGENTA + "https://github.com/DenisHumen"
        + Fore.GREEN + "\n Steam  🌟 - "
        + Fore.MAGENTA + "https://steamcommunity.com/id/Krokosha/"
        + Fore.GREEN + "\n\n"
    )


# =============================================================================
# ОБРАБОТЧИКИ МЕНЮ
# =============================================================================

class MenuHandlers:
    """Класс с обработчиками всех пунктов меню"""
    
    # -------------------------------------------------------------------------
    # BALANCES
    # -------------------------------------------------------------------------
    
    @staticmethod
    def handle_check_balances():
        """Обработчик меню балансов"""
        blockchain = show_menu(
            "Выберите блокчейн:",
            build_submenu_choices(BALANCES_SUBMENU)
        )
        
        if blockchain == 'back':
            return
        
        if blockchain == 'ETH':
            MenuHandlers._handle_eth_balances()
        elif blockchain == 'SOL':
            MenuHandlers._handle_sol_balances()
        elif blockchain == 'Eclipse':
            eclipse_balance_checker()
        elif blockchain == 'debank_checker':
            debank_checker_menu()
        elif blockchain == 'debank_protocols':
            debank_protocol_menu()
    
    @staticmethod
    def _handle_eth_balances():
        """Обработчик балансов ETH"""
        choice = show_menu(
            "Выберите действие для ETH:",
            build_submenu_choices(ETH_BALANCES_SUBMENU)
        )
        
        match choice:
            case 'check_wallet_balances_eth':
                check_wallet_balances_menu()
            case 'check_token_balances':
                check_token_balance_menu()
    
    @staticmethod
    def _handle_sol_balances():
        """Обработчик балансов SOL"""
        choice = show_menu(
            "Выберите действие для SOL:",
            build_submenu_choices(SOL_BALANCES_SUBMENU)
        )
        
        match choice:
            case 'check_wallet_balances_sol':
                solana_balance_checker()
            case 'check_token_balances_sol':
                show_wip_message("Функционал проверки токенов SOL")
    
    # -------------------------------------------------------------------------
    # TRANSACTIONS
    # -------------------------------------------------------------------------
    
    @staticmethod
    def handle_transactions():
        """Обработчик меню транзакций"""
        choice = show_menu(
            "Выберите действие:",
            build_submenu_choices(TRANSACTIONS_SUBMENU)
        )
        
        match choice:
            case 'drainers':
                MenuHandlers._handle_drainers()
            case 'transfer_wallets_to_wallets_call':
                MenuHandlers._handle_transfer_wallets()
            case 'transfer_erc20_tokens_call':
                from modules.eth.transfer_erc20_tokens import run_transfer_erc20_tokens
                run_transfer_erc20_tokens()
            case 'relay_bridge':
                relay_bridge_main()
    
    @staticmethod
    def _handle_drainers():
        """Обработчик drainers"""
        choice = show_menu(
            "Выберите действие:",
            build_submenu_choices(DRAINERS_SUBMENU)
        )
        
        match choice:
            case 'eth_drainers':
                eth_drainers()
            case 'sol_drainers':
                show_wip_message("Функционал SOL Drainers")
    
    @staticmethod
    def _handle_transfer_wallets():
        """Обработчик перевода между кошельками"""
        print(Fore.GREEN + f"\n\nФормат данных для data/transfer_token.csv: from_wallet,to_wallet,amount")
        print(Fore.YELLOW + f"from_wallet — приватный ключ отправителя")
        print(Fore.YELLOW + f"to_wallet — адрес или приватный ключ получателя (определяется автоматически)")
        print(Fore.YELLOW + f"amount — '90-100' или '90-100%' для процентов, 0.1-0.2 для суммы в нативном токене\n")

        network_type = show_menu(
            "Select network type:",
            [
                Choice('🌐 Mainnet', 'mainnet'),
                Choice('🔧 Testnet', 'testnet'),
                Choice('🔙 Back', 'back')
            ]
        )

        if network_type == 'back':
            return

        network_choices = list(mainnet_rpc_urls.keys()) if network_type == 'mainnet' else list(testnet_rpc_urls.keys())
        network = show_menu(
            "Which network do you want to use for transfer?",
            [Choice(n, n) for n in network_choices] + [Choice('🔙 Back', 'back')]
        )

        if network == 'back':
            return

        transfer_data = MenuHandlers._load_transfer_data()
        if not transfer_data:
            return

        run_transfer(transfer_data, network)
    
    @staticmethod
    def _load_transfer_data() -> list:
        """Загружает данные для перевода"""
        transfer_data = []
        try:
            with open('data/transfer_token.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('from_wallet') and row.get('to_wallet') and row.get('amount'):
                        transfer_data.append(row)
        except Exception as e:
            print(Fore.RED + f"Ошибка чтения data/transfer_token.csv: {e}")
            return []

        if not transfer_data:
            print(Fore.RED + "Нет данных для отправки в data/transfer_token.csv.")

        return transfer_data
    
    # -------------------------------------------------------------------------
    # CLAIMER
    # -------------------------------------------------------------------------

    @staticmethod
    def handle_claimer():
        """Обработчик меню клеймера"""
        choice = show_menu(
            "Выберите проект для клейма:",
            build_submenu_choices(CLAIMER_SUBMENU)
        )

        if choice == 'zora_claimer':
            claimer_menu()

    # -------------------------------------------------------------------------
    # TWITTER
    # -------------------------------------------------------------------------

    @staticmethod
    def handle_twitter():
        """Обработчик меню Twitter"""
        choice = show_menu(
            "Выберите действие с Twitter:",
            build_submenu_choices(TWITTER_SUBMENU)
        )
        
        match choice:
            case 'twitter_check':
                run_twitter_check(get_os_type())
            case 'twitter_info':
                run_twitter_check(get_os_type())
            case 'twitter_task':
                run_twitter_tasks()
    
    # -------------------------------------------------------------------------
    # PROJECTS
    # -------------------------------------------------------------------------
    
    @staticmethod
    def handle_projects():
        """Обработчик меню проектов"""
        choice = show_menu(
            "🎮 Выберите проект для автоматизации:",
            build_submenu_choices(PROJECTS_SUBMENU),
            qmark='🎮'
        )
        
        if choice == 'neura':
            neura_menu()
        elif choice == 'pharos':
            pharos_menu()
    
    @staticmethod
    def handle_project_stats():
        """Обработчик статистики проектов"""
        while True:
            stats_choices = []
            if neura_statistics is not None:
                stats_choices.append(Choice('📊 Neura         🌟 Статистика по ETHmachine', 'neura_stat'))
            else:
                current_os = get_os_type()
                stats_choices.append(Choice(f'📊 Neura         ⚠️  Доступно только на Windows (текущая ОС: {current_os})', 'neura_stat_unavailable'))
            
            stats_choices.append(Choice('🔙 Back', 'back'))
            
            action = show_menu("Выберите действие (статистика по проектам):", stats_choices)
            
            match action:
                case 'neura_stat':
                    if neura_statistics is not None:
                        neura_statistics()
                    else:
                        MenuHandlers._show_neura_unavailable()
                case 'neura_stat_unavailable':
                    MenuHandlers._show_neura_unavailable()
                case 'back':
                    break
    
    @staticmethod
    def _show_neura_unavailable():
        """Показывает сообщение о недоступности Neura Statistics"""
        print(Fore.RED + "\n⚠️  Модуль Neura Statistics недоступен!")
        if neura_load_error:
            print(Fore.YELLOW + f"Причина: {neura_load_error}")
        else:
            print(Fore.YELLOW + "Этот модуль работает только на Windows из-за зависимости от pyarmor_runtime.pyd")
        print(Fore.YELLOW + f"Ваша текущая ОС: {get_os_type()}, Python: {platform.python_version()}")
        input("\nНажмите Enter для продолжения...")
    
    # -------------------------------------------------------------------------
    # CEX
    # -------------------------------------------------------------------------
    
    @staticmethod
    def handle_cex():
        """Обработчик меню CEX"""
        exchange = show_menu(
            "Выберите биржу:",
            build_submenu_choices(CEX_SUBMENU)
        )
        
        match exchange:
            case 'OKX':
                MenuHandlers._handle_okx()
            case 'Binance':
                MenuHandlers._handle_binance()
            case 'Bitget':
                MenuHandlers._handle_bitget()
            case 'MEXC':
                MenuHandlers._handle_mexc()
    
    @staticmethod
    def _handle_okx():
        """Обработчик OKX"""
        action = show_menu(
            "Выберите действие:",
            build_submenu_choices(OKX_SUBMENU)
        )
        
        match action:
            case 'withdraw_from_okx':
                okx_withdraw()
            case 'get_balances_okx':
                get_balances_okx()
            case 'subaccount_collector_okx':
                check_okx_subaccounts_and_balances()
            case 'spot_trade_okx':
                start_okx_spot_trading()
    
    @staticmethod
    def _handle_binance():
        """Обработчик Binance"""
        action = show_menu(
            "Выберите действие:",
            build_submenu_choices(BINANCE_SUBMENU)
        )
        
        match action:
            case 'withdraw_from_binance':
                binance_withdraw()
            case 'get_balances_binance':
                print(Fore.GREEN + "\n\tФункционал Binance в разработке, скоро будет доступен\n")
                get_balances_binance()
            case 'subaccount_collector_binance':
                print(Fore.GREEN + "\n\tФункционал Binance в разработке, скоро будет доступен\n")
                subaccount_collector_binance()
    
    @staticmethod
    def _handle_bitget():
        """Обработчик Bitget"""
        action = show_menu(
            "Выберите действие:",
            build_submenu_choices(BITGET_SUBMENU)
        )
        
        match action:
            case 'withdraw_from_bitget':
                bitget_withdraw()
            case 'get_balances_bitget':
                show_wip_message("Функционал Bitget")
            case 'subaccount_collector_bitget':
                check_bitget_subaccounts_and_balances()
    
    @staticmethod
    def _handle_mexc():
        """Обработчик MEXC"""
        action = show_menu(
            "Выберите действие:",
            build_submenu_choices(MEXC_SUBMENU)
        )
        
        if action == 'withdraw_from_mexc':
            mexc_withdraw()
    
    # -------------------------------------------------------------------------
    # TOOLS (MISCELLANEOUS)
    # -------------------------------------------------------------------------
    
    @staticmethod
    def handle_tools():
        """Обработчик меню инструментов"""
        choice = show_menu(
            "Выберите действие:",
            build_submenu_choices(TOOLS_SUBMENU)
        )
        
        match choice:
            case 'check_gas_price':
                check_all_gas_prices()
            case 'generate_wallets':
                MenuHandlers._handle_generate_wallets()
            case 'ETH_convert_tool':
                MenuHandlers._handle_convert_tool()
            case 'password_generator':
                password_generator_menu()
            case 'nickname_generator':
                from modules.nickname_generator import generate_nicknames
                generate_nicknames()
            case 'fullname_generator':
                from modules.fullname_generator import generate_fullnames_menu
                generate_fullnames_menu()
            case 'check_proxy':
                check_proxy_menu()
            case 'last_transactions':
                check_last_transactions()
            case 'check_age_discord':
                MenuHandlers._handle_discord_check()
            case 'email_checker':
                run_email_checker()
    
    @staticmethod
    def _handle_generate_wallets():
        """Обработчик генерации кошельков"""
        wallet_type = show_menu(
            "Выберите тип генерации кошельков:",
            build_submenu_choices(GENERATE_WALLETS_SUBMENU),
            qmark='🪙'
        )
        
        if wallet_type == 'back':
            return
        
        num_wallets = MenuHandlers._select_wallet_count()
        if num_wallets is None or num_wallets == 'back':
            return
        
        if wallet_type == 'eth_wallets':
            MenuHandlers._generate_eth_wallets(num_wallets)
        elif wallet_type == 'sol_wallets':
            MenuHandlers._generate_sol_wallets(num_wallets)
    
    @staticmethod
    def _select_wallet_count():
        """Выбор количества кошельков"""
        choices = [
            Choice(f'▶️  {opt["label"]}' if opt["value"] not in ['manual', 'back'] else
                   f'✏️ {opt["label"]}' if opt["value"] == 'manual' else f'🔙 {opt["label"]}', 
                   opt["value"])
            for opt in WALLET_COUNT_OPTIONS
        ]
        
        num_wallets = show_menu(
            "Сколько кошельков вы хотите сгенерировать?",
            choices,
            qmark='🪙'
        )
        
        if num_wallets == 'back':
            return None
        
        if num_wallets == 'manual':
            try:
                num_wallets = int(input(Fore.YELLOW + "Введите количество кошельков для генерации: "))
                if num_wallets <= 0:
                    print(Fore.RED + "Пожалуйста, введите положительное число!")
                    return None
            except ValueError:
                print(Fore.RED + "Неверный ввод. Пожалуйста, введите правильное число.")
                return None
        
        return num_wallets
    
    @staticmethod
    def _generate_eth_wallets(num_wallets: int):
        """Генерация ETH кошельков"""
        eth_choice = show_menu(
            "Выберите тип генерации ETH кошельков:",
            build_submenu_choices(ETH_WALLETS_SUBMENU),
            qmark='⚡'
        )
        
        match eth_choice:
            case 'generate':
                eth_generate_wallets(num_wallets)
                print(Fore.GREEN + f"\nСгенерировано {num_wallets} кошельков и сохранено в result/result.csv\n")
            case 'nice_generate':
                MenuHandlers._generate_nice_eth_wallets(num_wallets)
    
    @staticmethod
    def _generate_nice_eth_wallets(num_wallets: int):
        """Генерация красивых ETH кошельков"""
        print(f"\n{Fore.CYAN}Выберите реализацию генератора:{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Python - медленно, но без зависимостей{Style.RESET_ALL}")
        print(f"{Fore.GREEN}Rust - быстро (10-100x), требует Cargo{Style.RESET_ALL}\n")
        
        impl_choice = show_menu(
            "Реализация:",
            build_submenu_choices(RUST_IMPL_SUBMENU),
            qmark='⚙️'
        )
        
        if impl_choice == 'python':
            eth_generate_nice_wallets(num_wallets)
            print(Fore.GREEN + f"\nСгенерировано {num_wallets} красивых кошельков и сохранено в result/result.csv\n")
        elif impl_choice == 'rust':
            MenuHandlers._run_rust_eth_generator(num_wallets)
    
    @staticmethod
    def _run_rust_eth_generator(num_wallets: int):
        """Запуск Rust генератора ETH кошельков"""
        if check_cargo_installed():
            print(f"\n{Fore.GREEN}✓ Cargo установлен, используем Rust версию{Style.RESET_ALL}")
            
            use_auto_threads = show_menu(
                "Использовать все доступные потоки?",
                [
                    Choice("✅ Да (рекомендуется)", 'yes'),
                    Choice("⚙️ Указать вручную", 'no')
                ],
                qmark='🔧'
            )
            
            if use_auto_threads == 'yes':
                threads = 0
            else:
                threads_input = show_menu(
                    "Количество потоков:",
                    [Choice(str(t), str(t)) for t in [2, 4, 6, 8, 12, 16]],
                    qmark='🔢'
                )
                threads = int(threads_input)
            
            run_rust_generator(
                num_wallets=num_wallets,
                config_path="config/config.py",
                output_path="result/result.csv",
                threads=threads,
                display_process=True
            )
        else:
            print(f"\n{Fore.RED}❌ Cargo не установлен!{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Используем Python версию...{Style.RESET_ALL}\n")
            eth_generate_nice_wallets(num_wallets)
            print(Fore.GREEN + f"\nСгенерировано {num_wallets} красивых кошельков и сохранено в result/result.csv\n")
    
    @staticmethod
    def _generate_sol_wallets(num_wallets: int):
        """Генерация SOL кошельков"""
        sol_choice = show_menu(
            "Выберите тип генерации SOL кошельков:",
            build_submenu_choices(SOL_WALLETS_SUBMENU),
            qmark='☀️'
        )
        
        match sol_choice:
            case 'generate':
                sol_generate_wallets(num_wallets)
                print(Fore.GREEN + f"\nСгенерировано {num_wallets} SOL кошельков и сохранено в result/result.csv\n")
            case 'nice_generate':
                sol_generate_nice_wallets(num_wallets)
                print(Fore.GREEN + f"\nСгенерировано {num_wallets} красивых SOL кошельков и сохранено в result/result.csv\n")
    
    @staticmethod
    def _handle_convert_tool():
        """Обработчик инструмента конвертации"""
        action = show_menu(
            "Выберите операцию конвертации:",
            build_submenu_choices(CONVERT_TOOL_SUBMENU)
        )
        
        match action:
            case 'eth_mnemonic_to_privkey':
                process_mnemonics()
            case 'eth_privkey_to_wallet':
                process_private_keys()
            case 'sol_mnemonic_to_privkey':
                sol_process_mnemonics()
    
    @staticmethod
    def _handle_discord_check():
        """Обработчик проверки Discord"""
        os_choice = show_menu(
            "Выберите способ проверки возраста аккаунта Discord:",
            build_submenu_choices(DISCORD_OS_SUBMENU)
        )
        
        if os_choice in ['windows', 'macos', 'linux']:
            check_discord_accounts(os_choice)


# =============================================================================
# ГЛАВНОЕ МЕНЮ
# =============================================================================

def main_menu():
    """Главное меню приложения"""
    try:
        print_welcome_message()
        
        while True:
            # Строим меню из конфигурации
            menu_items = get_enabled_main_menu_items()
            choices = build_choices(menu_items)
            
            action = show_menu(
                MAIN_MENU_CONFIG['title'],
                choices,
                qmark=MAIN_MENU_CONFIG['qmark'],
                pointer=MAIN_MENU_CONFIG['pointer']
            )
            
            # Обработка действий
            match action:
                case 'check_balances':
                    MenuHandlers.handle_check_balances()
                case 'transactions':
                    MenuHandlers.handle_transactions()
                case 'twitter':
                    MenuHandlers.handle_twitter()
                case 'project_stats':
                    MenuHandlers.handle_project_stats()
                case 'projects_menu':
                    MenuHandlers.handle_projects()
                case 'CEX_menu':
                    MenuHandlers.handle_cex()
                case 'miscellaneous':
                    MenuHandlers.handle_tools()
                case 'backup_menu':
                    backup_menu()
                case 'info':
                    info()
                case 'claimer':
                    MenuHandlers.handle_claimer()
                case 'faucets':
                    show_wip_message("Функционал Faucets")
                case 'exit':
                    show_exit_animation()
                    break
                case None:
                    # Пользователь нажал Ctrl+C
                    break
    
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n\nПрервано пользователем.")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")


# =============================================================================
# ТОЧКА ВХОДА
# =============================================================================

# Проверка и создание файлов при импорте
check_and_create_files()

if __name__ == "__main__":
    check_version("ETHmachine")
    create_backup()
    
    # Сбрасываем цвета после бэкапа
    print(Style.RESET_ALL, end='')
    
    print(Fore.CYAN + "\n🔍 Проверка конфигурации..." + Style.RESET_ALL)
    if not validate_configuration():
        print(Fore.RED + "\n❌ Обнаружены проблемы в конфигурации!" + Style.RESET_ALL)
        print(Fore.YELLOW + "Исправьте ошибки и перезапустите скрипт." + Style.RESET_ALL)
        input("\nНажмите Enter для выхода...")
        exit(1)

    # Выбор файла данных (если несколько — интерактивный выбор)
    select_data_file()
    
    # Запускаем live мониторинг если включен
    backup_manager = None
    try:
        from config.modules.cfg_backup import SFTP_LIVE_SYNC_ENABLE, SFTP_SERVER_INTO_BACKUP_ENABLE
        
        if SFTP_SERVER_INTO_BACKUP_ENABLE and SFTP_LIVE_SYNC_ENABLE:
            backup_manager = BackupManager()
            backup_manager.start_live_monitoring()
    except Exception as e:
        print(Fore.YELLOW + f"⚠️  Не удалось запустить live мониторинг: {e}")
    
    if DISPLAY_LIST_BACKUPS:
        list_backups()
    
    try:
        main_menu()
    finally:
        # Останавливаем мониторинг при выходе
        if backup_manager:
            backup_manager.stop_live_monitoring()
            print(Fore.YELLOW + "\n🔄 Live синхронизация остановлена")
