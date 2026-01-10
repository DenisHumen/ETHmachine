import csv
import sys
import time
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from loguru import logger
from colorama import init
from questionary import Choice, select

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.console import Group
from threading import Lock

init(autoreset=True)

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import NUM_THREADS, RETRY_COUNT
from config.networks import NETWORKS, get_network_symbol
from modules.eth.database import (
    init_database, create_balance_tasks, get_pending_tasks,
    update_task_status, reset_database_for_new_run, get_task_statistics
)


console = Console()
PROXY_LIST = []
PROXY_INDEX = 0

# Глобальные переменные для прогресса в стиле Neura
progress_lock = Lock()
stats = {
    'total': 0,
    'success': 0,
    'failed': 0,
    'current_network': '',
    'logs': []
}
MAX_LOGS = 8


def add_log(message: str, level: str = "INFO"):
    """Добавить лог в буфер для отображения"""
    with progress_lock:
        timestamp = time.strftime("%H:%M:%S")
        stats['logs'].append((timestamp, message, level))
        if len(stats['logs']) > MAX_LOGS:
            stats['logs'] = stats['logs'][-MAX_LOGS:]


def load_wallets() -> list:
    wallet_file = project_root / 'data' / 'walletss.txt'
    wallets = []
    
    try:
        with open(wallet_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and line.startswith('0x'):
                    wallets.append(line)
        logger.info(f"Загружено {len(wallets)} кошельков")
    except FileNotFoundError:
        logger.error(f"Файл {wallet_file} не найден!")
    except Exception as e:
        logger.error(f"Ошибка загрузки кошельков: {e}")
    
    return wallets


def load_proxies() -> list:
    global PROXY_LIST
    proxy_file = project_root / 'data' / 'proxy.csv'
    
    try:
        with open(proxy_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and '@' in line and ':' in line:
                    PROXY_LIST.append(line)
        logger.info(f"Загружено {len(PROXY_LIST)} прокси")
    except FileNotFoundError:
        logger.warning("Файл proxy.csv не найден - работаем без прокси")
    except Exception as e:
        logger.warning(f"Ошибка загрузки прокси: {e}")
    
    return PROXY_LIST


def get_next_proxy() -> dict:
    global PROXY_INDEX, PROXY_LIST
    
    if not PROXY_LIST:
        return None
    
    proxy_str = PROXY_LIST[PROXY_INDEX % len(PROXY_LIST)]
    PROXY_INDEX += 1
    
    try:
        auth, addr = proxy_str.split('@')
        proxy_url = f"http://{auth}@{addr}"
        return {'http': proxy_url, 'https': proxy_url}
    except:
        return None


def get_random_proxy() -> dict:
    if not PROXY_LIST:
        return None
    
    proxy_str = random.choice(PROXY_LIST)
    try:
        auth, addr = proxy_str.split('@')
        proxy_url = f"http://{auth}@{addr}"
        return {'http': proxy_url, 'https': proxy_url}
    except:
        return None


def get_balance_via_rpc(wallet: str, rpc_url: str, proxy: dict = None, timeout: int = 10) -> float:
    try:
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_getBalance",
            "params": [wallet, "latest"],
            "id": 1
        }
        
        response = requests.post(
            rpc_url,
            json=payload,
            proxies=proxy,
            timeout=timeout,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and data['result']:
                balance_wei = int(data['result'], 16)
                return balance_wei / 10**18
        
        return -1
        
    except requests.exceptions.Timeout:
        return -1
    except requests.exceptions.RequestException:
        return -1
    except Exception:
        return -1


def check_single_wallet(wallet: str, rpc_urls: list, network_name: str, symbol: str) -> dict:
    short_addr = f"{wallet[:6]}...{wallet[-4:]}"
    
    proxy = get_next_proxy()
    
    max_attempts = min(RETRY_COUNT, len(rpc_urls))
    
    for attempt in range(max_attempts):
        rpc_url = rpc_urls[attempt % len(rpc_urls)]
        
        balance = get_balance_via_rpc(wallet, rpc_url, proxy, timeout=10)
        
        if balance >= 0:
            return {
                'wallet': wallet,
                'balance': balance,
                'symbol': symbol,
                'network': network_name,
                'success': True,
                'error': None
            }
        
        proxy = get_random_proxy()
    
    return {
        'wallet': wallet,
        'balance': 0,
        'symbol': symbol,
        'network': network_name,
        'success': False,
        'error': 'All RPC failed'
    }


def create_progress_panel() -> Panel:
    """Создать панель прогресса в стиле Ubuntu/Neura"""
    with progress_lock:
        total = stats['total']
        success = stats['success']
        failed = stats['failed']
        processed = success + failed
        network = stats['current_network']
        logs_copy = list(stats['logs'])
    
    percent = (processed / total * 100) if total > 0 else 0
    success_rate = (success / processed * 100) if processed > 0 else 0
    
    # Прогресс бар в стиле Ubuntu
    bar_width = 40
    filled = int(bar_width * percent / 100)
    bar_filled = "━" * filled
    bar_empty = "─" * (bar_width - filled)
    
    # Цвет бара в зависимости от успешности
    if success_rate >= 80:
        bar_style = "bright_green"
    elif success_rate >= 50:
        bar_style = "yellow"
    else:
        bar_style = "red"
    
    # Таблица статистики
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
        "📊 Всего:", Text(str(total), style="bold"),
        "⚡ Потоков:", Text(str(NUM_THREADS), style="bold cyan")
    )
    
    # Заголовок сети
    header = Text()
    header.append(f"\n🌐 ", style="bold")
    header.append(f"{network}\n", style="bold cyan")
    
    # Прогресс бар
    progress_bar = Text()
    progress_bar.append(bar_filled, style=f"bold {bar_style}")
    progress_bar.append(bar_empty, style="dim")
    progress_bar.append(f" {percent:.1f}%\n", style=f"bold {bar_style}")
    
    # Обработано
    processed_text = Text()
    processed_text.append(f"Обработано: ", style="dim")
    processed_text.append(f"{processed}/{total}\n\n", style="bold")
    
    # Логи
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
        title="[bold bright_blue]💰 ETH BALANCE CHECKER[/bold bright_blue]",
        subtitle="[dim]ETHmachine v2.0[/dim]",
        border_style="bright_blue",
        padding=(1, 2)
    )


