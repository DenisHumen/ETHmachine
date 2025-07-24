import csv
import random
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from pathlib import Path
from datetime import datetime, timedelta

import requests
from colorama import Fore, Style, init
from web3 import Web3

init()

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import NUM_THREADS, RETRY_COUNT

def load_wallets():
    """Загружает адреса кошельков из файла data/walletss.txt"""
    try:
        wallets_file = project_root / 'data' / 'walletss.txt'
        with open(wallets_file, 'r') as f:
            wallets = [line.strip() for line in f if line.strip()]
        return wallets
    except FileNotFoundError:
        print(Fore.RED + "❌ Файл data/walletss.txt не найден!")
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
        print(Fore.YELLOW + "⚠️ Файл data/proxy.csv не найден! Работаем без прокси.")
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

def get_assigned_proxy(wallet_index, proxies_list):
    """Назначает прокси кошельку по алгоритму"""
    if not proxies_list:
        return None
    
    num_wallets = wallet_index + 1  # Индекс начинается с 0
    num_proxies = len(proxies_list)
    
    if num_proxies >= num_wallets:
        # Если прокси больше или равно кошелькам, берем по порядку
        return proxies_list[wallet_index % num_proxies]
    else:
        # Если прокси меньше кошельков, берем по порядку и повторяем цикл
        return proxies_list[wallet_index % num_proxies]

def get_reserve_proxy(proxies_list):
    """Возвращает случайную резервную прокси"""
    if not proxies_list:
        return None
    return random.choice(proxies_list)

def get_short_error_message(error_str):
    """Преобразует длинные технические ошибки в короткие понятные сообщения"""
    error_lower = error_str.lower()
    
    if 'connection' in error_lower or 'timeout' in error_lower:
        return 'Ошибка подключения'
    elif 'poa chain' in error_lower or 'extradata' in error_lower:
        return 'Несовместимая сеть (POA)'
    elif 'too many requests' in error_lower or '429' in error_str:
        return 'Превышен лимит запросов'
    elif 'proxy' in error_lower:
        return 'Ошибка прокси'
    elif 'authentication' in error_lower:
        return 'Ошибка аутентификации'
    elif 'not found' in error_lower or '404' in error_str:
        return 'RPC не найден'
    elif 'internal server error' in error_lower or '500' in error_str:
        return 'Внутренняя ошибка сервера'
    elif 'bad gateway' in error_lower or '502' in error_str:
        return 'Плохой шлюз'
    elif 'service unavailable' in error_lower or '503' in error_str:
        return 'Сервис недоступен'
    elif 'gateway timeout' in error_lower or '504' in error_str:
        return 'Таймаут шлюза'
    elif 'json' in error_lower and 'decode' in error_lower:
        return 'Неверный ответ RPC'
    elif 'ssl' in error_lower or 'certificate' in error_lower:
        return 'Ошибка SSL сертификата'
    elif 'network is unreachable' in error_lower:
        return 'Сеть недоступна'
    elif 'name resolution failed' in error_lower or 'dns' in error_lower:
        return 'Ошибка DNS'
    else:
        # Возвращаем первые 30 символов оригинальной ошибки
        return error_str[:30] + '...' if len(error_str) > 30 else error_str

def get_wallet_balance_with_web3(wallet_address, rpc_urls, proxy=None):
    """Получает баланс нативного токена для кошелька через Web3 с перебором всех RPC"""
    
    proxies_list = load_proxies()
    current_proxy = proxy
    
    # Перебираем все RPC URLs
    for rpc_attempt, rpc_url in enumerate(rpc_urls):
        # Для каждого RPC пробуем несколько раз с разными прокси
        for attempt in range(RETRY_COUNT + 1):
            session = requests.Session()
            try:
                if current_proxy:
                    proxy_dict = get_proxy_dict(current_proxy)
                    if proxy_dict:
                        session.proxies.update(proxy_dict)
                
                w3 = Web3(Web3.HTTPProvider(rpc_url, session=session))
                
                if not w3.is_connected():
                    raise ConnectionError(f"Не удалось подключиться к RPC: {rpc_url}")
                
                checksum_address = w3.to_checksum_address(wallet_address)
                balance_wei = w3.eth.get_balance(checksum_address)
                balance_eth = w3.from_wei(balance_wei, 'ether')
                
                return float(balance_eth)
                
            except Exception as e:
                if attempt < RETRY_COUNT:
                    # Меняем прокси при ошибке
                    if proxies_list:
                        current_proxy = random.choice(proxies_list)
                    time.sleep(1)
                    continue
                else:
                    # Если все попытки для текущего RPC исчерпаны, переходим к следующему RPC
                    if rpc_attempt < len(rpc_urls) - 1:
                        # Меняем прокси для следующего RPC
                        if proxies_list:
                            current_proxy = random.choice(proxies_list)
                        break
                    else:
                        # Все RPC исчерпаны
                        raise Exception(get_short_error_message(str(e)))
            finally:
                session.close()
    
    # Если дошли до сюда, значит все RPC не сработали
    raise Exception("Все RPC недоступны")

