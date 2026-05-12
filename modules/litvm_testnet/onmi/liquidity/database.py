"""Persistent storage для модуля Liquidity.

Tables:
  • onmi_lp_positions — текущая позиция (wallet × pair). Хранит cumulative
    суммы внесённого/выведенного и текущий LP-balance (по последней проверке).
    **Никогда** не удаляется при reset.
  • onmi_lp_history — каждый add/remove c tx_hash, gas, status, error.
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


_SCHEMA = """
CREATE TABLE IF NOT EXISTS onmi_lp_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT NOT NULL,
    pair_address    TEXT NOT NULL,
    token_address   TEXT NOT NULL,
    token_symbol    TEXT,
    total_added_eth_wei     TEXT DEFAULT '0',
    total_added_token_wei   TEXT DEFAULT '0',
    total_removed_eth_wei   TEXT DEFAULT '0',
    total_removed_token_wei TEXT DEFAULT '0',
    lp_acquired_wei         TEXT DEFAULT '0',
    lp_removed_wei          TEXT DEFAULT '0',
    first_action_at REAL,
    last_action_at  REAL,
    UNIQUE(wallet_address, pair_address)
);

CREATE INDEX IF NOT EXISTS idx_lp_positions_wallet
  ON onmi_lp_positions(wallet_address);

CREATE TABLE IF NOT EXISTS onmi_lp_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address  TEXT NOT NULL,
    wallet_name     TEXT,
    pair_address    TEXT NOT NULL,
    token_address   TEXT NOT NULL,
    token_symbol    TEXT,
    side            TEXT NOT NULL,        -- 'add' | 'remove'
    amount_eth_wei  TEXT,
    amount_token_wei TEXT,
    lp_tokens_wei   TEXT,
    tx_hash         TEXT,
    gas_used        INTEGER,
    status          TEXT NOT NULL,        -- pending|sent|arrived|failed
    error_message   TEXT,
    attempts        INTEGER DEFAULT 0,
    created_at      REAL,
    sent_at         REAL,
    confirmed_at    REAL,
    updated_at      REAL
);

CREATE INDEX IF NOT EXISTS idx_lp_history_wallet
  ON onmi_lp_history(wallet_address);
CREATE INDEX IF NOT EXISTS idx_lp_history_status
  ON onmi_lp_history(status);
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
# Positions
# ---------------------------------------------------------------------------

def _get_position(conn, wallet: str, pair: str):
    return conn.execute(
        "SELECT * FROM onmi_lp_positions WHERE wallet_address=? AND pair_address=?",
        (wallet.lower(), pair.lower()),
    ).fetchone()


