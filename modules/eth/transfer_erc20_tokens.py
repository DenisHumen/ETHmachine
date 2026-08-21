"""
💎 МОДУЛЬ ПЕРЕВОДОВ ТОКЕНОВ ERC-20
===================================

Универсальный модуль для отправки токенов ERC-20 между кошельками в различных блокчейн сетях.

Основные возможности:
- Прямая отправка токенов между кошельками
- Многопоточная обработка
- Циклическая обработка с условиями
- Поддержка процентных и фиксированных сумм
- Интеграция с Telegram
- Детальная статистика

Автор: ETHmachine Team
Версия: 1.0
"""

import sys
import os
import csv
import math
import time
import random
import sqlite3
import requests
from web3 import Web3
from eth_account import Account
from colorama import Fore, Style
from datetime import datetime
from pathlib import Path
from itertools import cycle
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from modules.simple_logger import logger, log_wallet_task, set_auto_progress

# Настройка путей для импорта
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.modules.general_config import TX_SEND_ATTEMPTS, WHAITE_TRANSACTION_PENDING, WHAITE_TRANSACTION_PENDING_COUNT
from config.modules.cfg_transfer_erc20 import (
    expected_completion_time_token, MIN_FROM_BALANCE_TOKEN, trim_the_number_of_characters_enable_token,
    trim_the_number_of_characters_token, loop_transfer_enable_token, loop_transfer_count_token,
    expected_balance_from_wallet_token, expected_balance_to_wallet_token, sleep_time_between_loops_token,
    TYPE_VALUE_TO_WALLET_TOKEN, TELEGRAM_LOG_LEVEL_transfer_token,
    MULTI_THREADING_TOKEN, NUM_THREADS_TOKEN, GAS_PRICE_MULTIPLIER_TOKEN, GAS_LIMIT_MULTIPLIER_TOKEN
)
from config.networks import get_explorer_url, get_network_display_name, get_network_symbol
from config.token_address_erc20 import *

# Сентинел адреса нативного токена сети — используется в config/token_address_erc20.py
# (например AVAX/CORE/KAVA). Принимаем 'native' (строка) и каноничный
# EIP-1010 placeholder 0xEeee…EEeE.
NATIVE_TOKEN_PLACEHOLDER = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

def _is_native_token(token_address):
    """True, если адрес обозначает нативный токен сети, а не ERC-20 контракт."""
    if not token_address:
        return False
    if not isinstance(token_address, str):
        return False
    s = token_address.strip().lower()
    return s == "native" or s == NATIVE_TOKEN_PLACEHOLDER.lower()

# ERC-20 ABI для взаимодействия с токенами
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]

# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE — статусы переводов токенов
# ═══════════════════════════════════════════════════════════════════════════════

DB_DIR = Path(__file__).parent.parent.parent / "db"
DB_FILE = DB_DIR / "transfer_tasks.db"
_db_lock = Lock()
_stats_lock = Lock()  # защищает мутации TOKEN_TRANSFER_STATS в многопоточном режиме


def _init_token_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with _db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS token_transfer_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_address TEXT NOT NULL,
                    to_wallet TEXT NOT NULL,
                    to_address TEXT NOT NULL,
                    network TEXT NOT NULL,
                    token_symbol TEXT NOT NULL,
                    token_address TEXT NOT NULL,
                    amount_raw TEXT,
                    amount_sent TEXT,
                    native_balance_wei TEXT,
                    required_gas_wei TEXT,
                    gas_limit INTEGER,
                    max_fee_per_gas_wei TEXT,
                    tx_hash TEXT,
                    explorer_link TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_token_transfer_status "
                "ON token_transfer_tasks(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_token_transfer_network "
                "ON token_transfer_tasks(network)"
            )
            conn.commit()


