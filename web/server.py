"""aiohttp server factory + threaded launcher."""
from __future__ import annotations

import asyncio
import threading
from typing import Optional

from aiohttp import web

from config.modules.cfg_web import (
    WEB_AUTOSTART_FROM_MAIN,
    WEB_ENABLED,
    WEB_HOST,
    WEB_PORT,
)
from web.core import auth
from web.storage import database as db
from web.logs import sink as log_sink
from web.handlers import (
    auth as auth_h,
    configs as configs_h,
    dashboard as dashboard_h,
    databases as databases_h,
    files as files_h,
    settings as settings_h,
)
from web.logs.bus import get_bus
from web.core.paths import STATIC_DIR


_state: dict = {
    "thread": None,
    "loop": None,
    "runner": None,
    "site": None,
    "stop_event": None,
}
_state_lock = threading.Lock()


def make_app() -> web.Application:
    db.init_database()
    app = web.Application(middlewares=[auth.session_middleware],
                          client_max_size=2 * 1024 * 1024)

    # Public
    app.router.add_get("/", lambda r: web.HTTPFound(
        "/dashboard" if r.get("user") else (
            "/register" if db.count_users() == 0 else "/login")))
    app.router.add_get("/api/health", dashboard_h.health)

    # Auth
    app.router.add_get("/login", auth_h.login_get)
    app.router.add_post("/login", auth_h.login_post)
    app.router.add_get("/register", auth_h.register_get)
    app.router.add_post("/register", auth_h.register_post)
    app.router.add_post("/logout", auth_h.logout_post)

    # Dashboard + WS
    app.router.add_get("/dashboard", dashboard_h.dashboard)
    app.router.add_get("/api/ws/logs", dashboard_h.ws_logs)

    # Databases
    app.router.add_get("/databases", databases_h.databases_index)
    app.router.add_get("/databases/{db}", databases_h.database_view)
    app.router.add_get("/databases/{db}/{table}", databases_h.table_view)

    # Files
    app.router.add_get("/files", files_h.files_index)
    app.router.add_get("/files/download", files_h.files_download)

    # Configs
    app.router.add_get("/configs", configs_h.configs_index)
    app.router.add_get("/configs/edit", configs_h.configs_edit)
    app.router.add_post("/configs/save", configs_h.configs_save)

    # Settings
    app.router.add_get("/settings", settings_h.settings_get)

    # Static
    app.router.add_static("/static/", path=str(STATIC_DIR), name="static",
                          show_index=False, follow_symlinks=False)

    async def _on_startup(app: web.Application):
        loop = asyncio.get_running_loop()
        get_bus().attach_loop(loop)
        log_sink.attach_to_logger()

    app.on_startup.append(_on_startup)
    return app


async def _serve(host: str, port: int, stop_event: asyncio.Event) -> None:
    app = make_app()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port, reuse_address=True)
    await site.start()
    with _state_lock:
        _state["runner"] = runner
        _state["site"] = site
    try:
        await stop_event.wait()
    finally:
        try:
            await runner.cleanup()
        except Exception:
            pass


def _thread_main(host: str, port: int) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop_event = asyncio.Event()
    with _state_lock:
        _state["loop"] = loop
        _state["stop_event"] = stop_event
    try:
        loop.run_until_complete(_serve(host, port, stop_event))
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        with _state_lock:
            _state["loop"] = None
            _state["runner"] = None
            _state["site"] = None
            _state["stop_event"] = None


def is_running() -> bool:
    with _state_lock:
        t = _state["thread"]
        return bool(t and t.is_alive())


def start_web_server_thread(host: Optional[str] = None,
                             port: Optional[int] = None,
                             *, force: bool = False) -> bool:
    """Start web server in background thread. Idempotent.

    Returns True if a server was started (or already running), False if
    WEB_ENABLED is False.
    """
    if not force and not WEB_ENABLED:
        return False
    if is_running():
        return True
    h = host or WEB_HOST
    p = int(port or WEB_PORT)
    t = threading.Thread(target=_thread_main, args=(h, p),
                         name="ETHmachine-Web", daemon=True)
    with _state_lock:
        _state["thread"] = t
    t.start()
    return True


def stop(timeout: float = 5.0) -> None:
    with _state_lock:
        loop = _state["loop"]
        ev = _state["stop_event"]
        t = _state["thread"]
    if loop and ev:
        loop.call_soon_threadsafe(ev.set)
    if t:
        t.join(timeout=timeout)
    with _state_lock:
        _state["thread"] = None


def autostart_if_enabled() -> bool:
    if WEB_ENABLED and WEB_AUTOSTART_FROM_MAIN:
        return start_web_server_thread()
    return False
