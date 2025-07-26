import os
import time
import json


from colorama import Fore, init
from questionary import Choice, select

from config.rpc import (
    L1, base, sepolia, arbitrum, optimism, soneium, Polygon, Binance_Smart_Chain,
    Avalanche, Fantom, Gravity_Alpha_Mainnet, monad_testnet, sahara_testnet, zora,
    somnia_testnet, mega_eth_testnet, Abstract, pharos_testnet, camp_testnet
)
from config.config import (
    expected_completion_time, NICE_ADDRESS_WORDS_enable, REPEATED_CHAR_COUNT_enable,
    DISPLAY_LIST_BACKUPS
)

from modules.auto_backup import create_backup, list_backups

from modules.info import info
from modules.eth.eth_get_balaces import check_wallet_balances_menu
from modules.eth.eth_get_token_balance import check_token_balances_menu
from modules.get_gas_price import check_all_gas_prices

from modules.faucets.somnia import run_somnia_faucet
from modules.twitter.twitter_check import run_twitter_check

from modules.cex.okx import withdraw_from_okx, get_balances_okx
from modules.cex.binance import withdraw_from_binance, get_balances_binance
from modules.GitHub.check_version import check_version

from modules.eth.eth_wallet_generator import eth_generate_wallets
from modules.eth.eth_nice_address import eth_generate_nice_wallets
from modules.eth.eth_mnemonic_to_privkey import process_mnemonics
from modules.eth.eth_private_key_to_wallet_address import process_private_keys
from modules.eth.eth_drainers import eth_drainers

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
    '🚀 Gravity Alpha Mainnet': Gravity_Alpha_Mainnet,
    '🚀 Zora': zora,
    '🚀 Abstract': Abstract,
}

testnet_rpc_urls = {
    '🚀 Sepolia': sepolia,
    '🚀 Monad Testnet (native token MON)': monad_testnet,
    '🚀 Sahara testnet': sahara_testnet,
    '🚀 Somnia Testnet': somnia_testnet,
    '🚀 Mega ETH Testnet': mega_eth_testnet,
    '🚀 Pharos Testnet': pharos_testnet,
    '🚀 Camp Testnet': camp_testnet,
}



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
        'db/spot_trade.sqlite',
        'data/one_time_intermediary.csv',
        'data/private_keys.txt',
        'data/twitter/twitters.csv',
        'result/twitter/result.csv',
        'data/twitter/twitter_task.csv'
    ]
    required_directories = [
        'result',
        'data',
        'db',
        'result/json/pharos_faucet',
        'result/faucet',
        'result/twitter',
        'data/twitter',
        'backups'
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
                        '\n'
                        'TOKEN = [\'USDC\']\n'
                        '"""\n'
                        '        - Список токенов:\n'
                        '                - USDC\n'
                        '                - USDT\n'
                        '                - ETH\n'
                        '"""\n'
                    )
                elif 'transfer_token.csv' in file:
                    f.write('from_wallet,to_wallet,intermediary,amount\n')
                elif 'one_time_intermediary.csv' in file:
                    f.write('mnemonic,wallet_address,private_key,status\n')
                elif 'data/twitter/twitters.csv' in file:
                    f.write('nickname,auth_token,ct0\n')
                elif 'data/twitter/twitter_task.csv' in file:
                    f.write('еще в разработке\n')
            print(Fore.GREEN + f"File created: {file}")

