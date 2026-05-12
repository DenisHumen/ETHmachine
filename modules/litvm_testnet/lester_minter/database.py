"""SQLite-схема для Lester Minter (общая БД db/litvm.db).

Таблицы:
  minter_wallet_tasks — состояние per-wallet (план + счётчики).
  minter_deployments  — лог каждого деплоя (план + результат).
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
                CREATE TABLE IF NOT EXISTS minter_wallet_tasks (
                    address TEXT PRIMARY KEY,
                    name TEXT,
                    planned INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS minter_deployments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    tx_index INTEGER NOT NULL,
                    token_name TEXT NOT NULL,
                    token_symbol TEXT NOT NULL,
                    decimals INTEGER NOT NULL,
                    total_supply TEXT NOT NULL,
                    mintable INTEGER NOT NULL,
                    burnable INTEGER NOT NULL,
                    pausable INTEGER NOT NULL,
                    logo_url TEXT,
                    fee_wei TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    tx_hash TEXT,
                    token_address TEXT,
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
                "CREATE INDEX IF NOT EXISTS idx_minter_deploy_addr "
                "ON minter_deployments(address)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_minter_deploy_status "
                "ON minter_deployments(status)"
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Wallet tasks
# ---------------------------------------------------------------------------

def upsert_wallet(address: str, name: Optional[str] = None) -> None:
    addr = address.lower()
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            conn.execute("""
                INSERT INTO minter_wallet_tasks
                    (address, name, created_at, updated_at)
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
                f"UPDATE minter_wallet_tasks SET {sets} WHERE address = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()


def get_wallet(address: str) -> Optional[dict]:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM minter_wallet_tasks WHERE address = ?",
                (address.lower(),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def recompute_wallet_counters(address: str) -> dict:
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            counts = conn.execute("""
                SELECT
                    SUM(CASE WHEN status='confirmed' THEN 1 ELSE 0 END) AS done,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS fail,
                    COUNT(*) AS total
                FROM minter_deployments WHERE address = ?
            """, (addr,)).fetchone()
            done = int(counts["done"] or 0)
            fail = int(counts["fail"] or 0)
            total = int(counts["total"] or 0)
            # planned remains as is from wallet task; status derived
            wallet = conn.execute(
                "SELECT planned, status FROM minter_wallet_tasks WHERE address = ?",
                (addr,),
            ).fetchone()
            planned = int((wallet["planned"] if wallet else 0) or total)
            if done + fail >= planned and planned > 0:
                new_status = "completed" if fail == 0 else "failed"
            elif done + fail > 0:
                new_status = "in_progress"
            else:
                new_status = (wallet["status"] if wallet else "pending") or "pending"
            conn.execute("""
                UPDATE minter_wallet_tasks
                SET completed = ?, failed = ?, status = ?, updated_at = ?
                WHERE address = ?
            """, (done, fail, new_status, time.time(), addr))
            conn.commit()
            return {"planned": planned, "completed": done, "failed": fail,
                    "total": total, "status": new_status}
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Deployment tasks
# ---------------------------------------------------------------------------

def insert_deployment(record: dict) -> int:
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute("""
                INSERT INTO minter_deployments
                    (address, tx_index, token_name, token_symbol, decimals,
                     total_supply, mintable, burnable, pausable, logo_url,
                     fee_wei, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (
                record["address"].lower(), int(record["tx_index"]),
                record["token_name"], record["token_symbol"],
                int(record["decimals"]), str(record["total_supply"]),
                int(bool(record["mintable"])), int(bool(record["burnable"])),
                int(bool(record["pausable"])), record.get("logo_url"),
                str(record.get("fee_wei", 0)),
                now, now,
            ))
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_deployment(dep_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [int(dep_id)]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE minter_deployments SET {sets} WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()


def list_deployments_for_wallet(address: str) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM minter_deployments WHERE address = ? "
                "ORDER BY tx_index ASC, id ASC",
                (address.lower(),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def list_pending_for_wallet(address: str) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM minter_deployments WHERE address = ? "
                "AND status IN ('pending', 'sending') "
                "ORDER BY tx_index ASC, id ASC",
                (address.lower(),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def used_symbols_for_wallet(address: str) -> set[str]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT token_symbol FROM minter_deployments WHERE address = ?",
                (address.lower(),),
            ).fetchall()
            return {(r["token_symbol"] or "").upper() for r in rows}
        finally:
            conn.close()


def list_all_deployments() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM minter_deployments "
                "ORDER BY address ASC, tx_index ASC, id ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def list_all_wallets() -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM minter_wallet_tasks ORDER BY address ASC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            wt = conn.execute(
                "SELECT status, COUNT(*) c FROM minter_wallet_tasks GROUP BY status"
            ).fetchall()
            dt = conn.execute(
                "SELECT status, COUNT(*) c FROM minter_deployments GROUP BY status"
            ).fetchall()
            wallet_total = conn.execute(
                "SELECT COUNT(*) c FROM minter_wallet_tasks"
            ).fetchone()["c"]
            dep_total = conn.execute(
                "SELECT COUNT(*) c FROM minter_deployments"
            ).fetchone()["c"]
        finally:
            conn.close()
    stats = {"wallet_total": int(wallet_total), "deploy_total": int(dep_total)}
    for r in wt:
        stats[f"wallet_{r['status']}"] = int(r["c"])
    for r in dt:
        stats[f"deploy_{r['status']}"] = int(r["c"])
    return stats


def reset_tasks() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM minter_deployments")
            conn.execute("DELETE FROM minter_wallet_tasks")
            conn.commit()
        finally:
            conn.close()
