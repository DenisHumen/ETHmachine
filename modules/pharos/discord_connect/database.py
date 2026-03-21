"""Pharos Discord Connect — работа с базой данных SQLite."""
import sqlite3
import json
import threading
from pathlib import Path
from datetime import datetime

DB_FILE = str(Path(__file__).parent.parent.parent.parent / "db" / "pharos_discord.db")

_db_lock = threading.Lock()


def _get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Создать таблицу задач если не существует."""
    with _db_lock:
        conn = _get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS discord_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                private_key TEXT NOT NULL,
                address TEXT NOT NULL UNIQUE,
                account_name TEXT,
                proxy TEXT,
                discord_token TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                jwt_token TEXT,
                jwt_created_at TEXT,
                session_data TEXT DEFAULT '{}',
                discord_username TEXT,
                discord_id TEXT,
                error_message TEXT,
                attempts INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
        """)

        # Миграция: добавить account_name если таблица уже существует
        try:
            conn.execute("ALTER TABLE discord_tasks ADD COLUMN account_name TEXT")
        except Exception:
            pass
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_discord_tasks_status
            ON discord_tasks(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_discord_tasks_address
            ON discord_tasks(address)
        """)
        conn.commit()
        conn.close()


def create_tasks(wallets: list[dict]):
    """Создать задачи из списка кошельков. Пропускает уже существующие."""
    init_database()
    with _db_lock:
        conn = _get_connection()
        for w in wallets:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO discord_tasks
                    (private_key, address, account_name, proxy, discord_token, status)
                    VALUES (?, ?, ?, ?, ?, 'pending')
                """, (
                    w["private_key"],
                    w["address"],
                    w.get("account_name"),
                    w.get("proxy"),
                    w.get("discord_token"),
                ))
            except Exception as e:
                print(f"  [!] Ошибка добавления {w.get('address', '?')[:10]}...: {e}")
        conn.commit()
        conn.close()


def get_all_tasks() -> list[dict]:
    """Получить все задачи."""
    init_database()
    with _db_lock:
        conn = _get_connection()
        rows = conn.execute("SELECT * FROM discord_tasks ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_pending_tasks() -> list[dict]:
    """Получить задачи для обработки (pending, failed, auth_ok)."""
    init_database()
    with _db_lock:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT * FROM discord_tasks WHERE status IN ('pending', 'failed', 'auth_ok') ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_task_counts() -> dict:
    """Получить количество задач по статусам."""
    init_database()
    with _db_lock:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM discord_tasks GROUP BY status"
        ).fetchall()
        conn.close()
        counts = {r["status"]: r["cnt"] for r in rows}
        counts["total"] = sum(counts.values())
        return counts


def update_task(address: str, **kwargs):
    """Обновить поля задачи (thread-safe)."""
    with _db_lock:
        conn = _get_connection()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [address]
        conn.execute(
            f"UPDATE discord_tasks SET {sets}, updated_at = ? WHERE address = ?",
            [*list(kwargs.values()), datetime.now().isoformat(), address]
        )
        conn.commit()
        conn.close()


def update_task_auth(address: str, jwt_token: str):
    """Обновить JWT токен и время создания."""
    with _db_lock:
        conn = _get_connection()
        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE discord_tasks
               SET jwt_token = ?, jwt_created_at = ?, status = 'auth_ok', updated_at = ?
               WHERE address = ?""",
            (jwt_token, now, now, address)
        )
        conn.commit()
        conn.close()


def update_task_discord_connected(address: str, discord_username: str = None,
                                   discord_id: str = None):
    """Пометить задачу как выполненную (Discord привязан)."""
    with _db_lock:
        conn = _get_connection()
        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE discord_tasks
               SET status = 'completed', discord_username = ?, discord_id = ?,
                   completed_at = ?, updated_at = ?
               WHERE address = ?""",
            (discord_username, discord_id, now, now, address)
        )
        conn.commit()
        conn.close()


def update_task_failed(address: str, error_message: str):
    """Пометить задачу как неудачную."""
    with _db_lock:
        conn = _get_connection()
        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE discord_tasks
               SET status = 'failed', error_message = ?,
                   attempts = attempts + 1, updated_at = ?
               WHERE address = ?""",
            (error_message, now, address)
        )
        conn.commit()
        conn.close()


def update_task_session(address: str, session_data: dict):
    """Сохранить данные сессии."""
    with _db_lock:
        conn = _get_connection()
        conn.execute(
            """UPDATE discord_tasks
               SET session_data = ?, updated_at = ?
               WHERE address = ?""",
            (json.dumps(session_data), datetime.now().isoformat(), address)
        )
        conn.commit()
        conn.close()


def get_task_by_address(address: str) -> dict | None:
    """Получить задачу по адресу."""
    init_database()
    with _db_lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT * FROM discord_tasks WHERE address = ?", (address,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None


def get_saved_jwt(address: str) -> tuple[str | None, str | None]:
    """Получить сохранённый JWT и время создания."""
    task = get_task_by_address(address)
    if task:
        return task.get("jwt_token"), task.get("jwt_created_at")
    return None, None


def clear_database():
    """Полная очистка таблицы задач."""
    init_database()
    with _db_lock:
        conn = _get_connection()
        conn.execute("DELETE FROM discord_tasks")
        conn.commit()
        conn.close()


def get_all_results() -> list[dict]:
    """Получить все результаты для экспорта."""
    init_database()
    with _db_lock:
        conn = _get_connection()
        rows = conn.execute("""
            SELECT address, proxy, discord_token, status,
                   discord_username, discord_id,
                   error_message, attempts,
                   created_at, updated_at, completed_at
            FROM discord_tasks ORDER BY id
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def is_database_empty() -> bool:
    """Проверить пустая ли база."""
    counts = get_task_counts()
    return counts.get("total", 0) == 0