def process_wallet_task(wallet_index, wallet, assigned_proxy, rpc_urls, reserve_proxies):
    """Обрабатывает один кошелек с повторными попытками"""
    
    current_proxy = assigned_proxy
    
    for attempt in range(RETRY_COUNT + 1):
        try:
            balance = get_wallet_balance_with_web3(wallet, rpc_urls, current_proxy)
            return wallet, balance, True
        
        except Exception as e:
            if attempt < RETRY_COUNT:
                # При ошибке используем резервную прокси
                current_proxy = get_reserve_proxy(reserve_proxies)
                time.sleep(1)
                continue
            else:
                error_msg = get_short_error_message(str(e))
                return wallet, 0, False
    
    return wallet, 0, False

def process_wallet_task_all_networks(wallet_index, wallet, assigned_proxy, all_networks, reserve_proxies):
    """Обрабатывает один кошелек для всех сетей"""
    
    wallet_results = {}
    
    for network_name, rpc_urls in all_networks.items():
        current_proxy = assigned_proxy
        
        for attempt in range(RETRY_COUNT + 1):
            try:
                balance = get_wallet_balance_with_web3(wallet, rpc_urls, current_proxy)
                wallet_results[network_name] = balance
                break
                
            except Exception as e:
                if attempt < RETRY_COUNT:
                    current_proxy = get_reserve_proxy(reserve_proxies)
                    time.sleep(1)
                    continue
                else:
                    wallet_results[network_name] = 0
                    break
    
    return wallet, wallet_results, True

def save_results(results, network_name, wallets):
    """Сохраняет результаты в CSV файл с сохранением порядка"""
    result_dir = project_root / 'result'
    result_dir.mkdir(exist_ok=True)
    
    result_file = result_dir / 'result.csv'
    
    results_dict = {}
    for wallet, balance, success in results:
        results_dict[wallet] = (balance, success)
    
    with open(result_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['address', 'balance', 'network'])
        
        for wallet in wallets:
            if wallet in results_dict:
                balance, success = results_dict[wallet]
                if success:
                    writer.writerow([wallet, balance, network_name])
                else:
                    writer.writerow([wallet, 0, network_name])
            else:
                writer.writerow([wallet, 0, network_name])

def save_results_all_networks(results, all_networks, wallets):
    """Сохраняет результаты всех сетей в CSV файл с сохранением порядка"""
    result_dir = project_root / 'result'
    result_dir.mkdir(exist_ok=True)
    
    result_file = result_dir / 'result.csv'
    
    results_dict = {}
    for wallet, network_balances, success in results:
        results_dict[wallet] = (network_balances, success)
    
    with open(result_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Создаем заголовок с названиями сетей
        header = ['address'] + [network_name.replace('🚀 ', '') for network_name in all_networks.keys()]
        writer.writerow(header)
        
        for wallet in wallets:
            if wallet in results_dict:
                network_balances, success = results_dict[wallet]
                if success and isinstance(network_balances, dict):
                    row = [wallet]
                    for network_name in all_networks.keys():
                        balance = network_balances.get(network_name, 0)
                        row.append(balance)
                    writer.writerow(row)
                else:
                    row = [wallet] + [0] * len(all_networks)
                    writer.writerow(row)
            else:
                row = [wallet] + [0] * len(all_networks)
                writer.writerow(row)

def format_time_remaining(seconds):
    """Форматирует оставшееся время в читаемый вид"""
    if seconds < 60:
        return f"{int(seconds)}с"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes}м {seconds}с"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}ч {minutes}м"

def get_estimated_completion_time(seconds_remaining):
    """Возвращает предполагаемое время завершения"""
    completion_time = datetime.now() + timedelta(seconds=seconds_remaining)
    return completion_time.strftime("%H:%M:%S")

