"""
DeBank Protocol Checker
Проверка DeFi-позиций (стейкинг, лендинг, locked, LP и т.д.) через DeBank
Использует Playwright для перехвата portfolio/project_list API
"""

import csv
import sys
import json
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

from config.modules.cfg_base import (
    NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS, DELAY_BETWEEN_ACCOUNTS
)
from modules.debank.database import (
    init_database, create_protocol_tasks, get_pending_protocol_tasks,
    update_protocol_task_status, save_protocol_positions_batch,
    delete_wallet_protocols, get_all_protocols, reset_protocols_database,
    get_protocol_task_statistics
)
from modules.debank.debank_checker import (
    load_wallets, load_private_keys_as_wallets, load_proxies, parse_proxy_for_playwright
)

console = Console()
MAX_CONCURRENT = NUM_THREADS


def parse_protocol_data(data) -> list:
    """Парсинг DeFi-позиций из API ответа portfolio/project_list"""
    positions = []

    if isinstance(data, dict) and 'data' in data:
        protocol_list = data['data']
    elif isinstance(data, list):
        protocol_list = data
    else:
        return positions

    if not isinstance(protocol_list, list):
        return positions

    for protocol in protocol_list:
        if not isinstance(protocol, dict):
            continue

        protocol_name = protocol.get('name', 'Unknown')
        protocol_id = protocol.get('id', protocol.get('dao_id', ''))
        chain = protocol.get('chain', '')

        portfolio_items = protocol.get('portfolio_item_list', [])
        if not isinstance(portfolio_items, list):
            continue

        for item in portfolio_items:
            if not isinstance(item, dict):
                continue

            position_type = item.get('name', 'Unknown')
            stats = item.get('stats', {}) or {}
            detail = item.get('detail', {}) or {}
            net_usd = stats.get('net_usd_value', 0) or 0
            asset_usd = stats.get('asset_usd_value', 0) or 0

            # Description (veSONUS#373014, UB-WETH и т.д.)
            description = detail.get('description', '') or ''

            # Unlock time (для locked позиций)
            unlock_time = ''
            if 'unlock_at' in detail:
                try:
                    ts = detail['unlock_at']
                    if ts:
                        unlock_time = datetime.fromtimestamp(ts).strftime('%Y/%m/%d %H:%M')
                except Exception:
                    pass
            elif 'end_at' in detail:
                try:
                    ts = detail['end_at']
                    if ts:
                        unlock_time = datetime.fromtimestamp(ts).strftime('%Y/%m/%d %H:%M')
                except Exception:
                    pass

            # Health rate (для lending)
            health_rate = ''
            if 'health_rate' in detail:
                hr = detail['health_rate']
                if hr is not None:
                    # Очень большие значения (>1e10) показываем как ">10"
                    if isinstance(hr, (int, float)) and hr > 1e10:
                        health_rate = '>10'
                    elif isinstance(hr, (int, float)) and hr > 0:
                        health_rate = f">{hr:.2f}"
                    else:
                        health_rate = str(hr)

            # Supply tokens
            supply_tokens = detail.get('supply_token_list', []) or []
            # Reward tokens
            reward_tokens = detail.get('reward_token_list', []) or []
            # Borrow tokens (для lending)
            borrow_tokens = detail.get('borrow_token_list', []) or []

            # Собираем позиции из supply_token_list
            for token in supply_tokens:
                if not isinstance(token, dict):
                    continue
                amount = token.get('amount', 0)
                if not amount or float(amount) <= 0:
                    continue

                symbol = token.get('symbol', token.get('optimized_symbol', 'UNKNOWN'))
                price = token.get('price', 0) or 0
                value_usd = float(amount) * float(price)

                # Адаптивное форматирование: больше знаков для малых сумм
                amt = float(amount)
                if amt >= 1:
                    balance_token = f"{amt:.4f} {symbol}"
                elif amt >= 0.0001:
                    balance_token = f"{amt:.8f} {symbol}"
                else:
                    balance_token = f"{amt:.12f} {symbol}"

                # Pool name: description если есть (veSONUS#373014), иначе symbol
                pool_name = description if description else symbol

                # Extra data: rewards, debt
                extra = {}
                if reward_tokens:
                    extra['rewards'] = [
                        {'symbol': r.get('symbol', ''), 'amount': r.get('amount', 0),
                         'value_usd': (r.get('amount', 0) or 0) * (r.get('price', 0) or 0)}
                        for r in reward_tokens if isinstance(r, dict) and (r.get('amount', 0) or 0) > 0
                    ]
                if borrow_tokens:
                    extra['borrows'] = [
                        {'symbol': r.get('symbol', ''), 'amount': r.get('amount', 0),
                         'value_usd': (r.get('amount', 0) or 0) * (r.get('price', 0) or 0)}
                        for r in borrow_tokens if isinstance(r, dict) and (r.get('amount', 0) or 0) > 0
                    ]

                positions.append({
                    'protocol_name': protocol_name,
                    'protocol_id': protocol_id,
                    'chain': chain,
                    'position_type': position_type,
                    'pool_name': pool_name,
                    'balance': float(amount),
                    'balance_token': balance_token,
                    'value_usd': value_usd,
                    'unlock_time': unlock_time,
                    'health_rate': health_rate,
                    'extra_data': json.dumps(extra, ensure_ascii=False) if extra else '',
                })

    return positions


