"""
База данных для отслеживания прогресса задач Neura Protocol
Хранит статус выполнения каждой задачи для каждого кошелька
"""

import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from threading import Lock

# Путь к базе данных
DB_DIR = Path(__file__).parent.parent.parent / "db"
DB_FILE = DB_DIR / "neura_tasks.db"

db_lock = Lock()


def ensure_db_directory():
    """Создание директории для БД если не существует"""
    DB_DIR.mkdir(parents=True, exist_ok=True)


def get_private_key_hash(private_key: str) -> str:
    """Хеширование приватного ключа для безопасного хранения"""
    return hashlib.sha256(private_key.encode()).hexdigest()[:16]


def init_database():
    """Инициализация базы данных с таблицей задач"""
    ensure_db_directory()
    
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            # Таблица задач для каждого кошелька
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS neura_wallet_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL,
                    private_key_hash TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    last_attempt TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(wallet_address, task_type)
                )
            ''')
            
            # Индексы для быстрого поиска
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_wallet_task 
                ON neura_wallet_tasks(wallet_address, task_type)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status 
                ON neura_wallet_tasks(status)
            ''')
            
            conn.commit()


def create_tasks_for_wallets(wallets: List[Tuple[str, str]], task_types: List[str]):
    """
    Создание задач для списка кошельков
    
    Args:
        wallets: список кортежей (wallet_address, private_key)
        task_types: список типов задач (например ['collect_pulses', 'claim_tasks'])
    """
    init_database()
    
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            for wallet_address, private_key in wallets:
                pk_hash = get_private_key_hash(private_key)
                
                for task_type in task_types:
                    # Используем INSERT OR IGNORE чтобы не дублировать задачи
                    cursor.execute('''
                        INSERT OR IGNORE INTO neura_wallet_tasks 
                        (wallet_address, private_key_hash, task_type, status)
                        VALUES (?, ?, ?, 'pending')
                    ''', (wallet_address, pk_hash, task_type))
            
            conn.commit()


def get_pending_tasks(task_type: str) -> List[Dict]:
    """
    Получить все pending задачи определенного типа
    Включает: pending, failed, in_progress (застрявшие при перезапуске)
    
    Returns:
        Список словарей с информацией о задачах
    """
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, wallet_address, private_key_hash, task_type, status, attempts
                FROM neura_wallet_tasks 
                WHERE task_type = ? AND status IN ('pending', 'failed', 'in_progress')
                ORDER BY attempts ASC, created_at ASC
            ''', (task_type,))
            
            return [dict(row) for row in cursor.fetchall()]


def get_wallet_task_status(wallet_address: str, task_type: str) -> Optional[Dict]:
    """Получить статус задачи для кошелька"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM neura_wallet_tasks 
                WHERE wallet_address = ? AND task_type = ?
            ''', (wallet_address, task_type))
            
            row = cursor.fetchone()
            return dict(row) if row else None


def update_task_status(
    wallet_address: str, 
    task_type: str, 
    status: str, 
    error_message: Optional[str] = None
):
    """
    Обновить статус задачи
    
    Args:
        wallet_address: адрес кошелька
        task_type: тип задачи
        status: новый статус ('pending', 'in_progress', 'completed', 'failed')
        error_message: сообщение об ошибке (опционально)
    """
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            
            if status == 'completed':
                cursor.execute('''
                    UPDATE neura_wallet_tasks 
                    SET status = ?, completed_at = ?, updated_at = ?, error_message = NULL
                    WHERE wallet_address = ? AND task_type = ?
                ''', (status, now, now, wallet_address, task_type))
            elif status == 'failed':
                cursor.execute('''
                    UPDATE neura_wallet_tasks 
                    SET status = ?, attempts = attempts + 1, last_attempt = ?, 
                        updated_at = ?, error_message = ?
                    WHERE wallet_address = ? AND task_type = ?
                ''', (status, now, now, error_message, wallet_address, task_type))
            else:
                cursor.execute('''
                    UPDATE neura_wallet_tasks 
                    SET status = ?, updated_at = ?
                    WHERE wallet_address = ? AND task_type = ?
                ''', (status, now, wallet_address, task_type))
            
            conn.commit()


def increment_task_attempts(wallet_address: str, task_type: str):
    """Увеличить счетчик попыток для задачи"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE neura_wallet_tasks 
                SET attempts = attempts + 1, last_attempt = ?, updated_at = ?
                WHERE wallet_address = ? AND task_type = ?
            ''', (datetime.now().isoformat(), datetime.now().isoformat(), 
                  wallet_address, task_type))
            
            conn.commit()


def get_task_statistics() -> Dict:
    """Получить статистику по всем задачам"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT task_type, status, COUNT(*) as count
                FROM neura_wallet_tasks
                GROUP BY task_type, status
            ''')
            
            stats = {}
            for row in cursor.fetchall():
                task_type, status, count = row
                if task_type not in stats:
                    stats[task_type] = {}
                stats[task_type][status] = count
            
            return stats


def reset_failed_tasks(task_type: Optional[str] = None, max_attempts: Optional[int] = None):
    """
    Сбросить failed задачи обратно в pending
    
    Args:
        task_type: тип задачи (None = все типы)
        max_attempts: сбросить только задачи с попытками <= max_attempts
    """
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            query = "UPDATE neura_wallet_tasks SET status = 'pending' WHERE status = 'failed'"
            params = []
            
            if task_type:
                query += " AND task_type = ?"
                params.append(task_type)
            
            if max_attempts is not None:
                query += " AND attempts <= ?"
                params.append(max_attempts)
            
            cursor.execute(query, params)
            conn.commit()
            
            return cursor.rowcount


def clear_all_tasks():
    """Очистить все задачи (для отладки)"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM neura_wallet_tasks")
            conn.commit()


def all_tasks_completed(task_types: List[str]) -> bool:
    """
    Проверить, все ли задачи указанных типов завершены (completed)
    
    Args:
        task_types: список типов задач для проверки
    
    Returns:
        True если все задачи completed или БД пуста
    """
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            # Проверяем есть ли вообще задачи
            cursor.execute("SELECT COUNT(*) FROM neura_wallet_tasks")
            total = cursor.fetchone()[0]
            if total == 0:
                return False  # БД пуста - не пересоздаём
            
            # Проверяем есть ли незавершённые задачи
            placeholders = ','.join('?' * len(task_types))
            cursor.execute(f'''
                SELECT COUNT(*) FROM neura_wallet_tasks 
                WHERE task_type IN ({placeholders}) 
                AND status != 'completed'
            ''', task_types)
            
            not_completed = cursor.fetchone()[0]
            return not_completed == 0


def reset_database_for_new_run(task_types: List[str]):
    """
    Сбросить БД для нового запуска - удалить все задачи указанных типов
    
    Args:
        task_types: список типов задач для удаления
    """
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            placeholders = ','.join('?' * len(task_types))
            cursor.execute(f'''
                DELETE FROM neura_wallet_tasks 
                WHERE task_type IN ({placeholders})
            ''', task_types)
            
            deleted = cursor.rowcount
            conn.commit()
            
            return deleted


def get_all_tasks_for_wallet(wallet_address: str) -> List[Dict]:
    """Получить все задачи для кошелька"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM neura_wallet_tasks 
                WHERE wallet_address = ?
                ORDER BY task_type
            ''', (wallet_address,))
            
            return [dict(row) for row in cursor.fetchall()]
