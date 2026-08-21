"""
Transfer Wallets to Wallets — прямой перевод нативных токенов между кошельками.
Многопоточность. SQLite для задач и статистики.
"""

import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

import requests
from colorama import Fore
from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound

from config.modules.general_config import (
    DELAY_BETWEEN_ACCOUNTS,
    NUM_THREADS,
    RETRY_COUNT,
    TX_SEND_ATTEMPTS,
    WHAITE_TRANSACTION_PENDING,
    WHAITE_TRANSACTION_PENDING_COUNT,
)
from config.modules.cfg_transfer import (
    MIN_FROM_BALANCE,
    TELEGRAM_LOG_LEVEL_transfer,
    trim_the_number_of_characters,
    trim_the_number_of_characters_enable,
)
from config.networks import get_explorer_url, get_network_rpc_urls, get_network_symbol
from modules.proxy_manager import ProxyManager, parse_proxy
from modules.simple_logger import logger
from modules.ui import ui

# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

DB_DIR = Path(__file__).parent.parent.parent / "db"
DB_FILE = DB_DIR / "transfer_tasks.db"
RESULT_DIR = Path(__file__).parent.parent.parent / "result"

db_lock = Lock()
stats_lock = Lock()


def _ensure_dirs():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)


def _init_db():
    """Создание таблиц transfer_tasks и transfer_statistics."""
    _ensure_dirs()
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS transfer_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_private_key TEXT NOT NULL,
                    from_address TEXT NOT NULL,
                    to_wallet TEXT NOT NULL,
                    to_address TEXT NOT NULL,
                    amount_raw TEXT NOT NULL,
                    amount_wei TEXT,
                    amount_eth TEXT,
                    network TEXT NOT NULL,
                    proxy TEXT,
                    tx_hash TEXT,
                    explorer_link TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    attempts INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS transfer_statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    network TEXT NOT NULL,
                    total_tasks INTEGER DEFAULT 0,
                    completed INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    total_amount_wei TEXT DEFAULT '0',
                    total_amount_eth TEXT DEFAULT '0.0',
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_transfer_status ON transfer_tasks(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_transfer_network ON transfer_tasks(network)")
            conn.commit()


def _get_tasks_by_network(network: str) -> List[Dict]:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM transfer_tasks WHERE network = ? ORDER BY id", (network,)
            ).fetchall()
            return [dict(r) for r in rows]


def _get_pending_tasks(network: str) -> List[Dict]:
    """Задачи, которые нужно обработать в этом запуске.

    'tx_sent' сюда входит намеренно: транзакция уже в сети, но подтверждения
    мы не дождались — такую задачу нужно до-опросить по её же хэшу
    (см. _resume_sent_tx), а не отправлять повторно.
    """
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM transfer_tasks WHERE network = ? AND status IN ('pending', 'failed', 'tx_sent') ORDER BY id",
                (network,),
            ).fetchall()
            return [dict(r) for r in rows]