async def check_wallet_protocols(wallet: str, proxy_config: dict, semaphore: asyncio.Semaphore,
                                 playwright_instance) -> dict:
    """Проверка DeFi-позиций одного кошелька через Playwright"""
    async with semaphore:
        for attempt in range(RETRY_COUNT + 1):
            try:
                launch_args = {'headless': True}
                if proxy_config:
                    launch_args['proxy'] = proxy_config

                browser = await playwright_instance.chromium.launch(**launch_args)
                try:
                    page = await browser.new_page()

                    # Перехват API ответа portfolio/project_list
                    protocol_data = {}

                    async def handle_response(response):
                        url = response.url
                        if 'api.debank.com' in url and 'portfolio/project_list' in url:
                            try:
                                body = await response.json()
                                protocol_data['protocols'] = body
                            except Exception:
                                pass

                    page.on('response', handle_response)

                    await page.goto(
                        f'https://debank.com/profile/{wallet}',
                        wait_until='networkidle',
                        timeout=30000
                    )

                    # Ждём загрузки данных (протоколы грузятся чуть дольше балансов)
                    await asyncio.sleep(random.uniform(3, 6))

                    if 'protocols' in protocol_data:
                        positions = parse_protocol_data(protocol_data['protocols'])
                        total_usd = sum(p['value_usd'] for p in positions)
                        return {
                            'wallet': wallet,
                            'positions': positions,
                            'success': True,
                            'total_usd': total_usd,
                            'error': None,
                        }

                    if attempt < RETRY_COUNT:
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                        continue

                    return {
                        'wallet': wallet,
                        'positions': [],
                        'success': True,
                        'total_usd': 0,
                        'error': None,
                    }

                finally:
                    await browser.close()

            except Exception as e:
                if attempt < RETRY_COUNT:
                    await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                    continue
                return {
                    'wallet': wallet,
                    'positions': [],
                    'success': False,
                    'error': str(e)[:80],
                }

    return {'wallet': wallet, 'positions': [], 'success': False, 'error': 'Max retries exceeded'}


def create_protocol_panel(total: int, success: int, failed: int, logs: list) -> Panel:
    """Панель прогресса для Protocol Checker"""
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
    header.append("\n🔗 ", style="bold")
    header.append("DeBank Protocol Checker\n", style="bold magenta")

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
        title="[bold bright_magenta]🔗 DEBANK PROTOCOL CHECKER[/bold bright_magenta]",
        subtitle="[dim]ETHmachine[/dim]",
        border_style="bright_magenta",
        padding=(1, 2)
    )


