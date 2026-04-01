"""Pharos — работа с базой данных SQLite.

Таблицы:
  wallets          — основная таблица кошельков и их статусов
  cycle_runs       — лог запусков циклов (mode, status, started_at, ...)
  wallet_tasks     — задачи для каждого кошелька в рамках цикла
  cycle_results_*  — результаты завершённых циклов (создаются динамически)
"""
import sqlite3
import json
import threading
from datetime import datetime
from pathlib import Path

DB_FILE = str(Path(__file__).parent.parent.parent / "db" / "pharos_bot.db")

_db_lock = threading.Lock()


def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ═══════════════════════════════════════════════════════════
# Инициализация схемы
# ═══════════════════════════════════════════════════════════

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

    # Миграция: добавить колонки если таблица уже существует без них
    for col, default in [
        ("faroswap_faucet_status", "'pending'"),
        ("last_faroswap_claim", "NULL"),
        ("account_name", "NULL"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE wallets ADD COLUMN {col} TEXT DEFAULT {default}")
        except Exception:
            pass

    # --- cycle_runs: лог запусков циклов ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cycle_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            total_wallets INTEGER DEFAULT 0,
            processed_wallets INTEGER DEFAULT 0,
            successful INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            cycle_number INTEGER DEFAULT 1,
            stretch_hours REAL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            results_table TEXT
        )
    """)

    # --- wallet_tasks: задачи кошельков в рамках цикла ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_run_id INTEGER NOT NULL,
            wallet_address TEXT NOT NULL,
            wallet_index INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            scheduled_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            result_json TEXT,
            error TEXT,
            FOREIGN KEY (cycle_run_id) REFERENCES cycle_runs(id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_wallet_tasks_cycle
        ON wallet_tasks(cycle_run_id, status)
    """)

    conn.commit()


# ═══════════════════════════════════════════════════════════
# Wallets CRUD
# ═══════════════════════════════════════════════════════════

def create_database(wallets_data: list[dict]):
    """Создать/обновить базу данных с кошельками."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        cursor = conn.cursor()

        for w in wallets_data:
            try:
                pk = w["private_key"]
                cursor.execute("""
                    INSERT OR REPLACE INTO wallets (private_key, address, account_name, proxy, jwt_token,
                        last_faucet_claim, faucet_status, last_faroswap_claim, faroswap_faucet_status,
                        checkin_status, quests_completed, total_points)
                    VALUES (?, ?, ?, ?,
                        COALESCE((SELECT jwt_token FROM wallets WHERE private_key = ?), NULL),
                        COALESCE((SELECT last_faucet_claim FROM wallets WHERE private_key = ?), NULL),
                        COALESCE((SELECT faucet_status FROM wallets WHERE private_key = ?), 'pending'),
                        COALESCE((SELECT last_faroswap_claim FROM wallets WHERE private_key = ?), NULL),
                        COALESCE((SELECT faroswap_faucet_status FROM wallets WHERE private_key = ?), 'pending'),
                        COALESCE((SELECT checkin_status FROM wallets WHERE private_key = ?), 'pending'),
                        COALESCE((SELECT quests_completed FROM wallets WHERE private_key = ?), '[]'),
                        COALESCE((SELECT total_points FROM wallets WHERE private_key = ?), 0))
                """, (pk, w["address"], w.get("account_name"), w.get("proxy"), pk, pk, pk, pk, pk, pk, pk, pk))
            except Exception as e:
                print(f"  [!] Ошибка добавления {w['address'][:10]}...: {e}")

        conn.commit()
        conn.close()


def ensure_wallets(wallets_data: list[dict]):
    """Автоматическая инициализация: создать БД и синхронизировать кошельки из data.csv.
    Вызывается автоматически перед каждой операцией."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)

        existing = {row["private_key"] for row in conn.execute("SELECT private_key FROM wallets").fetchall()}
        new_wallets = [w for w in wallets_data if w["private_key"] not in existing]

        if new_wallets:
            for w in new_wallets:
                try:
                    conn.execute("""
                        INSERT INTO wallets (private_key, address, account_name, proxy)
                        VALUES (?, ?, ?, ?)
                    """, (w["private_key"], w["address"], w.get("account_name"), w.get("proxy")))
                except Exception:
                    pass
            conn.commit()

        # Обновить прокси и account_name для существующих
        for w in wallets_data:
            if w["private_key"] in existing:
                conn.execute("""
                    UPDATE wallets SET proxy = ?, account_name = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE private_key = ?
                """, (w.get("proxy"), w.get("account_name"), w["private_key"]))
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


