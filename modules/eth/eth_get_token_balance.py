import csv
import sys
import time
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from colorama import init

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
from config import token_address_erc20
from modules.ui import ui
from modules.ui.menu_model import BACK_KEY
from modules.eth.database import (
    init_database, create_balance_tasks, get_pending_tasks,
    update_task_status, reset_database_for_new_run, get_all_results
)
from modules.proxy_manager import get_proxy_dict, mask_proxy, parse_proxy
from modules.simple_logger import logger

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
    """Разбор прокси общим парсером из modules.proxy_manager.

    Локальная копия умела только `user:pass@host:port`: на обычном `host:port`
    распаковка падала в голый except и возвращала None — запрос молча уходил
    напрямую с реального IP пользователя.
    """
    return get_proxy_dict(proxy_str)


def get_tokens_for_network(network_name: str) -> dict:
    var_name = network_name.lower().replace(' ', '_').replace('-', '_')
    var_name = var_name.replace('🚀_', '').replace('🔧_', '')

    if hasattr(token_address_erc20, var_name):
        return getattr(token_address_erc20, var_name)

    aliases = {
        'ethereum': 'ethereum_mainnet',
        'arbitrum_one': 'arbitrum',
        'optimism_mainnet': 'optimism',
        'bsc': 'binance_smart_chain',
        'bnb': 'binance_smart_chain',
        'avax': 'avalanche',
    }

    alt_name = aliases.get(var_name)
    if alt_name and hasattr(token_address_erc20, alt_name):
        return getattr(token_address_erc20, alt_name)

    return {}


_DECIMALS_CACHE = {}

KNOWN_TOKEN_DECIMALS = {
    '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48': 6,
    '0xaf88d065e77c8cc2239327c5edb3a432268e5831': 6,
    '0xff970a61a04b1ca14834a43f5de4533ebddb5cc8': 6,
    '0x0b2c639c533813f4aa9d7837caf62653d097ff85': 6,
    '0x2791bca1f2de4661ed88a30c99a7a9449aa84174': 6,
    '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913': 6,
    '0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d': 18,
    '0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e': 6,
    '0x04068da6c83afcfa0e13ba15a6696662335d5b75': 6,
    '0xdac17f958d2ee523a2206206994597c13d831ec7': 6,
    '0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9': 6,
    '0x94b008aa00579c1307b0ef2c499ad98a8ce58e58': 6,
    '0xc2132d05d31c914a87c6611c10748aeb04b58e8f': 6,
    '0x55d398326f99059ff775485246999027b3197955': 18,
    '0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7': 6,
    '0x049d68029688eabf473097a2fc38ef61633a3c7a': 6,
    '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599': 8,
}


def _eth_call(rpc_url: str, token_address: str, data: str, proxy_dict: dict = None):
    """eth_call helper. Returns int on success, None on any error (RPC error, empty result, network failure)."""
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
            timeout=15,
            headers={'Content-Type': 'application/json'}
        )
        if resp.status_code != 200:
            return None
        try:
            result = resp.json()
        except ValueError:
            return None
        if not isinstance(result, dict):
            return None
        if 'error' in result:
            return None
        if 'result' not in result:
            return None
        hex_value = result['result']
        if not isinstance(hex_value, str) or not hex_value or hex_value == '0x':
            return None
        if hex_value.startswith('0x'):
            hex_value = hex_value[2:]
        if not hex_value:
            return None
        try:
            return int(hex_value, 16)
        except ValueError:
            return None
    except Exception:
        return None


def resolve_token_decimals(token_address: str, rpc_urls: list, proxies: list):
    """Возвращает (decimals: int, resolved: bool). resolved=False означает fallback на 18."""
    cache_key = token_address.lower()
    if cache_key in _DECIMALS_CACHE:
        cached = _DECIMALS_CACHE[cache_key]
        return cached, True

    attempts_per_rpc = 3
    for rpc_url in rpc_urls:
        for attempt in range(attempts_per_rpc):
            if proxies and attempt < attempts_per_rpc - 1:
                proxy_str = random.choice(proxies)
                proxy_dict = make_proxy_dict(proxy_str)
            else:
                proxy_dict = None
            value = _eth_call(rpc_url, token_address, "0x313ce567", proxy_dict)
            if value is not None and 0 <= value <= 30:
                _DECIMALS_CACHE[cache_key] = value
                return value, True

    known = KNOWN_TOKEN_DECIMALS.get(cache_key)
    if known is not None:
        _DECIMALS_CACHE[cache_key] = known
        return known, True

    return 18, False


def get_token_balance_rpc(wallet: str, token_address: str, rpc_url: str, decimals: int, proxy_dict: dict = None) -> float:
    data = f"0x70a08231000000000000000000000000{wallet[2:].lower()}"
    raw = _eth_call(rpc_url, token_address, data, proxy_dict)
    if raw is None:
        return -1
    return raw / 10 ** decimals