def upsert_position_after_add(
    *, wallet_address: str, pair_address: str, token_address: str,
    token_symbol: str, eth_added_wei: int, token_added_wei: int,
    lp_received_wei: int,
) -> None:
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            row = _get_position(conn, wallet_address, pair_address)
            if row is None:
                conn.execute(
                    """
                    INSERT INTO onmi_lp_positions(
                        wallet_address, pair_address, token_address,
                        token_symbol, total_added_eth_wei,
                        total_added_token_wei, lp_acquired_wei,
                        first_action_at, last_action_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (wallet_address.lower(), pair_address.lower(),
                     token_address.lower(), token_symbol or "",
                     str(int(eth_added_wei)), str(int(token_added_wei)),
                     str(int(lp_received_wei)), now, now),
                )
            else:
                new_eth = int(row["total_added_eth_wei"] or 0) + int(eth_added_wei)
                new_tok = int(row["total_added_token_wei"] or 0) + int(token_added_wei)
                new_lp = int(row["lp_acquired_wei"] or 0) + int(lp_received_wei)
                conn.execute(
                    """
                    UPDATE onmi_lp_positions
                    SET total_added_eth_wei=?,
                        total_added_token_wei=?,
                        lp_acquired_wei=?,
                        token_symbol=COALESCE(NULLIF(token_symbol,''), ?),
                        last_action_at=?
                    WHERE id=?
                    """,
                    (str(new_eth), str(new_tok), str(new_lp),
                     token_symbol or "", now, row["id"]),
                )
            conn.commit()
        finally:
            conn.close()


def upsert_position_after_remove(
    *, wallet_address: str, pair_address: str, token_address: str,
    token_symbol: str, eth_received_wei: int, token_received_wei: int,
    lp_burned_wei: int,
) -> None:
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            row = _get_position(conn, wallet_address, pair_address)
            if row is None:
                conn.execute(
                    """
                    INSERT INTO onmi_lp_positions(
                        wallet_address, pair_address, token_address,
                        token_symbol, total_removed_eth_wei,
                        total_removed_token_wei, lp_removed_wei,
                        first_action_at, last_action_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (wallet_address.lower(), pair_address.lower(),
                     token_address.lower(), token_symbol or "",
                     str(int(eth_received_wei)), str(int(token_received_wei)),
                     str(int(lp_burned_wei)), now, now),
                )
            else:
                new_eth = int(row["total_removed_eth_wei"] or 0) + int(eth_received_wei)
                new_tok = int(row["total_removed_token_wei"] or 0) + int(token_received_wei)
                new_lp = int(row["lp_removed_wei"] or 0) + int(lp_burned_wei)
                conn.execute(
                    """
                    UPDATE onmi_lp_positions
                    SET total_removed_eth_wei=?,
                        total_removed_token_wei=?,
                        lp_removed_wei=?,
                        token_symbol=COALESCE(NULLIF(token_symbol,''), ?),
                        last_action_at=?
                    WHERE id=?
                    """,
                    (str(new_eth), str(new_tok), str(new_lp),
                     token_symbol or "", now, row["id"]),
                )
            conn.commit()
        finally:
            conn.close()


def list_positions(*, wallet_address: Optional[str] = None,
                   with_lp_only: bool = False) -> list[dict]:
    """Возвращает позиции из БД. Поле lp_net_wei = acquired - removed."""
    with _lock:
        conn = _connect()
        try:
            q = "SELECT * FROM onmi_lp_positions"
            args: list = []
            if wallet_address:
                q += " WHERE wallet_address=?"
                args.append(wallet_address.lower())
            rows = conn.execute(q, args).fetchall()
        finally:
            conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            acq = int(d.get("lp_acquired_wei") or 0)
            rem = int(d.get("lp_removed_wei") or 0)
        except Exception:
            acq = rem = 0
        d["lp_net_wei"] = max(0, acq - rem)
        if with_lp_only and d["lp_net_wei"] <= 0:
            continue
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def insert_history(*, wallet_address: str, wallet_name: Optional[str],
                   pair_address: str, token_address: str,
                   token_symbol: str, side: str,
                   amount_eth_wei: int, amount_token_wei: int,
                   lp_tokens_wei: int) -> int:
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO onmi_lp_history(
                    wallet_address, wallet_name, pair_address, token_address,
                    token_symbol, side, amount_eth_wei, amount_token_wei,
                    lp_tokens_wei, status, attempts, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?, 'pending', 0, ?, ?)
                """,
                (wallet_address, wallet_name, pair_address.lower(),
                 token_address.lower(), token_symbol or "", side,
                 str(int(amount_eth_wei)), str(int(amount_token_wei)),
                 str(int(lp_tokens_wei)), now, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_history(history_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [history_id]
    with _lock:
        conn = _connect()
        try:
            conn.execute(f"UPDATE onmi_lp_history SET {cols} WHERE id=?", vals)
            conn.commit()
        finally:
            conn.close()


def list_history(limit: int = 10_000) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM onmi_lp_history ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def reset_history() -> None:
    """Чистит **только** history. positions сохраняются."""
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM onmi_lp_history")
            conn.commit()
        finally:
            conn.close()


def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            positions_total = conn.execute(
                "SELECT COUNT(*) c FROM onmi_lp_positions"
            ).fetchone()["c"]
            history_total = conn.execute(
                "SELECT COUNT(*) c FROM onmi_lp_history"
            ).fetchone()["c"]
            by_status = conn.execute(
                "SELECT status, COUNT(*) c FROM onmi_lp_history GROUP BY status"
            ).fetchall()
            by_side = conn.execute(
                "SELECT side, COUNT(*) c FROM onmi_lp_history "
                "WHERE status='arrived' GROUP BY side"
            ).fetchall()
        finally:
            conn.close()
    stats = {
        "positions_total": int(positions_total),
        "history_total": int(history_total),
    }
    for r in by_status:
        stats[f"status_{r['status']}"] = int(r["c"])
    for r in by_side:
        stats[f"side_{r['side']}"] = int(r["c"])
    return stats
