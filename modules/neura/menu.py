import sys
import csv
import random
import asyncio
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from colorama import Fore, Style

from questionary import Choice, select

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from modules.simple_logger import logger
from config.modules.cfg_base import NUM_THREADS, SLEEP_BETWEEN_ACTIONS, RETRY_COUNT, astrum_CAPTCHA_API_KEY
from config.modules.cfg_neura import (
    NEURA_MODULES, NEURA_USE_PROXY, NEURA_RANDOM_PROXY,
    NEURA_TELEGRAM_NOTIFICATIONS, NEURA_TELEGRAM_LOG_LEVEL,
    SHUFFLE_WALLET_LIST_NEURA,
    NEURA_RANDOM_MODULE_ORDER
)
from config.networks import NETWORKS
from modules.neura.client import NeuraClient
from modules.neura.database import (
    init_database, create_tasks_for_wallets, get_pending_tasks,
    update_task_status, get_task_statistics, reset_failed_tasks,
    all_tasks_completed, reset_database_for_new_run, get_wallet_task_status
)
from modules.notifications import send_telegram_notification

progress_lock = Lock()


def load_private_keys() -> List[str]:
    keys_file = project_root / 'data' / 'private_keys.txt'
    
    if not keys_file.exists():
        logger.error(f"Файл {keys_file} не найден!")
        return []
    
    with open(keys_file, 'r') as f:
        keys = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    logger.info(f"Загружено {len(keys)} приватных ключей")
    return keys


def load_proxies() -> List[str]:
    proxy_file = project_root / 'data' / 'proxy.csv'
    
    if not proxy_file.exists():
        logger.warning("Файл proxy.csv не найден, работаем без прокси")
        return []
    
    proxies = []
    with open(proxy_file, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0].strip():
                proxies.append(row[0].strip())
    
    logger.info(f"Загружено {len(proxies)} прокси")
    return proxies


def get_wallet_address_from_key(private_key: str) -> str:
    from eth_account import Account
    return Account.from_key(private_key).address


def prepare_wallets(private_keys: List[str]) -> List[Tuple[str, str]]:
    wallets = []
    for pk in private_keys:
        try:
            address = get_wallet_address_from_key(pk)
            wallets.append((address, pk))
        except Exception as e:
            logger.error(f"Ошибка при обработке ключа: {e}")
    return wallets


def get_randomized_modules(modules: List[str]) -> List[str]:
    if not NEURA_RANDOM_MODULE_ORDER:
        return modules
    
    modules_copy = [m for m in modules if m != 'claim_tasks']
    has_claim_tasks = 'claim_tasks' in modules
    
    random.shuffle(modules_copy)
    
    if has_claim_tasks:
        modules_copy.append('claim_tasks')
    
    return modules_copy


