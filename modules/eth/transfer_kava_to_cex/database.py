"""SQLite-схема и CRUD для модуля transfer_kava_to_cex.

Релевантные принципы из AGENTS.md:
  • Каждая операция открывает свой connection (WAL-mode).
  • Lifecycle статусов: pending → tx_sent → awaiting_arrival → arrived / failed / skipped.
  • Excel — производная от БД.

Схема — 2 связанные таблицы:
  kava_wallets         — справочник кошельков (PK = id, UNIQUE по wallet_address)
  kava_transfer_tasks  — задачи на перевод (FK → kava_wallets.id, UNIQUE по wallet_id
                         для текущего цикла — 1:1)

Foreign key включён через PRAGMA foreign_keys=ON.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_DIR = Path(__file__).resolve().parents[3] / "db"
DB_PATH = DB_DIR / "transfer_kava_to_cex.db"

# Статусы задачи
STATUS_PENDING = "pending"
STATUS_TX_SENT = "tx_sent"
STATUS_AWAITING = "awaiting_arrival"
STATUS_ARRIVED = "arrived"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

TERMINAL_OK = (STATUS_ARRIVED,)
TERMINAL = (STATUS_ARRIVED, STATUS_SKIPPED)
NON_TERMINAL = (STATUS_PENDING, STATUS_TX_SENT, STATUS_AWAITING, STATUS_FAILED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kava_wallets (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address        TEXT    NOT NULL UNIQUE,    -- 0x EVM (from PK)
    account_name          TEXT,
    private_key           TEXT    NOT NULL,
    proxy                 TEXT,
    reserve_proxy         TEXT,
    cex_address_bech32    TEXT    NOT NULL,           -- kava1...
    cex_address_evm       TEXT    NOT NULL,           -- 0x... (converted)
    transfer_amount_spec  TEXT,                       -- raw e.g. "100-100%"
    csv_index             INTEGER NOT NULL DEFAULT 0, -- порядок в data.csv
    created_at            INTEGER NOT NULL,
    updated_at            INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kava_transfer_tasks (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id                INTEGER NOT NULL,
    status                   TEXT    NOT NULL DEFAULT 'pending',
    src_balance_before_wei   TEXT,
    src_balance_after_wei    TEXT,
    dst_balance_before_wei   TEXT,
    dst_balance_after_wei    TEXT,
    sent_amount_wei          TEXT,
    sent_amount_human        TEXT,
    gas_price_wei            TEXT,
    gas_limit                INTEGER,
    nonce                    INTEGER,
    tx_hash                  TEXT,
    explorer_link            TEXT,
    receipt_status           INTEGER,         -- 1=ok, 0=fail, NULL=unknown
    arrival_detected_at      INTEGER,         -- unix ts когда мы убедились что пришло
    error_message            TEXT,
    attempts                 INTEGER NOT NULL DEFAULT 0,
    created_at               INTEGER NOT NULL,
    updated_at               INTEGER NOT NULL,
    UNIQUE(wallet_id),
    FOREIGN KEY (wallet_id) REFERENCES kava_wallets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kava_tasks_status  ON kava_transfer_tasks(status);
CREATE INDEX IF NOT EXISTS idx_kava_wallets_addr  ON kava_wallets(wallet_address);
CREATE INDEX IF NOT EXISTS idx_kava_wallets_csvi  ON kava_wallets(csv_index);
"""


def _now() -> int:
    return int(time.time())


def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database() -> None:
    with _connect() as c:
        c.executescript(SCHEMA)


def reset_database() -> None:
    with _connect() as c:
        c.execute("DROP TABLE IF EXISTS kava_transfer_tasks")
        c.execute("DROP TABLE IF EXISTS kava_wallets")
        c.executescript(SCHEMA)


# ----------------------------------------------------------------------------
# Wallets
# ----------------------------------------------------------------------------

