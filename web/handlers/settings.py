"""Settings page: users + audit."""
from __future__ import annotations

from aiohttp import web

from web.storage import database as db
from web.core.templating import render


async def settings_get(request: web.Request) -> web.Response:
    return render(request, "settings.html",
                  users=[dict(u) for u in db.list_users()],
                  audit=[dict(a) for a in db.recent_audit(100)])
