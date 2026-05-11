"""
DeBank Balance Checker
Проверка всех балансов токенов через DeBank (debank.com)
Использует Playwright для обхода anti-bot защиты DeBank API
Асинхронная обработка с прокси-ротацией и Rich UI
"""

import csv
import sys
import asyncio
import time
import random
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.console import Group
from questionary import Choice, select

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.modules.general_config import (
    NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS, DELAY_BETWEEN_ACCOUNTS
)
from modules.debank.database import (
    init_database, create_tasks, get_pending_tasks,
    update_task_status, save_token_balances_batch, delete_wallet_balances,
    get_all_balances, reset_database, get_task_statistics
)

console = Console()

# Максимум параллельных браузерных контекстов
MAX_CONCURRENT = NUM_THREADS


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


def load_private_keys_as_wallets() -> list:
    """Загрузить приватные ключи из data/private_keys.txt и конвертировать в адреса"""
    from eth_account import Account

    pk_file = project_root / 'data' / 'private_keys.txt'
    wallets = []
    try:
        with open(pk_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if not line.startswith('0x'):
                    line = '0x' + line
                try:
                    account = Account.from_key(line)
                    wallets.append(account.address)
                except Exception:
                    console.print(f"[yellow]⚠️ Невалидный ключ: {line[:8]}...{line[-4:]}[/yellow]")
    except FileNotFoundError:
        console.print("[red]❌ Файл data/private_keys.txt не найден[/red]")
    except Exception as e:
        console.print(f"[red]Ошибка загрузки приватных ключей: {e}[/red]")
    return wallets


def load_proxies() -> list:
    proxy_file = project_root / 'data' / 'proxy.csv'
    proxies = []
    try:
        with open(proxy_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and '@' in line and ':' in line:
                    if not line.lower().startswith('proxy') and not line.lower().startswith('login'):
                        proxies.append(line)
    except Exception:
        pass
    return proxies


def parse_proxy_for_playwright(proxy_str: str) -> dict:
    """Конвертировать строку прокси в формат Playwright"""
    if not proxy_str:
        return None
    try:
        auth, addr = proxy_str.split('@')
        login, password = auth.split(':', 1)
        ip, port = addr.split(':', 1)
        return {
            'server': f'http://{ip}:{port}',
            'username': login,
            'password': password,
        }
    except Exception:
        return None


def parse_token_data(data) -> list:
    """Парсинг данных токенов из API ответа DeBank"""
    tokens = []

    if isinstance(data, dict) and 'data' in data:
        token_list = data['data']
    elif isinstance(data, list):
        token_list = data
    else:
        return tokens

    if not isinstance(token_list, list):
        return tokens

    for token in token_list:
        if not isinstance(token, dict):
            continue
        amount = token.get('amount', 0)
        if amount and float(amount) > 0:
            price = token.get('price', 0) or 0
            value_usd = float(amount) * float(price)
            tokens.append({
                'chain': token.get('chain', ''),
                'symbol': token.get('symbol', token.get('optimized_symbol', 'UNKNOWN')),
                'name': token.get('name', ''),
                'address': token.get('id', token.get('contract_id', '')),
                'balance': float(amount),
                'price_usd': float(price),
                'value_usd': value_usd,
                'logo_url': token.get('logo_url', ''),
            })
    return tokens


async def check_wallet_playwright(wallet: str, proxy_config: dict, semaphore: asyncio.Semaphore,
                                  playwright_instance) -> dict:
    """Проверка одного кошелька через Playwright browser"""
    async with semaphore:
        for attempt in range(RETRY_COUNT + 1):
            try:
                launch_args = {'headless': True}
                if proxy_config:
                    launch_args['proxy'] = proxy_config

                browser = await playwright_instance.chromium.launch(**launch_args)
                try:
                    page = await browser.new_page()

                    # Перехват API ответа cache_balance_list
                    balance_data = {}

                    async def handle_response(response):
                        url = response.url
                        if 'api.debank.com' in url and 'cache_balance_list' in url:
                            try:
                                body = await response.json()
                                balance_data['tokens'] = body
                            except Exception:
                                pass

                    page.on('response', handle_response)

                    # Навигация на профиль кошелька
                    await page.goto(
                        f'https://debank.com/profile/{wallet}',
                        wait_until='networkidle',
                        timeout=30000
                    )

                    # Ждём загрузки данных
                    await asyncio.sleep(random.uniform(2, 4))

                    if 'tokens' in balance_data:
                        tokens = parse_token_data(balance_data['tokens'])
                        total_usd = sum(t['value_usd'] for t in tokens)
                        return {
                            'wallet': wallet,
                            'tokens': tokens,
                            'success': True,
                            'total_usd': total_usd,
                            'error': None,
                        }

                    if attempt < RETRY_COUNT:
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                        continue

                    return {
                        'wallet': wallet,
                        'tokens': [],
                        'success': False,
                        'error': 'No balance data received',
                    }

                finally:
                    await browser.close()

            except Exception as e:
                if attempt < RETRY_COUNT:
                    await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                    continue
                return {
                    'wallet': wallet,
                    'tokens': [],
                    'success': False,
                    'error': str(e)[:80],
                }

    return {'wallet': wallet, 'tokens': [], 'success': False, 'error': 'Max retries exceeded'}


def create_panel(total: int, success: int, failed: int, logs: list) -> Panel:
    """Панель прогресса в стиле проекта"""
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
        "⚡ Параллельно:", Text(str(MAX_CONCURRENT), style="bold cyan")
    )

    header = Text()
    header.append("\n🏦 ", style="bold")
    header.append("DeBank Balance Checker\n", style="bold cyan")

    progress_bar = Text()
    progress_bar.append(bar_filled, style=f"bold {bar_style}")
    progress_bar.append(bar_empty, style="dim")
    progress_bar.append(f" {percent:.1f}%\n", style=f"bold {bar_style}")

    processed_text = Text()
    processed_text.append("Обработано: ", style="dim")
    processed_text.append(f"{processed}/{total}\n\n", style="bold")

    logs_section = Text()
    logs_section.append("📝 Последние события:\n", style="bold")
    for ts, msg, lvl in logs[-8:]:
        logs_section.append(f"  {ts} ", style="dim")
        style = {"SUCCESS": "green", "ERROR": "red", "WARNING": "yellow", "INFO": "cyan"}.get(lvl, "white")
        logs_section.append(f"{msg}\n", style=style)
    if not logs:
        logs_section.append("  Ожидание...\n", style="dim")

    content = Group(header, progress_bar, processed_text, table, Text(""), logs_section)

    return Panel(
        content,
        title="[bold bright_blue]🏦 DEBANK BALANCE CHECKER[/bold bright_blue]",
        subtitle="[dim]ETHmachine[/dim]",
        border_style="bright_blue",
        padding=(1, 2)
    )


async def process_wallets_async(wallets: list) -> dict:
    """Асинхронная обработка кошельков через Playwright"""
    from playwright.async_api import async_playwright

    results = {}
    total = len(wallets)
    success = 0
    failed = 0
    logs = []

    proxies = load_proxies()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    if not proxies:
        console.print("[yellow]⚠️ Прокси не найдены, запросы пойдут напрямую[/yellow]")

    delay_min, delay_max = DELAY_BETWEEN_ACCOUNTS
    logs.append((time.strftime("%H:%M:%S"), f"Запуск {total} кошельков ({MAX_CONCURRENT} параллельно, задержка {delay_min}-{delay_max}с)", "INFO"))
    if proxies:
        logs.append((time.strftime("%H:%M:%S"), f"Загружено {len(proxies)} прокси (round-robin)", "INFO"))

    live = Live(create_panel(total, 0, 0, logs), console=console, refresh_per_second=2)
    live.start()

    try:
        async with async_playwright() as p:

            async def process_wallet(idx, wallet):
                """Обработка одного кошелька с обновлением UI"""
                nonlocal success, failed
                proxy_str = proxies[idx % len(proxies)] if proxies else None
                proxy_config = parse_proxy_for_playwright(proxy_str)

                short = f"{wallet[:6]}...{wallet[-4:]}"
                try:
                    result = await check_wallet_playwright(wallet, proxy_config, semaphore, p)
                    results[wallet] = result

                    if result['success']:
                        success += 1
                        delete_wallet_balances(wallet)
                        if result['tokens']:
                            batch = [
                                (wallet, t['chain'], t['symbol'], t['name'],
                                 t['address'], t['balance'], t['price_usd'],
                                 t['value_usd'], t['logo_url'])
                                for t in result['tokens']
                            ]
                            save_token_balances_batch(batch)

                        update_task_status(wallet, 'completed')
                        token_count = len(result['tokens'])
                        total_usd = result.get('total_usd', 0)
                        logs.append((
                            time.strftime("%H:%M:%S"),
                            f"[{short}] ✅ {token_count} токенов | ${total_usd:.2f}",
                            "SUCCESS"
                        ))
                    else:
                        failed += 1
                        update_task_status(wallet, 'failed', result.get('error', 'Unknown'))
                        logs.append((
                            time.strftime("%H:%M:%S"),
                            f"[{short}] ❌ {result.get('error', 'Unknown')[:40]}",
                            "ERROR"
                        ))
                except Exception as e:
                    failed += 1
                    results[wallet] = {'wallet': wallet, 'tokens': [], 'success': False, 'error': str(e)[:50]}
                    update_task_status(wallet, 'failed', str(e)[:100])
                    logs.append((time.strftime("%H:%M:%S"), f"[{short}] ❌ {str(e)[:30]}", "ERROR"))

                live.update(create_panel(total, success, failed, logs))

            # Запуск задач с задержкой DELAY_BETWEEN_ACCOUNTS между стартами
            tasks = []
            for idx, wallet in enumerate(wallets):
                task = asyncio.create_task(process_wallet(idx, wallet))
                tasks.append(task)
                if idx < len(wallets) - 1:
                    await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS))

            # Дождаться завершения всех задач
            await asyncio.gather(*tasks, return_exceptions=True)

    finally:
        live.stop()

    return results


