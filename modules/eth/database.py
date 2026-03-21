import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from threading import Lock

DB_DIR = Path(__file__).parent.parent.parent / "db"
DB_FILE = DB_DIR / "eth_balance_tasks.db"

db_lock = Lock()


def ensure_db_directory():
    DB_DIR.mkdir(parents=True, exist_ok=True)


def init_database():
    ensure_db_directory()
    
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS eth_balance_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL,
                    account_name TEXT,
                    task_type TEXT NOT NULL,
                    network TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    balance TEXT,
                    balance_usdt TEXT,
                    attempts INTEGER DEFAULT 0,
                    last_attempt TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(wallet_address, task_type, network)
                )
            ''')

            # Миграция: добавить account_name если таблица уже существует
            try:
                cursor.execute("ALTER TABLE eth_balance_tasks ADD COLUMN account_name TEXT")
            except Exception:
                pass
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_wallet_task 
                ON eth_balance_tasks(wallet_address, task_type)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status 
                ON eth_balance_tasks(status)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_task_network 
                ON eth_balance_tasks(task_type, network)
            ''')
            
            conn.commit()


def create_balance_tasks(wallets: List[str], task_type: str, network: Optional[str] = None):
    init_database()
    
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            for wallet_address in wallets:
                cursor.execute('''
                    INSERT OR IGNORE INTO eth_balance_tasks 
                    (wallet_address, task_type, network, status)
                    VALUES (?, ?, ?, 'pending')
                ''', (wallet_address, task_type, network))
            
            conn.commit()


def get_pending_tasks(task_type: str, network: Optional[str] = None) -> List[Dict]:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if network:
                cursor.execute('''
                    SELECT id, wallet_address, task_type, network, status, attempts
                    FROM eth_balance_tasks 
                    WHERE task_type = ? AND network = ? AND status IN ('pending', 'failed', 'in_progress')
                    ORDER BY attempts ASC, created_at ASC
                ''', (task_type, network))
            else:
                cursor.execute('''
                    SELECT id, wallet_address, task_type, network, status, attempts
                    FROM eth_balance_tasks 
                    WHERE task_type = ? AND status IN ('pending', 'failed', 'in_progress')
                    ORDER BY attempts ASC, created_at ASC
                ''', (task_type,))
            
            return [dict(row) for row in cursor.fetchall()]


def get_wallet_task_status(wallet_address: str, task_type: str, network: Optional[str] = None) -> Optional[Dict]:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if network:
                cursor.execute('''
                    SELECT * FROM eth_balance_tasks 
                    WHERE wallet_address = ? AND task_type = ? AND network = ?
                ''', (wallet_address, task_type, network))
            else:
                cursor.execute('''
                    SELECT * FROM eth_balance_tasks 
                    WHERE wallet_address = ? AND task_type = ?
                ''', (wallet_address, task_type))
            
            row = cursor.fetchone()
            return dict(row) if row else None


def update_task_status(
    wallet_address: str, 
    task_type: str, 
    status: str,
    network: Optional[str] = None,
    balance: Optional[str] = None,
    balance_usdt: Optional[str] = None,
    error_message: Optional[str] = None
):

    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            
            if status == 'completed':
                if network:
                    cursor.execute('''
                        UPDATE eth_balance_tasks 
                        SET status = ?, balance = ?, balance_usdt = ?, 
                            completed_at = ?, updated_at = ?, attempts = attempts + 1
                        WHERE wallet_address = ? AND task_type = ? AND network = ?
                    ''', (status, balance, balance_usdt, now, now, wallet_address, task_type, network))
                else:
                    cursor.execute('''
                        UPDATE eth_balance_tasks 
                        SET status = ?, balance = ?, balance_usdt = ?, 
                            completed_at = ?, updated_at = ?, attempts = attempts + 1
                        WHERE wallet_address = ? AND task_type = ?
                    ''', (status, balance, balance_usdt, now, now, wallet_address, task_type))
            elif status == 'failed':
                if network:
                    cursor.execute('''
                        UPDATE eth_balance_tasks 
                        SET status = ?, error_message = ?, last_attempt = ?, 
                            updated_at = ?, attempts = attempts + 1
                        WHERE wallet_address = ? AND task_type = ? AND network = ?
                    ''', (status, error_message, now, now, wallet_address, task_type, network))
                else:
                    cursor.execute('''
                        UPDATE eth_balance_tasks 
                        SET status = ?, error_message = ?, last_attempt = ?, 
                            updated_at = ?, attempts = attempts + 1
                        WHERE wallet_address = ? AND task_type = ?
                    ''', (status, error_message, now, now, wallet_address, task_type))
            else:  # in_progress или pending
                if network:
                    cursor.execute('''
                        UPDATE eth_balance_tasks 
                        SET status = ?, last_attempt = ?, updated_at = ?
                        WHERE wallet_address = ? AND task_type = ? AND network = ?
                    ''', (status, now, now, wallet_address, task_type, network))
                else:
                    cursor.execute('''
                        UPDATE eth_balance_tasks 
                        SET status = ?, last_attempt = ?, updated_at = ?
                        WHERE wallet_address = ? AND task_type = ?
                    ''', (status, now, now, wallet_address, task_type))
            
            conn.commit()


