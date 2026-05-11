"""Auth: scrypt password hashing, signed cookies, session middleware."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional

from aiohttp import web

from config.modules.cfg_web import WEB_COOKIE_SECRET_FILE
from web.storage import database as db
from web.core.paths import ROOT

COOKIE_NAME = "ethmachine_session"
SECRET_PATH = ROOT / WEB_COOKIE_SECRET_FILE

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LEN = 32


def _load_or_create_secret() -> bytes:
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_PATH.exists():
        data = SECRET_PATH.read_bytes()
        if len(data) >= 32:
            return data
    secret = secrets.token_bytes(48)
    SECRET_PATH.write_bytes(secret)
    try:
        # best-effort: 0o600 на Unix; на Windows игнорируется тихо.
        SECRET_PATH.chmod(0o600)
    except Exception:
        pass
    return secret


COOKIE_SECRET: bytes = _load_or_create_secret()


# ---------------------------------------------------------------------------
# Password hashing (stdlib scrypt)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> tuple[str, str]:
    """Return (hash_b64, salt_b64)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_LEN)
    return (base64.b64encode(digest).decode("ascii"),
            base64.b64encode(salt).decode("ascii"))


def verify_password(password: str, hash_b64: str, salt_b64: str) -> bool:
    try:
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_LEN)
    return hmac.compare_digest(digest, expected)


# ---------------------------------------------------------------------------
# Signed cookies
# ---------------------------------------------------------------------------

def _sign(value: str) -> str:
    sig = hmac.new(COOKIE_SECRET, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return sig[:32]


def make_cookie_value(session_id: str) -> str:
    return f"{session_id}.{_sign(session_id)}"


def parse_cookie_value(raw: str) -> Optional[str]:
    if not raw or "." not in raw:
        return None
    sid, sig = raw.rsplit(".", 1)
    if not hmac.compare_digest(_sign(sid), sig):
        return None
    return sid


# ---------------------------------------------------------------------------
# CSRF token = sha256(session_id + secret)
# ---------------------------------------------------------------------------

def csrf_token(session_id: str) -> str:
    return hashlib.sha256(
        session_id.encode("utf-8") + b"|" + COOKIE_SECRET
    ).hexdigest()[:32]


def csrf_check(session_id: str, supplied: str) -> bool:
    return hmac.compare_digest(csrf_token(session_id), supplied or "")


# ---------------------------------------------------------------------------
# Session creation/destruction
# ---------------------------------------------------------------------------

def login_user(request: web.Request, user_id: int) -> str:
    sid = secrets.token_urlsafe(32)
    ua = request.headers.get("User-Agent", "")[:500]
    ip = request.remote or ""
    db.create_session(sid, user_id, user_agent=ua, ip=ip)
    db.touch_user_login(user_id)
    return sid


def logout_session(session_id: str) -> None:
    db.delete_session(session_id)


# ---------------------------------------------------------------------------
# Middleware: attach request.user (or None)
# ---------------------------------------------------------------------------

PUBLIC_PATHS = {"/login", "/register", "/api/health"}


def is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    if path.startswith("/static/"):
        return True
    return False


@web.middleware
async def session_middleware(request: web.Request, handler):
    request["user"] = None
    request["session_id"] = None

    raw = request.cookies.get(COOKIE_NAME)
    sid = parse_cookie_value(raw) if raw else None
    if sid:
        row = db.get_session(sid)
        if row is not None:
            request["session_id"] = sid
            request["user"] = {
                "id": row["user_id"],
                "username": row["username"],
                "role": row["role"],
            }

    if not is_public(request.path) and request["user"] is None:
        # special-case: при пустой users → редирект на /register, иначе /login
        target = "/register" if db.count_users() == 0 else "/login"
        return web.HTTPFound(target)

    return await handler(request)
