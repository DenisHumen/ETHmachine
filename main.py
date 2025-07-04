import os
import csv
import time
import json
import random

from concurrent.futures import ThreadPoolExecutor, as_completed

from colorama import Fore, init
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from questionary import Choice, select

from config.rpc import (
    L1, base, sepolia, arbitrum, optimism, soneium, Polygon, Binance_Smart_Chain,
    Avalanche, Fantom, Gravity_Alpha_Mainnet, monad_testnet, sahara_testnet, zora,
    somnia_testnet, mega_eth_testnet, Abstract, pharos_testnet, camp_testnet
)
from config.config import (
    NUM_THREADS, expected_completion_time, NICE_ADDRESS_WORDS_enable, REPEATED_CHAR_COUNT_enable
)

# Импорт функций из модулей
from modules.get_wallet_balance import get_wallet_balance
from modules.get_wallet_balance_fast import get_wallet_balance_fast
from modules.get_token_wallet_balance_fast import check_token_balances
from modules.get_gas_price import get_gas_price
from modules.sum_balances import sum_balances
from modules.get_transaction_count import get_transaction_count

from modules.cex.okx_withdraw import withdraw_from_okx, get_balances_okx
from modules.GitHub.check_version import check_version

from modules.eth.eth_wallet_generator import eth_generate_wallets
from modules.eth.eth_nice_address import eth_generate_nice_wallets
from modules.eth.eth_mnemonic_to_privkey import process_mnemonics
from modules.eth.private_key_to_wallet_address import process_private_keys

from modules.sol.sol_wallet_generator import sol_generate_wallets
from modules.sol.sol_nice_address import sol_generate_nice_wallets
from modules.sol.sol_mnemonic_to_privkey import sol_process_mnemonics

from modules.transefer_wallets_to_wallets import (
    transefer_wallets_to_wallets, process_wallets_transfer, get_proxy_list
)

from modules.stats_modules.pharos_stats import pharos_wallet_stats

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

# менюшку позимствовал у askaer, покупайте его скрипты :)
# позже шайтан код переделайю на case вместо if-elif, а то пиздец

def check_and_create_files():
    required_files = [
        'result/result.csv',
        'result/transaction_count_result.csv',
        'data/proxy.csv',
        'data/walletss.txt',
        'data/cex_settings.py',
        'data/transfer_token.csv',
        'data/mnemonic.txt',
        'db/transfer_progress.json',
        'data/one_time_intermediary.csv',
        'data/private_keys.txt'
    ]
    required_directories = ['result', 'data', 'db']

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
                    )
                elif 'transfer_token.csv' in file:
                    f.write('from_wallet,to_wallet,intermediary,amount\n')
                elif 'one_time_intermediary.csv' in file:
                    f.write('mnemonic,wallet_address,private_key,status\n')
            print(Fore.GREEN + f"File created: {file}")