def process_wallets_batch(wallets: list, rpc_urls: list, network_name: str, symbol: str) -> dict:
    """Обрабатывает кошельки и возвращает dict {wallet: result} для сохранения порядка"""
    global stats
    
    results_dict = {}  # Словарь для сохранения порядка
    total = len(wallets)
    max_workers = min(NUM_THREADS, total, 20)
    
    # Инициализация статистики
    with progress_lock:
        stats['total'] = total
        stats['success'] = 0
        stats['failed'] = 0
        stats['current_network'] = network_name
        stats['logs'] = []
    
    add_log(f"Запуск проверки {total} кошельков", "INFO")
    add_log(f"Потоков: {max_workers}, RPC: {len(rpc_urls)}", "INFO")
    
    with Live(create_progress_panel(), refresh_per_second=4, console=console, screen=False) as live:
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_wallet = {
                executor.submit(check_single_wallet, wallet, rpc_urls, network_name, symbol): wallet
                for wallet in wallets
            }
            
            for future in as_completed(future_to_wallet):
                wallet = future_to_wallet[future]
                short_addr = f"{wallet[:6]}...{wallet[-4:]}"
                
                try:
                    result = future.result(timeout=60)
                    results_dict[wallet] = result
                    
                    with progress_lock:
                        if result['success']:
                            stats['success'] += 1
                            update_task_status(
                                wallet, 'native_balance', 'completed',
                                network=network_name,
                                balance=str(result['balance']),
                                balance_usdt='0'
                            )
                            if result['balance'] > 0:
                                add_log(f"[{short_addr}] ✅ {result['balance']:.6f} {symbol}", "SUCCESS")
                            else:
                                add_log(f"[{short_addr}] ✅ 0 {symbol}", "SUCCESS")
                        else:
                            stats['failed'] += 1
                            update_task_status(
                                wallet, 'native_balance', 'failed',
                                network=network_name,
                                error_message=result['error']
                            )
                            add_log(f"[{short_addr}] ❌ {result['error']}", "ERROR")
                        
                except Exception as e:
                    with progress_lock:
                        stats['failed'] += 1
                    results_dict[wallet] = {
                        'wallet': wallet,
                        'balance': 0,
                        'symbol': symbol,
                        'network': network_name,
                        'success': False,
                        'error': str(e)[:50]
                    }
                    update_task_status(
                        wallet, 'native_balance', 'failed',
                        network=network_name,
                        error_message=str(e)[:100]
                    )
                    add_log(f"[{short_addr}] ❌ {str(e)[:30]}", "ERROR")
                
                live.update(create_progress_panel())
    
    return results_dict


