"""SQLite БД для SafePal X1 Eligibility Checker."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

DB_DIR = Path(__file__).resolve().parents[3] / "db"
DB_PATH = DB_DIR / "safepal_x1_checker.db"

_db_lock = Lock()


def _ensure_dir() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)


def init_database() -> None:
    _ensure_dir()
    with _db_lock, sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS check_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL UNIQUE,
                account_name TEXT,
                act_code TEXT,
                channel_code TEXT,
                chain_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                eligible INTEGER,
                result_text TEXT,
                channel_name TEXT,
                sku TEXT,
                session_id TEXT,
                error_message TEXT,
                attempts INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_safepal_x1_addr ON check_tasks(wallet_address)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_safepal_x1_status ON check_tasks(status)")
        conn.commit()


def create_tasks(wallets: List[Dict[str, Any]], act_code: str, channel_code: str,
                 chain_id: Any) -> int:
    """Idempotent создание задач. wallets: [{wallet_address, account_name}]."""
    if not wallets:
        return 0
    init_database()
    inserted = 0
    with _db_lock, sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        for w in wallets:
            addr = (w.get("wallet_address") or "").strip()
            if not addr:
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO check_tasks
                    (wallet_address, account_name, act_code, channel_code, chain_id, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (addr, w.get("account_name"), act_code, channel_code, str(chain_id)),
            )
            inserted += cur.rowcount
            if w.get("account_name"):
                cur.execute(
                    "UPDATE check_tasks SET account_name = ? "
                    "WHERE wallet_address = ? AND (account_name IS NULL OR account_name = '')",
                    (w["account_name"], addr),
                )
        conn.commit()
    return inserted


def get_pending_addresses() -> List[str]:
    init_database()
    with _db_lock, sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT wallet_address FROM check_tasks "
            "WHERE status IN ('pending', 'failed') "
            "ORDER BY attempts ASC, created_at ASC"
        )
        return [r[0] for r in cur.fetchall()]


def update_task_success(address: str, eligible: bool, result_text: str,
                        channel_name: Optional[str], sku: Optional[str],
                        session_id: Optional[str]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _db_lock, sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE check_tasks
            SET status = 'completed', eligible = ?, result_text = ?,
                channel_name = COALESCE(?, channel_name),
                sku = COALESCE(?, sku),
                session_id = COALESCE(?, session_id),
                error_message = NULL,
                attempts = attempts + 1,
                updated_at = ?, completed_at = ?
            WHERE wallet_address = ?
            """,
            (1 if eligible else 0, result_text, channel_name, sku, session_id,
             now, now, address),
        )
        conn.commit()


def update_task_failed(address: str, error_message: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _db_lock, sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE check_tasks
            SET status = 'failed', attempts = attempts + 1,
                updated_at = ?, error_message = ?
            WHERE wallet_address = ?
            """,
            (now, (error_message or "")[:500], address),
        )
        conn.commit()


def get_all_results() -> List[Dict[str, Any]]:
    init_database()
    with _db_lock, sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT wallet_address, account_name, act_code, channel_code, chain_id,
                   status, eligible, result_text, channel_name, sku,
                   error_message, attempts, created_at, completed_at
            FROM check_tasks
            ORDER BY eligible DESC, wallet_address
            """
        )
        return [dict(r) for r in cur.fetchall()]


def get_task_statistics() -> Dict[str, int]:
    init_database()
    with _db_lock, sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()

        def _count(where: str = "") -> int:
            cur.execute(
                f"SELECT COUNT(*) FROM check_tasks{(' WHERE ' + where) if where else ''}"
            )
            return cur.fetchone()[0]

        return {
            "total": _count(),
            "completed": _count("status = 'completed'"),
            "pending": _count("status = 'pending'"),
            "failed": _count("status = 'failed'"),
            "eligible": _count("status = 'completed' AND eligible = 1"),
            "not_eligible": _count("status = 'completed' AND eligible = 0"),
        }


def get_total_tasks_count() -> int:
    return get_task_statistics()["total"]


def all_tasks_completed() -> bool:
    stats = get_task_statistics()
    return stats["total"] > 0 and stats["pending"] == 0 and stats["failed"] == 0


def reset_database() -> int:
    init_database()
    with _db_lock, sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM check_tasks")
        cnt = cur.fetchone()[0]
        cur.execute("DELETE FROM check_tasks")
        conn.commit()
        return cnt
