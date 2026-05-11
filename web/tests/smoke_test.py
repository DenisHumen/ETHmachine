"""End-to-end smoke test for the web dashboard.

Boots the aiohttp server in a background thread, performs first-run
registration, login, navigates pages, exercises the WebSocket logs
stream, edits a config file, and asserts everything works.

Run:  python -m web.tests.smoke_test
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _http(opener, method, url, data=None, allow_redirect=True):
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp = opener.open(req, timeout=10)
        return resp.status, resp.read(), resp.headers, resp.url
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers, e.url


def main():
    failures = []

    def check(label, ok, detail=""):
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {label}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    # Use a temp DB so we don't pollute real db/web_admin.db
    real_db = ROOT / "db" / "web_admin.db"
    real_secret = ROOT / "db" / ".web_cookie_secret"
    backup_db = None
    backup_secret = None
    if real_db.exists():
        backup_db = real_db.with_suffix(".db.bak_smoke")
        shutil.move(real_db, backup_db)
    if real_secret.exists():
        backup_secret = real_secret.with_suffix(".bak_smoke")
        shutil.move(real_secret, backup_secret)

    # also clear -wal/-shm
    for ext in ("-wal", "-shm"):
        side = real_db.parent / (real_db.name + ext)
        if side.exists():
            side.unlink()

    # Force reload of auth (so it re-reads the secret file we deleted)
    for mod in [m for m in list(sys.modules) if m.startswith("web") or m.startswith("config.modules.cfg_web")]:
        sys.modules.pop(mod, None)

    import web as web_pkg
    from web.server import start_web_server_thread, stop, is_running
    from config.modules.cfg_web import WEB_PORT

    port = WEB_PORT
    base = f"http://127.0.0.1:{port}"

    started = start_web_server_thread()
    check("server starts", started and is_running())
    # wait for server to bind
    deadline = time.time() + 10
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception as e:
            last_err = e
            time.sleep(0.2)
    else:
        check("health endpoint reachable", False, str(last_err))
        return _cleanup(backup_db, backup_secret, real_db, real_secret, failures)

    # Health endpoint
    cj = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPRedirectHandler(),
    )
    code, body, _, _ = _http(opener, "GET", base + "/api/health")
    check("health 200", code == 200 and b"true" in body.lower() or b"ok" in body.lower())

    # First-run: GET / -> /register
    code, body, _, final_url = _http(opener, "GET", base + "/")
    check("first-run redirects to /register", code == 200 and final_url.endswith("/register"),
          f"url={final_url}")

    # Register
    code, body, _, final_url = _http(opener, "POST", base + "/register",
                                     data={"username": "rootuser",
                                           "password": "verysecret123",
                                           "password2": "verysecret123"})
    check("register sets session + redirects to dashboard",
          code == 200 and final_url.endswith("/dashboard"),
          f"code={code} url={final_url}")

    # Logout (need csrf)
    # Fetch dashboard to capture csrf token via the page (csrf is embedded in logout form)
    code, body_dash, _, _ = _http(opener, "GET", base + "/dashboard")
    check("dashboard 200 after register", code == 200 and b"LIVE LOGS" in body_dash)
    # Extract csrf
    import re
    m = re.search(rb'name="csrf" value="([^"]+)"', body_dash)
    csrf = m.group(1).decode() if m else ""
    check("csrf token present in dashboard", bool(csrf))

    code, _, _, final_url = _http(opener, "POST", base + "/logout",
                                  data={"csrf": csrf})
    check("logout redirects to /login", code == 200 and final_url.endswith("/login"),
          f"url={final_url}")

    # Login
    code, _, _, final_url = _http(opener, "POST", base + "/login",
                                  data={"username": "rootuser",
                                        "password": "verysecret123"})
    check("login redirects to /dashboard", code == 200 and final_url.endswith("/dashboard"))

    # Re-capture csrf after re-login (session is new)
    code, body_dash, _, _ = _http(opener, "GET", base + "/dashboard")
    m = re.search(rb'name="csrf" value="([^"]+)"', body_dash)
    csrf = m.group(1).decode() if m else ""
    check("csrf token refreshed after login", bool(csrf))

    # Wrong password
    cj2 = CookieJar()
    opener2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj2))
    code, body, _, _ = _http(opener2, "POST", base + "/login",
                             data={"username": "rootuser", "password": "WRONG"})
    check("wrong password stays on /login", code == 200 and b"LOGIN" in body)

    # Pages reachable
    for path in ("/dashboard", "/databases", "/files", "/configs", "/settings"):
        code, body, _, _ = _http(opener, "GET", base + path)
        check(f"GET {path} -> 200", code == 200, f"len={len(body)}")

    # Files: traversal blocked
    code, _, _, _ = _http(opener, "GET",
                          base + "/files/download?root=data&path=../../main.py")
    check("traversal /files/download blocked", code in (403, 404))

    # Configs editor: read existing config + write same content (no diff)
    code, body, _, _ = _http(opener, "GET",
                             base + "/configs/edit?path=config/modules/cfg_web.py")
    check("configs/edit loads cfg_web.py", code == 200 and b"WEB_PORT" in body)

    # Try config editor with restart-required marker
    code, body, _, _ = _http(opener, "GET",
                             base + "/configs/edit?path=config/modules/general_config.py")
    check("configs/edit loads general_config.py", code == 200)

    # Save no-op (same content)
    rel = "config/modules/cfg_web.py"
    content = (ROOT / rel).read_text(encoding="utf-8")
    code, body, _, _ = _http(opener, "POST", base + "/configs/save",
                             data={"csrf": csrf, "path": rel, "content": content})
    check("configs/save no-op accepted", code == 200)

    # Save with a tiny edit, then revert
    edited = content + "\n# smoke-test marker\n"
    code, body, _, _ = _http(opener, "POST", base + "/configs/save",
                             data={"csrf": csrf, "path": rel, "content": edited})
    check("configs/save edit accepted", code == 200 and b"diff" in body.lower())
    # Verify file actually changed
    on_disk = (ROOT / rel).read_text(encoding="utf-8")
    check("file on disk reflects edit", on_disk.endswith("# smoke-test marker\n"))
    # Revert
    code, _, _, _ = _http(opener, "POST", base + "/configs/save",
                          data={"csrf": csrf, "path": rel, "content": content})
    check("configs/save revert accepted", code == 200)
    check("file restored", (ROOT / rel).read_text(encoding="utf-8") == content)

    # Logs WS via aiohttp client
    async def ws_test():
        import aiohttp
        cookie_header = "; ".join(f"{c.name}={c.value}" for c in cj)
        async with aiohttp.ClientSession(headers={"Cookie": cookie_header}) as s:
            async with s.ws_connect(f"ws://127.0.0.1:{port}/api/ws/logs") as ws:
                # First message must be snapshot
                msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                data = json.loads(msg.data)
                assert data.get("type") == "snapshot", f"got {data}"
                # Generate a log line and verify it streams
                from loguru import logger
                logger.info("SMOKE_TEST_MARKER_xyz")
                got = False
                deadline = time.time() + 5
                while time.time() < deadline:
                    msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                    if msg.type.name in ("CLOSED", "CLOSE", "CLOSING"):
                        break
                    try:
                        d = json.loads(msg.data)
                    except Exception:
                        continue
                    if d.get("type") == "log" and "SMOKE_TEST_MARKER_xyz" in (d.get("record", {}).get("msg") or ""):
                        got = True
                        break
                await ws.close()
                return got

    try:
        ws_ok = asyncio.run(ws_test())
    except Exception as e:  # pragma: no cover
        ws_ok = False
        import traceback
        print(f"  ws err: {e!r}")
        traceback.print_exc()
    check("WS /api/ws/logs streams new log records", ws_ok)

    # Dashboard renders cyberpunk style
    code, body, _, _ = _http(opener, "GET", base + "/dashboard")
    check("dashboard contains glitch class", b"glitch" in body)

    # Static asset
    code, body, _, _ = _http(opener, "GET", base + "/static/css/theme.css")
    check("static CSS 200", code == 200 and b"--red" in body)

    # Stop server
    stop(timeout=5)
    check("server stops", not is_running())

    return _cleanup(backup_db, backup_secret, real_db, real_secret, failures)


def _cleanup(backup_db, backup_secret, real_db, real_secret, failures):
    # remove temp DB and restore backups
    for ext in ("", "-wal", "-shm"):
        p = real_db.parent / (real_db.name + ext)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    if real_secret.exists():
        try:
            real_secret.unlink()
        except Exception:
            pass
    if backup_db and backup_db.exists():
        shutil.move(backup_db, real_db)
    if backup_secret and backup_secret.exists():
        shutil.move(backup_secret, real_secret)

    print("=" * 60)
    if failures:
        print(f"FAILED: {len(failures)}")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("ALL SMOKE TESTS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
