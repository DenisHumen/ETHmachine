"""Параллельный обход аккаунтов.

Один и тот же блок с ``ThreadPoolExecutor`` был скопирован в два десятка
модулей — вместе с одинаковыми ошибками: где-то Ctrl+C не отменял
оставшиеся задачи, где-то счётчики менялись без блокировки, где-то
последовательный путь при одном аккаунте отсутствовал и на один кошелёк
поднимался пул из 25 потоков.

Правила (см. AGENTS.md §4):
  • индекс ``[i/N]`` — позиция в data.csv, а не порядок завершения;
  • при ``threads <= 1`` или одном элементе пул не создаётся;
  • KeyboardInterrupt отменяет невзятые задачи и пробрасывается наверх;
  • счётчики защищены общей блокировкой.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")


@dataclass
class Counters:
    """Потокобезопасные счётчики результатов."""

    _values: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._values[name] = self._values.get(name, 0) + amount

    def get(self, name: str) -> int:
        with self._lock:
            return self._values.get(name, 0)

    def as_dict(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)

    @property
    def lock(self) -> threading.Lock:
        """Общая блокировка — для составных операций (лог + счётчик)."""
        return self._lock

    def __bool__(self) -> bool:
        with self._lock:
            return any(self._values.values())


def resolve_threads(requested: int | None = None, total: int = 0) -> int:
    """Сколько потоков реально поднимать.

    Больше потоков, чем элементов, не нужно; ``None`` означает «взять из
    общего конфига».
    """
    if requested is None:
        try:
            from config.modules.general_config import NUM_THREADS

            requested = int(NUM_THREADS)
        except Exception:
            requested = 1
    threads = max(1, int(requested))
    if total:
        threads = min(threads, total)
    return threads


def run_parallel(
    items: Sequence[T],
    worker: Callable[[int, T], Any],
    *,
    threads: int | None = None,
    thread_name_prefix: str = "worker",
    start_index: int = 1,
) -> list[Any]:
    """Выполняет ``worker(index, item)`` для каждого элемента.

    ``index`` — позиция элемента в исходном списке (с ``start_index``),
    а не порядок завершения: пользователь сопоставляет строки лога
    со строками data.csv.

    Исключения внутри worker не гасятся — модуль сам решает, что считать
    ошибкой задачи, а что фатальным сбоем. Возвращает результаты в порядке
    исходного списка (``None`` там, где worker упал).
    """
    total = len(items)
    if total == 0:
        return []

    workers = resolve_threads(threads, total)
    results: list[Any] = [None] * total

    if workers <= 1 or total == 1:
        for offset, item in enumerate(items):
            results[offset] = worker(offset + start_index, item)
        return results

    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix=thread_name_prefix) as pool:
        futures = {
            pool.submit(worker, offset + start_index, item): offset
            for offset, item in enumerate(items)
        }
        try:
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        except KeyboardInterrupt:
            # Отменяем то, что ещё не взято в работу, и пробрасываем наверх:
            # состояние уже начатых задач модуль сохраняет сам.
            for future in futures:
                future.cancel()
            raise
    return results


def run_with_counters(
    items: Sequence[T],
    worker: Callable[[int, T, Counters], Any],
    *,
    threads: int | None = None,
    thread_name_prefix: str = "worker",
) -> Counters:
    """``run_parallel`` со счётчиками, которые worker обновляет сам."""
    counters = Counters()

    def _call(index: int, item: T) -> Any:
        return worker(index, item, counters)

    run_parallel(items, _call, threads=threads,
                 thread_name_prefix=thread_name_prefix)
    return counters


def chunked(items: Iterable[T], size: int) -> Iterable[list[T]]:
    """Разбивает последовательность на пачки — для батчевых API."""
    if size <= 0:
        raise ValueError("размер пачки должен быть положительным")
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


__all__ = [
    "Counters", "resolve_threads", "run_parallel", "run_with_counters",
    "chunked",
]
