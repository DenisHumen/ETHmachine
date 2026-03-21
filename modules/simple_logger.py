import sys
from typing import Optional

from loguru import logger

# ═══════════════════════════════════════════════════════════
# Loguru setup
# ═══════════════════════════════════════════════════════════

logger.remove()

logger.level("INFO",    color="<white>")
logger.level("SUCCESS", color="<green>")
logger.level("WARNING", color="<yellow>")
logger.level("ERROR",   color="<red>")
logger.level("DEBUG",   color="<cyan>")

# ═══════════════════════════════════════════════════════════
# Таблица маппинга уровней -> метка, loguru-цвет, ANSI-фон
# ═══════════════════════════════════════════════════════════

_LEVELS = {
    #              label    loguru-fg   ANSI background
    "INFO":    ("START", "cyan",    "\033[46m"),
    "SUCCESS": ("  OK ", "green",   "\033[42m"),
    "WARNING": (" WARN", "yellow",  "\033[43m"),
    "ERROR":   (" FAIL", "red",     "\033[41m"),
    "DEBUG":   ("DEBUG", "magenta", "\033[45m"),
}

_RST = "\033[0m"
_WB  = "\033[97;1m"  # bright-white + bold

_STATUS_DISPATCH = {
    "success": "success",
    "error":   "error",
    "warning": "warning",
    "debug":   "debug",
}

# ═══════════════════════════════════════════════════════════
# Форматирование
# ═══════════════════════════════════════════════════════════

def _format_record(record) -> str:
    """
    Формат строки лога:
      HH:MM:SS │ account_name │ ██ LABEL ██ │ [i/N] │ wallet │ message
    Бейдж — сплошной цветной прямоугольник (ANSI bg) с белым
    жирным текстом внутри.  [i/N] — белый, wallet — синий,
    сообщение — цвет уровня.
    """
    lvl = record["level"].name
    label, fg, bg = _LEVELS.get(lvl, ("?????", "white", "\033[47m"))

    ts    = record["time"].strftime("%H:%M:%S")
    badge = f"{bg}{_WB} {label} {_RST}"
    extra = record["extra"]

    parts: list[str] = [f"<white>{ts}</white>"]

    account_name = extra.get("account_name") or "null"
    parts.append(f"<white>{account_name}</white>")

    parts.append(badge)

    idx = extra.get("task_index")
    tot = extra.get("task_total")
    if idx is not None and tot is not None:
        parts.append(f"<white>[{idx}/{tot}]</white>")

    wallet = extra.get("wallet")
    if wallet:
        parts.append(f"<blue>{wallet}</blue>")

    parts.append(f"<{fg}>{record['message']}</{fg}>")
    return " │ ".join(parts) + "\n"


LOG_FORMAT_FILE = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} - {message}"
)

_handler_id = logger.add(
    sys.stderr,
    format=_format_record,
    level="DEBUG",
    colorize=True,
)

# ═══════════════════════════════════════════════════════════
# Публичный API
# ═══════════════════════════════════════════════════════════

def _emit(
    message: str,
    status: str,
    index: Optional[int] = None,
    total: Optional[int] = None,
    wallet: Optional[str] = None,
    account_name: Optional[str] = None,
) -> None:
    """Единая точка отправки лога с контекстом."""
    bound = logger.bind(task_index=index, task_total=total, wallet=wallet, account_name=account_name)
    method = _STATUS_DISPATCH.get(status, "info")
    getattr(bound, method)(message)


def log_wallet_task(
    wallet: str, index: int, total: int, message: str, status: str = "info",
    account_name: Optional[str] = None,
) -> None:
    _emit(message, status, index=index, total=total, wallet=wallet, account_name=account_name)


def log_task(index: int, total: int, message: str, status: str = "info",
             account_name: Optional[str] = None) -> None:
    _emit(message, status, index=index, total=total, account_name=account_name)


def log_simple(message: str, status: str = "info", account_name: Optional[str] = None) -> None:
    _emit(message, status, account_name=account_name)


def setup_file_logging(log_file: str):
    logger.add(
        log_file,
        format=LOG_FORMAT_FILE,
        level="DEBUG",
        rotation="10 MB"
    )


__all__ = ['logger', 'log_wallet_task', 'log_task', 'log_simple', 'setup_file_logging']