async def process_wallets_protocols_async(wallets: list) -> dict:
    """Асинхронная обработка кошельков — сбор DeFi-позиций"""
    from playwright.async_api import async_playwright

    results = {}
    total = len(wallets)
    success = 0
    failed = 0
    logs = []

    proxies = load_proxies()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    if not proxies:
        console.print("[yellow][!] Прокси не найдены, запросы пойдут напрямую[/yellow]")

    delay_min, delay_max = DELAY_BETWEEN_ACCOUNTS
    logs.append((time.strftime("%H:%M:%S"), f"Запуск {total} кошельков ({MAX_CONCURRENT} параллельно)", "INFO"))
    if proxies:
        logs.append((time.strftime("%H:%M:%S"), f"Загружено {len(proxies)} прокси (round-robin)", "INFO"))

    live = Live(create_protocol_panel(total, 0, 0, logs), console=console, refresh_per_second=2)
    live.start()

    try:
        async with async_playwright() as p:

            async def process_wallet(idx, wallet):
                nonlocal success, failed
                proxy_str = proxies[idx % len(proxies)] if proxies else None
                proxy_config = parse_proxy_for_playwright(proxy_str)

                short = f"{wallet[:6]}...{wallet[-4:]}"
                try:
                    result = await check_wallet_protocols(wallet, proxy_config, semaphore, p)
                    results[wallet] = result

                    if result['success']:
                        success += 1
                        delete_wallet_protocols(wallet)
                        if result['positions']:
                            batch = [
                                (wallet, pos['protocol_name'], pos['protocol_id'], pos['chain'],
                                 pos['position_type'], pos['pool_name'], pos['balance'],
                                 pos['balance_token'], pos['value_usd'], pos['unlock_time'],
                                 pos['health_rate'], pos['extra_data'])
                                for pos in result['positions']
                            ]
                            save_protocol_positions_batch(batch)

                        update_protocol_task_status(wallet, 'completed')
                        pos_count = len(result['positions'])
                        total_usd = result.get('total_usd', 0)
                        logs.append((
                            time.strftime("%H:%M:%S"),
                            f"[{short}] ✅ {pos_count} позиций | ${total_usd:.2f}",
                            "SUCCESS"
                        ))
                    else:
                        failed += 1
                        update_protocol_task_status(wallet, 'failed', result.get('error', 'Unknown'))
                        logs.append((
                            time.strftime("%H:%M:%S"),
                            f"[{short}] ❌ {result.get('error', 'Unknown')[:40]}",
                            "ERROR"
                        ))
                except Exception as e:
                    failed += 1
                    results[wallet] = {'wallet': wallet, 'positions': [], 'success': False, 'error': str(e)[:50]}
                    update_protocol_task_status(wallet, 'failed', str(e)[:100])
                    logs.append((time.strftime("%H:%M:%S"), f"[{short}] ❌ {str(e)[:30]}", "ERROR"))

                live.update(create_protocol_panel(total, success, failed, logs))

            tasks = []
            for idx, wallet in enumerate(wallets):
                task = asyncio.create_task(process_wallet(idx, wallet))
                tasks.append(task)
                if idx < len(wallets) - 1:
                    await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS))

            await asyncio.gather(*tasks, return_exceptions=True)

    finally:
        live.stop()

    return results


def process_wallets_protocols(wallets: list) -> dict:
    """Обёртка для запуска асинхронной обработки"""
    return asyncio.run(process_wallets_protocols_async(wallets))


def _fmt_balance(val: float) -> str:
    """Форматирование баланса без научной нотации"""
    if val == 0:
        return '0'
    if val >= 1:
        return f"{val:.4f}"
    elif val >= 0.0001:
        return f"{val:.8f}"
    else:
        return f"{val:.12f}"


def _fmt_usd(val: float) -> str:
    """Форматирование USD с адаптивной точностью"""
    if val == 0:
        return '0.00'
    if val >= 0.01:
        return f"{val:.2f}"
    elif val >= 0.0001:
        return f"{val:.6f}"
    else:
        return f"{val:.10f}"


def _format_cell(p: dict) -> str:
    """Форматирование ячейки позиции — вся ключевая инфа в одной строке"""
    parts = []
    parts.append(p['balance_token'])
    parts.append(f"${_fmt_usd(p['value_usd'])}")

    if p.get('unlock_time'):
        parts.append(f"unlock:{p['unlock_time']}")
    if p.get('health_rate'):
        parts.append(f"health:{p['health_rate']}")

    extra = p.get('extra_data')
    if extra:
        try:
            data = json.loads(extra) if isinstance(extra, str) else extra
            if isinstance(data, dict):
                for key in ('rewards', 'borrows'):
                    items = data.get(key, [])
                    for item in items:
                        sym = item.get('symbol', '?')
                        amt = item.get('amount', 0)
                        val = item.get('value_usd', 0)
                        parts.append(f"{key[:-1]}:{_fmt_balance(amt)} {sym} (${_fmt_usd(val)})")
        except (json.JSONDecodeError, TypeError):
            pass

    return ' | '.join(parts)


def _make_column_key(p: dict) -> str:
    """Создаёт уникальный ключ колонки из позиции"""
    return f"{p['protocol_name']}|{p['chain']}|{p['position_type']}|{p['pool_name']}"


def _make_column_header(key: str) -> str:
    """Преобразует ключ в читаемый заголовок"""
    parts = key.split('|')
    return f"{parts[0]} [{parts[1]}] {parts[2]}: {parts[3]}"


def save_protocols_csv(wallets: list):
    """Экспорт DeFi-позиций в CSV (wide format: один кошелёк — одна строка)"""
    result_dir = project_root / 'result'
    result_dir.mkdir(exist_ok=True)

    all_protocols = get_all_protocols()
    if not all_protocols:
        console.print("[yellow][!] Нет данных о протоколах для экспорта[/yellow]")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = result_dir / f"debank_protocols_{timestamp}.csv"

    wallet_positions = {}
    all_columns = []
    seen_columns = set()

    for p in all_protocols:
        w = p['wallet_address']
        col_key = _make_column_key(p)

        if col_key not in seen_columns:
            seen_columns.add(col_key)
            all_columns.append(col_key)

        wallet_positions.setdefault(w, {})[col_key] = _format_cell(p)

    all_wallets = list(dict.fromkeys(
        [w for w in wallets if w in wallet_positions] +
        [w for w in wallet_positions if w not in wallets]
    ))

    headers = ['wallet'] + [_make_column_header(c) for c in all_columns]

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for wallet in all_wallets:
            positions = wallet_positions.get(wallet, {})
            row = [wallet]
            for col_key in all_columns:
                row.append(positions.get(col_key, '0'))
            writer.writerow(row)

    console.print(f"[green][v] Протоколы сохранены: {filepath}[/green]")
    return filepath