def _update_task(task_id: int, **kwargs):
    if not kwargs:
        return
    kwargs["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [task_id]
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.execute(f"UPDATE transfer_tasks SET {set_clause} WHERE id = ?", values)
            conn.commit()


def _clear_tasks(network: str):
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.execute("DELETE FROM transfer_tasks WHERE network = ?", (network,))
            conn.commit()


def _create_tasks(rows: List[Dict], network: str, proxies: List[str]):
    """Создать задачи в БД из CSV-строк."""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            for i, row in enumerate(rows):
                from_key = row["from_wallet"].strip()
                to_wallet_raw = row["to_wallet"].strip()
                amount_raw = row["amount"].strip()

                from_address = Account.from_key(from_key).address
                to_address = _resolve_address(to_wallet_raw)

                proxy = proxies[i % len(proxies)] if proxies else None

                conn.execute(
                    """INSERT INTO transfer_tasks
                       (from_private_key, from_address, to_wallet, to_address,
                        amount_raw, network, proxy, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                    (from_key, from_address, to_wallet_raw, to_address, amount_raw, network, proxy),
                )
            conn.commit()


def _get_stats_summary(network: str) -> Dict:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM transfer_tasks WHERE network = ?", (network,))
            total = c.fetchone()[0]
            c.execute(
                "SELECT COUNT(*) FROM transfer_tasks WHERE network = ? AND status = 'completed'",
                (network,),
            )
            completed = c.fetchone()[0]
            c.execute(
                "SELECT COUNT(*) FROM transfer_tasks WHERE network = ? AND status = 'failed'",
                (network,),
            )
            failed = c.fetchone()[0]
            c.execute(
                "SELECT COUNT(*) FROM transfer_tasks WHERE network = ? AND status = 'pending'",
                (network,),
            )
            pending = c.fetchone()[0]
            c.execute(
                "SELECT COUNT(*) FROM transfer_tasks WHERE network = ? AND status = 'tx_sent'",
                (network,),
            )
            unconfirmed = c.fetchone()[0]
            # Суммируем в Python, а не через SUM(): у SQLite INTEGER знаковый 64-битный,
            # и сумма wei больше 2^63 (≈9.2 токена) роняет запрос с 'integer overflow'.
            c.execute(
                "SELECT amount_wei FROM transfer_tasks WHERE network = ? AND status = 'completed'",
                (network,),
            )
            total_wei = 0
            for (raw_wei,) in c.fetchall():
                try:
                    total_wei += int(raw_wei)
                except (TypeError, ValueError):
                    continue  # мусор в колонке не должен ронять всю статистику
            return {
                "total": total,
                "completed": completed,
                "failed": failed,
                "pending": pending,
                "unconfirmed": unconfirmed,
                "total_wei": total_wei,
                "total_eth": total_wei / 10**18 if total_wei else 0.0,
            }


def _save_statistics(network: str, started_at: str):
    stats = _get_stats_summary(network)
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.execute(
                """INSERT INTO transfer_statistics
                   (network, total_tasks, completed, failed, total_amount_wei, total_amount_eth, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    network,
                    stats["total"],
                    stats["completed"],
                    stats["failed"],
                    str(stats["total_wei"]),
                    f"{stats['total_eth']:.8f}",
                    started_at,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════


def _resolve_address(wallet_value: str) -> str:
    """Определить тип (адрес / приватный ключ) и вернуть адрес."""
    wallet_value = wallet_value.strip()
    # Адрес: 0x + 40 hex = 42 символа
    if wallet_value.startswith("0x") and len(wallet_value) == 42:
        try:
            return Web3.to_checksum_address(wallet_value)
        except Exception:
            pass
    # Приватный ключ: 64 hex (без 0x) или 66 (с 0x)
    try:
        acc = Account.from_key(wallet_value)
        return acc.address
    except Exception:
        pass
    # Fallback
    return Web3.to_checksum_address(wallet_value)


def _short_addr(address: str) -> str:
    if len(address) >= 10:
        return f"{address[:6]}...{address[-4:]}"
    return address


def _parse_amount(amount_raw: str) -> Tuple[str, float, float]:
    """
    Парсит строку amount из CSV.
    Возвращает (тип, мин, макс)
    тип: 'percent' или 'eth'

    Правила:
      - "90-100%" или "90-100" (в кавычках, целые числа) → процент
      - 90-100% (с символом %) → процент
      - 0.1-0.2 (десятичные числа без %) → ETH
    """
    raw = amount_raw.strip().strip('"').strip("'").strip()

    is_percent = False
    if raw.endswith("%"):
        is_percent = True
        raw = raw[:-1].strip()

    if "-" in raw:
        parts = raw.split("-", 1)
        lo_str, hi_str = parts[0].strip(), parts[1].strip()
        if hi_str.endswith("%"):
            is_percent = True
            hi_str = hi_str[:-1].strip()
        try:
            lo = float(lo_str)
            hi = float(hi_str)
        except ValueError:
            raise ValueError(f"Невозможно распарсить amount: {amount_raw}")

        if not is_percent:
            if "." in lo_str or "." in hi_str:
                return ("eth", lo, hi)
            else:
                return ("percent", lo, hi)
        return ("percent", lo, hi)
    else:
        val = float(raw)
        if is_percent:
            return ("percent", val, val)
        if "." in raw:
            return ("eth", val, val)
        return ("percent", val, val)


def _apply_trim(amount_eth: float) -> float:
    """Обрезать сумму до случайного количества символов после точки."""
    if not trim_the_number_of_characters_enable:
        return amount_eth
    chars = random.randint(trim_the_number_of_characters[0], trim_the_number_of_characters[1])
    s = f"{amount_eth:.18f}"
    dot_idx = s.index(".")
    trimmed = s[: dot_idx + 1 + chars]
    return float(trimmed)


def _calc_min_from_balance_wei() -> int:
    lo = MIN_FROM_BALANCE[0] if len(MIN_FROM_BALANCE) > 0 else 0
    hi = MIN_FROM_BALANCE[1] if len(MIN_FROM_BALANCE) > 1 else lo
    val = random.uniform(lo, hi)
    return Web3.to_wei(val, "ether")


# ═══════════════════════════════════════════════════════════════════════════════
# WEB3 + PROXY
# ═══════════════════════════════════════════════════════════════════════════════


def _get_web3(rpc_url: str, proxy_str: Optional[str] = None) -> Tuple[Web3, Optional[requests.Session]]:
    """Создать Web3 инстанс с прокси (если задан)."""
    session = None
    if proxy_str:
        proxy_url = parse_proxy(proxy_str)
        if proxy_url:
            session = requests.Session()
            session.proxies = {"http": proxy_url, "https": proxy_url}

    if session:
        from web3 import HTTPProvider

        provider = HTTPProvider(rpc_url, session=session)
        w3 = Web3(provider)
    else:
        w3 = Web3(Web3.HTTPProvider(rpc_url))

    return w3, session


def _get_balance_safe(w3: Web3, address: str, attempts: int = 3) -> int:
    for i in range(attempts):
        try:
            return w3.eth.get_balance(Web3.to_checksum_address(address))
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2)
    return 0


def _get_nonce_safe(w3: Web3, address: str, attempts: int = 3) -> Optional[int]:
    for i in range(attempts):
        try:
            return w3.eth.get_transaction_count(Web3.to_checksum_address(address))
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2)
    return None


def _estimate_gas_safe(w3: Web3, tx: dict, attempts: int = 3) -> int:
    for i in range(attempts):
        try:
            gas = w3.eth.estimate_gas(tx)
            return int(gas * 1.2)
        except Exception:
            if i == attempts - 1:
                return int(21000 * 1.2)
            time.sleep(2)
    return int(21000 * 1.2)


# ═══════════════════════════════════════════════════════════════════════════════
# CORE TRANSFER LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

_completed_counter = 0
_completed_lock = Lock()


def _normalize_tx_hash(tx_hash_hex: str) -> str:
    """Хэш всегда в виде 0x… — так его принимают и RPC, и эксплореры."""
    tx_hash_hex = (tx_hash_hex or "").strip()
    if tx_hash_hex and not tx_hash_hex.startswith("0x"):
        tx_hash_hex = "0x" + tx_hash_hex
    return tx_hash_hex


def _tx_is_broadcast(w3: Web3, tx_hash_hex: str) -> bool:
    """Знает ли сеть про эту транзакцию (мемпул или блок).

    Отвечаем True только при положительном ответе узла: любая другая ситуация
    трактуется как «не отправлено», иначе задача с так и не ушедшей транзакцией
    навсегда застряла бы в статусе tx_sent.
    """
    try:
        return w3.eth.get_transaction(tx_hash_hex) is not None
    except Exception:
        return False


def _poll_tx_receipt(
    tx_hash_hex: str,
    rpc_urls: List[str],
    proxy_str: Optional[str],
    prefix: str,
    w3: Optional[Web3] = None,
) -> Tuple[Optional[Web3], Optional[object]]:
    """Дождаться receipt уже отправленной транзакции.

    После broadcast единственный безопасный «повтор» — опрос того же хэша:
    пересборка и повторная отправка означали бы второй перевод средств.
    Поэтому тут мы только ждём и переживаем падения RPC, переключаясь на
    другой узел. Возвращает (w3, receipt); receipt=None — не дождались.

    w3 — узел, который принял транзакцию: он узнает её раньше остальных,
    поэтому опрос начинаем с него.
    """
    attempts = max(1, WHAITE_TRANSACTION_PENDING_COUNT)
    delay = max(1, WHAITE_TRANSACTION_PENDING)

    for i in range(attempts):
        try:
            if w3 is None:
                w3, _ = _get_web3(random.choice(rpc_urls), proxy_str)
            receipt = w3.eth.get_transaction_receipt(tx_hash_hex)
            if receipt is not None:
                return w3, receipt
        except TransactionNotFound:
            pass  # ещё в мемпуле — ждём дальше
        except Exception as e:
            # Узел отвалился — на следующей итерации возьмём другой RPC.
            logger.warning(f"{prefix} ⚠️ Ошибка опроса receipt: {str(e)[:120]}")
            w3 = None

        if i == 0:
            logger.info(f"{prefix} ⏳ Ожидание подтверждения: {tx_hash_hex}")
        if i < attempts - 1:
            time.sleep(delay)

    return w3, None


def _confirm_sent_tx(
    task_id: int,
    tx_hash_hex: str,
    send_value: int,
    from_address: str,
    to_address: str,
    rpc_urls: List[str],
    proxy_str: Optional[str],
    explorer_url: str,
    symbol: str,
    prefix: str,
    w3: Optional[Web3] = None,
) -> bool:
    """Довести до конца уже отправленную транзакцию — только ожидание, без отправки."""
    global _completed_counter

    full_explorer = f"{explorer_url}{tx_hash_hex}"
    w3, receipt = _poll_tx_receipt(tx_hash_hex, rpc_urls, proxy_str, prefix, w3=w3)

    if receipt is None:
        # Средства, возможно, уже ушли. Статус 'tx_sent' + сохранённый хэш нужны,
        # чтобы следующий запуск дособрал подтверждение, а не отправил перевод дважды.
        err = f"Не дождались подтверждения, tx: {tx_hash_hex}"
        logger.warning(f"{prefix} ⏱️ {err}")
        _update_task(
            task_id,
            status="tx_sent",
            tx_hash=tx_hash_hex,
            explorer_link=full_explorer,
            error_message=err,
        )
        return False

    if receipt.status != 1:
        # Откат нативного перевода средства не двигает, поэтому задачу можно
        # безопасно повторить в следующем запуске.
        err = f"Транзакция откачена (reverted), tx: {tx_hash_hex}"
        logger.error(f"{prefix} ❌ {err}")
        _update_task(
            task_id,
            status="failed",
            tx_hash=tx_hash_hex,
            explorer_link=full_explorer,
            error_message=err,
        )
        return False

    sent_eth = float(Web3.from_wei(send_value, "ether"))

    logger.success(
        f"{prefix} ✅ Подтверждено: {sent_eth:.8f} {symbol} | "
        f"{_short_addr(from_address)} → {_short_addr(to_address)} | "
        f"{full_explorer}"
    )

    # --- Wait for balance on target ---
    if w3 is not None:
        _wait_for_balance_increase(w3, to_address, prefix, symbol)

    # --- Update DB ---
    _update_task(
        task_id,
        status="completed",
        amount_wei=str(send_value),
        amount_eth=f"{sent_eth:.8f}",
        tx_hash=tx_hash_hex,
        explorer_link=full_explorer,
        error_message=None,
    )

    with _completed_lock:
        _completed_counter += 1

    # Telegram
    if TELEGRAM_LOG_LEVEL_transfer >= 2:

        pass
    return True


def _resume_sent_tx(
    task: Dict,
    rpc_urls: List[str],
    explorer_url: str,
    symbol: str,
    prefix: str,
) -> bool:
    """Задача, чья транзакция уже в сети: проверяем её статус, ничего не отправляя."""
    tx_hash_hex = _normalize_tx_hash(task.get("tx_hash") or "")
    try:
        send_value = int(task.get("amount_wei") or 0)
    except (TypeError, ValueError):
        send_value = 0

    logger.info(f"{prefix} 🔁 Транзакция уже отправлена ранее — проверяем статус: {tx_hash_hex}")

    return _confirm_sent_tx(
        task_id=task["id"],
        tx_hash_hex=tx_hash_hex,
        send_value=send_value,
        from_address=task["from_address"],
        to_address=task["to_address"],
        rpc_urls=rpc_urls,
        proxy_str=task.get("proxy"),
        explorer_url=explorer_url,
        symbol=symbol,
        prefix=prefix,
    )


def _process_single_transfer(
    task: Dict,
    rpc_urls: List[str],
    explorer_url: str,
    symbol: str,
    total_tasks: int,
    task_index: int,
):
    """Обработка одного перевода (вызывается из потока)."""
    global _completed_counter
    task_id = task["id"]
    from_key = task["from_private_key"]
    from_address = task["from_address"]
    to_address = task["to_address"]
    amount_raw = task["amount_raw"]
    proxy_str = task["proxy"]
    proxy_display = proxy_str.split("@")[-1] if proxy_str and "@" in proxy_str else (proxy_str or "direct")

    prefix = f"[{task_index}/{total_tasks}]"

    # Транзакция этой задачи уже в сети (прошлый запуск / аварийное завершение).
    # Пересобирать и отправлять заново нельзя — это дубль перевода средств.
    if task.get("status") == "tx_sent" and (task.get("tx_hash") or "").strip():
        return _resume_sent_tx(task, rpc_urls, explorer_url, symbol, prefix)

    gas_bump = 10000000000  # стартовый запас 10 gwei, растёт при insufficient funds
    # Заполняется сразу после broadcast. Непустое значение — стоп-сигнал для
    # retry-цикла: пересылать уже отправленную транзакцию нельзя.
    broadcast: Optional[Tuple[str, int, Web3]] = None

    for attempt in range(1, RETRY_COUNT + 1):
        rpc_url = random.choice(rpc_urls)
        try:
            _update_task(task_id, status="in_progress", attempts=task.get("attempts", 0) + 1)

            logger.info(
                f"{prefix} 🚀 Перевод: {_short_addr(from_address)} → {_short_addr(to_address)} "
                f"| proxy: {proxy_display} | попытка {attempt}/{RETRY_COUNT}"
            )

            w3, session = _get_web3(rpc_url, proxy_str)
            if not w3.is_connected():
                raise ConnectionError(f"Не удалось подключиться к RPC: {rpc_url}")

            chain_id = w3.eth.chain_id
            balance = _get_balance_safe(w3, from_address)
            balance_eth = float(w3.from_wei(balance, "ether"))

            if balance == 0:
                logger.warning(f"{prefix} ⚠️ Нулевой баланс на {_short_addr(from_address)} — пропускаем")
                _update_task(task_id, status="insufficient_balance", error_message="Нулевой баланс")
                return False

            # --- Parse amount ---
            amount_type, lo, hi = _parse_amount(amount_raw)

            if amount_type == "percent":
                percent = random.uniform(lo, hi)
                send_value = int(balance * percent / 100)
                logger.info(
                    f"{prefix} 💰 Баланс: {balance_eth:.6f} {symbol} | "
                    f"Отправка: {percent:.1f}% = {float(w3.from_wei(send_value, 'ether')):.8f} {symbol}"
                )
            else:
                amount_eth_val = random.uniform(lo, hi)
                amount_eth_val = _apply_trim(amount_eth_val)
                send_value = w3.to_wei(amount_eth_val, "ether")
                logger.info(
                    f"{prefix} 💰 Баланс: {balance_eth:.6f} {symbol} | "
                    f"Отправка: {amount_eth_val:.8f} {symbol}"
                )

            # --- Build tx for gas estimation ---
            from_checksum = Web3.to_checksum_address(from_address)
            to_checksum = Web3.to_checksum_address(to_address)
            nonce = _get_nonce_safe(w3, from_address)
            if nonce is None:
                raise ValueError("Не удалось получить nonce")

            gas_price = w3.eth.gas_price

            # Detect EIP-1559 support
            try:
                latest_block = w3.eth.get_block("latest")
                base_fee = latest_block.get("baseFeePerGas")
            except Exception:
                base_fee = None

            is_eip1559 = base_fee is not None

            # Gas: простой ETH-перевод всегда 21000 gas
            gas_limit = 21000
            min_keep = _calc_min_from_balance_wei()

            if is_eip1559:
                max_priority_fee = max(w3.to_wei(0.001, "gwei"), int(gas_price * 0.01))
                # maxFeePerGas = текущий gas_price + priority (точный расчёт)
                max_fee_per_gas = gas_price + max_priority_fee
                gas_cost = gas_limit * max_fee_per_gas
            else:
                legacy_gas_price = int(gas_price * 1.1)
                gas_cost = gas_limit * legacy_gas_price

            # gas_bump увеличивается на 10 gwei при каждой ошибке insufficient funds
            total_reserved = gas_cost + min_keep + gas_bump

            # --- If sending more than balance allows, recalculate ---
            if send_value + total_reserved > balance:
                send_value = balance - total_reserved
                if send_value <= 0:
                    err = (
                        f"Недостаточно средств: баланс {balance_eth:.8f} {symbol}, "
                        f"комиссия ~{float(w3.from_wei(gas_cost, 'ether')):.8f} {symbol}"
                    )
                    logger.warning(f"{prefix} ⚠️ {err} — пропускаем")
                    _update_task(task_id, status="insufficient_balance", error_message=err)
                    return False
                logger.warning(
                    f"{prefix} ⚠️ Сумма скорректирована с учётом газа: "
                    f"{float(w3.from_wei(send_value, 'ether')):.8f} {symbol}"
                )

            # Apply trim for non-percentage fixed ETH amounts only
            if amount_type == "eth":
                trimmed_eth = _apply_trim(float(w3.from_wei(send_value, "ether")))
                new_send_value = w3.to_wei(trimmed_eth, "ether")
                if new_send_value + total_reserved <= balance:
                    send_value = new_send_value

            # --- Build final transaction ---
            if is_eip1559:
                tx = {
                    "type": 0x2,
                    "chainId": chain_id,
                    "from": from_checksum,
                    "to": to_checksum,
                    "value": send_value,
                    "nonce": nonce,
                    "gas": gas_limit,
                    "maxFeePerGas": max_fee_per_gas,
                    "maxPriorityFeePerGas": max_priority_fee,
                }
            else:
                tx = {
                    "chainId": chain_id,
                    "from": from_checksum,
                    "to": to_checksum,
                    "value": send_value,
                    "nonce": nonce,
                    "gas": gas_limit,
                    "gasPrice": legacy_gas_price,
                }

            # --- Sign & Send ---
            account = Account.from_key(from_key)
            signed = account.sign_transaction(tx)
            raw = signed.rawTransaction if hasattr(signed, 'rawTransaction') else signed.raw_transaction
            # Хэш известен ещё до broadcast — он нужен, чтобы опознать транзакцию,
            # если ответ узла потеряется уже после того, как тот её принял.
            local_hash = _normalize_tx_hash(signed.hash.hex()) if hasattr(signed, "hash") else ""

            try:
                tx_hash_hex = _normalize_tx_hash(w3.eth.send_raw_transaction(raw).hex())
            except Exception:
                # Отправка «упала», но транзакция могла уйти в сеть (оборванный
                # ответ, таймаут HTTP). Повторить её — значит перевести средства
                # дважды, поэтому сначала спрашиваем узел, знает ли он наш хэш.
                if local_hash and _tx_is_broadcast(w3, local_hash):
                    logger.warning(
                        f"{prefix} ⚠️ Ответ RPC потерян, но транзакция уже в сети: {local_hash}"
                    )
                    tx_hash_hex = local_hash
                else:
                    raise

            broadcast = (tx_hash_hex, send_value, w3)
            logger.info(f"{prefix} 📤 TX отправлена: {tx_hash_hex}")

            # Факт отправки фиксируем ДО ожидания: если процесс прервётся или
            # подтверждения не дождёмся, следующий запуск до-опросит этот же
            # хэш (_resume_sent_tx) вместо повторного перевода средств.
            _update_task(
                task_id,
                status="tx_sent",
                amount_wei=str(send_value),
                amount_eth=f"{float(w3.from_wei(send_value, 'ether')):.8f}",
                tx_hash=tx_hash_hex,
                explorer_link=f"{explorer_url}{tx_hash_hex}",
                error_message=None,
            )
            break  # дальше только ожидание — вне retry-цикла

        except KeyboardInterrupt:
            # Статус 'failed' ставим только если денег точно не отправляли:
            # иначе следующий запуск счёл бы задачу неотправленной и перевёл бы
            # средства второй раз.
            if broadcast is None:
                _update_task(task_id, status="failed", error_message="Прервано пользователем")
            raise
        except Exception as e:
            err_msg = str(e)[:200]
            logger.error(f"{prefix} ❌ Ошибка (попытка {attempt}/{RETRY_COUNT}): {err_msg}")

            if broadcast is not None:
                # Сюда можно попасть только если упала запись в БД уже после
                # broadcast. Повторять отправку нельзя ни при каких условиях.
                logger.error(f"{prefix} ⛔ Транзакция уже отправлена — повтор отменён")
                return False

            # При insufficient funds увеличиваем вычет на 10 gwei для следующей попытки
            if "insufficient funds" in err_msg.lower():
                gas_bump += w3.to_wei(10, "gwei")
                logger.info(f"{prefix} 💡 Увеличен запас газа на +10 gwei (итого +{gas_bump} wei)")

            if attempt < RETRY_COUNT:
                sleep_time = random.uniform(3, 8)
                logger.info(f"{prefix} 🔄 Повтор через {sleep_time:.1f}с...")
                time.sleep(sleep_time)
            else:
                _update_task(task_id, status="failed", error_message=err_msg)
                logger.error(f"{prefix} 💀 Все попытки исчерпаны для {_short_addr(from_address)}")

                if TELEGRAM_LOG_LEVEL_transfer >= 1:
                    pass
                return False

    if broadcast is None:
        return False

    # Ожидание подтверждения живёт вне retry-цикла: транзакция уже в сети, и
    # никакой исход ожидания не даёт права отправить её заново.
    tx_hash_hex, send_value, w3 = broadcast
    return _confirm_sent_tx(
        task_id=task_id,
        tx_hash_hex=tx_hash_hex,
        send_value=send_value,
        from_address=from_address,
        to_address=to_address,
        rpc_urls=rpc_urls,
        proxy_str=proxy_str,
        explorer_url=explorer_url,
        symbol=symbol,
        prefix=prefix,
        w3=w3,
    )


def _wait_for_balance_increase(w3: Web3, address: str, prefix: str, symbol: str):
    """Ждём появления баланса на целевом кошельке."""
    logger.info(f"{prefix} 📥 Ожидание поступления на {_short_addr(address)}...")
    for i in range(WHAITE_TRANSACTION_PENDING_COUNT):
        try:
            bal = w3.eth.get_balance(Web3.to_checksum_address(address))
            if bal > 0:
                logger.success(
                    f"{prefix} 📥 Баланс получен на {_short_addr(address)}: "
                    f"{float(w3.from_wei(bal, 'ether')):.8f} {symbol}"
                )
                return
        except Exception:
            pass
        time.sleep(WHAITE_TRANSACTION_PENDING)
    logger.warning(f"{prefix} ⏱️ Таймаут ожидания баланса на {_short_addr(address)}")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════


def run_transfer(transfer_data: List[Dict], network: str):
    """
    Главная точка входа.
    transfer_data — список словарей с ключами: from_wallet, to_wallet, amount
    network — полное имя сети (с эмодзи), напр. '🚀 Base'
    """
    global _completed_counter
    _completed_counter = 0

    _init_db()

    rpc_urls = get_network_rpc_urls(network)
    explorer_url = get_explorer_url(network)
    symbol = get_network_symbol(network)

    if not rpc_urls:
        logger.error(f"Нет RPC для сети {network}")
        return

    # --- Check existing tasks in DB ---
    existing = _get_tasks_by_network(network)

    if existing:
        all_done = all(t["status"] == "completed" for t in existing)
        if all_done:
            logger.info("✅ Все предыдущие задачи выполнены. Очистка для нового запуска...")
            _clear_tasks(network)
            existing = []
        else:
            # Список статусов совпадает с _get_pending_tasks, иначе счётчик
            # разойдётся с тем, что реально будет обработано.
            pending_count = sum(1 for t in existing if t["status"] in ("pending", "failed", "tx_sent"))
            completed_count = sum(1 for t in existing if t["status"] == "completed")

            ui.print_lines(ui.panel(
                f"Незавершённые задачи · {network}",
                [f"✅ Выполнено: {completed_count}",
                 f"⏳ Осталось:  {pending_count}"],
                color=ui.theme.FG_WARN,
            ))

            choice = ui.menu("Что делать с существующими задачами?", [
                ("▶️ Продолжить выполнение", "continue"),
                ("🗑️ Очистить и начать заново", "clear"),
                ("❌ Отмена", "cancel"),
            ])

            if choice in (None, "cancel"):
                return
            elif choice == "clear":
                _clear_tasks(network)
                existing = []
            # else: continue — используем существующие задачи

    # --- Create new tasks if needed ---
    if not existing:
        proxies = ProxyManager.load_proxies()
        logger.info(f"📋 Загружено прокси: {len(proxies)}")
        _create_tasks(transfer_data, network, proxies)
        logger.success(f"📋 Создано {len(transfer_data)} задач в БД")

    # --- Get tasks to process ---
    tasks = _get_pending_tasks(network)
    if not tasks:
        logger.info("✅ Нет задач для выполнения.")
        return

    total = len(tasks)
    all_tasks_total = len(_get_tasks_by_network(network))

    print()
    print(Fore.CYAN + "═" * 60)
    print(Fore.CYAN + f"  🔄 Transfer Wallets to Wallets")
    print(Fore.CYAN + f"  📡 Сеть: {network} ({symbol})")
    print(Fore.CYAN + f"  📋 Задач к выполнению: {total} из {all_tasks_total}")
    print(Fore.CYAN + f"  🧵 Потоков: {min(NUM_THREADS, total)}")
    print(Fore.CYAN + f"  ⏱️  Задержка между потоками: {DELAY_BETWEEN_ACCOUNTS[0]}-{DELAY_BETWEEN_ACCOUNTS[1]}с")
    min_time_sec = total * DELAY_BETWEEN_ACCOUNTS[0]
    max_time_sec = total * DELAY_BETWEEN_ACCOUNTS[1]
    def _fmt_time(sec):
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}ч {m}мин"
        return f"{m}мин {s}с"
    print(Fore.CYAN + f"  🕐 Примерное время: {_fmt_time(min_time_sec)} — {_fmt_time(max_time_sec)}")
    print(Fore.CYAN + "═" * 60)
    print()

    started_at = datetime.now().isoformat()

    if TELEGRAM_LOG_LEVEL_transfer >= 1:

    # --- Multithreaded execution ---
        pass
    max_workers = min(NUM_THREADS, total)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for i, task in enumerate(tasks):
            if i > 0:
                delay = random.uniform(DELAY_BETWEEN_ACCOUNTS[0], DELAY_BETWEEN_ACCOUNTS[1])
                time.sleep(delay)

            future = executor.submit(
                _process_single_transfer,
                task=task,
                rpc_urls=rpc_urls,
                explorer_url=explorer_url,
                symbol=symbol,
                total_tasks=all_tasks_total,
                task_index=i + 1,
            )
            futures[future] = task

        for future in as_completed(futures):
            try:
                future.result()
            except KeyboardInterrupt:
                logger.warning("⚠️ Прерывание по Ctrl+C...")
                executor.shutdown(wait=False, cancel_futures=True)
                break
            except Exception as e:
                logger.error(f"Необработанная ошибка потока: {e}")

    # --- Statistics ---
    # Переводы уже выполнены — сбой в подсчёте статистики не должен выглядеть
    # как провал всего запуска.
    try:
        _save_statistics(network, started_at)
        stats = _get_stats_summary(network)
        _print_final_stats(stats, symbol, network, started_at)
    except Exception as e:
        logger.error(f"Не удалось собрать финальную статистику: {e}")

    # Telegram final report
    if TELEGRAM_LOG_LEVEL_transfer >= 1:


        pass
