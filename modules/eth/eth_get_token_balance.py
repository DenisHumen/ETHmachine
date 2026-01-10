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

init(autoreset=True)

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import NUM_THREADS, RETRY_COUNT
from config.networks import NETWORKS, get_network_symbol
from config import token_address_erc20
from modules.eth.database import (
    init_database, create_balance_tasks, get_pending_tasks,
    update_task_status, reset_database_for_new_run
)

console = Console()


def load_wallets() -> list:
    wallet_file = project_root / 'data' / 'walletss.txt'
    wallets = []
    try:
        with open(wallet_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and line.startswith('0x'):
                    wallets.append(line)
    except Exception as e:
        console.print(f"[red]Ошибка загрузки кошельков: {e}[/red]")
    return wallets


def load_proxies() -> list:
    proxy_file = project_root / 'data' / 'proxy.csv'
    proxies = []
    try:
        with open(proxy_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and '@' in line and ':' in line:
                    proxies.append(line)
    except:
        pass
    return proxies


def make_proxy_dict(proxy_str: str) -> dict:
    if not proxy_str:
        return None
    try:
        auth, addr = proxy_str.split('@')
        proxy_url = f"http://{auth}@{addr}"
        return {'http': proxy_url, 'https': proxy_url}
    except:
        return None


def get_tokens_for_network(network_name: str) -> dict:
    var_name = network_name.lower().replace(' ', '_').replace('-', '_')
    var_name = var_name.replace('🚀_', '').replace('🔧_', '')
    
    if hasattr(token_address_erc20, var_name):
        return getattr(token_address_erc20, var_name)
    
    alternatives = {
        'ethereum': 'ethereum_mainnet',
        'eth': 'ethereum_mainnet',
        'bsc': 'binance_smart_chain',
        'bnb': 'binance_smart_chain',
        'arb': 'arbitrum',
        'op': 'optimism',
        'poly': 'polygon',
        'avax': 'avalanche',
    }
    
    for key, alt_name in alternatives.items():
        if key in var_name.lower():
            if hasattr(token_address_erc20, alt_name):
                return getattr(token_address_erc20, alt_name)
    
    return {}


def get_token_balance_rpc(wallet: str, token_address: str, rpc_url: str, proxy_dict: dict = None) -> float:
    data = f"0x70a08231000000000000000000000000{wallet[2:].lower()}"
    
    try:
        resp = requests.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": token_address, "data": data}, "latest"],
                "id": 1
            },
            proxies=proxy_dict,
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )
        if resp.status_code == 200:
            result = resp.json()
            if 'result' in result and result['result'] and result['result'] != '0x':
                hex_value = result['result']
                if hex_value.startswith('0x'):
                    hex_value = hex_value[2:]
                if hex_value:
                    balance = int(hex_value, 16) / 10**18 
                    return balance
            return 0  
        return -1
    except:
        return -1


def check_wallet_token(wallet: str, token_address: str, rpc_urls: list, proxies: list, proxy_idx: int) -> dict:
    proxy_str = proxies[proxy_idx % len(proxies)] if proxies else None
    proxy_dict = make_proxy_dict(proxy_str)
    
    for rpc_url in rpc_urls[:3]: 
        balance = get_token_balance_rpc(wallet, token_address, rpc_url, proxy_dict)
        if balance >= 0:
            return {'wallet': wallet, 'balance': balance, 'success': True, 'error': None}
        if proxies:
            proxy_str = random.choice(proxies)
            proxy_dict = make_proxy_dict(proxy_str)
    
    return {'wallet': wallet, 'balance': 0, 'success': False, 'error': 'RPC failed'}


def create_panel(network: str, token: str, total: int, success: int, failed: int, logs: list) -> Panel:
    processed = success + failed
    percent = (processed / total * 100) if total > 0 else 0
    
    bar_width = 40
    filled = int(bar_width * percent / 100)
    bar_filled = "━" * filled
    bar_empty = "─" * (bar_width - filled)
    
    success_rate = (success / processed * 100) if processed > 0 else 100
    bar_style = "bright_green" if success_rate >= 80 else "yellow" if success_rate >= 50 else "red"
    
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
    
    header = Text()
    header.append(f"\n🌐 ", style="bold")
    header.append(f"{network}", style="bold cyan")
    header.append(f" | ", style="dim")
    header.append(f"🪙 {token.upper()}\n", style="bold yellow")
    
    progress_bar = Text()
    progress_bar.append(bar_filled, style=f"bold {bar_style}")
    progress_bar.append(bar_empty, style="dim")
    progress_bar.append(f" {percent:.1f}%\n", style=f"bold {bar_style}")
    
    processed_text = Text()
    processed_text.append(f"Обработано: ", style="dim")
    processed_text.append(f"{processed}/{total}\n\n", style="bold")
    
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
        title="[bold bright_blue]🪙 ERC-20 TOKEN BALANCE CHECKER[/bold bright_blue]",
        subtitle="[dim]ETHmachine v2.0[/dim]",
        border_style="bright_blue",
        padding=(1, 2)
    )