def process_wallets(wallets: list) -> dict:
    """Обёртка для запуска асинхронной обработки"""
    return asyncio.run(process_wallets_async(wallets))


def save_results_csv(wallets: list):
    """Экспорт балансов: одна строка = один кошелёк, токены как колонки.
    Формат колонки: chain:symbol (например eth:ETH, arb:USDC).
    Если у кошелька нет токена — пишется 0.
    """
    result_dir = project_root / 'result'
    result_dir.mkdir(exist_ok=True)

    all_balances = get_all_balances()
    if not all_balances:
        console.print("[yellow]⚠️ Нет данных для экспорта[/yellow]")
        return None

    # Собрать все уникальные токены (chain:symbol) в порядке появления
    token_columns = []
    token_columns_set = set()
    # wallet -> {token_key: balance}
    wallet_data = {}

    for b in all_balances:
        w = b['wallet_address']
        token_key = f"{b['chain']}:{b['token_symbol']}"

        if token_key not in token_columns_set:
            token_columns_set.add(token_key)
            token_columns.append(token_key)

        if w not in wallet_data:
            wallet_data[w] = {}
        wallet_data[w][token_key] = b['balance']

    # Вычислить total_usd для каждого кошелька
    wallet_totals = {}
    for b in all_balances:
        w = b['wallet_address']
        wallet_totals[w] = wallet_totals.get(w, 0) + b['value_usd']

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = result_dir / f"debank_balances_{timestamp}.csv"

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # Заголовок: wallet, total_usd, chain:symbol, chain:symbol, ...
        writer.writerow(['wallet', 'total_usd'] + token_columns)

        # Пишем в порядке wallets (из файла), потом остальные из БД
        written = set()
        for wallet in wallets:
            if wallet in wallet_data:
                row = [wallet, f"{wallet_totals.get(wallet, 0):.2f}"]
                for tk in token_columns:
                    row.append(wallet_data[wallet].get(tk, 0))
                writer.writerow(row)
                written.add(wallet)
        # Кошельки из БД, которых нет в wallets (на всякий случай)
        for wallet in wallet_data:
            if wallet not in written:
                row = [wallet, f"{wallet_totals.get(wallet, 0):.2f}"]
                for tk in token_columns:
                    row.append(wallet_data[wallet].get(tk, 0))
                writer.writerow(row)

    console.print(f"[green]💾 Результаты сохранены: {filepath}[/green]")
    return filepath


