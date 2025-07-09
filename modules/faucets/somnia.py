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

# Импорт конфигурации
import sys
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS, PRINT_FULL_ERRORS_MESSAGES, LOOP_FACETS, somnia_timeout, IGNORE_TIME_SLEEP_BETWEEN_ACTIONS

class SomniaFaucet:
    def __init__(self):
        self.base_url = 'https://testnet.somnia.network/api/faucet'
        self.ua = UserAgent()

    def drip(self, address, proxy, session=None):
        """Запросить токены из крана для указанного адреса"""
        
        # Используем переданную сессию или создаем новую
        if session is None:
            session = requests.Session()
            should_close_session = True
        else:
            should_close_session = False
        
        try:
            # Настраиваем прокси для сессии
            if proxy:
                if '@' in proxy:
                    # Формат: login:password@ip:port
                    auth_part, address_part = proxy.split('@')
                    login, password = auth_part.split(':')
                    ip, port = address_part.split(':')
                    proxy_url = f"http://{login}:{password}@{ip}:{port}"
                else:
                    # Формат: ip:port
                    proxy_url = f"http://{proxy}"
                
                session.proxies.update({
                    'http': proxy_url,
                    'https': proxy_url
                })

            # Используем точные заголовки из рабочего кода
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

            # Используем точный формат данных из рабочего кода
            data = {
                "address": address
            }

            # Используем точную логику запроса из рабочего кода
            response = session.post(self.base_url, headers=headers, json=data, timeout=30)

            # Используем точную логику обработки ответа из рабочего кода
            success = response.json()['success']
            if success:
                return True, "Успешно получены токены из крана"
            else:
                error_msg = response.json().get("error", "Неизвестная ошибка")
                
                # Проверяем сообщение о 24-часовом ожидании
                if "Please wait 24 hours between requests" in error_msg:
                    return True, "Кран уже запрошен (ожидание 24 часа)"
                
                return False, f"Ошибка крана: {error_msg}"

        except requests.exceptions.RequestException as e:
            return False, f"Ошибка запроса: {str(e)}"
        finally:
            # Закрываем сессию только если создали ее в этом методе
            if should_close_session:
                session.close()

    def is_proxy_working(self, proxy):
        """Проверить работоспособность прокси"""
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

            response = session.get(test_url, timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
        finally:
            session.close()

def load_wallets():
    """Загружает кошельки из файла data/walletss.txt"""
    try:
        wallets_file = project_root / 'data' / 'walletss.txt'
        with open(wallets_file, 'r', encoding='utf-8') as f:
            wallets = [line.strip() for line in f if line.strip()]
        return wallets
    except FileNotFoundError:
        print(Fore.RED + "❌ Файл data/walletss.txt не найден!")
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
                    # Убираем http:// если есть
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
                    'last_attempt': datetime.strptime(row['last_attempt'], '%Y-%m-%d %H:%M:%S') if row['last_attempt'] else datetime.min
                }
    except FileNotFoundError:
        # Создаем файл с заголовками
        with open(log_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['wallet', 'success', 'failure', 'last_attempt']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
    
    return log, log_file

def write_log(log_file, log):
    """Записывает лог в файл"""
    try:
        with open(log_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['wallet', 'success', 'failure', 'last_attempt']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            # Создаем копию словаря для избежания ошибки "dictionary changed size during iteration"
            log_copy = dict(log)
            for wallet, counts in log_copy.items():
                writer.writerow({
                    'wallet': wallet,
                    'success': counts['success'],
                    'failure': counts['failure'],
                    'last_attempt': counts['last_attempt'].strftime('%Y-%m-%d %H:%M:%S')
                })
    except Exception as e:
        print(Fore.RED + f"Ошибка записи лога: {e}")

def process_wallet_task(wallet, proxy, faucet, log, log_file):
    """Обрабатывает один кошелек"""
    
    session = None
    try:
        # Создаем сессию для этого кошелька
        session = requests.Session()
        
        # Генерируем рандомный таймаут для этого кошелька (в часах)
        random_timeout_hours = random.uniform(somnia_timeout[0], somnia_timeout[1])
        
        # Проверяем, не обрабатывался ли кошелек в течение рандомного таймаута
        if wallet in log and datetime.now() - log[wallet]['last_attempt'] < timedelta(hours=random_timeout_hours):
            time_left = timedelta(hours=random_timeout_hours) - (datetime.now() - log[wallet]['last_attempt'])
            hours_left = int(time_left.total_seconds() // 3600)
            return wallet, False, f"Пропущен (осталось {hours_left}ч до следующего запроса, таймаут: {random_timeout_hours:.1f}ч)"

        # Проверяем прокси
        if not faucet.is_proxy_working(proxy):
            return wallet, False, "Прокси не работает"

        # Попытки запроса крана
        for attempt in range(RETRY_COUNT + 1):
            try:
                success, message = faucet.drip(wallet, proxy, session)
                
                # Обновляем лог
                if wallet not in log:
                    log[wallet] = {'success': 0, 'failure': 0, 'last_attempt': datetime.now()}

                if success:
                    log[wallet]['success'] += 1
                    # Обновляем время последнего запроса с учетом рандомного таймаута
                    log[wallet]['last_attempt'] = datetime.now()
                    write_log(log_file, log)
                    
                    # Задержка после успешного запроса (только если не игнорируем)
                    if not IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
                        delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
                        time.sleep(delay)
                    
                    return wallet, True, f"{message} (следующий запрос через {random_timeout_hours:.1f}ч)"
                else:
                    log[wallet]['failure'] += 1
                    # Даже при неудаче обновляем время, чтобы не спамить
                    log[wallet]['last_attempt'] = datetime.now()
                    
                    # Выводим полное сообщение об ошибке если включена настройка
                    if PRINT_FULL_ERRORS_MESSAGES and ("Rate limit" in message or "Ошибка крана:" in message):
                        print(f"\n{Fore.RED}[ПОЛНАЯ ОШИБКА] {wallet[:10]}...: {message}{Style.RESET_ALL}")
                    
                    if attempt < RETRY_COUNT:
                        time.sleep(2)  # Пауза перед повтором
                        continue
                    else:
                        write_log(log_file, log)
                        return wallet, False, message

            except Exception as e:
                error_msg = f"Ошибка: {str(e)}"
                
                # Выводим полное сообщение об исключении если включена настройка
                if PRINT_FULL_ERRORS_MESSAGES:
                    print(f"\n{Fore.RED}[ПОЛНОЕ ИСКЛЮЧЕНИЕ] {wallet[:10]}...: {error_msg}{Style.RESET_ALL}")
                
                if attempt < RETRY_COUNT:
                    time.sleep(2)
                    continue
                else:
                    if wallet not in log:
                        log[wallet] = {'success': 0, 'failure': 0, 'last_attempt': datetime.now()}
                    log[wallet]['failure'] += 1
                    log[wallet]['last_attempt'] = datetime.now()
                    write_log(log_file, log)
                    return wallet, False, error_msg

        return wallet, False, "Не удалось выполнить запрос"
    
    finally:
        # Обязательно закрываем сессию для каждого кошелька
        if session:
            try:
                session.close()
            except Exception as e:
                print(f"{Fore.YELLOW}[WARNING] Ошибка закрытия сессии для {wallet[:10]}...: {e}{Style.RESET_ALL}")

def check_and_process_expired_wallets():
    """Проверяет и обрабатывает кошельки, для которых прошло более рандомного таймаута с последнего запроса"""
    
    # Загружаем данные
    wallets = load_wallets()
    proxies = load_proxies()
    log, log_file = read_log()
    
    if not wallets or not proxies:
        return 0
    
    faucet = SomniaFaucet()
    processed_count = 0
    
    # Фильтруем кошельки, которые готовы к обработке
    ready_wallets = []
    for i, wallet in enumerate(wallets):
        proxy = proxies[i % len(proxies)]
        
        # Генерируем рандомный таймаут для проверки
        random_timeout_hours = random.uniform(somnia_timeout[0], somnia_timeout[1])
        
        # Проверяем, прошло ли более рандомного таймаута с последнего запроса
        if wallet in log:
            time_since_last = datetime.now() - log[wallet]['last_attempt']
            if time_since_last < timedelta(hours=random_timeout_hours):
                continue  # Еще рано для этого кошелька
        
        ready_wallets.append((wallet, proxy))
    
    if not ready_wallets:
        return 0
    
    if IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
        # Пакетная обработка: берем NUM_THREADS кошельков и обрабатываем параллельно
        batch_size = NUM_THREADS
        total_batches = (len(ready_wallets) + batch_size - 1) // batch_size  # Округляем вверх
        
        for batch_num in range(0, len(ready_wallets), batch_size):
            batch_end = min(batch_num + batch_size, len(ready_wallets))
            batch = ready_wallets[batch_num:batch_end]
            current_batch_num = batch_num // batch_size + 1
            
            print(f"{Fore.CYAN}[LOOP] 🔄 Обработка пакета {current_batch_num}/{total_batches}: кошельки {batch_num + 1}-{batch_end} ({len(batch)} шт.){Style.RESET_ALL}")
            
            # Обрабатываем пакет многопоточно
            with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = []
                for wallet, proxy in batch:
                    future = executor.submit(process_wallet_task, wallet, proxy, faucet, log, log_file)
                    futures.append((future, wallet, proxy))
                
                # Собираем результаты
                for future, wallet, proxy in futures:
                    try:
                        wallet_result, success, message = future.result(timeout=120)
                        
                        # Форматируем информацию о прокси для вывода
                        if '@' in proxy:
                            auth_part, address_part = proxy.split('@')
                            proxy_display = f"xxx:xxx@{address_part}"
                        else:
                            proxy_display = f"{proxy.rsplit('.', 1)[0]}.xxx:{proxy.split(':')[-1]}"
                        
                        if success:
                            processed_count += 1
                            print(f"{Fore.GREEN}[LOOP] ✅ {wallet[:10]}... | Прокси: {proxy_display} - {message}{Style.RESET_ALL}")
                        else:
                            if "Пропущен" not in message:
                                print(f"{Fore.RED}[LOOP] ❌ {wallet[:10]}... | Прокси: {proxy_display} - {message[:50]}...{Style.RESET_ALL}")
                    
                    except Exception as e:
                        print(f"{Fore.RED}[LOOP] ❌ {wallet[:10]}... | Исключение: {str(e)}{Style.RESET_ALL}")
            
            # Задержка между пакетами (если не последний пакет)
            if batch_end < len(ready_wallets):
                delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
                print(f"{Fore.BLUE}[LOOP] ⏸️ Пауза между пакетами {delay:.1f}с... (следующий пакет {current_batch_num + 1}/{total_batches}){Style.RESET_ALL}")
                time.sleep(delay)
    
    else:
        # Последовательная обработка с задержками
        wallet_counter = 0
        for wallet, proxy in ready_wallets:
            # Добавляем задержку между кошельками
            if wallet_counter > 0:
                delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
                print(f"{Fore.BLUE}[LOOP] ⏳ Задержка {delay:.1f}с перед обработкой {wallet[:10]}...{Style.RESET_ALL}")
                time.sleep(delay)
            
            # Обрабатываем кошелек
            wallet_result, success, message = process_wallet_task(wallet, proxy, faucet, log, log_file)
            
            # Форматируем информацию о прокси для вывода
            if '@' in proxy:
                auth_part, address_part = proxy.split('@')
                proxy_display = f"xxx:xxx@{address_part}"
            else:
                proxy_display = f"{proxy.rsplit('.', 1)[0]}.xxx:{proxy.split(':')[-1]}"
            
            if success:
                processed_count += 1
                print(f"{Fore.GREEN}[LOOP] ✅ {wallet[:10]}... | Прокси: {proxy_display} - {message}{Style.RESET_ALL}")
            else:
                if "Пропущен" not in message:
                    print(f"{Fore.RED}[LOOP] ❌ {wallet[:10]}... | Прокси: {proxy_display} - {message[:50]}...{Style.RESET_ALL}")
            
            wallet_counter += 1
    
    return processed_count

def run_somnia_faucet_loop():
    """Основная функция для зацикленного запуска процесса получения токенов из крана Somnia"""
    
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + "🔄 Запуск зацикленного процесса получения токенов из крана Somnia")
    print(Fore.CYAN + "⏰ Проверка каждую минуту, запрос крана если прошло более таймаута")
    if IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
        print(Fore.CYAN + f"🚀 Режим пакетной обработки: {NUM_THREADS} кошельков одновременно, пауза между пакетами {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с")
    else:
        print(Fore.CYAN + f"⏳ Режим с задержками: {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с между кошельками")
    print(Fore.MAGENTA + "="*80)
    
    # Загружаем данные для первоначальной проверки
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
            
            print(f"\n{Fore.CYAN}[{current_time}] 🔍 Цикл #{cycle_count} - Проверка кошельков...{Style.RESET_ALL}")
            
            # Проверяем и обрабатываем просроченные кошельки
            processed_in_cycle = check_and_process_expired_wallets()
            total_processed += processed_in_cycle
            
            if processed_in_cycle > 0:
                print(f"{Fore.GREEN}[СТАТИСТИКА] Обработано в этом цикле: {processed_in_cycle}, Всего обработано: {total_processed}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[СТАТИСТИКА] Нет кошельков готовых для запроса крана (ожидание 25ч){Style.RESET_ALL}")
            
            # Ждем 1 минуту до следующей проверки
            print(f"{Fore.BLUE}⏳ Ожидание 60 секунд до следующей проверки...{Style.RESET_ALL}")
            for remaining in range(60, 0, -1):
                print(f"\r{Fore.BLUE}⏳ Следующая проверка через {remaining} сек...{Style.RESET_ALL}", end="", flush=True)
                time.sleep(1)
            print()  # Новая строка после обратного отсчета
            
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}🛑 Остановка зацикленного процесса пользователем{Style.RESET_ALL}")
        print(f"{Fore.GREEN}📊 Итого обработано кошельков: {total_processed}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}🔄 Выполнено циклов: {cycle_count}{Style.RESET_ALL}")

def run_somnia_faucet():
    """Основная функция для запуска процесса получения токенов из крана Somnia"""
    
    # Проверяем настройку зацикливания
    if LOOP_FACETS:
        run_somnia_faucet_loop()
        return
    
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + "🚰 Запуск процесса получения токенов из крана Somnia")
    print(Fore.CYAN + f"⏰ Таймаут между запросами: {somnia_timeout[0]}-{somnia_timeout[1]} часов (рандомно)")
    if IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
        print(Fore.CYAN + f"🚀 Режим пакетной обработки: {NUM_THREADS} кошельков одновременно, пауза между пакетами {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с")
    else:
        print(Fore.CYAN + f"⏳ Режим с задержками: {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с между кошельками")
    print(Fore.MAGENTA + "="*80)
    
    # Загружаем данные
    wallets = load_wallets()
    proxies = load_proxies()
    log, log_file = read_log()
    
    if not wallets:
        print(Fore.RED + "❌ Нет кошельков для обработки!")
        return
    
    if not proxies:
        print(Fore.RED + "❌ Нет прокси для работы!")
        return
    
    # Проверяем соответствие количества кошельков и прокси
    if len(proxies) < len(wallets):
        print(Fore.YELLOW + f"⚠️ ВНИМАНИЕ: Прокси ({len(proxies)}) меньше чем кошельков ({len(wallets)})")
        print(Fore.YELLOW + "Некоторые прокси будут использоваться повторно")
    
    print(Fore.GREEN + f"📂 Загружено {len(wallets)} кошельков")
    print(Fore.GREEN + f"🔗 Загружено {len(proxies)} прокси")
    print(Fore.CYAN + f"🧵 Потоков: {NUM_THREADS}")
    print(Fore.CYAN + f"🔄 Попыток на кошелек: {RETRY_COUNT + 1}")
    
    # Подготавливаем задачи
    tasks = []
    for i, wallet in enumerate(wallets):
        proxy = proxies[i % len(proxies)]  # Циклически используем прокси
        tasks.append((wallet, proxy))
    
    faucet = SomniaFaucet()
    total_wallets = len(tasks)
    completed_wallets = 0
    successful_count = 0
    failed_count = 0
    skipped_count = 0
    
    # Прогресс-бар
    bar_length = 50
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_cycle = cycle(spinner)
    
    print(Fore.MAGENTA + "\n" + "-"*80)
    print(Fore.YELLOW + "🔄 Начинаем обработку кошельков...")
    print(Fore.MAGENTA + "-"*80)
    
    # Многопоточная обработка
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        if IGNORE_TIME_SLEEP_BETWEEN_ACTIONS:
            # Пакетная обработка без задержек
            future_to_wallet = {
                executor.submit(process_wallet_task, wallet, proxy, faucet, log, log_file): wallet
                for wallet, proxy in tasks
            }
        else:
            # Обработка с задержками между запусками
            future_to_wallet = {}
            for wallet, proxy in tasks:
                future = executor.submit(process_wallet_task, wallet, proxy, faucet, log, log_file)
                future_to_wallet[future] = wallet
                
                # Добавляем фиксированную задержку между запуском задач
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

if __name__ == "__main__":
    run_somnia_faucet()
