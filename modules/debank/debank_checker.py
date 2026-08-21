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
from urllib.parse import urlparse, parse_qs

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

# Пути ответов DeBank, из которых собираются балансы.
# ``cache_balance_list`` — агрегат сразу по всем сетям, ``balance_list`` — по
# одной сети (фронт дёргает его десятки раз). ``used_chains`` нужен, чтобы
# отличить пустой кошелёк от сорванной загрузки: если сетей у адреса нет,
# DeBank балансы вообще не запрашивает, и ждать их бессмысленно.
USED_CHAINS_PATH = '/user/used_chains'
CACHE_BALANCE_PATH = '/token/cache_balance_list'
CHAIN_BALANCE_PATH = '/token/balance_list'

# Сколько секунд ждём данные после загрузки страницы.
DATA_WAIT_TIMEOUT = 30

# Каждая попытка — полный запуск браузера, поэтому ретраев немного:
# при RETRY_COUNT=15 один проблемный кошелёк занимал поток минут на десять.
MAX_ATTEMPTS = max(1, min(RETRY_COUNT, 3))


# Источники кошельков: обе колонки лежат в общем data.csv проекта.
SOURCE_ADDRESSES = 'wallets'
SOURCE_PRIVATE_KEYS = 'private_keys'


def _legacy_lines(filename: str) -> list:
    """Строки из старых отдельных файлов (data/walletss.txt и т.п.).

    Нужны как запасной вариант, пока данные не перенесены в data.csv.
    """
    path = project_root / 'data' / filename
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f
                    if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error(f"Не удалось прочитать {path.name}: {e}")
        return []


def _address_from_key(private_key: str):
    """Адрес по приватному ключу. Сам ключ наружу не уходит."""
    from eth_account import Account

    key = private_key if private_key.startswith('0x') else '0x' + private_key
    try:
        return Account.from_key(key).address
    except Exception:
        return None


def load_wallet_rows(source: str = SOURCE_ADDRESSES) -> list:
    """Кошельки из общего data.csv — по адресам или по приватным ключам.

    Возвращает список ``{'address', 'proxy'}``: прокси берётся из той же
    строки, чтобы кошелёк всегда ходил через свой, а не через случайный.
    """
    from modules.data_manager import load_data

    rows = []
    invalid_keys = 0

    for row in load_data():
        proxy = (row.get('proxy') or '').strip()
        if source == SOURCE_PRIVATE_KEYS:
            key = (row.get('private_key') or '').strip()
            if not key:
                continue
            address = _address_from_key(key)
            if not address:
                invalid_keys += 1      # сам ключ не логируем — это секрет
                continue
        else:
            address = (row.get('wallet_address') or '').strip()
            if not address.startswith('0x'):
                continue
        rows.append({'address': address, 'proxy': proxy})

    if invalid_keys:
        logger.warning(f"Пропущено невалидных ключей: {invalid_keys}")

    if rows:
        return rows

    # Нужной колонки в data.csv нет — поддерживаем старые отдельные файлы.
    if source == SOURCE_PRIVATE_KEYS:
        legacy = [a for a in
                  (_address_from_key(k) for k in _legacy_lines('private_keys.txt'))
                  if a]
        source_name = 'data/private_keys.txt'
    else:
        legacy = [a for a in _legacy_lines('walletss.txt') if a.startswith('0x')]
        source_name = 'data/walletss.txt'

    if legacy:
        logger.warning(f"В data.csv нужной колонки нет — взяли {source_name}")
    return [{'address': a, 'proxy': ''} for a in legacy]


def load_wallets() -> list:
    """Адреса из колонки wallet_address общего data.csv."""
    return [row['address'] for row in load_wallet_rows(SOURCE_ADDRESSES)]


def load_private_keys_as_wallets() -> list:
    """Адреса, выведенные из колонки private_key общего data.csv."""
    return [row['address'] for row in load_wallet_rows(SOURCE_PRIVATE_KEYS)]


def load_proxies() -> list:
    """Общий пул прокси: колонка proxy из data.csv, иначе старый proxy.csv."""
    from modules.data_manager import get_proxies

    proxies = [p for p in get_proxies() if '@' in p and ':' in p]
    if proxies:
        return proxies

    return [line for line in _legacy_lines('proxy.csv')
            if '@' in line and ':' in line
            and not line.lower().startswith(('proxy', 'login'))]


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


def chains_from_body(body):
    """Список сетей из ``/user/used_chains``; пустой список — кошелёк пустой."""
    if not isinstance(body, dict):
        return None
    data = body.get('data')
    if not isinstance(data, dict):
        return None
    chains = data.get('chains')
    return chains if isinstance(chains, list) else None


