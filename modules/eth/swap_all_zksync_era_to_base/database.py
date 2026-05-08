"""SQLite задач swap-all zkSync Era → Base USDC."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_DIR = Path(__file__).resolve().parents[3] / "db"
DB_PATH = DB_DIR / "swap_all_zksync_era_to_base.db"

STATUS_PENDING = "pending"
STATUS_SKIPPED = "skipped"
STATUS_SWAP_CREATED = "swap_created"
STATUS_TX_SENT = "tx_sent"
STATUS_AWAITING = "awaiting_arrival"
STATUS_ARRIVED = "arrived"
STATUS_FAILED = "failed"

TERMINAL = (STATUS_SKIPPED, STATUS_ARRIVED, STATUS_FAILED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS swap_all_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    account_name TEXT,
    private_key TEXT NOT NULL,
    proxy TEXT,
    reserve_proxy TEXT,
    token TEXT NOT NULL,
    contract TEXT,
    decimals INTEGER NOT NULL DEFAULT 18,
    raw_balance TEXT NOT NULL DEFAULT '0',
    human_balance TEXT NOT NULL DEFAULT '0',
    usd_value TEXT NOT NULL DEFAULT '0',
    supported INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    swap_id TEXT,
    deposit_address TEXT,
    sent_amount_raw TEXT,
    sent_amount_human TEXT,
    src_tx_hash TEXT,
    dst_tx_hash TEXT,
    dst_balance_before TEXT,
    dst_balance_after TEXT,
    received_amount TEXT,
    error_message TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    extra_json TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(wallet_address, token, contract)
);
CREATE INDEX IF NOT EXISTS idx_swap_all_zk_wallet ON swap_all_tasks(wallet_address);
CREATE INDEX IF NOT EXISTS idx_swap_all_zk_status ON swap_all_tasks(status);
"""


def _now() -> int:
    return int(time.time())


def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_database() -> None:
    with _connect() as c:
        c.executescript(SCHEMA)


def reset_database() -> None:
    with _connect() as c:
        c.execute("DROP TABLE IF EXISTS swap_all_tasks")
        c.executescript(SCHEMA)


def upsert_task(*, wallet_address: str, account_name: str, private_key: str,
                proxy: Optional[str], reserve_proxy: Optional[str],
                token: str, contract: str, decimals: int,
                raw_balance: str, human_balance: str, usd_value: str,
                supported: bool,
                extra: Optional[Dict[str, Any]] = None) -> int:
    now = _now()
    extra_json = json.dumps(extra or {})
    with _connect() as c:
        existing = c.execute(
            """SELECT id, status FROM swap_all_tasks
               WHERE wallet_address = ? AND token = ? AND contract = ?""",
            (wallet_address.lower(), token.upper(), contract.lower()),
        ).fetchone()
        if existing is None:
            cur = c.execute(
                """INSERT INTO swap_all_tasks
                    (wallet_address, account_name, private_key, proxy,
                     reserve_proxy, token, contract, decimals,
                     raw_balance, human_balance, usd_value, supported,
                     status, extra_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (wallet_address.lower(), account_name, private_key, proxy,
                 reserve_proxy, token.upper(), contract.lower(), int(decimals),
                 raw_balance, human_balance, usd_value, 1 if supported else 0,
                 STATUS_PENDING if supported else STATUS_SKIPPED,
                 extra_json, now, now),
            )
            return int(cur.lastrowid)
        keep_status = existing["status"]
        if keep_status in (STATUS_PENDING, STATUS_SKIPPED):
            new_status = STATUS_PENDING if supported else STATUS_SKIPPED
        else:
            new_status = keep_status
        c.execute(
            """UPDATE swap_all_tasks SET account_name=?, private_key=?, proxy=?,
                  reserve_proxy=?, decimals=?, raw_balance=?, human_balance=?,
                  usd_value=?, supported=?, status=?, extra_json=?, updated_at=?
               WHERE id=?""",
            (account_name, private_key, proxy, reserve_proxy, int(decimals),
             raw_balance, human_balance, usd_value, 1 if supported else 0,
             new_status, extra_json, now, existing["id"]),
        )
        return int(existing["id"])


def update_task(task_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    with _connect() as c:
        c.execute(f"UPDATE swap_all_tasks SET {cols} WHERE id = ?", values)


def increment_attempts(task_id: int) -> None:
    with _connect() as c:
        c.execute(
            "UPDATE swap_all_tasks SET attempts = attempts + 1, updated_at = ? "
            "WHERE id = ?", (_now(), task_id),
        )


def list_pending_for_wallet(wallet_address: str) -> List[Dict[str, Any]]:
    with _connect() as c:
        rows = c.execute(
            """SELECT * FROM swap_all_tasks
               WHERE wallet_address = ?
                 AND supported = 1
                 AND status NOT IN (?, ?, ?)
               ORDER BY id ASC""",
            (wallet_address.lower(), STATUS_ARRIVED, STATUS_SKIPPED, STATUS_FAILED),
        ).fetchall()
        return [dict(r) for r in rows]


def list_all_tasks() -> List[Dict[str, Any]]:
    with _connect() as c:
        rows = c.execute(
            "SELECT * FROM swap_all_tasks ORDER BY wallet_address, token"
        ).fetchall()
        return [dict(r) for r in rows]


def list_wallets_with_pending() -> List[str]:
    with _connect() as c:
        rows = c.execute(
            """SELECT DISTINCT wallet_address FROM swap_all_tasks
               WHERE supported = 1 AND status NOT IN (?, ?, ?)""",
            (STATUS_ARRIVED, STATUS_SKIPPED, STATUS_FAILED),
        ).fetchall()
        return [r["wallet_address"] for r in rows]


def get_statistics() -> Dict[str, int]:
    with _connect() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) as cnt FROM swap_all_tasks GROUP BY status"
        ).fetchall()
        s = {r["status"]: int(r["cnt"]) for r in rows}
        s["total"] = sum(s.values())
        return s


__all__ = [
    "init_database", "reset_database", "upsert_task", "update_task",
    "increment_attempts", "list_pending_for_wallet", "list_all_tasks",
    "list_wallets_with_pending", "get_statistics", "DB_PATH",
    "STATUS_PENDING", "STATUS_SKIPPED", "STATUS_SWAP_CREATED",
    "STATUS_TX_SENT", "STATUS_AWAITING", "STATUS_ARRIVED", "STATUS_FAILED",
    "TERMINAL",
]
