import csv
import random
import time
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from pathlib import Path

import requests
from colorama import Fore, Style, init
from web3 import Web3
from loguru import logger

init()

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

# Настройка логгера
log_dir = project_root / 'log'
log_dir.mkdir(exist_ok=True)

# Удаляем стандартный обработчик и добавляем свои
logger.remove()

# Консольный вывод с цветами
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)

# Файловый вывод для ошибок
logger.add(
    log_dir / "eth_token_balance_errors.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="ERROR",
    rotation="10 MB"
)

# Общий файловый вывод
logger.add(
    log_dir / "eth_token_balance.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="50 MB"
)

from config.config import NUM_THREADS, RETRY_COUNT
import config.token_address_erc20 as token_addresses
import config.rpc as rpc_config

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]

def load_wallets():
    """Загружает адреса кошельков из файла data/walletss.txt"""
    try:
        wallets_file = project_root / 'data' / 'walletss.txt'
        with open(wallets_file, 'r') as f:
            wallets = [line.strip() for line in f if line.strip()]
        return wallets
    except FileNotFoundError:
        logger.error("❌ Файл data/walletss.txt не найден!")
        return []

def load_proxies():
    """Загружает прокси из файла data/proxy.csv"""
    try:
        proxy_file = project_root / 'data' / 'proxy.csv'
        with open(proxy_file, 'r') as f:
            reader = csv.reader(f)
            proxies = [row[0] for row in reader if row]
        return proxies
    except FileNotFoundError:
        logger.warning("⚠️ Файл data/proxy.csv не найден! Работаем без прокси.")
        return []

def get_proxy_dict(proxy_string):
    """Преобразует строку прокси в формат для requests"""
    if not proxy_string:
        return None
    
    try:
        auth_part, address_part = proxy_string.split('@')
        login, password = auth_part.split(':')
        ip, port = address_part.split(':')
        
        proxy_url = f"http://{login}:{password}@{ip}:{port}"
        return {
            'http': proxy_url,
            'https': proxy_url
        }
    except:
        return None

def get_token_balance(wallet_address, rpc_url, token_address, proxy=None):
    """Получает баланс токена для указанного кошелька"""
    
    if not token_address:
        raise ValueError("Адрес токена не указан")
    
    session = requests.Session()
    try:
        if proxy:
            proxy_dict = get_proxy_dict(proxy)
            if proxy_dict:
                session.proxies.update(proxy_dict)
        
        w3 = Web3(Web3.HTTPProvider(rpc_url, session=session))
        
        if not w3.is_connected():
            raise ConnectionError(f"Не удалось подключиться к RPC: {rpc_url}")
        
        token_address = Web3.to_checksum_address(token_address)
        wallet_address = Web3.to_checksum_address(wallet_address)
        
        contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        
        balance_raw = contract.functions.balanceOf(wallet_address).call()
        decimals = contract.functions.decimals().call()
        
        balance = balance_raw / (10 ** decimals)
        
        return balance
        
    finally:
        session.close()

def get_rpc_urls_for_network(network):
    """Получает список RPC URL для указанной сети"""
    return getattr(rpc_config, network, None)

def get_random_rpc(rpc_urls):
    """Возвращает случайный RPC URL из списка"""
    if not rpc_urls:
        return None
    return random.choice(rpc_urls)

def process_wallet_task(wallet, proxy, rpc_urls, token_address):
    """Обрабатывает один кошелек с повторными попытками"""
    
    for attempt in range(RETRY_COUNT + 1):
        try:
            rpc_url = get_random_rpc(rpc_urls)
            if not rpc_url:
                raise ValueError("Нет доступных RPC URL")
                
            balance = get_token_balance(wallet, rpc_url, token_address, proxy)
            return wallet, balance, True
        
        except Exception as e:
            if attempt < RETRY_COUNT:
                proxy = random.choice(load_proxies()) if load_proxies() else None
                time.sleep(1)
                continue
            else:
                logger.error(f"❌ Ошибка для кошелька {wallet[:10]}...: {e}")
                return wallet, 0, False
    
    return wallet, 0, False