def check_wallet_balances_single_network(rpc_urls_list, network_type, clean_network):
    """Функция для проверки балансов в одной сети"""
    
    if not rpc_urls_list:
        print(Fore.RED + f"❌ RPC URLs для сети {clean_network} не найдены!")
        return
    
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + f"🚀 Начинаем проверку балансов нативных токенов")
    print(Fore.CYAN + f"🌐 Сеть: {clean_network} ({network_type})")
    print(Fore.CYAN + f"🔗 RPC URLs: {len(rpc_urls_list)} шт.")
    print(Fore.CYAN + f"🧵 Потоков: {NUM_THREADS}")
    print(Fore.MAGENTA + "="*80)
    
    wallets = load_wallets()
    proxies_list = load_proxies()
    
    if not wallets:
        print(Fore.RED + "❌ Нет кошельков для обработки!")
        return
    
    print(Fore.GREEN + f"📂 Загружено {len(wallets)} кошельков")
    print(Fore.GREEN + f"🔗 Загружено {len(proxies_list)} прокси")
    
    total_wallets = len(wallets)
    completed_wallets = 0
    bar_length = 50
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_cycle = cycle(spinner)
    
    results = []
    successful_count = 0
    failed_count = 0
    
    # Для расчета времени
    start_time = time.time()
    
    print(Fore.MAGENTA + "\n" + "-"*80)
    print(Fore.YELLOW + "🔄 Начинаем обработку кошельков...")
    print(Fore.MAGENTA + "-"*80)
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_wallet = {
            executor.submit(
                process_wallet_task, 
                i,
                wallet,
                get_assigned_proxy(i, proxies_list),
                rpc_urls_list,
                proxies_list
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
                    balance_info = f"Баланс: {Fore.GREEN}{balance:.6f}{Fore.RESET} {Fore.GREEN}ETH{Fore.RESET}"
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
                balance_info = f"Исключение: {str(e)[:20]}..."
                wallet_result = wallet
            
            finally:
                completed_wallets += 1
                progress = int((completed_wallets / total_wallets) * bar_length)
                progress_percent = (completed_wallets / total_wallets) * 100
                bar = "█" * progress + "░" * (bar_length - progress)
                spinner_frame = next(spinner_cycle)
                
                remaining_wallets = total_wallets - completed_wallets
                
                # Расчет времени
                elapsed_time = time.time() - start_time
                if completed_wallets > 0:
                    avg_time_per_wallet = elapsed_time / completed_wallets
                    estimated_remaining_time = avg_time_per_wallet * remaining_wallets
                    time_remaining_str = format_time_remaining(estimated_remaining_time)
                    completion_time_str = get_estimated_completion_time(estimated_remaining_time)
                    time_info = f"⏱️  {time_remaining_str} | 🎯 {completion_time_str}"
                else:
                    time_info = "⏱️Расчет... | 🎯--:--:--"
                
                print(
                    f"\r{Fore.BLUE}[{bar}] {completed_wallets}/{total_wallets} ({progress_percent:.1f}%) | "
                    f"{spinner_frame} | ✅{successful_count} | ❌{failed_count} | "
                    f"Осталось: {remaining_wallets} | {time_info} | {status_color}{status_icon} {wallet_result[:10]}...{wallet_result[-6:]} | {balance_info}{Style.RESET_ALL}",
                    end="",
                    flush=True,
                )
    
    print(Fore.MAGENTA + "\n\n" + "="*80)
    print(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА:")
    print(Fore.GREEN + f"✅ Успешно обработано: {successful_count}")
    print(Fore.RED + f"❌ Ошибок: {failed_count}")
    print(Fore.CYAN + f"📈 Процент успеха: {(successful_count/total_wallets)*100:.1f}%")
    
    total_time = time.time() - start_time
    print(Fore.CYAN + f"⏱️ Общее время выполнения: {format_time_remaining(total_time)}")
    
    print(Fore.CYAN + "\n💾 Сохраняем результаты...")
    save_results(results, clean_network, wallets)
    print(Fore.GREEN + "✅ Результаты сохранены в result/result.csv")
    print(Fore.MAGENTA + "="*80 + "\n")

def check_wallet_balances_all_networks(all_networks):
    """Функция для проверки балансов во всех сетях"""
    
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + f"🚀 Начинаем проверку балансов во ВСЕХ сетях")
    print(Fore.CYAN + f"🌐 Количество сетей: {len(all_networks)}")
    print(Fore.CYAN + f"🧵 Потоков: {NUM_THREADS}")
    print(Fore.MAGENTA + "="*80)
    
    wallets = load_wallets()
    proxies_list = load_proxies()
    
    if not wallets:
        print(Fore.RED + "❌ Нет кошельков для обработки!")
        return
    
    print(Fore.GREEN + f"📂 Загружено {len(wallets)} кошельков")
    print(Fore.GREEN + f"🔗 Загружено {len(proxies_list)} прокси")
    
    total_wallets = len(wallets)
    completed_wallets = 0
    bar_length = 50
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_cycle = cycle(spinner)
    
    results = []
    successful_count = 0
    failed_count = 0
    
    # Для расчета времени
    start_time = time.time()
    
    print(Fore.MAGENTA + "\n" + "-"*80)
    print(Fore.YELLOW + "🔄 Начинаем обработку кошельков...")
    print(Fore.MAGENTA + "-"*80)
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_wallet = {
            executor.submit(
                process_wallet_task_all_networks, 
                i,
                wallet,
                get_assigned_proxy(i, proxies_list),
                all_networks,
                proxies_list
            ): wallet
            for i, wallet in enumerate(wallets)
        }
        
        for future in as_completed(future_to_wallet):
            wallet = future_to_wallet[future]
            try:
                wallet_result, network_balances, success = future.result(timeout=60)
                results.append((wallet_result, network_balances, success))
                
                if success:
                    successful_count += 1
                    networks_with_balance = sum(1 for balance in network_balances.values() if balance > 0)
                    status_info = f"Сетей с балансом: {networks_with_balance}/{len(all_networks)}"
                else:
                    failed_count += 1
                    status_info = "Ошибка получения балансов"
                
            except Exception as e:
                failed_count += 1
                results.append((wallet, {}, False))
                status_info = f"Исключение: {str(e)[:20]}..."
                wallet_result = wallet
            
            finally:
                completed_wallets += 1
                progress = int((completed_wallets / total_wallets) * bar_length)
                progress_percent = (completed_wallets / total_wallets) * 100
                bar = "█" * progress + "░" * (bar_length - progress)
                spinner_frame = next(spinner_cycle)
                
                remaining_wallets = total_wallets - completed_wallets
                
                # Расчет времени
                elapsed_time = time.time() - start_time
                if completed_wallets > 0:
                    avg_time_per_wallet = elapsed_time / completed_wallets
                    estimated_remaining_time = avg_time_per_wallet * remaining_wallets
                    time_remaining_str = format_time_remaining(estimated_remaining_time)
                    completion_time_str = get_estimated_completion_time(estimated_remaining_time)
                    time_info = f"⏱️{time_remaining_str} | 🎯{completion_time_str}"
                else:
                    time_info = "⏱️Расчет... | 🎯--:--:--"
                
                print(
                    f"\r{Fore.BLUE}[{bar}] {completed_wallets}/{total_wallets} ({progress_percent:.1f}%) | "
                    f"{spinner_frame} | ✅{successful_count} | ❌{failed_count} | "
                    f"Осталось: {remaining_wallets} | {time_info} | {wallet_result[:10]}...{wallet_result[-6:]} | {status_info}{Style.RESET_ALL}",
                    end="",
                    flush=True,
                )
    
    print(Fore.MAGENTA + "\n\n" + "="*80)
    print(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА:")
    print(Fore.GREEN + f"✅ Успешно обработано: {successful_count}")
    print(Fore.RED + f"❌ Ошибок: {failed_count}")
    print(Fore.CYAN + f"📈 Процент успеха: {(successful_count/total_wallets)*100:.1f}%")
    
    total_time = time.time() - start_time
    print(Fore.CYAN + f"⏱️ Общее время выполнения: {format_time_remaining(total_time)}")
    
    print(Fore.CYAN + "\n💾 Сохраняем результаты...")
    save_results_all_networks(results, all_networks, wallets)
    print(Fore.GREEN + "✅ Результаты сохранены в result/result.csv")
    print(Fore.MAGENTA + "="*80 + "\n")

def check_wallet_balances_menu():
    """Главная функция для запуска проверки балансов кошельков"""
    from modules.eth.rpc_return_module import get_network_rpc_selection
    
    rpc_urls_list, network_type, clean_network = get_network_rpc_selection()
    if rpc_urls_list is None:
        return
    
    if rpc_urls_list == 'ALL_NETWORKS':
        # Проверяем все сети
        check_wallet_balances_all_networks(network_type)
    else:
        # Проверяем одну сеть
        check_wallet_balances_single_network(rpc_urls_list, network_type, clean_network)