def print_summary(results: dict):
    """Вывод итогов проверки"""
    success_list = [r for r in results.values() if r['success']]
    failed_list = [r for r in results.values() if not r['success']]

    total_tokens = sum(len(r['tokens']) for r in success_list)
    total_usd = sum(r.get('total_usd', 0) for r in success_list)

    console.print("\n" + "=" * 60)
    console.print("[bold cyan]📊 ИТОГИ ПРОВЕРКИ DEBANK[/bold cyan]")
    console.print("=" * 60)
    console.print(f"[green]✅ Успешно: {len(success_list)}[/green]")
    console.print(f"[red]❌ Ошибки: {len(failed_list)}[/red]")
    console.print(f"[yellow]💰 Общая стоимость: ${total_usd:,.2f}[/yellow]")
    console.print("=" * 60)

    wallets_with_value = sorted(
        [r for r in success_list if r.get('total_usd', 0) > 0],
        key=lambda x: x.get('total_usd', 0),
        reverse=True
    )
    if wallets_with_value:
        console.print("\n[bold cyan]🏆 Топ кошельков по стоимости:[/bold cyan]")
        for i, r in enumerate(wallets_with_value[:10], 1):
            w = r['wallet']
            console.print(
                f"  {i}. {w[:10]}...{w[-6:]} → "
                f"[green]${r['total_usd']:,.2f}[/green] "
                f"({len(r['tokens'])} токенов)"
            )