def process_wallet_task_all_tokens(wallet, proxy, rpc_urls, tokens_dict):
    """Обрабатывает один кошелек для всех токенов с повторными попытками"""
    
    wallet_results = {}
    
    for token_symbol, token_address in tokens_dict.items():
        for attempt in range(RETRY_COUNT + 1):
            try:
                rpc_url = get_random_rpc(rpc_urls)
                if not rpc_url:
                    raise ValueError("Нет доступных RPC URL")
                    
                balance = get_token_balance(wallet, rpc_url, token_address, proxy)
                wallet_results[token_symbol] = balance
                break
                
            except Exception as e:
                if attempt < RETRY_COUNT:
                    proxy = random.choice(load_proxies()) if load_proxies() else None
                    time.sleep(1)
                    continue
                else:
                    wallet_results[token_symbol] = 0
                    break
    
    return wallet, wallet_results, True

def save_results(results, token_symbol, wallets):
    try:
        """Сохраняет результаты в CSV файл с сохранением порядка"""
        result_dir = project_root / 'result'
        result_dir.mkdir(exist_ok=True)
        
        result_file = result_dir / 'result.csv'
        
        results_dict = {}
        for wallet, balance, success in results:
            results_dict[wallet] = (balance, success)
        
        with open(result_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['address', 'balance', 'token'])
            
            for wallet in wallets:
                if wallet in results_dict:
                    balance, success = results_dict[wallet]
                    if success:
                        writer.writerow([wallet, balance, token_symbol])
                    else:
                        writer.writerow([wallet, 0, token_symbol])
                else:
                    writer.writerow([wallet, 0, token_symbol])
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении результатов: {e}")
        raise