def main_menu():
    check_and_create_files()
    try:
        print(Fore.GREEN + "\nWelcome to ETHmachine! 🌟")
        while True:
            action = select(
                f"Что вы хотите сделать?",
                choices=[
                    Choice('💲 BALANCES                     🌟 Проверить балансы нативка/токены', 'check_balances'),
                    Choice('💲 TRANSACTIONS                 🌟 Транзакции между кошельками', 'transactions'),
                    Choice('🚰 Faucets                      🌟 Краны', 'faucets'),
                    Choice('🐦 Twitter                      🌟 Сбор данных по твиттерам', 'twitter'),
                    #Choice('📊 Check project stats         🌟 Проверка статистики по проектам', 'project_stats'),
                    Choice('⛽ Check Gas Price              🌟 Проверить цену газа', 'check_gas_price'),
                    Choice('🪙  Generate Wallets             🌟 Генерация кошельков', 'generate_wallets'),
                    #Choice('🏦 CEX                          🌟 Функционал CEX', 'CEX_menu'),
                    Choice('🔑 ETH/SOL convert tool         🌟 Конвертация мнемоники/priv_key в wallet_address/priv_key', 'ETH_convert_tool'),
                    #Choice('🔍 Check Proxy                  🌟 Проверить прокси', 'check_proxy'),
                    #Choice('📖 INFO                         🌟 Информация о всех пунктах', 'info'),
                    Choice('❌ Exit', 'exit')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()

            match action:
                case 'check_balances':
                    blockchain = select(
                        "Выберите блокчейн:",
                        choices=[
                            Choice('💲 ETH', 'ETH'),
                            Choice('💲 SOL', 'SOL'),
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
                            Choice('🔄 Transfer Wallets to Wallets  🌟 Отправить токены между кошельками через третий кошелек (from_wallet,to_wallet,intermediary,amount)', 'transfer_wallets_to_wallets_call'),
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

                            # читаем данные из transfer_token.csv
                            import csv
                            transfer_data = []
                            try:
                                with open('data/transfer_token.csv', 'r', encoding='utf-8') as f:
                                    reader = csv.DictReader(f)
                                    for row in reader:
                                        if row['from_wallet'] and row['to_wallet'] and row['intermediary'] and row['amount']:
                                            transfer_data.append(row)
                            except Exception as e:
                                print(Fore.RED + f"Ошибка чтения data/transfer_token.csv: {e}")
                                continue

                            if not transfer_data:
                                print(Fore.RED + "Нет данных для отправки в data/transfer_token.csv")
                                continue

                            # --- Работа с прогресс-баром и прогресс-файлом ---
                            db_dir = "db"
                            if not os.path.exists(db_dir):
                                os.makedirs(db_dir)
                            progress_file = os.path.join(db_dir, "transfer_progress.json")

                            # Определяем прогресс
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
                                    # Удаляем старый прогресс-файл
                                    try:
                                        os.remove(progress_file)
                                    except Exception:
                                        pass
                            else:
                                # Если файла нет, создать пустой прогресс-файл (для явности)
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
                    #info()
                    print(Fore.GREEN + "\n\tИнформация о всех пунктах:\n")
                    print(Fore.YELLOW + "\t еще пишу, будет по позже.\n")
                    time.sleep(3)
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
                                Choice('💧 Somnia', 'Somnia_faucet'),
                                Choice('🔙 Back', 'back')
                            ],
                            qmark='🛠️',
                            pointer='👉'
                        ).ask()

                        match action:
                            case 'Somnia_faucet':
                                run_somnia_faucet()
                                continue

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
                    print(Fore.GREEN + f"\n\tФункционал CEX в разработке\n \tОбращайтесь с вопросами в тг https://t.me/DenisHumen")
                    time.sleep(3)
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
                            Choice('💲 Withdraw from OKX      🌟 Вывод с OKX', 'withdraw_from_okx'),
                            Choice('💲 Withdraw from Binance  🌟 Вывод с Binance', 'withdraw_from_binance'),
                            Choice('💲 Auto spot trade        🌟 Спотовая торговлять на бирже', 'spot_trade'),
                            Choice('🔙 Back', 'back')
                        ],
                        qmark='🛠️',
                        pointer='👉'
                    ).ask()

                    match action:
                        case 'spot_trade':
                            action = select(
                                'Выберите биржу:',
                                choices=[
                                    Choice('💲 Binance', 'binance'),
                                    Choice('💲 OKX', 'okx'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()

                            match action:
                                case 'binance':
                                    print(Fore.GREEN + f"\n\tВ разработке\n")
                                    continue
                                case 'okx':
                                    print(Fore.GREEN + f"\n\tВ разработке\n")
                                    continue
                                case 'back':
                                    continue

                        case 'withdraw_from_okx':
                            continue
                            #withdraw_from_okx()
                        case 'withdraw_from_binance':
                            continue
                            #withdraw_from_binance()



                        case 'spot_trade':
                            print(Fore.GREEN + f"\n\tПараметры задаются в config/config.py раздел НАСТРОЙКИ ФУНКЦИИ SPOT TRADE\n")
                            action = select(
                                'Выберите биржу:',
                                choices=[
                                    Choice('💲 Binance', 'binance'),
                                    Choice('💲 OKX', 'okx'),
                                    Choice('🔙 Back', 'back')
                                ],
                                qmark='🛠️',
                                pointer='👉'
                            ).ask()
                            print(Fore.GREEN + f"\n\tФункционал CEX в разработке")



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
