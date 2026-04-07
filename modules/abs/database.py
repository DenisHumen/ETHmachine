"""Abstract Portal — работа с базой данных SQLite.

Таблицы:
  wallets          — основная таблица кошельков и их статусов
  sessions         — Privy сессии (access token, cookies)
  badges           — бейджи аккаунта
  xp_history       — история XP по эпохам/неделям
  actions_log      — лог всех действий
"""
import sqlite3
import threading
from pathlib import Path

DB_FILE = str(Path(__file__).parent.parent.parent / "db" / "abs_portal.db")

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

            -- Статус авторизации
            logged_in INTEGER DEFAULT 0,

            -- Профиль
            abs_wallet_address TEXT,
            tier INTEGER DEFAULT 0,
            tier_v2 INTEGER DEFAULT 0,
            tier_name TEXT,
            total_xp INTEGER DEFAULT 0,
            xp_multiplier REAL DEFAULT 1.0,
            eth_balance TEXT,

            -- Streak
            current_streak_days INTEGER DEFAULT 0,
            longest_streak_days INTEGER DEFAULT 0,
            voted_today INTEGER DEFAULT 0,

            -- Socials
            twitter_connected INTEGER DEFAULT 0,
            discord_connected INTEGER DEFAULT 0,

            -- Сессия
            privy_access_token TEXT,
            privy_id_token TEXT,
            privy_refresh_token TEXT,
            session_cookies TEXT,
            user_agent TEXT,

            -- Таймстемпы
            stats_updated_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- sessions (Privy auth data) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL UNIQUE,
            privy_access_token TEXT,
            privy_id_token TEXT,
            privy_refresh_token TEXT,
            cookies TEXT,
            user_agent TEXT,
            client_id TEXT,
            valid INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- badges ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            badge_id INTEGER NOT NULL,
            badge_name TEXT,
            badge_icon TEXT,
            badge_description TEXT,
            badge_requirement TEXT,
            badge_type TEXT,
            claimed INTEGER DEFAULT 0,
            claim_available INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(wallet_address, badge_id)
        )
    """)

    # --- xp_history ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS xp_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            epoch INTEGER NOT NULL,
            description TEXT,
            points INTEGER DEFAULT 0,
            referral_xp INTEGER DEFAULT 0,
            season INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(wallet_address, epoch)
        )
    """)

    # --- actions_log ---
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
        CREATE INDEX IF NOT EXISTS idx_abs_actions_wallet
        ON actions_log(wallet_address, action_type)
    """)

    conn.commit()


# ---------------------------------------------------------------
# Wallets CRUD
# ---------------------------------------------------------------

def ensure_wallets(wallets_data: list[dict]) -> int:
    """Синхронизировать кошельки из data.csv в БД."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            cursor = conn.cursor()
            count = 0
            current_keys = set()
            for w in wallets_data:
                cursor.execute("""
                    INSERT INTO wallets (private_key, address, account_name, proxy, reserve_proxy)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(private_key) DO UPDATE SET
                        account_name = COALESCE(excluded.account_name, wallets.account_name),
                        proxy = COALESCE(excluded.proxy, wallets.proxy),
                        reserve_proxy = COALESCE(excluded.reserve_proxy, wallets.reserve_proxy),
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    w["private_key"], w["address"],
                    w.get("account_name"), w.get("proxy"), w.get("reserve_proxy"),
                ))
                current_keys.add(w["private_key"])
                count += 1

            # Удалить кошельки, которых нет в текущем файле данных
            if current_keys:
                placeholders = ",".join("?" for _ in current_keys)
                cursor.execute(
                    f"DELETE FROM wallets WHERE private_key NOT IN ({placeholders})",
                    list(current_keys),
                )

            conn.commit()
            return count
        finally:
            conn.close()


def get_all_wallets() -> list[dict]:
    """Получить все кошельки."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            rows = conn.execute("SELECT * FROM wallets ORDER BY id").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_wallet(address: str) -> dict | None:
    """Получить кошелёк по адресу."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            row = conn.execute(
                "SELECT * FROM wallets WHERE address = ?", (address,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def update_wallet_profile(address: str, **kwargs):
    """Обновить данные профиля кошелька."""
    with _db_lock:
        conn = get_connection()
        try:
            sets = []
            vals = []
            for k, v in kwargs.items():
                sets.append(f"{k} = ?")
                vals.append(v)
            sets.append("updated_at = CURRENT_TIMESTAMP")
            vals.append(address)
            conn.execute(
                f"UPDATE wallets SET {', '.join(sets)} WHERE address = ?",
                vals,
            )
            conn.commit()
        finally:
            conn.close()


def update_wallet_stats(address: str, tier: int, tier_v2: int, tier_name: str,
                        total_xp: int, xp_multiplier: float,
                        current_streak: int, longest_streak: int, voted_today: bool,
                        twitter: bool, discord: bool,
                        abs_wallet: str = None, eth_balance: str = None):
    """Обновить полную статистику кошелька."""
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                UPDATE wallets SET
                    tier = ?, tier_v2 = ?, tier_name = ?,
                    total_xp = ?, xp_multiplier = ?,
                    current_streak_days = ?, longest_streak_days = ?,
                    voted_today = ?,
                    twitter_connected = ?, discord_connected = ?,
                    abs_wallet_address = COALESCE(?, abs_wallet_address),
                    eth_balance = COALESCE(?, eth_balance),
                    stats_updated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE address = ?
            """, (
                tier, tier_v2, tier_name,
                total_xp, xp_multiplier,
                current_streak, longest_streak, int(voted_today),
                int(twitter), int(discord),
                abs_wallet, eth_balance,
                address,
            ))
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------
# Sessions CRUD
# ---------------------------------------------------------------

