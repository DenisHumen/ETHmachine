"""Общий слой над SQLite для модульных баз задач.

Каждый модуль хранит прогресс в своей базе под ``db/``. Схемы разные — и
это нормально, менять их нельзя: в них уже лежит состояние пользователей.
Одинаковой была обвязка: открыть соединение с WAL, выполнить запрос,
закрыть, собрать ``{статус: количество}``, пересоздать таблицу.

``SqliteStore`` берёт на себя обвязку. Схема, путь и имена колонок
остаются в модуле.

Использование::

    from modules.core.sqlite_store import SqliteStore

    STORE = SqliteStore(DB_PATH, _SCHEMA, table="swap_all_tasks")

    def init_database() -> None:
        STORE.init()

    def get_statistics() -> dict:
        return STORE.statistics()
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence


class SqliteStore:
    """Соединения, транзакции и типовые запросы для одной таблицы.

    ``connect_factory`` нужен модулям, которые делят одну базу на несколько
    таблиц (например litvm_testnet): они передают общую фабрику соединений.
    """

    def __init__(
        self,
        db_path: str | Path,
        schema_sql: str,
        *,
        table: str,
        pk: str = "id",
        status_column: str = "status",
        timeout: float = 30.0,
        connect_factory: Callable[[], sqlite3.Connection] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.schema_sql = schema_sql
        self.table = table
        self.pk = pk
        self.status_column = status_column
        self.timeout = timeout
        self._connect_factory = connect_factory
        self._lock = threading.Lock()

    # ── Соединения ──────────────────────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        """Новое соединение. Одно соединение на операцию, не шарить между потоками."""
        if self._connect_factory is not None:
            return self._connect_factory()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        # WAL — параллельные читатели не блокируют писателя. Без него
        # веб-панель не может открыть базу, пока модуль работает.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Соединение с коммитом на выходе и откатом при исключении."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Схема ───────────────────────────────────────────────────────────

    def init(self) -> None:
        """Идемпотентное создание схемы."""
        with self._lock, self.connection() as conn:
            conn.executescript(self.schema_sql)

    def reset(self) -> None:
        """Полная очистка таблицы модуля.

        Дропаем только свою таблицу: базу целиком трогать нельзя — в ней
        могут жить таблицы соседних модулей.
        """
        with self._lock, self.connection() as conn:
            conn.execute(f"DROP TABLE IF EXISTS {self.table}")
            conn.executescript(self.schema_sql)

    # ── Запросы ─────────────────────────────────────────────────────────

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Изменяющий запрос. Возвращает ``lastrowid``."""
        with self._lock, self.connection() as conn:
            cursor = conn.execute(sql, tuple(params))
            return int(cursor.lastrowid or 0)

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self._lock, self.connection() as conn:
            conn.executemany(sql, [tuple(r) for r in rows])

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(params))]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        with self.connection() as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
            return row[0] if row else None

    # ── Типовые операции над таблицей ───────────────────────────────────

    def insert(self, values: Mapping[str, Any]) -> int:
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        return self.execute(
            f"INSERT INTO {self.table} ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )

    def update_where(self, where: str, params: Sequence[Any],
                     values: Mapping[str, Any]) -> None:
        """Частичный апдейт. Пустой набор полей — не запрос, а no-op."""
        if not values:
            return
        assignments = ", ".join(f"{key}=?" for key in values)
        self.execute(
            f"UPDATE {self.table} SET {assignments} WHERE {where}",
            list(values.values()) + list(params),
        )

    def update_by_pk(self, pk_value: Any, values: Mapping[str, Any]) -> None:
        self.update_where(f"{self.pk}=?", [pk_value], values)

    def rows(self, where: str | None = None, params: Sequence[Any] = (),
             *, order_by: str | None = None, limit: int | None = None) -> list[dict]:
        sql = f"SELECT * FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.query(sql, params)

    def count(self, where: str | None = None, params: Sequence[Any] = ()) -> int:
        sql = f"SELECT COUNT(*) FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        return int(self.scalar(sql, params) or 0)

    def statistics(self, *, status_column: str | None = None) -> dict[str, int]:
        """``{статус: количество, 'total': N}`` — вход для панели статистики."""
        column = status_column or self.status_column
        stats: dict[str, int] = {}
        try:
            rows = self.query(
                f"SELECT {column} AS status, COUNT(*) AS n "
                f"FROM {self.table} GROUP BY {column}"
            )
        except sqlite3.OperationalError:
            # Таблицы ещё нет — модуль ни разу не запускался.
            return {"total": 0}
        for row in rows:
            stats[str(row["status"] or "unknown")] = int(row["n"])
        stats["total"] = sum(stats.values())
        return stats

    def distinct(self, column: str, where: str | None = None,
                 params: Sequence[Any] = ()) -> list[Any]:
        sql = f"SELECT DISTINCT {column} FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        return [row[column] for row in self.query(sql, params)]

    def __repr__(self) -> str:  # pragma: no cover — отладочное
        return f"SqliteStore(table={self.table!r}, db={self.db_path!s})"


__all__ = ["SqliteStore"]