def check_wallet_token(wallet: str, token_address: str, rpc_urls: list, decimals: int, proxies: list, proxy_idx: int) -> dict:
    last_error = 'RPC failed'
    for rpc_url in rpc_urls:
        for attempt in range(2):
            if proxies:
                if attempt == 0:
                    proxy_str = proxies[proxy_idx % len(proxies)]
                else:
                    proxy_str = random.choice(proxies)
                proxy_dict = make_proxy_dict(proxy_str)
            else:
                proxy_dict = None
            balance = get_token_balance_rpc(wallet, token_address, rpc_url, decimals, proxy_dict)
            if balance >= 0:
                return {'wallet': wallet, 'balance': balance, 'success': True, 'error': None}

        balance = get_token_balance_rpc(wallet, token_address, rpc_url, decimals, None)
        if balance >= 0:
            return {'wallet': wallet, 'balance': balance, 'success': True, 'error': None}

    return {'wallet': wallet, 'balance': 0, 'success': False, 'error': last_error}


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

    # Нераспознанный прокси = запрос с реального IP. Молчать об этом нельзя:
    # пользователь узнает о проблеме только когда RPC его забанит.
    bad_proxies = [p for p in dict.fromkeys(proxies) if p and parse_proxy(p) is None]
    if bad_proxies:
        logger.warning(
            f"Не удалось разобрать {len(bad_proxies)} прокси "
            f"({', '.join(mask_proxy(p) for p in bad_proxies[:3])}) — эти запросы пойдут напрямую"
        )
        logs.append((
            time.strftime("%H:%M:%S"),
            f"⚠️ Не разобрано прокси: {len(bad_proxies)} — часть запросов пойдёт напрямую",
            "WARNING"
        ))

    decimals, resolved = resolve_token_decimals(token_address, rpc_urls, proxies)

    if resolved:
        logs.append((time.strftime("%H:%M:%S"), f"Запуск {total} кошельков в {max_workers} потоках (decimals={decimals})", "INFO"))
    else:
        logs.append((time.strftime("%H:%M:%S"), f"⚠️ Не удалось получить decimals токена через RPC, используется fallback={decimals}. Балансы могут быть некорректны!", "WARNING"))

    with Live(create_panel(network_name, token_symbol, total, 0, 0, logs), console=console, refresh_per_second=4) as live:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(check_wallet_token, wallet, token_address, rpc_urls, decimals, proxies, idx): wallet
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


def merge_with_db_results(results: dict, task_type: str, network_name: str) -> dict:
    """Дополняет результаты текущего прогона завершёнными задачами из БД.

    При «Продолжить незавершённые задачи» обрабатываются только pending-кошельки,
    поэтому без слияния отчёт объявлял все прошлые успехи «ERROR: Not processed»
    с нулевым балансом, хотя реальные данные лежат в db/eth_balance_tasks.db.
    """
    merged = {}
    try:
        rows = get_all_results(task_type, network_name)
    except Exception as e:
        logger.warning(f"Не удалось прочитать прошлые результаты из БД: {e}")
        rows = []

    for row in rows:
        if row.get('status') != 'completed':
            continue
        wallet = row.get('wallet_address')
        if not wallet:
            continue
        try:
            balance = float(row.get('balance') or 0)
        except (TypeError, ValueError):
            continue
        merged[wallet] = {'wallet': wallet, 'balance': balance, 'success': True, 'error': None}

    # Свежий результат всегда приоритетнее сохранённого
    merged.update(results)
    return merged


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
        console.print("[red]❌ Нет кошельков в data/data.csv![/red]")
        return

    console.print(f"[cyan]📋 Загружено {len(wallets)} кошельков[/cyan]")

    network_type = ui.choose("Какой тип сети?", [
        ("🌐 Mainnet", "mainnet"),
        ("🔧 Testnet", "testnet"),
    ])

    if network_type in (None, BACK_KEY):
        return

    networks = {k: v for k, v in NETWORKS.items() if v['type'] == network_type}

    selected_network = ui.choose("В какой сети считаем балансы?", [
        (get_network_display_name(name), name) for name in networks
    ])

    if selected_network in (None, BACK_KEY):
        return

    network_data = networks[selected_network]
    rpc_urls = network_data['rpc_urls']

    available_tokens = get_tokens_for_network(selected_network)

    if not available_tokens:
        console.print(f"[yellow]⚠️ Для сети {selected_network} нет настроенных токенов в config/token_address_erc20.py[/yellow]")
        return

    selected_token = ui.choose(f"Какой токен считаем в сети {selected_network}?", [
        (f"🪙 {symbol.upper()} ({address[:10]}…)", symbol)
        for symbol, address in available_tokens.items()
    ])

    if selected_token in (None, BACK_KEY):
        return

    token_address = available_tokens[selected_token]

    action = ui.choose("Действие с базой данных", [
        ("▶️ Продолжить незавершённые задачи", "continue"),
        ("🔄 Начать заново (сброс БД)", "reset"),
    ])

    if action in (None, BACK_KEY):
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

    # Отчёт строим по БД + текущему прогону, иначе resume затрёт прошлые успехи
    report = merge_with_db_results(results, task_type, selected_network)

    save_results(report, wallets, selected_network, selected_token)
    print_summary(report, selected_token)

    console.print("\n[bold green]✅ Проверка токенов завершена![/bold green]\n")

    try:
        results_list = list(results.values())
    except:
        pass


if __name__ == "__main__":
    check_token_balance_menu()
