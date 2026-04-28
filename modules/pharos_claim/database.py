"""SQLite-база для Pharos Claim Checker.

Таблицы:
  claim_runs  — запуски чекера (id, started_at, finished_at, total, eligible, not_eligible, failed)
  claim_tasks — задачи на кошелёк (pending/running/completed/failed) с результатами
"""
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_FILE = str(Path(__file__).parent.parent.parent / "db" / "pharos_claim.db")

_db_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS claim_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            total INTEGER DEFAULT 0,
            eligible INTEGER DEFAULT 0,
            not_eligible INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS claim_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            wallet_index INTEGER NOT NULL,
            account_name TEXT,
            address TEXT NOT NULL,
            proxy TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            eligible INTEGER,
            amount TEXT,
            claimed INTEGER,
            tiers TEXT,
            raw_response TEXT,
            endpoint TEXT,
            error TEXT,
            started_at TEXT,
            finished_at TEXT,
            FOREIGN KEY (run_id) REFERENCES claim_runs(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_claim_tasks_run ON claim_tasks(run_id, status)")
    # ── Колонки для on-chain клейма (ALTER TABLE с защитой от повторного добавления)
    existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(claim_tasks)").fetchall()}
    for col, ddl in (
        ("claim_status",        "TEXT"),    # pending / claimed / failed / skipped
        ("claim_tx_hash",       "TEXT"),
        ("claim_amount",        "TEXT"),
        ("claim_tier",          "TEXT"),
        ("claim_error",         "TEXT"),
        ("claim_attempted_at",  "TEXT"),
        ("claim_finished_at",   "TEXT"),
        # ── Колонки для регистрации tier (Instant Airdrop — до даты клейма)
        ("register_status",       "TEXT"),  # registered / already / failed / not_eligible
        ("register_tier",         "TEXT"),  # сохранённый tier по ответу сервера
        ("register_error",        "TEXT"),
        ("register_attempted_at", "TEXT"),
        ("register_finished_at",  "TEXT"),
    ):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE claim_tasks ADD COLUMN {col} {ddl}")
    conn.commit()


# ─────────────────── runs ───────────────────

def create_run(total: int) -> int:
    with _db_lock:
        conn = _connect()
        _init_schema(conn)
        cur = conn.execute(
            "INSERT INTO claim_runs (started_at, total) VALUES (?, ?)",
            (datetime.now().isoformat(timespec="seconds"), total),
        )
        run_id = cur.lastrowid
        conn.commit()
        conn.close()
        return int(run_id)


def finish_run(run_id: int) -> dict:
    with _db_lock:
        conn = _connect()
        row = conn.execute("""
            SELECT
                SUM(CASE WHEN status = 'completed' AND eligible = 1 THEN 1 ELSE 0 END) AS eligible,
                SUM(CASE WHEN status = 'completed' AND (eligible = 0 OR eligible IS NULL) THEN 1 ELSE 0 END) AS not_eligible,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM claim_tasks WHERE run_id = ?
        """, (run_id,)).fetchone()
        stats = {k: (row[k] or 0) for k in ("eligible", "not_eligible", "failed")}
        conn.execute("""
            UPDATE claim_runs
            SET finished_at = ?, status = 'completed',
                eligible = ?, not_eligible = ?, failed = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(timespec="seconds"),
            stats["eligible"], stats["not_eligible"], stats["failed"], run_id,
        ))
        conn.commit()
        conn.close()
        return stats


def get_last_run_id() -> Optional[int]:
    with _db_lock:
        conn = _connect()
        _init_schema(conn)
        row = conn.execute("SELECT id FROM claim_runs ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        return int(row["id"]) if row else None


# ─────────────────── tasks ───────────────────

def create_tasks(run_id: int, wallets: list[dict]) -> None:
    with _db_lock:
        conn = _connect()
        rows = [
            (run_id, i, w.get("account_name"), w["address"], w.get("proxy"))
            for i, w in enumerate(wallets, 1)
        ]
        conn.executemany("""
            INSERT INTO claim_tasks (run_id, wallet_index, account_name, address, proxy)
            VALUES (?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
        conn.close()


def get_pending_tasks(run_id: int) -> list[dict]:
    with _db_lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM claim_tasks WHERE run_id = ? AND status = 'pending' ORDER BY wallet_index",
            (run_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def mark_running(task_id: int) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute(
            "UPDATE claim_tasks SET status = 'running', started_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), task_id),
        )
        conn.commit()
        conn.close()


def mark_completed(
    task_id: int,
    *,
    eligible: bool,
    amount: Optional[str],
    claimed: Optional[bool],
    tiers: Optional[list],
    endpoint: Optional[str],
    raw_response: Optional[dict],
) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute("""
            UPDATE claim_tasks
            SET status = 'completed', finished_at = ?,
                eligible = ?, amount = ?, claimed = ?, tiers = ?,
                endpoint = ?, raw_response = ?, error = NULL
            WHERE id = ?
        """, (
            datetime.now().isoformat(timespec="seconds"),
            1 if eligible else 0,
            amount,
            None if claimed is None else (1 if claimed else 0),
            json.dumps(tiers, ensure_ascii=False) if tiers else None,
            endpoint,
            json.dumps(raw_response, ensure_ascii=False) if raw_response is not None else None,
            task_id,
        ))
        conn.commit()
        conn.close()


def mark_failed(task_id: int, error: str) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute("""
            UPDATE claim_tasks
            SET status = 'failed', finished_at = ?, error = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(timespec="seconds"), error[:500], task_id,
        ))
        conn.commit()
        conn.close()


def update_proxy(task_id: int, proxy: Optional[str]) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute("UPDATE claim_tasks SET proxy = ? WHERE id = ?", (proxy, task_id))
        conn.commit()
        conn.close()


def get_run_tasks(run_id: int) -> list[dict]:
    with _db_lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM claim_tasks WHERE run_id = ? ORDER BY wallet_index",
            (run_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_run(run_id: int) -> Optional[dict]:
    with _db_lock:
        conn = _connect()
        row = conn.execute("SELECT * FROM claim_runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        return dict(row) if row else None


# ─────────────────── resume / reset ───────────────────

def get_addresses_in_run(run_id: int) -> set[str]:
    """Множество адресов (lowercase), уже зарегистрированных в run."""
    with _db_lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT address FROM claim_tasks WHERE run_id = ?", (run_id,),
        ).fetchall()
        conn.close()
        return {str(r["address"]).lower() for r in rows}


def get_max_wallet_index(run_id: int) -> int:
    with _db_lock:
        conn = _connect()
        row = conn.execute(
            "SELECT COALESCE(MAX(wallet_index), 0) AS mx FROM claim_tasks WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        conn.close()
        return int(row["mx"] or 0)


def append_tasks(run_id: int, wallets: list[dict]) -> int:
    """Добавить в run новые задачи (адреса, которых ещё нет).

    Возвращает количество добавленных задач.
    """
    if not wallets:
        return 0
    existing = get_addresses_in_run(run_id)
    start_idx = get_max_wallet_index(run_id)
    to_add = [w for w in wallets if w["address"].lower() not in existing]
    if not to_add:
        return 0
    with _db_lock:
        conn = _connect()
        rows = [
            (run_id, start_idx + i, w.get("account_name"), w["address"], w.get("proxy"))
            for i, w in enumerate(to_add, 1)
        ]
        conn.executemany("""
            INSERT INTO claim_tasks (run_id, wallet_index, account_name, address, proxy)
            VALUES (?, ?, ?, ?, ?)
        """, rows)
        # Обновим total у run
        conn.execute(
            "UPDATE claim_runs SET total = (SELECT COUNT(*) FROM claim_tasks WHERE run_id = ?) WHERE id = ?",
            (run_id, run_id),
        )
        conn.commit()
        conn.close()
    return len(to_add)


def requeue_stale(run_id: int, *, include_failed: bool = True) -> int:
    """Сбросить зависшие 'running' (и опц. 'failed') обратно в 'pending'.

    Возвращает количество возвращённых задач.
    """
    statuses = ("running", "failed") if include_failed else ("running",)
    placeholders = ",".join("?" * len(statuses))
    with _db_lock:
        conn = _connect()
        cur = conn.execute(
            f"""UPDATE claim_tasks
                SET status = 'pending', started_at = NULL, finished_at = NULL, error = NULL
                WHERE run_id = ? AND status IN ({placeholders})""",
            (run_id, *statuses),
        )
        changed = cur.rowcount or 0
        conn.commit()
        conn.close()
    return int(changed)


def reopen_run(run_id: int) -> None:
    """Снять статус 'completed' с run, чтобы добавить новые кошельки."""
    with _db_lock:
        conn = _connect()
        conn.execute(
            "UPDATE claim_runs SET status = 'running', finished_at = NULL WHERE id = ?",
            (run_id,),
        )
        conn.commit()
        conn.close()


def reset_all() -> None:
    """Полностью очистить БД чекера (удалить все runs и tasks)."""
    with _db_lock:
        conn = _connect()
        conn.execute("DROP TABLE IF EXISTS claim_tasks")
        conn.execute("DROP TABLE IF EXISTS claim_runs")
        conn.commit()
        _init_schema(conn)
        conn.close()


# ─────────────────── claim (on-chain) ───────────────────

def get_claim_candidates(run_id: int, *, include_failed: bool = True) -> list[dict]:
    """Eligible + НЕ заклеймленные задачи в run_id, кандидаты для клеймера.

    Статус "заклеймлен" берём ИСКЛЮЧИТЕЛЬНО из claim_status (ставится клеймером после
    успешного on-chain receipt). Колонка `claimed` (1/0 от чекера) НЕ используется —
    апи claim.pharos.xyz возвращает там флаг регистрации, а не факт claim.

    Условия:
      • completed чекером (status='completed') и eligible=1;
      • claim_status НЕ 'claimed' и НЕ 'skipped';
      • если include_failed=False — также пропускаем 'failed'.
    """
    bad_statuses = ("claimed", "skipped")
    if not include_failed:
        bad_statuses = bad_statuses + ("failed",)
    placeholders = ",".join("?" * len(bad_statuses))
    with _db_lock:
        conn = _connect()
        rows = conn.execute(
            f"""SELECT * FROM claim_tasks
                WHERE run_id = ?
                  AND status = 'completed'
                  AND eligible = 1
                  AND (claim_status IS NULL OR claim_status NOT IN ({placeholders}))
                ORDER BY wallet_index""",
            (run_id, *bad_statuses),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def mark_claim_running(task_id: int) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute(
            """UPDATE claim_tasks
               SET claim_status = 'running',
                   claim_attempted_at = ?,
                   claim_error = NULL
               WHERE id = ?""",
            (datetime.now().isoformat(timespec="seconds"), task_id),
        )
        conn.commit()
        conn.close()


def mark_claim_done(
    task_id: int,
    *,
    tx_hash: Optional[str],
    amount: Optional[str],
    tier: Optional[str],
    already_claimed: bool = False,
) -> None:
    """Успех клейма (или skipped, если already_claimed)."""
    status = "skipped" if already_claimed else "claimed"
    with _db_lock:
        conn = _connect()
        conn.execute(
            """UPDATE claim_tasks
               SET claim_status = ?,
                   claim_tx_hash = ?,
                   claim_amount = ?,
                   claim_tier = ?,
                   claim_error = NULL,
                   claim_finished_at = ?,
                   claimed = 1
               WHERE id = ?""",
            (
                status, tx_hash, amount, tier,
                datetime.now().isoformat(timespec="seconds"), task_id,
            ),
        )
        conn.commit()
        conn.close()


def mark_claim_failed(
    task_id: int,
    error: str,
    *,
    tx_hash: Optional[str] = None,
    tier: Optional[str] = None,
) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute(
            """UPDATE claim_tasks
               SET claim_status = 'failed',
                   claim_tx_hash = COALESCE(?, claim_tx_hash),
                   claim_tier = COALESCE(?, claim_tier),
                   claim_error = ?,
                   claim_finished_at = ?
               WHERE id = ?""",
            (
                tx_hash, tier, error[:500],
                datetime.now().isoformat(timespec="seconds"), task_id,
            ),
        )
        conn.commit()
        conn.close()


def mark_claim_not_ready(
    task_id: int,
    reason: str,
    *,
    tier: Optional[str] = None,
) -> None:
    """Proof ещё не опубликован сервером — будет автоматически повторено позже."""
    with _db_lock:
        conn = _connect()
        conn.execute(
            """UPDATE claim_tasks
               SET claim_status = 'not_ready',
                   claim_tier = COALESCE(?, claim_tier),
                   claim_error = ?,
                   claim_finished_at = ?
               WHERE id = ?""",
            (
                tier, reason[:500],
                datetime.now().isoformat(timespec="seconds"), task_id,
            ),
        )
        conn.commit()
        conn.close()


def reset_claim_state(run_id: int) -> int:
    """Сбросить ВСЕ claim_* колонки в run_id (для перезапуска клеймера).

    Возвращает количество затронутых задач.
    """
    with _db_lock:
        conn = _connect()
        cur = conn.execute(
            """UPDATE claim_tasks
               SET claim_status = NULL,
                   claim_tx_hash = NULL,
                   claim_amount = NULL,
                   claim_tier = NULL,
                   claim_error = NULL,
                   claim_attempted_at = NULL,
                   claim_finished_at = NULL
               WHERE run_id = ?""",
            (run_id,),
        )
        changed = cur.rowcount or 0
        conn.commit()
        conn.close()
    return int(changed)


# ─────────────────── registrar helpers ───────────────────

def get_register_candidates(
    run_id: int,
    *,
    include_failed: bool = True,
) -> list[dict]:
    """Eligible задачи в run_id, кандидаты для регистрации tier.

    Условия:
      • status='completed' и eligible=1 (прошли чекер как eligible);
      • register_status NOT IN ('registered', 'already')
        (если include_failed=False — также пропускаем 'failed' и 'not_eligible').
    """
    bad_statuses: tuple[str, ...] = ("registered", "already")
    if not include_failed:
        bad_statuses = bad_statuses + ("failed", "not_eligible")
    placeholders = ",".join("?" * len(bad_statuses))
    with _db_lock:
        conn = _connect()
        rows = conn.execute(
            f"""SELECT * FROM claim_tasks
                WHERE run_id = ?
                  AND status = 'completed'
                  AND eligible = 1
                  AND (register_status IS NULL OR register_status NOT IN ({placeholders}))
                ORDER BY wallet_index""",
            (run_id, *bad_statuses),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def mark_register_running(task_id: int) -> None:
    with _db_lock:
        conn = _connect()
        conn.execute(
            """UPDATE claim_tasks
               SET register_status = 'running',
                   register_attempted_at = ?,
                   register_error = NULL
               WHERE id = ?""",
            (datetime.now().isoformat(timespec="seconds"), task_id),
        )
        conn.commit()
        conn.close()


def mark_register_done(
    task_id: int,
    *,
    tier: Optional[str],
    already_registered: bool = False,
) -> None:
    status = "already" if already_registered else "registered"
    with _db_lock:
        conn = _connect()
        conn.execute(
            """UPDATE claim_tasks
               SET register_status = ?,
                   register_tier = ?,
                   register_error = NULL,
                   register_finished_at = ?
               WHERE id = ?""",
            (
                status, tier,
                datetime.now().isoformat(timespec="seconds"), task_id,
            ),
        )
        conn.commit()
        conn.close()


def mark_register_failed(
    task_id: int,
    error: str,
    *,
    tier: Optional[str] = None,
    not_eligible: bool = False,
) -> None:
    status = "not_eligible" if not_eligible else "failed"
    with _db_lock:
        conn = _connect()
        conn.execute(
            """UPDATE claim_tasks
               SET register_status = ?,
                   register_tier = COALESCE(?, register_tier),
                   register_error = ?,
                   register_finished_at = ?
               WHERE id = ?""",
            (
                status, tier, error[:500],
                datetime.now().isoformat(timespec="seconds"), task_id,
            ),
        )
        conn.commit()
        conn.close()


def reset_register_state(run_id: int) -> int:
    """Сбросить ВСЕ register_* колонки в run_id."""
    with _db_lock:
        conn = _connect()
        cur = conn.execute(
            """UPDATE claim_tasks
               SET register_status = NULL,
                   register_tier = NULL,
                   register_error = NULL,
                   register_attempted_at = NULL,
                   register_finished_at = NULL
               WHERE run_id = ?""",
            (run_id,),
        )
        changed = cur.rowcount or 0
        conn.commit()
        conn.close()
    return int(changed)