def get_session(address: str) -> dict | None:
    """Получить сессию кошелька."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            row = conn.execute(
                "SELECT * FROM sessions WHERE wallet_address = ? AND valid = 1",
                (address,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def save_session(address: str, privy_access_token: str = None,
                 privy_id_token: str = None, privy_refresh_token: str = None,
                 cookies: str = None, user_agent: str = None, client_id: str = None):
    """Сохранить / обновить сессию."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            conn.execute("""
                INSERT INTO sessions (wallet_address, privy_access_token, privy_id_token,
                    privy_refresh_token, cookies, user_agent, client_id, valid, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(wallet_address) DO UPDATE SET
                    privy_access_token = COALESCE(excluded.privy_access_token, sessions.privy_access_token),
                    privy_id_token = COALESCE(excluded.privy_id_token, sessions.privy_id_token),
                    privy_refresh_token = COALESCE(excluded.privy_refresh_token, sessions.privy_refresh_token),
                    cookies = COALESCE(excluded.cookies, sessions.cookies),
                    user_agent = COALESCE(excluded.user_agent, sessions.user_agent),
                    client_id = COALESCE(excluded.client_id, sessions.client_id),
                    valid = 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (address, privy_access_token, privy_id_token,
                  privy_refresh_token, cookies, user_agent, client_id))
            conn.commit()
        finally:
            conn.close()


def invalidate_session(address: str):
    """Пометить сессию как невалидную."""
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE sessions SET valid = 0, updated_at = CURRENT_TIMESTAMP WHERE wallet_address = ?",
                (address,),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------
# Badges CRUD
# ---------------------------------------------------------------

def save_badges(address: str, badges: list[dict]):
    """Сохранить / обновить бейджи."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            for b in badges:
                conn.execute("""
                    INSERT INTO badges (wallet_address, badge_id, badge_name, badge_icon,
                        badge_description, badge_requirement, badge_type,
                        claimed, claim_available, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(wallet_address, badge_id) DO UPDATE SET
                        badge_name = excluded.badge_name,
                        badge_icon = excluded.badge_icon,
                        badge_description = excluded.badge_description,
                        badge_requirement = excluded.badge_requirement,
                        badge_type = excluded.badge_type,
                        claimed = excluded.claimed,
                        claim_available = excluded.claim_available,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    address, b["id"], b.get("name"), b.get("icon"),
                    b.get("description"), b.get("requirement"), b.get("type"),
                    int(b.get("claimed", False)), int(b.get("claim_available", False)),
                ))
            conn.commit()
        finally:
            conn.close()


