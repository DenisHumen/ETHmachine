import csv
import random
import time
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from pathlib import Path
import requests
from fake_useragent import UserAgent
from colorama import Fore, Style

import sys
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS, PRINT_FULL_ERRORS_MESSAGES, LOOP_FACETS, somnia_timeout, IGNORE_TIME_SLEEP_BETWEEN_ACTIONS

try:
    from config.config import ENABLE_CHECK_BALANCE
except ImportError:
    ENABLE_CHECK_BALANCE = True  

try:
    from config.config import SLEEP_BETWEEN_CHECK_BALANCE
except ImportError:
    SLEEP_BETWEEN_CHECK_BALANCE = [1, 3]  

try:
    from config.config import DELAY_FOR_READY_WALLETS_somnia
except ImportError:
    DELAY_FOR_READY_WALLETS_somnia = [60, 60]  

try:
    from config.config import DELAY_BETWEEN_REPETITIONS_somnia
except ImportError:
    DELAY_BETWEEN_REPETITIONS_somnia = [10, 30]  

try:
    from config.config import PATH_TO_WALLETS_SOMNIA
except ImportError:
    PATH_TO_WALLETS_SOMNIA = 'data/walletss.txt' 

try:
    from config.config import DELAY_BETWEEN_WALLETS_somnia
except ImportError:
    DELAY_BETWEEN_WALLETS_somnia = [1, 15]  

try:
    from config.rpc import somnia_testnet
except ImportError:
    somnia_testnet = ['https://dream-rpc.somnia.network'] 

from web3 import Web3

sys.path.append(str(project_root / "modules"))
from notifications import send_telegram_notification
from config.config import TELEGRAM_LOG_LEVEL_somnia, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

def display_proxy_distribution_info(wallets_count, proxies_count, log=None):
    """Отображает информацию о распределении прокси"""
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + "🔗 ПРИНЦИП РАБОТЫ С ПРОКСИ:")
    
    if proxies_count == wallets_count:
        print(Fore.GREEN + "✅ Режим 1К1: Каждому кошельку назначен свой прокси")
        print(Fore.CYAN + f"   📊 Кошельков: {wallets_count}, Прокси: {proxies_count}")
        print(Fore.YELLOW + "   ⚠️ Резервных прокси нет")
        
    elif proxies_count < wallets_count:
        print(Fore.YELLOW + "⚠️ Режим рандомного распределения: Прокси: меньше кошельков")
        print(Fore.CYAN + f"   📊 Кошельков: {wallets_count}, Прокси: {proxies_count}")
        print(Fore.YELLOW + "   🔀 Прокси: будут назначаться случайным образом")
        
    else:  
        main_proxies = wallets_count
        reserve_proxies = proxies_count - wallets_count
        print(Fore.GREEN + "✅ Режим 1К1 с резервными прокси")
        print(Fore.CYAN + f"   📊 Кошельков: {wallets_count}, Всего прокси: {proxies_count}")
        print(Fore.CYAN + f"   🎯 Основные прокси: 1-{main_proxies} (по одному на кошелек)")
        print(Fore.CYAN + f"   🔄 Резервные прокси: {main_proxies + 1}-{proxies_count} ({reserve_proxies} шт.)")
        print(Fore.YELLOW + f"   ⚡ Количество попыток с резервными: {RETRY_COUNT}")
    
    print(Fore.MAGENTA + "="*80)
    
    print(Fore.YELLOW + "💾 ИНФОРМАЦИЯ О ПРОГРЕССЕ:")
    print(Fore.CYAN + "   📁 Файл прогресса: result/faucet/somnia_process.csv")
    print(Fore.CYAN + "   🔄 Содержит: время последних запросов, счетчики успехов/ошибок")
    
    if log is not None:
        existing_wallets = len(log)
        new_wallets = wallets_count - existing_wallets
        print(Fore.CYAN + f"   📈 В прогрессе уже есть: {existing_wallets} кошельков из {wallets_count}")
        if new_wallets > 0:
            print(Fore.GREEN + f"   🆕 Будет инициализировано впервые: {new_wallets} новых кошельков")
        else:
            print(Fore.GREEN + "   ✅ Все кошельки уже есть в прогрессе")
    
    print(Fore.YELLOW + "   ⚠️ При удалении файла процесс начнется заново для всех кошельков")
    print(Fore.MAGENTA + "="*80)

