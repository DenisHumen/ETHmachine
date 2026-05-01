"""SQLite-БД задач свопа Lite → Era.

Хранит состояние per-swap-task (один токен на один кошелёк = одна запись).
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_DIR = Path(__file__).resolve().parents[3] / "db"
DB_PATH = DB_DIR / "zksync_lite_swap.db"


# Допустимые статусы:
# pending, signing_key, swap_created, lite_tx_sent, awaiting_arrival, arrived,
# failed, skipped
STATUS_PENDING = "pending"
STATUS_SWAP_CREATED = "swap_created"
STATUS_LITE_TX_SENT = "lite_tx_sent"
STATUS_AWAITING_ARRIVAL = "awaiting_arrival"
STATUS_ARRIVED = "arrived"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

TERMINAL_OK = (STATUS_ARRIVED,)
TERMINAL_FAIL = (STATUS_FAILED,)


SCHEMA = """
CREATE TABLE IF NOT EXISTS swap_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    private_key TEXT NOT NULL,
    proxy TEXT,
    route TEXT NOT NULL,                  -- 'layerswap' | 'orbiter'
    source_token TEXT NOT NULL,           -- ETH/USDT/USDC/DAI
    target_token TEXT NOT NULL,           -- что получим на Era
    amount_raw_planned TEXT NOT NULL,
    amount_human_planned TEXT NOT NULL,
    decimals INTEGER NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,  -- 0 = first, ETH = последний
    status TEXT NOT NULL DEFAULT 'pending',
    layerswap_swap_id TEXT,
    deposit_address TEXT,
    lite_tx_hash TEXT,
    l1_tx_hash TEXT,
    era_tx_hash TEXT,
    era_balance_before TEXT,
    era_balance_after TEXT,
    error_message TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    extra_json TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_swap_wallet ON swap_tasks(wallet_address);
CREATE INDEX IF NOT EXISTS idx_swap_status ON swap_tasks(status);
"""


def _now() -> int:
    return int(time.time())


def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_database() -> None:
    with _connect() as c:
        c.executescript(SCHEMA)


def reset_database() -> None:
    with _connect() as c:
        c.execute("DROP TABLE IF EXISTS swap_tasks")
        c.executescript(SCHEMA)


def create_task(*, wallet_address: str, private_key: str, proxy: Optional[str],
                route: str, source_token: str, target_token: str,
                amount_raw_planned: str, amount_human_planned: str,
                decimals: int, priority: int = 0,
                extra: Optional[Dict[str, Any]] = None) -> int:
    now = _now()
    with _connect() as c:
        cur = c.execute(
            """
            INSERT INTO swap_tasks
                (wallet_address, private_key, proxy, route, source_token,
                 target_token, amount_raw_planned, amount_human_planned,
                 decimals, priority, status, extra_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                wallet_address.lower(), private_key, proxy, route,
                source_token.upper(), target_token,
                str(amount_raw_planned), str(amount_human_planned),
                int(decimals), int(priority), STATUS_PENDING,
                json.dumps(extra or {}), now, now,
            ),
        )
        return int(cur.lastrowid)


def update_task(task_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    with _connect() as c:
        c.execute(f"UPDATE swap_tasks SET {cols} WHERE id = ?", values)


def increment_attempts(task_id: int) -> None:
    with _connect() as c:
        c.execute(
            "UPDATE swap_tasks SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
            (_now(), task_id),
        )


def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as c:
        row = c.execute("SELECT * FROM swap_tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def list_pending_for_wallet(wallet_address: str) -> List[Dict[str, Any]]:
    with _connect() as c:
        rows = c.execute(
            """SELECT * FROM swap_tasks
               WHERE wallet_address = ? AND status NOT IN (?, ?, ?)
               ORDER BY priority ASC, id ASC""",
            (wallet_address.lower(), STATUS_ARRIVED, STATUS_SKIPPED, STATUS_FAILED),
        ).fetchall()
        return [dict(r) for r in rows]


def list_all_tasks(status: Optional[str] = None) -> List[Dict[str, Any]]:
    with _connect() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM swap_tasks WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM swap_tasks ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def list_wallets_with_pending() -> List[str]:
    with _connect() as c:
        rows = c.execute(
            """SELECT DISTINCT wallet_address FROM swap_tasks
               WHERE status NOT IN (?, ?, ?)""",
            (STATUS_ARRIVED, STATUS_SKIPPED, STATUS_FAILED),
        ).fetchall()
        return [r["wallet_address"] for r in rows]


def get_statistics() -> Dict[str, int]:
    with _connect() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) AS cnt FROM swap_tasks GROUP BY status"
        ).fetchall()
        stats = {r["status"]: int(r["cnt"]) for r in rows}
        stats["total"] = sum(stats.values())
        return stats


__all__ = [
    "init_database", "reset_database", "create_task", "update_task",
    "increment_attempts", "get_task", "list_pending_for_wallet",
    "list_all_tasks", "list_wallets_with_pending", "get_statistics",
    "STATUS_PENDING", "STATUS_SWAP_CREATED", "STATUS_LITE_TX_SENT",
    "STATUS_AWAITING_ARRIVAL", "STATUS_ARRIVED", "STATUS_FAILED",
    "STATUS_SKIPPED", "DB_PATH",
]