def watch_balance_api(page) -> dict:
    """Подписаться на ответы DeBank; словарь наполняется по ходу загрузки."""
    state = {'chains': None, 'cache': None, 'per_chain': {}}

    async def handle_response(response):
        url = response.url
        if 'api.debank.com' not in url:
            return
        parsed = urlparse(url)
        try:
            if parsed.path == USED_CHAINS_PATH:
                chains = chains_from_body(await response.json())
                if chains is not None:
                    state['chains'] = chains
            elif parsed.path == CACHE_BALANCE_PATH:
                data = (await response.json()).get('data')
                if isinstance(data, list):
                    state['cache'] = data
            elif parsed.path == CHAIN_BALANCE_PATH:
                data = (await response.json()).get('data')
                if isinstance(data, list):
                    chain = parse_qs(parsed.query).get('chain', [''])[0]
                    state['per_chain'][chain] = data
        except Exception:
            # Тело ответа могло стать недоступным — доберём из других запросов.
            pass

    page.on('response', handle_response)
    return state


def collected_tokens(state: dict) -> list:
    """Токены из агрегата, дополненные посетевыми ответами, без дублей."""
    merged = {}
    for token in (state.get('cache') or []):
        merged[(token.get('chain'), token.get('id'))] = token
    for tokens in state.get('per_chain', {}).values():
        for token in tokens:
            merged.setdefault((token.get('chain'), token.get('id')), token)
    return list(merged.values())


def balances_ready(state: dict) -> bool:
    """Пришло ли всё, что DeBank собирался отдать по этому кошельку."""
    chains = state.get('chains')
    if chains is None:
        return False        # профиль ещё не загрузился
    if not chains:
        return True         # сетей нет — кошелёк пустой, балансов не будет
    if state.get('cache') is not None:
        return True         # пришёл агрегат сразу по всем сетям
    return set(chains) <= set(state.get('per_chain', {}))