def debank_checker_menu():
    """Главное меню DeBank Checker"""
    # Выбор источника кошельков
    wallet_source = select(
        "\n╔════════════════════════════════════════════════╗\n"
        "║      Источник кошельков                        ║\n"
        "╚════════════════════════════════════════════════╝",
        choices=[
            Choice('   📋 Адреса кошельков (data/walletss.txt)', 'wallets'),
            Choice('   🔑 Приватные ключи (data/private_keys.txt)', 'private_keys'),
            Choice('   🔙 Назад', 'back')
        ],
        qmark='🛠️ ',
        pointer='👉'
    ).ask()

    if wallet_source == 'back' or not wallet_source:
        return

    if wallet_source == 'private_keys':
        wallets = load_private_keys_as_wallets()
        if not wallets:
            console.print("[red]❌ Нет валидных ключей в data/private_keys.txt[/red]")
            return
        console.print(f"[cyan]🔑 Конвертировано {len(wallets)} приватных ключей в адреса[/cyan]")
    else:
        wallets = load_wallets()
        if not wallets:
            console.print("[red]❌ Нет кошельков в data/walletss.txt[/red]")
            return
        console.print(f"[cyan]📋 Загружено {len(wallets)} кошельков[/cyan]")

    init_database()

    stats = get_task_statistics()
    completed = stats.get('completed', 0)
    pending = stats.get('pending', 0)
    failed_count = stats.get('failed', 0)

    if completed > 0 or pending > 0 or failed_count > 0:
        console.print(f"[dim]БД: ✅ {completed} | ⏳ {pending} | ❌ {failed_count}[/dim]")

    action = select(
        "\n╔════════════════════════════════════════════════╗\n"
        "║      DeBank Balance Checker                    ║\n"
        "╚════════════════════════════════════════════════╝",
        choices=[
            Choice('   ▶️  Продолжить незавершённые задачи', 'continue'),
            Choice('   🔄 Начать заново (сброс БД)', 'reset'),
            Choice('   📊 Экспорт результатов в CSV', 'export'),
            Choice('   🔙 Назад', 'back')
        ],
        qmark='🛠️ ',
        pointer='👉'
    ).ask()

    if action == 'back' or not action:
        return

    if action == 'export':
        save_results_csv(wallets)
        return

    if action == 'reset':
        reset_database()
        console.print("[yellow]🔄 База данных сброшена[/yellow]")
        create_tasks(wallets)
    else:
        create_tasks(wallets)

    pending_tasks = get_pending_tasks()
    if not pending_tasks:
        console.print("[yellow]⚠️ Все задачи уже выполнены. Используйте 'Начать заново' для повторной проверки.[/yellow]")
        save_results_csv(wallets)
        return

    wallets_to_check = [t['wallet_address'] for t in pending_tasks]
    console.print(f"[cyan]📋 Задач к выполнению: {len(wallets_to_check)}[/cyan]")

    # Обработка
    results = process_wallets(wallets_to_check)

    # Итоги
    print_summary(results)

    # Экспорт в CSV
    save_results_csv(wallets)

    console.print("\n[bold green]✅ Проверка DeBank завершена![/bold green]\n")

    # Telegram
    try:
        results_list = list(results.values())
        success_count = len([r for r in results_list if r['success']])
        total_usd = sum(r.get('total_usd', 0) for r in results_list if r['success'])
    except Exception:
        pass


if __name__ == "__main__":
    debank_checker_menu()