def main_menu():
    check_and_create_files()
    try:
        while True:
            action = select(
                f"What do you want to do?",
                choices=[
                    Choice('💲 Check Balances | Проверить балансы', 'check_balances'),
                    Choice('🔧 Check Token Balances | Проверить балансы токенов', 'check_token_balances'),
                    Choice('📊 Check project stats | Проверка статистики по проектам', 'project_stats'),
                    Choice('💰 Sum Balances | Суммировать балансы', 'sum_balances'),
                    Choice('⛽ Check Gas Price | Проверить цену газа', 'check_gas_price'),
                    Choice('🔢 Check Transaction Count | Количество транзакций в выбранной сети', 'check_transaction_count'),
                    Choice('🪙  Generate Wallets | Генерация кошельков', 'generate_wallets'),
                    Choice('🏦 CEX | Функционал CEX', 'CEX_menu'),
                    Choice('🔄 Transfer Wallets to Wallets | Отправить токены между кошельками через третий кошелек (from_wallet,to_wallet,intermediary,amount)', 'transefer_wallets_to_wallets_call'),
                    Choice('🔑 ETH/SOL convert tool | Конвертация мнемоники/priv_key в wallet_address/priv_key', 'ETH_convert_tool'),
                    Choice('🔍 Check Proxy | Проверить прокси', 'check_proxy'),
                    Choice('🌐 Check All Balances Across Networks | Проверить все балансы во всех сетях', 'check_all_balances'),  # New option
                    Choice('❌ Exit | Выход', 'exit')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()

            match action:




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

                        match action:
                            case 'pharos_stats':

                                pharos_wallet_stats()
                                # print(Fore.GREEN + "\n\tСтатистика берется из сайта https://pharos-stats.vercel.app/\n")
                                # print(Fore.YELLOW + "\n\tНа данный момент чекер находится в разработке, сейчас не работает\n")
                                # print(Fore.YELLOW + "\tЕсли хотите добавить другие сети, то пишите в тг https://t.me/DenisHumen\n")
                                # animation = [
                                #     "🕐",
                                #     "🕑",
                                #     "🕒",
                                #     "🕓",
                                #     "🕔",
                                #     "🕕",
                                #     "🕖",
                                #     "🕗",
                                #     "🕘",
                                #     "🕙",
                                #     "🕚",
                                #     "🕛",
                                #     "🕐",
                                #     "🕑",
                                #     "🕒",
                                #     "🕓",
                                #     "🕔",
                                #     "🕕",
                                #     "🕖",
                                #     "🕗",
                                #     "🕘",
                                #     "🕙",
                                #     "🕚",
                                #     "🕛",
                                #     "🕐",
                                #     "🕑",
                                #     "🕒",
                                #     "🕓",
                                #     "🕔",
                                #     "🕕",
                                #     "🕖",
                                #     "🕗",
                                #     "🕘",
                                #     "🕙",
                                #     "🕚",
                                #     "🕛"
                                # ]
                                # for frame in animation:
                                #     print(Fore.GREEN + f"\r{frame}", end='', flush=True)
                                #     time.sleep(0.1)
                                # print()
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
                    print(Fore.GREEN + "\n\t❤️‍🔥 Спасибо за использование ETHmachine! \n \t❤️‍🔥 Если есть вопросы и предложения то в тг https://t.me/DenisHumen!\n\n")
                    #time.sleep(3)
                    break
                
                case 'CEX_menu':
                    print(Fore.GREEN + f"\n\tФункционал CEX в разработке\n \tОбращайтесь с вопросами в тг https://t.me/DenisHumen")
                    time.sleep(3)
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
                                    print(Fore.RED + "Конвертация мнемонической фразы в приватный ключ для SOL еще в работе, скоро будет доступна!\n")
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

                case 'sum_balances':
                    print(Fore.GREEN + "Summing balances from result/result.csv...")
                    try:
                        with open('result/result.csv', 'r', encoding='utf-8') as csvfile:
                            reader = csv.reader(csvfile)
                            data = list(reader)
                            if len(data) <= 1:
                                print(Fore.RED + "Error: result/result.csv is empty. Please run balance check first.")
                            else:
                                sum_balances('result/result.csv')
                    except FileNotFoundError:
                        print(Fore.RED + "Error: result/result.csv not found. Please run balance check first.")
                    except Exception as e:
                        print(Fore.RED + f"Error: {e}")
                    continue

                case 'check_all_balances': 
                    print(Fore.GREEN + f"\n\tФункционал CEX в разработке\n \tОбращайтесь с вопросами в тг https://t.me/DenisHumen")
                    time.sleep(3)
                    continue

                case 'transefer_wallets_to_wallets_call':
                    # выбор сети
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

                case'back':
                    continue

                case 'check_balances' | 'check_gas_price' | 'check_transaction_count':
                    menu_funcs = {
                        'check_balances': check_balances_menu,
                        'check_gas_price': check_gas_price_menu,
                        'check_transaction_count': check_transaction_count_menu
                    }
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
                    if network_type in ['mainnet', 'testnet']:
                        network_choices = list(mainnet_rpc_urls.keys()) if network_type == 'mainnet' else list(testnet_rpc_urls.keys())
                        network = select(
                            "Which network do you want to check?",
                            choices=[Choice(n, n) for n in network_choices] + [Choice('🔙 Back', 'back')],
                            qmark='🛠️',
                            pointer='👉'
                        ).ask()

                        if network == 'back':
                            continue

                        menu_funcs[action](network, network_type)

                case 'check_token_balances':
                    from modules.get_token_wallet_balance_fast import check_token_balances_menu
                    check_token_balances_menu()

    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_balances_menu(network, network_type):
    try:
        mode = select(
            "Select mode:",
            choices=[
                Choice('🚀 Fast (requires proxies)', 'fast'),
                Choice('🐢 Slow (no proxies)', 'slow'),
                Choice('🔙 Back', 'back')
            ],
            qmark='🛠️',
            pointer='👉'
        ).ask()

        if mode == 'back':
            return

        with open('data/walletss.txt', 'r', encoding='utf-8') as file:
            wallet_addresses = file.readlines()

        rpc_urls = mainnet_rpc_urls if network_type == 'mainnet' else testnet_rpc_urls

        if mode == 'fast':
            check_balances_fast(wallet_addresses, network, random.choice(rpc_urls[network]))
        else:
            check_balances_slow(wallet_addresses, network, random.choice(rpc_urls[network]))
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def format_proxy(proxy):
    if not proxy.startswith('http://'):
        return 'http://' + proxy
    return proxy

def get_with_retry(func, address, rpc_url, proxies):
    while True:
        try:
            if func == get_wallet_balance_fast:
                return func(address, rpc_url, [format_proxy(proxy) for proxy in proxies])
            else:
                return func(address, rpc_url)
        except Exception as e:
            if '429 Client Error: Too Many Requests' in str(e) or 'ProxyError' in str(e) or '407 Proxy Authentication Required' in str(e):
                if proxies:
                    proxy = random.choice(proxies)
                    proxies.remove(proxy)
                    # Continue retrying with new proxy without printing the error
                else:
                    return 'N/A'
            elif 'Failed to parse' in str(e):
                tqdm.write(Fore.RED + f"Error with proxy: {e}")
                tqdm.set_description("Error occurred", refresh=True)
                tqdm.colour = "red"
                input(Fore.RED + "Press Enter to continue...")
                return 'N/A'
            else:
                raise e

def check_balances_fast(wallet_addresses, network, rpc_url):
    try:
        with open('data/proxy.csv', 'r', encoding='utf-8') as file:
            proxies = file.readlines()[1:]

        if len(proxies) == 0:
            print(Fore.RED + "ERROR: No proxies found in data/proxy.csv")
            return
        elif len(proxies) < len(wallet_addresses):
            print(Fore.YELLOW + "WARNING: Так как прокси меньше кошельков, будут браться рандомно.")
        else:
            print(Fore.GREEN + "INFO: Прокси больше или равны количеству кошельков, будет использоваться 1к1.")

        results = {addr.strip(): 'N/A' for addr in wallet_addresses}

        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            with logging_redirect_tqdm():
                future_to_address = {executor.submit(get_with_retry, get_wallet_balance_fast, addr.strip(), rpc_url, [format_proxy(proxy) for proxy in proxies.copy()]): addr for addr in wallet_addresses}
                for future in tqdm(as_completed(future_to_address), total=len(wallet_addresses), desc="Checking balances", unit="wallet", colour="green"):
                    address = future_to_address[future]
                    try:
                        balance = future.result()
                        results[address.strip()] = balance if balance is not None else 'N/A'
                    except Exception as e:
                        tqdm.write(Fore.RED + f"Error checking balance for {address.strip()}: {e}")
                        tqdm.set_description("Error occurred", refresh=True)
                        tqdm.colour = "red"
                        input(Fore.RED + "Press Enter to continue...")
                        return

        with open('result/result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'balance', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for address in wallet_addresses:
                writer.writerow({'address': address.strip(), 'balance': results[address.strip()], 'network': network})

        print(Fore.GREEN + f"\n\n\nBalances checked and saved in result/result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_balances_slow(wallet_addresses, network, rpc_url):
    try:
        results = {addr.strip(): 'N/A' for addr in wallet_addresses}

        with open('result/result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'balance', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for address in tqdm(wallet_addresses, desc="Checking balances", unit="wallet"):
                address = address.strip()
                balance = get_wallet_balance(address, rpc_url)
                time.sleep(1)
                results[address] = balance

            for address in wallet_addresses:
                writer.writerow({'address': address.strip(), 'balance': results[address.strip()], 'network': network})

        print(Fore.GREEN + f"\n\n\nBalances checked and saved in result/result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_gas_price_menu(network, network_type):
    try:
        rpc_urls = mainnet_rpc_urls if network_type == 'mainnet' else testnet_rpc_urls
        gas_price = get_gas_price(random.choice(rpc_urls[network]))
        if gas_price is not None:
            print(Fore.GREEN + f"\n\n\n⛽ Current gas price on {network}: {gas_price} Gwei\n")
        else:
            print(Fore.RED + f"\n\n\n❌ Failed to retrieve gas price for {network}.\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_transaction_count_menu(network, network_type):
    try:
        mode = select(
            "Select mode:",
            choices=[
                Choice('🚀 Fast (requires proxies)', 'fast'),
                Choice('🐢 Slow (no proxies)', 'slow')
            ],
            qmark='🛠️',
            pointer='👉'
        ).ask()

        with open('data/walletss.txt', 'r', encoding='utf-8') as file:
            wallet_addresses = file.readlines()

        rpc_urls = mainnet_rpc_urls if network_type == 'mainnet' else testnet_rpc_urls

        if mode == 'fast':
            check_transaction_count_fast(wallet_addresses, network, random.choice(rpc_urls[network]))
        else:
            check_transaction_count_slow(wallet_addresses, network, random.choice(rpc_urls[network]))
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_transaction_count_fast(wallet_addresses, network, rpc_url):
    try:
        with open('data/proxy.csv', 'r', encoding='utf-8') as file:
            proxies = file.readlines()[1:]

        if len(proxies) == 0:
            print(Fore.RED + "ERROR: No proxies found in data/proxy.csv")
            return
        elif len(proxies) < len(wallet_addresses):
            print(Fore.YELLOW + "WARNING: Так как прокси меньше кошельков, будут браться рандомно.")
        else:
            print(Fore.GREEN + "INFO: Прокси больше или равны количеству кошельков, будет использоваться 1к1.")

        results = {addr.strip(): 'N/A' for addr in wallet_addresses}

        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            with logging_redirect_tqdm():
                future_to_address = {executor.submit(get_with_retry, get_transaction_count, addr.strip(), rpc_url, [format_proxy(proxy) for proxy in proxies.copy()]): addr for addr in wallet_addresses}
                for future in tqdm(as_completed(future_to_address), total=len(wallet_addresses), desc="Checking transaction counts", unit="wallet", colour="green"):
                    address = future_to_address[future]
                    try:
                        count = future.result()
                        results[address.strip()] = count if count is not None else 'N/A'
                    except Exception as e:
                        tqdm.write(Fore.RED + f"Error checking transaction count for {address.strip()}: {e}")
                        tqdm.set_description("Error occurred", refresh=True)
                        tqdm.colour = "red"
                        input(Fore.RED + "Press Enter to continue...")
                        return

        with open('result/transaction_count_result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'transaction_count', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for address in wallet_addresses:
                writer.writerow({'address': address.strip(), 'transaction_count': results[address.strip()], 'network': network})

        print(Fore.GREEN + f"\n\n\nTransaction counts checked and saved in result/transaction_count_result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_transaction_count_slow(wallet_addresses, network, rpc_url):
    try:
        results = {addr.strip(): 'N/A' for addr in wallet_addresses}

        with open('result/transaction_count_result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'transaction_count', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for address in tqdm(wallet_addresses, desc="Checking transaction counts", unit="wallet"):
                address = address.strip()
                count = get_transaction_count(address, rpc_url)
                time.sleep(1)
                results[address] = count

            for address in wallet_addresses:
                writer.writerow({'address': address.strip(), 'transaction_count': results[address.strip()], 'network': network})

        print(Fore.GREEN + f"\n\n\nTransaction counts checked and saved in result/transaction_count_result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

if __name__ == "__main__":
    check_version("ETHmachine")
    main_menu()

