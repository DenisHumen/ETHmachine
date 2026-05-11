"""Web admin database — schema + CRUD for web_admin.db."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional

from config.modules.cfg_web import WEB_DB_PATH, WEB_SESSION_TTL_DAYS
from web.core.paths import ROOT

DB_PATH = ROOT / WEB_DB_PATH
_init_lock = threading.Lock()
_initialized = False


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _expires_in_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    init_database()
    c = sqlite3.connect(str(DB_PATH), timeout=10.0)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_database() -> None:
    """Idempotent создание схемы. Безопасно для concurrent calls."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), timeout=10.0)
        try:
            c.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS users (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    username        TEXT UNIQUE NOT NULL,
                    password_hash   TEXT NOT NULL,
                    password_salt   TEXT NOT NULL,
                    role            TEXT NOT NULL DEFAULT 'viewer',
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL,
                    last_login_at   TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id              TEXT PRIMARY KEY,
                    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at      TEXT NOT NULL,
                    last_seen_at    TEXT NOT NULL,
                    user_agent      TEXT,
                    ip              TEXT,
                    expires_at      TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

                CREATE TABLE IF NOT EXISTS audit_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts              TEXT NOT NULL,
                    user_id         INTEGER,
                    action          TEXT NOT NULL,
                    target          TEXT,
                    metadata        TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

                CREATE TABLE IF NOT EXISTS config_changes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         INTEGER NOT NULL,
                    path            TEXT NOT NULL,
                    ts              TEXT NOT NULL,
                    diff            TEXT NOT NULL,
                    restart_required INTEGER NOT NULL DEFAULT 0,
                    applied         INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_cc_path ON config_changes(path);

                CREATE TABLE IF NOT EXISTS runs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    module          TEXT NOT NULL,
                    started_at      TEXT NOT NULL,
                    ended_at        TEXT,
                    status          TEXT NOT NULL DEFAULT 'running',
                    pid             INTEGER,
                    run_token       TEXT NOT NULL UNIQUE
                );
                """
            )
            c.commit()
        finally:
            c.close()
        _initialized = True


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def count_users() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(username: str, password_hash: str, password_salt: str,
                role: str = "viewer") -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO users (username, password_hash, password_salt, role, "
            "is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (username, password_hash, password_salt, role, _utcnow()),
        )
        return int(cur.lastrowid)


def find_user_by_username(username: str) -> Optional[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        ).fetchone()


def find_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)
        ).fetchone()


def touch_user_login(user_id: int) -> None:
    with conn() as c:
        c.execute("UPDATE users SET last_login_at=? WHERE id=?", (_utcnow(), user_id))


def list_users() -> list[sqlite3.Row]:
    with conn() as c:
        return list(c.execute(
            "SELECT id, username, role, is_active, created_at, last_login_at "
            "FROM users ORDER BY id"
        ))


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(session_id: str, user_id: int, user_agent: str = "",
                   ip: str = "") -> None:
    now = _utcnow()
    with conn() as c:
        c.execute(
            "INSERT INTO sessions (id, user_id, created_at, last_seen_at, "
            "user_agent, ip, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, user_id, now, now, user_agent[:500], ip[:64],
             _expires_in_days(WEB_SESSION_TTL_DAYS)),
        )


def get_session(session_id: str) -> Optional[sqlite3.Row]:
    with conn() as c:
        row = c.execute(
            "SELECT s.*, u.username, u.role, u.is_active "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.id=? AND s.expires_at > ? AND u.is_active=1",
            (session_id, _utcnow()),
        ).fetchone()
        if row:
            c.execute("UPDATE sessions SET last_seen_at=? WHERE id=?",
                      (_utcnow(), session_id))
        return row


def delete_session(session_id: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def cleanup_expired_sessions() -> int:
    with conn() as c:
        cur = c.execute("DELETE FROM sessions WHERE expires_at <= ?", (_utcnow(),))
        return cur.rowcount


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def audit(action: str, target: str = "", user_id: Optional[int] = None,
          metadata: Optional[dict[str, Any]] = None) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO audit_log (ts, user_id, action, target, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (_utcnow(), user_id, action, target[:500],
             json.dumps(metadata, ensure_ascii=False) if metadata else None),
        )


def recent_audit(limit: int = 100) -> list[sqlite3.Row]:
    with conn() as c:
        return list(c.execute(
            "SELECT a.*, u.username FROM audit_log a "
            "LEFT JOIN users u ON u.id=a.user_id "
            "ORDER BY a.id DESC LIMIT ?", (limit,)
        ))


# ---------------------------------------------------------------------------
# Config changes
# ---------------------------------------------------------------------------

def record_config_change(user_id: int, path: str, diff: str,
                         restart_required: bool) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO config_changes (user_id, path, ts, diff, restart_required) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, path, _utcnow(), diff, 1 if restart_required else 0),
        )
        return int(cur.lastrowid)


def recent_config_changes(limit: int = 50) -> list[sqlite3.Row]:
    with conn() as c:
        return list(c.execute(
            "SELECT cc.*, u.username FROM config_changes cc "
            "LEFT JOIN users u ON u.id=cc.user_id "
            "ORDER BY cc.id DESC LIMIT ?", (limit,)
        ))


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def runs_start(module: str, run_token: str, pid: int) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO runs (module, started_at, status, pid, run_token) "
            "VALUES (?, ?, 'running', ?, ?)",
            (module, _utcnow(), pid, run_token),
        )
        return int(cur.lastrowid)


def runs_end(run_token: str, status: str = "done") -> None:
    with conn() as c:
        c.execute("UPDATE runs SET ended_at=?, status=? WHERE run_token=?",
                  (_utcnow(), status, run_token))


def runs_active() -> list[sqlite3.Row]:
    with conn() as c:
        return list(c.execute(
            "SELECT * FROM runs WHERE status='running' ORDER BY started_at DESC"
        ))


def runs_recent(limit: int = 30) -> list[sqlite3.Row]:
    with conn() as c:
        return list(c.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ))
