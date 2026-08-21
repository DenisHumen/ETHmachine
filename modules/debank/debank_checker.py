"""DeBank Balance Checker — балансы всех токенов кошелька во всех сетях.

Данные снимаются через браузер (Playwright): открывается профиль кошелька
на debank.com и перехватывается ответ ``cache_balance_list`` — прямой вызов
API упирается в anti-bot защиту.

Здесь же живут общие для обоих DeBank-модулей части: загрузка кошельков и
прокси, выбор источника кошельков, панель хода проверки и панель прогресса
по задачам — ``debank_protocol_checker`` импортирует их отсюда.
"""

import csv
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

from config.modules.general_config import (
    NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS, DELAY_BETWEEN_ACCOUNTS
)
from modules.debank.database import (
    init_database, create_tasks, get_pending_tasks,
    update_task_status, save_token_balances_batch, delete_wallet_balances,
    get_all_balances, reset_database, get_task_statistics
)
from modules.simple_logger import logger
from modules.ui import ui
from modules.ui.menu_model import BACK_KEY, MenuItem, render_items

project_root = Path(__file__).parent.parent.parent

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
        logger.error(f"Не удалось прочитать data/walletss.txt: {e}")
    return wallets


def load_private_keys_as_wallets() -> list:
    """Адреса, выведенные из data/private_keys.txt.

    Ключи используются локально и наружу не уходят — DeBank видит только
    публичные адреса.
    """
    from eth_account import Account

    pk_file = project_root / 'data' / 'private_keys.txt'
    wallets = []
    try:
        with open(pk_file, 'r', encoding='utf-8') as f:
            for number, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if not line.startswith('0x'):
                    line = '0x' + line
                try:
                    account = Account.from_key(line)
                    wallets.append(account.address)
                except Exception:
                    # Сам ключ в лог не пишем — это секрет.
                    logger.warning(f"Строка {number}: не похоже на приватный ключ")
    except FileNotFoundError:
        logger.error("Файл data/private_keys.txt не найден")
    except Exception as e:
        logger.error(f"Не удалось прочитать data/private_keys.txt: {e}")
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


def progress_panel(icon: str, title: str, accent: str, total: int,
                   success: int, failed: int, logs: list) -> Panel:
    """Панель хода проверки для Live-вывода.

    Одна на оба DeBank-модуля: отличались только заголовок и цвет рамки.
    Живой прогресс рисует rich, а не UI-набор проекта: набор отдаёт
    статичные блоки, здесь же панель перерисовывается по ходу работы.
    """
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
    header.append(f"\n{icon} ", style="bold")
    header.append(f"{title}\n", style=f"bold {accent}")

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
        title=f"[bold {accent}]{icon} {title}[/bold {accent}]",
        subtitle="[dim]ETHmachine[/dim]",
        border_style=accent,
        padding=(1, 2)
    )


def balance_panel(total: int, success: int, failed: int, logs: list) -> Panel:
    return progress_panel("🏦", "DeBank · балансы токенов", "bright_blue",
                          total, success, failed, logs)


def choose_wallet_source() -> list | None:
    """Спрашивает, откуда брать кошельки, и возвращает список адресов.

    ``None`` — пользователь вышел или подходящих кошельков не нашлось.
    """
    source = ui.menu("Откуда берём кошельки?", render_items([
        MenuItem("wallets", "Адреса кошельков",
                 "data/walletss.txt — только публичные адреса", icon="📋"),
        MenuItem("private_keys", "Приватные ключи",
                 "data/private_keys.txt — в файле лежат секреты", icon="🔑"),
        MenuItem(BACK_KEY, "Назад", "", icon="←"),
    ]))
    if source in (None, BACK_KEY):
        return None

    if source == "private_keys":
        wallets = load_private_keys_as_wallets()
        if not wallets:
            logger.error("В data/private_keys.txt нет валидных ключей")
            return None
        logger.info(f"🔑 Из ключей получено адресов: {len(wallets)}")
        return wallets

    wallets = load_wallets()
    if not wallets:
        logger.error("В data/walletss.txt нет адресов")
        return None
    logger.info(f"📋 Загружено кошельков: {len(wallets)}")
    return wallets


