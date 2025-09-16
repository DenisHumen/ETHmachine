import os
import time
import json
import csv

from colorama import Fore, init
from questionary import Choice, select

from config.rpc import (
    L1, base, sepolia, arbitrum, optimism, soneium, Polygon, Binance_Smart_Chain,
    Avalanche, Fantom, Gravity_Alpha_Mainnet, monad_testnet, zora,
    somnia, mega_eth_testnet, Abstract, pharos_testnet, camp_testnet, kite_testnet
)
from config.config import (
    expected_completion_time, NICE_ADDRESS_WORDS_enable, REPEATED_CHAR_COUNT_enable,
    DISPLAY_LIST_BACKUPS, USE_INTERMEDIARY, USE_INTERMEDIARY_TOKEN, expected_completion_time_token
)

from modules.auto_backup import create_backup, list_backups

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
        'result/twitter/result.csv',
        'data/twitter/twitter_task.csv',
        'data/discord_token.txt',
        'data/email.csv',
    ]
    required_directories = [
        'result',
        'data',
        'db',
        'result/json/pharos_faucet',
        'result/faucet',
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
                        '# https://www.okx.com/ru/account/my-api\n'
                        'OKX_API_KEY = ""\n'
                        'OKX_API_SECRET = ""\n'
                        'OKX_API_PASSPHRAS = ""\n'
                        'OKX_EU_TYPE = 0  # включите это, если депозиты приходят на Трейдинг аккаунт, вместо Спотового аккаунта\n'
                        "'------------------------------------------------------------------------------------------------------------'\n"
                        'binance_api_key = ""\n'
                        'secret_key = ""\n'
                        "'------------------------------------------------------------------------------------------------------------'\n"
                        '\n'
                        '# https://www.bitget.com/ru/support/articles/360033773814\n'
                        'bitget_api_key = ""\n'
                        'bitget_api_secret = ""\n'
                        'bitget_passphrase = ""  # Может потребоваться для некоторых API ключей\n'
                        "'------------------------------------------------------------------------------------------------------------'\n"
                    )
                elif 'transfer_token.csv' in file:
                    f.write('from_wallet,to_wallet,intermediary,amount\n')
                elif 'one_time_intermediary.csv' in file:
                    f.write('mnemonic,wallet_address,private_key,status\n')
                elif 'data/twitter/twitters.csv' in file:
                    f.write('nickname,auth_token,ct0\n')
                elif 'data/twitter/twitter_task.csv' in file:
                    f.write('еще в разработке\n')
                elif 'data/email.csv' in file:
                    f.write('email,password,imap_domain\n')
            print(Fore.GREEN + f"File created: {file}")

# Создаем файлы ДО импорта модулей
check_and_create_files()

# Импорты модулей ПОСЛЕ создания файлов
from modules.info import info
from modules.eth.eth_get_balaces import check_wallet_balances_menu
from modules.eth.eth_get_token_balance import check_token_balances_menu
from modules.password_generator import password_generator_menu
from modules.get_gas_price import check_all_gas_prices

from modules.twitter.twitter_check import run_twitter_check
from modules.discord.discord_age import check_discord_accounts
from modules.email.email_imap_checker import run_email_checker

from modules.cex.okx.okx_SubAccount import check_okx_subaccounts_and_balances, get_balances_okx
from modules.cex.okx.okx_withdraw import okx_withdraw
from modules.cex.okx.okx_SpotTrade import start_okx_spot_trading
from modules.cex.binance.binance_withdraw import binance_withdraw
from modules.cex.binance.binance_SubAccount import get_balances_binance, subaccount_collector_binance
from modules.cex.bitget.bitget_SubAccount import check_bitget_subaccounts_and_balances
from modules.cex.bitget.bitget_withdraw import bitget_withdraw
from modules.GitHub.check_version import check_version

from modules.check_proxy import check_proxy_menu

from modules.eth.eth_wallet_generator import eth_generate_wallets
from modules.eth.eth_nice_address import eth_generate_nice_wallets
from modules.eth.eth_mnemonic_to_privkey import process_mnemonics
from modules.eth.eth_private_key_to_wallet_address import process_private_keys
from modules.eth.eth_drainers import eth_drainers
from modules.eth.eth_last_tx import check_last_transactions
from modules.relay_link.relay_link import main as relay_bridge_main

from modules.sol.sol_wallet_generator import sol_generate_wallets
from modules.sol.sol_nice_address import sol_generate_nice_wallets
from modules.sol.sol_mnemonic_to_privkey import sol_process_mnemonics

from modules.eth.transfer_wallets_to_wallets import (
    process_wallets_transfer, get_proxy_list
)


init(autoreset=True)

