import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Optional, Set

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

    wallet = extra.get("wallet") or ""

    # account_name показываем только если он задан и отличается от wallet
    account_name = (extra.get("account_name") or "").strip()
    if account_name and account_name.lower() not in {"null", "none", wallet.lower()}:
        # Если это полный адрес — пропускаем (wallet уже короткий).
        if not (account_name.startswith("0x") and len(account_name) == 42):
            parts.append(f"<white>{account_name}</white>")

    parts.append(badge)

    idx = extra.get("task_index")
    tot = extra.get("task_total")
    if idx is not None and tot is not None:
        parts.append(f"<white>[{idx}/{tot}]</white>")

    if wallet:
        parts.append(f"<blue>{wallet}</blue>")

    # Экранируем фигурные скобки в сообщении: loguru с colorize=True
    # пропускает результат через .format_map(record), и любые `{...}`
    # в тексте интерпретируются как плейсхолдеры (KeyError).
    # Также экранируем `<` — иначе фрагменты вида `<none>` / `<html>`
    # из ошибок RPC/HTTP воспринимаются Colorizer-ом как цветовые теги.
    msg_text = (
        str(record["message"])
        .replace("{", "{{").replace("}", "}}")
        .replace("<", "\\<")
    )
    parts.append(f"<{fg}>{msg_text}</{fg}>")
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
# Авто прогресс-бар (pip-style, в одну строку) для wallet-задач
# ───────────────────────────────────────────────────────────
# Активируется автоматически при первом вызове log_wallet_task /
# log_task с заполненными index/total. Показывает, сколько
# кошельков выполнено и сколько ещё в работе. Потокобезопасен.
# Если параллельно уже работает «внешний» tqdm-бар (например,
# в dune.base.checker или pharos_claim.claim_runner) — наш бар
# не создаётся, чтобы не дублировать вывод и не ломать чужой UI.
# ═══════════════════════════════════════════════════════════

_progress_lock = threading.RLock()
_progress_bar = None
_progress_total: Optional[int] = None
_progress_desc: str = "Wallets"
_progress_seen: Dict[int, str] = {}
_progress_done: Set[int] = set()
_progress_safe_handler_id: Optional[int] = None
_progress_auto_enabled: bool = True

# Терминальные статусы — после них кошелёк считается завершённым.
_TERMINAL_STATUSES = {"success", "error"}

_BAR_FORMAT = (
    "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} "
    "[{elapsed}<{remaining}, {rate_fmt}{postfix}]"
)


def set_auto_progress(enabled: bool) -> None:
    """Включить / выключить автоматический прогресс-бар.

    По умолчанию включён. Отключение немедленно закрывает активный бар.
    """
    global _progress_auto_enabled
    _progress_auto_enabled = bool(enabled)
    if not enabled:
        _close_progress_bar()


def set_progress_description(desc: str) -> None:
    """Поменять подпись активного авто-бара (или подпись по-умолчанию)."""
    global _progress_desc
    _progress_desc = str(desc) if desc else "Wallets"
    with _progress_lock:
        if _progress_bar is not None:
            try:
                _progress_bar.set_description_str(_progress_desc, refresh=False)
            except Exception:
                pass


def _has_external_tqdm() -> bool:
    """True, если кроме нашего бара есть другие активные tqdm-инстансы."""
    try:
        from tqdm import tqdm  # type: ignore
    except Exception:
        return False
    try:
        instances = list(getattr(tqdm, "_instances", []) or [])
    except Exception:
        return False
    for inst in instances:
        if inst is not _progress_bar:
            return True
    return False


def _safe_tqdm_write(msg: str) -> None:
    try:
        from tqdm import tqdm  # type: ignore
    except Exception:
        sys.stderr.write(msg)
        return
    try:
        tqdm.write(msg, end="")
    except UnicodeEncodeError as exc:
        enc = getattr(exc, "encoding", None) or "ascii"
        safe = msg.encode(enc, errors="replace").decode(enc, errors="replace")
        try:
            tqdm.write(safe, end="")
        except Exception:
            sys.stderr.write(safe)


def _install_safe_sink_locked() -> None:
    """Перевести stderr-sink loguru на tqdm.write, чтобы лог не рвал бар."""
    global _handler_id, _progress_safe_handler_id
    if _progress_safe_handler_id is not None:
        return
    try:
        logger.remove(_handler_id)
    except Exception:
        pass
    _progress_safe_handler_id = logger.add(
        _safe_tqdm_write,
        format=_format_record,
        level="DEBUG",
        colorize=True,
    )


def _restore_default_sink_locked() -> None:
    global _handler_id, _progress_safe_handler_id
    if _progress_safe_handler_id is None:
        return
    try:
        logger.remove(_progress_safe_handler_id)
    except Exception:
        pass
    _progress_safe_handler_id = None
    _handler_id = logger.add(
        sys.stderr,
        format=_format_record,
        level="DEBUG",
        colorize=True,
    )