def task_stats_panel(title: str, stats: dict) -> str | None:
    """Панель прогресса по задачам. ``None`` — в базе пока пусто."""
    labels = {"completed": "готово", "pending": "в очереди", "failed": "с ошибкой"}
    ordered = {label: stats.get(key, 0) for key, label in labels.items()}
    if not any(ordered.values()):
        return None
    ordered["total"] = sum(stats.values())
    return ui.stats_panel(title, ordered)


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
        logger.warning("Прокси не найдены — запросы пойдут напрямую")

    delay_min, delay_max = DELAY_BETWEEN_ACCOUNTS
    logs.append((time.strftime("%H:%M:%S"), f"Запуск {total} кошельков ({MAX_CONCURRENT} параллельно, задержка {delay_min}-{delay_max}с)", "INFO"))
    if proxies:
        logs.append((time.strftime("%H:%M:%S"), f"Загружено {len(proxies)} прокси (round-robin)", "INFO"))

    live = Live(balance_panel(total, 0, 0, logs), console=console, refresh_per_second=2)
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

                live.update(balance_panel(total, success, failed, logs))

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
        logger.warning("В базе нет балансов — экспортировать нечего")
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

    logger.success(f"Результаты сохранены: {filepath}")
    return filepath


def plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение: 1 токен, 2 токена, 5 токенов."""
    tail = abs(count) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def top_wallets_panel(title: str, results: dict, count_key: str,
                      forms: tuple) -> str | None:
    """Топ-10 кошельков по стоимости. ``None`` — ни на одном ничего нет."""
    top = sorted(
        (r for r in results.values()
         if r['success'] and r.get('total_usd', 0) > 0),
        key=lambda r: r['total_usd'], reverse=True,
    )[:10]
    if not top:
        return None

    amounts = [f"${r['total_usd']:,.2f}" for r in top]
    width = max(len(amount) for amount in amounts)
    lines = []
    for index, (row, amount) in enumerate(zip(top, amounts), 1):
        count = len(row[count_key])
        lines.append(
            f"{index:>2}. {ui.pad(ui.shorten_address(row['wallet'], 10, 6), 18)}"
            f"{ui.theme.FG_OK}{ui.pad(amount, width, 'right')}{ui.theme.RESET}  "
            f"{ui.theme.FG_MUTED}{count} {plural(count, *forms)}{ui.theme.RESET}"
        )
    return ui.panel(title, lines)


def print_summary(results: dict):
    """Итоги проверки балансов."""
    succeeded = [r for r in results.values() if r['success']]
    failed = [r for r in results.values() if not r['success']]
    total_usd = sum(r.get('total_usd', 0) for r in succeeded)

    ui.print_lines(ui.stats_panel("Итоги проверки балансов", {
        "успешно": len(succeeded),
        "с ошибкой": len(failed),
        "токенов найдено": sum(len(r['tokens']) for r in succeeded),
        "стоимость": f"${total_usd:,.2f}",
        "total": len(results),
    }))

    top = top_wallets_panel("Топ кошельков по стоимости", results, "tokens",
                            ("токен", "токена", "токенов"))
    if top:
        ui.print_lines(top)


def debank_checker_menu():
    """Меню проверки балансов — точка входа из главного меню."""
    wallets = choose_wallet_source()
    if not wallets:
        return

    init_database()

    stats = task_stats_panel("Прогресс · балансы", get_task_statistics())
    if stats:
        ui.print_lines(stats)

    action = ui.menu("Проверка балансов DeBank", render_items([
        MenuItem("continue", "Продолжить проверку",
                 "взять из базы незавершённые кошельки", icon="▶️"),
        MenuItem("reset", "Начать заново",
                 "очистить базу и проверить все кошельки", icon="🔄"),
        MenuItem("export", "Экспорт в CSV",
                 "выгрузить балансы из базы", icon="📄"),
        MenuItem(BACK_KEY, "Назад", "", icon="←"),
    ]))
    if action in (None, BACK_KEY):
        return

    if action == "export":
        save_results_csv(wallets)
        return

    if action == "reset":
        reset_database()
        logger.warning("База балансов очищена")
    create_tasks(wallets)

    pending_tasks = get_pending_tasks()
    if not pending_tasks:
        logger.info("Все кошельки уже проверены — для повторной проверки "
                    "выберите «Начать заново»")
        save_results_csv(wallets)
        return

    wallets_to_check = [t['wallet_address'] for t in pending_tasks]
    logger.info(f"📋 Задач к выполнению: {len(wallets_to_check)}")

    results = process_wallets(wallets_to_check)
    print_summary(results)
    save_results_csv(wallets)
    logger.success("Проверка балансов DeBank завершена")


__all__ = [
    "debank_checker_menu",
    # Общее с debank_protocol_checker.
    "load_wallets", "load_private_keys_as_wallets", "load_proxies",
    "parse_proxy_for_playwright", "choose_wallet_source", "progress_panel",
    "task_stats_panel", "top_wallets_panel", "plural",
]
