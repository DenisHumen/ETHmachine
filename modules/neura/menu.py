import sys
import csv
import random
import asyncio
import time
from pathlib import Path
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Thread

from loguru import logger
from colorama import Fore, Style, init as colorama_init
from questionary import Choice, select

from rich.console import Console, Group
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn, 
    TimeElapsedColumn, TimeRemainingColumn, TaskProgressColumn,
    MofNCompleteColumn
)
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.style import Style as RichStyle

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import (
    NUM_THREADS, SLEEP_BETWEEN_ACTIONS, RETRY_COUNT,
    NEURA_MODULES, NEURA_USE_PROXY, NEURA_RANDOM_PROXY,
    NEURA_TELEGRAM_NOTIFICATIONS, NEURA_TELEGRAM_LOG_LEVEL,
    astrum_CAPTCHA_API_KEY, SHUFFLE_WALLET_LIST_NEURA,
    NEURA_RANDOM_MODULE_ORDER
)
from config.networks import NETWORKS
from modules.neura.client import NeuraClient
from modules.neura.database import (
    init_database, create_tasks_for_wallets, get_pending_tasks,
    update_task_status, get_task_statistics, reset_failed_tasks,
    all_tasks_completed, reset_database_for_new_run
)
from modules.notifications import send_telegram_notification

colorama_init(autoreset=False)
console = Console()

progress_lock = Lock()
stats = {
    'total': 0,
    'success': 0,
    'failed': 0,
    'sent': 0,  
    'current_module': '',
    'current_wallet': '',
    'logs': [],
    'start_time': None,
    'total_points_earned': 0
}

MAX_LOGS = 12  


def add_log(message: str, level: str = "INFO"):
    """Добавить лог в буфер для отображения"""
    with progress_lock:
        timestamp = time.strftime("%H:%M:%S")
        stats['logs'].append((timestamp, message, level))
        if len(stats['logs']) > MAX_LOGS:
            stats['logs'] = stats['logs'][-MAX_LOGS:]


def create_progress_panel() -> Panel:
    """Создать панель прогресса в стиле Ubuntu"""
    with progress_lock:
        total = stats['total']
        success = stats['success']
        failed = stats['failed']
        sent = stats.get('sent', 0)
        in_progress = max(0, sent - success - failed)
        processed = success + failed
        module = stats['current_module']
        logs_copy = list(stats['logs'])
        start_time = stats.get('start_time')
        
    percent = (processed / total * 100) if total > 0 else 0
    success_rate = (success / processed * 100) if processed > 0 else 0
    
    elapsed_str = "00:00:00"
    eta_str = "рассчёт..."
    if start_time:
        elapsed = time.time() - start_time
        elapsed_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))
        if processed > 0 and processed < total:
            avg_time = elapsed / processed
            remaining = (total - processed) * avg_time
            eta_str = time.strftime("%H:%M:%S", time.gmtime(remaining))
        elif processed >= total:
            eta_str = "завершено"
    
    bar_width = 40
    filled = int(bar_width * percent / 100)
    bar_filled = "━" * filled
    bar_empty = "─" * (bar_width - filled)
    
    if success_rate >= 80:
        bar_style = "bright_green"
    elif success_rate >= 50:
        bar_style = "yellow"
    else:
        bar_style = "red"
    
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Label", style="dim")
    table.add_column("Value")
    table.add_column("Label2", style="dim")
    table.add_column("Value2")
    
    table.add_row(
        "✅ Успешно:", Text(str(success), style="bold green"),
        "❌ Ошибки:", Text(str(failed), style="bold red")
    )
    table.add_row(
        "⏳ В работе:", Text(str(in_progress), style="bold yellow"),
        "📊 Всего:", Text(str(total), style="bold")
    )
    table.add_row(
        "⏱️ Время:", Text(elapsed_str, style="bold cyan"),
        "🏁 Осталось:", Text(eta_str, style="bold magenta")
    )
    table.add_row(
        "⚡ Потоков:", Text(str(NUM_THREADS), style="bold cyan"),
        "📈 Успех:", Text(f"{success_rate:.1f}%", style="bold green" if success_rate >= 80 else "bold yellow")
    )
    
    header = Text()
    header.append(f"\n🔮 ", style="bold")
    header.append(f"{module}\n", style="bold cyan")
    
    progress_bar = Text()
    progress_bar.append(bar_filled, style=f"bold {bar_style}")
    progress_bar.append(bar_empty, style="dim")
    progress_bar.append(f" {percent:.1f}%\n", style=f"bold {bar_style}")
    
    processed_text = Text()
    processed_text.append(f"Обработано: ", style="dim")
    processed_text.append(f"{processed}/{total}", style="bold")
    processed_text.append(f" | Ожидает: ", style="dim")
    processed_text.append(f"{total - processed - in_progress}\n\n", style="bold")
    
    logs_section = Text()
    logs_section.append("📝 Последние события:\n", style="bold")
    
    if logs_copy:
        for timestamp, message, level in logs_copy[-MAX_LOGS:]:
            logs_section.append(f"  {timestamp} ", style="dim")
            level_style = {
                "SUCCESS": "green",
                "ERROR": "red", 
                "WARNING": "yellow",
                "INFO": "white"
            }.get(level, "white")
            logs_section.append(f"{message}\n", style=level_style)
    else:
        logs_section.append("  Ожидание...\n", style="dim")
    
    content = Group(
        header,
        progress_bar,
        processed_text,
        table,
        Text(""),
        logs_section
    )
    
    return Panel(
        content,
        title="[bold bright_blue]🚀 NEURA PROTOCOL[/bold bright_blue]",
        subtitle="[dim]ETHmachine v2.0[/dim]",
        border_style="bright_blue",
        padding=(1, 2)
    )