def save_results_all_tokens(results, tokens_dict, wallets):
    try:
        """Сохраняет результаты всех токенов в CSV файл (каждый кошелек в одной строке) с сохранением порядка"""
        result_dir = project_root / 'result'
        result_dir.mkdir(exist_ok=True)
        
        result_file = result_dir / 'result.csv'
        
        results_dict = {}
        for wallet, token_balances, success in results:
            results_dict[wallet] = (token_balances, success)
        
        with open(result_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            header = ['address'] + [token_symbol.upper() for token_symbol in tokens_dict.keys()]
            writer.writerow(header)
            
            for wallet in wallets:
                if wallet in results_dict:
                    token_balances, success = results_dict[wallet]
                    if success and isinstance(token_balances, dict):
                        row = [wallet]
                        for token_symbol in tokens_dict.keys():
                            balance = token_balances.get(token_symbol, 0)
                            row.append(balance)
                        writer.writerow(row)
                    else:
                        row = [wallet] + [0] * len(tokens_dict)
                        writer.writerow(row)
                else:
                    row = [wallet] + [0] * len(tokens_dict)
                    writer.writerow(row)
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении результатов: {e}")
        raise


def check_token_balances_menu():
    """Меню для выбора сети и проверки балансов токенов"""
    from modules.eth.rpc_return_module import get_network_rpc_selection, get_token_selection_for_network
    
    rpc_urls_list, network_type, clean_network = get_network_rpc_selection()
    if rpc_urls_list is None:
        return
    
    token_symbol, token_data = get_token_selection_for_network(clean_network)
    if token_symbol is None:
        return
    
    if token_symbol == 'ALL_TOKENS':
        check_all_tokens_balances(rpc_urls_list, network_type, clean_network, token_data)
    else:
        check_token_balances(rpc_urls_list, network_type, clean_network, token_symbol, token_data)

def check_all_tokens_balances(rpc_urls_list, network_type, clean_network, tokens_dict):
    """Функция для проверки балансов всех токенов"""
    
    if not rpc_urls_list:
        logger.error(f"❌ RPC URLs для сети {clean_network} не найдены!")
        return
    
    logger.info(Fore.MAGENTA + "="*80)
    logger.info(Fore.YELLOW + f"🚀 Начинаем проверку балансов ВСЕХ токенов")
    logger.info(Fore.CYAN + f"🌐 Сеть: {clean_network} ({network_type})")
    logger.info(Fore.CYAN + f"🪙 Количество токенов: {len(tokens_dict)}")
    logger.info(Fore.CYAN + f"🔗 RPC URLs: {len(rpc_urls_list)} шт.")
    logger.info(Fore.CYAN + f"🧵 Потоков: {NUM_THREADS}")
    logger.info(Fore.MAGENTA + "="*80)
    
    wallets = load_wallets()
    proxies_list = load_proxies()
    
    if not wallets:
        logger.error("❌ Нет кошельков для обработки!")
        return
    
    logger.info(Fore.GREEN + f"📂 Загружено {len(wallets)} кошельков")
    logger.info(Fore.GREEN + f"🔗 Загружено {len(proxies_list)} прокси")
    
    total_wallets = len(wallets)
    completed_wallets = 0
    bar_length = 50
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_cycle = cycle(spinner)
    
    results = []
    successful_count = 0
    failed_count = 0
    
    logger.info(Fore.MAGENTA + "-"*80)
    logger.info(Fore.YELLOW + "🔄 Начинаем обработку кошельков...")
    logger.info(Fore.MAGENTA + "\n" + "-"*80)
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_wallet = {
            executor.submit(
                process_wallet_task_all_tokens, 
                wallet, 
                proxies_list[i % len(proxies_list)] if proxies_list else None,
                rpc_urls_list,
                tokens_dict
            ): wallet
            for i, wallet in enumerate(wallets)
        }
        
        for future in as_completed(future_to_wallet):
            wallet = future_to_wallet[future]
            try:
                wallet_result, token_balances, success = future.result(timeout=60)
                results.append((wallet_result, token_balances, success))
                
                if success:
                    successful_count += 1
                    tokens_with_balance = sum(1 for balance in token_balances.values() if balance > 0)
                    status_info = f"Токенов с балансом: {tokens_with_balance}/{len(tokens_dict)}"
                else:
                    failed_count += 1
                    status_info = "Ошибка получения балансов"
                    wallet_result = wallet
                
            except Exception as e:
                failed_count += 1
                results.append((wallet, {}, False))
                status_info = f"Исключение: {str(e)[:20]}..."
                wallet_result = wallet
                logger.error(f"Исключение при обработке кошелька {wallet}: {e}")
            
            finally:
                completed_wallets += 1
                progress = int((completed_wallets / total_wallets) * bar_length)
                progress_percent = (completed_wallets / total_wallets) * 100
                bar = "█" * progress + "░" * (bar_length - progress)
                spinner_frame = next(spinner_cycle)
                
                remaining_wallets = total_wallets - completed_wallets
                
                print(
                    f"\r{Fore.BLUE}[{bar}] {completed_wallets}/{total_wallets} ({progress_percent:.1f}%) | "
                    f"{spinner_frame} | ✅{successful_count} | ❌{failed_count} | "
                    f"Осталось: {remaining_wallets} | {wallet_result[:10]}...{wallet_result[-6:]} | {status_info}{Style.RESET_ALL}",
                    end="\n" if progress_percent >= 100 else "",
                    flush=True,
                )
                
                if progress_percent >= 100:
                    print()
    
    logger.info(Fore.MAGENTA + "\n" + "="*80)
    logger.info(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА:")
    logger.info(Fore.GREEN + f"✅ Успешно обработано: {successful_count}")
    logger.info(Fore.RED + f"❌ Ошибок: {failed_count}")
    logger.info(Fore.CYAN + f"📈 Процент успеха: {(successful_count/total_wallets)*100:.1f}%")
    
    logger.info(Fore.CYAN + "💾 Сохраняем результаты...")
    saved = save_results_all_tokens(results, tokens_dict, wallets)
    if saved:
        logger.info(Fore.GREEN + "✅ Результаты сохранены в result/result.csv")
    else:
        logger.error("❌ Не удалось сохранить результаты!")
    logger.info(Fore.MAGENTA + "="*80 + "\n")
    
    try:
        from modules.notifications import send_telegram_notification
        result_file_path = project_root / 'result' / 'result.csv'
        send_telegram_notification(
            notif_type="success",
            title="Проверка балансов всех токенов завершена",
            message=f"Сеть: {clean_network} ({network_type})\nТокенов: {len(tokens_dict)}\nУспешно: {successful_count}\nОшибок: {failed_count}",
            main_title="Баланс чек завершён",
            file_path=str(result_file_path)
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")

def check_token_balances(rpc_urls_list, network_type, clean_network, token_symbol, token_address):
    """Основная функция для проверки балансов токенов"""
    
    if not rpc_urls_list:
        logger.error(f"❌ RPC URLs для сети {clean_network} не найдены!")
        return
    
    logger.info(Fore.MAGENTA + "="*80)
    logger.info(Fore.YELLOW + f"🚀 Начинаем проверку балансов токена:")
    logger.info(f"🪙 {Fore.GREEN}{token_symbol.upper()}{Fore.RESET} ({Fore.BLUE}{token_address}{Fore.RESET})")
    logger.info(Fore.CYAN + f"🌐 Сеть: {clean_network} ({network_type})")
    logger.info(Fore.CYAN + f"🔗 RPC URLs: {len(rpc_urls_list)} шт.")
    logger.info(Fore.CYAN + f"🧵 Потоков: {NUM_THREADS}")
    logger.info(Fore.MAGENTA + "="*80)
    
    wallets = load_wallets()
    proxies_list = load_proxies()
    
    if not wallets:
        logger.error("❌ Нет кошельков для обработки!")
        return
    
    logger.info(Fore.GREEN + f"📂 Загружено {len(wallets)} кошельков")
    logger.info(Fore.GREEN + f"🔗 Загружено {len(proxies_list)} прокси")
    
    total_wallets = len(wallets)
    completed_wallets = 0
    bar_length = 50
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_cycle = cycle(spinner)
    
    results = []
    successful_count = 0
    failed_count = 0
    
    logger.info(Fore.MAGENTA + "-"*80)
    logger.info(Fore.YELLOW + "🔄 Начинаем обработку кошельков...")
    logger.info(Fore.MAGENTA + "-"*80 + "\n")
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_wallet = {
            executor.submit(
                process_wallet_task, 
                wallet, 
                proxies_list[i % len(proxies_list)] if proxies_list else None,
                rpc_urls_list,
                token_address
            ): wallet
            for i, wallet in enumerate(wallets)
        }
        
        for future in as_completed(future_to_wallet):
            wallet = future_to_wallet[future]
            try:
                wallet_result, balance, success = future.result(timeout=30)
                results.append((wallet_result, balance, success))
                
                if success:
                    successful_count += 1
                    status_icon = "✅"
                    status_color = Fore.GREEN
                    balance_info = f"Баланс: {Fore.GREEN}{balance:.6f}{Fore.RESET} {Fore.GREEN}{token_symbol.upper()}{Fore.RESET}"
                else:
                    failed_count += 1
                    status_icon = "❌"
                    status_color = Fore.RED
                    balance_info = "Ошибка получения баланса"
                
            except Exception as e:
                failed_count += 1
                results.append((wallet, 0, False))
                status_icon = "❌"
                status_color = Fore.RED
                balance_info = f"Необработанное исключение: {e}"
                wallet_result = wallet
                logger.error(f"Исключение при обработке кошелька {wallet}: {e}")
            
            finally:
                completed_wallets += 1
                progress = int((completed_wallets / total_wallets) * bar_length)
                progress_percent = (completed_wallets / total_wallets) * 100
                bar = "█" * progress + "░" * (bar_length - progress)
                spinner_frame = next(spinner_cycle)
                
                remaining_wallets = total_wallets - completed_wallets
                
                print(
                    f"\r{Fore.BLUE}[{bar}] {completed_wallets}/{total_wallets} ({progress_percent:.1f}%) | "
                    f"{spinner_frame} | ✅{successful_count} | ❌{failed_count} | "
                    f"Осталось: {remaining_wallets} | {status_color}{status_icon} {wallet_result[:10]}...{wallet_result[-6:]} | {balance_info}{Style.RESET_ALL}",
                    end="",
                    flush=True,
                )
    
    logger.info(Fore.MAGENTA + "\n\n")
    logger.info(Fore.MAGENTA + "="*80)
    logger.info(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА:")
    logger.info(Fore.GREEN + f"✅ Успешно обработано: {successful_count}")
    logger.info(Fore.RED + f"❌ Ошибок: {failed_count}")
    logger.info(Fore.CYAN + f"📈 Процент успеха: {(successful_count/total_wallets)*100:.1f}%")
    
    logger.info(Fore.CYAN + "💾 Сохраняем результаты...")
    saved = save_results(results, token_symbol, wallets)
    if saved:
        logger.info(Fore.GREEN + "✅ Результаты сохранены в result/result.csv")
    else:
        logger.error("❌ Не удалось сохранить результаты!")
    logger.info(Fore.MAGENTA + "="*80 + "\n")
    
    try:
        from modules.notifications import send_telegram_notification
        result_file_path = project_root / 'result' / 'result.csv'
        send_telegram_notification(
            notif_type="success",
            title=f"Проверка балансов токена {token_symbol.upper()} завершена",
            message=f"Сеть: {clean_network} ({network_type})\nТокен: {token_symbol.upper()}\nУспешно: {successful_count}\nОшибок: {failed_count}",
            main_title="Баланс чек завершён",
            file_path=str(result_file_path)
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")