def get_badges(address: str) -> list[dict]:
    """Получить бейджи кошелька."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            rows = conn.execute(
                "SELECT * FROM badges WHERE wallet_address = ? ORDER BY badge_id",
                (address,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def update_badge_claimed(address: str, badge_id: int):
    """Пометить бейдж как заклеймленный."""
    with _db_lock:
        conn = get_connection()
        try:
            conn.execute("""
                UPDATE badges SET claimed = 1, claim_available = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE wallet_address = ? AND badge_id = ?
            """, (address, badge_id))
            conn.commit()
        finally:
            conn.close()


def get_wallets_with_claimable_badges() -> list[dict]:
    """Получить кошельки, у которых есть бейджи доступные для клейма."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            rows = conn.execute("""
                SELECT DISTINCT w.* FROM wallets w
                INNER JOIN badges b ON w.address = b.wallet_address
                WHERE b.claim_available = 1 AND b.claimed = 0
                ORDER BY w.id
            """).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def get_all_unique_badges() -> list[dict]:
    """Получить список всех уникальных бейджей (id + name) из БД."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            rows = conn.execute(
                "SELECT DISTINCT badge_id, badge_name FROM badges ORDER BY badge_id"
            ).fetchall()
            return [{"badge_id": r["badge_id"], "badge_name": r["badge_name"]} for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------
# XP History
# ---------------------------------------------------------------

def save_xp_history(address: str, xp_items: list[dict]):
    """Сохранить историю XP по эпохам."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            for item in xp_items:
                conn.execute("""
                    INSERT INTO xp_history (wallet_address, epoch, description, points,
                        referral_xp, season, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(wallet_address, epoch) DO UPDATE SET
                        description = excluded.description,
                        points = excluded.points,
                        referral_xp = excluded.referral_xp,
                        season = excluded.season,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    address, item["epoch"], item.get("description"),
                    item.get("points", 0),
                    item.get("referralXp") or item.get("referral_xp") or 0,
                    item.get("season", 0),
                ))
            conn.commit()
        finally:
            conn.close()


def get_xp_history(address: str) -> list[dict]:
    """Получить историю XP кошелька."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            rows = conn.execute(
                "SELECT * FROM xp_history WHERE wallet_address = ? ORDER BY epoch DESC",
                (address,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------
# Actions Log
# ---------------------------------------------------------------

def log_action(address: str, action: str, status: str,
               details: str = None, error: str = None):
    """Записать действие в лог."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            conn.execute(
                "INSERT INTO actions_log (wallet_address, action_type, status, details, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (address, action, status, details, error),
            )
            conn.commit()
        finally:
            conn.close()


def get_pending_actions(action_type: str) -> list[dict]:
    """Получить незавершённые действия."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            rows = conn.execute(
                "SELECT * FROM actions_log WHERE action_type = ? AND status = 'pending' ORDER BY id",
                (action_type,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------
# Статистика БД
# ---------------------------------------------------------------

def get_db_stats() -> dict:
    """Общая статистика для меню."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            total = conn.execute("SELECT COUNT(*) FROM wallets").fetchone()[0]
            logged_in = conn.execute("SELECT COUNT(*) FROM wallets WHERE logged_in = 1").fetchone()[0]
            with_stats = conn.execute("SELECT COUNT(*) FROM wallets WHERE stats_updated_at IS NOT NULL").fetchone()[0]
            total_badges = conn.execute("SELECT COUNT(DISTINCT badge_id) FROM badges").fetchone()[0]
            claimed_badges = conn.execute("SELECT COUNT(*) FROM badges WHERE claimed = 1").fetchone()[0]
            total_xp = conn.execute("SELECT COALESCE(SUM(total_xp), 0) FROM wallets").fetchone()[0]
            return {
                "total_wallets": total,
                "logged_in": logged_in,
                "with_stats": with_stats,
                "unique_badges": total_badges,
                "claimed_badges": claimed_badges,
                "total_xp": total_xp,
            }
        finally:
            conn.close()


def clear_all_tasks():
    """Очистить все задачи и начать заново."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            conn.execute("UPDATE wallets SET logged_in = 0, stats_updated_at = NULL")
            conn.execute("DELETE FROM badges")
            conn.execute("DELETE FROM xp_history")
            conn.execute("DELETE FROM actions_log")
            conn.execute("UPDATE sessions SET valid = 0")
            conn.commit()
        finally:
            conn.close()


def get_incomplete_wallets() -> list[dict]:
    """Получить кошельки без завершённой статистики."""
    with _db_lock:
        conn = get_connection()
        try:
            _init_schema(conn)
            rows = conn.execute(
                "SELECT * FROM wallets WHERE stats_updated_at IS NULL ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
