"""Alchemy Base Sepolia faucet — SQLite БД.

Структура зеркальная Ghost Faucet:
  wallet_tasks      — текущий статус задачи (очищается через "очистить и начать заново")
  request_history   — история отправленных заявок (НЕ очищается, нужна для
                      контроля 24-часового кулдауна даже после reset_tasks).
"""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "db" / "fhenix_alchemy_base_sepolia.db"

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wallet_tasks (
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
                    tx_hash TEXT,
                    success INTEGER NOT NULL DEFAULT 0,
                    response TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_addr "
                "ON request_history(address, requested_at DESC)"
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# wallet_tasks
# ---------------------------------------------------------------------------

def upsert_wallet(address: str, account_name: str | None = None) -> None:
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            conn.execute("""
                INSERT INTO wallet_tasks (address, account_name, status)
                VALUES (?, ?, 'pending')
                ON CONFLICT(address) DO UPDATE SET
                    account_name = COALESCE(excluded.account_name, wallet_tasks.account_name),
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
                f"UPDATE wallet_tasks SET {sets}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE address = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()


def get_task(address: str) -> dict | None:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM wallet_tasks WHERE address = ?",
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
                "UPDATE wallet_tasks SET attempts = attempts + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE address = ?",
                (address.lower(),),
            )
            conn.commit()
            row = conn.execute(
                "SELECT attempts FROM wallet_tasks WHERE address = ?",
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
                "SELECT status, COUNT(*) AS cnt FROM wallet_tasks GROUP BY status"
            ).fetchall()
            stats: dict = {r["status"]: r["cnt"] for r in rows}
            total = conn.execute("SELECT COUNT(*) FROM wallet_tasks").fetchone()[0]
            stats["total"] = total
            return stats
        finally:
            conn.close()


def reset_tasks() -> None:
    """Очистить только статусы задач. История запросов сохраняется."""
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM wallet_tasks")
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# request_history (never cleared)
# ---------------------------------------------------------------------------

def record_request(address: str, success: bool,
                   tx_hash: str | None = None,
                   response: str | None = None) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO request_history (address, requested_at, tx_hash, success, response) "
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
        finally:
            conn.close()


def last_request_at(address: str) -> datetime | None:
    """Время последней (любой — успешной или нет) заявки. UTC-aware."""
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT requested_at FROM request_history "
                "WHERE address = ? ORDER BY requested_at DESC LIMIT 1",
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


def cooldown_remaining(address: str, cooldown_hours: int) -> timedelta | None:
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
