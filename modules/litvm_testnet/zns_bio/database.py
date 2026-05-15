"""Persistent storage for zns_bio module.

Все таблицы живут в общей БД проекта (db/litvm.db), см. AGENTS.md §5.1
для litvm_testnet (мультипресетный, deliberately shared).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

from modules.litvm_testnet.database import connect as _connect_shared


_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    return _connect_shared()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS zns_registrations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT NOT NULL,
    wallet_name     TEXT,
    domain_name     TEXT NOT NULL,
    tld             TEXT NOT NULL,
    full_name       TEXT NOT NULL,             -- "name.tld"
    years           INTEGER NOT NULL,
    price_wei       TEXT NOT NULL,             -- payable value in wei
    price_native    REAL,                      -- = price_wei / 1e18
    referral        TEXT,
    credits         TEXT,
    tx_hash         TEXT,
    gas_used        INTEGER,
    token_id        TEXT,                      -- ZNSRegistry tokenID after mint
    status          TEXT NOT NULL,             -- pending|sent|arrived|failed|skipped
    error_message   TEXT,
    attempts        INTEGER DEFAULT 0,
    created_at      REAL,
    sent_at         REAL,
    confirmed_at    REAL,
    updated_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_zns_wallet ON zns_registrations(wallet_address);
CREATE INDEX IF NOT EXISTS idx_zns_status ON zns_registrations(status);
CREATE INDEX IF NOT EXISTS idx_zns_domain  ON zns_registrations(full_name);
"""


def init_database() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def insert_registration(*, wallet_address: str, wallet_name: Optional[str],
                        domain_name: str, tld: str, years: int,
                        price_wei: int, referral: str,
                        credits: int = 0) -> int:
    now = time.time()
    full = f"{domain_name}.{tld}"
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """INSERT INTO zns_registrations(
                    wallet_address, wallet_name, domain_name, tld, full_name,
                    years, price_wei, price_native, referral, credits,
                    status, attempts, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?, 'pending', 0, ?, ?)""",
                (wallet_address.lower(), wallet_name or "",
                 domain_name.lower(), tld.lower(), full.lower(),
                 int(years), str(int(price_wei)),
                 float(int(price_wei) / 1e18),
                 (referral or "").lower(), str(int(credits)),
                 now, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_registration(reg_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    keys = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [int(reg_id)]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE zns_registrations SET {keys} WHERE id=?", vals,
            )
            conn.commit()
        finally:
            conn.close()


def list_registrations(*, status: Optional[str] = None) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            if status:
                cur = conn.execute(
                    "SELECT * FROM zns_registrations WHERE status=? "
                    "ORDER BY id DESC", (status,))
            else:
                cur = conn.execute(
                    "SELECT * FROM zns_registrations ORDER BY id DESC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            out: dict = {}
            cur = conn.execute(
                "SELECT status, COUNT(*) AS n FROM zns_registrations "
                "GROUP BY status")
            for r in cur.fetchall():
                out[f"status_{r['status']}"] = int(r["n"])
            cur = conn.execute("SELECT COUNT(*) AS n FROM zns_registrations")
            out["total"] = int(cur.fetchone()["n"])
            cur = conn.execute(
                "SELECT COUNT(DISTINCT wallet_address) AS n "
                "FROM zns_registrations WHERE status='arrived'")
            out["unique_wallets_done"] = int(cur.fetchone()["n"])
            cur = conn.execute(
                "SELECT COALESCE(SUM(CAST(price_wei AS REAL)),0) AS s "
                "FROM zns_registrations WHERE status='arrived'")
            out["total_paid_wei"] = float(cur.fetchone()["s"] or 0)
            return out
        finally:
            conn.close()


def domain_already_used(full_name: str) -> bool:
    """В нашей БД (NOT on-chain). Защита от двойной отправки."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "SELECT 1 FROM zns_registrations WHERE full_name=? "
                "AND status IN ('pending','sent','arrived') LIMIT 1",
                (full_name.lower(),),
            )
            return cur.fetchone() is not None
        finally:
            conn.close()


def reset_registrations() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM zns_registrations")
            conn.commit()
        finally:
            conn.close()


DB_PATH = None  # shared in litvm.db
