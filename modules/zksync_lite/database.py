"""SQLite-хранилище задач/результатов чекера zkSync Lite.

Каждая задача — это один кошелёк. Балансы хранятся в JSON-поле,
чтобы поддержать произвольный набор токенов на аккаунте."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

DB_DIR = Path(__file__).resolve().parents[2] / "db"
DB_FILE = DB_DIR / "zksync_lite_balance.db"

_db_lock = Lock()


def _ensure_dir() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    """Соединение с включённым WAL (AGENTS §5.1).

    Веб-дашборд открывает этот же файл в режиме `mode=ro`, а горячий
    rollback-journal делает такое открытие невозможным: восстановление требует
    записи. Свойство персистентное и идемпотентное, схему не трогает.
    На сетевых дисках WAL недоступен — тогда остаёмся в journal-режиме.
    """
    conn = sqlite3.connect(str(DB_FILE))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    return conn


def init_database() -> None:
    _ensure_dir()
    with _db_lock, _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS zksync_lite_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL UNIQUE,
                account_name   TEXT,
                status         TEXT NOT NULL DEFAULT 'pending',
                account_id     INTEGER,
                pubkey_hash    TEXT,
                account_type   TEXT,
                nonce          INTEGER,
                is_active      INTEGER DEFAULT 0,
                tokens_count   INTEGER DEFAULT 0,
                nfts_count     INTEGER DEFAULT 0,
                eth_balance    TEXT,
                balances_json  TEXT DEFAULT '{}',
                nfts_json      TEXT DEFAULT '{}',
                error_message  TEXT,
                attempts       INTEGER DEFAULT 0,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at   TIMESTAMP
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_zkl_status ON zksync_lite_tasks(status)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_zkl_addr ON zksync_lite_tasks(wallet_address)"
        )
        conn.commit()


def create_tasks(wallets: List[Dict[str, Optional[str]]]) -> int:
    """Создаёт задачи (idempotent). Возвращает количество вставленных."""
    if not wallets:
        return 0
    init_database()
    inserted = 0
    with _db_lock, _connect() as conn:
        cur = conn.cursor()
        for w in wallets:
            addr = (w.get("wallet_address") or "").strip()
            if not addr:
                continue
            cur.execute(
                "INSERT OR IGNORE INTO zksync_lite_tasks "
                "(wallet_address, account_name, status) VALUES (?, ?, 'pending')",
                (addr, w.get("account_name")),
            )
            inserted += cur.rowcount
            if w.get("account_name"):
                cur.execute(
                    "UPDATE zksync_lite_tasks SET account_name = ? "
                    "WHERE wallet_address = ? AND (account_name IS NULL OR account_name = '')",
                    (w["account_name"], addr),
                )
        conn.commit()
    return inserted


def get_pending_tasks() -> List[Dict[str, Any]]:
    """Задачи в статусе pending или failed (для retry)."""
    init_database()
    with _db_lock, _connect() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT wallet_address, account_name, attempts FROM zksync_lite_tasks "
            "WHERE status IN ('pending', 'failed') "
            "ORDER BY attempts ASC, created_at ASC"
        )
        return [dict(r) for r in cur.fetchall()]


def update_task_success(
    address: str,
    *,
    account_id: Optional[int],
    pubkey_hash: Optional[str],
    account_type: Optional[str],
    nonce: Optional[int],
    is_active: bool,
    eth_balance: Optional[str],
    balances: Dict[str, Any],
    nfts: Dict[str, Any],
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _db_lock, _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE zksync_lite_tasks
            SET status = 'completed',
                account_id = ?, pubkey_hash = ?, account_type = ?, nonce = ?,
                is_active = ?, tokens_count = ?, nfts_count = ?,
                eth_balance = ?, balances_json = ?, nfts_json = ?,
                error_message = NULL,
                attempts = attempts + 1,
                updated_at = ?, completed_at = ?
            WHERE wallet_address = ?
            """,
            (
                account_id,
                pubkey_hash,
                account_type,
                nonce,
                1 if is_active else 0,
                len(balances or {}),
                len(nfts or {}),
                eth_balance,
                json.dumps(balances or {}, ensure_ascii=False, default=str),
                json.dumps(nfts or {}, ensure_ascii=False, default=str),
                now, now, address,
            ),
        )
        conn.commit()


def update_task_failed(address: str, error_message: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _db_lock, _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE zksync_lite_tasks
            SET status = 'failed',
                attempts = attempts + 1,
                updated_at = ?,
                error_message = ?
            WHERE wallet_address = ?
            """,
            (now, (error_message or "")[:500], address),
        )
        conn.commit()


def get_all_results() -> List[Dict[str, Any]]:
    init_database()
    with _db_lock, _connect() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT wallet_address, account_name, status, account_id, pubkey_hash,
                   account_type, nonce, is_active, tokens_count, nfts_count,
                   eth_balance, balances_json, nfts_json,
                   error_message, attempts, created_at, completed_at
            FROM zksync_lite_tasks
            ORDER BY is_active DESC, tokens_count DESC, wallet_address
            """
        )
        rows: List[Dict[str, Any]] = []
        for r in cur.fetchall():
            d = dict(r)
            try:
                d["balances"] = json.loads(d.pop("balances_json") or "{}")
            except Exception:
                d["balances"] = {}
            try:
                d["nfts"] = json.loads(d.pop("nfts_json") or "{}")
            except Exception:
                d["nfts"] = {}
            rows.append(d)
        return rows


def get_task_statistics() -> Dict[str, int]:
    init_database()
    with _db_lock, _connect() as conn:
        cur = conn.cursor()

        def _count(where: str = "") -> int:
            cur.execute(
                f"SELECT COUNT(*) FROM zksync_lite_tasks{(' WHERE ' + where) if where else ''}"
            )
            return cur.fetchone()[0]

        return {
            "total": _count(),
            "completed": _count("status = 'completed'"),
            "pending": _count("status = 'pending'"),
            "failed": _count("status = 'failed'"),
            "active": _count("status = 'completed' AND is_active = 1"),
            "with_tokens": _count("status = 'completed' AND tokens_count > 0"),
            "with_nfts": _count("status = 'completed' AND nfts_count > 0"),
        }


def get_total_tasks_count() -> int:
    return get_task_statistics()["total"]


def all_tasks_completed() -> bool:
    s = get_task_statistics()
    return s["total"] > 0 and s["completed"] == s["total"]


def reset_database() -> int:
    init_database()
    with _db_lock, _connect() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM zksync_lite_tasks")
        deleted = cur.rowcount
        conn.commit()
        return deleted


__all__ = [
    "DB_FILE",
    "init_database",
    "create_tasks",
    "get_pending_tasks",
    "update_task_success",
    "update_task_failed",
    "get_all_results",
    "get_task_statistics",
    "get_total_tasks_count",
    "all_tasks_completed",
    "reset_database",
]
