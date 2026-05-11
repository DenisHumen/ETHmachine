"""LiteForge bridge (Sepolia ⇄ LiteForge) — таблицы БД пресета.

Файл БД общий для всего проекта (`db/litvm.db`). Здесь — две таблицы:

  bridge_wallet_tasks
    Запись на кошелёк. Хранит планируемое и фактическое количество транзакций,
    суммарный объём, общий статус (`pending` / `in_progress` / `completed` /
    `failed`). Через эту таблицу резюмируется незавершённая работа: запустили
    20 кошельков → прервали → пере-запустили → пресет видит, что у части
    `completed=False` и продолжает с tx-задач из `bridge_tx_tasks`.

  bridge_tx_tasks
    Одна строка = одна планируемая транзакция bridge.
    На каждую запланированную tx ДВА суб-статуса
    (как просил пользователь: «две задачи — списались и пришли»):
      send_status: pending → approved (только L1→L2) → sent → confirmed → failed
      dst_status:  pending → arrived → timeout → failed
    Tx считается полностью успешной когда оба = `confirmed` + `arrived`.

Резюмируемость (AGENTS.md §14):
  • План создаётся один раз (`plan_wallet`), потом не пере-планируется
    без явного `reset_tasks()`.
  • Каждый шаг (approve sent / deposit sent / receipt confirmed / dst arrived)
    апсертится в БД сразу — interrupt не теряет прогресс.
  • При запуске worker сначала тянет незавершённые tx-задачи кошелька
    (`list_pending_tx_for_wallet`) и продолжает с того места, где остановился.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from modules.litvm_testnet.database import (
    DB_PATH,  # noqa: F401  (re-exported convenience)
    connect as _connect,
    init_database as _init_project_db,
)

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def init_database() -> None:
    _init_project_db()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bridge_wallet_tasks (
                    address TEXT PRIMARY KEY,
                    account_name TEXT,
                    direction TEXT NOT NULL DEFAULT 'l1_to_l2',  -- l1_to_l2 | l2_to_l1
                    planned_count INTEGER NOT NULL DEFAULT 0,
                    completed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    -- pending | planned | in_progress | completed | failed
                    return_enabled INTEGER NOT NULL DEFAULT 0,
                    return_status TEXT,
                    -- NULL | pending | sent | confirmed | failed | skipped
                    error_message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bridge_tx_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    tx_index INTEGER NOT NULL,         -- 1..planned_count
                    direction TEXT NOT NULL,           -- l1_to_l2 | l2_to_l1
                    amount_wei TEXT NOT NULL,
                    amount_human REAL NOT NULL,
                    pct REAL NOT NULL,                 -- от какого процента баланса посчитано
                    src_balance_before_wei TEXT,
                    src_balance_after_wei TEXT,
                    dst_balance_before_wei TEXT,
                    dst_balance_after_wei TEXT,
                    send_status TEXT NOT NULL DEFAULT 'pending',
                    -- pending | approved | sent | confirmed | failed
                    dst_status TEXT NOT NULL DEFAULT 'pending',
                    -- pending | arrived | submitted | finalized | timeout | failed
                    approve_tx_hash TEXT,
                    src_tx_hash TEXT,
                    dst_arrival_seconds REAL,
                    finalize_tx_hash TEXT,
                    finalize_attempts INTEGER NOT NULL DEFAULT 0,
                    finalize_last_at REAL,
                    finalize_last_reason TEXT,
                    error_message TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(address, tx_index, direction)
                )
                """
            )
            # Миграции: добавляем недостающие колонки, если БД старая
            for col, ddl in (
                ("finalize_tx_hash", "TEXT"),
                ("finalize_attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("finalize_last_at", "REAL"),
                ("finalize_last_reason", "TEXT"),
            ):
                try:
                    conn.execute(f"ALTER TABLE bridge_tx_tasks ADD COLUMN {col} {ddl}")
                except Exception:
                    pass
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bridge_tx_addr "
                "ON bridge_tx_tasks(address, send_status, dst_status)"
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# bridge_wallet_tasks
# ---------------------------------------------------------------------------

def upsert_wallet(address: str, account_name: Optional[str] = None,
                  direction: str = "l1_to_l2",
                  return_enabled: bool = False) -> None:
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO bridge_wallet_tasks
                    (address, account_name, direction, return_enabled, status)
                VALUES (?, ?, ?, ?, 'pending')
                ON CONFLICT(address) DO UPDATE SET
                    account_name = COALESCE(excluded.account_name, bridge_wallet_tasks.account_name),
                    direction = excluded.direction,
                    return_enabled = excluded.return_enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (addr, account_name, direction, 1 if return_enabled else 0),
            )
            conn.commit()
        finally:
            conn.close()


