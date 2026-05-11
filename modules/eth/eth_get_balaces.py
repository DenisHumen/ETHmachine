"""
Модуль проверки балансов нативных токенов EVM кошельков
v3.1 - Без Lock, простой и надёжный
"""

import csv
import sys
import time
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from colorama import init
from questionary import Choice, select

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.console import Group

init(autoreset=True)

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.modules.general_config import NUM_THREADS
from config.networks import NETWORKS, get_network_display_name
from modules.eth.database import (
    init_database, create_balance_tasks, get_pending_tasks,
    update_task_status, reset_database_for_new_run
)

console = Console()


def load_wallets() -> list:
    from modules.data_manager import get_wallet_addresses
    wallets = get_wallet_addresses()
    if not wallets:
        console.print("[yellow]Нет wallet_address в data.csv, пробуем private_key...[/yellow]")
        from modules.data_manager import get_private_keys
        from eth_account import Account
        for pk in get_private_keys():
            try:
                pk_hex = pk if pk.startswith('0x') else f'0x{pk}'
                wallets.append(Account.from_key(pk_hex).address)
            except Exception:
                pass
    return wallets


def load_proxies() -> list:
    from modules.data_manager import get_proxies
    return get_proxies()


def make_proxy_dict(proxy_str: str) -> dict:
    if not proxy_str:
        return None
    try:
        auth, addr = proxy_str.split('@')
        proxy_url = f"http://{auth}@{addr}"
        return {'http': proxy_url, 'https': proxy_url}
    except:
        return None


def get_balance_rpc(wallet: str, rpc_url: str, proxy_dict: dict = None) -> float:
    """Получение баланса через JSON-RPC. Возвращает баланс или -1 при ошибке."""
    try:
        resp = requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "method": "eth_getBalance", "params": [wallet, "latest"], "id": 1},
            proxies=proxy_dict,
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )
        if resp.status_code == 200:
            data = resp.json()
            if 'result' in data and data['result']:
                return int(data['result'], 16) / 10**18
        return -1
    except:
        return -1


def check_wallet(wallet: str, rpc_urls: list, proxies: list, proxy_idx: int) -> dict:
    """Проверка одного кошелька. Возвращает результат."""
    # Получаем прокси по индексу
    proxy_str = proxies[proxy_idx % len(proxies)] if proxies else None
    proxy_dict = make_proxy_dict(proxy_str)
    
    for rpc_url in rpc_urls[:3]:  # Максимум 3 RPC
        balance = get_balance_rpc(wallet, rpc_url, proxy_dict)
        if balance >= 0:
            return {'wallet': wallet, 'balance': balance, 'success': True, 'error': None}
        # Меняем прокси при ошибке
        if proxies:
            proxy_str = random.choice(proxies)
            proxy_dict = make_proxy_dict(proxy_str)
    
    return {'wallet': wallet, 'balance': 0, 'success': False, 'error': 'RPC failed'}


def create_panel(network: str, total: int, success: int, failed: int, logs: list) -> Panel:
    """Создание панели прогресса в стиле Ubuntu/Neura"""
    processed = success + failed
    percent = (processed / total * 100) if total > 0 else 0
    
    # Прогресс бар
    bar_width = 40
    filled = int(bar_width * percent / 100)
    bar_filled = "━" * filled
    bar_empty = "─" * (bar_width - filled)
    
    # Цвет бара
    success_rate = (success / processed * 100) if processed > 0 else 100
    bar_style = "bright_green" if success_rate >= 80 else "yellow" if success_rate >= 50 else "red"
    
    # Таблица статистики
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("L1", style="dim")
    table.add_column("V1")
    table.add_column("L2", style="dim")
    table.add_column("V2")
    table.add_row(
        "✅ Успешно:", Text(str(success), style="bold green"),
        "❌ Ошибки:", Text(str(failed), style="bold red")
    )
    table.add_row(
        "📊 Всего:", Text(str(total), style="bold"),
        "⚡ Потоков:", Text(str(NUM_THREADS), style="bold cyan")
    )
    
    # Заголовок
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
    for ts, msg, lvl in logs[-8:]:
        logs_section.append(f"  {ts} ", style="dim")
        style = {"SUCCESS": "green", "ERROR": "red", "WARNING": "yellow"}.get(lvl, "white")
        logs_section.append(f"{msg}\n", style=style)
    if not logs:
        logs_section.append("  Ожидание...\n", style="dim")
    
    content = Group(header, progress_bar, processed_text, table, Text(""), logs_section)
    
    return Panel(
        content,
        title="[bold bright_blue]💰 ETH BALANCE CHECKER[/bold bright_blue]",
        subtitle="[dim]ETHmachine v2.0[/dim]",
        border_style="bright_blue",
        padding=(1, 2)
    )


