import sys
from loguru import logger

logger.remove()

logger.level("INFO", color="<white>")
logger.level("SUCCESS", color="<green>")
logger.level("WARNING", color="<yellow>")
logger.level("ERROR", color="<red>")
logger.level("DEBUG", color="<cyan>")

LOG_FORMAT = (
    "<level>{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} - {message}</level>"
)

LOG_FORMAT_FILE = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} - {message}"
)

_handler_id = logger.add(
    sys.stderr,
    format=LOG_FORMAT,
    level="DEBUG",
    colorize=True
)


def log_wallet_task(wallet: str, index: int, total: int, message: str, status: str = "info"):
    full_msg = f"[{wallet}] [{index}/{total}] | {message}"
    
    if status == "success":
        logger.success(full_msg)
    elif status == "error":
        logger.error(full_msg)
    elif status == "warning":
        logger.warning(full_msg)
    else:
        logger.info(full_msg)


def log_task(index: int, total: int, message: str, status: str = "info"):
    full_msg = f"[{index}/{total}] | {message}"
    
    if status == "success":
        logger.success(full_msg)
    elif status == "error":
        logger.error(full_msg)
    elif status == "warning":
        logger.warning(full_msg)
    else:
        logger.info(full_msg)


def log_simple(message: str, status: str = "info"):
    if status == "success":
        logger.success(message)
    elif status == "error":
        logger.error(message)
    elif status == "warning":
        logger.warning(message)
    elif status == "debug":
        logger.debug(message)
    else:
        logger.info(message)


def setup_file_logging(log_file: str):
    logger.add(
        log_file,
        format=LOG_FORMAT_FILE,
        level="DEBUG",
        rotation="10 MB"
    )


__all__ = ['logger', 'log_wallet_task', 'log_task', 'log_simple', 'setup_file_logging']