logger.remove()


def load_private_keys() -> List[str]:
    keys_file = project_root / 'data' / 'private_keys.txt'
    
    if not keys_file.exists():
        add_log(f"Файл {keys_file} не найден!", "ERROR")
        return []
    
    with open(keys_file, 'r') as f:
        keys = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    add_log(f"Загружено {len(keys)} приватных ключей", "INFO")
    return keys


def load_proxies() -> List[str]:
    proxy_file = project_root / 'data' / 'proxy.csv'
    
    if not proxy_file.exists():
        add_log("Файл proxy.csv не найден, работаем без прокси", "WARNING")
        return []
    
    proxies = []
    with open(proxy_file, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0].strip():
                proxies.append(row[0].strip())
    
    add_log(f"Загружено {len(proxies)} прокси", "INFO")
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
            add_log(f"Ошибка при обработке ключа: {e}", "ERROR")
    return wallets


def get_randomized_modules(modules: List[str]) -> List[str]:
    """
    Рандомизировать порядок модулей, оставляя claim_tasks последним.
    """
    if not NEURA_RANDOM_MODULE_ORDER:
        return modules
    
    # Отделяем claim_tasks
    modules_copy = [m for m in modules if m != 'claim_tasks']
    has_claim_tasks = 'claim_tasks' in modules
    
    # Рандомизируем остальные модули
    random.shuffle(modules_copy)
    
    # Добавляем claim_tasks в конец если он был
    if has_claim_tasks:
        modules_copy.append('claim_tasks')
    
    return modules_copy


