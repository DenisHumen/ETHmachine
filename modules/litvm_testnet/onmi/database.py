"""SQLite-схема для модуля Onmi (общая БД `db/litvm.db`).

Таблицы:
  onmi_coin_tasks — одна запись на (address, tx_index). План + результат.

Lifecycle (§14.2 AGENTS.md):
  pending  → image_ready → metadata_ready → tx_sent → arrived ✅
                                                     ↘ failed ❌
  skipped — terminal (native balance < min, нет картинки и т.п.)
"""
from __future__ import annotations

import sqlite3  # noqa: F401  (used implicitly via connect())
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
                CREATE TABLE IF NOT EXISTS onmi_coin_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    name TEXT,
                    tx_index INTEGER NOT NULL DEFAULT 1,

                    -- planned coin metadata
                    coin_name TEXT NOT NULL,
                    coin_symbol TEXT NOT NULL,
                    coin_description TEXT,

                    -- planned native value for initial buy (0 = createToken)
                    initial_buy_wei TEXT NOT NULL DEFAULT '0',
                    initial_buy_human REAL NOT NULL DEFAULT 0,

                    -- картинка
                    image_source_url TEXT,
                    image_local_path TEXT,
                    image_uploaded_url TEXT,

                    -- метаданные
                    metadata_uri TEXT,

                    -- баланс на старте
                    native_balance_before_wei TEXT,

                    -- on-chain результат
                    token_address TEXT,
                    tx_hash TEXT,
                    gas_used INTEGER,
                    tokens_received_wei TEXT,

                    status TEXT NOT NULL DEFAULT 'pending',
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
                "CREATE INDEX IF NOT EXISTS idx_onmi_addr ON onmi_coin_tasks(address)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_onmi_status ON onmi_coin_tasks(status)"
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
    coin_name: str,
    coin_symbol: str,
    coin_description: Optional[str],
    initial_buy_wei: int,
    initial_buy_human: float,
    native_balance_before_wei: Optional[int] = None,
    status: str = "pending",
) -> int:
    now = time.time()
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id FROM onmi_coin_tasks WHERE address = ? AND tx_index = ?",
                (addr, int(tx_index)),
            ).fetchone()
            if row:
                conn.execute("""
                    UPDATE onmi_coin_tasks
                    SET coin_name = ?,
                        coin_symbol = ?,
                        coin_description = ?,
                        initial_buy_wei = ?,
                        initial_buy_human = ?,
                        native_balance_before_wei = ?,
                        status = ?,
                        name = COALESCE(?, name),
                        updated_at = ?
                    WHERE id = ?
                """, (
                    coin_name, coin_symbol, coin_description,
                    str(int(initial_buy_wei)), float(initial_buy_human),
                    str(int(native_balance_before_wei)) if native_balance_before_wei is not None else None,
                    status, name, now, int(row["id"]),
                ))
                conn.commit()
                return int(row["id"])
            cur = conn.execute("""
                INSERT INTO onmi_coin_tasks
                    (address, name, tx_index, coin_name, coin_symbol, coin_description,
                     initial_buy_wei, initial_buy_human, native_balance_before_wei,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                addr, name, int(tx_index), coin_name, coin_symbol, coin_description,
                str(int(initial_buy_wei)), float(initial_buy_human),
                str(int(native_balance_before_wei)) if native_balance_before_wei is not None else None,
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
                f"UPDATE onmi_coin_tasks SET {sets} WHERE id = ?",
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
                "SELECT * FROM onmi_coin_tasks WHERE address = ? AND tx_index = ?",
                (address.lower(), int(tx_index)),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def used_symbols() -> set[str]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT coin_symbol FROM onmi_coin_tasks"
            ).fetchall()
            return {(r["coin_symbol"] or "").upper() for r in rows}
        finally:
            conn.close()


def list_all_tasks() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM onmi_coin_tasks ORDER BY address ASC, tx_index ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) c FROM onmi_coin_tasks GROUP BY status"
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) c FROM onmi_coin_tasks"
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
            conn.execute("DROP TABLE IF EXISTS onmi_coin_tasks")
            conn.commit()
        finally:
            conn.close()
    init_database()