def save_results_to_csv(results_dict: dict, original_wallets: list, network_name: str):
    """Сохраняет результаты в CSV в порядке original_wallets"""
    result_dir = project_root / 'result'
    result_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_network = network_name.replace('🚀 ', '').replace(' ', '_')
    filename = result_dir / f"balances_{clean_network}_{timestamp}.csv"
    
    main_file = result_dir / 'result.csv'
    
    try:
        for filepath in [filename, main_file]:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['wallet', 'balance', 'symbol', 'network', 'status'])
                
                # Сохраняем в порядке original_wallets
                for wallet in original_wallets:
                    if wallet in results_dict:
                        r = results_dict[wallet]
                        status = 'OK' if r['success'] else f"ERROR: {r['error']}"
                        writer.writerow([r['wallet'], r['balance'], r['symbol'], r['network'], status])
                    else:
                        # Если результата нет - записываем как ошибку
                        writer.writerow([wallet, 0, '', network_name, 'ERROR: Not processed'])
        
        add_log(f"💾 Результаты сохранены", "SUCCESS")
        return filename
        
    except Exception as e:
        add_log(f"❌ Ошибка сохранения: {e}", "ERROR")
        return None


def print_results_summary(results_dict: dict, symbol: str):
    results = list(results_dict.values())
    success_results = [r for r in results if r['success']]
    failed_results = [r for r in results if not r['success']]
    
    total_balance = sum(r['balance'] for r in success_results)
    
    console.print("\n" + "="*60)
    console.print(f"[bold cyan]📊 ИТОГИ ПРОВЕРКИ[/bold cyan]")
    console.print("="*60)
    console.print(f"[green]✅ Успешно проверено: {len(success_results)}[/green]")
    console.print(f"[red]❌ Ошибки: {len(failed_results)}[/red]")
    console.print(f"[yellow]💰 Общий баланс: {total_balance:.6f} {symbol}[/yellow]")
    console.print("="*60)
    
    wallets_with_balance = [r for r in success_results if r['balance'] > 0]
    if wallets_with_balance:
        wallets_with_balance.sort(key=lambda x: x['balance'], reverse=True)
        
        console.print("\n[bold cyan]🏆 Топ кошельков с балансом:[/bold cyan]")
        for i, r in enumerate(wallets_with_balance[:10], 1):
            console.print(f"  {i}. {r['wallet'][:10]}...{r['wallet'][-6:]} → [green]{r['balance']:.6f} {symbol}[/green]")
    
    console.print()