async def process_wallet_task(
    private_key: str, 
    proxy: str, 
    task_type: str,
    all_proxies: List[str] = None,
    wallet_index: int = 0,
    total_wallets: int = 0
) -> Tuple[str, bool, str]:

    wallet_address = get_wallet_address_from_key(private_key)
    current_proxy = proxy
    last_error = ""
    proxy_ip = current_proxy.split('@')[-1] if current_proxy and '@' in current_proxy else (current_proxy[:20] if current_proxy else 'No proxy')
    
    logger.info(f"[{wallet_index}/{total_wallets}] | [{wallet_address}] | {task_type} | Proxy: {proxy_ip}")
    
    for attempt in range(RETRY_COUNT):
        try:
            async with NeuraClient(private_key=private_key, proxy=current_proxy) as client:
                if not await client.authorize():
                    last_error = "Authorization failed"
                    logger.warning(f"[{wallet_address}] Auth failed (попытка {attempt + 1}/{RETRY_COUNT}), смена прокси...")
                    if all_proxies and len(all_proxies) > 1:
                        current_proxy = random.choice([p for p in all_proxies if p != current_proxy] or all_proxies)
                    await asyncio.sleep(random.uniform(3, 7)) 
                    continue
                
                success = False
                
                if task_type == 'collect_pulses':
                    user_data = await client.get_user()
                    uncollected_count = 0
                    if client.user_data and client.user_data.pulses:
                        uncollected_count = len([p for p in client.user_data.pulses.data if not p.is_collected])
                    
                    if uncollected_count == 0:
                        logger.success(f"[{wallet_address}] Все пульсы уже собраны")
                        return wallet_address, True, ""
                    
                    success = await client.collect_pulses()
                    
                    if success:
                        logger.success(f"[{wallet_address}] Собрано {uncollected_count} пульсов")
                        return wallet_address, True, ""
                        
                elif task_type == 'claim_tasks':
                    tasks = await client._get_tasks()
                    claimable = len([t for t in tasks if t.get('status') == 'claimable']) if tasks else 0
                    
                    if claimable == 0:
                        logger.success(f"[{wallet_address}] Все задачи уже заклеймлены")
                        return wallet_address, True, ""
                    
                    success = await client.claim_tasks()
                    
                    if success:
                        logger.success(f"[{wallet_address}] Заклеймлено {claimable} задач")
                        return wallet_address, True, ""
                
                elif task_type == 'faucet':
                    success = await client.request_tokens()
                    
                    if success:
                        logger.success(f"[{wallet_address}] Токены из faucet получены")
                        return wallet_address, True, ""
                
                elif task_type == 'swap':
                    success, tx_hashes = await client.execute_swap()
                    
                    if success:
                        return wallet_address, True, ""
                
                else:
                    return wallet_address, False, f"Unknown task type: {task_type}"
                
                if not success:
                    last_error = "Task execution failed"
                    logger.warning(f"[{wallet_address}] Не удалось выполнить, retry {attempt + 1}/{RETRY_COUNT}...")
                    if all_proxies and len(all_proxies) > 1:
                        current_proxy = random.choice([p for p in all_proxies if p != current_proxy] or all_proxies)
                    await asyncio.sleep(random.uniform(2, 5))
                    continue
                
        except Exception as e:
            import traceback
            last_error = str(e)
            logger.error(f"[{wallet_address}] Ошибка: {str(e)}")
            if all_proxies and len(all_proxies) > 1:
                current_proxy = random.choice([p for p in all_proxies if p != current_proxy] or all_proxies)
            await asyncio.sleep(random.uniform(2, 5))
    
    logger.error(f"[{wallet_address}] Все {RETRY_COUNT} попыток исчерпаны | {last_error}")
    return wallet_address, False, last_error


def run_task_sync(private_key: str, proxy: str, task_type: str, all_proxies: List[str] = None, wallet_index: int = 0, total_wallets: int = 0) -> Tuple[str, bool, str]:
    return asyncio.run(process_wallet_task(private_key, proxy, task_type, all_proxies, wallet_index, total_wallets))


async def process_wallet_all_modules(
    private_key: str,
    proxy: str,
    task_types: List[str],
    all_proxies: List[str],
    wallet_index: int,
    total_wallets: int
) -> Tuple[str, Dict[str, bool], Dict[str, str]]:
    """Обработка всех модулей для одного кошелька последовательно"""
    wallet_address = get_wallet_address_from_key(private_key)
    results = {}
    errors = {}
    
    # Рандомизируем порядок модулей для этого кошелька
    modules = get_randomized_modules(task_types)
    
    logger.info(f"[{wallet_index}/{total_wallets}] | [{wallet_address}] | Модули: {' → '.join(modules)}")
    
    for task_type in modules:
        # Проверяем статус задачи в БД
        task_status = get_wallet_task_status(wallet_address, task_type)
        if task_status and task_status.get('status') == 'completed':
            logger.info(f"[{wallet_address}] {task_type} уже выполнен, пропускаем")
            results[task_type] = True
            continue
        
        update_task_status(wallet_address, task_type, 'in_progress')
        
        _, success, error = await process_wallet_task(
            private_key, proxy, task_type, all_proxies, wallet_index, total_wallets
        )
        
        results[task_type] = success
        if not success:
            errors[task_type] = error
            update_task_status(wallet_address, task_type, 'failed', error)
        else:
            update_task_status(wallet_address, task_type, 'completed')
        
        # Пауза между модулями
        if task_type != modules[-1]:
            delay = random.uniform(*SLEEP_BETWEEN_ACTIONS)
            logger.info(f"[{wallet_address}] Пауза {delay:.1f}с перед следующим модулем...")
            await asyncio.sleep(delay)
    
    return wallet_address, results, errors


