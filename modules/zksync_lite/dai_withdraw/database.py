"""SQLite БД для DAI-withdraw задач."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_FILE = Path(__file__).resolve().parents[3] / "db" / "dai_withdraw.db"

STATUS_PENDING = "pending"
STATUS_LITE_TX_SENT = "lite_tx_sent"
STATUS_LITE_TX_FAILED = "lite_tx_failed"
STATUS_FINALIZED_L1 = "finalized_l1"  # обнаружено получение в L1
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS dai_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    private_key TEXT NOT NULL,
    proxy TEXT,
    reserve_proxy TEXT,
    eth_address TEXT NOT NULL,
    amount_raw_planned TEXT,
    amount_human_planned TEXT,
    fee_raw TEXT,
    fee_token TEXT,
    decimals INTEGER DEFAULT 18,
    status TEXT NOT NULL DEFAULT 'pending',
    lite_tx_hash TEXT,
    l1_balance_before TEXT,
    l1_balance_after TEXT,
    error_message TEXT,
    attempts INTEGER DEFAULT 0,
    extra_json TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dai_status ON dai_tasks(status);
CREATE INDEX IF NOT EXISTS idx_dai_wallet ON dai_tasks(wallet_address);
"""


def _conn() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_FILE))
    c.row_factory = sqlite3.Row
    return c


def init_database() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)
        c.commit()


def reset_database() -> None:
    if DB_FILE.exists():
        DB_FILE.unlink()
    init_database()


def create_task(*, wallet_address: str, private_key: str,
                proxy: Optional[str], reserve_proxy: Optional[str],
                eth_address: str,
                amount_raw_planned: str, amount_human_planned: str,
                decimals: int = 18,
                extra: Optional[Dict[str, Any]] = None) -> int:
    now = int(time.time())
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO dai_tasks (
                wallet_address, private_key, proxy, reserve_proxy, eth_address,
                amount_raw_planned, amount_human_planned, decimals,
                status, extra_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (wallet_address.lower(), private_key, proxy, reserve_proxy,
             eth_address.lower(),
             amount_raw_planned, amount_human_planned, decimals,
             json.dumps(extra or {}), now, now),
        )
        c.commit()
        return cur.lastrowid


def update_task(task_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = int(time.time())
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [task_id]
    with _conn() as c:
        c.execute(f"UPDATE dai_tasks SET {cols} WHERE id = ?", vals)
        c.commit()


def increment_attempts(task_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE dai_tasks SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
            (int(time.time()), task_id),
        )
        c.commit()


def list_pending() -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM dai_tasks WHERE status = ? ORDER BY id ASC",
            (STATUS_PENDING,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_all() -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM dai_tasks ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_statistics() -> Dict[str, int]:
    with _conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM dai_tasks GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}


__all__ = [
    "init_database", "reset_database", "create_task", "update_task",
    "increment_attempts", "list_pending", "list_all", "get_statistics",
    "STATUS_PENDING", "STATUS_LITE_TX_SENT", "STATUS_LITE_TX_FAILED",
    "STATUS_FINALIZED_L1", "STATUS_SKIPPED", "STATUS_FAILED",
]
