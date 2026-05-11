"""Auth handlers: /login, /register, /logout."""
from __future__ import annotations

import re

from aiohttp import web

from web.core import auth
from web.storage import database as db
from web.core.templating import render

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,64}$")


async def login_get(request: web.Request) -> web.Response:
    if db.count_users() == 0:
        return web.HTTPFound("/register")
    if request.get("user"):
        return web.HTTPFound("/dashboard")
    return render(request, "login.html")


async def login_post(request: web.Request) -> web.Response:
    if db.count_users() == 0:
        return web.HTTPFound("/register")
    data = await request.post()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return render(request, "login.html", error="Введите логин и пароль")
    row = db.find_user_by_username(username)
    if row is None or not auth.verify_password(password, row["password_hash"], row["password_salt"]):
        db.audit("login_failed", target=username)
        return render(request, "login.html", error="Неверный логин или пароль")
    sid = auth.login_user(request, int(row["id"]))
    db.audit("login_ok", target=username, user_id=int(row["id"]))
    resp = web.HTTPFound("/dashboard")
    resp.set_cookie(auth.COOKIE_NAME, auth.make_cookie_value(sid),
                    httponly=True, samesite="Lax", path="/",
                    max_age=60 * 60 * 24 * 30)
    return resp


async def register_get(request: web.Request) -> web.Response:
    if db.count_users() > 0:
        return web.HTTPFound("/login")
    return render(request, "register.html")


async def register_post(request: web.Request) -> web.Response:
    if db.count_users() > 0:
        return web.HTTPFound("/login")
    data = await request.post()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    password2 = data.get("password2") or ""
    if not USERNAME_RE.match(username):
        return render(request, "register.html",
                      error="Username: 3–64 символа [A-Za-z0-9_.-]")
    if len(password) < 8:
        return render(request, "register.html", error="Пароль минимум 8 символов")
    if password != password2:
        return render(request, "register.html", error="Пароли не совпадают")
    h, s = auth.hash_password(password)
    user_id = db.create_user(username, h, s, role="root")
    db.audit("register_root", target=username, user_id=user_id)
    sid = auth.login_user(request, user_id)
    resp = web.HTTPFound("/dashboard")
    resp.set_cookie(auth.COOKIE_NAME, auth.make_cookie_value(sid),
                    httponly=True, samesite="Lax", path="/",
                    max_age=60 * 60 * 24 * 30)
    return resp


async def logout_post(request: web.Request) -> web.Response:
    sid = request.get("session_id")
    user = request.get("user")
    if sid:
        # check csrf
        data = await request.post()
        if not auth.csrf_check(sid, data.get("csrf", "")):
            return web.Response(status=403, text="csrf")
        auth.logout_session(sid)
        if user:
            db.audit("logout", user_id=user["id"])
    resp = web.HTTPFound("/login")
    resp.del_cookie(auth.COOKIE_NAME, path="/")
    return resp