def run_wallet_all_modules_sync(
    private_key: str,
    proxy: str,
    task_types: List[str],
    all_proxies: List[str],
    wallet_index: int,
    total_wallets: int
) -> Tuple[str, Dict[str, bool], Dict[str, str]]:
    """Синхронная обёртка для обработки кошелька"""
    return asyncio.run(process_wallet_all_modules(
        private_key, proxy, task_types, all_proxies, wallet_index, total_wallets
    ))


def run_module_pipeline(task_types: List[str]):
    """
    Конвейер обработки модулей Neura.
    Каждый кошелек выполняет ВСЕ модули последовательно, затем переход к следующему кошельку.
    Пример: wallet_1 (collect_pulses → claim_tasks) → wallet_2 (collect_pulses → claim_tasks) → ...
    """
    if not astrum_CAPTCHA_API_KEY or astrum_CAPTCHA_API_KEY.strip() == '':
        logger.error("astrum_CAPTCHA_API_KEY не указан в config/modules/cfg_base.py!")
        logger.warning("Для работы модуля Neura необходим API ключ для решения капчи.")
        logger.info("Получить ключ: https://t.me/astrumsolutionsbot")
        return
    
    # Статистика по модулям
    module_stats = {task: {'success': 0, 'failed': 0} for task in task_types}
    
    private_keys = load_private_keys()
    if not private_keys:
        logger.error("Нет приватных ключей для обработки!")
        return
    
    proxies = load_proxies() if NEURA_USE_PROXY else []
    wallets = prepare_wallets(private_keys)
    
    if SHUFFLE_WALLET_LIST_NEURA:
        random.shuffle(wallets)
        logger.info("Список кошельков перемешан")
    
    init_database()
    
    if all_tasks_completed(task_types):
        logger.info("Все задачи завершены, сбрасываем БД...")
        deleted = reset_database_for_new_run(task_types)
        logger.success(f"Удалено {deleted} задач из БД")
    
    create_tasks_for_wallets(wallets, task_types)
    
    # Фильтруем кошельки с незавершёнными задачами
    wallets_with_pending = []
    for addr, pk in wallets:
        for task_type in task_types:
            task_status = get_wallet_task_status(addr, task_type)
            if not task_status or task_status.get('status') != 'completed':
                wallets_with_pending.append((addr, pk))
                break
    
    if not wallets_with_pending:
        logger.success("Все задачи для всех кошельков уже выполнены!")
        return
    
    logger.info(f"Кошельков: {len(wallets_with_pending)}, Модулей: {len(task_types)}, Потоков: {NUM_THREADS}")
    logger.info(f"Режим: каждый кошелек выполняет все модули последовательно")
    
    if NEURA_TELEGRAM_NOTIFICATIONS and NEURA_TELEGRAM_LOG_LEVEL >= 1:
        send_telegram_notification(
            notif_type="info",
            title="🚀 Neura Protocol Started",
            message=f"Кошельков: {len(wallets_with_pending)}, Модулей: {len(task_types)}\nРежим: по кошелькам",
            main_title="ETHmachine Neura"
        )
    
    # Обрабатываем кошельки в пулах потоков
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures_dict = {}
        proxy_index = 0
        
        for idx, (wallet_address, private_key) in enumerate(wallets_with_pending):
            proxy = None
            if proxies:
                if NEURA_RANDOM_PROXY:
                    proxy = random.choice(proxies)
                else:
                    proxy = proxies[proxy_index % len(proxies)]
                    proxy_index += 1
            
            future = executor.submit(
                run_wallet_all_modules_sync,
                private_key, proxy, task_types, proxies,
                idx + 1, len(wallets_with_pending)
            )
            futures_dict[future] = wallet_address
        
        # Собираем результаты
        for future in futures_dict:
            wallet_addr = futures_dict[future]
            try:
                result_address, results, errors = future.result()
                
                with progress_lock:
                    for task_type, success in results.items():
                        if success:
                            module_stats[task_type]['success'] += 1
                        else:
                            module_stats[task_type]['failed'] += 1
                            
            except Exception as e:
                logger.error(f"[{wallet_addr}] Критическая ошибка: {str(e)}")
                with progress_lock:
                    for task_type in task_types:
                        module_stats[task_type]['failed'] += 1
    
    # Выводим статистику
    logger.info("=" * 50)
    logger.info("📊 Статистика по модулям:")
    for task_type, st in module_stats.items():
        logger.info(f"   {task_type}: ✅ {st['success']} | ❌ {st['failed']}")
    
    final_stats = get_task_statistics()
    
    print(f"\n{Fore.GREEN}🏁 Конвейер завершён!{Style.RESET_ALL}\n")
    for t, s in final_stats.items():
        print(f"  {t}: {s}")
    
    if NEURA_TELEGRAM_NOTIFICATIONS and NEURA_TELEGRAM_LOG_LEVEL >= 1:
        send_telegram_notification(
            notif_type="success",
            title="🏁 Neura Protocol Completed",
            message=f"Статистика: {final_stats}",
            main_title="ETHmachine Neura"
        )