def process_wallets_tokens(wallets: list, token_address: str, rpc_urls: list, 
                           network_name: str, token_symbol: str) -> dict:
    results = {}
    total = len(wallets)
    success = 0
    failed = 0
    logs = []  
    
    proxies = load_proxies()
    max_workers = min(NUM_THREADS, total, 20)
    
    logs.append((time.strftime("%H:%M:%S"), f"Запуск {total} кошельков в {max_workers} потоках", "INFO"))
    
    with Live(create_panel(network_name, token_symbol, total, 0, 0, logs), console=console, refresh_per_second=4) as live:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(check_wallet_token, wallet, token_address, rpc_urls, proxies, idx): wallet
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
                        update_task_status(wallet, f'token_{token_symbol}', 'completed', 
                                         network=network_name, balance=str(result['balance']))
                        if result['balance'] > 0:
                            logs.append((time.strftime("%H:%M:%S"), 
                                       f"[{short}] ✅ {result['balance']:.6f} {token_symbol.upper()}", "SUCCESS"))
                        else:
                            logs.append((time.strftime("%H:%M:%S"), 
                                       f"[{short}] ✅ 0 {token_symbol.upper()}", "SUCCESS"))
                    else:
                        failed += 1
                        update_task_status(wallet, f'token_{token_symbol}', 'failed', 
                                         network=network_name, error_message=result['error'])
                        logs.append((time.strftime("%H:%M:%S"), f"[{short}] ❌ {result['error']}", "ERROR"))
                except Exception as e:
                    failed += 1
                    results[wallet] = {'wallet': wallet, 'balance': 0, 'success': False, 'error': str(e)[:30]}
                    update_task_status(wallet, f'token_{token_symbol}', 'failed', 
                                     network=network_name, error_message=str(e)[:50])
                    logs.append((time.strftime("%H:%M:%S"), f"[{short}] ❌ {str(e)[:20]}", "ERROR"))
                
                live.update(create_panel(network_name, token_symbol, total, success, failed, logs))
    
    return results


def save_results(results: dict, wallets: list, network_name: str, token_symbol: str):
    result_dir = project_root / 'result'
    result_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_network = network_name.replace('🚀 ', '').replace(' ', '_')
    
    for filepath in [
        result_dir / f"token_balances_{clean_network}_{token_symbol}_{timestamp}.csv",
        result_dir / 'result.csv'
    ]:
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['wallet', 'balance', 'token', 'network', 'status'])
            for wallet in wallets:
                if wallet in results:
                    r = results[wallet]
                    status = 'OK' if r['success'] else f"ERROR: {r['error']}"
                    writer.writerow([wallet, r['balance'], token_symbol.upper(), network_name, status])
                else:
                    writer.writerow([wallet, 0, token_symbol.upper(), network_name, 'ERROR: Not processed'])
    
    console.print(f"[green]💾 Результаты сохранены в result/result.csv[/green]")


def print_summary(results: dict, token_symbol: str):
    success_list = [r for r in results.values() if r['success']]
    failed_list = [r for r in results.values() if not r['success']]
    total_balance = sum(r['balance'] for r in success_list)
    
    console.print("\n" + "="*60)
    console.print(f"[bold cyan]📊 ИТОГИ ПРОВЕРКИ ТОКЕНА {token_symbol.upper()}[/bold cyan]")
    console.print("="*60)
    console.print(f"[green]✅ Успешно: {len(success_list)}[/green]")
    console.print(f"[red]❌ Ошибки: {len(failed_list)}[/red]")
    console.print(f"[yellow]💰 Общий баланс: {total_balance:.6f} {token_symbol.upper()}[/yellow]")
    console.print("="*60)
    
    with_balance = sorted([r for r in success_list if r['balance'] > 0], key=lambda x: x['balance'], reverse=True)
    if with_balance:
        console.print(f"\n[bold cyan]🏆 Топ кошельков с балансом {token_symbol.upper()}:[/bold cyan]")
        for i, r in enumerate(with_balance[:10], 1):
            console.print(f"  {i}. {r['wallet'][:10]}...{r['wallet'][-6:]} → [green]{r['balance']:.6f} {token_symbol.upper()}[/green]")


