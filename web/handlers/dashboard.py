"""Dashboard + WS logs."""
from __future__ import annotations

import asyncio
import json

from aiohttp import WSMsgType, web

from web.storage import database as db
from web.logs.bus import get_bus
from web.core.templating import render


async def dashboard(request: web.Request) -> web.Response:
    return render(request, "dashboard.html",
                  active_runs=[dict(r) for r in db.runs_active()])


async def ws_logs(request: web.Request) -> web.WebSocketResponse:
    if request.get("user") is None:
        return web.Response(status=401, text="auth required")
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=2 * 1024 * 1024)
    await ws.prepare(request)

    bus = get_bus()
    bus.attach_loop(asyncio.get_running_loop())
    q = bus.subscribe()

    try:
        await ws.send_json({"type": "snapshot", "records": bus.snapshot()})

        async def reader():
            async for msg in ws:
                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                    break

        reader_task = asyncio.create_task(reader())
        try:
            while not ws.closed:
                try:
                    rec = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    if ws.closed:
                        break
                    continue
                try:
                    await ws.send_json({"type": "log", "record": rec})
                except (ConnectionResetError, RuntimeError):
                    break
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        bus.unsubscribe(q)
        if not ws.closed:
            await ws.close()
    return ws


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})
