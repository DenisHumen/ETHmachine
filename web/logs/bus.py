"""LogsBus — in-memory ring buffer + WebSocket subscribers."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from typing import Any, Optional


class LogsBus:
    """Thread-safe pub/sub: producers (любой поток) кладут записи через
    `put_threadsafe`; потребители (asyncio coroutines) подписываются через
    `subscribe()` -> `asyncio.Queue` и читают по мере появления.
    Ring buffer хранит последние N записей для новых подписчиков.
    """

    def __init__(self, ring_size: int = 2000):
        self._ring: deque[dict[str, Any]] = deque(maxlen=ring_size)
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: set[asyncio.Queue] = set()
        self._next_id = 1

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ------- producer side (sync, любой поток) -------

    def put_threadsafe(self, record: dict[str, Any]) -> None:
        with self._lock:
            record_id = self._next_id
            self._next_id += 1
            record = {**record, "id": record_id, "ts": record.get("ts") or time.time()}
            self._ring.append(record)
            subs = list(self._subscribers)
            loop = self._loop

        if loop is None or not subs:
            return
        for q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, record)
            except RuntimeError:
                # loop закрыт
                pass

    # ------- consumer side (asyncio) -------

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._ring)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)


_bus: Optional[LogsBus] = None
_bus_lock = threading.Lock()


def get_bus() -> LogsBus:
    """Lazy singleton. Размер берём из cfg_web."""
    global _bus
    if _bus is not None:
        return _bus
    with _bus_lock:
        if _bus is None:
            try:
                from config.modules.cfg_web import WEB_LOG_RING_SIZE
            except Exception:
                WEB_LOG_RING_SIZE = 2000
            _bus = LogsBus(ring_size=WEB_LOG_RING_SIZE)
    return _bus