def check_token_balance_menu():
    wallets = load_wallets()
    if not wallets:
        console.print("[red]❌ Нет кошельков в data/walletss.txt![/red]")
        return
    
    console.print(f"[cyan]📋 Загружено {len(wallets)} кошельков[/cyan]")
    
    network_type = select(
        "\n╔════════════════════════════════════════════════╗\n"
        "║      Выбор типа сети / Network Type            ║\n"
        "╚════════════════════════════════════════════════╝",
        choices=[
            Choice('   🌐 Mainnet Networks', 'mainnet'),
            Choice('   🔧 Testnet Networks', 'testnet'),
            Choice('   🔙 Назад / Back', 'back')
        ],
        qmark='🛠️ ',
        pointer='👉'
    ).ask()
    
    if network_type == 'back' or not network_type:
        return
    
    networks = {k: v for k, v in NETWORKS.items() if v['type'] == network_type}
    
    network_choices = [Choice(name, name) for name in networks.keys()] + [Choice('🔙 Назад', 'back')]
    selected_network = select("Выберите сеть:", choices=network_choices, qmark='🛠️', pointer='👉').ask()
    
    if selected_network == 'back' or not selected_network:
        return
    
    network_data = networks[selected_network]
    rpc_urls = network_data['rpc_urls']
    
    available_tokens = get_tokens_for_network(selected_network)
    
    if not available_tokens:
        console.print(f"[yellow]⚠️ Для сети {selected_network} нет настроенных токенов в config/token_address_erc20.py[/yellow]")
        return
    
    token_choices = [
        Choice(f'   🪙 {symbol.upper()} ({address[:10]}...)', symbol) 
        for symbol, address in available_tokens.items()
    ] + [Choice('   🔙 Назад', 'back')]
    
    selected_token = select(
        f"Выберите токен для сети {selected_network}:",
        choices=token_choices,
        qmark='🛠️',
        pointer='👉'
    ).ask()
    
    if selected_token == 'back' or not selected_token:
        return
    
    token_address = available_tokens[selected_token]
    
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
    
    console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
    console.print(f"[bold cyan]🌐 Сеть: {selected_network}[/bold cyan]")
    console.print(f"[bold cyan]🪙 Токен: {selected_token.upper()} ({token_address})[/bold cyan]")
    console.print(f"[bold cyan]{'='*60}[/bold cyan]")
    
    task_type = f'token_{selected_token}'
    
    init_database()
    
    if action == 'reset':
        reset_database_for_new_run(task_type, selected_network)
        create_balance_tasks(wallets, task_type, selected_network)
    
    pending = get_pending_tasks(task_type, selected_network)
    if not pending:
        create_balance_tasks(wallets, task_type, selected_network)
        pending = get_pending_tasks(task_type, selected_network)
    
    if not pending:
        console.print(f"[yellow]⚠️ Все задачи уже выполнены для {selected_token.upper()}[/yellow]")
        return
    
    wallets_to_check = [t['wallet_address'] for t in pending]
    console.print(f"[cyan]📋 Задач: {len(wallets_to_check)}[/cyan]")
    
    results = process_wallets_tokens(wallets_to_check, token_address, rpc_urls, 
                                     selected_network, selected_token)
    
    save_results(results, wallets, selected_network, selected_token)
    print_summary(results, selected_token)
    
    console.print("\n[bold green]✅ Проверка токенов завершена![/bold green]\n")
    
    try:
        from modules.notifications import send_telegram_notification
        results_list = list(results.values())
        send_telegram_notification(
            notif_type="success",
            title=f"Проверка баланса {selected_token.upper()} завершена",
            message=f"Сеть: {selected_network}\nВсего: {len(results_list)}\nУспешно: {len([r for r in results_list if r['success']])}",
            main_title="ETHmachine Token Balance Check"
        )
    except:
        pass


if __name__ == "__main__":
    check_token_balance_menu()
