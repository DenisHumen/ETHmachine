"""
Database для Zora Claimer
Хранение задач, статистики и результатов клейма
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from threading import Lock

DB_DIR = Path(__file__).parent.parent.parent.parent / "db"
DB_FILE = DB_DIR / "zora_claimer.db"

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
                CREATE TABLE IF NOT EXISTS claim_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL,
                    network TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    claimable_wei TEXT DEFAULT '0',
                    claimable_eth REAL DEFAULT 0.0,
                    claimed_wei TEXT DEFAULT '0',
                    claimed_eth REAL DEFAULT 0.0,
                    tx_hash TEXT,
                    explorer_link TEXT,
                    gas_used TEXT,
                    gas_price TEXT,
                    gas_cost_eth REAL DEFAULT 0.0,
                    error_message TEXT,
                    attempts INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    UNIQUE(wallet_address, network)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS claim_statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    total_wallets INTEGER DEFAULT 0,
                    total_claimed_eth REAL DEFAULT 0.0,
                    total_gas_cost_eth REAL DEFAULT 0.0,
                    total_successful INTEGER DEFAULT 0,
                    total_failed INTEGER DEFAULT 0,
                    total_skipped INTEGER DEFAULT 0,
                    run_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    run_finished_at TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_claim_wallet_network
                ON claim_tasks(wallet_address, network)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_claim_status
                ON claim_tasks(status)
            ''')

            conn.commit()


def create_claim_tasks(wallets: List[Tuple[str, str]], networks: List[str]):
    """
    Создание задач для клейма

    Args:
        wallets: список (address, private_key)
        networks: список сетей ['base', 'zora']
    """
    init_database()

    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()

            for wallet_address, _ in wallets:
                for network in networks:
                    cursor.execute('''
                        INSERT OR IGNORE INTO claim_tasks
                        (wallet_address, network, status)
                        VALUES (?, ?, 'pending')
                    ''', (wallet_address, network))

            conn.commit()


def get_pending_tasks() -> List[Dict]:
    """Получить незавершённые задачи"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, wallet_address, network, status, claimable_wei,
                       claimable_eth, attempts, error_message
                FROM claim_tasks
                WHERE status IN ('pending', 'failed', 'in_progress')
                ORDER BY attempts ASC, created_at ASC
            ''')

            return [dict(row) for row in cursor.fetchall()]


def get_task(wallet_address: str, network: str) -> Optional[Dict]:
    """Получить задачу по адресу и сети"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT * FROM claim_tasks
                WHERE wallet_address = ? AND network = ?
            ''', (wallet_address, network))

            row = cursor.fetchone()
            return dict(row) if row else None


def update_task_claimable(wallet_address: str, network: str, claimable_wei: str, claimable_eth: float):
    """Обновить информацию о доступном клейме"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute('''
                UPDATE claim_tasks
                SET claimable_wei = ?, claimable_eth = ?, updated_at = ?
                WHERE wallet_address = ? AND network = ?
            ''', (claimable_wei, claimable_eth, now, wallet_address, network))

            conn.commit()


def update_task_status(
    wallet_address: str,
    network: str,
    status: str,
    tx_hash: Optional[str] = None,
    explorer_link: Optional[str] = None,
    claimed_wei: Optional[str] = None,
    claimed_eth: Optional[float] = None,
    gas_used: Optional[str] = None,
    gas_price: Optional[str] = None,
    gas_cost_eth: Optional[float] = None,
    error_message: Optional[str] = None
):
    """Обновить статус задачи"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            if status == 'completed':
                cursor.execute('''
                    UPDATE claim_tasks
                    SET status = ?, tx_hash = ?, explorer_link = ?,
                        claimed_wei = ?, claimed_eth = ?,
                        gas_used = ?, gas_price = ?, gas_cost_eth = ?,
                        completed_at = ?, updated_at = ?, error_message = NULL
                    WHERE wallet_address = ? AND network = ?
                ''', (status, tx_hash, explorer_link,
                      claimed_wei or '0', claimed_eth or 0.0,
                      gas_used, gas_price, gas_cost_eth or 0.0,
                      now, now, wallet_address, network))
            elif status == 'skipped':
                cursor.execute('''
                    UPDATE claim_tasks
                    SET status = ?, updated_at = ?, error_message = ?
                    WHERE wallet_address = ? AND network = ?
                ''', (status, now, error_message, wallet_address, network))
            elif status == 'failed':
                cursor.execute('''
                    UPDATE claim_tasks
                    SET status = ?, attempts = attempts + 1,
                        updated_at = ?, error_message = ?
                    WHERE wallet_address = ? AND network = ?
                ''', (status, now, error_message, wallet_address, network))
            else:
                cursor.execute('''
                    UPDATE claim_tasks
                    SET status = ?, updated_at = ?
                    WHERE wallet_address = ? AND network = ?
                ''', (status, now, wallet_address, network))

            conn.commit()


def get_task_statistics() -> Dict:
    """Получить статистику задач"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT network, status, COUNT(*) as count,
                       SUM(claimed_eth) as total_claimed,
                       SUM(gas_cost_eth) as total_gas
                FROM claim_tasks
                GROUP BY network, status
            ''')

            stats = {}
            for row in cursor.fetchall():
                network, status, count, total_claimed, total_gas = row
                if network not in stats:
                    stats[network] = {}
                stats[network][status] = {
                    'count': count,
                    'total_claimed': total_claimed or 0.0,
                    'total_gas': total_gas or 0.0
                }

            return stats


def get_all_results() -> List[Dict]:
    """Получить все результаты для экспорта"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT wallet_address, network, status,
                       claimable_eth, claimed_eth, gas_cost_eth,
                       tx_hash, explorer_link, error_message,
                       created_at, completed_at
                FROM claim_tasks
                ORDER BY wallet_address, network
            ''')

            return [dict(row) for row in cursor.fetchall()]


def all_tasks_completed() -> bool:
    """Проверить, все ли задачи завершены"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM claim_tasks")
            total = cursor.fetchone()[0]
            if total == 0:
                return False

            cursor.execute('''
                SELECT COUNT(*) FROM claim_tasks
                WHERE status NOT IN ('completed', 'skipped')
            ''')

            not_completed = cursor.fetchone()[0]
            return not_completed == 0


def reset_database():
    """Очистить базу данных"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM claim_tasks")
            deleted = cursor.rowcount
            conn.commit()
            return deleted


def get_total_tasks_count() -> int:
    """Общее количество задач"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM claim_tasks")
            return cursor.fetchone()[0]