def process_wallets(wallets: list, rpc_urls: list, network_name: str, symbol: str) -> dict:
    """Обработка кошельков с прогресс-баром. Возвращает dict для сохранения порядка."""
    results = {}
    total = len(wallets)
    success = 0
    failed = 0
    logs = []  # (timestamp, message, level)
    
    proxies = load_proxies()
    max_workers = min(NUM_THREADS, total, 20)
    
    logs.append((time.strftime("%H:%M:%S"), f"Запуск {total} кошельков в {max_workers} потоках", "INFO"))
    
    with Live(create_panel(network_name, total, 0, 0, logs), console=console, refresh_per_second=4) as live:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Создаём задачи с индексом для прокси
            futures = {
                executor.submit(check_wallet, wallet, rpc_urls, proxies, idx): wallet
                for idx, wallet in enumerate(wallets)
            }
            
            for future in as_completed(futures):
                wallet = futures[future]
                short = f"{wallet[:6]}...{wallet[-4:]}"
                
                try:
                    result = future.result(timeout=30)
                    results[wallet] = result
                    
                    if result['success']:
                        success += 1
                        update_task_status(wallet, 'native_balance', 'completed', network=network_name, balance=str(result['balance']))
                        if result['balance'] > 0:
                            logs.append((time.strftime("%H:%M:%S"), f"[{short}] ✅ {result['balance']:.6f} {symbol}", "SUCCESS"))
                        else:
                            logs.append((time.strftime("%H:%M:%S"), f"[{short}] ✅ 0 {symbol}", "SUCCESS"))
                    else:
                        failed += 1
                        update_task_status(wallet, 'native_balance', 'failed', network=network_name, error_message=result['error'])
                        logs.append((time.strftime("%H:%M:%S"), f"[{short}] ❌ {result['error']}", "ERROR"))
                except Exception as e:
                    failed += 1
                    results[wallet] = {'wallet': wallet, 'balance': 0, 'success': False, 'error': str(e)[:30]}
                    update_task_status(wallet, 'native_balance', 'failed', network=network_name, error_message=str(e)[:50])
                    logs.append((time.strftime("%H:%M:%S"), f"[{short}] ❌ {str(e)[:20]}", "ERROR"))
                
                # Обновляем панель
                live.update(create_panel(network_name, total, success, failed, logs))
    
    return results


def save_results(results: dict, wallets: list, network_name: str, symbol: str):
    """Сохранение результатов в порядке wallets"""
    result_dir = project_root / 'result'
    result_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_network = network_name.replace('🚀 ', '').replace(' ', '_')
    
    for filepath in [result_dir / f"balances_{clean_network}_{timestamp}.csv", result_dir / 'result.csv']:
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['wallet', 'balance', 'symbol', 'network', 'status'])
            for wallet in wallets:
                if wallet in results:
                    r = results[wallet]
                    status = 'OK' if r['success'] else f"ERROR: {r['error']}"
                    writer.writerow([wallet, r['balance'], symbol, network_name, status])
                else:
                    writer.writerow([wallet, 0, symbol, network_name, 'ERROR: Not processed'])
    
    console.print(f"[green]💾 Результаты сохранены в result/result.csv[/green]")


def print_summary(results: dict, symbol: str):
    """Вывод итогов"""
    success_list = [r for r in results.values() if r['success']]
    failed_list = [r for r in results.values() if not r['success']]
    total_balance = sum(r['balance'] for r in success_list)
    
    console.print("\n" + "="*60)
    console.print(f"[bold cyan]📊 ИТОГИ ПРОВЕРКИ[/bold cyan]")
    console.print("="*60)
    console.print(f"[green]✅ Успешно: {len(success_list)}[/green]")
    console.print(f"[red]❌ Ошибки: {len(failed_list)}[/red]")
    console.print(f"[yellow]💰 Общий баланс: {total_balance:.6f} {symbol}[/yellow]")
    console.print("="*60)
    
    # Топ кошельков с балансом
    with_balance = sorted([r for r in success_list if r['balance'] > 0], key=lambda x: x['balance'], reverse=True)
    if with_balance:
        console.print("\n[bold cyan]🏆 Топ кошельков с балансом:[/bold cyan]")
        for i, r in enumerate(with_balance[:10], 1):
            console.print(f"  {i}. {r['wallet'][:10]}...{r['wallet'][-6:]} → [green]{r['balance']:.6f} {symbol}[/green]")


def check_wallet_balances_menu():
    """Главное меню"""
    wallets = load_wallets()
    if not wallets:
        console.print("[red]❌ Нет кошельков![/red]")
        return
    
    console.print(f"[cyan]📋 Загружено {len(wallets)} кошельков[/cyan]")
    
    # Выбор типа сети
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
    
    # Получаем сети
    networks = {k: v for k, v in NETWORKS.items() if v['type'] == ('mainnet' if 'mainnet' in network_type else 'testnet')}
    
    # Если выбрана одна сеть
    if network_type in ['mainnet', 'testnet']:
        choices = [Choice(get_network_display_name(name), name) for name in networks.keys()] + [Choice('🔙 Назад', 'back')]
        selected = select("Выберите сеть:", choices=choices, qmark='🛠️', pointer='👉').ask()
        if selected == 'back' or not selected:
            return
        networks = {selected: networks[selected]}
    
    # Действие с БД
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
    
    all_results = {}
    
    for network_name, network_data in networks.items():
        # Networks with an `oklink_chain` flag are checked through the OKLink
        # multi-token checker (native + all ERC20 in one shot, with Excel export).
        oklink_chain = network_data.get('oklink_chain')
        if oklink_chain:
            from modules.eth.oklink_balance_checker import run_oklink_balance_check
            console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
            console.print(f"[bold cyan]🌐 Сеть: {network_name} (OKLink)[/bold cyan]")
            console.print(f"[bold cyan]{'='*60}[/bold cyan]")
            run_oklink_balance_check(wallets, network_name, oklink_chain)
            continue

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
            console.print(f"[yellow]⚠️ Все задачи уже выполнены[/yellow]")
            continue
        
        wallets_to_check = [t['wallet_address'] for t in pending]
        console.print(f"[cyan]📋 Задач: {len(wallets_to_check)}[/cyan]")
        
        # Обработка
        results = process_wallets(wallets_to_check, rpc_urls, network_name, symbol)
        all_results.update(results)
        
        # Сохранение в порядке wallets
        save_results(results, wallets, network_name, symbol)
        print_summary(results, symbol)
    
    console.print("\n[bold green]✅ Проверка завершена![/bold green]\n")
    
    # Telegram
    try:
        results_list = list(all_results.values())
    except:
        pass


if __name__ == "__main__":
    check_wallet_balances_menu()

