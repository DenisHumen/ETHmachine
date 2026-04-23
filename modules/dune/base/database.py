"""
SQLite база для Dune Base Checker.

Хранит задачи проверки и их результаты, чтобы можно было:
  • продолжить с места остановки;
  • повторно выгрузить результаты в Excel без обращения к API;
  • очистить и перезапустить с нуля.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

DB_DIR = Path(__file__).resolve().parents[3] / "db"
DB_FILE = DB_DIR / "dune_base_checker.db"

_db_lock = Lock()


def _ensure_dir() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)


def init_database() -> None:
    """Создание таблицы и индексов, если их ещё нет."""
    _ensure_dir()
    with _db_lock, sqlite3.connect(str(DB_FILE)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS check_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL UNIQUE,
                account_name TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                found_in_ranking INTEGER DEFAULT 0,
                found_in_volume INTEGER DEFAULT 0,
                ranking_data TEXT DEFAULT '{}',
                volume_data TEXT DEFAULT '{}',
                error_message TEXT,
                attempts INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dune_base_addr ON check_tasks(wallet_address)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dune_base_status ON check_tasks(status)")
        conn.commit()


def create_check_tasks(wallets: List[Dict[str, Optional[str]]]) -> int:
    """Создать задачи (idempotent). На вход — список dict с ключами:
    `wallet_address`, `account_name`. Возвращает количество вставленных.
    """
    if not wallets:
        return 0
    init_database()
    inserted = 0
    with _db_lock, sqlite3.connect(str(DB_FILE)) as conn:
        cur = conn.cursor()
        for w in wallets:
            addr = (w.get("wallet_address") or "").strip()
            if not addr:
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO check_tasks (wallet_address, account_name, status)
                VALUES (?, ?, 'pending')
                """,
                (addr, w.get("account_name")),
            )
            inserted += cur.rowcount
            # обновляем имя, если оно изменилось/добавилось
            if w.get("account_name"):
                cur.execute(
                    "UPDATE check_tasks SET account_name = ? WHERE wallet_address = ? AND (account_name IS NULL OR account_name = '')",
                    (w["account_name"], addr),
                )
        conn.commit()
    return inserted


def get_pending_addresses() -> List[str]:
    """Адреса задач, которые ещё не выполнены успешно (pending или failed)."""
    init_database()
    with _db_lock, sqlite3.connect(str(DB_FILE)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT wallet_address FROM check_tasks WHERE status IN ('pending', 'failed') "
            "ORDER BY attempts ASC, created_at ASC"
        )
        return [r[0] for r in cur.fetchall()]


def update_task_success(
    address: str,
    found_in_ranking: bool,
    found_in_volume: bool,
    ranking_row: Dict[str, Any],
    volume_row: Dict[str, Any],
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _db_lock, sqlite3.connect(str(DB_FILE)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE check_tasks
            SET status = 'completed',
                found_in_ranking = ?, found_in_volume = ?,
                ranking_data = ?, volume_data = ?,
                error_message = NULL,
                attempts = attempts + 1,
                updated_at = ?, completed_at = ?
            WHERE wallet_address = ?
            """,
            (
                1 if found_in_ranking else 0,
                1 if found_in_volume else 0,
                json.dumps(ranking_row or {}, ensure_ascii=False, default=str),
                json.dumps(volume_row or {}, ensure_ascii=False, default=str),
                now, now, address,
            ),
        )
        conn.commit()


def update_task_failed(address: str, error_message: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _db_lock, sqlite3.connect(str(DB_FILE)) as conn:
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
    """Все строки таблицы для экспорта в xlsx."""
    init_database()
    with _db_lock, sqlite3.connect(str(DB_FILE)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT wallet_address, account_name, status,
                   found_in_ranking, found_in_volume,
                   ranking_data, volume_data,
                   error_message, attempts, created_at, completed_at
            FROM check_tasks
            ORDER BY (found_in_ranking + found_in_volume) DESC, wallet_address
            """
        )
        rows: List[Dict[str, Any]] = []
        for r in cur.fetchall():
            d = dict(r)
            try:
                d["ranking_data"] = json.loads(d.get("ranking_data") or "{}")
            except Exception:  # noqa: BLE001
                d["ranking_data"] = {}
            try:
                d["volume_data"] = json.loads(d.get("volume_data") or "{}")
            except Exception:  # noqa: BLE001
                d["volume_data"] = {}
            rows.append(d)
        return rows


def get_task_statistics() -> Dict[str, int]:
    init_database()
    with _db_lock, sqlite3.connect(str(DB_FILE)) as conn:
        cur = conn.cursor()
        def _count(where: str = "") -> int:
            cur.execute(f"SELECT COUNT(*) FROM check_tasks{(' WHERE ' + where) if where else ''}")
            return cur.fetchone()[0]
        return {
            "total": _count(),
            "completed": _count("status = 'completed'"),
            "pending": _count("status = 'pending'"),
            "failed": _count("status = 'failed'"),
            "found_ranking": _count("status = 'completed' AND found_in_ranking = 1"),
            "found_volume": _count("status = 'completed' AND found_in_volume = 1"),
            "found_any": _count("status = 'completed' AND (found_in_ranking = 1 OR found_in_volume = 1)"),
        }


def get_total_tasks_count() -> int:
    return get_task_statistics()["total"]


def all_tasks_completed() -> bool:
    s = get_task_statistics()
    return s["total"] > 0 and s["completed"] == s["total"]


def reset_database() -> int:
    init_database()
    with _db_lock, sqlite3.connect(str(DB_FILE)) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM check_tasks")
        deleted = cur.rowcount
        conn.commit()
        return deleted


__all__ = [
    "init_database",
    "create_check_tasks",
    "get_pending_addresses",
    "update_task_success",
    "update_task_failed",
    "get_all_results",
    "get_task_statistics",
    "get_total_tasks_count",
    "all_tasks_completed",
    "reset_database",
    "DB_FILE",
]
