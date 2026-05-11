"""Jinja2 templating helper."""
from __future__ import annotations

import html as _html
import json
from typing import Any

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape

from web.core.paths import TEMPLATES_DIR


_env: Environment | None = None


def env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        _env.filters["tojson_safe"] = lambda v: json.dumps(v, ensure_ascii=False)
        _env.filters["humansize"] = _human_size
    return _env


def _human_size(n: int) -> str:
    n = int(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def render(request: web.Request, template: str, **ctx) -> web.Response:
    user = request.get("user")
    sid = request.get("session_id") or ""
    csrf = ""
    if sid:
        from web.core.auth import csrf_token
        csrf = csrf_token(sid)
    rendered = env().get_template(template).render(
        user=user,
        csrf_token=csrf,
        path=request.path,
        **ctx,
    )
    return web.Response(text=rendered, content_type="text/html",
                        headers={
                            "Content-Security-Policy":
                                "default-src 'self'; "
                                "script-src 'self'; "
                                "style-src 'self' 'unsafe-inline'; "
                                "connect-src 'self' ws: wss:; "
                                "img-src 'self' data:; "
                                "frame-ancestors 'none'",
                            "X-Frame-Options": "DENY",
                            "X-Content-Type-Options": "nosniff",
                        })


def escape(s: Any) -> str:
    return _html.escape(str(s))