mainnet_rpc_urls = {
    '🚀 Ethereum Mainnet': L1,
    '🚀 Base': base,
    '🚀 Arbitrum One': arbitrum,
    '🚀 Optimism': optimism,
    '🚀 Soneium': soneium,
    '🚀 Polygon': Polygon,
    '🚀 Binance Smart Chain': Binance_Smart_Chain,
    '🚀 Avalanche': Avalanche,
    '🚀 Fantom': Fantom,
    '🚀 Gravity Alpha Mainnet (сеть Gravity )': Gravity_Alpha_Mainnet,
    '🚀 Zora': zora,
    '🚀 Abstract': Abstract,
    '🚀 Somnia': somnia,
}

testnet_rpc_urls = {
    '🚀 Sepolia': sepolia,
    '🚀 Monad Testnet (native token MON)': monad_testnet,
    '🚀 Mega ETH Testnet': mega_eth_testnet,
    '🚀 Pharos Testnet': pharos_testnet,
    '🚀 Camp Testnet': camp_testnet,
    '🚀 Kite Testnet': kite_testnet,
}



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
            + Fore.GREEN + "\n\n"
        )
        while True:
            action = select(
                f"Что вы хотите сделать?",
                choices=[
                    Choice('💲 BALANCES                     🌟 Проверить балансы нативка/токены', 'check_balances'),
                    Choice('💲 TRANSACTIONS                 🌟 Транзакции между кошельками', 'transactions'),
                    #Choice('🚰 Faucets                      🌟 Краны', 'faucets'),
                    Choice('🐦 Twitter                      🌟 Сбор данных по твиттерам', 'twitter'),
                    #Choice('📊 Check project stats         🌟 Проверка статистики по проектам', 'project_stats'),
                    Choice('⛽ Check Gas Price              🌟 Проверить цену газа', 'check_gas_price'),
                    Choice('🪙  Generate Wallets             🌟 Генерация кошельков', 'generate_wallets'),
                    Choice('🏦 CEX                          🌟 Функционал CEX', 'CEX_menu'),
                    Choice('🛠️ ETH/SOL convert tool          🌟 Конвертация мнемоники/priv_key в wallet_address/priv_key', 'ETH_convert_tool'),
                    Choice('🧰 Miscellaneous                🌟 Разные удобные штуки', 'miscellaneous'),
                    Choice('📖 INFO                         🌟 Информация о всех пунктах', 'info'),
                    Choice('❌ Exit', 'exit')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()

            match action:
                case 'miscellaneous':
                    choices = select(
                        "Выберите действие:",
                        choices=[
                            Choice('🗂️ password generator           🌟 Генерация паролей по заданым параметра в "config/config.py"', 'password_generator'),
                            Choice('🗂️ Check Proxy                  🌟 Проверить прокси', 'check_proxy'),
                            Choice('🗂️ Last Transactions            🌟 Проверить последние транзакции', 'last_transactions'),
                            Choice('🗂️ Check age discord            🌟 Проверить возраст аккаунта Discord', 'check_age_discord'),
                            Choice('� Email IMAP Checker           🌟 Проверить почтовые аккаунты через IMAP', 'email_checker'),
                            Choice('�🔙 Back', 'back')
                        ],
                        qmark='🛠️',
                        pointer='👉'
                    ).ask()

                    match choices:
                        case 'password_generator':
                            password_generator_menu()
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
                                #check_wallet_balances_sol()
                                print(Fore.RED + "Функционал проверки балансов SOL в разработке, скоро будет доступен!\n")
                            case 'check_token_balances_sol':
                                #check_token_balances_sol()
                                print(Fore.RED + "Функционал проверки токенов SOL в разработке, скоро будет доступен!\n")
                            case 'back':
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

                case 'twitter':
                    count = select(
                        "Выберите действие:",
                        choices=[
                            Choice('🐦 Check Twitter Accounts  🌟 сбор статистики по аккаунтам с data/twitter/twitters.csv', 'check_twitter_accounts'),
                            Choice('🐦 Twitter Task            🌟 выполнение задач по файлу data/twitter/twitter_task.csv', 'twitter_task'),
                            Choice('ℹ️ INFO', 'info'),
                            Choice('🔙 Back', 'back')
                        ],
                        qmark='🛠️',
                        pointer='👉',
                    ).ask()
                    match count:
                        case 'check_twitter_accounts':
                            choices = select(
                                "Выберите платформу на которой запускается скрипт:",
                                choices=[
                                    Choice('🐦 Windows', 'windows'),
                                    Choice('🐦 Linux', 'linux'),
                                    Choice('🐦 MacOS', 'macos'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()

                            match choices:
                                case 'windows':
                                    run_twitter_check('windows')
                                case 'linux':
                                    run_twitter_check('linux')
                                case 'macos':
                                    run_twitter_check('macos')
                                case 'back':
                                    continue

                        case 'twitter_task':
                            print(Fore.GREEN + "\n\tФункционал Twitter Task в разработке, скоро будет доступен!\n")
                        case 'info':
                            print(Fore.GREEN + "\n\tИнформация о Twitter Checker (еще делаю):\n")

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
                        action = select(
                            "Выберите действие (статистика по проектам):",
                            choices=[
                                Choice('📈 Pharos', 'pharos_stats'),
                                Choice('📈 Monad', 'monad'),
                                Choice('📈 Mega ETH', 'MegaETH'),
                                Choice('🔙 Back', 'back')
                            ],
                            qmark='🛠️',
                            pointer='👉'
                        ).ask()

                        animation = [
                            "🕐",
                            "🕑",
                            "🕒",
                            "🕓",
                            "🕔",
                            "🕕",
                            "🕖",
                            "🕗",
                            "🕘",
                            "🕙",
                            "🕚",
                            "🕛",
                            "🕐",
                            "🕑",
                            "🕒",
                            "🕓",
                            "🕔",
                            "🕕",
                            "🕖",
                            "🕗",
                            "🕘",
                            "🕙",
                            "🕚",
                            "🕛",
                            "🕐",
                            "🕑",
                            "🕒",
                            "🕓",
                            "🕔",
                            "🕕",
                            "🕖",
                            "🕗",
                            "🕘",
                            "🕙",
                            "🕚",
                            "🕛"
                        ]

                        match action:
                            case 'pharos_stats':

                                #pharos_wallet_stats()
                                print(Fore.GREEN + "\n\tСтатистика берется из сайта https://pharos-stats.vercel.app/\n")
                                print(Fore.YELLOW + "\n\tНа данный момент чекер находится в разработке, сейчас не работает\n")
                                print(Fore.YELLOW + "\tЕсли хотите добавить другие сети, то пишите в тг https://t.me/DenisHumen\n")

                                for frame in animation:
                                    print(Fore.GREEN + f"\r{frame}", end='', flush=True)
                                    time.sleep(0.1)
                                print()
                                continue
                            
                            case 'monad':
                                print(Fore.GREEN + '\n\tДоступна в скрипте https://github.com/DenisHumen/CryptoProjectChecker\n')
                                time.sleep(3)

                            case 'MegaETH':
                                print(Fore.GREEN + '\n\tДоступна в скрипте https://github.com/DenisHumen/CryptoProjectChecker\n')
                                time.sleep(3)

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

                        case 'back':
                            continue

                case 'ETH_convert_tool':
                    action = select(
                        'Выберите действие:',
                        choices=[
                            Choice('🔑 Convert Mnemonic to Private Key | Конвертация мнемонической фразы в приватный ключ', 'mnemonic_to_priv_key'),
                            Choice('🔑 Convert Private Key to Wallet Address | Конвертация приватного ключа в адрес кошелька', 'private_key_to_wallet_address'),
                            Choice('🔙 Back', 'back')
                        ],
                        qmark='🛠️',
                        pointer='👉'
                    ).ask()

                    match action:
                        case 'back':
                            continue
                        case 'mnemonic_to_priv_key':
                            blockchain_action = select(
                                'Sol или ETH?',
                                choices=[
                                    Choice('💲 ETH', 'ETH'),
                                    Choice('💲 SOL', 'SOL'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()
                            
                            match blockchain_action:
                                case 'back':
                                    continue
                                case 'SOL':
                                    #print(Fore.RED + "Конвертация мнемонической фразы в приватный ключ для SOL еще в работе, скоро будет доступна!\n")
                                    sol_process_mnemonics()
                                    time.sleep(2)
                                    continue
                                case 'ETH':
                                    if not os.path.exists('data/mnemonic.txt') or os.stat('data/mnemonic.txt').st_size == 0:
                                        print(Fore.RED + "Файл data/mnemonic.txt пуст или не существует. Пожалуйста, добавьте мнемонические фразы.")
                                        time.sleep(2)
                                        continue
                                    print(Fore.GREEN + "Конвертация мнемонической фразы в приватный ключ для ETH")
                                    process_mnemonics()
                                    continue
                            
                            time.sleep(2)
                            continue
                        case 'private_key_to_wallet_address':
                            action = select(
                                'Выберите действие:',
                                choices=[
                                    Choice('💲 ETH', 'ETH'),
                                    Choice('💲 SOL', 'SOL'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()

                            match action:
                                case 'back':
                                    continue
                                case 'SOL':
                                    print(Fore.RED + "Конвертация приватного ключа в адрес кошелька для SOL еще в работе, скоро будет доступна!\n")
                                    continue
                                case 'ETH':
                                    print(Fore.GREEN + "Конвертация приватного ключа в адрес кошелька")
                                    process_private_keys()
                                    time.sleep(2)
                                    continue

                case 'generate_wallets':
                    num_wallets = select(
                        "How many wallets do you want to generate?",
                        choices=[
                            Choice('▶️  1', 1),
                            Choice('▶️  10', 10),
                            Choice('▶️  100', 100),
                            Choice('▶️  1000', 1000),
                            Choice('▶️  5000', 5000),
                            Choice('▶️  10000', 10000),
                            Choice('✏️ Enter manually', 'manual'),
                            Choice('🔙 Back', 'back')
                        ],
                        qmark='🛠️',
                        pointer='👉'
                    ).ask()
                    if num_wallets == 'back':
                        continue
                    if num_wallets == 'manual':
                        try:
                            num_wallets = int(input(Fore.YELLOW + "Enter the number of wallets to generate: "))
                            if num_wallets <= 0:
                                print(Fore.RED + "Please enter a positive number: ")
                                continue
                        except ValueError:
                            print(Fore.RED + "Invalid input. Please enter a valid number.")
                            continue

                    if num_wallets and num_wallets != 'back':
                        action = select(
                            f"Для какой сети?",
                            choices=[
                                Choice('💲 ETH', 'ETH'),
                                Choice('💲 SOL', 'SOL'),
                                Choice('🔙 Back', 'back')
                            ],
                            qmark='🛠️',
                            pointer='👉'
                        ).ask()
                        if action == 'ETH':

                            addr_type = select(
                                f"Какие адреса генерировать ?",
                                choices=[
                                    Choice('💲 Normal | Обычные', 'normal'),
                                    Choice('💲 Nice | Красивые', 'nice'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()
                            if addr_type == 'normal':
                                eth_generate_wallets(num_wallets)
                                print(Fore.GREEN + f"\nGenerated {num_wallets} wallets and saved to result/result.csv\n")
                                continue
                            if addr_type == 'nice':
                                if not NICE_ADDRESS_WORDS_enable and not REPEATED_CHAR_COUNT_enable:
                                    print(Fore.RED + "\nОшибка: Все параметры поиска отключены.")
                                    print(Fore.YELLOW + "Включите NICE_ADDRESS_WORDS_enable или REPEATED_CHAR_COUNT_enable в config/config.py и повторите попытку.\n")
                                    continue
                                if NICE_ADDRESS_WORDS_enable or REPEATED_CHAR_COUNT_enable:
                                    eth_generate_nice_wallets(num_wallets)
                                    print(Fore.GREEN + f"\nGenerated {num_wallets} nice wallets and saved to result/result.csv\n")
                                    continue


                        elif action == 'SOL':
                            addr_type = select(
                                f"Какие адреса генерировать ?",
                                choices=[
                                    Choice('💲 Normal | Обычные', 'normal'),
                                    Choice('💲 Nice | Красивые', 'nice'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()
                            if addr_type == 'normal':
                                sol_generate_wallets(num_wallets)
                                print(Fore.GREEN + f"\nGenerated {num_wallets} SOL wallets and saved to result/result.csv\n")
                                continue
                            elif addr_type == 'nice':
                                if not NICE_ADDRESS_WORDS_enable and not REPEATED_CHAR_COUNT_enable:
                                    print(Fore.RED + "\nОшибка: Все параметры поиска отключены.")
                                    print(Fore.YELLOW + "Включите NICE_ADDRESS_WORDS_enable или REPEATED_CHAR_COUNT_enable в config/config.py и повторите попытку.\n")
                                    continue
                                if NICE_ADDRESS_WORDS_enable or REPEATED_CHAR_COUNT_enable:
                                    sol_generate_nice_wallets(num_wallets)
                                    print(Fore.GREEN + f"\nGenerated {num_wallets} nice SOL wallets and saved to result/result.csv\n")
                                    continue


                        elif action == 'back':
                            continue
                    #continue

                case 'check_all_balances': 
                    print(Fore.GREEN + f"\n\tФункционал CEX в разработке\n \tОбращайтесь с вопросами в тг https://t.me/DenisHumen")
                    time.sleep(3)
                    continue

                case 'check_gas_price':
                    check_all_gas_prices()

                case'back':
                    continue


    except Exception as e:
        print(Fore.RED + f"Error: {e}")


if __name__ == "__main__":
    check_version("ETHmachine")
    create_backup()
    if DISPLAY_LIST_BACKUPS:
        list_backups()
    main_menu()