def neura_menu():
    while True:
        action = select(
            "🔮 Neura Protocol - выберите действие:",
            choices=[
                Choice('🚀 Запустить конвейер модулей    🌟 Выполнить все модули из конфига', 'run_pipeline'),
                Choice('📥 Collect Pulses               🌟 Только сбор пульсов', 'collect_pulses'),
                Choice('🎁 Claim Tasks                  🌟 Только клейм задач', 'claim_tasks'),
                Choice('💧 Faucet                       🌟 Получить токены из faucet', 'faucet'),
                Choice('🔄 Swap                         🌟 Выполнить swap токенов', 'swap'),
                Choice('📊 Статистика                   🌟 Показать статус задач', 'show_stats'),
                Choice('🔄 Сбросить failed задачи       🌟 Перезапустить неудачные', 'reset_failed'),
                Choice('🔙 Назад', 'back')
            ],
            qmark='🔮',
            pointer='👉'
        ).ask()
        
        match action:
            case 'run_pipeline':
                run_module_pipeline(NEURA_MODULES)
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
            
            case 'collect_pulses':
                run_module_pipeline(['collect_pulses'])
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
            
            case 'claim_tasks':
                run_module_pipeline(['claim_tasks'])
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
            
            case 'faucet':
                run_module_pipeline(['faucet'])
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
            
            case 'swap':
                run_module_pipeline(['swap'])
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
            
            case 'show_stats':
                db_stats = get_task_statistics()
                print(f"\n{Fore.CYAN}📊 Статистика задач Neura:{Style.RESET_ALL}")
                if not db_stats:
                    print("   Нет данных")
                else:
                    for task_type, status_counts in db_stats.items():
                        print(f"\n   {Fore.CYAN}📌 {task_type}:{Style.RESET_ALL}")
                        for status, count in status_counts.items():
                            if status == 'completed':
                                print(f"      ✅ {Fore.GREEN}{status}: {count}{Style.RESET_ALL}")
                            elif status == 'failed':
                                print(f"      ❌ {Fore.RED}{status}: {count}{Style.RESET_ALL}")
                            else:
                                print(f"      ⏳ {Fore.YELLOW}{status}: {count}{Style.RESET_ALL}")
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
            
            case 'reset_failed':
                count = reset_failed_tasks()
                print(f"{Fore.GREEN}🔄 Сброшено {count} failed задач в pending{Style.RESET_ALL}")
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
            
            case 'back':
                return


if __name__ == "__main__":
    neura_menu()
