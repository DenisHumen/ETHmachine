"""LiteForge (litvm_testnet) — общая БД проекта.

Все таблицы проекта (faucet, будущие пресеты — свапы, daily-action и т.п.)
живут в одном файле `db/litvm.db`. Пресеты подключают свои таблицы и работают
с ними сами; здесь — то, что общее для всего проекта (cookie-кэш Vercel BotID,
shared утилиты).

Конвенция AGENTS.md §5.1 («db/<module>.db на каждый модуль») для litvm_testnet
осознанно нарушена — проект мультипресетный и состояние шарится.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent.parent / "db" / "litvm.db"

_lock = threading.Lock()


def connect() -> sqlite3.Connection:
    """Открыть подключение к общей БД (WAL, Row-фабрика).
    Каждый поток получает своё подключение, как требует AGENTS.md §5.1."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    """Создаёт project-level таблицы. Пресет вызывает свой init после этого."""
    with _lock:
        conn = connect()
        try:
            # Кэш cookie `_vcrcs` (Vercel BotID), привязан к прокси.
            # proxy='' — пустой ключ означает "без прокси" (direct connection).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vcrcs_cookies (
                    proxy TEXT PRIMARY KEY,
                    cookie TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT,
                    user_agent TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# vcrcs_cookies
# ---------------------------------------------------------------------------

def _normalize_proxy_key(proxy: Optional[str]) -> str:
    """Канонизирует ключ proxy: пусто → '', strip whitespace, lower-case схема."""
    return (proxy or "").strip()


def get_vcrcs(proxy: Optional[str]) -> Optional[dict]:
    """Возвращает dict {cookie, fetched_at, expires_at, user_agent} или None.
    Не проверяет TTL — это делает caller (cookie_is_fresh)."""
    key = _normalize_proxy_key(proxy)
    with _lock:
        conn = connect()
        try:
            row = conn.execute(
                "SELECT cookie, fetched_at, expires_at, user_agent "
                "FROM vcrcs_cookies WHERE proxy = ?",
                (key,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def save_vcrcs(proxy: Optional[str], cookie: str,
               expires_at: Optional[datetime] = None,
               user_agent: Optional[str] = None) -> None:
    """Сохранить/обновить cookie для прокси."""
    key = _normalize_proxy_key(proxy)
    now_iso = datetime.now(timezone.utc).isoformat()
    exp_iso = expires_at.astimezone(timezone.utc).isoformat() if expires_at else None
    with _lock:
        conn = connect()
        try:
            conn.execute(
                "INSERT INTO vcrcs_cookies (proxy, cookie, fetched_at, expires_at, user_agent) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(proxy) DO UPDATE SET "
                "  cookie = excluded.cookie, "
                "  fetched_at = excluded.fetched_at, "
                "  expires_at = excluded.expires_at, "
                "  user_agent = excluded.user_agent",
                (key, cookie, now_iso, exp_iso, user_agent),
            )
            conn.commit()
        finally:
            conn.close()


def invalidate_vcrcs(proxy: Optional[str]) -> None:
    """Удалить cookie для прокси (например, после 429 от хаба)."""
    key = _normalize_proxy_key(proxy)
    with _lock:
        conn = connect()
        try:
            conn.execute("DELETE FROM vcrcs_cookies WHERE proxy = ?", (key,))
            conn.commit()
        finally:
            conn.close()


def cookie_is_fresh(record: dict, safety_margin_sec: int = 60) -> bool:
    """True если cookie ещё не истекла. Если expires_at пусто — считаем свежей
    (decay контролируется отдельно). safety_margin_sec — отступ перед истечением."""
    exp = record.get("expires_at") if record else None
    if not exp:
        return True
    try:
        dt = datetime.fromisoformat(exp)
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) + timedelta(seconds=safety_margin_sec) < dt