# ═══════════════════════════════════════════════════════════
# Cycle Runs — управление запусками циклов
# ═══════════════════════════════════════════════════════════

def create_cycle_run(mode: str, total_wallets: int, cycle_number: int = 1,
                     stretch_hours: float = 0) -> int:
    """Создать новый запуск цикла. Возвращает cycle_run_id."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        cursor = conn.execute("""
            INSERT INTO cycle_runs (mode, status, total_wallets, cycle_number,
                                    stretch_hours, started_at)
            VALUES (?, 'running', ?, ?, ?, ?)
        """, (mode, total_wallets, cycle_number, stretch_hours,
              datetime.now().isoformat()))
        run_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return run_id


def get_active_cycle_run(mode: str) -> dict | None:
    """Найти незавершённый цикл для данного режима (для resume)."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        row = conn.execute("""
            SELECT * FROM cycle_runs
            WHERE mode = ? AND status = 'running'
            ORDER BY id DESC LIMIT 1
        """, (mode,)).fetchone()
        conn.close()
        return dict(row) if row else None


def finish_cycle_run(run_id: int, successful: int, failed: int):
    """Завершить запуск цикла и создать таблицу результатов."""
    with _db_lock:
        conn = get_connection()
        now = datetime.now()
        results_table = f"cycle_results_{now.strftime('%Y%m%d_%H%M%S')}"

        conn.execute("""
            UPDATE cycle_runs SET status = 'completed', successful = ?, failed = ?,
                finished_at = ?, results_table = ?
            WHERE id = ?
        """, (successful, failed, now.isoformat(), results_table, run_id))

        # Создать таблицу результатов из wallet_tasks
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS [{results_table}] (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                wallet_index INTEGER,
                account_name TEXT,
                status TEXT,
                started_at TEXT,
                finished_at TEXT,
                result_json TEXT,
                error TEXT
            )
        """)

        # Скопировать результаты
        conn.execute(f"""
            INSERT INTO [{results_table}]
                (wallet_address, wallet_index, status, started_at, finished_at, result_json, error)
            SELECT
                wt.wallet_address, wt.wallet_index, wt.status,
                wt.started_at, wt.finished_at, wt.result_json, wt.error
            FROM wallet_tasks wt
            WHERE wt.cycle_run_id = ?
        """, (run_id,))

        # Добавить account_name из wallets
        conn.execute(f"""
            UPDATE [{results_table}] SET account_name = (
                SELECT w.account_name FROM wallets w
                WHERE w.address = [{results_table}].wallet_address
            )
        """)

        conn.commit()
        conn.close()
        return results_table


def update_cycle_progress(run_id: int, processed: int):
    """Обновить прогресс цикла."""
    with _db_lock:
        conn = get_connection()
        conn.execute("""
            UPDATE cycle_runs SET processed_wallets = ? WHERE id = ?
        """, (processed, run_id))
        conn.commit()
        conn.close()


# ═══════════════════════════════════════════════════════════
# Wallet Tasks — задачи кошельков в рамках цикла
# ═══════════════════════════════════════════════════════════