def update_wallet(address: str, **fields) -> None:
    if not fields:
        return
    addr = address.lower()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [addr]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE bridge_wallet_tasks SET {sets}, "
                f"updated_at = CURRENT_TIMESTAMP WHERE address = ?",
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
                "SELECT * FROM bridge_wallet_tasks WHERE address = ?",
                (address.lower(),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def recompute_wallet_counters(address: str) -> dict:
    """Пересчитывает completed/failed_count и общий status кошелька на
    основании bridge_tx_tasks. Возвращает {planned, completed, failed, status}."""
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT send_status, dst_status FROM bridge_tx_tasks "
                "WHERE address = ?",
                (addr,),
            ).fetchall()
            total = len(rows)
            completed = sum(
                1 for r in rows
                if r["send_status"] == "confirmed"
                and r["dst_status"] in ("arrived", "submitted", "finalized")
            )
            failed = sum(
                1 for r in rows
                if r["send_status"] == "failed" or r["dst_status"] in ("failed", "timeout")
            )
            if total == 0:
                status = "pending"
            elif completed == total:
                status = "completed"
            elif completed + failed == total:
                status = "failed" if failed > 0 else "completed"
            elif completed > 0 or failed > 0:
                status = "in_progress"
            else:
                status = "planned"
            conn.execute(
                "UPDATE bridge_wallet_tasks SET planned_count = ?, "
                "completed_count = ?, failed_count = ?, status = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE address = ?",
                (total, completed, failed, status, addr),
            )
            conn.commit()
            return {"planned": total, "completed": completed,
                    "failed": failed, "status": status}
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# bridge_tx_tasks
# ---------------------------------------------------------------------------

def insert_tx_task(*, address: str, tx_index: int, direction: str,
                   amount_wei: int, amount_human: float, pct: float) -> int:
    """Создать новую запись tx-задачи. Не делает upsert — план создаётся
    один раз; при попытке повторной вставки (UNIQUE) бросит ошибку."""
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO bridge_tx_tasks
                    (address, tx_index, direction, amount_wei, amount_human, pct)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(address, tx_index, direction) DO UPDATE SET
                    amount_wei = excluded.amount_wei,
                    amount_human = excluded.amount_human,
                    pct = excluded.pct,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (addr, int(tx_index), direction, str(int(amount_wei)),
                 float(amount_human), float(pct)),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id FROM bridge_tx_tasks "
                "WHERE address = ? AND tx_index = ? AND direction = ?",
                (addr, int(tx_index), direction),
            ).fetchone()
            return int(row["id"])
        finally:
            conn.close()


def update_tx_task(tx_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [int(tx_id)]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                f"UPDATE bridge_tx_tasks SET {sets}, "
                f"updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()


def increment_attempts(tx_id: int) -> int:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE bridge_tx_tasks SET attempts = attempts + 1, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(tx_id),),
            )
            conn.commit()
            row = conn.execute(
                "SELECT attempts FROM bridge_tx_tasks WHERE id = ?",
                (int(tx_id),),
            ).fetchone()
            return int(row["attempts"]) if row else 0
        finally:
            conn.close()