def check_wallet_balances_menu():
    wallets = load_wallets()
    if not wallets:
        logger.error("Нет кошельков для проверки!")
        return
    
    load_proxies()
    
    network_type = select(
        "\n╔════════════════════════════════════════════════╗\n"
        "║      Выбор типа сети / Network Type            ║\n"
        "╚════════════════════════════════════════════════╝",
        choices=[
            Choice('   🌐 Mainnet Networks', 'mainnet'),
            Choice('   🔧 Testnet Networks', 'testnet'),
            Choice('   🌐 Все Mainnet сети', 'all_mainnet'),
            Choice('   🔧 Все Testnet сети', 'all_testnet'),
            Choice('   🔙 Назад / Back', 'back')
        ],
        qmark='🛠️ ',
        pointer='👉'
    ).ask()
    
    if network_type == 'back' or not network_type:
        return
    
    if network_type == 'mainnet':
        networks = {k: v for k, v in NETWORKS.items() if v['type'] == 'mainnet'}
    elif network_type == 'testnet':
        networks = {k: v for k, v in NETWORKS.items() if v['type'] == 'testnet'}
    elif network_type == 'all_mainnet':
        networks = {k: v for k, v in NETWORKS.items() if v['type'] == 'mainnet'}
    elif network_type == 'all_testnet':
        networks = {k: v for k, v in NETWORKS.items() if v['type'] == 'testnet'}
    else:
        return
    
    if network_type in ['mainnet', 'testnet']:
        network_choices = [Choice(name, name) for name in networks.keys()]
        network_choices.append(Choice('🔙 Назад', 'back'))
        
        selected_network = select(
            "Выберите сеть:",
            choices=network_choices,
            qmark='🛠️',
            pointer='👉'
        ).ask()
        
        if selected_network == 'back' or not selected_network:
            return
        
        networks = {selected_network: networks[selected_network]}
    
    action = select(
        "\n╔════════════════════════════════════════════════╗\n"
        "║      Действие с базой данных                   ║\n"
        "╚════════════════════════════════════════════════╝",
        choices=[
            Choice('   ▶️  Продолжить незавершённые задачи', 'continue'),
            Choice('   🔄 Начать заново (сброс БД)', 'reset'),
            Choice('   🔙 Назад', 'back')
        ],
        qmark='🛠️ ',
        pointer='👉'
    ).ask()
    
    if action == 'back' or not action:
        return
    
    all_results = {}  # dict для сохранения порядка
    
    for network_name, network_data in networks.items():
        rpc_urls = network_data['rpc_urls']
        symbol = network_data['symbol']
        
        console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
        console.print(f"[bold cyan]🌐 Сеть: {network_name}[/bold cyan]")
        console.print(f"[bold cyan]{'='*60}[/bold cyan]")
        
        init_database()
        
        if action == 'reset':
            reset_database_for_new_run('native_balance', network_name)
            create_balance_tasks(wallets, 'native_balance', network_name)
        
        pending = get_pending_tasks('native_balance', network_name)
        
        if not pending:
            create_balance_tasks(wallets, 'native_balance', network_name)
            pending = get_pending_tasks('native_balance', network_name)
        
        if not pending:
            console.print(f"[yellow]⚠️ Все задачи уже выполнены для {network_name}[/yellow]")
            continue
        
        wallets_to_check = [t['wallet_address'] for t in pending]
        console.print(f"[cyan]📋 Задач для обработки: {len(wallets_to_check)}[/cyan]")
        
        results_dict = process_wallets_batch(wallets_to_check, rpc_urls, network_name, symbol)
        all_results.update(results_dict)
        
        # Сохраняем в порядке оригинального списка wallets
        save_results_to_csv(results_dict, wallets, network_name)
        
        print_results_summary(results_dict, symbol)
    
    console.print("\n[bold green]✅ Проверка завершена![/bold green]\n")
    
    try:
        from modules.notifications import send_telegram_notification
        
        all_results_list = list(all_results.values())
        success_count = len([r for r in all_results_list if r['success']])
        failed_count = len([r for r in all_results_list if not r['success']])
        
        send_telegram_notification(
            notif_type="success",
            title="Проверка балансов завершена",
            message=f"Всего: {len(all_results_list)}\nУспешно: {success_count}\nОшибок: {failed_count}",
            main_title="ETHmachine Balance Check"
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление: {e}")


if __name__ == "__main__":
    check_wallet_balances_menu()