async def process_wallet_task(
    private_key: str, 
    proxy: str, 
    task_type: str,
    all_proxies: List[str] = None
) -> Tuple[str, bool, str]:

    wallet_address = get_wallet_address_from_key(private_key)
    current_proxy = proxy
    last_error = ""
    proxy_ip = current_proxy.split('@')[-1] if current_proxy and '@' in current_proxy else (current_proxy[:20] if current_proxy else 'No proxy')
    
    add_log(f"[{wallet_address}] 🚀 Старт | Proxy: {proxy_ip}", "INFO")
    
    for attempt in range(RETRY_COUNT):
        try:
            async with NeuraClient(private_key=private_key, proxy=current_proxy) as client:
                if not await client.authorize():
                    last_error = "Authorization failed"
                    add_log(f"[{wallet_address}] ⚠️ Auth failed (попытка {attempt + 1}/{RETRY_COUNT}), смена прокси...", "WARNING")
                    if all_proxies and len(all_proxies) > 1:
                        current_proxy = random.choice([p for p in all_proxies if p != current_proxy] or all_proxies)
                        proxy_ip = current_proxy.split('@')[-1] if '@' in current_proxy else current_proxy[:20]
                    await asyncio.sleep(random.uniform(3, 7)) 
                    continue
                
                success = False
                
                if task_type == 'collect_pulses':
                    user_data = await client.get_user()
                    uncollected_count = 0
                    if client.user_data and client.user_data.pulses:
                        uncollected_count = len([p for p in client.user_data.pulses.data if not p.is_collected])
                    
                    if uncollected_count == 0:
                        add_log(f"[{wallet_address}] ✅ Все пульсы уже собраны", "SUCCESS")
                        return wallet_address, True, ""
                    
                    success = await client.collect_pulses()
                    
                    if success:
                        add_log(f"[{wallet_address}] ✅ Собрано {uncollected_count} пульсов", "SUCCESS")
                        return wallet_address, True, ""
                        
                elif task_type == 'claim_tasks':
                    tasks = await client._get_tasks()
                    claimable = len([t for t in tasks if t.get('status') == 'claimable']) if tasks else 0
                    
                    if claimable == 0:
                        add_log(f"[{wallet_address}] ✅ Все задачи уже заклеймлены", "SUCCESS")
                        return wallet_address, True, ""
                    
                    success = await client.claim_tasks()
                    
                    if success:
                        add_log(f"[{wallet_address}] ✅ Заклеймлено {claimable} задач", "SUCCESS")
                        return wallet_address, True, ""
                
                elif task_type == 'faucet':
                    success = await client.request_tokens()
                    
                    if success:
                        add_log(f"[{wallet_address}] ✅ Токены из faucet получены", "SUCCESS")
                        return wallet_address, True, ""
                
                elif task_type == 'swap':
                    # Callback для логирования каждого свапа в реальном времени
                    def swap_progress_callback(swap_num: int, total_swaps: int, tx_hash: str = None, status: str = "progress"):
                        explorer_url = NETWORKS.get('🚀 Neura Testnet', {}).get('tx_url', 'https://testnet-blockscout.infra.neuraprotocol.io/tx/')
                        short_addr = wallet_address[:8] + "..." + wallet_address[-4:]
                        if status == "success" and tx_hash:
                            add_log(f"[{short_addr}] ✅ Swap [{swap_num}/{total_swaps}] | {explorer_url}{tx_hash}", "SUCCESS")
                        elif status == "start":
                            add_log(f"[{short_addr}] 🔄 Swap [{swap_num}/{total_swaps}] начат...", "INFO")
                    
                    success, tx_hashes = await client.execute_swap(progress_callback=swap_progress_callback)
                    
                    if success:
                        if not tx_hashes:
                            add_log(f"[{wallet_address}] ✅ Swap выполнен успешно", "SUCCESS")
                        return wallet_address, True, ""
                
                else:
                    return wallet_address, False, f"Unknown task type: {task_type}"
                
                if not success:
                    last_error = "Task execution failed"
                    add_log(f"[{wallet_address}] ⚠️ Не удалось выполнить, retry {attempt + 1}/{RETRY_COUNT}...", "WARNING")
                    if all_proxies and len(all_proxies) > 1:
                        current_proxy = random.choice([p for p in all_proxies if p != current_proxy] or all_proxies)
                    await asyncio.sleep(random.uniform(2, 5))
                    continue
                
        except Exception as e:
            import traceback
            last_error = str(e)
            full_error = traceback.format_exc()
            add_log(f"[{wallet_address}] ❌ Ошибка: {str(e)}", "ERROR")
            logger.error(f"[{wallet_address}] Full error:\n{full_error}")
            if all_proxies and len(all_proxies) > 1:
                current_proxy = random.choice([p for p in all_proxies if p != current_proxy] or all_proxies)
            await asyncio.sleep(random.uniform(2, 5))
    
    add_log(f"[{wallet_address}] ❌ Все {RETRY_COUNT} попыток исчерпаны | {last_error}", "ERROR")
    return wallet_address, False, last_error