def upsert_wallet(*, wallet_address: str, account_name: str, private_key: str,
                  proxy: Optional[str], reserve_proxy: Optional[str],
                  cex_address_bech32: str, cex_address_evm: str,
                  transfer_amount_spec: str, csv_index: int) -> int:
    """Создаёт/обновляет запись кошелька. Возвращает wallet_id."""
    now = _now()
    addr = wallet_address.lower()
    with _connect() as c:
        existing = c.execute(
            "SELECT id FROM kava_wallets WHERE wallet_address = ?", (addr,),
        ).fetchone()
        if existing is None:
            cur = c.execute(
                """INSERT INTO kava_wallets
                   (wallet_address, account_name, private_key, proxy,
                    reserve_proxy, cex_address_bech32, cex_address_evm,
                    transfer_amount_spec, csv_index, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (addr, account_name, private_key, proxy, reserve_proxy,
                 cex_address_bech32, cex_address_evm, transfer_amount_spec,
                 csv_index, now, now),
            )
            return int(cur.lastrowid)
        c.execute(
            """UPDATE kava_wallets SET account_name=?, private_key=?, proxy=?,
                  reserve_proxy=?, cex_address_bech32=?, cex_address_evm=?,
                  transfer_amount_spec=?, csv_index=?, updated_at=?
               WHERE id=?""",
            (account_name, private_key, proxy, reserve_proxy,
             cex_address_bech32, cex_address_evm, transfer_amount_spec,
             csv_index, now, existing["id"]),
        )
        return int(existing["id"])


def list_wallets_ordered() -> List[Dict[str, Any]]:
    """Все кошельки в порядке csv_index ASC."""
    with _connect() as c:
        rows = c.execute(
            "SELECT * FROM kava_wallets ORDER BY csv_index ASC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_wallet(wallet_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as c:
        r = c.execute(
            "SELECT * FROM kava_wallets WHERE id=?", (wallet_id,)
        ).fetchone()
        return dict(r) if r else None


# ----------------------------------------------------------------------------
# Tasks
# ----------------------------------------------------------------------------

def get_or_create_task(wallet_id: int) -> Dict[str, Any]:
    now = _now()
    with _connect() as c:
        r = c.execute(
            "SELECT * FROM kava_transfer_tasks WHERE wallet_id=?", (wallet_id,)
        ).fetchone()
        if r:
            return dict(r)
        c.execute(
            """INSERT INTO kava_transfer_tasks (wallet_id, status, created_at, updated_at)
               VALUES (?, ?, ?, ?)""",
            (wallet_id, STATUS_PENDING, now, now),
        )
        r = c.execute(
            "SELECT * FROM kava_transfer_tasks WHERE wallet_id=?", (wallet_id,)
        ).fetchone()
        return dict(r)


def get_task_by_wallet(wallet_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as c:
        r = c.execute(
            "SELECT * FROM kava_transfer_tasks WHERE wallet_id=?", (wallet_id,)
        ).fetchone()
        return dict(r) if r else None


def update_task(task_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    with _connect() as c:
        c.execute(
            f"UPDATE kava_transfer_tasks SET {cols} WHERE id = ?", values
        )


def increment_attempts(task_id: int) -> None:
    with _connect() as c:
        c.execute(
            "UPDATE kava_transfer_tasks SET attempts = attempts + 1, "
            "updated_at = ? WHERE id = ?", (_now(), task_id),
        )


def list_all_tasks_joined() -> List[Dict[str, Any]]:
    """Все задачи JOIN-нутые с кошельками, в порядке csv_index."""
    with _connect() as c:
        rows = c.execute(
            """SELECT
                  w.id            AS wallet_id,
                  w.wallet_address,
                  w.account_name,
                  w.cex_address_bech32,
                  w.cex_address_evm,
                  w.transfer_amount_spec,
                  w.csv_index,
                  t.id            AS task_id,
                  t.status,
                  t.src_balance_before_wei,
                  t.src_balance_after_wei,
                  t.dst_balance_before_wei,
                  t.dst_balance_after_wei,
                  t.sent_amount_wei,
                  t.sent_amount_human,
                  t.gas_price_wei,
                  t.gas_limit,
                  t.nonce,
                  t.tx_hash,
                  t.explorer_link,
                  t.receipt_status,
                  t.arrival_detected_at,
                  t.error_message,
                  t.attempts,
                  t.created_at    AS task_created_at,
                  t.updated_at    AS task_updated_at
               FROM kava_wallets w
               LEFT JOIN kava_transfer_tasks t ON t.wallet_id = w.id
               ORDER BY w.csv_index ASC, w.id ASC"""
        ).fetchall()
        return [dict(r) for r in rows]


def list_tasks_by_status(statuses: List[str]) -> List[Dict[str, Any]]:
    if not statuses:
        return []
    placeholders = ",".join("?" * len(statuses))
    with _connect() as c:
        rows = c.execute(
            f"""SELECT t.*, w.wallet_address, w.account_name
                FROM kava_transfer_tasks t
                JOIN kava_wallets w ON w.id = t.wallet_id
                WHERE t.status IN ({placeholders})
                ORDER BY w.csv_index ASC""",
            statuses,
        ).fetchall()
        return [dict(r) for r in rows]


def get_statistics() -> Dict[str, int]:
    with _connect() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) AS cnt FROM kava_transfer_tasks GROUP BY status"
        ).fetchall()
        s: Dict[str, int] = {r["status"]: int(r["cnt"]) for r in rows}
        total_w = c.execute("SELECT COUNT(*) FROM kava_wallets").fetchone()[0]
        s["wallets_total"] = int(total_w)
        s["total"] = sum(v for k, v in s.items() if k != "wallets_total")
        return s


__all__ = [
    "DB_PATH",
    "STATUS_PENDING", "STATUS_TX_SENT", "STATUS_AWAITING",
    "STATUS_ARRIVED", "STATUS_FAILED", "STATUS_SKIPPED",
    "TERMINAL", "TERMINAL_OK", "NON_TERMINAL",
    "init_database", "reset_database",
    "upsert_wallet", "list_wallets_ordered", "get_wallet",
    "get_or_create_task", "get_task_by_wallet",
    "update_task", "increment_attempts",
    "list_all_tasks_joined", "list_tasks_by_status",
    "get_statistics",
]
