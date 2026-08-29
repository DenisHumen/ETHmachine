"""ETHmachine web dashboard — public entry points.

Stays import-light: heavy modules (aiohttp/jinja2) are imported lazily by
`startup()` after preflight passes, so a missing dependency cannot crash
`import web` itself.
"""
from __future__ import annotations

import socket
import sys
import time

from web.preflight import check as preflight_check, print_instructions

__all__ = ["startup", "stop", "is_running", "preflight_check"]


# ANSI codes — main.py инициализирует colorama, так что цвета работают и в
# Windows-консоли. Если colorama не подключён, последовательности всё равно
# не сломают текст (большинство современных терминалов их понимают).
_R = "\033[91m"   # bright red
_G = "\033[92m"   # bright green
_C = "\033[96m"   # bright cyan
_B = "\033[1m"    # bold
_DIM = "\033[2m"
_X = "\033[0m"


def _wait_for_port(host: str, port: int, timeout: float = 3.0) -> bool:
    """Wait until the TCP port accepts a connection. Returns True if it did."""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((probe_host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _build_url(host: str, port: int) -> str:
    """Pretty URL for the banner. 0.0.0.0 → 127.0.0.1 in printed link."""
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    return f"http://{display_host}:{port}/"


def _supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


def _emit(text: str) -> None:
    """Print text to stdout with flush; fall back to ASCII-safe write."""
    try:
        print(text, flush=True)
        return
    except UnicodeEncodeError:
        pass
    try:
        sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")
        sys.stdout.flush()
    except Exception:
        try:
            sys.stderr.write(text.encode("ascii", "replace").decode("ascii") + "\n")
        except Exception:
            pass


def _print_banner(host: str, port: int, *, ready: bool) -> None:
    url = _build_url(host, port)
    bind_info = f"{host}:{port}"
    exposed = host not in ("127.0.0.1", "localhost", "::1")

    try:
        # Общий UI-набор проекта: рамка и цвета те же, что во всех меню.
        # Импорт лёгкий — только stdlib внутри.
        from modules.ui import components, theme

        state = ("работает" if ready else "запускается…")
        lines = [
            f"{theme.FG_MUTED}состояние{theme.RESET}  "
            f"{(theme.FG_OK if ready else theme.FG_WARN)}{state}{theme.RESET}",
            f"{theme.FG_MUTED}адрес    {theme.RESET}  "
            f"{theme.FG_BRAND}{theme.BOLD}{url}{theme.RESET}",
            f"{theme.FG_MUTED}слушает  {theme.RESET}  {bind_info}",
            "",
            f"{theme.FG_MUTED}Первый вход открывает /register — там создаётся"
            f" учётная запись.{theme.RESET}",
            f"{theme.FG_MUTED}Выключить: WEB_ENABLED=False в"
            f" config/modules/general_config.py{theme.RESET}",
        ]
        if exposed:
            lines.insert(3, f"{theme.FG_ERR}Панель доступна не только с этого "
                            f"компьютера — в ней видны приватные ключи.{theme.RESET}")
        _emit("")
        _emit(components.panel("Веб-панель ETHmachine", lines,
                               color=theme.FG_ERR if exposed else theme.FG_ACCENT))
        _emit("")
    except Exception:
        # UI-набор недоступен — печатаем то же самое простым текстом.
        _emit("")
        _emit(f"  Веб-панель ETHmachine: {url}  (слушает {bind_info})")
        _emit("")

    # Дублируем короткую строку через loguru, чтобы баннер точно попал в
    # тот же поток, где пользователь видит остальные логи (и в WS-канал
    # дашборда заодно).
    try:
        from loguru import logger  # type: ignore
        logger.success(
            f"Веб-панель {'работает' if ready else 'запускается'} -> {url} "
            f"(слушает {bind_info})"
        )
    except Exception:
        pass


def _print_disabled() -> None:
    # Выключатель живёт в general_config.py; cfg_web.py его только реэкспортирует,
    # поэтому подсказка должна вести именно туда, где его правят.
    msg = ("\n[web] панель выключена (WEB_ENABLED=False в "
           "config/modules/general_config.py)\n\n")
    try:
        sys.stdout.write(f"{_DIM}{msg}{_X}")
    except UnicodeEncodeError:
        sys.stdout.write(msg)


def startup(*, autostart: bool = True, force: bool = False,
            announce: bool = True) -> bool:
    """Run preflight + (optionally) start the web server in a background thread.

    Returns True if the server was started (or already running), False otherwise.
    Never raises — on any failure prints a clear instruction block.

    When `announce` is True (the default) prints a banner with the URL and
    bind info as soon as the port accepts connections.
    """
    # Выключатель проверяем ПЕРВЫМ. Иначе пользователь с отключённой панелью
    # получал стену инструкций по установке aiohttp/jinja2 — зависимостей,
    # которые ему не нужны.
    try:
        from config.modules.cfg_web import WEB_ENABLED as _enabled
    except Exception:
        _enabled = False
    if not _enabled and not force:
        if announce:
            _print_disabled()
        return False

    if announce:
        _emit(f"{_DIM}[web] запуск панели...{_X}")
    result = preflight_check()
    if not result.ok:
        print_instructions(result)
        return False
    try:
        # Lazy: only import after preflight succeeds.
        from config.modules.cfg_web import (WEB_AUTOSTART_FROM_MAIN, WEB_ENABLED,
                                            WEB_HOST, WEB_PORT)
        from web.server import autostart_if_enabled, start_web_server_thread

        if force:
            ok = start_web_server_thread(force=True)
        elif autostart:
            ok = autostart_if_enabled()
        else:
            ok = start_web_server_thread()

        if not ok:
            if announce and not WEB_ENABLED:
                _print_disabled()
            return False

        if announce:
            ready = _wait_for_port(WEB_HOST, WEB_PORT, timeout=3.0)
            _print_banner(WEB_HOST, WEB_PORT, ready=ready)
        return True
    except Exception as exc:  # pragma: no cover — defensive
        sys.stderr.write(f"[web] startup failed: {exc!r}\n")
        try:
            from loguru import logger
            logger.error(f"WEB dashboard failed to start: {exc!r}")
        except Exception:
            pass
        return False


def stop(timeout: float = 5.0) -> None:
    """Stop the web server thread if it is running. Safe if never started."""
    try:
        from web.server import stop as _stop
    except Exception:
        return
    _stop(timeout=timeout)


def is_running() -> bool:
    try:
        from web.server import is_running as _is_running
    except Exception:
        return False
    return _is_running()
