"""Адаптер логгера Abstract Portal -> modules.simple_logger (loguru)."""
import threading
from colorama import Fore, Style
from modules.simple_logger import log_wallet_task, log_simple


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


def banner():
    with _print_lock:
        print(f"""
{Fore.GREEN}+==================================================+
|{Fore.WHITE}       ABSTRACT PORTAL STATS CHECKER               {Fore.GREEN}|
|{Fore.WHITE}        ETHmachine Integration                     {Fore.GREEN}|
+==================================================+{Style.RESET_ALL}
""")


def header(text: str):
    log(text, "header")


def stats_block(stats: dict):
    """Вывести блок статистики."""
    with _print_lock:
        print(f"\n{Fore.GREEN}{'=' * 50}{Style.RESET_ALL}")
        for key, val in stats.items():
            color = Fore.GREEN if any(w in key.lower() for w in ("success", "done", "ok")) else (
                Fore.RED if any(w in key.lower() for w in ("fail", "error")) else Fore.YELLOW
            )
            print(f"  {color}{key}: {val}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'=' * 50}{Style.RESET_ALL}")
