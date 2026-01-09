import os
import time
import json
import csv
import platform

from colorama import Fore, Style, init
from questionary import Choice, select

# Импортируем из нового централизованного модуля networks
from config.networks import (
    get_mainnet_networks, get_testnet_networks,)

from config.config import (
    expected_completion_time, DISPLAY_LIST_BACKUPS, USE_INTERMEDIARY
)

# Импорт модуля бэкапа
from modules.backup import create_backup, list_backups, backup_menu
from modules.backup.backup_manager import BackupManager

neura_statistics = None
if platform.system().lower() == 'windows':
    try:
        from modules.statistics.neura_stats import neura_statistics
    except Exception as e:
        print(Fore.YELLOW + f"⚠️  Не удалось загрузить модуль Neura Statistics: {e}")
        neura_statistics = None

# Импорт новых модулей для работы с биржами
from modules.config_validator import validate_configuration

def check_and_create_files():
    required_files = [
        'result/result.csv',
        'data/proxy.csv',
        'data/walletss.txt',
        'data/walletss_sol.txt',
        'config/cex_settings.py',
        'data/transfer_token.csv',
        'data/mnemonic.txt',
        'db/transfer_progress.json',
        'data/one_time_intermediary.csv',
        'data/private_keys.txt',
        'data/twitter/twitters.csv',
        'data/twitter/twitter_task.csv',
        'result/twitter/result.csv',
        'data/discord_token.txt',
        'data/email.csv',
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
                if 'result.csv' in file:
                    f.write('address,balance,network\n')
                elif 'transaction_count_result.csv' in file:
                    f.write('address,transaction_count,network\n')
                elif 'cex_settings.py' in file:
                    f.write(
                        '# Конфигурация для множественных аккаунтов бирж\n'
                        '# Для каждой биржи можно настроить несколько аккаунтов\n\n'
                        '# OKX Configuration\n'
                        '# https://www.okx.com/ru/account/my-api\n'
                        'OKX_EU_TYPE = 0  # включите это, если депозиты приходят на Трейдинг аккаунт, вместо Спотового аккаунта\n\n'
                        'OKX_ACCOUNTS = [\n'
                        '    {\n'
                        '        \'name\': \'OKX Main\',\n'
                        '        \'api_key\': \'\',\n'
                        '        \'api_secret\': \'\',\n'
                        '        \'passphrase\': \'\',\n'
                        '        \'type\': OKX_EU_TYPE,\n'
                        '        \'enabled\': False,\n'
                        '    },\n'
                        ']\n\n'
                        '# Binance Configuration\n'
                        '# https://www.binance.com/en/my/settings/api-management\n'
                        'BINANCE_ACCOUNTS = [\n'
                        '    {\n'
                        '        \'name\': \'Binance Main\',\n'
                        '        \'api_key\': \'\',\n'
                        '        \'api_secret\': \'\',\n'
                        '        \'enabled\': False,\n'
                        '    },\n'
                        ']\n\n'
                        '# Bitget Configuration\n'
                        '# https://www.bitget.com/ru/support/articles/360033773814\n'
                        'BITGET_ACCOUNTS = [\n'
                        '    {\n'
                        '        \'name\': \'Bitget Main\',\n'
                        '        \'api_key\': \'\',\n'
                        '        \'api_secret\': \'\',\n'
                        '        \'passphrase\': \'\',\n'
                        '        \'enabled\': False,\n'
                        '    },\n'
                        ']\n\n'
                        '# MEXC Configuration\n'
                        '# https://www.mexc.com/ru-RU/user/openapi\n'
                        'MEXC_ACCOUNTS = [\n'
                        '    {\n'
                        '        \'name\': \'MEXC Main\',\n'
                        '        \'api_key\': \'\',\n'
                        '        \'api_secret\': \'\',\n'
                        '        \'enabled\': False,\n'
                        '    },\n'
                        ']\n'
                    )
                elif 'transfer_token.csv' in file:
                    f.write('from_wallet,to_wallet,intermediary,amount\n')
                elif 'one_time_intermediary.csv' in file:
                    f.write('mnemonic,wallet_address,private_key,status\n')
                elif 'data/twitter/twitters.csv' in file:
                    f.write('nickname,auth_token,ct0,proxy\n')
                elif 'data/twitter/twitter_task.csv' in file:
                    f.write('link,type,value\n')
                elif 'data/email.csv' in file:
                    f.write('email,password,imap_domain\n')
            print(Fore.GREEN + f"File created: {file}")

check_and_create_files()

# Проверка конфигурации при запуске


from modules.info import info
from modules.eth.eth_get_balaces import check_wallet_balances_menu
from modules.eth.eth_get_token_balance import check_token_balances_menu
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

# Импорт модуля Neura Protocol
from modules.neura.menu import neura_menu

from modules.eth.transfer_wallets_to_wallets import (
    process_wallets_transfer, get_proxy_list
)

# Инициализация colorama
init(autoreset=True)

# Автоматически получаем словари сетей из централизованной конфигурации
mainnet_rpc_urls = get_mainnet_networks()
testnet_rpc_urls = get_testnet_networks()


def get_os_type():
    """
    Определяет тип операционной системы
    
    Returns:
        str: 'windows', 'linux' или 'macos'
    """
    system = platform.system().lower()
    if system == 'windows':
        return 'windows'
    elif system == 'darwin':
        return 'macos'
    else:
        return 'linux'


def main_menu():
    try:
        print(
            Fore.GREEN + "\nWelcome to ETHmachine! 🌟 \n ERC20  🌟 - "
            + Fore.MAGENTA + "0xa24fbbd57720ec580395aedba3ad37f6a6067727"
            + Fore.GREEN + " \n TG     🌟 - "
            + Fore.MAGENTA + "https://t.me/DenisHumen"
            + Fore.GREEN + " \n GitHub 🌟 - "
            + Fore.MAGENTA + "https://github.com/DenisHumen"
            + Fore.GREEN + "\n Steam  🌟 - "
            + Fore.MAGENTA + "https://steamcommunity.com/id/Krokosha/"
            + Fore.GREEN + "\n Web    🌟 - "
            + Fore.MAGENTA + "https://krokosha.xyz/"
            + Fore.GREEN + "\n\n"
        )
        while True:
            action = select(
                f"Что вы хотите сделать?",
                choices=[
                    Choice('💲 BALANCES                     🌟 Проверить балансы нативка/токены', 'check_balances'),
                    Choice('🚀 TRANSACTIONS                 🌟 Транзакции между кошельками', 'transactions'),
                    Choice('🐦 Twitter                      🌟 Сбор данных по твиттерам', 'twitter'),
                    Choice('📊 Check project stats          🌟 Проверка статистики по проектам', 'project_stats'),
                    Choice('🎮 PROJECTS                     🌟 Автоматизация проектов (Neura и др.)', 'projects_menu'),
                    #Choice('🔍 Selenium Profile              🌟 Профиль Selenium', 'selenium_profile'),
                    #Choice('🚰 Faucets                      🌟 Краны', 'faucets'),
                    #Choice('💰 Claimer                     🌟 Клейм дропов', 'claimer'),
                    Choice('🏦 CEX                          🌟 Функционал CEX', 'CEX_menu'),
                    Choice('🧰 Tools                        🌟 Разные удобные инструменты', 'miscellaneous'),
                    Choice('💾 Backup                       🌟 Локальные и SFTP бэкапы', 'backup_menu'),
                    Choice('📖 INFO                         🌟 Информация о всех пунктах', 'info'),
                    Choice('❌ Exit', 'exit')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()

            match action:
                case 'backup_menu':
                    backup_menu()
                    continue

                case 'projects_menu':
                    # Projects submenu - автоматизация проектов
                    projects_action = select(
                        "🎮 Выберите проект для автоматизации:",
                        choices=[
                            Choice('🔮 Neura Protocol            🌟 Сбор пульсов и клейм задач', 'neura'),
                            Choice('🔙 Назад', 'back')
                        ],
                        qmark='🎮',
                        pointer='👉'
                    ).ask()
                    
                    match projects_action:
                        case 'neura':
                            neura_menu()
                        case 'back':
                            continue
                    continue

                case 'claimer':
                    print(Fore.RED + "\n\tФункционал Claimer в разработке, скоро будет доступен!\n")
                    time.sleep(3)
                    continue

                case 'twitter':
                    # Twitter submenu
                    twitter_action = select(
                        "Выберите действие с Twitter:",
                        choices=[
                            Choice('🐦 Twitter Check             🌟 Проверка аккаунтов Twitter', 'twitter_check'),
                            Choice('🐦 Twitter Info              🌟 Получение информации Twitter', 'twitter_info'),
                            Choice('🐦 Twitter Task              🌟 Выполнение заданий Twitter', 'twitter_task'),
                            Choice('🔙 Back', 'back')
                        ],
                        qmark='🛠️',
                        pointer='👉'
                    ).ask()

                    match twitter_action:
                        case 'twitter_check':
                            run_twitter_check(get_os_type())
                        case 'twitter_info':
                            run_twitter_check(get_os_type())
                        case 'twitter_task':
                            run_twitter_tasks()
                        case 'back':
                            continue

                case 'miscellaneous':
                    # Формируем список пунктов меню
                    misc_choices = [
                        Choice('⛽ Check Gas Price              🌟 Проверить цену газа', 'check_gas_price'),
                        Choice('🪙 Generate Wallets             🌟 Генерация кошельков', 'generate_wallets'),
                        Choice('🛠️ ETH/SOL convert tool          🌟 Конвертация мнемоники/priv_key в wallet_address/priv_key', 'ETH_convert_tool'),
                        Choice('🔑 Password Generator           🌟 Генерация паролей по заданым параметра в "config/config.py"', 'password_generator'),
                        Choice('🎭 Nickname Generator           🌟 Генерация человечески выглядящих никнеймов', 'nickname_generator'),
                        Choice('👤 Fullname Generator           🌟 Генерация имён и фамилий (RU/UA/ENG)', 'fullname_generator'),
                        Choice('🛠️ Check Proxy                  🌟 Проверить прокси', 'check_proxy'),
                        Choice('🗂️ Last Transactions            🌟 Проверить последние транзакции', 'last_transactions'),
                        Choice('🗂️ Check age discord            🌟 Проверить возраст аккаунта Discord', 'check_age_discord'),
                        Choice('📧 Email IMAP Checker           🌟 Проверить почтовые аккаунты через IMAP', 'email_checker'),
                        Choice('🔙 Back', 'back')
                    ]
                    
                    choices = select(
                        "Выберите действие:",
                        choices=misc_choices,
                        qmark='🛠️',
                        pointer='👉'
                    ).ask()

                    match choices:
                        case 'check_gas_price':
                            check_all_gas_prices()
                        case 'generate_wallets':
                            # Generate Wallets submenu
                            wallets_action = select(
                                "Выберите тип генерации кошельков:",
                                choices=[
                                    Choice('⚡ ETH Кошельки              🌟 Генерация ETH кошельков', 'eth_wallets'),
                                    Choice('☀️ SOL Кошельки              🌟 Генерация SOL кошельков', 'sol_wallets'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🪙',
                                pointer='👉'
                            ).ask()

                            match wallets_action:
                                case 'eth_wallets':
                                    num_wallets = select(
                                        "Сколько кошельков вы хотите сгенерировать?",
                                        choices=[
                                            Choice('▶️  1', 1),
                                            Choice('▶️  10', 10),
                                            Choice('▶️  100', 100),
                                            Choice('▶️  1000', 1000),
                                            Choice('▶️  5000', 5000),
                                            Choice('▶️  10000', 10000),
                                            Choice('✏️ Ввести вручную', 'manual'),
                                            Choice('🔙 Back', 'back')
                                        ],
                                        qmark='🪙',
                                        pointer='👉'
                                    ).ask()
                                    
                                    if num_wallets == 'back':
                                        continue
                                    if num_wallets == 'manual':
                                        try:
                                            num_wallets = int(input(Fore.YELLOW + "Введите количество кошельков для генерации: "))
                                            if num_wallets <= 0:
                                                print(Fore.RED + "Пожалуйста, введите положительное число!")
                                                continue
                                        except ValueError:
                                            print(Fore.RED + "Неверный ввод. Пожалуйста, введите правильное число.")
                                            continue
                                    
                                    eth_wallets_choice = select(
                                        "Выберите тип генерации ETH кошельков:",
                                        choices=[
                                            Choice('🪙 Генерация кошельков       🌟 Сгенерировать кошельки', 'generate'),
                                            Choice('✨ Генерация красивых кошельков 🌟 Сгенерировать красивые кошельки', 'nice_generate'),
                                            Choice('🔙 Back', 'back')
                                        ],
                                        qmark='⚡',
                                        pointer='👉'
                                    ).ask()
                                    match eth_wallets_choice:
                                        case 'generate':
                                            eth_generate_wallets(num_wallets)
                                            print(Fore.GREEN + f"\nСгенерировано {num_wallets} кошельков и сохранено в result/result.csv\n")
                                        case 'nice_generate':
                                            # Выбор реализации: Python или Rust
                                            print(f"\n{Fore.CYAN}Выберите реализацию генератора:{Style.RESET_ALL}")
                                            print(f"{Fore.YELLOW}Python - медленно, но без зависимостей{Style.RESET_ALL}")
                                            print(f"{Fore.GREEN}Rust - быстро (10-100x), требует Cargo{Style.RESET_ALL}\n")
                                            
                                            impl_choice = select(
                                                "Реализация:",
                                                choices=[
                                                    Choice("🐍 Python (медленно, стабильно)", value='python'),
                                                    Choice("🦀 Rust (быстро, требует Cargo)", value='rust'),
                                                    Choice("← Назад", value='back')
                                                ],
                                                qmark='⚙️',
                                                pointer='👉'
                                            ).ask()
                                            
                                            if impl_choice == 'python':
                                                eth_generate_nice_wallets(num_wallets)
                                                print(Fore.GREEN + f"\nСгенерировано {num_wallets} красивых кошельков и сохранено в result/result.csv\n")
                                            elif impl_choice == 'rust':
                                                # Проверяем Cargo и запускаем Rust версию
                                                if check_cargo_installed():
                                                    print(f"\n{Fore.GREEN}✓ Cargo установлен, используем Rust версию{Style.RESET_ALL}")
                                                    
                                                    # Спрашиваем про количество потоков
                                                    use_auto_threads_choice = select(
                                                        "Использовать все доступные потоки?",
                                                        choices=[
                                                            Choice("✅ Да (рекомендуется)", value='yes'),
                                                            Choice("⚙️ Указать вручную", value='no')
                                                        ],
                                                        qmark='🔧',
                                                        pointer='👉'
                                                    ).ask()
                                                    
                                                    if use_auto_threads_choice == 'yes':
                                                        threads = 0
                                                    else:
                                                        threads_input = select(
                                                            "Количество потоков:",
                                                            choices=['2', '4', '6', '8', '12', '16'],
                                                            qmark='🔢',
                                                            pointer='👉'
                                                        ).ask()
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
                                            elif impl_choice == 'back':
                                                continue
                                        case 'back':
                                            continue
                                case 'sol_wallets':
                                    # Сначала выбираем количество кошельков
                                    num_wallets = select(
                                        "Сколько кошельков вы хотите сгенерировать?",
                                        choices=[
                                            Choice('▶️  1', 1),
                                            Choice('▶️  10', 10),
                                            Choice('▶️  100', 100),
                                            Choice('▶️  1000', 1000),
                                            Choice('▶️  5000', 5000),
                                            Choice('▶️  10000', 10000),
                                            Choice('✏️ Ввести вручную', 'manual'),
                                            Choice('🔙 Back', 'back')
                                        ],
                                        qmark='🪙',
                                        pointer='👉'
                                    ).ask()
                                    
                                    if num_wallets == 'back':
                                        continue
                                    if num_wallets == 'manual':
                                        try:
                                            num_wallets = int(input(Fore.YELLOW + "Введите количество кошельков для генерации: "))
                                            if num_wallets <= 0:
                                                print(Fore.RED + "Пожалуйста, введите положительное число!")
                                                continue
                                        except ValueError:
                                            print(Fore.RED + "Неверный ввод. Пожалуйста, введите правильное число.")
                                            continue
                                    
                                    # Теперь выбираем тип генерации
                                    sol_wallets_choice = select(
                                        "Выберите тип генерации SOL кошельков:",
                                        choices=[
                                            Choice('🪙 Генерация кошельков       🌟 Сгенерировать кошельки', 'generate'),
                                            Choice('✨ Генерация красивых кошельков 🌟 Сгенерировать красивые кошельки', 'nice_generate'),
                                            Choice('🔙 Back', 'back')
                                        ],
                                        qmark='☀️',
                                        pointer='👉'
                                    ).ask()
                                    match sol_wallets_choice:
                                        case 'generate':
                                            sol_generate_wallets(num_wallets)
                                            print(Fore.GREEN + f"\nСгенерировано {num_wallets} SOL кошельков и сохранено в result/result.csv\n")
                                        case 'nice_generate':
                                            sol_generate_nice_wallets(num_wallets)
                                            print(Fore.GREEN + f"\nСгенерировано {num_wallets} красивых SOL кошельков и сохранено в result/result.csv\n")
                                        case 'back':
                                            continue
                                case 'back':
                                    continue
                        case 'ETH_convert_tool':
                            # ETH/SOL Convert tool submenu
                            convert_action = select(
                                "Выберите операцию конвертации:",
                                choices=[
                                    Choice('⚡ ETH >> 🔐 Mnemonic to Private Key 🌟 Конвертировать мнемонику в приватный ключ', 'eth_mnemonic_to_privkey'),
                                    Choice('⚡ ETH >> 🗝️ Private Key to Wallet    🌟 Конвертировать приватный ключ в адрес кошелька', 'eth_privkey_to_wallet'),
                                    Choice('☀️ SOL >> 🔐 Mnemonic to Private Key 🌟 Конвертировать мнемонику в приватный ключ', 'sol_mnemonic_to_privkey'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()

                            match convert_action:
                                case 'eth_mnemonic_to_privkey':
                                    process_mnemonics()
                                case 'eth_privkey_to_wallet':
                                    process_private_keys()
                                case 'sol_mnemonic_to_privkey':
                                    sol_process_mnemonics()
                                case 'back':
                                    continue
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
                            choices = select(
                                "Выберите способ проверки возраста аккаунта Discord:",
                                choices=[
                                    Choice('💲 Windows', 'windows'),
                                    Choice('💲 MacOS', 'macos'),
                                    Choice('💲 Linux', 'linux'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()
                            match choices:
                                case 'windows':
                                    check_discord_accounts('windows')
                                case 'macos':
                                    check_discord_accounts('macos')
                                case 'linux':
                                    check_discord_accounts('linux')
                                case 'back':
                                    continue
                        case 'email_checker':
                            run_email_checker()
                            continue
                        case 'back':
                            continue

                case 'check_balances':
                    blockchain = select(
                        "Выберите блокчейн:",
                        choices=[
                            Choice('💲 ETH', 'ETH'),
                            Choice('💲 SOL', 'SOL'),
                            Choice('💲 Eclipse', 'Eclipse'),
                            Choice('🔙 Back', 'back')
                        ],
                        qmark='🛠️',
                        pointer='👉'
                    ).ask()
                    if blockchain == 'back':
                        continue

                    if blockchain == 'ETH':
                        choices = select(
                            "Выберите действие для ETH:",
                            choices=[
                                Choice('💲 Check Wallets Balances', 'check_wallet_balances_eth'),
                                Choice('💲 Check Token Balances', 'check_token_balances'),
                                Choice('🔙 Back', 'back')
                            ],
                            qmark='🛠️',
                            pointer='👉'
                        ).ask()
                        match choices:
                            case 'check_wallet_balances_eth':
                                check_wallet_balances_menu()
                            case 'check_token_balances':
                                check_token_balances_menu()
                            case 'back':
                                continue

                    elif blockchain == 'SOL':
                        choices = select(
                            "Выберите действие для SOL:",
                            choices=[
                                Choice('💲 Check Wallets Balances', 'check_wallet_balances_sol'),
                                Choice('💲 Check Token Balances', 'check_token_balances_sol'),
                                Choice('🔙 Back', 'back')
                            ],
                            qmark='🛠️',
                            pointer='👉'
                        ).ask()
                        match choices:
                            case 'check_wallet_balances_sol':
                                solana_balance_checker()
                            case 'check_token_balances_sol':
                                print(Fore.RED + "Функционал проверки токенов SOL в разработке, скоро будет доступен!\n")
                            case 'back':
                                continue

                    elif blockchain == 'Eclipse':
                        eclipse_balance_checker()
                        continue

                case 'transactions':
                    choices = select(
                        "Выберите действие:",
                        choices=[
                            Choice('🧹 Drainers                     🌟 Сборщик балансов на main кошелек ', 'drainers'),
                            Choice('🔄 Transfer Wallets to Wallets  🌟 Отправить нативные токены между кошельками', 'transfer_wallets_to_wallets_call'),
                            Choice('💎 Transfer ERC20 Tokens        🌟 Отправить ERC20 токены между кошельками', 'transfer_erc20_tokens_call'),
                            Choice('🌉 Relay Bridge                 🌟 Мост между сетями через Relay Link', 'relay_bridge'),
                            Choice('🔙 Back', 'back')
                        ],
                        qmark='🛠️',
                        pointer='👉'
                    ).ask()

                    match choices:
                        case 'drainers':
                            choices = select(
                                "Выберите действие:",
                                choices=[
                                    Choice('💲 ETH Drainers', 'eth_drainers'),
                                    Choice('💲 SOL Drainers', 'sol_drainers'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()

                            match choices:
                                case 'eth_drainers':
                                    eth_drainers()
                                case 'sol_drainers':
                                    print(Fore.RED + "Функционал SOL Drainers в разработке, скоро будет доступен!\n")
                                    time.sleep(3)
                                case 'back':
                                    continue

                        case 'transfer_wallets_to_wallets_call':
                            print(Fore.GREEN + f"\n\nФормат данных для data/transfer_token.csv: from_wallet,to_wallet,intermediary,amount")
                            print(Fore.YELLOW + f"Пример: Приватник откуда, Приватник конечный получатель, Приватник посредник, количество в процентах от баланса (например 10-15 для рандомного выбора между 10% и 15% от баланса)\n")
                            print(Fore.YELLOW + "C посредника будет отправленно 100% от баланса")
                            network_type = select(
                                "Select network type:",
                                choices=[
                                    Choice('🌐 Mainnet', 'mainnet'),
                                    Choice('🔧 Testnet', 'testnet'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()
                            if network_type == 'back':
                                continue

                            network_choices = list(mainnet_rpc_urls.keys()) if network_type == 'mainnet' else list(testnet_rpc_urls.keys())
                            network = select(
                                "Which network do you want to use for transfer?",
                                choices=[Choice(n, n) for n in network_choices] + [Choice('🔙 Back', 'back')],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()
                            if network == 'back':
                                continue

                            transfer_data = []
                            try:
                                with open('data/transfer_token.csv', 'r', encoding='utf-8') as f:
                                    reader = csv.DictReader(f)
                                    for row in reader:
                                        if USE_INTERMEDIARY:
                                            if row['from_wallet'] and row['to_wallet'] and row['intermediary'] and row['amount']:
                                                transfer_data.append(row)
                                        else:
                                            if row['from_wallet'] and row['to_wallet'] and row['amount']:
                                                if 'intermediary' not in row:
                                                    row['intermediary'] = ''
                                                transfer_data.append(row)
                            except Exception as e:
                                print(Fore.RED + f"Ошибка чтения data/transfer_token.csv: {e}")
                                continue

                            if not transfer_data:
                                if USE_INTERMEDIARY:
                                    print(Fore.RED + "Нет данных для отправки в data/transfer_token.csv или не заполнено поле посредника (intermediary).")
                                    continue
                                else:
                                    print(Fore.RED + "Нет данных для отправки в data/transfer_token.csv.")
                                    continue

                            db_dir = "db"
                            if not os.path.exists(db_dir):
                                os.makedirs(db_dir)
                            progress_file = os.path.join(db_dir, "transfer_progress.json")

                            start_idx = 0
                            completed_txs = 0
                            resume = None
                            if os.path.exists(progress_file):
                                with open(progress_file, "r", encoding="utf-8") as pf:
                                    try:
                                        progress_data = json.load(pf)
                                        start_idx = progress_data.get("last_idx", 0)
                                        completed_txs = progress_data.get("completed_txs", 0)
                                    except Exception:
                                        start_idx = 0
                                        completed_txs = 0
                                resume = select(
                                    "Обнаружен файл прогресса. Продолжить с места остановки или начать сначала?",
                                    choices=[
                                        Choice("▶️ Продолжить", "resume"),
                                        Choice("🔄 Начать сначала", "restart"),
                                        Choice("❌ Отмена", "cancel")
                                    ],
                                    qmark='🛠️',
                                    pointer='👉'
                                ).ask()
                                if resume == "cancel":
                                    continue
                                elif resume == "restart":
                                    start_idx = 0
                                    completed_txs = 0
                                    try:
                                        os.remove(progress_file)
                                    except Exception:
                                        pass
                            else:
                                with open(progress_file, "w", encoding="utf-8") as pf:
                                    json.dump({"last_idx": 0, "completed_txs": 0}, pf)

                            proxies = get_proxy_list()
                            total_tx = len(transfer_data) * 2
                            total_seconds = expected_completion_time
                            delay_between = total_seconds / (total_tx - 1) if total_tx > 1 else 0

                            process_wallets_transfer(
                                transfer_data, proxies, network, delay_between, total_tx,
                                progress_file=progress_file, start_idx=start_idx, completed_txs=completed_txs
                            )
                            continue

                        case 'transfer_erc20_tokens_call':
                            from modules.eth.transfer_erc20_tokens import run_transfer_erc20_tokens
                            run_transfer_erc20_tokens()
                            continue

                        case 'relay_bridge':
                            relay_bridge_main()
                            continue

                        case 'back':
                            continue

                case 'info':
                    info()
                    continue

                case 'check_balances_SOL':
                    print(Fore.GREEN + f"\n\tФункционал CEX в разработке\n \tОбращайтесь с вопросами в тг https://t.me/DenisHumen")
                    continue

                case 'faucets':
                    while True:
                        print(Fore.GREEN + "\n\tВНИМАНИЕ кран будет запрашивать или в кошельки по файлу 'data/walletss.txt' или 'data/private_keys.txt'!\n")
                        print(Fore.GREEN + "\tВсе зависит от крана, если можно без использования приватника то там его не будет")
                        print(Fore.GREEN + "\tПри запуске всегда будет говориться с каким файлом работает и проверять пуст ли файл\n")
                        action = select(
                            "Запрос крана:",
                            choices=[
                                Choice('🔙 Back', 'back')
                            ],
                            qmark='🛠️',
                            pointer='👉'
                        ).ask()

                        match action:
                            case 'back':
                                break

                case 'project_stats':
                    while True:
                        stats_choices = []
                        if neura_statistics is not None:
                            stats_choices.append(Choice('📊 Neura         🌟 Статистика по ETHmachine', 'neura_stat'))
                        else:
                            current_os = get_os_type()
                            stats_choices.append(Choice(f'📊 Neura         ⚠️  Доступно только на Windows (текущая ОС: {current_os})', 'neura_stat_unavailable'))
                        
                        stats_choices.append(Choice('🔙 Back', 'back'))
                        
                        action = select(
                            "Выберите действие (статистика по проектам):",
                            choices=stats_choices,
                            qmark='🛠️',
                            pointer='👉'
                        ).ask()

                        match action:
                            case 'neura_stat':
                                if neura_statistics is not None:
                                    neura_statistics()
                                else:
                                    print(Fore.RED + "\n⚠️  Модуль Neura Statistics недоступен!")
                                    print(Fore.YELLOW + "Этот модуль работает только на Windows из-за зависимости от pyarmor_runtime.pyd")
                                    print(Fore.YELLOW + f"Ваша текущая ОС: {get_os_type()}")
                                    input("\nНажмите Enter для продолжения...")
                            case 'neura_stat_unavailable':
                                print(Fore.RED + "\n⚠️  Модуль Neura Statistics недоступен!")
                                print(Fore.YELLOW + "Этот модуль работает только на Windows из-за зависимости от pyarmor_runtime.pyd")
                                print(Fore.YELLOW + f"Ваша текущая ОС: {get_os_type()}")
                                input("\nНажмите Enter для продолжения...")
                            case 'back':
                                break

                case 'check_proxy':
                    check_proxy_menu()
                    continue

                case 'exit':
                    animation = [
                        "👋",
                        "👋🙂",
                        "👋🙂🚀",
                        "👋🙂🚀💸",
                        "👋🙂🚀💸✨",
                        "👋🙂🚀💸✨🦾",
                        "👋🙂🚀💸✨🦾\n"
                    ]
                    for frame in animation:
                        print(Fore.GREEN + f"\r{frame}", end='', flush=True)
                        time.sleep(0.1)
                    print(Fore.GREEN + "\n\t❤️‍🔥 Спасибо за использование ETHmachine! \n \t❤️‍🔥 Если есть вопросы и предложения то в тг https://t.me/DenisHumen\n\n")
                    #time.sleep(3)
                    break

                case 'CEX_menu':
                    action = select(
                        'Выберите действие:',
                        choices=[
                            Choice('💲 OKX          🌟 Работа с OKX', 'OKX'),
                            Choice('💲 Binance      🌟 Работа с Binance', 'Binance'),
                            Choice('💲 Bitget       🌟 Работа с Bitget', 'Bitget'),
                            Choice('💲 MEXC         🌟 Работа с MEXC', 'MEXC'),
                            Choice('🔙 Back', 'back')
                        ],
                        qmark='🛠️',
                        pointer='👉'
                    ).ask()
                    match action:
                        case 'OKX':
                            action = select(
                                'Выберите действие:',
                                choices=[
                                    Choice('💲 Withdraw from OKX          🌟 Вывод с OKX', 'withdraw_from_okx'),
                                    Choice('💲 Get Balances from OKX      🌟 Получить балансы с OKX', 'get_balances_okx'),
                                    Choice('💲 Subaccount collector OKX   🌟 Сборщик субаккаунтов OKX', 'subaccount_collector_okx'),
                                    Choice('💲 Auto spot trade OKX        🌟 Спотовая торговля на бирже', 'spot_trade_okx'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()

                            match action:
                                case 'withdraw_from_okx':
                                    okx_withdraw()
                                    continue
                                case 'get_balances_okx':
                                    get_balances_okx()
                                    continue
                                case 'subaccount_collector_okx':
                                    check_okx_subaccounts_and_balances()
                                case 'spot_trade_okx':
                                    #print(Fore.GREEN + "\n\tФункционал OKX в разработке, скоро будет доступен\n")
                                    start_okx_spot_trading()
                                case 'back':
                                    continue

                        case 'Binance':
                            action = select(
                                'Выберите действие:',
                                choices=[
                                    Choice('💲 Withdraw from Binance  🌟 Вывод с Binance', 'withdraw_from_binance'),
                                    Choice('💲 Get Balances from Binance  🌟 Получить балансы с Binance', 'get_balances_binance'),
                                    Choice('💲 Subaccount collector Binance', 'subaccount_collector_binance'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()

                            match action:
                                case 'withdraw_from_binance':
                                    binance_withdraw()
                                    continue
                                case 'get_balances_binance':
                                    print(Fore.GREEN + "\n\tФункционал Binance в разработке, скоро будет доступен\n")
                                    get_balances_binance()
                                case 'subaccount_collector_binance':
                                    print(Fore.GREEN + "\n\tФункционал Binance в разработке, скоро будет доступен\n")
                                    subaccount_collector_binance()
                                    continue
                                case 'back':
                                    continue

                        case 'Bitget':
                            action = select(
                                'Выберите действие:',
                                choices=[
                                    Choice('💲 Withdraw from Bitget           🌟 Вывод с Bitget', 'withdraw_from_bitget'),
                                    Choice('💲 Get Balances from Bitget       🌟 Получить балансы с Bitget', 'get_balances_bitget'),
                                    Choice('💲 Subaccount collector Bitget    🌟 Сборщик субаккаунтов Bitget', 'subaccount_collector_bitget'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()

                            match action:
                                case 'withdraw_from_bitget':
                                    bitget_withdraw()
                                    continue
                                case 'get_balances_bitget':
                                    print(Fore.GREEN + "\n\tФункционал Bitget в разработке, скоро будет доступен\n")
                                    #get_balances_bitget()
                                    continue
                                case 'subaccount_collector_bitget':
                                    #print(Fore.GREEN + "\n\tФункционал Bitget в разработке, скоро будет доступен\n")
                                    check_bitget_subaccounts_and_balances()
                                case 'back':
                                    continue

                        case 'MEXC':
                            action = select(
                                'Выберите действие:',
                                choices=[
                                    Choice('💲 Withdraw from MEXC           🌟 Вывод с MEXC', 'withdraw_from_mexc'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()

                            match action:
                                case 'withdraw_from_mexc':
                                    mexc_withdraw()
                                    continue
                                case 'back':
                                    continue

                        case 'back':
                            continue

                case 'check_all_balances': 
                    print(Fore.GREEN + f"\n\tФункционал CEX в разработке\n \tОбращайтесь с вопросами в тг https://t.me/DenisHumen")
                    time.sleep(3)
                    continue

                case'back':
                    continue


    except Exception as e:
        print(Fore.RED + f"Error: {e}")


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
    #print(Fore.GREEN + "✅ Конфигурация проверена успешно!\n")

    # Запускаем live мониторинг если включен
    backup_manager = None
    try:
        from config.config import SFTP_LIVE_SYNC_ENABLE, SFTP_SERVER_INTO_BACKUP_ENABLE
        
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