def create_wallet_tasks(run_id: int, wallets: list[dict], scheduled_times: list[str] = None):
    """Создать задачи для всех кошельков в рамках цикла."""
    with _db_lock:
        conn = get_connection()
        for i, w in enumerate(wallets):
            scheduled = scheduled_times[i] if scheduled_times and i < len(scheduled_times) else None
            conn.execute("""
                INSERT INTO wallet_tasks (cycle_run_id, wallet_address, wallet_index, status, scheduled_at)
                VALUES (?, ?, ?, 'pending', ?)
            """, (run_id, w["address"], i, scheduled))
        conn.commit()
        conn.close()


def get_pending_tasks(run_id: int) -> list[dict]:
    """Получить все невыполненные задачи для цикла."""
    with _db_lock:
        conn = get_connection()
        rows = conn.execute("""
            SELECT wt.*, w.private_key, w.proxy, w.jwt_token, w.account_name
            FROM wallet_tasks wt
            JOIN wallets w ON w.address = wt.wallet_address
            WHERE wt.cycle_run_id = ? AND wt.status = 'pending'
            ORDER BY wt.wallet_index
        """, (run_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_all_tasks_for_run(run_id: int) -> list[dict]:
    """Получить все задачи для цикла (вкл. завершённые)."""
    with _db_lock:
        conn = get_connection()
        rows = conn.execute("""
            SELECT wt.*, w.private_key, w.proxy, w.jwt_token, w.account_name
            FROM wallet_tasks wt
            JOIN wallets w ON w.address = wt.wallet_address
            WHERE wt.cycle_run_id = ?
            ORDER BY wt.wallet_index
        """, (run_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def update_task_status(task_id: int, status: str, result_json: str = None, error: str = None):
    """Обновить статус задачи кошелька."""
    with _db_lock:
        conn = get_connection()
        now = datetime.now().isoformat()
        if status == "running":
            conn.execute("""
                UPDATE wallet_tasks SET status = ?, started_at = ? WHERE id = ?
            """, (status, now, task_id))
        else:
            conn.execute("""
                UPDATE wallet_tasks SET status = ?, finished_at = ?, result_json = ?, error = ?
                WHERE id = ?
            """, (status, now, result_json, error, task_id))
        conn.commit()
        conn.close()


def get_completed_task_count(run_id: int) -> tuple[int, int]:
    """Вернуть (successful, failed) для цикла."""
    with _db_lock:
        conn = get_connection()
        success = conn.execute("""
            SELECT COUNT(*) FROM wallet_tasks WHERE cycle_run_id = ? AND status = 'completed'
        """, (run_id,)).fetchone()[0]
        failed = conn.execute("""
            SELECT COUNT(*) FROM wallet_tasks WHERE cycle_run_id = ? AND status = 'failed'
        """, (run_id,)).fetchone()[0]
        conn.close()
        return success, failed


# ═══════════════════════════════════════════════════════════
# Results tables — чтение результатов из таблиц цикла
# ═══════════════════════════════════════════════════════════

def get_cycle_results(results_table: str) -> list[dict]:
    """Прочитать результаты из таблицы цикла."""
    with _db_lock:
        conn = get_connection()
        try:
            rows = conn.execute(f"SELECT * FROM [{results_table}] ORDER BY id").fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            conn.close()
            return []


def list_results_tables() -> list[dict]:
    """Вернуть список всех завершённых циклов с их таблицами результатов."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        rows = conn.execute("""
            SELECT id, mode, cycle_number, total_wallets, successful, failed,
                   started_at, finished_at, results_table, stretch_hours
            FROM cycle_runs
            WHERE status = 'completed' AND results_table IS NOT NULL
            ORDER BY id DESC
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_last_cycle_number(mode: str) -> int:
    """Получить номер последнего завершённого цикла."""
    with _db_lock:
        conn = get_connection()
        _init_schema(conn)
        row = conn.execute("""
            SELECT MAX(cycle_number) FROM cycle_runs WHERE mode = ?
        """, (mode,)).fetchone()
        conn.close()
        return row[0] if row and row[0] else 0