def print_protocol_summary(results: dict):
    """Вывод итогов проверки протоколов"""
    success_list = [r for r in results.values() if r['success']]
    failed_list = [r for r in results.values() if not r['success']]

    total_positions = sum(len(r['positions']) for r in success_list)
    total_usd = sum(r.get('total_usd', 0) for r in success_list)

    # Собираем уникальные протоколы
    protocols_found = set()
    for r in success_list:
        for pos in r['positions']:
            protocols_found.add(pos['protocol_name'])

    console.print("\n" + "=" * 60)
    console.print("[bold magenta]🔗 ИТОГИ ПРОВЕРКИ ПРОТОКОЛОВ[/bold magenta]")
    console.print("=" * 60)
    console.print(f"[green]✅ Успешно: {len(success_list)}[/green]")
    console.print(f"[red]❌ Ошибки: {len(failed_list)}[/red]")
    console.print(f"[cyan]🔗 Протоколов найдено: {len(protocols_found)}[/cyan]")
    console.print(f"[cyan]📋 Всего позиций: {total_positions}[/cyan]")
    console.print(f"[yellow]💰 Общая стоимость: ${total_usd:,.2f}[/yellow]")
    console.print("=" * 60)

    if protocols_found:
        console.print(f"\n[dim]Протоколы: {', '.join(sorted(protocols_found))}[/dim]")

    wallets_with_value = sorted(
        [r for r in success_list if r.get('total_usd', 0) > 0],
        key=lambda x: x.get('total_usd', 0),
        reverse=True
    )
    if wallets_with_value:
        console.print("\n[bold magenta]🏆 Топ кошельков по стоимости DeFi:[/bold magenta]")
        for i, r in enumerate(wallets_with_value[:10], 1):
            w = r['wallet']
            console.print(
                f"  {i}. {w[:10]}...{w[-6:]} → "
                f"[green]${r['total_usd']:,.2f}[/green] "
                f"({len(r['positions'])} позиций)"
            )


def debank_protocol_menu():
    """Главное меню DeBank Protocol Checker"""
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

    stats = get_protocol_task_statistics()
    completed = stats.get('completed', 0)
    pending = stats.get('pending', 0)
    failed_count = stats.get('failed', 0)

    if completed > 0 or pending > 0 or failed_count > 0:
        console.print(f"[dim]БД: ✅ {completed} | ⏳ {pending} | ❌ {failed_count}[/dim]")

    action = select(
        "\n╔════════════════════════════════════════════════╗\n"
        "║      DeBank Protocol Checker                   ║\n"
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
        save_protocols_csv(wallets)
        return

    if action == 'reset':
        reset_protocols_database()
        console.print("[yellow]🔄 База данных протоколов сброшена[/yellow]")
        create_protocol_tasks(wallets)
    else:
        create_protocol_tasks(wallets)

    pending_tasks = get_pending_protocol_tasks()
    if not pending_tasks:
        console.print("[yellow][!] Все задачи уже выполнены. Используйте 'Начать заново' для повторной проверки.[/yellow]")
        save_protocols_csv(wallets)
        return

    wallets_to_check = [t['wallet_address'] for t in pending_tasks]
    console.print(f"[cyan]📋 Задач к выполнению: {len(wallets_to_check)}[/cyan]")

    results = process_wallets_protocols(wallets_to_check)

    print_protocol_summary(results)

    save_protocols_csv(wallets)

    console.print("\n[bold green]✅ Проверка протоколов DeBank завершена![/bold green]\n")

    try:
        from modules.notifications import send_telegram_notification
        results_list = list(results.values())
        success_count = len([r for r in results_list if r['success']])
        total_usd = sum(r.get('total_usd', 0) for r in results_list if r['success'])
        send_telegram_notification(
            notif_type="success",
            title="DeBank Protocol проверка завершена",
            message=f"Всего: {len(results_list)}\nУспешно: {success_count}\nDeFi стоимость: ${total_usd:,.2f}",
            main_title="ETHmachine DeBank Protocol Checker"
        )
    except Exception:
        pass


if __name__ == "__main__":
    debank_protocol_menu()