class SomniaFaucet:
    def __init__(self):
        self.base_url = 'https://testnet.somnia.network/api/faucet'
        self.ua = UserAgent()

    def drip(self, address, proxy, session=None):
        """Запросить токены из крана для указанного адреса"""
        
        if session is None:
            session = requests.Session()
            should_close_session = True
        else:
            should_close_session = False
        
        try:
            if proxy:
                if '@' in proxy:
                    auth_part, address_part = proxy.split('@')
                    login, password = auth_part.split(':')
                    ip, port = address_part.split(':')
                    proxy_url = f"http://{login}:{password}@{ip}:{port}"
                else:
                    proxy_url = f"http://{proxy}"
                
                session.proxies.update({
                    'http': proxy_url,
                    'https': proxy_url
                })

            headers = {
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.9,ru;q=0.8,uk;q=0.7',
                'cache-control': 'no-cache',
                'content-type': 'application/json',
                'origin': 'https://story.impossible.finance',
                'pragma': 'no-cache',
                'priority': 'u=1, i',
                'referer': 'https://story.impossible.finance/',
                'user-agent': UserAgent().random
            }

            data = {
                "address": address
            }

            response = session.post(self.base_url, headers=headers, json=data, timeout=30)

            success = response.json()['success']
            if success:
                return True, "Успешно запрошены токены из крана"
            else:
                error_msg = response.json().get("error", "Неизвестная ошибка")
                
                if "Please wait 24 hours between requests" in error_msg:
                    return True, "Кран уже запрошен (ожидание 24 часа)"
                
                return False, f"Ошибка крана: {error_msg}"

        except requests.exceptions.RequestException as e:
            return False, f"Ошибка запроса: {str(e)}"
        finally:
            if should_close_session:
                session.close()

    def is_proxy_working(self, proxy, wallet_address=None):
        """Проверить работоспособность прокси с детальным логированием"""

        test_url = 'https://httpbin.org/ip'
        
        session = requests.Session()
        try:
            if proxy:
                if '@' in proxy:
                    auth_part, address_part = proxy.split('@')
                    login, password = auth_part.split(':')
                    ip, port = address_part.split(':')
                    proxy_url = f"http://{login}:{password}@{ip}:{port}"
                else:
                    proxy_url = f"http://{proxy}"
                
                session.proxies.update({
                    'http': proxy_url,
                    'https': proxy_url
                })

            response = session.get(test_url, timeout=10)
            
            if response.status_code == 200:
                return True, "OK"
            elif response.status_code == 407:
                return False, "Неуспешная авторизация прокси"
            else:
                return False, f"HTTP {response.status_code}"
                
        except requests.exceptions.ConnectTimeout:
            return False, "Timeout подключения"
        except requests.exceptions.ProxyError as e:
            if "407" in str(e):
                return False, "Неуспешная авторизация прокси"
            return False, f"Proxy error: {str(e)[:50]}"
        except requests.exceptions.ConnectionError as e:
            return False, f"Connection error: {str(e)[:50]}"
        except requests.exceptions.Timeout:
            return False, "Timeout запроса"
        except requests.exceptions.RequestException as e:
            return False, f"Request error: {str(e)[:50]}"
        except Exception as e:
            return False, f"Unexpected error: {str(e)[:50]}"
        finally:
            session.close()

def load_wallets():
    """Загружает кошельки из файла по пути PATH_TO_WALLETS_SOMNIA"""
    try:
        wallets_file = project_root / PATH_TO_WALLETS_SOMNIA
        with open(wallets_file, 'r', encoding='utf-8') as f:
            wallets = [line.strip() for line in f if line.strip()]
        return wallets
    except FileNotFoundError:
        print(Fore.RED + f"❌ Файл {PATH_TO_WALLETS_SOMNIA} не найден!")
        return []

