"""Адаптер логгера Pharos → modules.simple_logger (loguru)."""
import threading
from colorama import Fore, Style
from modules.simple_logger import logger as _loguru


_print_lock = threading.Lock()


def log(msg: str, level: str = "info", addr: str = ""):
    """Thread-safe лог в стиле pharos → loguru."""
    prefix = f"{addr} │ " if addr else ""
    full_msg = f"{prefix}{msg}"

    match level:
        case "success":
            _loguru.success(full_msg)
        case "error":
            _loguru.error(full_msg)
        case "warning":
            _loguru.warning(full_msg)
        case "cycle" | "header":
            _loguru.info(full_msg)
        case _:
            _loguru.info(full_msg)


def banner():
    with _print_lock:
        print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════╗
║{Fore.WHITE}       PHAROS TESTNET FAUCET & QUEST BOT          {Fore.CYAN}║
║{Fore.WHITE}        ETHmachine Integration                    {Fore.CYAN}║
╚══════════════════════════════════════════════════╝{Style.RESET_ALL}
""")


def header(text: str):
    log(text, "header")


def separator(index: int = 0, total: int = 0):
    with _print_lock:
        if total:
            print(f"\n{Fore.CYAN}{'─' * 40} [{index}/{total}] {'─' * 4}{Style.RESET_ALL}")
        else:
            print(f"{Fore.CYAN}{'─' * 50}{Style.RESET_ALL}")


def stats_block(stats: dict):
    """Вывести блок статистики."""
    with _print_lock:
        print(f"\n{Fore.CYAN}{'=' * 50}{Style.RESET_ALL}")
        for key, val in stats.items():
            color = Fore.GREEN if any(w in key.lower() for w in ("success", "done", "claimed", "успешно", "выполнено")) else (
                Fore.RED if any(w in key.lower() for w in ("fail", "неудач")) else Fore.YELLOW
            )
            print(f"  {color}{key}: {val}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 50}{Style.RESET_ALL}")
