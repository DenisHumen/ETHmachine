"""xStocks — работа с базой данных SQLite.

Таблицы:
  wallets          — основная таблица кошельков и их статусов
  referral_codes   — реферальные коды и статистика использований
  gm_history       — история Say GM
  actions_log      — лог всех действий (для расширяемости)
"""
import sqlite3
import random
import threading
from datetime import datetime
from pathlib import Path

DB_FILE = str(Path(__file__).parent.parent.parent / "db" / "xstocks.db")

_db_lock = threading.Lock()


def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------
# Инициализация схемы
# ---------------------------------------------------------------

def _init_schema(conn):
    """Создать все таблицы если не существуют."""
    cursor = conn.cursor()

    # --- wallets ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            private_key TEXT NOT NULL UNIQUE,
            address TEXT NOT NULL,
            account_name TEXT,
            proxy TEXT,
            reserve_proxy TEXT,
            sol_private_key TEXT,
            sol_address TEXT,

            -- Статусы регистрации
            evm_registered INTEGER DEFAULT 0,
            sol_connected INTEGER DEFAULT 0,
            participated INTEGER DEFAULT 0,

            -- Реферальные данные
            referral_link TEXT,
            referral_code TEXT,
            used_referral_code TEXT,

            -- Статистика (парсинг с главной)
            xboost TEXT DEFAULT '1x',
            referrals_count INTEGER DEFAULT 0,
            referrals_bonus INTEGER DEFAULT 0,
            today_points INTEGER DEFAULT 0,

            -- GM данные
            last_gm_at TEXT,
            next_gm_at TEXT,
            total_gm_count INTEGER DEFAULT 0,

            -- Сессия
            auth_token TEXT,
            cookies TEXT,
            user_agent TEXT,
            browser_data TEXT,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- referral_codes ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referral_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            referral_code TEXT NOT NULL UNIQUE,
            referral_link TEXT,
            usage_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- gm_history ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gm_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            gm_at TEXT NOT NULL,
            next_available_at TEXT,
            success INTEGER DEFAULT 1,
            error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- actions_log (расширяемость — лог любых действий) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS actions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            action_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            details TEXT,
            error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_actions_wallet
        ON actions_log(wallet_address, action_type)
    """)

    conn.commit()

    # Миграция: добавить новые колонки в существующие таблицы
    _migrate_columns(conn)


def _migrate_columns(conn):
    """Добавить колонки, которых нет в старых БД."""
    cursor = conn.cursor()
    existing = {row[1] for row in cursor.execute("PRAGMA table_info(wallets)").fetchall()}
    migrations = {
        "user_agent": "TEXT",
        "browser_data": "TEXT",
    }
    for col, col_type in migrations.items():
        if col not in existing:
            cursor.execute(f"ALTER TABLE wallets ADD COLUMN {col} {col_type}")
    conn.commit()


# ---------------------------------------------------------------
# Wallets CRUD
# ---------------------------------------------------------------

def ensure_wallets(wallets_data: list[dict]) -> int:
    """Инициализация: синхронизировать кошельки из data.csv в БД.
    Сохраняет существующие данные, добавляет новые кошельки."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)

        existing = {}
        for row in conn.execute("SELECT private_key, address FROM wallets").fetchall():
            existing[row["private_key"]] = row["address"]

        for w in wallets_data:
            pk = w["private_key"]
            if pk not in existing:
                conn.execute("""
                    INSERT INTO wallets (private_key, address, account_name, proxy,
                                         reserve_proxy, sol_private_key, sol_address)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (pk, w["address"], w.get("account_name"), w.get("proxy"),
                      w.get("reserve_proxy"), w.get("sol_private_key"), w.get("sol_address")))
            else:
                conn.execute("""
                    UPDATE wallets SET proxy = ?, reserve_proxy = ?, account_name = ?,
                        sol_private_key = ?, sol_address = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE private_key = ?
                """, (w.get("proxy"), w.get("reserve_proxy"), w.get("account_name"),
                      w.get("sol_private_key"), w.get("sol_address"), pk))
        conn.commit()

        total = conn.execute("SELECT COUNT(*) FROM wallets").fetchone()[0]
        conn.close()
        return total


def get_all_wallets() -> list[dict]:
    """Получить все кошельки из базы."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        rows = conn.execute("SELECT * FROM wallets ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_wallet_by_address(address: str) -> dict | None:
    """Получить кошелек по адресу."""
    with _db_lock:
        conn = get_connection()
        row = conn.execute("SELECT * FROM wallets WHERE address = ?", (address,)).fetchone()
        conn.close()
        return dict(row) if row else None


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


def mark_evm_registered(address: str, referral_link: str = None, referral_code: str = None):
    """Отметить EVM регистрацию."""
    kwargs = {"evm_registered": 1, "participated": 1}
    if referral_link:
        kwargs["referral_link"] = referral_link
    if referral_code:
        kwargs["referral_code"] = referral_code
    update_wallet(address, **kwargs)


def mark_sol_connected(address: str, connected: bool = True):
    """Отметить подключение Solana кошелька."""
    update_wallet(address, sol_connected=1 if connected else 0)


def update_auth(address: str, auth_token: str = None, cookies: str = None):
    """Обновить токен авторизации и cookies."""
    kwargs = {}
    if auth_token is not None:
        kwargs["auth_token"] = auth_token
    if cookies is not None:
        kwargs["cookies"] = cookies
    if kwargs:
        update_wallet(address, **kwargs)


def save_session(address: str, user_agent: str = None, auth_token: str = None,
                 cookies: str = None, browser_data: str = None):
    """Сохранить данные сессии (user-agent, cookies, browser fingerprint)."""
    kwargs = {}
    if user_agent is not None:
        kwargs["user_agent"] = user_agent
    if auth_token is not None:
        kwargs["auth_token"] = auth_token
    if cookies is not None:
        kwargs["cookies"] = cookies
    if browser_data is not None:
        kwargs["browser_data"] = browser_data
    if kwargs:
        update_wallet(address, **kwargs)


def get_session(address: str) -> dict | None:
    """Получить сохранённую сессию (user_agent, auth_token, cookies, browser_data)."""
    with _db_lock:
        conn = get_connection()
        row = conn.execute(
            "SELECT user_agent, auth_token, cookies, browser_data FROM wallets WHERE address = ?",
            (address,),
        ).fetchone()
        conn.close()
    if not row:
        return None
    d = dict(row)
    # Вернуть только если есть хотя бы user_agent
    if d.get("user_agent"):
        return d
    return None


def update_stats(address: str, xboost: str = None, referrals_count: int = None,
                 referrals_bonus: int = None, today_points: int = None):
    """Обновить статистику с главной страницы."""
    kwargs = {}
    if xboost is not None:
        kwargs["xboost"] = xboost
    if referrals_count is not None:
        kwargs["referrals_count"] = referrals_count
    if referrals_bonus is not None:
        kwargs["referrals_bonus"] = referrals_bonus
    if today_points is not None:
        kwargs["today_points"] = today_points
    if kwargs:
        update_wallet(address, **kwargs)


def update_gm(address: str, gm_at: str, next_gm_at: str):
    """Обновить данные GM (инкремент total_gm_count)."""
    with _db_lock:
        conn = get_connection()
        conn.execute("""
            UPDATE wallets SET total_gm_count = total_gm_count + 1,
                last_gm_at = ?, next_gm_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE address = ?
        """, (gm_at, next_gm_at, address))
        conn.commit()
        conn.close()


def record_gm_history(address: str, gm_at: str, next_available_at: str,
                      success: bool = True, error: str = None):
    """Записать GM в историю."""
    with _db_lock:
        conn = get_connection()
        conn.execute("""
            INSERT INTO gm_history (wallet_address, gm_at, next_available_at, success, error)
            VALUES (?, ?, ?, ?, ?)
        """, (address, gm_at, next_available_at, 1 if success else 0, error))
        conn.commit()
        conn.close()


def get_wallets_needing_gm() -> list[dict]:
    """Получить кошельки, которым пора делать GM."""
    now = datetime.now().isoformat()
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        rows = conn.execute("""
            SELECT * FROM wallets
            WHERE evm_registered = 1
              AND (next_gm_at IS NULL OR next_gm_at <= ?)
            ORDER BY id
        """, (now,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_wallets_needing_registration() -> list[dict]:
    """Получить кошельки, которые ещё не зарегистрированы."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        rows = conn.execute("""
            SELECT * FROM wallets WHERE evm_registered = 0 ORDER BY id
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_wallets_needing_sol() -> list[dict]:
    """Получить кошельки, у которых есть sol_private_key но sol не подключен."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        rows = conn.execute("""
            SELECT * FROM wallets
            WHERE sol_private_key IS NOT NULL AND sol_private_key != ''
              AND sol_connected = 0
              AND evm_registered = 1
            ORDER BY id
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------
# Referral Codes
# ---------------------------------------------------------------

def save_referral_code(wallet_address: str, referral_code: str, referral_link: str = None):
    """Сохранить реферальный код в таблицу referral_codes."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO referral_codes (wallet_address, referral_code, referral_link)
                VALUES (?, ?, ?)
            """, (wallet_address, referral_code, referral_link))
            conn.commit()
        except Exception:
            pass
        conn.close()


def increment_referral_usage(referral_code: str):
    """Увеличить счётчик использований реферального кода."""
    with _db_lock:
        conn = get_connection()
        conn.execute("""
            UPDATE referral_codes SET usage_count = usage_count + 1 WHERE referral_code = ?
        """, (referral_code,))
        conn.commit()
        conn.close()


def get_random_referral_code(max_diff_percent: int = 50) -> str | None:
    """Получить случайный реферальный код с балансировкой использований.
    Разница использований между кодами не больше max_diff_percent %."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        rows = conn.execute("""
            SELECT referral_code, usage_count FROM referral_codes ORDER BY usage_count ASC
        """).fetchall()
        conn.close()

    if not rows:
        return None

    codes = [dict(r) for r in rows]
    min_usage = codes[0]["usage_count"]

    if min_usage == 0:
        threshold = 1
    else:
        threshold = min_usage * (1 + max_diff_percent / 100)

    eligible = [c for c in codes if c["usage_count"] <= threshold]
    if not eligible:
        eligible = codes[:max(1, len(codes) // 2)]

    chosen = random.choice(eligible)
    return chosen["referral_code"]


def get_all_referral_codes() -> list[dict]:
    """Получить все реферальные коды."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        rows = conn.execute("SELECT * FROM referral_codes ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------
# Actions Log (расширяемость)
# ---------------------------------------------------------------

def log_action(wallet_address: str, action_type: str, status: str = "success",
               details: str = None, error: str = None):
    """Записать действие в лог."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        conn.execute("""
            INSERT INTO actions_log (wallet_address, action_type, status, details, error)
            VALUES (?, ?, ?, ?, ?)
        """, (wallet_address, action_type, status, details, error))
        conn.commit()
        conn.close()


def get_next_gm_time() -> str | None:
    """Получить ближайшее время следующего GM среди всех кошельков."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        row = conn.execute("""
            SELECT MIN(next_gm_at) as next_gm FROM wallets
            WHERE evm_registered = 1 AND next_gm_at IS NOT NULL
        """).fetchone()
        conn.close()
        return row["next_gm"] if row else None


def get_db_stats() -> dict:
    """Общая статистика по БД."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        total = conn.execute("SELECT COUNT(*) FROM wallets").fetchone()[0]
        registered = conn.execute("SELECT COUNT(*) FROM wallets WHERE evm_registered = 1").fetchone()[0]
        sol_connected = conn.execute("SELECT COUNT(*) FROM wallets WHERE sol_connected = 1").fetchone()[0]
        total_gm = conn.execute("SELECT SUM(total_gm_count) FROM wallets").fetchone()[0] or 0
        ref_codes = conn.execute("SELECT COUNT(*) FROM referral_codes").fetchone()[0]
        conn.close()
        return {
            "total_wallets": total,
            "evm_registered": registered,
            "sol_connected": sol_connected,
            "total_gm": total_gm,
            "referral_codes": ref_codes,
        }
