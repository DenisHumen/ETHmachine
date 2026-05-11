"""Read-only SQLite explorer for db/*.db files."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from web.core.paths import DB_DIR, safe_under


SAFE_DB_RE = re.compile(r"^[A-Za-z0-9._-]+\.db$")
SAFE_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def list_databases() -> list[dict[str, Any]]:
    out = []
    if not DB_DIR.exists():
        return out
    for p in sorted(DB_DIR.iterdir()):
        if p.is_file() and p.suffix == ".db" and SAFE_DB_RE.match(p.name):
            out.append({"name": p.name, "size": p.stat().st_size})
    return out


def _open_ro(name: str) -> sqlite3.Connection:
    if not SAFE_DB_RE.match(name):
        raise ValueError("invalid db name")
    target = (DB_DIR / name)
    if not safe_under(DB_DIR, target) or not target.exists():
        raise FileNotFoundError(name)
    # Open read-only via URI
    uri = f"file:{target.as_posix()}?mode=ro"
    c = sqlite3.connect(uri, uri=True, timeout=5.0)
    c.row_factory = sqlite3.Row
    return c


def list_tables(db_name: str) -> list[str]:
    with _open_ro(db_name) as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [r["name"] for r in rows]


def table_info(db_name: str, table: str) -> dict[str, Any]:
    if not SAFE_TABLE_RE.match(table):
        raise ValueError("invalid table name")
    with _open_ro(db_name) as c:
        # whitelist check
        existing = {r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()}
        if table not in existing:
            raise FileNotFoundError(f"table {table} not in {db_name}")
        cols = [dict(r) for r in c.execute(f'PRAGMA table_info("{table}")').fetchall()]
        cnt = c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return {"columns": cols, "count": int(cnt)}


def fetch_rows(db_name: str, table: str, limit: int = 100,
               offset: int = 0) -> tuple[list[str], list[list[Any]]]:
    if not SAFE_TABLE_RE.match(table):
        raise ValueError("invalid table name")
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with _open_ro(db_name) as c:
        existing = {r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()}
        if table not in existing:
            raise FileNotFoundError(f"table {table} not in {db_name}")
        cur = c.execute(f'SELECT * FROM "{table}" LIMIT ? OFFSET ?', (limit, offset))
        cols = [d[0] for d in cur.description]
        rows = [list(r) for r in cur.fetchall()]
    return cols, rows
