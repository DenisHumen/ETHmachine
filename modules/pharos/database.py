"""Pharos — работа с базой данных SQLite."""
import sqlite3
import json
import threading
from pathlib import Path

DB_FILE = str(Path(__file__).parent.parent.parent / "db" / "pharos_bot.db")

_db_lock = threading.Lock()


def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def create_database(wallets_data: list[dict]):
    """Создать/обновить базу данных с кошельками."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                private_key TEXT NOT NULL UNIQUE,
                address TEXT NOT NULL,
                proxy TEXT,
                jwt_token TEXT,
                last_faucet_claim TEXT,
                faucet_status TEXT DEFAULT 'pending',
                last_faroswap_claim TEXT,
                faroswap_faucet_status TEXT DEFAULT 'pending',
                checkin_status TEXT DEFAULT 'pending',
                quests_completed TEXT DEFAULT '[]',
                total_points INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Миграция: добавить колонки faroswap если таблица уже существует без них
        for col, default in [("faroswap_faucet_status", "'pending'"), ("last_faroswap_claim", "NULL")]:
            try:
                cursor.execute(f"ALTER TABLE wallets ADD COLUMN {col} TEXT DEFAULT {default}")
            except Exception:
                pass

        for w in wallets_data:
            try:
                pk = w["private_key"]
                cursor.execute("""
                    INSERT OR REPLACE INTO wallets (private_key, address, proxy, jwt_token,
                        last_faucet_claim, faucet_status, last_faroswap_claim, faroswap_faucet_status,
                        checkin_status, quests_completed, total_points)
                    VALUES (?, ?, ?,
                        COALESCE((SELECT jwt_token FROM wallets WHERE private_key = ?), NULL),
                        COALESCE((SELECT last_faucet_claim FROM wallets WHERE private_key = ?), NULL),
                        COALESCE((SELECT faucet_status FROM wallets WHERE private_key = ?), 'pending'),
                        COALESCE((SELECT last_faroswap_claim FROM wallets WHERE private_key = ?), NULL),
                        COALESCE((SELECT faroswap_faucet_status FROM wallets WHERE private_key = ?), 'pending'),
                        COALESCE((SELECT checkin_status FROM wallets WHERE private_key = ?), 'pending'),
                        COALESCE((SELECT quests_completed FROM wallets WHERE private_key = ?), '[]'),
                        COALESCE((SELECT total_points FROM wallets WHERE private_key = ?), 0))
                """, (pk, w["address"], w["proxy"], pk, pk, pk, pk, pk, pk, pk, pk))
            except Exception as e:
                print(f"  [!] Ошибка добавления {w['address'][:10]}...: {e}")

        conn.commit()
        conn.close()


def get_all_wallets() -> list[dict]:
    """Получить все кошельки из базы."""
    with _db_lock:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM wallets ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]


def update_wallet(address: str, **kwargs):
    """Обновить поля кошелька (thread-safe)."""
    with _db_lock:
        conn = get_connection()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [address]
        conn.execute(
            f"UPDATE wallets SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE address = ?",
            values
        )
        conn.commit()
        conn.close()


def update_jwt(address: str, jwt_token: str):
    update_wallet(address, jwt_token=jwt_token)


def update_faucet_status(address: str, status: str, claim_time: str = None):
    kwargs = {"faucet_status": status}
    if claim_time:
        kwargs["last_faucet_claim"] = claim_time
    update_wallet(address, **kwargs)


def update_faroswap_faucet_status(address: str, status: str, claim_time: str = None):
    kwargs = {"faroswap_faucet_status": status}
    if claim_time:
        kwargs["last_faroswap_claim"] = claim_time
    update_wallet(address, **kwargs)


def update_checkin_status(address: str, status: str):
    update_wallet(address, checkin_status=status)


def update_quests(address: str, completed_ids: list):
    update_wallet(address, quests_completed=json.dumps(completed_ids))


def update_proxy(address: str, proxy: str):
    update_wallet(address, proxy=proxy)


def get_completed_quests(address: str) -> list:
    with _db_lock:
        conn = get_connection()
        row = conn.execute(
            "SELECT quests_completed FROM wallets WHERE address = ?", (address,)
        ).fetchone()
        conn.close()
    if row and row["quests_completed"]:
        try:
            return json.loads(row["quests_completed"])
        except json.JSONDecodeError:
            return []
    return []


def reset_daily_statuses():
    """Сбросить ежедневные статусы (faucet, checkin, faroswap)."""
    with _db_lock:
        conn = get_connection()
        conn.execute("""
            UPDATE wallets SET faucet_status = 'pending', faroswap_faucet_status = 'pending',
            checkin_status = 'pending', updated_at = CURRENT_TIMESTAMP
        """)
        conn.commit()
        conn.close()
