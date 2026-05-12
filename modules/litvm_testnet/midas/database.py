"""SQLite-схема для Midas Prediction Market (общая БД db/litvm.db).

Таблицы (все с префиксом `midas_`):
  midas_wallets         — состояние per-wallet (статус, jwt-кэш, nickname).
  midas_faucet_claims   — лог запросов фaucet (USDC / native).
  midas_checkins        — лог daily check-in.
  midas_bets            — план/факт каждой ставки (PK id, status, tx).

Конвенция AGENTS.md §5: «каждая операция открывает свой connection».
Используем шаренный helper `modules.litvm_testnet.database.connect`.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

from modules.litvm_testnet.database import connect as _connect


_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_database() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS midas_wallets (
                    address TEXT PRIMARY KEY,
                    name TEXT,
                    nickname TEXT,
                    jwt_token TEXT,
                    jwt_obtained_at REAL,
                    registered INTEGER NOT NULL DEFAULT 0,
                    last_usdc_faucet_at REAL,
                    last_native_faucet_at REAL,
                    last_checkin_at REAL,
                    last_checkin_day TEXT,
                    bets_planned INTEGER NOT NULL DEFAULT 0,
                    bets_completed INTEGER NOT NULL DEFAULT 0,
                    bets_failed INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS midas_faucet_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response TEXT,
                    error_message TEXT,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_midas_faucet_addr "
                "ON midas_faucet_claims(address)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS midas_checkins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    status TEXT NOT NULL,
                    streak INTEGER,
                    response TEXT,
                    error_message TEXT,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_midas_checkin_addr "
                "ON midas_checkins(address)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS midas_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    market_address TEXT NOT NULL,
                    market_title TEXT,
                    outcome_index INTEGER NOT NULL,
                    amount_usdc_raw TEXT NOT NULL,
                    amount_usdc_human REAL NOT NULL,
                    shares TEXT,
                    max_cost_raw TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    approve_tx_hash TEXT,
                    buy_tx_hash TEXT,
                    gas_used INTEGER,
                    error_message TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    sent_at REAL,
                    confirmed_at REAL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_midas_bets_addr "
                "ON midas_bets(address)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_midas_bets_status "
                "ON midas_bets(status)"
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------

def upsert_wallet(address: str, name: Optional[str] = None) -> None:
    addr = address.lower()
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            conn.execute("""
                INSERT INTO midas_wallets (address, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    name = COALESCE(excluded.name, name),
                    updated_at = excluded.updated_at
            """, (addr, name, now, now))
            conn.commit()
        finally:
            conn.close()


def update_wallet(address: str, **fields) -> None:
    if not fields:
        return
    addr = address.lower()
    fields["updated_at"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [addr]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE midas_wallets SET {sets} WHERE address = ?", values
            )
            conn.commit()
        finally:
            conn.close()


def get_wallet(address: str) -> Optional[dict]:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM midas_wallets WHERE address = ?",
                (address.lower(),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def list_all_wallets() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM midas_wallets ORDER BY address ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def recompute_wallet_counters(address: str) -> dict:
    """Пересчитывает bets_completed/bets_failed/status кошелька."""
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            c = conn.execute("""
                SELECT
                    SUM(CASE WHEN status='confirmed' THEN 1 ELSE 0 END) AS done,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS fail,
                    COUNT(*) AS total
                FROM midas_bets WHERE address = ?
            """, (addr,)).fetchone()
            done = int(c["done"] or 0)
            fail = int(c["fail"] or 0)
            total = int(c["total"] or 0)
            wallet = conn.execute(
                "SELECT bets_planned, status, registered FROM midas_wallets "
                "WHERE address = ?",
                (addr,),
            ).fetchone()
            planned = int((wallet["bets_planned"] if wallet else 0) or total)
            registered = int((wallet["registered"] if wallet else 0) or 0)
            cur_status = wallet["status"] if wallet else "pending"
            if planned > 0 and done + fail >= planned:
                new_status = "completed" if fail == 0 else "failed"
            elif done + fail > 0:
                new_status = "in_progress"
            elif registered:
                new_status = "registered"
            else:
                new_status = cur_status or "pending"
            conn.execute(
                "UPDATE midas_wallets SET bets_completed=?, bets_failed=?, "
                "status=?, updated_at=? WHERE address=?",
                (done, fail, new_status, time.time(), addr),
            )
            conn.commit()
            return {"planned": planned, "completed": done, "failed": fail,
                    "total": total, "status": new_status}
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Faucet
# ---------------------------------------------------------------------------

def log_faucet_claim(address: str, kind: str, status: str,
                     response: Optional[str] = None,
                     error_message: Optional[str] = None) -> int:
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO midas_faucet_claims "
                "(address, kind, status, response, error_message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (address.lower(), kind, status, response, error_message,
                 time.time()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def list_all_faucet_claims() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM midas_faucet_claims ORDER BY id ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Check-in
# ---------------------------------------------------------------------------

def log_checkin(address: str, status: str, streak: Optional[int] = None,
                response: Optional[str] = None,
                error_message: Optional[str] = None) -> int:
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "INSERT INTO midas_checkins "
                "(address, status, streak, response, error_message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (address.lower(), status, streak, response, error_message,
                 time.time()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def list_all_checkins() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM midas_checkins ORDER BY id ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Bets
# ---------------------------------------------------------------------------

def insert_bet(record: dict) -> int:
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute("""
                INSERT INTO midas_bets
                    (address, market_address, market_title, outcome_index,
                     amount_usdc_raw, amount_usdc_human, status,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (
                record["address"].lower(),
                record["market_address"].lower(),
                record.get("market_title"),
                int(record["outcome_index"]),
                str(record["amount_usdc_raw"]),
                float(record["amount_usdc_human"]),
                now, now,
            ))
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_bet(bet_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [int(bet_id)]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE midas_bets SET {sets} WHERE id = ?", values
            )
            conn.commit()
        finally:
            conn.close()


def list_bets_for_wallet(address: str) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM midas_bets WHERE address = ? ORDER BY id ASC",
                (address.lower(),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def list_pending_bets_for_wallet(address: str) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM midas_bets WHERE address = ? "
                "AND status IN ('pending', 'sending', 'approved') "
                "ORDER BY id ASC",
                (address.lower(),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def list_all_bets() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM midas_bets "
                "ORDER BY address ASC, id ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Stats / Reset
# ---------------------------------------------------------------------------

def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            wt = conn.execute(
                "SELECT status, COUNT(*) c FROM midas_wallets GROUP BY status"
            ).fetchall()
            bt = conn.execute(
                "SELECT status, COUNT(*) c FROM midas_bets GROUP BY status"
            ).fetchall()
            wallet_total = conn.execute(
                "SELECT COUNT(*) c FROM midas_wallets"
            ).fetchone()["c"]
            bet_total = conn.execute(
                "SELECT COUNT(*) c FROM midas_bets"
            ).fetchone()["c"]
            registered = conn.execute(
                "SELECT COUNT(*) c FROM midas_wallets WHERE registered=1"
            ).fetchone()["c"]
            faucet_total = conn.execute(
                "SELECT COUNT(*) c FROM midas_faucet_claims"
            ).fetchone()["c"]
            faucet_success = conn.execute(
                "SELECT COUNT(*) c FROM midas_faucet_claims WHERE status='success'"
            ).fetchone()["c"]
            checkin_total = conn.execute(
                "SELECT COUNT(*) c FROM midas_checkins"
            ).fetchone()["c"]
            checkin_success = conn.execute(
                "SELECT COUNT(*) c FROM midas_checkins WHERE status='success'"
            ).fetchone()["c"]
        finally:
            conn.close()
    stats = {
        "wallet_total": int(wallet_total),
        "wallet_registered": int(registered),
        "bet_total": int(bet_total),
        "faucet_total": int(faucet_total),
        "faucet_success": int(faucet_success),
        "checkin_total": int(checkin_total),
        "checkin_success": int(checkin_success),
    }
    for r in wt:
        stats[f"wallet_{r['status']}"] = int(r["c"])
    for r in bt:
        stats[f"bet_{r['status']}"] = int(r["c"])
    return stats


def reset_tasks() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM midas_bets")
            conn.execute("DELETE FROM midas_checkins")
            conn.execute("DELETE FROM midas_faucet_claims")
            conn.execute("DELETE FROM midas_wallets")
            conn.commit()
        finally:
            conn.close()
