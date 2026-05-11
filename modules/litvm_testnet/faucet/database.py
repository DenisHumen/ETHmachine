"""LiteForge faucet — таблицы БД пресета.

Файл БД общий для всего проекта (db/litvm.db), путь и соединение берутся из
modules/litvm_testnet/database.py. Здесь только faucet-specific схемы:
  faucet_wallet_tasks — текущий статус (очищается через "сбросить и начать заново").
  request_history     — заявки с метками отправки и зачисления. НЕ очищается,
                        используется для:
                          (1) расчёта 24h-кулдауна
                          (2) среднего времени зачисления токенов (avg)
"""
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from modules.litvm_testnet.database import DB_PATH, connect as _connect, init_database as _init_project_db

_lock = threading.Lock()


def _migrate_legacy_wallet_tasks(conn) -> None:
    """Раньше таблица называлась `wallet_tasks` — переименовываем в
    `faucet_wallet_tasks` (раз и навсегда, без потери данных)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='wallet_tasks'"
    ).fetchone()
    if not row:
        return
    new_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='faucet_wallet_tasks'"
    ).fetchone()
    if new_exists:
        # Новая таблица уже создана (свежий init успел сделать CREATE).
        # Сливаем строки из старой и удаляем старую.
        conn.execute(
            "INSERT OR IGNORE INTO faucet_wallet_tasks "
            "SELECT * FROM wallet_tasks"
        )
        conn.execute("DROP TABLE wallet_tasks")
    else:
        conn.execute("ALTER TABLE wallet_tasks RENAME TO faucet_wallet_tasks")


def init_database() -> None:
    # Сначала project-level таблицы (vcrcs_cookies), затем faucet-specific.
    _init_project_db()
    with _lock:
        conn = _connect()
        try:
            _migrate_legacy_wallet_tasks(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS faucet_wallet_tasks (
                    address TEXT PRIMARY KEY,
                    account_name TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_tx_hash TEXT,
                    balance_before TEXT,
                    balance_after TEXT,
                    error_message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS request_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    arrived_at TEXT,
                    arrival_seconds REAL,
                    tx_hash TEXT,
                    success INTEGER NOT NULL DEFAULT 0,
                    response TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_addr "
                "ON request_history(address, requested_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_arrival "
                "ON request_history(arrived_at, arrival_seconds)"
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# faucet_wallet_tasks
# ---------------------------------------------------------------------------

def upsert_wallet(address: str, account_name: Optional[str] = None) -> None:
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            conn.execute("""
                INSERT INTO faucet_wallet_tasks (address, account_name, status)
                VALUES (?, ?, 'pending')
                ON CONFLICT(address) DO UPDATE SET
                    account_name = COALESCE(excluded.account_name, faucet_wallet_tasks.account_name),
                    updated_at = CURRENT_TIMESTAMP
            """, (addr, account_name))
            conn.commit()
        finally:
            conn.close()


def update_task(address: str, **fields) -> None:
    if not fields:
        return
    addr = address.lower()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [addr]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE faucet_wallet_tasks SET {sets}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE address = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()


def get_task(address: str) -> Optional[dict]:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM faucet_wallet_tasks WHERE address = ?",
                (address.lower(),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def increment_attempts(address: str) -> int:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE faucet_wallet_tasks SET attempts = attempts + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE address = ?",
                (address.lower(),),
            )
            conn.commit()
            row = conn.execute(
                "SELECT attempts FROM faucet_wallet_tasks WHERE address = ?",
                (address.lower(),),
            ).fetchone()
            return int(row["attempts"]) if row else 0
        finally:
            conn.close()


def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM faucet_wallet_tasks GROUP BY status"
            ).fetchall()
            stats: dict = {r["status"]: r["cnt"] for r in rows}
            total = conn.execute("SELECT COUNT(*) FROM faucet_wallet_tasks").fetchone()[0]
            stats["total"] = total
            return stats
        finally:
            conn.close()


def reset_tasks() -> None:
    """Очистить только статусы задач. История запросов сохраняется."""
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM faucet_wallet_tasks")
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# request_history (never cleared)
# ---------------------------------------------------------------------------

def record_request_sent(address: str, success: bool,
                        tx_hash: Optional[str] = None,
                        response: Optional[str] = None) -> int:
    """Записать факт отправки запроса крана. Возвращает id записи —
    его потом можно обновить через `mark_request_arrived`."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO request_history "
                "(address, requested_at, tx_hash, success, response) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    address.lower(),
                    datetime.now(timezone.utc).isoformat(),
                    tx_hash,
                    1 if success else 0,
                    (response or "")[:500],
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def mark_request_arrived(request_id: int, arrival_seconds: float) -> None:
    """Отметить, что по заявке с id=`request_id` баланс пришёл за `arrival_seconds`."""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE request_history SET arrived_at = ?, arrival_seconds = ? "
                "WHERE id = ?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    float(arrival_seconds),
                    int(request_id),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def last_request_at(address: str) -> Optional[datetime]:
    """Время последней УСПЕШНОЙ заявки (success=1). UTC-aware.

    Только успешные заявки накладывают 24h-кулдаун — если сервер ответил
    "Failed to send transaction", актуального on-chain кулдауна на этот
    адрес нет, и блокировать его локально на 24h нельзя."""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT requested_at FROM request_history "
                "WHERE address = ? AND success = 1 "
                "ORDER BY requested_at DESC LIMIT 1",
                (address.lower(),),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    try:
        return datetime.fromisoformat(row["requested_at"])
    except ValueError:
        return None


def cooldown_remaining(address: str, cooldown_hours: int) -> Optional[timedelta]:
    """Сколько времени осталось до следующего разрешённого запроса. None — кулдаун истёк."""
    last = last_request_at(address)
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - last
    cooldown = timedelta(hours=cooldown_hours)
    if elapsed >= cooldown:
        return None
    return cooldown - elapsed


def avg_arrival_seconds(samples: int = 20) -> Optional[float]:
    """Среднее время зачисления крана по `samples` последним записям с фактом arrival.
    Возвращает None если статистики ещё нет."""
    samples = max(1, int(samples))
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT arrival_seconds FROM request_history "
                "WHERE arrival_seconds IS NOT NULL "
                "ORDER BY id DESC LIMIT ?",
                (samples,),
            ).fetchall()
        finally:
            conn.close()
    if not rows:
        return None
    vals = [float(r["arrival_seconds"]) for r in rows if r["arrival_seconds"] is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)