def run_task_sync(private_key: str, proxy: str, task_type: str, all_proxies: List[str] = None) -> Tuple[str, bool, str]:
    return asyncio.run(process_wallet_task(private_key, proxy, task_type, all_proxies))


def run_task_sync_with_delay(private_key: str, proxy: str, task_type: str, all_proxies: List[str] = None, wallet_index: int = 0) -> Tuple[str, bool, str]:
    """
    Запуск задачи с задержкой старта на основе индекса кошелька.
    Это позволяет запустить все задачи параллельно, но каждый кошелёк
    начинает работу с небольшим смещением для равномерного распределения нагрузки.
    """
    # Задержка старта: каждый кошелёк стартует через случайный интервал
    # Распределяем старт равномерно, чтобы не все ломились одновременно
    if wallet_index > 0:
        # Группируем кошельки по потокам, задержка только для разных "волн"
        wave = wallet_index // NUM_THREADS
        if wave > 0:
            delay = wave * random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
            time.sleep(delay)
    
    return asyncio.run(process_wallet_task(private_key, proxy, task_type, all_proxies))


def run_module_pipeline(task_types: List[str]):
    global stats
    
    if not astrum_CAPTCHA_API_KEY or astrum_CAPTCHA_API_KEY.strip() == '':
        console.print("[red]❌ ОШИБКА: astrum_CAPTCHA_API_KEY не указан в config/config.py![/red]")
        console.print("[yellow]⚠️ Для работы модуля Neura необходим API ключ для решения капчи.[/yellow]")
        console.print("[cyan]ℹ️ Получить ключ: https://t.me/astrumsolutionsbot[/cyan]")
        return
    
    # Рандомизируем порядок модулей (claim_tasks всегда последним)
    task_types = get_randomized_modules(task_types)
    
    if NEURA_RANDOM_MODULE_ORDER:
        add_log(f"🔀 Порядок модулей: {' → '.join(task_types)}", "INFO")
    
    stats['logs'] = []
    stats['success'] = 0
    stats['failed'] = 0
    stats['sent'] = 0
    stats['start_time'] = None
    
    private_keys = load_private_keys()
    if not private_keys:
        console.print("[red]❌ Нет приватных ключей для обработки![/red]")
        return
    
    proxies = load_proxies() if NEURA_USE_PROXY else []
    wallets = prepare_wallets(private_keys)
    
    if SHUFFLE_WALLET_LIST_NEURA:
        random.shuffle(wallets)
        add_log("🔀 Список кошельков перемешан", "INFO")
    
    init_database()
    
    if all_tasks_completed(task_types):
        add_log("Все задачи завершены, сбрасываем БД...", "INFO")
        deleted = reset_database_for_new_run(task_types)
        add_log(f"Удалено {deleted} задач из БД", "SUCCESS")
    
    create_tasks_for_wallets(wallets, task_types)
    
    add_log(f"Кошельков: {len(wallets)}, Модулей: {len(task_types)}, Потоков: {NUM_THREADS}", "INFO")
    
    if NEURA_TELEGRAM_NOTIFICATIONS and NEURA_TELEGRAM_LOG_LEVEL >= 1:
        send_telegram_notification(
            notif_type="info",
            title="🚀 Neura Protocol Started",
            message=f"Кошельков: {len(wallets)}, Модулей: {len(task_types)}",
            main_title="ETHmachine Neura"
        )
    
    for task_type in task_types:
        stats['current_module'] = task_type
        stats['success'] = 0
        stats['failed'] = 0
        stats['sent'] = 0
        stats['start_time'] = time.time()
        
        pending_tasks = get_pending_tasks(task_type)
        pending_wallets = {t['wallet_address']: t for t in pending_tasks}
        
        wallets_to_process = [
            (addr, pk) for addr, pk in wallets 
            if addr in pending_wallets
        ]
        
        if not wallets_to_process:
            add_log(f"✅ Все задачи {task_type} уже выполнены!", "SUCCESS")
            continue
        
        stats['total'] = len(wallets_to_process)
        add_log(f"Запуск модуля: {task_type} ({len(wallets_to_process)} задач)", "INFO")
        
        with Live(create_progress_panel(), refresh_per_second=4, console=console, screen=False) as live:
            
            with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
                futures_dict = {} 
                proxy_index = 0
                
                def make_done_callback(wallet_addr, ttype, live_ref):
                    def done_callback(future):
                        try:
                            result_address, success, error_msg = future.result()
                            
                            with progress_lock:
                                if success:
                                    stats['success'] += 1
                                    update_task_status(wallet_addr, ttype, 'completed')
                                else:
                                    stats['failed'] += 1
                                    update_task_status(wallet_addr, ttype, 'failed', error_msg)
                            
                            live_ref.update(create_progress_panel())
                                
                        except Exception as e:
                            import traceback
                            full_error = traceback.format_exc()
                            logger.error(f"[{wallet_addr}] Future callback error:\n{full_error}")
                            with progress_lock:
                                stats['failed'] += 1
                                update_task_status(wallet_addr, ttype, 'failed', str(e))
                                add_log(f"[{wallet_addr}] ❌ Ошибка: {str(e)}", "ERROR")
                            live_ref.update(create_progress_panel())
                    return done_callback
                
                # Отправляем ВСЕ задачи в пул сразу для параллельной обработки
                for idx, (wallet_address, private_key) in enumerate(wallets_to_process):
                    proxy = None
                    if proxies:
                        if NEURA_RANDOM_PROXY:
                            proxy = random.choice(proxies)
                        else:
                            proxy = proxies[proxy_index % len(proxies)]
                            proxy_index += 1
                    
                    update_task_status(wallet_address, task_type, 'in_progress')
                    
                    with progress_lock:
                        stats['sent'] += 1
                    
                    # Передаём индекс для вычисления задержки старта внутри потока
                    future = executor.submit(run_task_sync_with_delay, private_key, proxy, task_type, proxies, idx)
                    futures_dict[future] = wallet_address
                    
                    future.add_done_callback(make_done_callback(wallet_address, task_type, live))
                    
                    live.update(create_progress_panel())
                
                # Ждём завершения всех задач
                for future in futures_dict:
                    try:
                        future.result() 
                    except:
                        pass  
        
        add_log(f"📈 {task_type}: ✅ {stats['success']} | ❌ {stats['failed']}", "INFO")
    
    final_stats = get_task_statistics()
    
    console.print("\n")
    console.print(Panel(
        f"[bold green]🏁 Конвейер завершён![/bold green]\n\n" +
        "\n".join([f"  {t}: {s}" for t, s in final_stats.items()]),
        title="[bold]📊 Финальная статистика[/bold]",
        border_style="green"
    ))
    
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
                Choice('� Faucet                       🌟 Получить токены из faucet', 'faucet'),
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
                console.print("\n[bold]📊 Статистика задач Neura:[/bold]")
                if not db_stats:
                    console.print("   [dim]Нет данных[/dim]")
                else:
                    for task_type, status_counts in db_stats.items():
                        console.print(f"\n   [cyan]📌 {task_type}:[/cyan]")
                        for status, count in status_counts.items():
                            emoji = '✅' if status == 'completed' else '❌' if status == 'failed' else '⏳'
                            color = 'green' if status == 'completed' else 'red' if status == 'failed' else 'yellow'
                            console.print(f"      {emoji} [{color}]{status}: {count}[/{color}]")
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
            
            case 'reset_failed':
                count = reset_failed_tasks()
                console.print(f"[green]🔄 Сброшено {count} failed задач в pending[/green]")
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
            
            case 'back':
                return


if __name__ == "__main__":
    neura_menu()