def get_tx_task(tx_id: int) -> Optional[dict]:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM bridge_tx_tasks WHERE id = ?",
                (int(tx_id),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def list_tx_for_wallet(address: str, direction: Optional[str] = None) -> list[dict]:
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            if direction is None:
                rows = conn.execute(
                    "SELECT * FROM bridge_tx_tasks WHERE address = ? "
                    "ORDER BY direction, tx_index",
                    (addr,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bridge_tx_tasks WHERE address = ? AND direction = ? "
                    "ORDER BY tx_index",
                    (addr, direction),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def list_pending_tx_for_wallet(address: str, direction: Optional[str] = None) -> list[dict]:
    """Tx-задачи кошелька, ещё НЕ завершённые успешно и не упавшие
    окончательно — то, что нужно проработать в этом запуске."""
    addr = address.lower()
    with _lock:
        conn = _connect()
        try:
            base = (
                "SELECT * FROM bridge_tx_tasks WHERE address = ? "
                "AND NOT (send_status = 'confirmed' AND dst_status IN ('arrived','submitted','finalized')) "
                "AND NOT (send_status = 'failed' AND dst_status IN ('failed','timeout'))"
            )
            if direction is None:
                rows = conn.execute(
                    base + " ORDER BY direction, tx_index", (addr,)
                ).fetchall()
            else:
                rows = conn.execute(
                    base + " AND direction = ? ORDER BY tx_index", (addr, direction),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def list_finalize_pending(direction: str = "l2_to_l1",
                          older_than_sec: float = 0.0) -> list[dict]:
    """Tx-задачи, ждущие L1-финализации (dst_status='submitted').
    Если older_than_sec > 0, возвращает только те, у которых
    finalize_last_at либо NULL, либо старше now-older_than_sec."""
    import time as _t
    with _lock:
        conn = _connect()
        try:
            if older_than_sec > 0:
                threshold = _t.time() - float(older_than_sec)
                rows = conn.execute(
                    "SELECT * FROM bridge_tx_tasks "
                    "WHERE direction = ? AND send_status = 'confirmed' "
                    "AND dst_status = 'submitted' "
                    "AND (finalize_last_at IS NULL OR finalize_last_at < ?) "
                    "ORDER BY address, tx_index",
                    (direction, threshold),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bridge_tx_tasks "
                    "WHERE direction = ? AND send_status = 'confirmed' "
                    "AND dst_status = 'submitted' "
                    "ORDER BY address, tx_index",
                    (direction,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def list_wallets_with_pending() -> list[str]:
    """Адреса, у которых есть хотя бы одна незавершённая tx-задача."""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT address FROM bridge_tx_tasks "
                "WHERE NOT (send_status = 'confirmed' AND dst_status IN ('arrived','submitted','finalized')) "
                "AND NOT (send_status = 'failed' AND dst_status IN ('failed','timeout'))"
            ).fetchall()
            return [r["address"] for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# statistics / reset
# ---------------------------------------------------------------------------

def get_statistics() -> dict:
    with _lock:
        conn = _connect()
        try:
            stats: dict = {}
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM bridge_wallet_tasks GROUP BY status"
            ).fetchall()
            for r in rows:
                stats[f"wallet_{r['status']}"] = r["cnt"]
            tot_w = conn.execute("SELECT COUNT(*) FROM bridge_wallet_tasks").fetchone()[0]
            stats["wallet_total"] = tot_w

            tx_rows = conn.execute(
                "SELECT send_status, dst_status, COUNT(*) AS cnt "
                "FROM bridge_tx_tasks GROUP BY send_status, dst_status"
            ).fetchall()
            tx_total = 0
            tx_done = 0
            tx_failed = 0
            tx_inflight = 0
            for r in tx_rows:
                cnt = int(r["cnt"])
                tx_total += cnt
                s, d = r["send_status"], r["dst_status"]
                if s == "confirmed" and d in ("arrived", "submitted", "finalized"):
                    tx_done += cnt
                elif s == "failed" or d in ("failed", "timeout"):
                    tx_failed += cnt
                else:
                    tx_inflight += cnt
            stats["tx_total"] = tx_total
            stats["tx_done"] = tx_done
            stats["tx_failed"] = tx_failed
            stats["tx_inflight"] = tx_inflight

            ret_rows = conn.execute(
                "SELECT return_status, COUNT(*) AS cnt "
                "FROM bridge_wallet_tasks "
                "WHERE return_enabled = 1 "
                "GROUP BY return_status"
            ).fetchall()
            for r in ret_rows:
                key = f"return_{r['return_status'] or 'pending'}"
                stats[key] = r["cnt"]

            return stats
        finally:
            conn.close()


def reset_tasks() -> None:
    """Полная очистка bridge-таблиц (vcrcs_cookies не трогаем)."""
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM bridge_tx_tasks")
            conn.execute("DELETE FROM bridge_wallet_tasks")
            conn.commit()
        finally:
            conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