def load_proxies():
    """Загружает прокси из файла data/proxy.csv"""
    try:
        proxy_file = project_root / 'data' / 'proxy.csv'
        with open(proxy_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            proxies = []
            for row in reader:
                if row and not row[0].lower().startswith('proxy'):
                    proxy = row[0].strip()
                    if proxy.startswith('http://'):
                        proxy = proxy[7:]
                    proxies.append(proxy)
        return proxies
    except FileNotFoundError:
        print(Fore.RED + "❌ Файл data/proxy.csv не найден!")
        return []

def read_log():
    """Читает лог файл с информацией о предыдущих запросах"""
    log_dir = project_root / 'result' / 'faucet'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / 'somnia_process.csv'
    log = {}
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                log[row['wallet']] = {
                    'success': int(row['success']),
                    'failure': int(row['failure']),
                    'last_attempt': datetime.strptime(row['last_attempt'], '%Y-%m-%d %H:%M:%S') if row['last_attempt'] else datetime.min,
                    'status': row.get('status', '')  
                }
    except FileNotFoundError:
        with open(log_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['wallet', 'success', 'failure', 'last_attempt', 'status']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
    
    return log, log_file

def write_log(log_file, log):
    """Записывает лог в файл"""
    try:
        with open(log_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['wallet', 'success', 'failure', 'last_attempt', 'status']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            log_copy = dict(log)
            for wallet, counts in log_copy.items():
                writer.writerow({
                    'wallet': wallet,
                    'success': counts['success'],
                    'failure': counts['failure'],
                    'last_attempt': counts['last_attempt'].strftime('%Y-%m-%d %H:%M:%S'),
                    'status': counts.get('status', '')
                })
    except Exception as e:
        print(Fore.RED + f"Ошибка записи лога: {e}")

def get_web3_connection(wallet_index):
    """Получает Web3 подключение для кошелька по индексу"""
    rpc_index = wallet_index % len(somnia_testnet)
    rpc_url = somnia_testnet[rpc_index]
    
    for attempt in range(len(somnia_testnet)):
        try:
            current_rpc = somnia_testnet[(rpc_index + attempt) % len(somnia_testnet)]
            w3 = Web3(Web3.HTTPProvider(current_rpc))
            w3.eth.block_number
            return w3
        except Exception as e:
            if attempt < len(somnia_testnet) - 1:
                print(f"{Fore.YELLOW}[RPC] Ошибка RPC {current_rpc}, пробуем следующий: {e}{Style.RESET_ALL}")
                continue
            else:
                print(f"{Fore.RED}[RPC] Все RPC недоступны для кошелька {wallet_index}: {e}{Style.RESET_ALL}")
                return None

def get_balance(wallet_address, wallet_index):
    """Получает баланс кошелька"""
    try:
        w3 = get_web3_connection(wallet_index)
        if w3 is None:
            return None
        
        balance_wei = w3.eth.get_balance(wallet_address)
        balance_eth = w3.from_wei(balance_wei, 'ether')
        return float(balance_eth)
    except Exception as e:
        print(f"{Fore.RED}[BALANCE] Ошибка получения баланса для {wallet_address[:10]}...: {e}{Style.RESET_ALL}")
        return None

def check_balances_for_ready_wallets(ready_wallets, log):
    """Проверяет балансы только для кошельков, готовых к обработке"""
    if not IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
        return {}
        
    if not ENABLE_CHECK_BALANCE:
        return {}
    
    balances_before = {}
    wallets_to_check = []
    
    for wallet, proxy in ready_wallets:
        wallets_to_check.append(wallet)
    
    if not wallets_to_check:
        return {}
    
    print(f"{Fore.CYAN}🔍 Проверка балансов перед запросом крана ({len(wallets_to_check)} кошельков)...{Style.RESET_ALL}")
    
    all_wallets = load_wallets()
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = {}
        for wallet in wallets_to_check:
            try:
                wallet_index = all_wallets.index(wallet)
                future = executor.submit(get_balance, wallet, wallet_index)
                futures[future] = wallet
            except ValueError:
                print(f"{Fore.YELLOW}[BALANCE] {wallet[:10]}... - не найден в списке кошельков{Style.RESET_ALL}")
        
        for future in as_completed(futures):
            wallet = futures[future]
            try:
                balance = future.result()
                if balance is not None:
                    balances_before[wallet] = balance
                    print(f"{Fore.CYAN}[BALANCE] {wallet[:10]}... = {balance:.6f} STT{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}[BALANCE] {wallet[:10]}... - не удалось получить баланс{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[BALANCE] {wallet[:10]}... - ошибка: {e}{Style.RESET_ALL}")
    
    return balances_before

def check_balances_after_processing_ready_wallets(processed_wallets, log, balances_before):
    """Проверяет балансы после обработки только для обработанных кошельков и обновляет статусы"""
    if not IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
        return 0, 0
        
    if not ENABLE_CHECK_BALANCE:
        return 0, 0
        
    if not processed_wallets:  
        return 0, 0
    
    wallets_to_check = []
    for wallet in processed_wallets:
        if wallet in log:
            if log[wallet].get('status') == 'не_подходит_под_кран':
                print(f"{Fore.YELLOW}[BALANCE] {wallet[:10]}... - пропускаем проверку баланса (Bot detected){Style.RESET_ALL}")
                continue
        wallets_to_check.append(wallet)
    
    if not wallets_to_check:
        print(f"{Fore.YELLOW}[BALANCE] Нет кошельков для проверки баланса (все пропущены){Style.RESET_ALL}")
        return 0, 0
    
    print(f"{Fore.CYAN}🔍 Проверка балансов после запроса крана ({len(wallets_to_check)} кошельков)...{Style.RESET_ALL}")
    
    tokens_received = 0
    tokens_not_received = 0
    
    all_wallets = load_wallets()
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = {}
        for wallet in wallets_to_check:
            try:
                wallet_index = all_wallets.index(wallet)
                future = executor.submit(get_balance, wallet, wallet_index)
                futures[future] = wallet
            except ValueError:
                print(f"{Fore.YELLOW}[BALANCE] {wallet[:10]}... - не найден в списке кошельков{Style.RESET_ALL}")
        
        for future in as_completed(futures):
            wallet = futures[future]
            try:
                balance_after = future.result()
                if balance_after is None:
                    print(f"{Fore.YELLOW}[BALANCE] {wallet[:10]}... - не удалось получить баланс после запроса{Style.RESET_ALL}")
                    continue
                    
                if wallet in balances_before:
                    balance_before = balances_before[wallet]
                    balance_diff = balance_after - balance_before
                    
                    if wallet in log:
                        if balance_diff > 0.0001:  
                            log[wallet]['status'] = '✅' 
                            tokens_received += 1
                            print(f"{Fore.GREEN}[BALANCE] {wallet[:10]}... = {balance_after:.6f} ETH (изменение: {balance_diff:+.6f}) - статус: ✅{Style.RESET_ALL}")
                        elif abs(balance_diff) < 0.0001:  
                            current_status = log[wallet].get('status', '')
                            
                            if current_status == '':
                                new_status = '⚠️'
                            elif current_status == '⚠️':
                                new_status = '⚠️⚠️'
                            elif current_status == '⚠️⚠️':
                                new_status = '⚠️⚠️⚠️'
                            elif current_status == '⚠️⚠️⚠️':
                                new_status = '❌'  
                            else:
                                new_status = '⚠️'  
                            
                            log[wallet]['status'] = new_status
                            tokens_not_received += 1
                            print(f"{Fore.YELLOW}[BALANCE] {wallet[:10]}... = {balance_after:.6f} ETH (изменение: {balance_diff:+.6f}) - статус: {new_status}{Style.RESET_ALL}")
                        else:
                            if 'status' not in log[wallet]:
                                log[wallet]['status'] = ''
                            print(f"{Fore.CYAN}[BALANCE] {wallet[:10]}... = {balance_after:.6f} ETH (изменение: {balance_diff:+.6f}){Style.RESET_ALL}")
                else:
                    print(f"{Fore.CYAN}[BALANCE] {wallet[:10]}... = {balance_after:.6f} ETH (нет данных о начальном балансе){Style.RESET_ALL}")
                    
            except Exception as e:
                print(f"{Fore.RED}[BALANCE] {wallet[:10]}... - ошибка получения баланса: {e}{Style.RESET_ALL}")
    
    return tokens_received, tokens_not_received

def process_wallet_task(wallet, proxy, faucet, log, log_file, reserve_proxies=None):
    """Обрабатывает один кошелек"""
    
    session = None
    try:
        session = requests.Session()
        random_timeout_hours = random.uniform(somnia_timeout[0], somnia_timeout[1])
        
        proxies_to_try = [proxy] 
        if reserve_proxies and len(reserve_proxies) > 0:
            num_reserves_to_use = min(RETRY_COUNT, len(reserve_proxies))
            random_reserves = random.sample(reserve_proxies, num_reserves_to_use)
            proxies_to_try.extend(random_reserves)

        for attempt in range(min(RETRY_COUNT + 1, len(proxies_to_try))):
            current_proxy = proxies_to_try[attempt]
            
            if '@' in current_proxy:
                auth_part, address_part = current_proxy.split('@')
                proxy_display = f"xxx:xxx@{address_part}"
            else:
                proxy_display = f"{current_proxy.rsplit('.', 1)[0]}.xxx:{current_proxy.split(':')[-1]}"
            
            if attempt == 0 or current_proxy != proxies_to_try[attempt - 1]:
                proxy_working, proxy_error = faucet.is_proxy_working(current_proxy, wallet)
                
                if not proxy_working:
                    if PRINT_FULL_ERRORS_MESSAGES:
                        print(f"{Fore.YELLOW}[PROXY DEBUG] {wallet[:10]}... - Прокси: {current_proxy.split('@')[-1] if '@' in current_proxy else current_proxy}: {proxy_error}{Style.RESET_ALL}")
                    
                    if attempt < len(proxies_to_try) - 1:
                        print(f"{Fore.YELLOW}[RETRY] {wallet[:10]}... - Прокси: {proxy_display} не работает ({proxy_error}), пробуем следующий резервный{Style.RESET_ALL}")
                        continue
                    else:
                        return wallet, False, f"Все прокси не работают (последняя ошибка: {proxy_error})"

            try:
                success, message = faucet.drip(wallet, current_proxy, session)
                
                if wallet not in log:
                    log[wallet] = {'success': 0, 'failure': 0, 'last_attempt': datetime.now(), 'status': ''}

                if success:
                    log[wallet]['success'] += 1
                    log[wallet]['last_attempt'] = datetime.now()
                    write_log(log_file, log)
                    
                    if not IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
                        delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
                        time.sleep(delay)
                    
                    if TELEGRAM_LOG_LEVEL_somnia == 1:
                        send_telegram_notification(
                            notif_type="success",
                            main_title="somnia faucet",
                            title=f"Успешный запрос крана",
                            message=message,
                            proxy=proxy_display,
                            wallet_address=wallet,
                            status="success"
                        )
                    
                    return wallet, True, f"{message} (следующий запрос через {random_timeout_hours:.1f}ч)"
                else:
                    
                    if "Bot detected" in message:
                        if wallet not in log:
                            log[wallet] = {'success': 0, 'failure': 0, 'last_attempt': datetime.now(), 'status': ''}
                        log[wallet]['failure'] += 1
                        log[wallet]['last_attempt'] = datetime.now()
                        log[wallet]['status'] = 'не_подходит_под_кран'
                        write_log(log_file, log)
                        
                        if TELEGRAM_LOG_LEVEL_somnia == 1:
                            send_telegram_notification(
                                notif_type="error",
                                main_title="somnia faucet",
                                title="Кошелек не подходит под кран (Bot detected)",
                                message=message,
                                proxy=proxy_display,
                                wallet_address=wallet,
                                status="error"
                            )
                        
                        return wallet, False, "Кошелек не подходит под кран (Bot detected)"
                    
                    if any(error in message.lower() for error in ["internal server error", "502", "503", "504", "server error"]):
                        if attempt < len(proxies_to_try) - 1:
                            retry_delay = random.uniform(DELAY_BETWEEN_REPETITIONS_somnia[0], DELAY_BETWEEN_REPETITIONS_somnia[1])
                            
                            if PRINT_FULL_ERRORS_MESSAGES:
                                print(f"{Fore.RED}[ПОЛНАЯ ОШИБКА] {wallet[:10]}... | Прокси: {proxy_display} - {message}, ждем {retry_delay:.1f}с и пробуем следующий прокси{Style.RESET_ALL}")
                            else:
                                error_preview = f"{message[:30]}..."
                                print(f"{Fore.YELLOW}[RETRY] {wallet[:10]}... | Прокси: {proxy_display} - Серверная ошибка ({error_preview}), ждем {retry_delay:.1f}с и пробуем следующий прокси{Style.RESET_ALL}")
                            
                            time.sleep(retry_delay)
                            continue
                        else:
                            if TELEGRAM_LOG_LEVEL_somnia == 1:
                                send_telegram_notification(
                                    notif_type="error",
                                    main_title="somnia faucet",
                                    title="Серверные ошибки на всех прокси",
                                    message=message,
                                    proxy=proxy_display,
                                    wallet_address=wallet,
                                    status="error"
                                )
                            
                            return wallet, False, f"Серверные ошибки на всех прокси: {message}"
                    
                    if attempt < len(proxies_to_try) - 1:
                        retry_delay = random.uniform(DELAY_BETWEEN_REPETITIONS_somnia[0], DELAY_BETWEEN_REPETITIONS_somnia[1])
                        
                        if PRINT_FULL_ERRORS_MESSAGES and ("Rate limit" in message or "Ошибка крана:" in message):
                            print(f"{Fore.RED}[ПОЛНАЯ ОШИБКА] {wallet[:10]}... | Прокси: {proxy_display} - {message}, ждем {retry_delay:.1f}с и пробуем следующий прокси{Style.RESET_ALL}")
                        else:
                            error_preview = f"{message[:30]}..."
                            print(f"{Fore.YELLOW}[RETRY] {wallet[:10]}... | Прокси: {proxy_display} - Ошибка крана ({error_preview}), ждем {retry_delay:.1f}с и пробуем следующий прокси{Style.RESET_ALL}")
                        
                        time.sleep(retry_delay)
                        continue
                    else:
                        return wallet, False, message

            except Exception as e:
                if attempt < len(proxies_to_try) - 1:
                    retry_delay = random.uniform(DELAY_BETWEEN_REPETITIONS_somnia[0], DELAY_BETWEEN_REPETITIONS_somnia[1])
                    
                    if PRINT_FULL_ERRORS_MESSAGES:
                        print(f"{Fore.RED}[ПОЛНОЕ ИСКЛЮЧЕНИЕ] {wallet[:10]}... | Прокси: {proxy_display} - {str(e)}, ждем {retry_delay:.1f}с и пробуем следующий прокси{Style.RESET_ALL}")
                    else:
                        error_preview = f"{str(e)[:30]}..."
                        print(f"{Fore.YELLOW}[RETRY] {wallet[:10]}... | Прокси: {proxy_display} - Исключение ({error_preview}), ждем {retry_delay:.1f}с и пробуем следующий прокси{Style.RESET_ALL}")
                    
                    time.sleep(retry_delay)
                    continue
                else:
                    error_msg = f"Исключение: {str(e)[:50]}..." if not PRINT_FULL_ERRORS_MESSAGES else f"Исключение: {str(e)}"
                    return wallet, False, error_msg

        return wallet, False, "Не удалось выполнить запрос на всех прокси"
    
    finally:
        if session:
            try:
                session.close()
            except Exception as e:
                print(f"{Fore.YELLOW}[WARNING] Ошибка закрытия сессии для {wallet[:10]}...: {e}{Style.RESET_ALL}")

def check_and_process_expired_wallets():
    """Проверяет ВСЕ кошельки в файле и создает полный план работ для обработки за один проход"""
    
    wallets = load_wallets()
    proxies = load_proxies()
    log, log_file = read_log()
    
    if not wallets or not proxies:
        return 0
    
    main_proxies = proxies[:len(wallets)]
    reserve_proxies = proxies[len(wallets):] if len(proxies) > len(wallets) else []
    
    faucet = SomniaFaucet()
    processed_count = 0
    processed_wallets = []  
    failed_count = 0  
    skipped_count = 0  
    
    all_successful_wallets_for_balance_check = []
    
    tokens_received_count = 0
    tokens_not_received_count = 0
    
    ready_wallets = []
    for i, wallet in enumerate(wallets):
        if len(proxies) >= len(wallets):
            proxy = main_proxies[i % len(main_proxies)]
        else:
            proxy = random.choice(proxies)
        
        random_timeout_hours = random.uniform(somnia_timeout[0], somnia_timeout[1])
        
        if wallet in log:
            time_since_last = datetime.now() - log[wallet]['last_attempt']
            if time_since_last < timedelta(hours=random_timeout_hours):
                continue  
        
        ready_wallets.append((wallet, proxy))
    
    if not ready_wallets:
        print(f"{Fore.YELLOW}📋 План работ пуст - все кошельки ожидают завершения таймаута{Style.RESET_ALL}")
        return 0
    
    batch_size = NUM_THREADS
    total_batches = (len(ready_wallets) + batch_size - 1) // batch_size
    
    print(f"{Fore.GREEN}📋 ПЛАН: {len(ready_wallets)} кошельков → {total_batches} пакетов по {batch_size} 🚀{Style.RESET_ALL}")
    
    balances_before = check_balances_for_ready_wallets(ready_wallets, log)
    
    for batch_num in range(0, len(ready_wallets), batch_size):
        batch_end = min(batch_num + batch_size, len(ready_wallets))
        batch = ready_wallets[batch_num:batch_end]
        current_batch_num = batch_num // batch_size + 1
        
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = []
            for wallet_index, (wallet, proxy) in enumerate(batch):
                if wallet_index > 0: 
                    delay = random.uniform(DELAY_BETWEEN_WALLETS_somnia[0], DELAY_BETWEEN_WALLETS_somnia[1])
                    time.sleep(delay)
                
                future = executor.submit(process_wallet_task, wallet, proxy, faucet, log, log_file, reserve_proxies)
                futures.append((future, wallet, proxy))
            
            batch_successful_wallets_for_balance_check = [] 
            
            for future, wallet, proxy in futures:
                try:
                    wallet_result, success, message = future.result(timeout=120)
                    
                    if '@' in proxy:
                        auth_part, address_part = proxy.split('@')
                        proxy_display = f"xxx:xxx@{address_part}"
                    else:
                        proxy_display = f"{proxy.rsplit('.', 1)[0]}.xxx:{proxy.split(':')[-1]}"
                    
                    if success:
                        processed_count += 1
                        processed_wallets.append(wallet)  
                        
                        if "Кран уже запрошен" not in message and "Bot detected" not in message:
                            batch_successful_wallets_for_balance_check.append(wallet)
                        
                        print(f"{Fore.GREEN}[ВЫПОЛНЕНИЕ] ✅ {wallet[:10]}... | Прокси: {proxy_display} - {message}{Style.RESET_ALL}")
                    else:
                        failed_count += 1
                        if PRINT_FULL_ERRORS_MESSAGES:
                            error_msg = message
                        else:
                            error_msg = f"{message[:50]}..."
                        
                        if "Bot detected" in message:
                            print(f"{Fore.RED}[ВЫПОЛНЕНИЕ] [BOT DETECTED] ❌ {wallet[:10]}... | Прокси: {proxy_display} - {error_msg}{Style.RESET_ALL}")
                        else:
                            print(f"{Fore.RED}[ВЫПОЛНЕНИЕ] ❌ {wallet[:10]}... | Прокси: {proxy_display} - {error_msg}{Style.RESET_ALL}")
                
                except Exception as e:
                    failed_count += 1
                    if PRINT_FULL_ERRORS_MESSAGES:
                        error_msg = str(e)
                    else:
                        error_msg = str(e)[:50] + "..." if len(str(e)) > 50 else str(e)
                    
                    proxy_display = f"xxx:xxx@{proxy.split('@')[-1]}" if '@' in proxy else f"{proxy.rsplit('.', 1)[0]}.xxx:{proxy.split(':')[-1]}"
                    print(f"{Fore.RED}[ВЫПОЛНЕНИЕ] ❌ {wallet[:10]}... | Прокси: {proxy_display} | Исключение: {error_msg}{Style.RESET_ALL}")
            
            all_successful_wallets_for_balance_check.extend(batch_successful_wallets_for_balance_check)
        
        if batch_end < len(ready_wallets):
            delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
            
            start_time = datetime.now()
            end_time = start_time + timedelta(seconds=delay)
            print(f"{Fore.BLUE}⏸️ Пауза между пакетами {delay:.1f}с... (следующий пакет {current_batch_num + 1}/{total_batches}){Style.RESET_ALL}")
            print(f"{Fore.BLUE}🕒 Начало: {start_time.strftime('%H:%M:%S')} → Окончание: {end_time.strftime('%H:%M:%S')}{Style.RESET_ALL}")
            
            for remaining in range(int(delay), 0, -1):
                print(f"\r{Fore.BLUE}⏸️ Осталось: {remaining}с до следующего пакета...{Style.RESET_ALL}", end="", flush=True)
                time.sleep(1)
            print()  

    if len(all_successful_wallets_for_balance_check) > 0: 
        if IGNORE_TIME_SLEEP_BETWEEN_ACTIONS and ENABLE_CHECK_BALANCE:
            delay = random.uniform(SLEEP_BETWEEN_CHECK_BALANCE[0], SLEEP_BETWEEN_CHECK_BALANCE[1])
            
            start_time = datetime.now()
            end_time = start_time + timedelta(seconds=delay)
            print(f"{Fore.BLUE}⏳ Ожидание {delay:.1f}с перед проверкой балансов после запроса крана...{Style.RESET_ALL}")
            print(f"{Fore.BLUE}🕒 Начало: {start_time.strftime('%H:%M:%S')} → Окончание: {end_time.strftime('%H:%M:%S')}{Style.RESET_ALL}")
            
            for remaining in range(int(delay), 0, -1):
                print(f"\r{Fore.BLUE}⏳ Осталось: {remaining}с до проверки балансов...{Style.RESET_ALL}", end="", flush=True)
                time.sleep(1)
            print()  
        
        tokens_received_count, tokens_not_received_count = check_balances_after_processing_ready_wallets(all_successful_wallets_for_balance_check, log, balances_before)
        write_log(log_file, log)  
    elif processed_count > 0:
        print(f"{Fore.YELLOW}[BALANCE] Пропускаем проверку балансов - все запросы были 'уже запрошен' или 'Bot detected'")
        write_log(log_file, log)  
    
    total_planned = len(ready_wallets)
    success_rate = (processed_count / total_planned * 100) if total_planned > 0 else 0
    
    successful_count = processed_count
    total_wallets = total_planned

    balance_info = ""
    if tokens_received_count > 0 or tokens_not_received_count > 0:
        total_checked = tokens_received_count + tokens_not_received_count
        tokens_rate = (tokens_received_count / total_checked * 100) if total_checked > 0 else 0
        balance_info = f" | 💰 {tokens_received_count}✅ {tokens_not_received_count}⚠️ токенов ({tokens_rate:.1f}%)"
    
    print(f"{Fore.GREEN}🏁 ИТОГ: {processed_count}✅ {failed_count}❌ из {total_planned} ({success_rate:.1f}% успех){balance_info}{Style.RESET_ALL}")
    
    if TELEGRAM_LOG_LEVEL_somnia == 2:
        stats_text = (
            f"ИТОГОВАЯ СТАТИСТИКА:\n"
            f"✅ Успешно обработано: {successful_count}\n"
            f"❌ Ошибок: {failed_count}\n"
            f"⏭️ Пропущено (ожидание 25ч): {skipped_count}\n"
            f"📈 Процент успеха: {(successful_count/(total_wallets-skipped_count)*100) if (total_wallets-skipped_count) > 0 else 0:.1f}%\n"
            f"💾 Лог сохранен в: result/faucet/somnia_process.csv"
        )
        send_telegram_notification(
            notif_type="info",
            main_title="somnia faucet",
            title="Итоговая статистика по кранам",
            message=stats_text,
            file_path=str(log_file)
        )

def run_somnia_faucet_loop():
    """Основная функция для зацикленного запуска процесса получения токенов из крана Somnia"""
    
    wallets = load_wallets()
    proxies = load_proxies()
    log, log_file = read_log() 
    
    if not wallets:
        print(Fore.RED + "❌ Нет кошельков для обработки!")
        return
    
    if not proxies:
        print(Fore.RED + "❌ Нет прокси для работы!")
        return
    
    display_proxy_distribution_info(len(wallets), len(proxies), log)
    
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + "🔄 Запуск зацикленного процесса получения токенов из крана Somnia")
    print(Fore.CYAN + "⏰ За один цикл обрабатываются ВСЕ подходящие кошельки из файла")
    print(Fore.CYAN + "🔄 Логика: анализ файла → составление плана → выполнение плана → пауза 60с → повтор")
    if IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
        print(Fore.CYAN + f"🚀 Режим пакетной обработки: {NUM_THREADS} кошельков одновременно, пауза между пакетами {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с")
    else:
        print(Fore.CYAN + f"⏳ Режим с задержками: {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с между кошельками")
    print(Fore.MAGENTA + "="*80)
    
    wallets = load_wallets()
    proxies = load_proxies()
    
    if not wallets:
        print(Fore.RED + "❌ Нет кошельков для обработки!")
        return
    
    if not proxies:
        print(Fore.RED + "❌ Нет прокси для работы!")
        return
    
    print(Fore.GREEN + f"📂 Загружено {len(wallets)} кошельков")
    print(Fore.GREEN + f"🔗 Загружено {len(proxies)} прокси")
    print(Fore.CYAN + f"🔄 Попыток на кошелек: {RETRY_COUNT + 1}")
    print(Fore.YELLOW + f"⏳ Для остановки используйте Ctrl+C")
    
    cycle_count = 0
    total_processed = 0
    
    try:
        while True:
            cycle_count += 1
            current_time = datetime.now().strftime("%H:%M:%S")
            
            print(f"\n{Fore.CYAN}[{current_time}] 🔄 Цикл #{cycle_count} - Анализ {len(wallets)} кошельков...{Style.RESET_ALL}")
            
            processed_in_cycle = check_and_process_expired_wallets()
            total_processed += processed_in_cycle
            
            if processed_in_cycle > 0:
                print(f"{Fore.GREEN}📊 Обработано в цикле: {processed_in_cycle}, Всего: {total_processed}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}📊 Нет готовых кошельков (все ожидают {somnia_timeout[0]}-{somnia_timeout[1]}ч){Style.RESET_ALL}")
            
            if DELAY_FOR_READY_WALLETS_somnia[0] == 0 and DELAY_FOR_READY_WALLETS_somnia[1] == 0:
                continue  
            else:
                delay = random.randint(DELAY_FOR_READY_WALLETS_somnia[0], DELAY_FOR_READY_WALLETS_somnia[1])
                
                start_time = datetime.now()
                end_time = start_time + timedelta(seconds=delay)
                print(f"{Fore.BLUE}⏳ Пауза {delay}с до следующего анализа...{Style.RESET_ALL}")
                print(f"{Fore.BLUE}🕒 Начало: {start_time.strftime('%H:%M:%S')} → Окончание: {end_time.strftime('%H:%M:%S')}{Style.RESET_ALL}")
                
                for remaining in range(delay, 0, -1):
                    print(f"\r{Fore.BLUE}⏳ Осталось: {remaining}с до следующего анализа...{Style.RESET_ALL}", end="", flush=True)
                    time.sleep(1)
                print()  
            
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}🛑 Остановка процесса пользователем{Style.RESET_ALL}")
        print(f"{Fore.GREEN}📊 Итого обработано: {total_processed} кошельков за {cycle_count} циклов{Style.RESET_ALL}")

def run_somnia_faucet():
    """Основная функция для запуска процесса получения токенов из крана Somnia"""
    
    if LOOP_FACETS:
        run_somnia_faucet_loop()
        return
    
    wallets = load_wallets()
    proxies = load_proxies()
    log, log_file = read_log()
    
    if not wallets:
        print(Fore.RED + "❌ Нет кошельков для обработки!")
        return
    
    if not proxies:
        print(Fore.RED + "❌ Нет прокси для работы!")
        return
    
    main_proxies = proxies[:len(wallets)]
    reserve_proxies = proxies[len(wallets):] if len(proxies) > len(wallets) else []
    
    display_proxy_distribution_info(len(wallets), len(proxies), log)
    
    tasks = []
    for i, wallet in enumerate(wallets):
        if len(proxies) >= len(wallets):
            proxy = main_proxies[i % len(main_proxies)]
        else:
            proxy = random.choice(proxies)
        tasks.append((wallet, proxy))
    
    ready_tasks = []
    for wallet, proxy in tasks:
        random_timeout_hours = random.uniform(somnia_timeout[0], somnia_timeout[1])
        
        if wallet in log and datetime.now() - log[wallet]['last_attempt'] < timedelta(hours=random_timeout_hours):
            continue
        
        ready_tasks.append((wallet, proxy))
    
    balances_before = check_balances_for_ready_wallets(ready_tasks, log)
    
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + "🚰 Запуск процесса получения токенов из крана Somnia")
    print(Fore.CYAN + f"⏰ Таймаут между запросами: {somnia_timeout[0]}-{somnia_timeout[1]} часов (рандомно)")
    print(Fore.CYAN + f"🌐 RPC серверов: {len(somnia_testnet)}")
    if IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
        print(Fore.CYAN + f"🚀 Режим пакетной обработки: {NUM_THREADS} кошельков одновременно, пауза между пакетами {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с")
    else:
        print(Fore.CYAN + f"⏳ Режим с задержками: {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с между кошельками")
    print(Fore.MAGENTA + "="*80)
    
    faucet = SomniaFaucet()
    total_wallets = len(tasks)
    completed_wallets = 0
    successful_count = 0
    failed_count = 0
    skipped_count = 0
    
    bar_length = 50
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_cycle = cycle(spinner)
    
    print(Fore.MAGENTA + "\n" + "-"*80)
    print(Fore.YELLOW + "🔄 Начинаем обработку кошельков...")
    print(Fore.MAGENTA + "-"*80)
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        if IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
            future_to_wallet = {}
            for wallet_index, (wallet, proxy) in enumerate(tasks):
                if wallet_index > 0:  
                    delay = random.uniform(DELAY_BETWEEN_WALLETS_somnia[0], DELAY_BETWEEN_WALLETS_somnia[1])
                    time.sleep(delay)
                
                future = executor.submit(process_wallet_task, wallet, proxy, faucet, log, log_file, reserve_proxies)
                future_to_wallet[future] = wallet
        else:
            future_to_wallet = {}
            for wallet, proxy in tasks:
                future = executor.submit(process_wallet_task, wallet, proxy, faucet, log, log_file, reserve_proxies)
                future_to_wallet[future] = wallet
                
                delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
                time.sleep(delay)
        
        for future in as_completed(future_to_wallet):
            wallet = future_to_wallet[future]
            try:
                wallet_result, success, message = future.result(timeout=120)
                
                if success:
                    successful_count += 1
                    status_icon = "✅"
                    status_color = Fore.GREEN
                elif "Пропущен" in message:
                    skipped_count += 1
                    status_icon = "⏭️"
                    status_color = Fore.YELLOW
                else:
                    failed_count += 1
                    status_icon = "❌"
                    status_color = Fore.RED
                
            except Exception as e:
                failed_count += 1
                status_icon = "❌"
                status_color = Fore.RED
                message = f"Исключение: {str(e)}"
                wallet_result = wallet
            
            finally:
                completed_wallets += 1
                progress = int((completed_wallets / total_wallets) * bar_length)
                bar = "█" * progress + "░" * (bar_length - progress)
                spinner_frame = next(spinner_cycle)
                
                remaining_wallets = total_wallets - completed_wallets
                
                print(
                    f"\r{Fore.BLUE}[{bar}] {completed_wallets}/{total_wallets} | "
                    f"{spinner_frame} | ✅{successful_count} | ❌{failed_count} | ⏭️{skipped_count} | "
                    f"Осталось: {remaining_wallets} | {status_color}{status_icon} {wallet_result[:10]}...{wallet_result[-6:]} | {message[:30]}...{Style.RESET_ALL}",
                    end="",
                    flush=True,
                )

    print(Fore.MAGENTA + "\n\n" + "="*80)
    print(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА:")
    print(Fore.GREEN + f"✅ Успешно обработано: {successful_count}")    
    print(Fore.RED + f"❌ Ошибок: {failed_count}")    
    print(Fore.YELLOW + f"⏭️ Пропущено (ожидание 25ч): {skipped_count}")
    print(Fore.CYAN + f"📈 Процент успеха: {(successful_count/(total_wallets-skipped_count)*100) if (total_wallets-skipped_count) > 0 else 0:.1f}%")
    print(Fore.CYAN + f"💾 Лог сохранен в: result/faucet/somnia_process.csv")
    print(Fore.MAGENTA + "="*80 + "\n")
    
    if TELEGRAM_LOG_LEVEL_somnia == 2:
        stats_text = (
            f"ИТОГОВАЯ СТАТИСТИКА:\n"
            f"✅ Успешно обработано: {successful_count}\n"
            f"❌ Ошибок: {failed_count}\n"
            f"⏭️ Пропущено (ожидание 25ч): {skipped_count}\n"
            f"📈 Процент успеха: {(successful_count/(total_wallets-skipped_count)*100) if (total_wallets-skipped_count) > 0 else 0:.1f}%\n"
            f"💾 Лог сохранен в: result/faucet/somnia_process.csv"
        )
        send_telegram_notification(
            notif_type="info",
            main_title="somnia faucet",
            title="Итоговая статистика по кранам",
            message=stats_text,
            file_path=str(log_file)
        )

def run_somnia_faucet_loop():
    """Основная функция для зацикленного запуска процесса получения токенов из крана Somnia"""
    
    wallets = load_wallets()
    proxies = load_proxies()
    log, log_file = read_log()  
    
    if not wallets:
        print(Fore.RED + "❌ Нет кошельков для обработки!")
        return
    
    if not proxies:
        print(Fore.RED + "❌ Нет прокси для работы!")
        return
    
    display_proxy_distribution_info(len(wallets), len(proxies), log)
    
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + "🔄 Запуск зацикленного процесса получения токенов из крана Somnia")
    print(Fore.CYAN + "⏰ За один цикл обрабатываются ВСЕ подходящие кошельки из файла")
    print(Fore.CYAN + "🔄 Логика: анализ файла → составление плана → выполнение плана → пауза 60с → повтор")
    if IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
        print(Fore.CYAN + f"🚀 Режим пакетной обработки: {NUM_THREADS} кошельков одновременно, пауза между пакетами {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с")
    else:
        print(Fore.CYAN + f"⏳ Режим с задержками: {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с между кошельками")
    print(Fore.MAGENTA + "="*80)
    
    wallets = load_wallets()
    proxies = load_proxies()
    
    if not wallets:
        print(Fore.RED + "❌ Нет кошельков для обработки!")
        return
    
    if not proxies:
        print(Fore.RED + "❌ Нет прокси для работы!")
        return
    
    print(Fore.GREEN + f"📂 Загружено {len(wallets)} кошельков")
    print(Fore.GREEN + f"🔗 Загружено {len(proxies)} прокси")
    print(Fore.CYAN + f"🔄 Попыток на кошелек: {RETRY_COUNT + 1}")
    print(Fore.YELLOW + f"⏳ Для остановки используйте Ctrl+C")
    
    cycle_count = 0
    total_processed = 0
    
    try:
        while True:
            cycle_count += 1
            current_time = datetime.now().strftime("%H:%M:%S")
            
            print(f"\n{Fore.CYAN}[{current_time}] 🔄 Цикл #{cycle_count} - Анализ {len(wallets)} кошельков...{Style.RESET_ALL}")
            
            processed_in_cycle = check_and_process_expired_wallets()
            total_processed += processed_in_cycle
            
            if processed_in_cycle > 0:
                print(f"{Fore.GREEN}📊 Обработано в цикле: {processed_in_cycle}, Всего: {total_processed}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}📊 Нет готовых кошельков (все ожидают {somnia_timeout[0]}-{somnia_timeout[1]}ч){Style.RESET_ALL}")
            
            if DELAY_FOR_READY_WALLETS_somnia[0] == 0 and DELAY_FOR_READY_WALLETS_somnia[1] == 0:
                continue 
            else:
                delay = random.randint(DELAY_FOR_READY_WALLETS_somnia[0], DELAY_FOR_READY_WALLETS_somnia[1])
                
                start_time = datetime.now()
                end_time = start_time + timedelta(seconds=delay)
                print(f"{Fore.BLUE}⏳ Пауза {delay}с до следующего анализа...{Style.RESET_ALL}")
                print(f"{Fore.BLUE}🕒 Начало: {start_time.strftime('%H:%M:%S')} → Окончание: {end_time.strftime('%H:%M:%S')}{Style.RESET_ALL}")
                
                for remaining in range(delay, 0, -1):
                    print(f"\r{Fore.BLUE}⏳ Осталось: {remaining}с до следующего анализа...{Style.RESET_ALL}", end="", flush=True)
                    time.sleep(1)
                print()  
            
            if TELEGRAM_LOG_LEVEL_somnia == 2 and processed_in_cycle > 0:
                stats_text = (
                    f"ИТОГОВАЯ СТАТИСТИКА:\n"
                    f"✅ Обработано в цикле: {processed_in_cycle}\n"
                    f"📊 Всего: {total_processed}\n"
                    f"💾 Лог сохранен в: result/faucet/somnia_process.csv"
                )
                send_telegram_notification(
                    notif_type="info",
                    main_title="somnia faucet",
                    title="Итоговая статистика по кранам (цикл)",
                    message=stats_text,
                    file_path=str(log_file)
                )
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}🛑 Остановка процесса пользователем{Style.RESET_ALL}")
        print(f"{Fore.GREEN}📊 Итого обработано: {total_processed} кошельков за {cycle_count} циклов{Style.RESET_ALL}")

