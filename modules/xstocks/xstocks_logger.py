"""Адаптер логгера xStocks -> modules.simple_logger (loguru)."""
import threading

from modules.simple_logger import log_simple, log_wallet_task
from modules.ui import ui


_print_lock = threading.Lock()


def _escape_loguru(text: str) -> str:
    """Escape special chars so loguru doesn't crash on HTML tags or JSON braces."""
    return text.replace("{", "{{").replace("}", "}}").replace("<", r"\<").replace(">", r"\>")


_LEVEL_MAP = {
    "success": "success",
    "error": "error",
    "warning": "warning",
    "cycle": "info",
    "header": "info",
    "info": "info",
}


def log(msg: str, level: str = "info", addr: str = "",
        index: int = None, total: int = None, account_name: str = None):
    """Thread-safe лог через simple_logger с контекстом кошелька."""
    safe_msg = _escape_loguru(str(msg))
    status = _LEVEL_MAP.get(level, "info")

    if addr and index is not None and total is not None:
        log_wallet_task(
            wallet=addr,
            index=index,
            total=total,
            message=safe_msg,
            status=status,
            account_name=account_name,
        )
    else:
        log_simple(safe_msg, status=status, account_name=account_name)


def stats_block(stats: dict, title: str = "Итог прогона"):
    """Итоговая сводка режима — одна рамка на все режимы модуля."""
    with _print_lock:
        ui.print_lines(ui.panel(title, ui.key_values(stats)))
