"""SQLite-схема для onmi-trade модуля.

Таблицы:
  onmi_known_tokens
      Список всех известных нам токенов, созданных на onmi.fun. Никогда не
      сбрасывается reset_trade_history() — токены копятся вечно. Источники:
        • coin_worker (после успешного createToken*) регистрирует свой токен.
        • init_database() сидит из onmi_coin_tasks (status='arrived').
        • Можно ручно через `register_token(...)`.

  onmi_trade_history
      Каждая buy/sell-операция: wallet × token × side × сумма × tx_hash.
      Lifecycle:
          pending → sent → arrived ✅
                          ↘ failed ❌
      Сбрасывается reset_trade_history(); known_tokens — НЕТ.
"""
from __future__ import annotations

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
                CREATE TABLE IF NOT EXISTS onmi_known_tokens (
                    address TEXT PRIMARY KEY,
                    symbol TEXT,
                    name TEXT,
                    creator_address TEXT,
                    source TEXT,
                    created_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    graduated INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS onmi_trade_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL,
                    wallet_name TEXT,
                    token_address TEXT NOT NULL,
                    token_symbol TEXT,
                    side TEXT NOT NULL,             -- 'buy' | 'sell'
                    amount_in_wei TEXT NOT NULL,    -- buy: zkLTC; sell: tokens
                    amount_out_wei TEXT,            -- buy: tokens; sell: zkLTC
                    tx_hash TEXT,
                    gas_used INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    sent_at REAL,
                    confirmed_at REAL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_onmi_trade_wallet "
                "ON onmi_trade_history(wallet_address)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_onmi_trade_token "
                "ON onmi_trade_history(token_address)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_onmi_trade_status "
                "ON onmi_trade_history(status)"
            )
            conn.commit()
        finally:
            conn.close()
    _seed_from_coin_tasks()


def _seed_from_coin_tasks() -> None:
    """Берём все token_address из onmi_coin_tasks (status='arrived')
    и регистрируем в onmi_known_tokens, если ещё нет."""
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            # таблица coin tasks могла ещё не существовать
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='onmi_coin_tasks'"
            ).fetchone()
            if not tables:
                return
            rows = conn.execute(
                "SELECT address, token_address, coin_symbol, coin_name "
                "FROM onmi_coin_tasks "
                "WHERE token_address IS NOT NULL AND token_address != ''"
            ).fetchall()
            for r in rows:
                addr = (r["token_address"] or "").strip()
                if not addr:
                    continue
                conn.execute("""
                    INSERT INTO onmi_known_tokens
                        (address, symbol, name, creator_address, source,
                         created_at, last_seen_at)
                    VALUES (?, ?, ?, ?, 'coin_tasks', ?, ?)
                    ON CONFLICT(address) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at,
                        symbol = COALESCE(onmi_known_tokens.symbol, excluded.symbol),
                        name = COALESCE(onmi_known_tokens.name, excluded.name),
                        creator_address = COALESCE(onmi_known_tokens.creator_address, excluded.creator_address)
                """, (
                    addr.lower(), r["coin_symbol"], r["coin_name"],
                    (r["address"] or "").lower(), now, now,
                ))
            conn.commit()
        finally:
            conn.close()


def register_token(
    *,
    address: str,
    symbol: Optional[str] = None,
    name: Optional[str] = None,
    creator_address: Optional[str] = None,
    source: str = "manual",
) -> None:
    """Добавить токен в onmi_known_tokens (или обновить last_seen_at)."""
    now = time.time()
    addr = (address or "").lower().strip()
    if not addr or not addr.startswith("0x") or len(addr) != 42:
        return
    with _lock:
        conn = _connect()
        try:
            conn.execute("""
                INSERT INTO onmi_known_tokens
                    (address, symbol, name, creator_address, source,
                     created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    symbol = COALESCE(onmi_known_tokens.symbol, excluded.symbol),
                    name = COALESCE(onmi_known_tokens.name, excluded.name),
                    creator_address = COALESCE(onmi_known_tokens.creator_address, excluded.creator_address)
            """, (
                addr, symbol, name,
                (creator_address or "").lower() or None,
                source, now, now,
            ))
            conn.commit()
        finally:
            conn.close()


def mark_token_graduated(address: str) -> None:
    """Помечаем токен как graduated → bonding-curve trades перестают работать."""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE onmi_known_tokens SET graduated = 1, last_seen_at = ? "
                "WHERE address = ?",
                (time.time(), (address or "").lower()),
            )
            conn.commit()
        finally:
            conn.close()


def list_known_tokens(include_graduated: bool = False) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            if include_graduated:
                rows = conn.execute(
                    "SELECT * FROM onmi_known_tokens ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM onmi_known_tokens WHERE graduated = 0 "
                    "ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def known_tokens_count() -> int:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) c FROM onmi_known_tokens"
            ).fetchone()
            return int(row["c"]) if row else 0
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Trade history
# ---------------------------------------------------------------------------

def insert_trade(
    *,
    wallet_address: str,
    wallet_name: Optional[str],
    token_address: str,
    token_symbol: Optional[str],
    side: str,                       # 'buy' | 'sell'
    amount_in_wei: int,
) -> int:
    now = time.time()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute("""
                INSERT INTO onmi_trade_history
                    (wallet_address, wallet_name, token_address, token_symbol,
                     side, amount_in_wei, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (
                (wallet_address or "").lower(), wallet_name,
                (token_address or "").lower(), token_symbol,
                side, str(int(amount_in_wei)), now, now,
            ))
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


def update_trade(trade_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [int(trade_id)]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE onmi_trade_history SET {sets} WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()


def list_trades(limit: int = 1000) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM onmi_trade_history "
                "ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            total_tokens = conn.execute(
                "SELECT COUNT(*) c FROM onmi_known_tokens"
            ).fetchone()["c"]
            graduated = conn.execute(
                "SELECT COUNT(*) c FROM onmi_known_tokens WHERE graduated = 1"
            ).fetchone()["c"]
            total = conn.execute(
                "SELECT COUNT(*) c FROM onmi_trade_history"
            ).fetchone()["c"]
            by_status = conn.execute(
                "SELECT status, COUNT(*) c FROM onmi_trade_history GROUP BY status"
            ).fetchall()
            by_side = conn.execute(
                "SELECT side, COUNT(*) c FROM onmi_trade_history "
                "WHERE status='arrived' GROUP BY side"
            ).fetchall()
        finally:
            conn.close()
    stats = {
        "known_tokens": int(total_tokens),
        "graduated": int(graduated),
        "trades_total": int(total),
    }
    for r in by_status:
        stats[f"status_{r['status']}"] = int(r["c"])
    for r in by_side:
        stats[f"side_{r['side']}"] = int(r["c"])
    return stats


def reset_trade_history() -> None:
    """Только trade-history. Known tokens НЕ удаляются."""
    with _lock:
        conn = _connect()
        try:
            conn.execute("DROP TABLE IF EXISTS onmi_trade_history")
            conn.commit()
        finally:
            conn.close()
    init_database()
