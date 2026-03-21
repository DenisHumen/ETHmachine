"""
База данных для DeBank Balance Checker
Хранение задач и результатов проверки балансов
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from threading import Lock

DB_DIR = Path(__file__).parent.parent.parent / "db"
DB_FILE = DB_DIR / "debank_checker.db"

db_lock = Lock()


def ensure_db_directory():
    DB_DIR.mkdir(parents=True, exist_ok=True)


def init_database():
    ensure_db_directory()

    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS debank_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL UNIQUE,
                    account_name TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Миграция: добавить account_name если таблица уже существует
            try:
                cursor.execute("ALTER TABLE debank_tasks ADD COLUMN account_name TEXT")
            except Exception:
                pass

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS debank_balances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL,
                    chain TEXT NOT NULL,
                    token_symbol TEXT NOT NULL,
                    token_name TEXT,
                    token_address TEXT,
                    balance REAL DEFAULT 0,
                    price_usd REAL DEFAULT 0,
                    value_usd REAL DEFAULT 0,
                    logo_url TEXT,
                    UNIQUE(wallet_address, chain, token_address)
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_debank_tasks_status
                ON debank_tasks(status)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_debank_balances_wallet
                ON debank_balances(wallet_address)
            ''')

            # Таблица протоколов (DeFi позиции)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS debank_protocols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL,
                    protocol_name TEXT NOT NULL,
                    protocol_id TEXT,
                    chain TEXT NOT NULL,
                    position_type TEXT NOT NULL,
                    pool_name TEXT,
                    balance REAL DEFAULT 0,
                    balance_token TEXT,
                    value_usd REAL DEFAULT 0,
                    unlock_time TEXT,
                    health_rate TEXT,
                    extra_data TEXT,
                    UNIQUE(wallet_address, protocol_id, chain, position_type, pool_name)
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_debank_protocols_wallet
                ON debank_protocols(wallet_address)
            ''')

            # Таблица задач для протоколов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS debank_protocol_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_debank_protocol_tasks_status
                ON debank_protocol_tasks(status)
            ''')

            conn.commit()


def create_tasks(wallets: List[str]):
    init_database()

    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            for wallet in wallets:
                cursor.execute('''
                    INSERT OR IGNORE INTO debank_tasks (wallet_address, status)
                    VALUES (?, 'pending')
                ''', (wallet,))
            conn.commit()


def get_pending_tasks() -> List[Dict]:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, wallet_address, status, attempts
                FROM debank_tasks
                WHERE status IN ('pending', 'failed')
                ORDER BY attempts ASC, created_at ASC
            ''')
            return [dict(row) for row in cursor.fetchall()]


def update_task_status(wallet_address: str, status: str, error_message: Optional[str] = None):
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            if status == 'completed':
                cursor.execute('''
                    UPDATE debank_tasks
                    SET status = ?, updated_at = ?, attempts = attempts + 1, error_message = NULL
                    WHERE wallet_address = ?
                ''', (status, now, wallet_address))
            elif status == 'failed':
                cursor.execute('''
                    UPDATE debank_tasks
                    SET status = ?, error_message = ?, updated_at = ?, attempts = attempts + 1
                    WHERE wallet_address = ?
                ''', (status, error_message, now, wallet_address))
            else:
                cursor.execute('''
                    UPDATE debank_tasks
                    SET status = ?, updated_at = ?
                    WHERE wallet_address = ?
                ''', (status, now, wallet_address))

            conn.commit()


def save_token_balance(wallet_address: str, chain: str, token_symbol: str,
                       token_name: str, token_address: str, balance: float,
                       price_usd: float, value_usd: float, logo_url: str = ''):
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO debank_balances
                (wallet_address, chain, token_symbol, token_name, token_address, balance, price_usd, value_usd, logo_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wallet_address, chain, token_address)
                DO UPDATE SET
                    token_symbol = excluded.token_symbol,
                    token_name = excluded.token_name,
                    balance = excluded.balance,
                    price_usd = excluded.price_usd,
                    value_usd = excluded.value_usd,
                    logo_url = excluded.logo_url
            ''', (wallet_address, chain, token_symbol, token_name, token_address,
                  balance, price_usd, value_usd, logo_url))
            conn.commit()


def save_token_balances_batch(balances: List[tuple]):
    """Batch insert/update token balances.
    Each tuple: (wallet_address, chain, token_symbol, token_name, token_address, balance, price_usd, value_usd, logo_url)
    """
    if not balances:
        return

    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO debank_balances
                (wallet_address, chain, token_symbol, token_name, token_address, balance, price_usd, value_usd, logo_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wallet_address, chain, token_address)
                DO UPDATE SET
                    token_symbol = excluded.token_symbol,
                    token_name = excluded.token_name,
                    balance = excluded.balance,
                    price_usd = excluded.price_usd,
                    value_usd = excluded.value_usd,
                    logo_url = excluded.logo_url
            ''', balances)
            conn.commit()


def get_all_balances() -> List[Dict]:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT wallet_address, chain, token_symbol, token_name,
                       token_address, balance, price_usd, value_usd
                FROM debank_balances
                ORDER BY wallet_address, value_usd DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]


def get_wallet_total_usd(wallet_address: str) -> float:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COALESCE(SUM(value_usd), 0)
                FROM debank_balances
                WHERE wallet_address = ?
            ''', (wallet_address,))
            return cursor.fetchone()[0]


def get_task_statistics() -> Dict:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT status, COUNT(*) as count
                FROM debank_tasks
                GROUP BY status
            ''')
            return {row[0]: row[1] for row in cursor.fetchall()}


def reset_database():
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM debank_tasks')
            cursor.execute('DELETE FROM debank_balances')
            conn.commit()


def delete_wallet_balances(wallet_address: str):
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM debank_balances WHERE wallet_address = ?', (wallet_address,))
            conn.commit()


# ─── Protocol positions ───────────────────────────────────────────────

def create_protocol_tasks(wallets: List[str]):
    init_database()
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            for wallet in wallets:
                cursor.execute('''
                    INSERT OR IGNORE INTO debank_protocol_tasks (wallet_address, status)
                    VALUES (?, 'pending')
                ''', (wallet,))
            conn.commit()


def get_pending_protocol_tasks() -> List[Dict]:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, wallet_address, status, attempts
                FROM debank_protocol_tasks
                WHERE status IN ('pending', 'failed')
                ORDER BY attempts ASC, created_at ASC
            ''')
            return [dict(row) for row in cursor.fetchall()]


def update_protocol_task_status(wallet_address: str, status: str, error_message: Optional[str] = None):
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            if status == 'completed':
                cursor.execute('''
                    UPDATE debank_protocol_tasks
                    SET status = ?, updated_at = ?, attempts = attempts + 1, error_message = NULL
                    WHERE wallet_address = ?
                ''', (status, now, wallet_address))
            elif status == 'failed':
                cursor.execute('''
                    UPDATE debank_protocol_tasks
                    SET status = ?, error_message = ?, updated_at = ?, attempts = attempts + 1
                    WHERE wallet_address = ?
                ''', (status, error_message, now, wallet_address))
            else:
                cursor.execute('''
                    UPDATE debank_protocol_tasks
                    SET status = ?, updated_at = ?
                    WHERE wallet_address = ?
                ''', (status, now, wallet_address))
            conn.commit()


def get_protocol_task_statistics() -> Dict:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT status, COUNT(*) as count
                FROM debank_protocol_tasks
                GROUP BY status
            ''')
            return {row[0]: row[1] for row in cursor.fetchall()}


def save_protocol_positions_batch(positions: List[tuple]):
    """Batch insert/update protocol positions.
    Each tuple: (wallet_address, protocol_name, protocol_id, chain, position_type,
                  pool_name, balance, balance_token, value_usd, unlock_time, health_rate, extra_data)
    """
    if not positions:
        return
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO debank_protocols
                (wallet_address, protocol_name, protocol_id, chain, position_type,
                 pool_name, balance, balance_token, value_usd, unlock_time, health_rate, extra_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wallet_address, protocol_id, chain, position_type, pool_name)
                DO UPDATE SET
                    protocol_name = excluded.protocol_name,
                    balance = excluded.balance,
                    balance_token = excluded.balance_token,
                    value_usd = excluded.value_usd,
                    unlock_time = excluded.unlock_time,
                    health_rate = excluded.health_rate,
                    extra_data = excluded.extra_data
            ''', positions)
            conn.commit()


def get_all_protocols() -> List[Dict]:
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT wallet_address, protocol_name, protocol_id, chain, position_type,
                       pool_name, balance, balance_token, value_usd, unlock_time, health_rate, extra_data
                FROM debank_protocols
                ORDER BY wallet_address, value_usd DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]


def delete_wallet_protocols(wallet_address: str):
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM debank_protocols WHERE wallet_address = ?', (wallet_address,))
            conn.commit()


def reset_protocols_database():
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM debank_protocol_tasks')
            cursor.execute('DELETE FROM debank_protocols')
            conn.commit()
