"""Общие механизмы: параллельный раннер и слой над SQLite."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from modules.core import runner
from modules.core.sqlite_store import SqliteStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_tasks (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet   TEXT NOT NULL,
    status   TEXT NOT NULL DEFAULT 'pending',
    note     TEXT
);
CREATE INDEX IF NOT EXISTS idx_demo_status ON demo_tasks(status);
"""


@pytest.fixture()
def store(tmp_path):
    s = SqliteStore(tmp_path / "demo.db", SCHEMA, table="demo_tasks")
    s.init()
    return s


# ── runner ───────────────────────────────────────────────────────────────

def test_run_parallel_preserves_order():
    items = list(range(20))
    result = runner.run_parallel(items, lambda idx, item: (idx, item * 2), threads=4)
    assert result == [(i + 1, i * 2) for i in items]


def test_run_parallel_index_is_position_not_completion_order():
    seen: list[tuple[int, str]] = []
    lock = threading.Lock()

    def work(index, item):
        with lock:
            seen.append((index, item))
        return index

    runner.run_parallel(["a", "b", "c"], work, threads=3)
    assert sorted(seen) == [(1, "a"), (2, "b"), (3, "c")]


def test_run_parallel_empty_input():
    assert runner.run_parallel([], lambda i, x: x) == []


def test_run_parallel_single_item_runs_sequentially():
    """На одном элементе пул потоков поднимать незачем."""
    thread_names: list[str] = []
    runner.run_parallel(
        ["only"], lambda i, x: thread_names.append(threading.current_thread().name),
        threads=25,
    )
    assert thread_names == ["MainThread"]


def test_run_parallel_propagates_worker_exception():
    def boom(index, item):
        if item == 2:
            raise ValueError("сломалось")
        return item

    with pytest.raises(ValueError):
        runner.run_parallel([1, 2, 3], boom, threads=3)


@pytest.mark.parametrize(
    ("requested", "total", "expected"),
    [(4, 10, 4), (25, 3, 3), (1, 100, 1), (0, 10, 1), (-5, 10, 1)],
)
def test_resolve_threads(requested, total, expected):
    assert runner.resolve_threads(requested, total) == expected


def test_counters_are_thread_safe():
    counters = runner.Counters()

    def work(index, item, c):
        c.bump("done")

    result = runner.run_with_counters(list(range(200)), work, threads=8)
    assert result.get("done") == 200
    assert result.as_dict() == {"done": 200}


def test_chunked_splits_evenly():
    assert list(runner.chunked(range(7), 3)) == [[0, 1, 2], [3, 4, 5], [6]]
    assert list(runner.chunked([], 3)) == []
    with pytest.raises(ValueError):
        list(runner.chunked([1], 0))


# ── SqliteStore ──────────────────────────────────────────────────────────

def test_init_is_idempotent(store):
    store.init()
    store.init()
    assert store.count() == 0


def test_insert_and_read_back(store):
    row_id = store.insert({"wallet": "0xabc", "status": "pending"})
    assert row_id > 0
    rows = store.rows()
    assert len(rows) == 1
    assert rows[0]["wallet"] == "0xabc"


def test_update_by_pk_partial(store):
    row_id = store.insert({"wallet": "0xabc", "status": "pending"})
    store.update_by_pk(row_id, {"status": "arrived"})
    row = store.rows()[0]
    assert row["status"] == "arrived"
    assert row["wallet"] == "0xabc", "частичный апдейт затронул чужие колонки"


def test_update_with_no_fields_is_noop(store):
    row_id = store.insert({"wallet": "0xabc", "status": "pending"})
    store.update_by_pk(row_id, {})
    assert store.rows()[0]["status"] == "pending"


def test_statistics_groups_by_status(store):
    for status in ("pending", "pending", "arrived", "failed"):
        store.insert({"wallet": "0x1", "status": status})
    stats = store.statistics()
    assert stats == {"pending": 2, "arrived": 1, "failed": 1, "total": 4}


def test_statistics_on_missing_table_does_not_raise(tmp_path):
    empty = SqliteStore(tmp_path / "none.db", SCHEMA, table="not_created_yet")
    assert empty.statistics() == {"total": 0}


def test_reset_only_drops_own_table(tmp_path):
    """Соседние таблицы в общей базе должны пережить очистку модуля."""
    path = tmp_path / "shared.db"
    mine = SqliteStore(path, SCHEMA, table="demo_tasks")
    mine.init()
    mine.insert({"wallet": "0x1", "status": "pending"})

    with mine.connection() as conn:
        conn.execute("CREATE TABLE neighbour (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO neighbour (v) VALUES ('важное')")

    mine.reset()

    assert mine.count() == 0
    with mine.connection() as conn:
        left = conn.execute("SELECT v FROM neighbour").fetchall()
    assert [dict(r)["v"] for r in left] == ["важное"]


def test_wal_mode_is_enabled(store):
    with store.connection() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"


def test_connection_rolls_back_on_error(store):
    store.insert({"wallet": "0x1", "status": "pending"})
    with pytest.raises(sqlite3.IntegrityError):
        with store.connection() as conn:
            conn.execute("INSERT INTO demo_tasks (wallet, status) VALUES ('0x2','x')")
            conn.execute("INSERT INTO demo_tasks (wallet, status) VALUES (NULL, 'y')")
    assert store.count() == 1, "неудачная транзакция оставила частичные данные"


def test_parallel_writes_do_not_lose_rows(store):
    """WAL плюс соединение на операцию должны выдержать запись из потоков."""
    def work(index, item):
        store.insert({"wallet": f"0x{item:04x}", "status": "pending"})

    runner.run_parallel(list(range(100)), work, threads=8)
    assert store.count() == 100