def get_task_statistics(task_type: Optional[str] = None, network: Optional[str] = None) -> Dict:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            if task_type and network:
                cursor.execute('''
                    SELECT status, COUNT(*) as count 
                    FROM eth_balance_tasks 
                    WHERE task_type = ? AND network = ?
                    GROUP BY status
                ''', (task_type, network))
            elif task_type:
                cursor.execute('''
                    SELECT status, COUNT(*) as count 
                    FROM eth_balance_tasks 
                    WHERE task_type = ?
                    GROUP BY status
                ''', (task_type,))
            else:
                cursor.execute('''
                    SELECT status, COUNT(*) as count 
                    FROM eth_balance_tasks 
                    GROUP BY status
                ''')
            
            return {row[0]: row[1] for row in cursor.fetchall()}


def reset_failed_tasks(task_type: Optional[str] = None, network: Optional[str] = None) -> int:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            if task_type and network:
                cursor.execute('''
                    UPDATE eth_balance_tasks 
                    SET status = 'pending', error_message = NULL
                    WHERE status = 'failed' AND task_type = ? AND network = ?
                ''', (task_type, network))
            elif task_type:
                cursor.execute('''
                    UPDATE eth_balance_tasks 
                    SET status = 'pending', error_message = NULL
                    WHERE status = 'failed' AND task_type = ?
                ''', (task_type,))
            else:
                cursor.execute('''
                    UPDATE eth_balance_tasks 
                    SET status = 'pending', error_message = NULL
                    WHERE status = 'failed'
                ''')
            
            count = cursor.rowcount
            conn.commit()
            return count


def all_tasks_completed(task_type: str, network: Optional[str] = None) -> bool:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            if network:
                cursor.execute('''
                    SELECT COUNT(*) FROM eth_balance_tasks 
                    WHERE task_type = ? AND network = ?
                ''', (task_type, network))
            else:
                cursor.execute('''
                    SELECT COUNT(*) FROM eth_balance_tasks 
                    WHERE task_type = ?
                ''', (task_type,))
            
            total = cursor.fetchone()[0]
            if total == 0:
                return False
            
            if network:
                cursor.execute('''
                    SELECT COUNT(*) FROM eth_balance_tasks 
                    WHERE task_type = ? AND network = ? AND status != 'completed'
                ''', (task_type, network))
            else:
                cursor.execute('''
                    SELECT COUNT(*) FROM eth_balance_tasks 
                    WHERE task_type = ? AND status != 'completed'
                ''', (task_type,))
            
            incomplete = cursor.fetchone()[0]
            return incomplete == 0


def reset_database_for_new_run(task_type: str, network: Optional[str] = None) -> int:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            if network:
                cursor.execute('''
                    DELETE FROM eth_balance_tasks 
                    WHERE task_type = ? AND network = ?
                ''', (task_type, network))
            else:
                cursor.execute('''
                    DELETE FROM eth_balance_tasks 
                    WHERE task_type = ?
                ''', (task_type,))
            
            count = cursor.rowcount
            conn.commit()
            return count


def get_completed_results(task_type: str, network: Optional[str] = None) -> List[Dict]:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if network:
                cursor.execute('''
                    SELECT wallet_address, balance, balance_usdt, network, completed_at
                    FROM eth_balance_tasks 
                    WHERE task_type = ? AND network = ? AND status = 'completed'
                    ORDER BY id ASC
                ''', (task_type, network))
            else:
                cursor.execute('''
                    SELECT wallet_address, balance, balance_usdt, network, completed_at
                    FROM eth_balance_tasks 
                    WHERE task_type = ? AND status = 'completed'
                    ORDER BY id ASC
                ''', (task_type,))
            
            return [dict(row) for row in cursor.fetchall()]


def get_all_results(task_type: str, network: Optional[str] = None) -> List[Dict]:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if network:
                cursor.execute('''
                    SELECT wallet_address, balance, balance_usdt, network, status
                    FROM eth_balance_tasks 
                    WHERE task_type = ? AND network = ?
                    ORDER BY id ASC
                ''', (task_type, network))
            else:
                cursor.execute('''
                    SELECT wallet_address, balance, balance_usdt, network, status
                    FROM eth_balance_tasks 
                    WHERE task_type = ?
                    ORDER BY id ASC
                ''', (task_type,))
            
            return [dict(row) for row in cursor.fetchall()]
