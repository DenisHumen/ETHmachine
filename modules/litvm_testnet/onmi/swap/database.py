"""Persistent storage для swap-модуля.

Tables:
  • onmi_swap_known_pairs — discovered UniswapV2 pairs (token + WETH side).
    Persistent — никогда не удаляется при reset.
  • onmi_swap_history — full audit log buy/sell-операций.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

from modules.litvm_testnet.database import connect as _connect_shared


_lock = threading.Lock()


def _connect():
    return _connect_shared()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS onmi_swap_known_pairs (
    pair_address    TEXT PRIMARY KEY,
    token_address   TEXT NOT NULL,
    token_symbol    TEXT,
    token_decimals  INTEGER DEFAULT 18,
    weth_address    TEXT NOT NULL,
    reserve_native_wei TEXT,
    reserve_token_wei  TEXT,
    discovered_at   REAL,
    last_seen_at    REAL,
    disabled        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_swap_pairs_token ON onmi_swap_known_pairs(token_address);

CREATE TABLE IF NOT EXISTS onmi_swap_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT NOT NULL,
    wallet_name     TEXT,
    pair_address    TEXT,
    token_address   TEXT NOT NULL,
    token_symbol    TEXT,
    side            TEXT NOT NULL,         -- 'buy' (native→token) | 'sell' (token→native)
    amount_in_wei   TEXT,
    amount_out_wei  TEXT,
    min_out_wei     TEXT,
    tx_hash         TEXT,
    gas_used        INTEGER,
    status          TEXT NOT NULL,         -- pending|sent|arrived|failed
    error_message   TEXT,
    attempts        INTEGER DEFAULT 0,
    created_at      REAL,
    sent_at         REAL,
    confirmed_at    REAL,
    updated_at      REAL
);

CREATE INDEX IF NOT EXISTS idx_swap_history_wallet ON onmi_swap_history(wallet_address);
CREATE INDEX IF NOT EXISTS idx_swap_history_status ON onmi_swap_history(status);
"""


def init_database() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Pairs
# ---------------------------------------------------------------------------

def upsert_pair(*, pair_address: str, token_address: str, token_symbol: str,
                token_decimals: int, weth_address: str,
                reserve_native_wei: int, reserve_token_wei: int) -> None:
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO onmi_swap_known_pairs(
                    pair_address, token_address, token_symbol, token_decimals,
                    weth_address, reserve_native_wei, reserve_token_wei,
                    discovered_at, last_seen_at, disabled
                )
                VALUES(?,?,?,?,?,?,?,?,?,0)
                ON CONFLICT(pair_address) DO UPDATE SET
                    token_symbol      = excluded.token_symbol,
                    token_decimals    = excluded.token_decimals,
                    reserve_native_wei= excluded.reserve_native_wei,
                    reserve_token_wei = excluded.reserve_token_wei,
                    last_seen_at      = excluded.last_seen_at
                """,
                (pair_address.lower(), token_address.lower(),
                 token_symbol or "", int(token_decimals or 18),
                 weth_address.lower(),
                 str(int(reserve_native_wei)),
                 str(int(reserve_token_wei)),
                 now, now),
            )
            conn.commit()
        finally:
            conn.close()


def list_known_pairs(*, min_reserve_native_wei: int = 0,
                     only_enabled: bool = True) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            q = "SELECT * FROM onmi_swap_known_pairs"
            cond = []
            if only_enabled:
                cond.append("disabled = 0")
            if cond:
                q += " WHERE " + " AND ".join(cond)
            rows = conn.execute(q).fetchall()
        finally:
            conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["reserve_native_wei_int"] = int(d.get("reserve_native_wei") or 0)
            d["reserve_token_wei_int"] = int(d.get("reserve_token_wei") or 0)
        except Exception:
            d["reserve_native_wei_int"] = 0
            d["reserve_token_wei_int"] = 0
        if d["reserve_native_wei_int"] >= int(min_reserve_native_wei):
            out.append(d)
    return out


def known_pairs_count() -> int:
    with _lock:
        conn = _connect()
        try:
            r = conn.execute(
                "SELECT COUNT(*) c FROM onmi_swap_known_pairs"
            ).fetchone()
        finally:
            conn.close()
    return int(r["c"])


def disable_pair(pair_address: str) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE onmi_swap_known_pairs SET disabled=1 WHERE pair_address=?",
                (pair_address.lower(),),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def insert_swap(*, wallet_address: str, wallet_name: Optional[str],
                pair_address: Optional[str], token_address: str,
                token_symbol: str, side: str, amount_in_wei: int,
                min_out_wei: int) -> int:
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO onmi_swap_history(
                    wallet_address, wallet_name, pair_address, token_address,
                    token_symbol, side, amount_in_wei, min_out_wei,
                    status, attempts, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?, 'pending', 0, ?, ?)
                """,
                (wallet_address, wallet_name,
                 (pair_address or "").lower() or None,
                 token_address.lower(), token_symbol or "", side,
                 str(int(amount_in_wei)), str(int(min_out_wei)),
                 now, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_swap(swap_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [swap_id]
    with _lock:
        conn = _connect()
        try:
            conn.execute(f"UPDATE onmi_swap_history SET {cols} WHERE id=?", vals)
            conn.commit()
        finally:
            conn.close()


def list_swaps(limit: int = 1000) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM onmi_swap_history ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def reset_history() -> None:
    """Очищает только historiu — pair-кэш сохраняется."""
    with _lock:
        conn = _connect()
        try:
            conn.execute("DROP TABLE IF EXISTS onmi_swap_history")
            conn.commit()
        finally:
            conn.close()
    init_database()


def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            pairs_total = conn.execute(
                "SELECT COUNT(*) c FROM onmi_swap_known_pairs"
            ).fetchone()["c"]
            pairs_enabled = conn.execute(
                "SELECT COUNT(*) c FROM onmi_swap_known_pairs WHERE disabled=0"
            ).fetchone()["c"]
            total = conn.execute(
                "SELECT COUNT(*) c FROM onmi_swap_history"
            ).fetchone()["c"]
            by_status = conn.execute(
                "SELECT status, COUNT(*) c FROM onmi_swap_history GROUP BY status"
            ).fetchall()
            by_side = conn.execute(
                "SELECT side, COUNT(*) c FROM onmi_swap_history "
                "WHERE status='arrived' GROUP BY side"
            ).fetchall()
        finally:
            conn.close()
    stats = {
        "pairs_total": int(pairs_total),
        "pairs_enabled": int(pairs_enabled),
        "swaps_total": int(total),
    }
    for r in by_status:
        stats[f"status_{r['status']}"] = int(r["c"])
    for r in by_side:
        stats[f"side_{r['side']}"] = int(r["c"])
    return stats
