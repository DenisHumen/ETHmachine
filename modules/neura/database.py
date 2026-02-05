import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from threading import Lock

DB_DIR = Path(__file__).parent.parent.parent / "db"
DB_FILE = DB_DIR / "neura_tasks.db"

db_lock = Lock()


def ensure_db_directory():
    DB_DIR.mkdir(parents=True, exist_ok=True)


def get_private_key_hash(private_key: str) -> str:
    return hashlib.sha256(private_key.encode()).hexdigest()[:16]


def init_database():
    ensure_db_directory()
    
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
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
    init_database()
    
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            for wallet_address, private_key in wallets:
                pk_hash = get_private_key_hash(private_key)
                
                for task_type in task_types:
                    cursor.execute('''
                        INSERT OR IGNORE INTO neura_wallet_tasks 
                        (wallet_address, private_key_hash, task_type, status)
                        VALUES (?, ?, ?, 'pending')
                    ''', (wallet_address, pk_hash, task_type))
            
            conn.commit()


def get_pending_tasks(task_type: str) -> List[Dict]:
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


def get_task_statistics() -> Dict:
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


def all_tasks_completed(task_types: List[str]) -> bool:
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