def _create_token_task(from_address, to_wallet, to_address, network,
                       token_symbol, token_address, amount_raw):
    """Создаёт запись задачи в БД и возвращает её id."""
    try:
        _init_token_db()
        with _db_lock:
            with sqlite3.connect(str(DB_FILE)) as conn:
                cur = conn.execute(
                    """INSERT INTO token_transfer_tasks
                       (from_address, to_wallet, to_address, network,
                        token_symbol, token_address, amount_raw, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                    (from_address, to_wallet, to_address, network,
                     token_symbol, token_address, amount_raw),
                )
                conn.commit()
                return cur.lastrowid
    except Exception as e:
        logger.warning(f"Не удалось создать запись задачи в БД: {e}")
        return None


def _update_token_task(task_id, **kwargs):
    """Обновляет поля задачи. Допустимые статусы:
    pending | completed | failed | insufficient_balance | insufficient_token_balance
    """
    if not task_id or not kwargs:
        return
    try:
        kwargs["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        with _db_lock:
            with sqlite3.connect(str(DB_FILE)) as conn:
                conn.execute(
                    f"UPDATE token_transfer_tasks SET {set_clause} WHERE id = ?",
                    values,
                )
                conn.commit()
    except Exception as e:
        logger.warning(f"Не удалось обновить задачу {task_id} в БД: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# GAS — корректный расчёт EIP-1559 / legacy
# ═══════════════════════════════════════════════════════════════════════════════


def _compute_gas_fees(w3):
    """Возвращает (max_fee_per_gas, max_priority_fee_per_gas, use_eip1559).

    На EIP-1559 сетях (Ethereum, Arbitrum, Base, Optimism, Polygon, …) считаем:
        max_priority_fee = max(eth_maxPriorityFeePerGas, 0.001 gwei)
        max_fee          = base_fee * GAS_PRICE_MULTIPLIER_TOKEN + priority_fee
    На legacy сетях:
        max_fee          = eth_gasPrice * GAS_PRICE_MULTIPLIER_TOKEN
    """
    base_fee = None
    try:
        latest = w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas")
    except Exception:
        base_fee = None

    if base_fee is not None:
        try:
            priority_fee = int(w3.eth.max_priority_fee)
        except Exception:
            priority_fee = w3.to_wei("0.001", "gwei")
        priority_fee = max(priority_fee, w3.to_wei("0.001", "gwei"))
        max_fee = int(base_fee * GAS_PRICE_MULTIPLIER_TOKEN) + priority_fee
        return max_fee, priority_fee, True

    try:
        gas_price = int(w3.eth.gas_price)
    except Exception:
        gas_price = w3.to_wei("30", "gwei")
    return int(gas_price * GAS_PRICE_MULTIPLIER_TOKEN), None, False


def _estimate_gas_limit(w3, token_contract, from_address, to_address, amount_raw):
    """Безопасно оценивает gas-limit ERC20 transfer и применяет
    GAS_LIMIT_MULTIPLIER_TOKEN. Fallback на 100000 при ошибке."""
    try:
        gas = token_contract.functions.transfer(
            Web3.to_checksum_address(to_address), amount_raw
        ).estimate_gas({"from": Web3.to_checksum_address(from_address)})
        return int(gas * GAS_LIMIT_MULTIPLIER_TOKEN)
    except Exception as e:
        logger.warning(
            f"Не удалось оценить газ ({from_address[:10]}…), "
            f"используем 100000 * множитель: {e}"
        )
        return int(100000 * GAS_LIMIT_MULTIPLIER_TOKEN)


def _build_fee_params(max_fee, priority_fee, use_eip1559):
    """Возвращает kwargs для build_transaction под нужный тип сети."""
    if use_eip1559:
        return {
            "type": 0x2,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
        }
    return {"gasPrice": max_fee}


# Глобальная статистика
TOKEN_TRANSFER_STATS = {
    "start_time": None,
    "end_time": None,
    "total_transactions_attempted": 0,
    "total_transactions_success": 0,
    "total_transactions_failed": 0,
    "total_amount_transferred": 0,
    "wallets_processed": 0,
    "wallets_failed": 0,
    "cycles_completed": 0,
    "errors": [],
    "successful_txs": [],
    "network": "",
    "token_symbol": "",
    "loop_mode": False
}

def init_token_stats(network, token_symbol, loop_mode=False):
    """Инициализация статистики для переводов токенов (сброс под текущий запуск)."""
    global TOKEN_TRANSFER_STATS
    with _stats_lock:
        TOKEN_TRANSFER_STATS["start_time"] = datetime.now()
        TOKEN_TRANSFER_STATS["end_time"] = None
        TOKEN_TRANSFER_STATS["total_transactions_attempted"] = 0
        TOKEN_TRANSFER_STATS["total_transactions_success"] = 0
        TOKEN_TRANSFER_STATS["total_transactions_failed"] = 0
        TOKEN_TRANSFER_STATS["total_amount_transferred"] = 0
        TOKEN_TRANSFER_STATS["wallets_processed"] = 0
        TOKEN_TRANSFER_STATS["wallets_failed"] = 0
        TOKEN_TRANSFER_STATS["cycles_completed"] = 0
        TOKEN_TRANSFER_STATS["errors"] = []
        TOKEN_TRANSFER_STATS["successful_txs"] = []
        TOKEN_TRANSFER_STATS["network"] = network
        TOKEN_TRANSFER_STATS["token_symbol"] = token_symbol
        TOKEN_TRANSFER_STATS["loop_mode"] = loop_mode


def _bump_stats(**deltas):
    """Атомарно изменяет несколько счётчиков TOKEN_TRANSFER_STATS."""
    with _stats_lock:
        for k, v in deltas.items():
            TOKEN_TRANSFER_STATS[k] = TOKEN_TRANSFER_STATS.get(k, 0) + v


def update_token_stats(success=True, amount=0, tx_hash=None, error_msg=None):
    """Обновление статистики переводов токенов (потокобезопасно)."""
    with _stats_lock:
        TOKEN_TRANSFER_STATS["total_transactions_attempted"] += 1
        if success:
            TOKEN_TRANSFER_STATS["total_transactions_success"] += 1
            if amount > 0:
                TOKEN_TRANSFER_STATS["total_amount_transferred"] += amount
            if tx_hash:
                TOKEN_TRANSFER_STATS["successful_txs"].append(tx_hash)
        else:
            TOKEN_TRANSFER_STATS["total_transactions_failed"] += 1
            if error_msg:
                TOKEN_TRANSFER_STATS["errors"].append(error_msg)

def finalize_token_stats():
    """Завершение статистики и отправка в телеграм"""
    global TOKEN_TRANSFER_STATS
    with _stats_lock:
        TOKEN_TRANSFER_STATS["end_time"] = datetime.now()
    
    # Рассчитываем время работы
    if TOKEN_TRANSFER_STATS["start_time"]:
        duration = TOKEN_TRANSFER_STATS["end_time"] - TOKEN_TRANSFER_STATS["start_time"]
        duration_str = str(duration).split('.')[0]
    else:
        duration_str = "Неизвестно"
    
    # Рассчитываем процент успешных транзакций
    success_rate = 0
    if TOKEN_TRANSFER_STATS["total_transactions_attempted"] > 0:
        success_rate = (TOKEN_TRANSFER_STATS["total_transactions_success"] / TOKEN_TRANSFER_STATS["total_transactions_attempted"]) * 100
    
    # Отправляем статистику
    if TELEGRAM_LOG_LEVEL_transfer_token >= 1:
        stats_message = f"""
📊 <b>СТАТИСТИКА ПЕРЕВОДОВ ТОКЕНОВ</b>

⏱️ <b>Время работы:</b> {duration_str}
🌐 <b>Сеть:</b> {TOKEN_TRANSFER_STATS['network']}
💎 <b>Токен:</b> {TOKEN_TRANSFER_STATS['token_symbol'].upper()}
🔁 <b>Цикличность:</b> {'Включена' if TOKEN_TRANSFER_STATS['loop_mode'] else 'Отключена'}

📈 <b>ТРАНЗАКЦИИ:</b>
• Всего попыток: {TOKEN_TRANSFER_STATS['total_transactions_attempted']}
• Успешных: {TOKEN_TRANSFER_STATS['total_transactions_success']}
• Неудачных: {TOKEN_TRANSFER_STATS['total_transactions_failed']}
• Процент успеха: {success_rate:.1f}%

👛 <b>КОШЕЛЬКИ:</b>
• Обработано: {TOKEN_TRANSFER_STATS['wallets_processed']}
• С ошибками: {TOKEN_TRANSFER_STATS['wallets_failed']}

💰 <b>ПЕРЕВЕДЕНО:</b>
• Общее количество: {TOKEN_TRANSFER_STATS['total_amount_transferred']:.6f} {TOKEN_TRANSFER_STATS['token_symbol'].upper()}

🔁 <b>ЦИКЛЫ:</b> {TOKEN_TRANSFER_STATS['cycles_completed']}

🚨 <b>Ошибки:</b> {len(TOKEN_TRANSFER_STATS['errors'])}
✅ <b>Успешные tx:</b> {len(TOKEN_TRANSFER_STATS['successful_txs'])}
        """
        

        # Отправляем файл результатов если есть
        result_file = "result/token_transfer_result.csv"
        if os.path.exists(result_file):

            pass
def get_network_rpc(network):
    """Получение RPC URL для сети"""
    from config.networks import get_network_rpc_urls
    import random
    
    rpc_urls = get_network_rpc_urls(network)
    if not rpc_urls:
        raise Exception(f"Неизвестная сеть: {network}")
    return random.choice(rpc_urls)

def get_proxy_list():
    """Получение списка прокси.

    ВАЖНО: НЕ блокирует ввод (раньше был input() — в многопоточном режиме это
    приводило к дедлоку, т.к. функция вызывается из каждого worker-потока).
    Если прокси нет — возвращаем пустой список и пишем предупреждение
    один раз; connect_with_failover тогда подключится напрямую.
    """
    from modules.data_manager import get_proxies
    proxies = get_proxies()
    if not proxies:
        # Атомарный флаг, чтобы не спамить варнингом из каждого потока
        if not getattr(get_proxy_list, "_warned", False):
            logger.warning(
                "В data/data.csv нет прокси — будем подключаться к RPC напрямую"
            )
            get_proxy_list._warned = True
    return proxies

def _build_session(proxy_url):
    """Строит requests.Session: либо с указанным прокси, либо ЯВНО без прокси
    (trust_env=False, чтобы не подцеплять HTTPS_PROXY из окружения)."""
    session = requests.Session()
    session.trust_env = False  # не используем системные proxy env vars
    if proxy_url:
        if '@' in proxy_url:
            auth_part, address_part = proxy_url.split('@')
            login, password = auth_part.split(':')
            ip, port = address_part.split(':')
            proxy_dict = {
                'http':  f"http://{login}:{password}@{ip}:{port}",
                'https': f"http://{login}:{password}@{ip}:{port}",
            }
        else:
            proxy_dict = {
                'http':  f"http://{proxy_url}",
                'https': f"http://{proxy_url}",
            }
        session.proxies.update(proxy_dict)
    return session


def _try_connect(rpc_url, proxy_url, timeout=10):
    """Одна попытка подключения. Возвращает (w3, session) или бросает."""
    from web3 import HTTPProvider
    session = _build_session(proxy_url)
    provider = HTTPProvider(rpc_url, session=session, request_kwargs={'timeout': timeout})
    w3 = Web3(provider)
    # Проверяем что соединение реально живо
    _ = w3.eth.chain_id
    return w3, session


# In-memory blacklist для RPC, которые мёртвы (404 / DNS / refused).
# Накапливается за время процесса — RPC из него пропускаются в connect_with_failover.
# Не сохраняется между запусками; конфиг networks.py остаётся источником истины.
_DEAD_RPC_BLACKLIST: set = set()
_DEAD_RPC_LOCK = Lock()
# Лог-однократность для каждого URL: чтобы не спамить «blacklist X» в каждом потоке.
_DEAD_RPC_LOGGED: set = set()


def _is_permanent_rpc_error(exc) -> bool:
    """True, если URL стабильно неюзабелен на эту сессию
    (мёртвый/требует API-ключ), а не временный сбой прокси/сети.

    Распознаём:
      - HTTP 404 (Not Found) — endpoint исчез / опечатка
      - HTTP 410 (Gone)
      - HTTP 401/403 — нужна авторизация (Alchemy/Ankr/Infura без ключа)
      - JSON-RPC «Unauthorized» / «API key required» — то же на уровне JSON
      - DNS/Name resolution failure
      - Connection refused — порт закрыт
    Таймауты (408/504), rate-limit (429), и 5xx считаем ВРЕМЕННЫМИ.
    """
    msg = str(exc)
    lower = msg.lower()
    if "404" in msg and "not found" in lower:
        return True
    if "410" in msg and ("gone" in lower or "Gone" in msg):
        return True
    if "401" in msg and ("unauthorized" in lower or "auth" in lower):
        return True
    if "403" in msg and "forbidden" in lower:
        return True
    # JSON-RPC сообщения с требованием API-ключа
    if "unauthorized" in lower and ("api key" in lower or "authenticate" in lower):
        return True
    if "api key" in lower and ("required" in lower or "missing" in lower or "must" in lower):
        return True
    if "nameresolutionerror" in lower or "name or service not known" in lower:
        return True
    if "name resolution" in lower or "failed to resolve" in lower:
        return True
    if "connection refused" in lower:
        return True
    return False


def _blacklist_rpc(rpc_url, reason):
    """Атомарно помечает RPC как мёртвый. Логирует один раз."""
    with _DEAD_RPC_LOCK:
        first_time = rpc_url not in _DEAD_RPC_BLACKLIST
        _DEAD_RPC_BLACKLIST.add(rpc_url)
        already_logged = rpc_url in _DEAD_RPC_LOGGED
        if first_time and not already_logged:
            _DEAD_RPC_LOGGED.add(rpc_url)
            should_log = True
        else:
            should_log = False
    if should_log:
        logger.warning(
            f"🚫 RPC помечен как мёртвый на эту сессию: {rpc_url[:60]} ({reason})"
        )


def connect_with_failover(network, proxies, exclude_proxy=None, exclude_rpc=None,
                          max_attempts=8):
    """Перебирает (rpc × proxy) комбинации до первой рабочей.

    Алгоритм:
      1. RPC из config.networks для нужной сети, перемешанные.
         Мёртвые RPC (_DEAD_RPC_BLACKLIST) пропускаются.
      2. Прокси из data.csv, перемешанные (плюс None как fallback).
      3. Пробуем не больше max_attempts комбинаций.
      4. Если ни одна не сработала — пробуем все RPC напрямую (без прокси).
      5. Если и это не помогло — поднимаем исключение.

    Возвращает (w3, session, used_rpc, used_proxy).
    """
    from config.networks import get_network_rpc_urls

    raw_rpc_urls = list(get_network_rpc_urls(network) or [])
    # Отфильтровываем мёртвые. Если после фильтра пусто — fallback к полному списку
    # (на случай если все попали в blacklist по ошибке).
    with _DEAD_RPC_LOCK:
        dead = set(_DEAD_RPC_BLACKLIST)
    rpc_urls = [r for r in raw_rpc_urls if r not in dead] or raw_rpc_urls
    if exclude_rpc:
        rpc_urls = [r for r in rpc_urls if r != exclude_rpc] or rpc_urls
    if not rpc_urls:
        raise Exception(f"Нет настроенных RPC для сети {network}")

    proxy_pool = [p for p in (proxies or []) if p and p != exclude_proxy]

    random.shuffle(rpc_urls)
    if proxy_pool:
        random.shuffle(proxy_pool)

    last_error = None
    attempts = 0

    # 1) (rpc, proxy) комбинации
    for rpc in rpc_urls:
        if attempts >= max_attempts:
            break
        # Если RPC попал в blacklist по ходу попыток — пропускаем
        if rpc in _DEAD_RPC_BLACKLIST:
            continue
        for proxy in (proxy_pool or [None]):
            attempts += 1
            try:
                w3, session = _try_connect(rpc, proxy)
                return w3, session, rpc, proxy
            except Exception as e:
                last_error = e
                # Если ошибка — это «RPC мёртв», вносим в blacklist и больше
                # не пробуем его через другие прокси.
                if _is_permanent_rpc_error(e):
                    _blacklist_rpc(rpc, f"{type(e).__name__}: {str(e)[:80]}")
                    break  # выходим из цикла по прокси для этого RPC
                logger.warning(
                    f"⚠️  RPC {rpc[:45]} via {(proxy or 'direct')[:25]} "
                    f"→ {type(e).__name__}: {str(e)[:120]}"
                )
                if attempts >= max_attempts:
                    break

    # 2) Last resort — все RPC напрямую без прокси (тоже минуя blacklist)
    for rpc in rpc_urls:
        if rpc in _DEAD_RPC_BLACKLIST:
            continue
        try:
            w3, session = _try_connect(rpc, None)
            logger.warning(f"⚠️  Подключились напрямую (без прокси) через {rpc[:45]}")
            return w3, session, rpc, None
        except Exception as e:
            last_error = e
            if _is_permanent_rpc_error(e):
                _blacklist_rpc(rpc, f"{type(e).__name__}: {str(e)[:80]}")

    raise Exception(
        f"Не удалось подключиться к сети {network} после {attempts} попыток: {last_error}"
    )


# Совместимость со старым API (на случай, если кто-то зовёт снаружи).
def get_web3_with_proxy(rpc_url, proxy_url):
    """DEPRECATED: одна попытка. Используйте connect_with_failover()."""
    try:
        return _try_connect(rpc_url, proxy_url)
    except Exception as e:
        logger.error(f"ВНИМАНИЕ: одиночное подключение упало ({rpc_url[:45]}): {e}")
        raise


def _safe_eth_call(callable_, retries=3, base_delay=1.0, name="eth_call"):
    """Делает callable_() с экспоненциальным бэкоффом. Бросает после retries неудач."""
    last_err = None
    for attempt in range(retries):
        try:
            return callable_()
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise last_err if last_err else Exception(f"{name} failed without error")


def get_token_balance(w3, token_address, wallet_address):
    """Получение баланса токена. Возвращает int.
    БРОСАЕТ исключение при сбоях RPC после внутренних ретраев — чтобы caller
    мог отличить «реально 0 на балансе» от «RPC недоступен»."""
    contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
    return _safe_eth_call(
        lambda: contract.functions.balanceOf(
            Web3.to_checksum_address(wallet_address)
        ).call(),
        name="balanceOf",
    )


def get_token_decimals(w3, token_address):
    """Получение количества десятичных знаков токена. БРОСАЕТ при сбоях RPC."""
    contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
    return _safe_eth_call(
        lambda: contract.functions.decimals().call(),
        name="decimals",
    )


def _get_decimals_with_reconnect(w3, session, token_address, network, proxies, used_rpc, used_proxy):
    """Пытается прочитать decimals; если RPC падает — переподключается через
    другую комбинацию (rpc, proxy) и пробует ещё раз. Возвращает (decimals, w3, session).
    Бросает, если получить decimals не удалось вообще."""
    try:
        return get_token_decimals(w3, token_address), w3, session
    except Exception as e:
        logger.warning(f"decimals: первичный RPC упал ({type(e).__name__}: {e}); реконнект…")
        try: session.close()
        except Exception: pass
        w3, session, used_rpc, used_proxy = connect_with_failover(
            network, proxies, exclude_proxy=used_proxy, exclude_rpc=used_rpc
        )
        # Второй заход — но уже без подавления ошибки
        return get_token_decimals(w3, token_address), w3, session


def _get_balance_with_reconnect(w3, session, token_address, wallet_address, network, proxies):
    """Аналогично — балансы токена с реконнектом при сбое RPC.
    Возвращает (balance, w3, session). Бросает, если RPC недоступен и после реконнекта."""
    try:
        return get_token_balance(w3, token_address, wallet_address), w3, session
    except Exception as e:
        logger.warning(f"balanceOf: RPC упал ({type(e).__name__}: {e}); реконнект…")
        try: session.close()
        except Exception: pass
        w3, session, _r, _p = connect_with_failover(network, proxies)
        return get_token_balance(w3, token_address, wallet_address), w3, session


def _get_native_balance_safe(w3, wallet_address):
    """Чтение нативного баланса с ретраями. БРОСАЕТ при сбое RPC после ретраев."""
    return _safe_eth_call(
        lambda: w3.eth.get_balance(Web3.to_checksum_address(wallet_address)),
        name="eth_getBalance",
    )


def _get_native_balance_with_reconnect(w3, session, wallet_address, network, proxies,
                                       used_rpc=None, used_proxy=None):
    """Чтение нативного баланса с реконнектом при сбое RPC.

    Возвращает (balance, w3, session). Бросает, если RPC недоступен даже после
    переподключения через другой (rpc, proxy)."""
    try:
        return _get_native_balance_safe(w3, wallet_address), w3, session
    except Exception as e:
        logger.warning(f"eth.get_balance: RPC упал ({type(e).__name__}: {e}); реконнект…")
        try: session.close()
        except Exception: pass
        w3, session, _r, _p = connect_with_failover(
            network, proxies, exclude_proxy=used_proxy, exclude_rpc=used_rpc
        )
        return _get_native_balance_safe(w3, wallet_address), w3, session


def _verify_zero_native_balance(balance, w3, session, wallet_address, network, proxies,
                                used_rpc, used_proxy):
    """Если первичный RPC вернул баланс=0 — sanity check через другой RPC.
    Возвращает (balance, w3, session). Никогда не бросает — на ошибках во время
    проверки возвращает изначальный 0 (т.е. поведение «как было раньше»).

    Цель: не фейлить кошелёк впустую если RPC отдал stale-нулевой ответ.
    """
    if balance != 0:
        return balance, w3, session

    from config.networks import get_network_rpc_urls
    rpc_pool = [r for r in (get_network_rpc_urls(network) or []) if r != used_rpc]
    if not rpc_pool:
        return balance, w3, session

    try:
        new_w3, new_session, new_rpc, _ = connect_with_failover(
            network, proxies, exclude_proxy=used_proxy, exclude_rpc=used_rpc,
            max_attempts=3,
        )
    except Exception as e:
        logger.warning(f"second-look @ balance=0: не удалось переподключиться: {e}")
        return balance, w3, session

    try:
        verified = _get_native_balance_safe(new_w3, wallet_address)
    except Exception as e:
        logger.warning(f"second-look @ balance=0: чтение упало ({type(e).__name__}: {e})")
        try: new_session.close()
        except Exception: pass
        return balance, w3, session

    if verified == 0:
        # Действительно пусто — закрываем новый коннект, возвращаем старый
        try: new_session.close()
        except Exception: pass
        return 0, w3, session

    # Второй RPC показал НЕНУЛЕВОЙ баланс → первый RPC лагал.
    # Переключаемся на новый коннект.
    logger.warning(
        f"⚠️  RPC {used_rpc[:40]} вернул баланс=0, но {new_rpc[:40]} "
        f"показал {verified} wei — используем второй"
    )
    try: session.close()
    except Exception: pass
    return verified, new_w3, new_session


def get_token_symbol(w3, token_address):
    """Получение символа токена (мягкое падение — для UI). При сбоях возвращает 'TOKEN'."""
    try:
        contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        return _safe_eth_call(
            lambda: contract.functions.symbol().call(),
            retries=2,
            name="symbol",
        )
    except Exception as e:
        logger.warning(f"Не удалось получить символ токена: {e}")
        return "TOKEN"

# Значения transfer_amount без суффикса, о которых уже предупредили.
# Предупреждаем один раз на уникальное значение, иначе в многопоточном режиме
# лог засоряется одинаковой строкой от каждого воркера.
_BARE_AMOUNT_WARNED: set = set()
_BARE_AMOUNT_LOCK = Lock()


def _warn_bare_amount(raw):
    """Однократно предупреждает, что значение без суффикса — это КОЛИЧЕСТВО.

    До исправления такая запись трактовалась как процент от баланса, поэтому
    пользователь, у которого в data.csv лежит '90', должен заметить смену
    смысла до того, как уйдёт транзакция."""
    with _BARE_AMOUNT_LOCK:
        if raw in _BARE_AMOUNT_WARNED:
            return
        _BARE_AMOUNT_WARNED.add(raw)
    logger.warning(
        f"⚠️  transfer_amount='{raw}' без суффикса → трактуем как КОЛИЧЕСТВО ТОКЕНОВ "
        f"(так описано в config/modules/cfg_transfer_erc20.py). "
        f"Если нужен процент от баланса — допишите '%': '{raw}%'"
    )


def _parse_amount_bounds(spec):
    """Разбирает 'X' или 'X-Y' в (lo, hi). Бросает ValueError на любом мусоре.

    Явная ошибка принципиальна: молчаливый fallback здесь означал бы отправку
    не той суммы, а это чужие деньги."""
    spec = spec.strip()
    if not spec:
        raise ValueError("нет числа перед суффиксом")

    parts = [p.strip() for p in spec.split('-')]
    if len(parts) == 1:
        lo_str = hi_str = parts[0]
    elif len(parts) == 2:
        lo_str, hi_str = parts
    else:
        raise ValueError("ожидается число или диапазон вида 'мин-макс'")

    try:
        lo, hi = float(lo_str), float(hi_str)
    except (TypeError, ValueError):
        raise ValueError(
            "границы не являются числами (десятичный разделитель — точка, не запятая)"
        ) from None

    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ValueError("границы должны быть конечными числами")
    if lo < 0 or hi < 0:
        raise ValueError("отрицательное значение недопустимо")
    # Перевёрнутый диапазон ('20-10') не запрещаем: random.uniform работает в любом
    # порядке, и раньше такая запись тоже отрабатывала — не ломаем чужие конфиги.
    return lo, hi


def parse_amount_range(amount_str):
    """
    Парсит значение transfer_amount из data/data.csv.

    Грамматика — ровно та, что описана в шапке config/modules/cfg_transfer_erc20.py:
        "10-20%"   → 10–20 % от баланса токена
        "90%"      → 90 % от баланса токена
        "1-3token" → 1–3 токена (абсолютное количество)
        "5token"   → 5 токенов
        "10-20"    → 10–20 токенов: без суффикса это КОЛИЧЕСТВО, а не процент

    Возвращает (lo, hi, 'PERCENT' | 'FIXED').

    Бросает ValueError на всём, что не разобралось. Раньше любая ошибка разбора
    молча превращалась в (100, 100, 'PERCENT') — то есть опечатка в одной ячейке
    CSV означала «отправить весь баланс». Вызывающий обязан пропустить кошелёк.
    """
    if amount_str is None:
        raise ValueError("значение не задано")
    raw = str(amount_str).strip()
    if not raw:
        raise ValueError("значение пустое")

    if raw.endswith('%'):
        lo, hi = _parse_amount_bounds(raw[:-1])
        return lo, hi, 'PERCENT'

    if raw.lower().endswith('token'):
        lo, hi = _parse_amount_bounds(raw[:-5])
        return lo, hi, 'FIXED'

    lo, hi = _parse_amount_bounds(raw)
    _warn_bare_amount(raw)
    return lo, hi, 'FIXED'

def apply_trim_to_amount(amount):
    """Применяет обрезку к количеству токенов"""
    if trim_the_number_of_characters_enable_token and trim_the_number_of_characters_token:
        trim_digits = random.choice(trim_the_number_of_characters_token)
        return round(amount, trim_digits)
    return amount

def get_nonce_safe(w3, address, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    """Безопасное получение nonce"""
    for attempt in range(max_attempts):
        try:
            return w3.eth.get_transaction_count(address)
        except Exception as e:
            logger.warning(f"[{address}] Ошибка получения nonce (попытка {attempt+1}/{max_attempts}): {e}")
            time.sleep(sleep_sec)
    logger.error(f"[{address}] Не удалось получить nonce после {max_attempts} попыток.")
    return None

def estimate_gas_safe(w3, tx, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    """Безопасная оценка газа"""
    for attempt in range(max_attempts):
        try:
            gas = w3.eth.estimate_gas(tx)
            return int(gas * GAS_LIMIT_MULTIPLIER_TOKEN)
        except KeyboardInterrupt:
            logger.error("\nОперация прервана пользователем (Ctrl+C). Завершение работы.")
            raise
        except Exception as e:
            logger.warning(f"Не удалось оценить газ (попытка {attempt+1}/{max_attempts}): {e}")
            time.sleep(sleep_sec)
    return int(100000 * GAS_LIMIT_MULTIPLIER_TOKEN)  # Используем стандартный лимит газа для токенов

def validate_wallet_format(wallet_value, expected_type, row_index):
    """Проверяет формат кошелька"""
    if not wallet_value or not isinstance(wallet_value, str):
        return False, f"Пустое значение кошелька"
    
    wallet_value = wallet_value.strip()
    
    if expected_type == 0:  # Приватный ключ
        if wallet_value.startswith('0x'):
            if len(wallet_value) == 66:
                try:
                    int(wallet_value, 16)
                    return True, "OK"
                except ValueError:
                    return False, f"Неверный формат приватного ключа (не hex)"
            else:
                return False, f"Неверная длина приватного ключа с 0x (ожидается 66 символов, получено {len(wallet_value)})"
        else:
            if len(wallet_value) == 64:
                try:
                    int(wallet_value, 16)
                    return True, "OK"
                except ValueError:
                    return False, f"Неверный формат приватного ключа (не hex)"
            else:
                return False, f"Неверная длина приватного ключа (ожидается 64 символа, получено {len(wallet_value)})"
    
    elif expected_type == 1:  # Адрес кошелька
        if wallet_value.startswith('0x') and len(wallet_value) == 42:
            try:
                int(wallet_value, 16)
                return True, "OK"
            except ValueError:
                return False, f"Неверный формат адреса кошелька (не hex)"
        else:
            return False, f"Неверный формат адреса кошелька (должен начинаться с 0x и быть длиной 42 символа, получено {len(wallet_value)})"
    
    return False, f"Неизвестный тип кошелька: {expected_type}"

def validate_token_transfer_data(transfer_data):
    """Проверяет данные переводов токенов на корректность"""
    errors = []
    
    for idx, row in enumerate(transfer_data, start=1):
        # Проверяем from_wallet (всегда должен быть приватный ключ)
        is_valid, error_msg = validate_wallet_format(row.get('from_wallet', ''), 0, idx)
        if not is_valid:
            errors.append(f"Строка {idx}, поле 'from_wallet': {error_msg}")

        # Проверяем to_wallet
        is_valid, error_msg = validate_wallet_format(row.get('to_wallet', ''), TYPE_VALUE_TO_WALLET_TOKEN, idx)
        if not is_valid:
            wallet_type_name = "приватный ключ" if TYPE_VALUE_TO_WALLET_TOKEN == 0 else "адрес кошелька"
            errors.append(f"Строка {idx}, поле 'to_wallet' (ожидается {wallet_type_name}): {error_msg}")
        
        # Проверяем не только наличие, но и разбор amount: опечатка в transfer_amount
        # раньше молча означала «отправить 100% баланса», поэтому ловим её до старта,
        # а не в момент, когда кошелёк уже подключился к RPC.
        raw_amount = row.get('amount', '').strip()
        if not raw_amount:
            errors.append(f"Строка {idx}, поле 'amount': отсутствует количество для перевода")
        else:
            try:
                parse_amount_range(raw_amount)
            except ValueError as e:
                errors.append(
                    f"Строка {idx}, поле 'amount': некорректное значение '{raw_amount}' — {e}. "
                    f"Допустимые формы: '10-20%', '90%', '1-3token', '5token', '10-20'"
                )

    return errors

def get_to_wallet_address(to_wallet_value):
    """Получает адрес кошелька получателя"""
    if TYPE_VALUE_TO_WALLET_TOKEN == 0:
        # to_wallet - это приватный ключ
        try:
            to_acc = Account.from_key(to_wallet_value)
            return to_acc.address, to_wallet_value
        except Exception as e:
            raise Exception(f"Ошибка создания аккаунта из приватного ключа: {e}")
    elif TYPE_VALUE_TO_WALLET_TOKEN == 1:
        # to_wallet - это уже адрес
        try:
            checksum_address = Web3.to_checksum_address(to_wallet_value)
            return checksum_address, None
        except Exception as e:
            raise Exception(f"Ошибка преобразования адреса в checksum формат: {e}")
    else:
        raise Exception(f"Неизвестный тип TYPE_VALUE_TO_WALLET_TOKEN: {TYPE_VALUE_TO_WALLET_TOKEN}")

def append_token_result_csv(row):
    """Записывает результат в CSV файл"""
    filename = "result/token_transfer_result.csv"
    header = [
        "datetime", "from_wallet", "from_address", "to_wallet", "to_address",
        "token_symbol", "token_address", "amount_sent", "tx_hash", "explorer_link",
    ]
    try:
        need_header = False
        try:
            with open(filename, "r", encoding="utf-8") as f:
                if not f.readline():
                    need_header = True
        except FileNotFoundError:
            need_header = True
        
        with open(filename, "a", encoding="utf-8", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            if need_header:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        logger.error(f"Ошибка записи в result/token_transfer_result.csv: {e}")

def countdown_timer(seconds, message_prefix="Пауза"):
    """Отсчет времени до следующей транзакции"""
    for remaining in range(seconds, 0, -1):
        print(
            f"{Fore.YELLOW}{message_prefix} {remaining} сек до следующей транзакции...{Style.RESET_ALL} ",
            end="\r",
            flush=True,
        )
        time.sleep(1)
    print("\r" + " " * 80 + "\r", end="")

def transfer_erc20_tokens(from_priv, to_wallet_value, network, token_address, token_symbol, amount, proxy=None, delay_between=0, task_index=None, task_total=None):
    """Основная функция для прямого перевода токенов ERC-20"""
    session = None
    task_id = None
    wallet_short = None  # обновляется после создания from_acc; используется _log

    use_threaded_log = (
        MULTI_THREADING_TOKEN and task_index is not None and task_total is not None
    )

    def _log(msg, status="info"):
        """В многопоточном режиме пишем через log_wallet_task — даёт
        выравнивание: HH:MM:SS │ STATUS │ [i/N] │ wallet │ message.
        В одиночном режиме оставляем привычный logger."""
        if use_threaded_log:
            log_wallet_task(
                wallet_short or "—", task_index, task_total, msg, status=status
            )
            return
        method = {
            "success": logger.success,
            "error":   logger.error,
            "warning": logger.warning,
            "info":    logger.info,
        }.get(status, logger.info)
        method(msg)

    try:
        start_time = time.time()
        dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        proxies = get_proxy_list()
        # Если caller передал конкретный прокси — поднимаем его в начало пула,
        # но НЕ ограничиваемся им: при сбое будем пробовать другие.
        if proxy:
            proxies = [proxy] + [p for p in proxies if p != proxy]

        # Создаем аккаунты
        try:
            from_acc = Account.from_key(from_priv)
            wallet_short = f"{from_acc.address[:8]}…{from_acc.address[-4:]}"
            to_address, to_priv = get_to_wallet_address(to_wallet_value)
        except Exception as e:
            _log(f"Ошибка создания аккаунта: {e}", status="error")
            update_token_stats(success=False, error_msg=f"Ошибка создания аккаунта: {e}")
            if TELEGRAM_LOG_LEVEL_transfer_token == 2:
                pass
            return

        # Создаём запись задачи в БД заранее (чтобы зафиксировать даже network_error)
        task_id = _create_token_task(
            from_address=from_acc.address,
            to_wallet=to_wallet_value,
            to_address=to_address,
            network=network,
            token_symbol=(token_symbol or "?"),
            token_address=token_address,
            amount_raw=str(amount),
        )

        # Подключаемся к сети с failover (rpc × proxy)
        try:
            w3, session, used_rpc, used_proxy = connect_with_failover(network, proxies)
        except Exception as e:
            err = f"не удалось подключиться к {network}: {e}"
            _log(err, status="error")
            _update_token_task(task_id, status="network_error", error_message=err)
            update_token_stats(success=False, error_msg=err)
            return

        explorer_url = get_explorer_url(network)
        is_native = _is_native_token(token_address)

        # Получаем информацию о токене.
        # Для нативного токена пропускаем ERC-20 чтения: decimals всегда 18,
        # символ берём из конфига сети, если caller не передал явный.
        if is_native:
            token_decimals = 18
            token_symbol_actual = (token_symbol or get_network_symbol(network) or "NATIVE").upper()
        else:
            try:
                token_decimals, w3, session = _get_decimals_with_reconnect(
                    w3, session, token_address, network, proxies, used_rpc, used_proxy
                )
            except Exception as e:
                err = f"не удалось прочитать decimals токена ({network}): {e}"
                _log(err, status="error")
                _update_token_task(task_id, status="network_error", error_message=err)
                update_token_stats(success=False, error_msg=err)
                return

            token_symbol_actual = get_token_symbol(w3, token_address) if not token_symbol else token_symbol

        _update_token_task(task_id, token_symbol=token_symbol_actual)

        if not MULTI_THREADING_TOKEN:
            token_addr_display = "NATIVE" if is_native else f"{token_address[:10]}..."
            logger.info("="*61)
            logger.info(f"[{dt_str}] Запуск перевода токенов:")
            logger.info(f"  FROM:         priv - {from_priv[:10]}... | wallet - {from_acc.address[:10]}...")
            logger.info(f"  TO:           {'priv - ' + to_priv[:10] + '... | ' if to_priv else ''}wallet - {to_address[:10]}...")
            logger.info(f"  Сеть:         {network}")
            logger.info(f"  Токен:        {token_symbol_actual} ({token_addr_display})")
            logger.info(f"  Decimals:     {token_decimals}")
            logger.info("-"*61)

        # Проверяем баланс токена отправителя (с реконнектом при сбое RPC).
        # Для нативного — баланс через eth.get_balance + sanity-check на 0;
        # для ERC-20 — balanceOf на контракте токена с реконнектом.
        try:
            if is_native:
                token_balance, w3, session = _get_native_balance_with_reconnect(
                    w3, session, from_acc.address, network, proxies,
                    used_rpc=used_rpc, used_proxy=used_proxy,
                )
                # Если первый RPC показал 0, перепроверяем на другом RPC.
                # Защищает от stale-нулевых ответов лагающих нод.
                token_balance, w3, session = _verify_zero_native_balance(
                    token_balance, w3, session, from_acc.address, network, proxies,
                    used_rpc, used_proxy,
                )
            else:
                token_balance, w3, session = _get_balance_with_reconnect(
                    w3, session, token_address, from_acc.address, network, proxies
                )
        except Exception as e:
            err = f"ошибка получения баланса токена (RPC недоступен): {e}"
            _log(err, status="error")
            _update_token_task(task_id, status="network_error", error_message=err)
            update_token_stats(success=False, error_msg=err)
            return

        if token_balance == 0:
            error_msg = f"баланс токена {token_symbol_actual} = 0"
            _log(error_msg, status="error")
            _update_token_task(
                task_id,
                status="insufficient_token_balance",
                error_message=f"Баланс токена {token_symbol_actual} равен 0 на {from_acc.address}",
            )
            update_token_stats(success=False, error_msg=error_msg)
            return

        # Рассчитываем количество токенов для отправки.
        # Неразобранный transfer_amount — это опечатка в data/data.csv, а не повод
        # отправить весь баланс: кошелёк пропускаем с явной ошибкой.
        try:
            amount_from, amount_to, amount_type = parse_amount_range(amount)
        except ValueError as e:
            error_msg = f"некорректный transfer_amount='{amount}': {e}"
            _log(error_msg, status="error")
            _update_token_task(
                task_id, status="failed",
                error_message=f"[{from_acc.address[:10]}…] {error_msg}",
            )
            update_token_stats(success=False, error_msg=error_msg)
            return

        # Итоговую сумму логируем всегда (в т.ч. в многопоточном режиме) —
        # пользователь должен видеть, как именно понят transfer_amount, до отправки.
        if amount_type == 'PERCENT':
            percent = random.uniform(amount_from, amount_to)
            send_amount_raw = int(token_balance * percent / 100)
            _log(f"сумма: {percent:.2f}% от баланса {token_symbol_actual} (transfer_amount='{amount}')")
        else:
            amount_tokens = random.uniform(amount_from, amount_to)
            amount_tokens = apply_trim_to_amount(amount_tokens)
            send_amount_raw = int(amount_tokens * (10 ** token_decimals))
            _log(f"сумма: {amount_tokens:.6f} {token_symbol_actual} (transfer_amount='{amount}')")

        if send_amount_raw > token_balance:
            send_amount_raw = token_balance
            _log(
                "запрошенное количество больше баланса — будет отправлен весь баланс",
                status="warning",
            )

        if send_amount_raw <= 0:
            error_msg = (
                f"расчётная сумма = 0 (balance={token_balance}, amount='{amount}')"
            )
            _log(error_msg, status="error")
            _update_token_task(
                task_id, status="insufficient_token_balance",
                error_message=f"[{from_acc.address[:10]}…] {error_msg}",
            )
            update_token_stats(success=False, error_msg=error_msg)
            return

        send_amount_formatted = send_amount_raw / (10 ** token_decimals)

        # ── Корректный расчёт газа ───────────────────────────────────────────
        # 1) gas_limit:
        #    - для ERC-20: estimate_gas от реального transfer() вызова
        #    - для нативного: 21000 (стандарт plain-send) * GAS_LIMIT_MULTIPLIER
        # 2) max_fee_per_gas / priority_fee — EIP-1559 если поддерживается
        # 3) для ERC-20 проверяем native_balance >= gas_cost;
        #    для нативного — token_balance == native_balance, и газ
        #    отъедается из того же баланса, поэтому проверка строже:
        #    send_amount + gas_cost <= balance.
        max_fee, max_priority_fee, use_eip1559 = _compute_gas_fees(w3)

        if is_native:
            token_contract = None
            gas_limit = int(21000 * GAS_LIMIT_MULTIPLIER_TOKEN)
        else:
            token_contract = w3.eth.contract(
                address=Web3.to_checksum_address(token_address), abi=ERC20_ABI
            )
            gas_limit = _estimate_gas_limit(
                w3, token_contract, from_acc.address, to_address, send_amount_raw
            )

        estimated_gas_cost_wei = gas_limit * max_fee
        eth_balance = w3.eth.get_balance(from_acc.address)

        # Для нативного газ списывается из того же баланса, что отправляем.
        # Если send_amount + gas > balance — клипуем send_amount до (balance - gas).
        if is_native and send_amount_raw + estimated_gas_cost_wei > eth_balance:
            clipped = eth_balance - estimated_gas_cost_wei
            if clipped <= 0:
                short_msg = (
                    f"недостаточно баланса на отправку + газ: "
                    f"balance={w3.from_wei(eth_balance, 'ether'):.8f} "
                    f"< gas={w3.from_wei(estimated_gas_cost_wei, 'ether'):.8f} "
                    f"{token_symbol_actual}"
                )
                _log(short_msg, status="error")
                _update_token_task(
                    task_id, status="insufficient_balance",
                    error_message=f"[{from_acc.address[:10]}…] {short_msg}",
                    native_balance_wei=str(eth_balance),
                    required_gas_wei=str(estimated_gas_cost_wei),
                    gas_limit=gas_limit,
                    max_fee_per_gas_wei=str(max_fee),
                )
                update_token_stats(success=False, error_msg=short_msg)
                return
            send_amount_raw = clipped
            send_amount_formatted = send_amount_raw / (10 ** token_decimals)
            if not MULTI_THREADING_TOKEN:
                logger.warning(
                    f"⚠️ Сумма уменьшена под газ: send={w3.from_wei(send_amount_raw, 'ether'):.8f} "
                    f"{token_symbol_actual}, gas≈{w3.from_wei(estimated_gas_cost_wei, 'ether'):.8f}"
                )

        if not MULTI_THREADING_TOKEN:
            logger.info(
                f"  Gas:          limit={gas_limit}, "
                f"maxFee={w3.from_wei(max_fee, 'gwei'):.6f} gwei "
                f"({'EIP-1559' if use_eip1559 else 'legacy'}), "
                f"стоимость≈{w3.from_wei(estimated_gas_cost_wei, 'ether'):.8f} {get_network_symbol(network)}"
            )

        # Для ERC-20 баланса нативного должно хватить только на газ;
        # для нативного эту проверку уже сделали выше (через клипинг).
        if not is_native and eth_balance < estimated_gas_cost_wei:
            short_msg = (
                f"недостаточно газа: "
                f"{w3.from_wei(eth_balance, 'ether'):.8f} {get_network_symbol(network)} < "
                f"{w3.from_wei(estimated_gas_cost_wei, 'ether'):.8f} {get_network_symbol(network)} "
                f"(gas_limit={gas_limit}, maxFee={w3.from_wei(max_fee, 'gwei'):.4f} gwei)"
            )
            _log(short_msg, status="error")
            _update_token_task(
                task_id,
                status="insufficient_balance",
                error_message=f"[{from_acc.address[:10]}…] {short_msg}",
                native_balance_wei=str(eth_balance),
                required_gas_wei=str(estimated_gas_cost_wei),
                gas_limit=gas_limit,
                max_fee_per_gas_wei=str(max_fee),
                amount_sent=f"{send_amount_formatted:.8f}",
            )
            update_token_stats(success=False, error_msg=short_msg)
            return

        _update_token_task(
            task_id,
            native_balance_wei=str(eth_balance),
            required_gas_wei=str(estimated_gas_cost_wei),
            gas_limit=gas_limit,
            max_fee_per_gas_wei=str(max_fee),
            amount_sent=f"{send_amount_formatted:.8f}",
        )

        # Прямой перевод токенов
        nonce = get_nonce_safe(w3, from_acc.address)
        if nonce is None:
            _log("не удалось получить nonce", status="error")
            _update_token_task(
                task_id, status="failed",
                error_message=f"Не удалось получить nonce для {from_acc.address}",
            )
            return

        # token_contract / gas_limit / max_fee — уже посчитаны выше
        fee_params = _build_fee_params(max_fee, max_priority_fee, use_eip1559)
        if is_native:
            # Plain native transfer — без data, просто to + value.
            tx_data = {
                'from': Web3.to_checksum_address(from_acc.address),
                'to': Web3.to_checksum_address(to_address),
                'value': send_amount_raw,
                'nonce': nonce,
                'chainId': w3.eth.chain_id,
                'gas': gas_limit,
                **fee_params,
            }
        else:
            tx_data = token_contract.functions.transfer(
                Web3.to_checksum_address(to_address),
                send_amount_raw
            ).build_transaction({
                'from': Web3.to_checksum_address(from_acc.address),
                'nonce': nonce,
                'chainId': w3.eth.chain_id,
                'gas': gas_limit,
                **fee_params,
            })

        # Отправляем транзакцию
        tx_hash = None
        tx_hash_hex = None
        send_error = None
        for attempt in range(TX_SEND_ATTEMPTS):
            try:
                signed_tx = w3.eth.account.sign_transaction(tx_data, from_priv)
                if not MULTI_THREADING_TOKEN:
                    logger.info(f"[{dt_str}] Отправка токенов {token_symbol_actual}...")

                tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                tx_hash_hex = w3.to_hex(tx_hash)

                if not MULTI_THREADING_TOKEN:
                    logger.success(f"✅ Успешно отправлено {send_amount_formatted:.6f} {token_symbol_actual}. Tx hash: {tx_hash_hex}")

                break
            except Exception as e:
                send_error = str(e)
                _log(
                    f"ошибка отправки tx (попытка {attempt+1}/{TX_SEND_ATTEMPTS}): {e}",
                    status="error",
                )
                if attempt == TX_SEND_ATTEMPTS - 1:
                    update_token_stats(success=False, error_msg=f"Ошибка отправки токенов: {e}")
                    if TELEGRAM_LOG_LEVEL_transfer_token == 2:
                        pass
                tx_data['nonce'] += 1
                time.sleep(3)
        else:
            err = f"не удалось отправить tx после {TX_SEND_ATTEMPTS} попыток: {send_error}"
            _log(err, status="error")
            _update_token_task(task_id, status="failed", error_message=err)
            return

        # Ждем подтверждения
        if not MULTI_THREADING_TOKEN:
            logger.info("Ожидание подтверждения транзакции...")

        tx_status_final = None
        time.sleep(WHAITE_TRANSACTION_PENDING)
        for attempt in range(WHAITE_TRANSACTION_PENDING_COUNT):
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                if receipt and receipt.status == 1:
                    _log(
                        f"✅ {send_amount_formatted:.6f} {token_symbol_actual} → "
                        f"{explorer_url}{tx_hash_hex}",
                        status="success",
                    )
                    tx_status_final = "completed"
                    break
                elif receipt and receipt.status == 0:
                    _log(
                        f"❌ tx reverted → {explorer_url}{tx_hash_hex}",
                        status="error",
                    )
                    tx_status_final = "failed"
                    break
            except Exception as e:
                if not MULTI_THREADING_TOKEN:
                    logger.warning(f"⏳ Транзакция в ожидании (попытка {attempt+1}/{WHAITE_TRANSACTION_PENDING_COUNT}): {e}")
            time.sleep(WHAITE_TRANSACTION_PENDING)
        else:
            _log(
                f"⏱ pending после {WHAITE_TRANSACTION_PENDING_COUNT} попыток: "
                f"{explorer_url}{tx_hash_hex}",
                status="error",
            )

        # Успех — ТОЛЬКО подтверждённая транзакция со status == 1.
        # Реверт и «висит в pending» не двигают токены, поэтому не должны попадать
        # ни в result-CSV, ни в счётчик успешных: иначе CSV расходится с ончейном
        # и с БД (там уже пишется реальный tx_status_final).
        succeeded = (tx_status_final == "completed")

        if succeeded:
            append_token_result_csv({
                "datetime": dt_str,
                "from_wallet": from_priv,
                "from_address": from_acc.address,
                "to_wallet": to_wallet_value,
                "to_address": to_address,
                "token_symbol": token_symbol_actual,
                "token_address": token_address,
                "amount_sent": send_amount_formatted,
                "tx_hash": tx_hash_hex,
                "explorer_link": f"{explorer_url}{tx_hash_hex}",
            })
            update_token_stats(success=True, amount=send_amount_formatted, tx_hash=tx_hash_hex)
        else:
            if tx_status_final == "failed":
                fail_reason = f"tx отклонена сетью (reverted): {tx_hash_hex}"
            else:
                fail_reason = (
                    f"tx не подтверждена за {WHAITE_TRANSACTION_PENDING_COUNT} попыток: {tx_hash_hex}"
                )
            update_token_stats(success=False, error_msg=fail_reason)

        _update_token_task(
            task_id,
            status=tx_status_final or "pending",
            tx_hash=tx_hash_hex,
            explorer_link=f"{explorer_url}{tx_hash_hex}",
        )

        # Финальный итоговый вывод (баланс получателя — best-effort, не критично)
        to_token_balance_formatted = None
        try:
            if is_native:
                to_token_balance = w3.eth.get_balance(Web3.to_checksum_address(to_address))
            else:
                to_token_balance = get_token_balance(w3, token_address, to_address)
            to_token_balance_formatted = to_token_balance / (10 ** token_decimals)
        except Exception as e:
            logger.warning(f"Не удалось прочитать итоговый баланс получателя: {e}")

        # Итоговый «зелёный» блок только для реально прошедшей транзакции —
        # для реверта/pending он вводил бы в заблуждение.
        if not MULTI_THREADING_TOKEN and succeeded:
            logger.success("=" * 60)
            logger.success(f"{explorer_url}{tx_hash_hex}")
            logger.success(f"from_wallet ({from_acc.address}) - {send_amount_formatted:.6f} {token_symbol_actual}")
            if to_token_balance_formatted is not None:
                logger.success(f"Баланс to_wallet ({to_address}) по завершению - {to_token_balance_formatted:.6f} {token_symbol_actual}")
            logger.success("=" * 60 + "\n")

    except Exception as e:
        _log(f"внутренняя ошибка: {type(e).__name__}: {e}", status="error")
        update_token_stats(success=False, error_msg=str(e))
        _update_token_task(task_id, status="failed", error_message=str(e))
        if TELEGRAM_LOG_LEVEL_transfer_token == 2:
            pass
    finally:
        if session:
            session.close()

def check_token_balances_for_loop(transfer_data, network, token_address, token_symbol, proxies):
    """Проверяет балансы токенов для принятия решения о продолжении цикла"""
    logger.info(f"🔍 Проверка балансов токенов {token_symbol.upper()}...")
    
    # Генерируем случайные пороговые значения
    min_from_balance = random.uniform(expected_balance_from_wallet_token[0], expected_balance_from_wallet_token[1])
    max_to_balance = random.uniform(expected_balance_to_wallet_token[0], expected_balance_to_wallet_token[1])
    
    logger.info(f"Проверка балансов: минимальный from_wallet = {min_from_balance:.6f} {token_symbol.upper()}, максимальный to_wallet = {max_to_balance:.6f} {token_symbol.upper()}")
    
    valid_wallets = []
    
    for row in transfer_data:
        session = None
        w3 = None
        try:
            # Подключаемся с failover (rpc × proxy)
            try:
                w3, session, _rpc, _proxy = connect_with_failover(network, proxies)
            except Exception as e:
                logger.error(
                    f"❌ {row.get('from_wallet', 'UNKNOWN')[:10]}... — "
                    f"не удалось подключиться к {network}: {e}"
                )
                continue  # пропускаем кошелёк, не дёргаем последующие RPC-вызовы

            from_acc = Account.from_key(row['from_wallet'])
            to_address, _ = get_to_wallet_address(row['to_wallet'])

            # Получаем decimals и балансы.
            # Для нативного — eth.get_balance с ретраями (через _safe_eth_call).
            # Полный реконнект здесь не делаем: при сбое кошелёк просто пропускается
            # в текущем цикле, на следующей итерации loop попробуем заново.
            if _is_native_token(token_address):
                token_decimals = 18
                from_token_balance_raw = _get_native_balance_safe(w3, from_acc.address)
                to_token_balance_raw = _get_native_balance_safe(w3, to_address)
            else:
                token_decimals = get_token_decimals(w3, token_address)
                from_token_balance_raw = get_token_balance(w3, token_address, from_acc.address)
                to_token_balance_raw = get_token_balance(w3, token_address, to_address)

            from_token_balance = from_token_balance_raw / (10 ** token_decimals)
            to_token_balance = to_token_balance_raw / (10 ** token_decimals)

            # Проверяем условия
            if from_token_balance >= min_from_balance and to_token_balance <= max_to_balance:
                valid_wallets.append(row)
                logger.info(f"✅ {from_acc.address[:10]}... - баланс {from_token_balance:.6f} {token_symbol.upper()} (подходит)")
            else:
                logger.warning(f"❌ {from_acc.address[:10]}... - from: {from_token_balance:.6f}, to: {to_token_balance:.6f} {token_symbol.upper()} (не подходит)")

        except Exception as e:
            logger.error(f"❌ Ошибка проверки баланса для {row.get('from_wallet', 'UNKNOWN')[:10]}...: {e}")
        finally:
            if session:
                try: session.close()
                except Exception: pass
    
    return valid_wallets

def process_token_transfers_loop(transfer_data, proxies, network, delay_between, token_address, token_symbol):
    """Циклическая обработка переводов токенов"""
    if not transfer_data:
        logger.error("Нет данных для циклической обработки")
        return
    
    # Инициализируем статистику
    init_token_stats(network, token_symbol, True)

    logger.info(f"🔄 Запуск циклической обработки переводов токенов {token_symbol.upper()}")
    logger.info(f"Количество циклов: {loop_transfer_count_token}")
    logger.info(f"Задержка между циклами: {sleep_time_between_loops_token[0]}-{sleep_time_between_loops_token[1]} сек")
    
    for cycle in range(loop_transfer_count_token):
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🔄 ЦИКЛ {cycle + 1}/{loop_transfer_count_token}")
            logger.info(f"{'='*60}")
            
            # Проверяем балансы и фильтруем подходящие кошельки
            valid_wallets = check_token_balances_for_loop(transfer_data, network, token_address, token_symbol, proxies)
            
            if not valid_wallets:
                logger.warning(f"❌ Цикл {cycle + 1}: Нет подходящих кошельков для отправки токенов")
                _bump_stats(cycles_completed=1)
                if cycle < loop_transfer_count_token - 1:
                    sleep_time = random.randint(sleep_time_between_loops_token[0], sleep_time_between_loops_token[1])
                    logger.info(f"⏳ Ожидание {sleep_time} сек до следующего цикла...")
                    time.sleep(sleep_time)
                continue
            
            logger.info(f"✅ Найдено {len(valid_wallets)} подходящих кошельков для цикла {cycle + 1}")
            
            # Обрабатываем валидные кошельки
            successful_in_cycle = 0
            for idx, row in enumerate(valid_wallets):
                try:
                    logger.info(f"\n[Цикл {cycle + 1}] [{idx+1}/{len(valid_wallets)}] Обработка кошелька {row['from_wallet'][:10]}...")
                    
                    transfer_erc20_tokens(
                        from_priv=row['from_wallet'],
                        to_wallet_value=row['to_wallet'],
                        network=network,
                        token_address=token_address,
                        token_symbol=token_symbol,
                        amount=row['amount'],
                        proxy=None,
                        delay_between=delay_between
                    )
                    
                    successful_in_cycle += 1
                    _bump_stats(wallets_processed=1)

                    # Задержка между транзакциями в цикле
                    if delay_between > 0 and idx < len(valid_wallets) - 1:
                        countdown_timer(delay_between, f"Пауза в цикле {cycle + 1}")

                except Exception as e:
                    logger.error(f"Ошибка обработки кошелька в цикле {cycle + 1}: {e}")
                    _bump_stats(wallets_failed=1)

            _bump_stats(cycles_completed=1)
            logger.info(f"✅ Цикл {cycle + 1} завершен. Успешно обработано: {successful_in_cycle}/{len(valid_wallets)} кошельков")
            
            # Отправляем уведомление о завершении цикла
            if TELEGRAM_LOG_LEVEL_transfer_token >= 1:
            
            # Задержка между циклами
                pass
            if cycle < loop_transfer_count_token - 1:
                sleep_time = random.randint(sleep_time_between_loops_token[0], sleep_time_between_loops_token[1])
                logger.info(f"⏳ Ожидание {sleep_time} сек до следующего цикла...")
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.warning(f"\n⚠️ Прерывание пользователем на цикле {cycle + 1}")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле {cycle + 1}: {e}")
            _bump_stats(cycles_completed=1)
    
    logger.info(f"\n🏁 Циклическая обработка завершена. Выполнено циклов: {TOKEN_TRANSFER_STATS['cycles_completed']}")
    
    # Завершаем статистику
    finalize_token_stats()

def process_token_transfers_normal(transfer_data, proxies, network, delay_between, token_address, token_symbol):
    """Обычная обработка переводов токенов без зацикливания"""
    # Проверяем, включена ли циклическая обработка
    if loop_transfer_enable_token:
        return process_token_transfers_loop(transfer_data, proxies, network, delay_between, token_address, token_symbol)
    
    # Инициализируем статистику
    init_token_stats(network, token_symbol, False)
    
    # Валидация данных
    validation_errors = validate_token_transfer_data(transfer_data)
    if validation_errors:
        logger.error("❌ Ошибки валидации данных:")
        for error in validation_errors:
            logger.error(f"  {error}")
        logger.error("\nИсправьте поля private_key / evm_cex_address / transfer_amount в data/data.csv и запустите снова.")
        return

    logger.success("✅ Валидация данных прошла успешно")
    
    # Обработка в зависимости от режима многопоточности
    if MULTI_THREADING_TOKEN:
        return process_token_transfers_multithreaded(transfer_data, proxies, network, delay_between, token_address, token_symbol)
    
    # Однопоточная обработка
    total_wallets = len(transfer_data)
    for idx, row in enumerate(transfer_data):
        try:
            logger.info(f"\n[{idx+1}/{total_wallets}] Обработка кошелька {row['from_wallet'][:10]}...")
            
            transfer_erc20_tokens(
                from_priv=row['from_wallet'],
                to_wallet_value=row['to_wallet'],
                network=network,
                token_address=token_address,
                token_symbol=token_symbol,
                amount=row['amount'],
                proxy=None,
                delay_between=delay_between
            )
            
            _bump_stats(wallets_processed=1)

            # Задержка между транзакциями
            if delay_between > 0 and idx < total_wallets - 1:
                countdown_timer(delay_between, "Пауза между транзакциями")

        except Exception as e:
            logger.error(f"Ошибка обработки кошелька {row.get('from_wallet', 'UNKNOWN')[:10]}...: {e}")
            _bump_stats(wallets_failed=1)

    # Завершаем статистику
    finalize_token_stats()

def process_token_transfers_multithreaded(transfer_data, proxies, network, delay_between, token_address, token_symbol):
    """Многопоточная обработка переводов токенов.

    Особенности:
      - Стартовая задержка между submit() = max(delay_between, 0.2s) — не выпускаем
        все потоки одновременно, иначе RPC получают burst и режут запросы.
      - Логи каждого worker'а идут через log_wallet_task с [i/N] и адресом,
        чтобы вывод не был перемешанным.
      - finalize_token_stats() вызывается в finally — работает даже при KeyboardInterrupt.
      - Все мутации статистики идут через _bump_stats / update_token_stats (потокобезопасно).
    """
    total = len(transfer_data)
    logger.info(
        f"🚀 Многопоточный запуск: потоки={NUM_THREADS_TOKEN}, "
        f"кошельков={total}, сеть={network}, токен={(token_symbol or '?').upper()}"
    )

    stagger = max(float(delay_between), 0.2)  # минимум 200мс между запусками потоков

    def process_single_transfer(row_with_index):
        idx, row = row_with_index
        try:
            transfer_erc20_tokens(
                from_priv=row['from_wallet'],
                to_wallet_value=row['to_wallet'],
                network=network,
                token_address=token_address,
                token_symbol=token_symbol,
                amount=row['amount'],
                proxy=None,
                delay_between=0,
                task_index=idx + 1,
                task_total=total,
            )
            _bump_stats(wallets_processed=1)
        except Exception as e:
            _bump_stats(wallets_failed=1)
            # transfer_erc20_tokens ловит свои ошибки сам — сюда долетают только
            # необработанные. Логируем с тем же выровненным форматом.
            try:
                from_acc = Account.from_key(row['from_wallet'])
                wallet_short = f"{from_acc.address[:8]}…{from_acc.address[-4:]}"
            except Exception:
                wallet_short = (row.get('from_wallet') or '?')[:10] + "…"
            log_wallet_task(
                wallet_short, idx + 1, total,
                f"необработанное исключение: {type(e).__name__}: {e}",
                status="error",
            )

    try:
        with ThreadPoolExecutor(max_workers=NUM_THREADS_TOKEN) as executor:
            tasks = []
            for idx, row in enumerate(transfer_data):
                if idx > 0:
                    time.sleep(stagger)  # стаггеринг старта потоков
                future = executor.submit(process_single_transfer, (idx, row))
                tasks.append(future)

            for future in as_completed(tasks):
                try:
                    future.result()
                except Exception as e:
                    # Любое необработанное исключение из потока — не валим весь pool
                    logger.error(f"❌ Поток упал с необработанной ошибкой: {e}")
                    _bump_stats(wallets_failed=1)
    finally:
        # Гарантируем финализацию статистики даже при KeyboardInterrupt
        finalize_token_stats()


def choose_token_for_network(network):
    """Выбор токена для конкретной сети через choice"""
    from questionary import select, Choice
    
    network_mapping = {
        '🚀 Base': base,
        '🚀 Arbitrum One': arbitrum,
        '🚀 Avalanche C-Chain': avalanche,
        '🚀 Core DAO': core_dao,
        '🚀 Kava': kava,
        '🚀 Pharos Testnet': pharos_testnet,
    }
    
    network_tokens = network_mapping.get(network)
    if not network_tokens:
        print(f"{Fore.RED}Сеть {network} не поддерживается для переводов токенов{Style.RESET_ALL}")
        return None, None
    
    print(f"\n{Fore.CYAN}Выберите токен для сети {network}:{Style.RESET_ALL}")
    
    # Создаем список выборов для questionary
    choices = []
    tokens_list = list(network_tokens.items())
    
    for symbol, address in tokens_list:
        # Упрощаем отображение символа
        display_symbol = symbol.split(' ')[0].split('(')[0]
        choices.append(Choice(f"{display_symbol} - {symbol}", (display_symbol.lower(), address)))
    
    choices.append(Choice('🔙 Назад', None))
    
    try:
        selected = select(
            "Выберите токен:",
            choices=choices,
            qmark='💎',
            pointer='👉'
        ).ask()
        
        if selected is None:
            return None, None
            
        token_symbol, token_address = selected
        print(f"{Fore.GREEN}Выбран токен: {token_symbol.upper()} ({token_address[:10]}...){Style.RESET_ALL}")
        return token_symbol, token_address
        
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Операция отменена пользователем{Style.RESET_ALL}")
        return None, None

def run_transfer_erc20_tokens():
    """Главная функция запуска модуля переводов ERC-20 токенов"""
    # В логах уже есть счётчик [i/N] (log_wallet_task), поэтому авто-tqdm выключаем —
    # иначе пользователь видит двойную индикацию прогресса.
    set_auto_progress(False)
    try:
        from questionary import Choice, select
        from colorama import Fore
        from modules.data_manager import get_transfer_rows
        from config.modules.cfg_transfer_erc20 import expected_completion_time_token

        print(Fore.GREEN + f"\n\n💎 МОДУЛЬ ПЕРЕВОДОВ ТОКЕНОВ ERC-20")
        print(Fore.GREEN + f"Данные читаются из data/data.csv:")
        print(Fore.YELLOW + f"  private_key      → from_wallet (отправитель)")
        print(Fore.YELLOW + f"  evm_cex_address  → to_wallet (получатель)")
        print(Fore.YELLOW + f"  transfer_amount  → amount (10-20token / 50-80% / 5token / 90%)\n")
        print(Fore.YELLOW + "Токен выбирается из меню при запуске для выбранной сети!")
        
        # Выбор типа сети
        network_type = select(
            "Select network type:",
            choices=[
                Choice('🌐 Mainnet', 'mainnet'),
                Choice('🔧 Testnet', 'testnet'),
                Choice('🔙 Back', 'back')
            ],
            qmark='🛠️',
            pointer='👉'
        ).ask()
        
        if network_type == 'back':
            return
        
        # Ограничиваем выбор сетей только теми, которые поддерживают токены
        supported_networks = [
            '🚀 Base',
            '🚀 Arbitrum One',
            '🚀 Avalanche C-Chain',
            '🚀 Core DAO',
            '🚀 Kava',
            '🚀 Pharos Testnet',
        ]
        if network_type == 'mainnet':
            available_networks = [n for n in supported_networks if 'Testnet' not in n]
        else:
            available_networks = [n for n in supported_networks if 'Testnet' in n]
        
        if not available_networks:
            print(Fore.RED + f"Нет поддерживаемых сетей для типа {network_type}")
            return
        
        # Выбор сети
        network = select(
            "Which network do you want to use for token transfer?",
            choices=[Choice(get_network_display_name(n), n) for n in available_networks] + [Choice('🔙 Back', 'back')],
            qmark='🛠️',
            pointer='👉'
        ).ask()
        
        if network == 'back':
            return
        
        # Выбор токена для выбранной сети
        token_result = choose_token_for_network(network)
        if not token_result or token_result[0] is None:
            return
        
        selected_token_symbol, selected_token_address = token_result

        # Чтение данных из data/data.csv через data_manager
        transfer_data = get_transfer_rows()

        if not transfer_data:
            print(Fore.RED + "Нет данных для перевода: заполните private_key, evm_cex_address и transfer_amount в data/data.csv.")
            return
        
        print(Fore.GREEN + f"Найдено {len(transfer_data)} записей для обработки с токеном {selected_token_symbol.upper()}")
        
        # Получаем прокси и вычисляем задержки
        proxies = get_proxy_list()
        delay_between = expected_completion_time_token / len(transfer_data) if len(transfer_data) > 1 else 0
        
        # Запускаем обработку
        process_token_transfers_normal(transfer_data, proxies, network, delay_between, selected_token_address, selected_token_symbol)
        
    except Exception as e:
        print(Fore.RED + f"Ошибка в модуле переводов токенов ERC-20: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Главная функция модуля"""
    run_transfer_erc20_tokens()

if __name__ == "__main__":
    main()
