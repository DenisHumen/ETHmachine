"""
Database для Perle Eligibility Checker
Хранение задач проверки элигибельности кошельков
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from threading import Lock

DB_DIR = Path(__file__).parent.parent.parent.parent / "db"
DB_FILE = DB_DIR / "perle_checker.db"

db_lock = Lock()


def ensure_db_directory():
    DB_DIR.mkdir(parents=True, exist_ok=True)


def init_database():
    """Инициализация базы данных"""
    ensure_db_directory()

    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS check_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sol_address TEXT NOT NULL UNIQUE,
                    account_name TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    eligible INTEGER DEFAULT 0,
                    total TEXT DEFAULT '0',
                    details TEXT DEFAULT '{}',
                    error_message TEXT,
                    attempts INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            ''')

            # Миграция: добавить account_name если таблица уже существует
            try:
                cursor.execute("ALTER TABLE check_tasks ADD COLUMN account_name TEXT")
            except Exception:
                pass

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_check_address
                ON check_tasks(sol_address)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_check_status
                ON check_tasks(status)
            ''')

            conn.commit()


def create_check_tasks(sol_addresses: List[str]):
    """
    Создание задач для проверки элигибельности.

    Args:
        sol_addresses: список SOL адресов
    """
    init_database()

    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()

            for address in sol_addresses:
                cursor.execute('''
                    INSERT OR IGNORE INTO check_tasks
                    (sol_address, status)
                    VALUES (?, 'pending')
                ''', (address,))

            conn.commit()


def get_pending_tasks() -> List[Dict]:
    """Получить незавершённые задачи"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, sol_address, status, eligible, total,
                       details, attempts, error_message
                FROM check_tasks
                WHERE status IN ('pending', 'failed')
                ORDER BY attempts ASC, created_at ASC
            ''')

            return [dict(row) for row in cursor.fetchall()]


def update_task_success(sol_address: str, eligible: bool, total: str, details: str):
    """Обновить задачу успешным результатом"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute('''
                UPDATE check_tasks
                SET status = 'completed', eligible = ?, total = ?,
                    details = ?, completed_at = ?, updated_at = ?,
                    error_message = NULL
                WHERE sol_address = ?
            ''', (1 if eligible else 0, total, details, now, now, sol_address))

            conn.commit()


def update_task_failed(sol_address: str, error_message: str):
    """Обновить задачу с ошибкой"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute('''
                UPDATE check_tasks
                SET status = 'failed', attempts = attempts + 1,
                    updated_at = ?, error_message = ?
                WHERE sol_address = ?
            ''', (now, error_message, sol_address))

            conn.commit()


def get_task_statistics() -> Dict:
    """Получить статистику задач"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM check_tasks")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM check_tasks WHERE status = 'completed'")
            completed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM check_tasks WHERE status = 'pending'")
            pending = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM check_tasks WHERE status = 'failed'")
            failed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM check_tasks WHERE status = 'completed' AND eligible = 1")
            eligible = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM check_tasks WHERE status = 'completed' AND eligible = 0")
            not_eligible = cursor.fetchone()[0]

            return {
                'total': total,
                'completed': completed,
                'pending': pending,
                'failed': failed,
                'eligible': eligible,
                'not_eligible': not_eligible,
            }


def get_all_results() -> List[Dict]:
    """Получить все результаты для экспорта"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT sol_address, status, eligible, total,
                       details, error_message, created_at, completed_at
                FROM check_tasks
                ORDER BY eligible DESC, sol_address
            ''')

            return [dict(row) for row in cursor.fetchall()]


def all_tasks_completed() -> bool:
    """Проверить, все ли задачи завершены"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM check_tasks")
            total = cursor.fetchone()[0]
            if total == 0:
                return False

            cursor.execute('''
                SELECT COUNT(*) FROM check_tasks
                WHERE status NOT IN ('completed')
            ''')

            not_completed = cursor.fetchone()[0]
            return not_completed == 0


def reset_database() -> int:
    """Очистить базу данных"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM check_tasks")
            deleted = cursor.rowcount
            conn.commit()
            return deleted


def get_total_tasks_count() -> int:
    """Общее количество задач"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM check_tasks")
            return cursor.fetchone()[0]
