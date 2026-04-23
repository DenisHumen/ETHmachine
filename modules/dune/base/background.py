"""Фоновый запуск Dune Base чекера.

Позволяет стартовать `run_base_checker` в daemon-потоке и сразу вернуться
в меню. Повторный запуск не допускается — пока один поток жив, второй
стартовать нельзя. Останов выполняется кооперативно через `_stop_event`
из `modules.dune.base.checker`.
"""

from __future__ import annotations

from datetime import datetime
from threading import Lock, Thread
from typing import Optional

from modules.dune.base import checker as _checker
from modules.simple_logger import logger

_thread: Optional[Thread] = None
_lock = Lock()
_started_at: Optional[datetime] = None


def _runner() -> None:
    try:
        _checker.run_base_checker()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[BG] Фоновый Dune Base checker завершился с ошибкой: {exc}")
    else:
        logger.success("[BG] Фоновый Dune Base checker завершён")


def start_background() -> bool:
    """Запустить чекер в фоновом потоке. Возвращает True, если поток стартовал."""
    global _thread, _started_at
    with _lock:
        if _thread is not None and _thread.is_alive():
            logger.warning("[BG] Фоновый запуск уже активен — повторный старт отклонён")
            return False
        _checker._stop_event.clear()
        _thread = Thread(target=_runner, name="dune-base-bg", daemon=True)
        _started_at = datetime.now()
        _thread.start()
        logger.info("[BG] Фоновый Dune Base checker запущен")
        return True


def is_running() -> bool:
    with _lock:
        return _thread is not None and _thread.is_alive()


def request_stop() -> bool:
    """Попросить фоновый поток остановиться (кооперативно)."""
    with _lock:
        if _thread is None or not _thread.is_alive():
            logger.info("[BG] Фоновый поток не активен — останавливать нечего")
            return False
        _checker._stop_event.set()
        logger.warning("[BG] Запрошен останов фонового Dune Base checker…")
        return True


def get_status() -> dict:
    running = is_running()
    return {
        "running": running,
        "started_at": _started_at.isoformat(sep=" ", timespec="seconds") if _started_at else None,
        "stop_requested": _checker._stop_event.is_set(),
    }
