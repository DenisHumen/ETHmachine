import sys
from loguru import logger

logger.remove()

logger.level("INFO", color="<white>")
logger.level("SUCCESS", color="<green>")
logger.level("WARNING", color="<yellow>")
logger.level("ERROR", color="<red>")
logger.level("DEBUG", color="<cyan>")

# ═══════════════════════════════════════════════════
# Статус-метки с рамкой ║ STATUS ║
# ═══════════════════════════════════════════════════

_STATUS_MAP = {
    "INFO":    "START",
    "SUCCESS": " OK  ",
    "WARNING": "WARN ",
    "ERROR":   "FAIL ",
    "DEBUG":   "DEBUG",
}


def _format_record(record):
    level_name = record["level"].name
    status = _STATUS_MAP.get(level_name, level_name[:5].ljust(5))
    time_str = record["time"].strftime("%H:%M:%S")
    msg = record["message"]

    return (
        f"<level>{time_str} ║ {status} ║ {msg}</level>\n"
    )


LOG_FORMAT_FILE = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} - {message}"
)

_handler_id = logger.add(
    sys.stderr,
    format=_format_record,
    level="DEBUG",
    colorize=True
)


def _log_by_status(message: str, status: str):
    match status:
        case "success":
            logger.success(message)
        case "error":
            logger.error(message)
        case "warning":
            logger.warning(message)
        case "debug":
            logger.debug(message)
        case _:
            logger.info(message)


def log_wallet_task(wallet: str, index: int, total: int, message: str, status: str = "info"):
    idx = str(index).zfill(3)
    full_msg = f"[{idx}] {wallet} │ {message}"
    _log_by_status(full_msg, status)


def log_task(index: int, total: int, message: str, status: str = "info"):
    idx = str(index).zfill(3)
    full_msg = f"[{idx}] {message}"
    _log_by_status(full_msg, status)


def log_simple(message: str, status: str = "info"):
    _log_by_status(message, status)


def setup_file_logging(log_file: str):
    logger.add(
        log_file,
        format=LOG_FORMAT_FILE,
        level="DEBUG",
        rotation="10 MB"
    )


__all__ = ['logger', 'log_wallet_task', 'log_task', 'log_simple', 'setup_file_logging']