def _ensure_progress_bar_locked(total: int):
    global _progress_bar, _progress_total, _progress_seen, _progress_done
    if not _progress_auto_enabled:
        return None
    if not isinstance(total, int) or total <= 0:
        return None

    if _progress_bar is not None and _progress_total == total:
        return _progress_bar

    if _progress_bar is not None and _progress_total != total:
        # Сменился набор задач — закрываем старый и стартуем новый.
        _close_progress_bar_locked()

    if _has_external_tqdm():
        return None

    try:
        from tqdm import tqdm  # type: ignore
    except Exception:
        return None

    _progress_total = total
    _progress_seen = {}
    _progress_done = set()
    try:
        _progress_bar = tqdm(
            total=total,
            desc=_progress_desc,
            unit="w",
            dynamic_ncols=True,
            leave=True,
            bar_format=_BAR_FORMAT,
            colour="cyan",
            file=sys.stderr,
            mininterval=0.1,
        )
        _progress_bar.set_postfix_str("done=0 in_work=0", refresh=False)
    except Exception:
        _progress_bar = None
        _progress_total = None
        return None

    _install_safe_sink_locked()
    return _progress_bar


def _close_progress_bar_locked() -> None:
    global _progress_bar, _progress_total, _progress_seen, _progress_done
    if _progress_bar is not None:
        try:
            _progress_bar.close()
        except Exception:
            pass
    _progress_bar = None
    _progress_total = None
    _progress_seen = {}
    _progress_done = set()
    _restore_default_sink_locked()


def _close_progress_bar() -> None:
    with _progress_lock:
        _close_progress_bar_locked()


def reset_progress() -> None:
    """Принудительно закрыть активный авто-бар (например, между запусками)."""
    _close_progress_bar()


def _update_progress(index: Optional[int], total: Optional[int], status: str) -> None:
    if index is None or total is None:
        return
    if not _progress_auto_enabled:
        return
    with _progress_lock:
        bar = _ensure_progress_bar_locked(total)
        if bar is None:
            return

        _progress_seen[index] = status
        if status in _TERMINAL_STATUSES and index not in _progress_done:
            _progress_done.add(index)
            try:
                bar.update(1)
            except Exception:
                pass

        in_work = sum(1 for i in _progress_seen if i not in _progress_done)
        try:
            bar.set_postfix_str(
                f"done={len(_progress_done)} in_work={in_work}",
                refresh=False,
            )
            bar.refresh()
        except Exception:
            pass

        if len(_progress_done) >= total:
            _close_progress_bar_locked()


# ═══════════════════════════════════════════════════════════
# tqdm-safe контекст: временно направляет stderr-sink через tqdm.write,
# чтобы progress-bar не рвался при печати логов.
# Сохранено для обратной совместимости с модулями (dune, pharos_claim),
# которые управляют собственным tqdm-баром.
# ═══════════════════════════════════════════════════════════


@contextmanager
def tqdm_safe_logging():
    global _handler_id
    try:
        from tqdm import tqdm  # type: ignore  # noqa: F401
    except Exception:
        yield
        return

    # Если уже стоит наш «безопасный» sink (активен авто-бар) —
    # ничего перехватывать не нужно.
    with _progress_lock:
        already_safe = _progress_safe_handler_id is not None

    if already_safe:
        yield
        return

    try:
        logger.remove(_handler_id)
    except Exception:
        pass
    tmp_id = logger.add(
        _safe_tqdm_write,
        format=_format_record,
        level="DEBUG",
        colorize=True,
    )
    try:
        yield
    finally:
        try:
            logger.remove(tmp_id)
        except Exception:
            pass
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
    # Авто прогресс-бар по wallet-задачам.
    _update_progress(index, total, status)


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


# Уже подключённые файловые sink-и: абсолютный путь -> id sink-а loguru.
_file_sinks: Dict[str, int] = {}
_file_sinks_lock = threading.Lock()


def setup_file_logging(log_file: str) -> int:
    """Подключает файловый sink loguru для указанного пути и возвращает его id.

    Функция вызывается из меню-обёрток модулей, а главное меню крутится в
    бесконечном цикле — один и тот же модуль можно запустить много раз за
    сессию. Без дедупликации каждый запуск добавлял ещё один sink на тот же
    файл: строки лога дублировались N раз, а N файловых дескрипторов висели
    открытыми до конца процесса. Поэтому запоминаем sink по абсолютному пути и
    на повторный вызов отдаём уже существующий id.
    """
    key = str(Path(log_file).resolve())

    with _file_sinks_lock:
        existing = _file_sinks.get(key)
        if existing is not None:
            return existing

        sink_id = logger.add(
            log_file,
            format=LOG_FORMAT_FILE,
            level="DEBUG",
            rotation="10 MB"
        )
        _file_sinks[key] = sink_id
        return sink_id


__all__ = [
    'logger',
    'log_wallet_task',
    'log_task',
    'log_simple',
    'setup_file_logging',
    'tqdm_safe_logging',
    'set_auto_progress',
    'set_progress_description',
    'reset_progress',
]
