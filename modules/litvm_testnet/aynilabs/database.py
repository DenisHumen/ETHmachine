"""SQLite-схема для модуля Aynilabs (живёт в общей БД `db/litvm.db`).

Таблицы:
  ayni_wrap_tasks — одна запись на (address, tx_index). Хранит план + результат.

Lifecycle статусов (§14.2 AGENTS.md):
  pending → tx_sent → arrived ✅
                    ↘ failed ❌
  skipped (planner: balance < min)                     — terminal
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

from modules.litvm_testnet.database import connect as _connect


_lock = threading.Lock()


def init_database() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ayni_wrap_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    name TEXT,
                    tx_index INTEGER NOT NULL DEFAULT 1,
                    planned_amount_wei TEXT NOT NULL,
                    planned_amount_human REAL NOT NULL,
                    native_balance_before_wei TEXT,
                    wzkltc_balance_before_wei TEXT,
                    wzkltc_balance_after_wei TEXT,
                    received_amount_wei TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    tx_hash TEXT,
                    gas_used INTEGER,
                    error_message TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    sent_at REAL,
                    confirmed_at REAL,
                    updated_at REAL NOT NULL,
                    UNIQUE(address, tx_index)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ayni_addr "
                "ON ayni_wrap_tasks(address)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ayni_status "
                "ON ayni_wrap_tasks(status)"
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def upsert_task(
    *,
    address: str,
    name: Optional[str],
    tx_index: int,
    planned_amount_wei: int,
    planned_amount_human: float,
    native_balance_before_wei: Optional[int] = None,
    wzkltc_balance_before_wei: Optional[int] = None,
    status: str = "pending",
) -> int:
    now = time.time()
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id FROM ayni_wrap_tasks WHERE address = ? AND tx_index = ?",
                (addr, int(tx_index)),
            ).fetchone()
            if row:
                conn.execute("""
                    UPDATE ayni_wrap_tasks
                    SET planned_amount_wei = ?,
                        planned_amount_human = ?,
                        native_balance_before_wei = ?,
                        wzkltc_balance_before_wei = ?,
                        status = ?,
                        name = COALESCE(?, name),
                        updated_at = ?
                    WHERE id = ?
                """, (
                    str(planned_amount_wei), float(planned_amount_human),
                    str(native_balance_before_wei) if native_balance_before_wei is not None else None,
                    str(wzkltc_balance_before_wei) if wzkltc_balance_before_wei is not None else None,
                    status, name, now, int(row["id"]),
                ))
                conn.commit()
                return int(row["id"])
            cur = conn.execute("""
                INSERT INTO ayni_wrap_tasks
                    (address, name, tx_index, planned_amount_wei,
                     planned_amount_human, native_balance_before_wei,
                     wzkltc_balance_before_wei, status,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                addr, name, int(tx_index), str(planned_amount_wei),
                float(planned_amount_human),
                str(native_balance_before_wei) if native_balance_before_wei is not None else None,
                str(wzkltc_balance_before_wei) if wzkltc_balance_before_wei is not None else None,
                status, now, now,
            ))
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_task(task_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [int(task_id)]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE ayni_wrap_tasks SET {sets} WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()


def get_task_for_wallet(address: str, tx_index: int = 1) -> Optional[dict]:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM ayni_wrap_tasks WHERE address = ? AND tx_index = ?",
                (address.lower(), int(tx_index)),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def list_pending() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ayni_wrap_tasks "
                "WHERE status IN ('pending', 'tx_sent') "
                "ORDER BY address ASC, tx_index ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def list_all_tasks() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM ayni_wrap_tasks ORDER BY address ASC, tx_index ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) c FROM ayni_wrap_tasks GROUP BY status"
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) c FROM ayni_wrap_tasks"
            ).fetchone()["c"]
        finally:
            conn.close()
    stats = {"total": int(total)}
    for r in rows:
        stats[r["status"]] = int(r["c"])
    return stats


def reset_database() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute("DROP TABLE IF EXISTS ayni_wrap_tasks")
            conn.commit()
        finally:
            conn.close()
    init_database()
