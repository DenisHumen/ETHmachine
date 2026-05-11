"""Loguru sink — заворачивает каждую запись в LogsBus.

Подключается ровно один раз через `attach_to_logger()`.
"""
from __future__ import annotations

import threading

from web.logs.bus import get_bus

_attached = False
_attach_lock = threading.Lock()
_handler_id: int | None = None


def _record_to_dict(record) -> dict:
    """Проецируем loguru record -> сериализуемый dict (для JSON)."""
    try:
        msg = record["message"]
    except Exception:
        msg = str(record)
    level = record["level"].name if hasattr(record.get("level"), "name") else str(record.get("level", ""))
    name = record.get("name") or ""
    function = record.get("function") or ""
    line = record.get("line") or 0
    thread = (record.get("thread") or {}).name if record.get("thread") else ""
    extra = record.get("extra") or {}
    return {
        "level": level,
        "msg": msg,
        "module": name,
        "function": function,
        "line": line,
        "thread": thread,
        "extra": {k: str(v) for k, v in extra.items()},
    }


def _sink(message) -> None:
    """Loguru вызывает sink с объектом Message; .record даёт dict."""
    try:
        record = message.record
    except Exception:
        return
    payload = _record_to_dict(record)
    get_bus().put_threadsafe(payload)


def attach_to_logger() -> None:
    """Idempotent. Безопасно вызывать несколько раз."""
    global _attached, _handler_id
    if _attached:
        return
    with _attach_lock:
        if _attached:
            return
        try:
            from loguru import logger
        except Exception:
            return
        _handler_id = logger.add(_sink, level="DEBUG", enqueue=False, backtrace=False, diagnose=False)
        _attached = True


def detach_from_logger() -> None:
    """Убирает sink (для тестов / shutdown)."""
    global _attached, _handler_id
    if not _attached:
        return
    try:
        from loguru import logger
        if _handler_id is not None:
            logger.remove(_handler_id)
    except Exception:
        pass
    _handler_id = None
    _attached = False