async def wait_for_balances(state: dict, timeout: float = DATA_WAIT_TIMEOUT) -> bool:
    """Ждём сами данные, а не фиксированную паузу: запросов на профиль десятки."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if balances_ready(state):
            return True
        await asyncio.sleep(0.5)
    return balances_ready(state)


async def check_wallet_playwright(wallet: str, proxy_config: dict, semaphore: asyncio.Semaphore,
                                  playwright_instance) -> dict:
    """Проверка одного кошелька через Playwright browser"""
    async with semaphore:
        last_error = 'Max retries exceeded'

        for attempt in range(MAX_ATTEMPTS):
            try:
                launch_args = {'headless': True}
                if proxy_config:
                    launch_args['proxy'] = proxy_config

                browser = await playwright_instance.chromium.launch(**launch_args)
                try:
                    page = await browser.new_page()
                    state = watch_balance_api(page)

                    # Не networkidle: профиль тянет балансы десятками запросов
                    # и тишины в сети может не наступить вовсе.
                    await page.goto(
                        f'https://debank.com/profile/{wallet}',
                        wait_until='domcontentloaded',
                        timeout=45000
                    )

                    await wait_for_balances(state)

                    tokens_raw = collected_tokens(state)
                    is_last = attempt == MAX_ATTEMPTS - 1

                    if state['chains'] is None:
                        # Нет даже списка сетей — блокировка, капча или прокси.
                        last_error = 'DeBank не отдал данные профиля'
                    elif balances_ready(state) or (tokens_raw and is_last):
                        # Пустой кошелёк — успех: сетей нет, значит и токенов нет.
                        tokens = parse_token_data(tokens_raw)
                        return {
                            'wallet': wallet,
                            'tokens': tokens,
                            'success': True,
                            'total_usd': sum(t['value_usd'] for t in tokens),
                            'error': None,
                        }
                    else:
                        last_error = 'Балансы не пришли за отведённое время'

                finally:
                    await browser.close()

            except Exception as e:
                last_error = str(e)[:80]

            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

    return {'wallet': wallet, 'tokens': [], 'success': False,
            'total_usd': 0, 'error': last_error}


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
    """Спрашивает, по какой колонке data.csv работать.

    Возвращает строки ``{'address', 'proxy'}`` — прокси нужен, чтобы
    кошелёк ходил через свой IP. ``None`` — пользователь вышел или
    подходящих кошельков не нашлось.
    """
    source = ui.menu("Откуда берём кошельки?", render_items([
        MenuItem(SOURCE_ADDRESSES, "Адреса кошельков",
                 "колонка wallet_address в data.csv", icon="📋"),
        MenuItem(SOURCE_PRIVATE_KEYS, "Приватные ключи",
                 "колонка private_key — в ней лежат секреты", icon="🔑"),
        MenuItem(BACK_KEY, "Назад", "", icon="←"),
    ]))
    if source in (None, BACK_KEY):
        return None

    rows = load_wallet_rows(source)
    if not rows:
        column = ('private_key' if source == SOURCE_PRIVATE_KEYS
                  else 'wallet_address')
        logger.error(f"В data.csv не заполнена колонка {column}")
        return None

    if source == SOURCE_PRIVATE_KEYS:
        logger.info(f"🔑 Из ключей получено адресов: {len(rows)}")
    else:
        logger.info(f"📋 Загружено кошельков: {len(rows)}")
    return rows


def wallet_proxy_map(rows: list) -> dict:
    """Карта «адрес → свой прокси» из строк data.csv."""
    return {row['address']: row['proxy'] for row in rows if row['proxy']}


def task_stats_panel(title: str, stats: dict) -> str | None:
    """Панель прогресса по задачам. ``None`` — в базе пока пусто."""
    labels = {"completed": "готово", "pending": "в очереди", "failed": "с ошибкой"}
    ordered = {label: stats.get(key, 0) for key, label in labels.items()}
    if not any(ordered.values()):
        return None
    ordered["total"] = sum(stats.values())
    return ui.stats_panel(title, ordered)


async def process_wallets_async(wallets: list, proxy_map: dict = None) -> dict:
    """Асинхронная обработка кошельков через Playwright.

    ``proxy_map`` — прокси из строки самого кошелька в data.csv; для
    кошельков без своего прокси берётся общий пул по кругу.
    """
    from playwright.async_api import async_playwright

    results = {}
    total = len(wallets)
    success = 0
    failed = 0
    logs = []

    proxies = load_proxies()
    proxy_map = proxy_map or {}
    paired = sum(1 for w in wallets if proxy_map.get(w))
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    if not proxies:
        logger.warning("Прокси не найдены — запросы пойдут напрямую")

    delay_min, delay_max = DELAY_BETWEEN_ACCOUNTS
    logs.append((time.strftime("%H:%M:%S"), f"Запуск {total} кошельков ({MAX_CONCURRENT} параллельно, задержка {delay_min}-{delay_max}с)", "INFO"))
    if paired:
        logs.append((time.strftime("%H:%M:%S"),
                     f"У {paired} кошельков свой прокси из data.csv", "INFO"))
    if proxies:
        logs.append((time.strftime("%H:%M:%S"),
                     f"Общий пул прокси: {len(proxies)} (round-robin)", "INFO"))

    live = Live(balance_panel(total, 0, 0, logs), console=console, refresh_per_second=2)
    live.start()

    try:
        async with async_playwright() as p:

            async def process_wallet(idx, wallet):
                """Обработка одного кошелька с обновлением UI"""
                nonlocal success, failed
                # Свой прокси кошелька важнее общего пула: один адрес — один IP.
                proxy_str = proxy_map.get(wallet)
                if not proxy_str and proxies:
                    proxy_str = proxies[idx % len(proxies)]
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

            # Очередь и пул воркеров вместо создания всех задач заранее:
            # раньше между стартами ждали DELAY_BETWEEN_ACCOUNTS
            # последовательно, и на тысячах кошельков одна только раздача
            # задач растягивалась на часы, а реальная параллельность была
            # в разы ниже MAX_CONCURRENT.
            queue = asyncio.Queue()
            for item in enumerate(wallets):
                queue.put_nowait(item)

            async def worker():
                while True:
                    try:
                        idx, wallet = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    await process_wallet(idx, wallet)
                    # Пауза между кошельками одного воркера.
                    await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS))

            workers = [asyncio.create_task(worker())
                       for _ in range(min(MAX_CONCURRENT, len(wallets)))]
            await asyncio.gather(*workers, return_exceptions=True)

    finally:
        live.stop()

    return results


def process_wallets(wallets: list, proxy_map: dict = None) -> dict:
    """Обёртка для запуска асинхронной обработки"""
    return asyncio.run(process_wallets_async(wallets, proxy_map))


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
    rows = choose_wallet_source()
    if not rows:
        return

    wallets = [row["address"] for row in rows]
    proxy_map = wallet_proxy_map(rows)

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

    results = process_wallets(wallets_to_check, proxy_map)
    print_summary(results)
    save_results_csv(wallets)
    logger.success("Проверка балансов DeBank завершена")


__all__ = [
    "debank_checker_menu",
    # Общее с debank_protocol_checker.
    "load_wallets", "load_private_keys_as_wallets", "load_proxies",
    "parse_proxy_for_playwright", "choose_wallet_source", "wallet_proxy_map",
    "load_wallet_rows", "progress_panel",
    "task_stats_panel", "top_wallets_panel", "plural",
]
