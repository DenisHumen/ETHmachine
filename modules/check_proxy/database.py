"""SQLite-хранилище запусков, задач и подробных результатов проверки прокси."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_DIR = PROJECT_ROOT / "db"
DB_PATH = DB_DIR / "proxy_checker.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    level         INTEGER NOT NULL,
    threads       INTEGER NOT NULL,
    total         INTEGER NOT NULL,
    completed     INTEGER NOT NULL DEFAULT 0,
    working       INTEGER NOT NULL DEFAULT 0,
    partial       INTEGER NOT NULL DEFAULT 0,
    broken        INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running',
    excel_path    TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    proxy         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending/running/done/failed
    overall       TEXT,                              -- WORKING/PARTIAL/BROKEN/INVALID
    score         REAL,
    country       TEXT,
    city          TEXT,
    asn           TEXT,
    ip            TEXT,
    avg_latency   REAL,
    jitter_ms     REAL,
    download_kbps REAL,
    failed_stage  TEXT,
    error         TEXT,
    started_at    TEXT,
    finished_at   TEXT,
    details_json  TEXT
);

CREATE TABLE IF NOT EXISTS service_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL,
    task_id       INTEGER NOT NULL,
    proxy         TEXT NOT NULL,
    category      TEXT NOT NULL,
    name          TEXT NOT NULL,
    url           TEXT NOT NULL,
    status        TEXT NOT NULL,             -- OK/BLOCKED/ERROR/TIMEOUT
    status_code   INTEGER,
    latency_ms    REAL,
    dns_ms        REAL,
    tcp_proxy_ms  REAL,
    proxy_connect_ms REAL,
    tls_target_ms REAL,
    ttfb_ms       REAL,
    download_ms   REAL,
    bytes_received INTEGER,
    failed_stage  TEXT,
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_run    ON tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_svc_run      ON service_results(run_id);
CREATE INDEX IF NOT EXISTS idx_svc_task     ON service_results(task_id);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ProxyCheckerDB:
    """Тонкая обёртка вокруг SQLite со встроенной блокировкой для многопоточности."""

    def __init__(self, path: Path = DB_PATH) -> None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---------- runs ----------
    def create_run(self, level: int, threads: int, proxies: List[str]) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO runs (started_at, level, threads, total) VALUES (?,?,?,?)",
                (_now(), level, threads, len(proxies)),
            )
            run_id = cur.lastrowid
            self._conn.executemany(
                "INSERT INTO tasks (run_id, idx, proxy) VALUES (?,?,?)",
                [(run_id, i + 1, p) for i, p in enumerate(proxies)],
            )
            self._conn.commit()
        return run_id

    def finalize_run(self, run_id: int, working: int, partial: int, broken: int,
                     excel_path: Optional[str] = None, status: str = "completed") -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE runs SET finished_at=?, working=?, partial=?, broken=?,
                                   excel_path=?, status=? WHERE id=?""",
                (_now(), working, partial, broken, excel_path, status, run_id),
            )
            self._conn.commit()

    def increment_completed(self, run_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET completed = completed + 1 WHERE id=?", (run_id,)
            )
            self._conn.commit()

    # ---------- tasks ----------
    def get_task_id(self, run_id: int, proxy_idx: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM tasks WHERE run_id=? AND idx=?", (run_id, proxy_idx)
            ).fetchone()
        return int(row[0]) if row else -1

    def mark_task_running(self, task_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET status='running', started_at=? WHERE id=?",
                (_now(), task_id),
            )
            self._conn.commit()

    def save_task_result(self, task_id: int, run_id: int, summary: Dict[str, Any]) -> None:
        details = json.dumps(summary.get("details", {}), ensure_ascii=False, default=str)
        with self._lock:
            self._conn.execute(
                """UPDATE tasks SET
                       status='done', overall=?, score=?, country=?, city=?, asn=?,
                       ip=?, avg_latency=?, jitter_ms=?, download_kbps=?,
                       failed_stage=?, error=?, finished_at=?, details_json=?
                   WHERE id=?""",
                (
                    summary.get("overall"),
                    summary.get("score"),
                    summary.get("country"),
                    summary.get("city"),
                    summary.get("asn"),
                    summary.get("ip"),
                    summary.get("avg_latency"),
                    summary.get("jitter_ms"),
                    summary.get("download_kbps"),
                    summary.get("failed_stage"),
                    summary.get("error"),
                    _now(),
                    details,
                    task_id,
                ),
            )
            self._conn.commit()

    def save_service_results(self, task_id: int, run_id: int, proxy: str,
                             rows: Iterable[Dict[str, Any]]) -> None:
        payload = [
            (
                run_id, task_id, proxy,
                r.get("category"), r.get("name"), r.get("url"),
                r.get("status"), r.get("status_code"),
                r.get("latency_ms"),
                r.get("dns_ms"), r.get("tcp_proxy_ms"), r.get("proxy_connect_ms"),
                r.get("tls_target_ms"), r.get("ttfb_ms"), r.get("download_ms"),
                r.get("bytes_received"),
                r.get("failed_stage"), r.get("error"),
            )
            for r in rows
        ]
        if not payload:
            return
        with self._lock:
            self._conn.executemany(
                """INSERT INTO service_results (
                       run_id, task_id, proxy, category, name, url,
                       status, status_code, latency_ms,
                       dns_ms, tcp_proxy_ms, proxy_connect_ms, tls_target_ms,
                       ttfb_ms, download_ms, bytes_received,
                       failed_stage, error
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                payload,
            )
            self._conn.commit()

    # ---------- queries for export ----------
    def fetch_run(self, run_id: int) -> Dict[str, Any]:
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            row = self._conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            self._conn.row_factory = None
        return dict(row) if row else {}

    def fetch_tasks(self, run_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE run_id=? ORDER BY idx", (run_id,)
            ).fetchall()
            self._conn.row_factory = None
        return [dict(r) for r in rows]

    def fetch_service_results(self, run_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            rows = self._conn.execute(
                "SELECT * FROM service_results WHERE run_id=? ORDER BY task_id, category, name",
                (run_id,),
            ).fetchall()
            self._conn.row_factory = None
        return [dict(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
