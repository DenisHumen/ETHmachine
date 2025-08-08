import csv
import random
import time
import sys
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from pathlib import Path
from datetime import datetime, timedelta

import requests
from colorama import Fore, Style, init
from web3 import Web3
from loguru import logger

init()

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import NUM_THREADS, RETRY_COUNT

def setup_error_logging():
    """Настраивает логирование ошибок в директорию log/"""
    log_dir = project_root / 'log'
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f'balance_check_errors_{timestamp}.log'
    
    # Настройка логгера
    logger = logging.getLogger('balance_checker')
    logger.setLevel(logging.ERROR)
    
    # Очищаем существующие обработчики
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Создаем обработчик для записи в файл
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.ERROR)
    
    # Форматирование логов с информацией о количестве попыток
    formatter = logging.Formatter(
        f'%(asctime)s | %(levelname)s | RETRY_COUNT={RETRY_COUNT} | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    
    return logger

def log_error(logger, wallet, error, proxy=None, rpc_url=None, network=None, attempt=None):
    """Записывает детальную информацию об ошибке в лог"""
    error_details = {
        'wallet': wallet,
        'error': str(error),
        'short_error': get_short_error_message(str(error)),
        'proxy': proxy[:20] + '...' if proxy and len(proxy) > 20 else proxy,
        'rpc_url': rpc_url,
        'network': network,
        'attempt': attempt,
        'timestamp': datetime.now().isoformat()
    }
    
    log_message = (
        f"Wallet: {error_details['wallet']} | "
        f"Network: {error_details['network']} | "
        f"Attempt: {error_details['attempt']} | "
        f"Proxy: {error_details['proxy']} | "
        f"RPC: {error_details['rpc_url']} | "
        f"Error: {error_details['short_error']} | "
        f"Full Error: {error_details['error']}"
    )
    
    logger.error(log_message)

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

def get_random_proxy_except_current(proxies_list, current_proxy):
    """Возвращает случайную прокси, отличную от текущей"""
    if not proxies_list:
        return None
    
    if len(proxies_list) <= 1:
        return proxies_list[0] if proxies_list else None
    
    available_proxies = [proxy for proxy in proxies_list if proxy != current_proxy]
    return random.choice(available_proxies) if available_proxies else random.choice(proxies_list)

def get_wallet_balance_with_web3(wallet_address, rpc_urls, proxy=None, logger=None, network_name=None):
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
                
                # Форматируем баланс чтобы избежать научной нотации
                return float(f"{balance_eth:.18f}")
                
            except Exception as e:
                # Логируем ошибку
                if logger:
                    log_error(logger, wallet_address, e, current_proxy, rpc_url, network_name, f"{attempt+1}/{RETRY_COUNT+1}")
                
                if attempt < RETRY_COUNT:
                    # Меняем прокси при ошибке на случайную, отличную от текущей
                    if proxies_list:
                        current_proxy = get_random_proxy_except_current(proxies_list, current_proxy)
                    time.sleep(random.uniform(1, 2))  # Добавляем случайную задержку
                    continue
                else:
                    # Если все попытки для текущего RPC исчерпаны, переходим к следующему RPC
                    if rpc_attempt < len(rpc_urls) - 1:
                        # Меняем прокси для следующего RPC на случайную
                        if proxies_list:
                            current_proxy = get_random_proxy_except_current(proxies_list, current_proxy)
                        break
                    else:
                        # Все RPC исчерпаны
                        raise Exception(get_short_error_message(str(e)))
            finally:
                session.close()
    
    # Если дошли до сюда, значит все RPC не сработали
    raise Exception("Все RPC недоступны")

def process_wallet_task(wallet_index, wallet, assigned_proxy, rpc_urls, reserve_proxies, logger=None, network_name=None):
    """Обрабатывает один кошелек с повторными попытками"""
    
    current_proxy = assigned_proxy
    
    for attempt in range(RETRY_COUNT + 1):
        try:
            balance = get_wallet_balance_with_web3(wallet, rpc_urls, current_proxy, logger, network_name)
            return wallet, balance, True
        
        except Exception as e:
            # Логируем ошибку на уровне задачи
            if logger:
                log_error(logger, wallet, e, current_proxy, None, network_name, f"Task attempt {attempt+1}/{RETRY_COUNT+1}")
            
            if attempt < RETRY_COUNT:
                # При ошибке используем случайную прокси, отличную от текущей
                current_proxy = get_random_proxy_except_current(reserve_proxies, current_proxy)
                time.sleep(random.uniform(1, 3))  # Случайная задержка между попытками
                continue
            else:
                error_msg = get_short_error_message(str(e))
                return wallet, 0, False
    
    return wallet, 0, False

def process_wallet_task_all_networks(wallet_index, wallet, assigned_proxy, all_networks, reserve_proxies, logger=None):
    """Обрабатывает один кошелек для всех сетей"""
    
    wallet_results = {}
    
    for network_name, rpc_urls in all_networks.items():
        current_proxy = assigned_proxy
        
        for attempt in range(RETRY_COUNT + 1):
            try:
                balance = get_wallet_balance_with_web3(wallet, rpc_urls, current_proxy, logger, network_name)
                wallet_results[network_name] = balance
                break
                
            except Exception as e:
                # Логируем ошибку для конкретной сети
                if logger:
                    log_error(logger, wallet, e, current_proxy, None, network_name, f"Network attempt {attempt+1}/{RETRY_COUNT+1}")
                
                if attempt < RETRY_COUNT:
                    # При ошибке используем случайную прокси, отличную от текущей
                    current_proxy = get_random_proxy_except_current(reserve_proxies, current_proxy)
                    time.sleep(random.uniform(1, 2))  # Случайная задержка между попытками
                    continue
                else:
                    wallet_results[network_name] = 0
                    break
    
    return wallet, wallet_results, True

def get_eth_price_usdt():
    """Получает актуальный курс ETH в USDT"""
    try:
        # Пробуем несколько API для получения курса
        apis = [
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
            "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT",
            "https://api.coinbase.com/v2/exchange-rates?currency=ETH"
        ]
        
        for api_url in apis:
            try:
                response = requests.get(api_url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    
                    if "coingecko" in api_url:
                        price = data.get('ethereum', {}).get('usd', 0)
                    elif "binance" in api_url:
                        price = float(data.get('price', 0))
                    elif "coinbase" in api_url:
                        rates = data.get('data', {}).get('rates', {})
                        price = float(rates.get('USD', 0))
                    else:
                        continue
                    
                    if price > 0:
                        logger.success(f"💰 Получен курс ETH: ${price:.2f} USDT")
                        return float(price)
                        
            except Exception as e:
                continue
        
        logger.warning("⚠️ Не удалось получить курс ETH, стоимость в USDT не будет рассчитана")
        return 0
        
    except Exception as e:
        logger.warning(f"⚠️ Ошибка получения курса ETH: {e}")
        return 0

def is_mainnet_network(network_name):
    """Проверяет, является ли сеть mainnet через модуль rpc_return_module"""
    try:
        from modules.eth.rpc_return_module import mainnet_rpc_urls
        # Проверяем как по полному имени, так и по очищенному
        clean_name = network_name.replace('🚀 ', '')
        return network_name in mainnet_rpc_urls or clean_name in [net.replace('🚀 ', '') for net in mainnet_rpc_urls.keys()]
    except ImportError:
        # Fallback список mainnet сетей
        mainnet_networks = [
            '🚀 Ethereum Mainnet',
            'Ethereum Mainnet',
            '🚀 Base', 
            'Base',
            '🚀 Arbitrum One',
            'Arbitrum One',
            '🚀 Optimism',
            'Optimism',
            '🚀 Soneium',
            'Soneium',
            '🚀 Polygon',
            'Polygon',
            '🚀 Binance Smart Chain',
            'Binance Smart Chain',
            '🚀 Avalanche',
            'Avalanche',
            '🚀 Fantom',
            'Fantom',
            '🚀 Gravity Alpha Mainnet',
            'Gravity Alpha Mainnet',
            '🚀 Zora',
            'Zora',
            '🚀 Abstract',
            'Abstract'
        ]
        return network_name in mainnet_networks

def save_results(results, network_name, wallets, network_type=None):
    try:
        """Сохраняет результаты в CSV файл с сохранением порядка"""
        result_dir = project_root / 'result'
        result_dir.mkdir(exist_ok=True)
        
        result_file = result_dir / 'result.csv'
        
        results_dict = {}
        for wallet, balance, success in results:
            results_dict[wallet] = (balance, success)
        
        # Получаем курс ETH для mainnet сетей - используем network_type если передан
        eth_price = 0
        is_mainnet = network_type == "mainnet" if network_type else is_mainnet_network(network_name)
        
        if is_mainnet:
            eth_price = get_eth_price_usdt()
        
        with open(result_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Определяем заголовки в зависимости от типа сети
            if is_mainnet and eth_price > 0:
                writer.writerow(['address', 'balance_eth', 'balance_usdt', 'network'])
            else:
                writer.writerow(['address', 'balance_eth', 'network'])
            
            for wallet in wallets:
                if wallet in results_dict:
                    balance, success = results_dict[wallet]
                    if success:
                        # Форматируем баланс без научной нотации
                        formatted_balance = f"{balance:.18f}".rstrip('0').rstrip('.')
                        if is_mainnet and eth_price > 0:
                            balance_usdt = balance * eth_price
                            writer.writerow([wallet, formatted_balance, f"{balance_usdt:.2f}", network_name])
                        else:
                            writer.writerow([wallet, formatted_balance, network_name])
                    else:
                        writer.writerow([wallet, "0", "0.00" if is_mainnet and eth_price > 0 else "", network_name])
                else:
                    writer.writerow([wallet, "0", "0.00" if is_mainnet and eth_price > 0 else "", network_name])
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении результатов: {e}")
        raise

def save_results_all_networks(results, all_networks, wallets):
    try:
        """Сохраняет результаты всех сетей в CSV файл с сохранением порядка"""
        result_dir = project_root / 'result'
        result_dir.mkdir(exist_ok=True)
        
        result_file = result_dir / 'result.csv'
        
        results_dict = {}
        for wallet, network_balances, success in results:
            results_dict[wallet] = (network_balances, success)
        
        # Получаем курс ETH для расчета USDT
        eth_price = get_eth_price_usdt()
        
        # Определяем какие сети являются mainnet
        mainnet_networks = []
        for network_name in all_networks.keys():
            if is_mainnet_network(network_name):
                mainnet_networks.append(network_name)
        
        with open(result_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Создаем заголовок с названиями сетей
            header = ['address']
            for network_name in all_networks.keys():
                clean_network_name = network_name.replace('🚀 ', '')
                header.append(f"{clean_network_name}_ETH")
                # Добавляем колонку USDT для mainnet сетей
                if is_mainnet_network(network_name) and eth_price > 0:
                    header.append(f"{clean_network_name}_USDT")
            
            writer.writerow(header)
            
            for wallet in wallets:
                if wallet in results_dict:
                    network_balances, success = results_dict[wallet]
                    if success and isinstance(network_balances, dict):
                        row = [wallet]
                        for network_name in all_networks.keys():
                            balance = network_balances.get(network_name, 0)
                            # Форматируем баланс без научной нотации
                            formatted_balance = f"{balance:.18f}".rstrip('0').rstrip('.')
                            row.append(formatted_balance)
                            # Добавляем стоимость в USDT для mainnet сетей
                            if is_mainnet_network(network_name) and eth_price > 0:
                                balance_usdt = balance * eth_price
                                row.append(f"{balance_usdt:.2f}")
                        writer.writerow(row)
                    else:
                        row = [wallet]
                        for network_name in all_networks.keys():
                            row.append("0")
                            # Добавляем 0 USDT для mainnet сетей
                            if is_mainnet_network(network_name) and eth_price > 0:
                                row.append("0.00")
                        writer.writerow(row)
                else:
                    row = [wallet]
                    for network_name in all_networks.keys():
                        row.append("0")
                        # Добавляем 0 USDT для mainnet сетей
                        if is_mainnet_network(network_name) and eth_price > 0:
                            row.append("0.00")
                    writer.writerow(row)
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении результатов: {e}")
        raise
    
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
    
    # Настраиваем логирование ошибок
    error_logger = setup_error_logging()
    
    if not rpc_urls_list:
        error_msg = f"RPC URLs для сети {clean_network} не найдены!"
        logger.error(f"❌ {error_msg}")
        if error_logger:
            error_logger.error(f"Configuration Error: {error_msg}")
        return
    
    logger.info("="*80)
    logger.info(f"🚀 Начинаем проверку балансов нативных токенов")
    logger.info(f"🌐 Сеть: {clean_network} ({network_type})")
    
    # Показываем информацию о mainnet и курсе - используем network_type для определения
    if network_type == "mainnet" or is_mainnet_network(clean_network):
        logger.success(f"💎 Mainnet сеть - будет добавлена стоимость в USDT")
        eth_price = get_eth_price_usdt()
        if eth_price > 0:
            logger.success(f"💰 Курс ETH: ${eth_price:.2f} USDT")
    else:
        logger.warning(f"🔧 Testnet сеть - только баланс в ETH")
    
    logger.info(f"🔗 RPC URLs: {len(rpc_urls_list)} шт.")
    logger.info(f"🧵 Потоков: {NUM_THREADS}")
    logger.info("="*80)
    
    wallets = load_wallets()
    proxies_list = load_proxies()
    
    if not wallets:
        logger.error("❌ Нет кошельков для обработки!")
        return
    
    logger.success(f"📂 Загружено {len(wallets)} кошельков")
    logger.success(f"🔗 Загружено {len(proxies_list)} прокси")
    
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
    
    logger.info("-"*80)
    logger.info("🔄 Начинаем обработку кошельков...")
    logger.info("-"*80+ "\n")
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_wallet = {
            executor.submit(
                process_wallet_task, 
                i,
                wallet,
                get_assigned_proxy(i, proxies_list),
                rpc_urls_list,
                proxies_list,
                logger,
                clean_network
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
                    end="\n" if progress_percent >= 100 else "",
                    flush=True,
                )

    logger.info("" + "="*80)
    logger.info("📊 ИТОГОВАЯ СТАТИСТИКА:")
    logger.success(f"✅ Успешно обработано: {successful_count}")
    logger.error(f"❌ Ошибок: {failed_count}")
    logger.info(f"📈 Процент успеха: {(successful_count/total_wallets)*100:.1f}%")
    
    total_time = time.time() - start_time
    logger.info(f"⏱️ Общее время выполнения: {format_time_remaining(total_time)}")
    
    logger.info("💾 Сохраняем результаты...")
    saved_result = save_results(results, clean_network, wallets, network_type)
    if saved_result:
        logger.success("✅ Результаты сохранены в result/result.csv")
    logger.info("="*80 + "\n")
    
    # Уведомление в Telegram с файлом
    from modules.notifications import send_telegram_notification
    result_file_path = project_root / 'result' / 'result.csv'
    send_telegram_notification(
        notif_type="success",
        title="Проверка балансов завершена",
        message=f"Сеть: {clean_network} ({network_type})\nУспешно: {successful_count}\nОшибок: {failed_count}",
        main_title="Баланс чек завершён",
        file_path=str(result_file_path)
    )

def check_wallet_balances_all_networks(all_networks):
    """Функция для проверки балансов во всех сетях"""
    
    # Настраиваем логирование ошибок
    error_logger = setup_error_logging()
    
    logger.info("="*80)
    logger.info(f"🚀 Начинаем проверку балансов во ВСЕХ сетях")
    logger.info(f"🌐 Количество сетей: {len(all_networks)}")
    
    # Показываем информацию о mainnet сетях
    mainnet_count = sum(1 for network in all_networks.keys() if is_mainnet_network(network))
    testnet_count = len(all_networks) - mainnet_count
    
    logger.success(f"💎 Mainnet сетей: {mainnet_count}")
    logger.warning(f"🔧 Testnet сетей: {testnet_count}")
    
    if mainnet_count > 0:
        logger.success(f"💰 Для mainnet сетей будет добавлена стоимость в USDT")
    
    logger.info(f"🧵 Потоков: {NUM_THREADS}")
    logger.info("="*80)
    
    wallets = load_wallets()
    proxies_list = load_proxies()
    
    if not wallets:
        logger.error("❌ Нет кошельков для обработки!")
        return
    
    logger.success(f"📂 Загружено {len(wallets)} кошельков")
    logger.success(f"🔗 Загружено {len(proxies_list)} прокси")
    
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
    
    logger.info("-"*80)
    logger.info("🔄 Начинаем обработку кошельков...\n")
    logger.info("-"*80)
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_wallet = {
            executor.submit(
                process_wallet_task_all_networks, 
                i,
                wallet,
                get_assigned_proxy(i, proxies_list),
                all_networks,
                proxies_list,
                logger
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
    # Сохраняем результаты после обработки всех кошельков
    save_results_all_networks(results, all_networks, wallets)
    logger.success("✅ Результаты сохранены в result/result.csv")
    #logger.info("="*80 + "\n")
    logger.info("💬 Отправляем уведомление в Telegram...")
    # Уведомление в Telegram с файлом
    from modules.notifications import send_telegram_notification
    result_file_path = project_root / 'result' / 'result.csv'
    send_telegram_notification(
        notif_type="success",
        title="Проверка балансов по всем сетям завершена",
        message=f"Сетей: {len(all_networks)}\nУспешно: {successful_count}\nОшибок: {failed_count}",
        main_title="Баланс чек завершён",
        file_path=str(result_file_path)
    )

def check_wallet_balances_menu():
    """Главная функция для запуска проверки балансов кошельков"""
    from modules.eth.rpc_return_module import get_network_rpc_selection

    rpc_urls_list, network_type, clean_network = get_network_rpc_selection()
    if rpc_urls_list is None:
        return

    if rpc_urls_list == 'ALL_NETWORKS':
        check_wallet_balances_all_networks(network_type)
    else:
        check_wallet_balances_single_network(rpc_urls_list, network_type, clean_network)