def _print_final_stats(stats: Dict, symbol: str, network: str, started_at: str):
    """Вывести финальную статистику в терминал."""
    duration = datetime.now() - datetime.fromisoformat(started_at)
    minutes = int(duration.total_seconds() // 60)
    seconds = int(duration.total_seconds() % 60)

    print()
    print(Fore.GREEN + "═" * 60)
    print(Fore.GREEN + "  📊 ФИНАЛЬНАЯ СТАТИСТИКА")
    print(Fore.GREEN + "═" * 60)
    print(Fore.GREEN + f"  📡 Сеть: {network}")
    print(Fore.GREEN + f"  ✅ Успешно:    {stats['completed']}/{stats['total']}")
    if stats["failed"] > 0:
        print(Fore.RED + f"  ❌ Ошибок:     {stats['failed']}/{stats['total']}")
    else:
        print(Fore.GREEN + f"  ❌ Ошибок:     0/{stats['total']}")
    if stats["pending"] > 0:
        print(Fore.YELLOW + f"  ⏳ Осталось:   {stats['pending']}")
    # Отправленные, но не подтверждённые: средства, скорее всего, ушли — их
    # нельзя молча приравнивать к ошибкам, иначе пользователь запустит перевод
    # повторно. Следующий запуск до-опросит эти транзакции по их хэшам.
    if stats.get("unconfirmed", 0) > 0:
        print(Fore.YELLOW + f"  ⏱️  Без подтверждения: {stats['unconfirmed']} (проверьте tx в эксплорере)")
    print(Fore.GREEN + f"  💰 Переведено: {stats['total_eth']:.8f} {symbol}")
    print(Fore.GREEN + f"  ⏱️  Время:      {minutes}м {seconds}с")
    success_rate = (stats["completed"] / stats["total"] * 100) if stats["total"] > 0 else 0
    print(Fore.GREEN + f"  📈 Успешность: {success_rate:.1f}%")
    print(Fore.GREEN + "═" * 60)
    print()
