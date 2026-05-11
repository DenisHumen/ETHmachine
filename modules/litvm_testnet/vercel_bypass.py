"""Vercel BotID + Caldera Hub tRPC client.

Реверс-инжиниринг liteforge.hub.caldera.xyz:

  1. Хаб развёрнут на Vercel. Каждый клиент проходит "Vercel Security
     Checkpoint" — JS-PoW challenge, выдающий cookie `_vcrcs`.
  2. Cookie `_vcrcs` сама по себе НЕ открывает API: Vercel дополнительно
     проверяет TLS-fingerprint (JA3/JA4). Пробовали `requests` и
     `curl_cffi(impersonate=chrome124)` — оба получают 429. Перенести
     сессию из браузера в Python не получается.
  3. Единственный надёжный способ дёрнуть API — из того же браузера, который
     прошёл checkpoint. Используем patchright (anti-detect форк Playwright):
     открываем браузер с прокси, ждём checkpoint, и все HTTP-запросы делаем
     через `page.evaluate(async () => fetch(...))`.
  4. Реальный faucet endpoint — это tRPC mutation:
        POST /api/trpc/faucet.requestFaucetFunds?batch=1
        body: { "0": { "json": {
            "rollupSubdomain": "liteforge",
            "recipientAddress": "0x...",
            "turnstileToken": "<solved Cloudflare Turnstile token>"
        }}}
     Ответ: [{"result":{"data":{"json":{"success":bool,"message":str,...}}}}]

Threading: patchright sync_api создаёт greenlets, привязанные к thread'у в
котором был вызван `sync_playwright().start()`. Использовать те же объекты
из другого потока — `greenlet.error: Cannot switch to a different thread`.
Поэтому ВСЕ операции с патчрайтом идут через единственный dedicated thread
(`_BrowserWorker`), worker-потоки шлют задачи в `queue.Queue` и ждут результат.
Captcha-resolve остаётся параллельным (он чисто HTTP к CapSolver и не
трогает патчрайт).
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from config.modules.cfg_litvm_testnet import (
    LITVM_FAUCET_URL,
    LITVM_VERCEL_BYPASS_HEADLESS,
    LITVM_VERCEL_BYPASS_TIMEOUT_SEC,
)
from modules.simple_logger import logger
from modules.litvm_testnet import database as db


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _parse_proxy_for_browser(proxy_raw: Optional[str]) -> Optional[Dict[str, str]]:
    """`USER:PASS@IP:PORT` → dict для patchright `context.proxy`."""
    if not proxy_raw:
        return None
    p = proxy_raw.strip()
    if not p:
        return None
    for pref in ("http://", "https://"):
        if p.startswith(pref):
            p = p[len(pref):]
            break
    try:
        if "@" in p:
            auth, addr = p.split("@", 1)
            user, pwd = auth.split(":", 1)
            return {"server": f"http://{addr}", "username": user, "password": pwd}
        return {"server": f"http://{p}"}
    except Exception:
        return None


class VercelBypassError(Exception):
    pass


class VercelCheckpointError(VercelBypassError):
    """Hub отдал Vercel Security Checkpoint вместо обычного ответа."""


# ---------------------------------------------------------------------------
# Dedicated patchright thread + jobs queue
# ---------------------------------------------------------------------------

class _Job:
    __slots__ = ("fn", "args", "kwargs", "event", "result", "error")

    def __init__(self, fn: Callable, args: tuple, kwargs: dict) -> None:
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.event = threading.Event()
        self.result: Any = None
        self.error: Optional[BaseException] = None


_STOP = object()


class _BrowserWorker:
    """Worker thread который владеет patchright (sync_playwright нельзя
    использовать кросс-потоково). Все обращения к браузеру — через
    `submit(fn, *args, **kwargs)`."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self._pw = None
        self._browser = None
        # contexts: key = proxy-string, value = dict(context, page)
        self._contexts: Dict[str, Dict[str, Any]] = {}

    # ---- public API (called from any thread) ----

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="litvm-browser", daemon=True,
        )
        self._thread.start()
        self._started.wait(timeout=5)

    def submit(self, fn: Callable, *args, timeout: float = 180.0, **kwargs) -> Any:
        """Послать функцию `fn(self, *args, **kwargs)` в browser-thread и
        дождаться результата. `fn` получает _BrowserWorker как первый arg
        чтобы пользоваться приватным состоянием (self._browser, ...)."""
        self.start()
        job = _Job(fn, args, kwargs)
        self._queue.put(job)
        if not job.event.wait(timeout=timeout):
            raise VercelBypassError(f"browser-thread timeout {timeout}s on {fn.__name__}")
        if job.error is not None:
            raise job.error
        return job.result

    def stop(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=10)
        self._thread = None

    # ---- thread loop ----

    def _loop(self) -> None:
        self._started.set()
        try:
            while True:
                job = self._queue.get()
                if job is _STOP:
                    self._teardown()
                    return
                assert isinstance(job, _Job)
                try:
                    job.result = job.fn(self, *job.args, **job.kwargs)
                except BaseException as e:  # noqa: BLE001
                    job.error = e
                finally:
                    job.event.set()
        except BaseException as e:
            logger.error(f"[litvm-vercel] browser-thread crashed: {e!r}")
        finally:
            try:
                self._teardown()
            except Exception:
                pass

    def _teardown(self) -> None:
        for key, ctx in list(self._contexts.items()):
            try:
                ctx["context"].close()
            except Exception:
                pass
        self._contexts.clear()
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None


# ---------------------------------------------------------------------------
# Operations that run inside _BrowserWorker thread
# (each takes `w: _BrowserWorker` as first arg)
# ---------------------------------------------------------------------------

def _op_ensure_browser(w: _BrowserWorker) -> None:
    if w._browser is not None:
        return
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as e:
        raise VercelBypassError(
            f"patchright не установлен: {e}. Запусти "
            f"`pip install patchright` и `python -m patchright install chromium`."
        )
    w._pw = sync_playwright().start()
    args = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1366,900",
    ]
    try:
        w._browser = w._pw.chromium.launch(
            headless=LITVM_VERCEL_BYPASS_HEADLESS,
            channel="chrome", args=args,
        )
    except Exception as exc:
        logger.warning(f"[litvm-vercel] channel=chrome недоступен ({exc}) — bundled Chromium")
        w._browser = w._pw.chromium.launch(
            headless=LITVM_VERCEL_BYPASS_HEADLESS, args=args,
        )


def _wait_past_checkpoint(page, proxy_label: str) -> None:
    deadline = time.time() + LITVM_VERCEL_BYPASS_TIMEOUT_SEC
    seen_cp = False
    while time.time() < deadline:
        try:
            title = (page.title() or "")
        except Exception:
            title = ""
        if title != "Vercel Security Checkpoint":
            time.sleep(2)  # дать SPA дочитать /api/auth/session
            if seen_cp:
                logger.info("[litvm-vercel] Vercel checkpoint пройден")
            return
        seen_cp = True
        time.sleep(1)
    raise VercelBypassError(
        f"Vercel checkpoint не пройден за {LITVM_VERCEL_BYPASS_TIMEOUT_SEC}s "
        f"(proxy={proxy_label})"
    )


def _persist_cookie(context, proxy: Optional[str]) -> None:
    """Сохраняет _vcrcs в БД (debug/observability)."""
    try:
        cookies = context.cookies(LITVM_FAUCET_URL)
    except Exception:
        return
    for c in cookies or []:
        if (c.get("name") or "").lower() != "_vcrcs":
            continue
        value = c.get("value") or ""
        if not value:
            continue
        exp: Optional[datetime] = None
        raw = c.get("expires")
        if isinstance(raw, (int, float)) and raw > 0:
            try:
                exp = datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                exp = None
        if exp is None:
            exp = datetime.now(timezone.utc) + timedelta(minutes=20)
        db.save_vcrcs(proxy, value, expires_at=exp, user_agent=_USER_AGENT)
        return


def _op_open_context(w: _BrowserWorker, proxy: Optional[str]) -> None:
    """Открывает context + page для proxy, проходит Vercel checkpoint.
    Идемпотентно: если context уже открыт — no-op."""
    key = (proxy or "").strip()
    if key in w._contexts:
        return
    _op_ensure_browser(w)
    kwargs: Dict[str, Any] = {
        "viewport": {"width": 1366, "height": 900},
        "user_agent": _USER_AGENT,
        "locale": "en-US",
    }
    bp = _parse_proxy_for_browser(proxy)
    if bp:
        kwargs["proxy"] = bp
    proxy_label = (bp or {}).get("server") or "direct"

    ctx = w._browser.new_context(**kwargs)
    page = ctx.new_page()
    page.set_default_timeout(int(LITVM_VERCEL_BYPASS_TIMEOUT_SEC * 1000))

    t0 = time.time()
    try:
        page.goto(LITVM_FAUCET_URL, wait_until="domcontentloaded",
                  timeout=int(LITVM_VERCEL_BYPASS_TIMEOUT_SEC * 1000))
        _wait_past_checkpoint(page, proxy_label)
        _persist_cookie(ctx, proxy)
    except Exception:
        try:
            ctx.close()
        except Exception:
            pass
        raise

    w._contexts[key] = {"context": ctx, "page": page}
    logger.success(
        f"[litvm-vercel] браузер готов за {time.time() - t0:.1f}s · proxy={proxy_label}"
    )


def _op_close_context(w: _BrowserWorker, proxy: Optional[str]) -> None:
    key = (proxy or "").strip()
    ctx = w._contexts.pop(key, None)
    if ctx is None:
        return
    try:
        ctx["context"].close()
    except Exception:
        pass


# Глобальный rate-limit для tRPC submits.
# Caldera Hub faucet — общая для всех кошельков hot-wallet на стороне сервера,
# подписывает и отправляет zkLTC. Если два submit'а долетают почти одновременно,
# server-side faucet получает nonce-конфликт и отвечает "Failed to send
# transaction". Размазываем submit'ы во времени минимум на N секунд между двумя
# подряд — все worker-потоки разделяют один browser-thread, так что одного
# глобального лока достаточно.
_TRPC_MIN_SPACING_SEC = 15.0  # эмпирически: блок-тайм Caldera ~2s, faucet tx
                              # confirm ~5s; 15s даёт server-side signer'у
                              # надёжный запас под nonce-стабилизацию даже
                              # при сильной конкуренции (50%+ кошельков
                              # с первой попытки).
_TRPC_LAST_SUBMIT_AT = 0.0


def _op_trpc_call(w: _BrowserWorker, proxy: Optional[str], procedure: str, payload: dict) -> dict:
    global _TRPC_LAST_SUBMIT_AT
    key = (proxy or "").strip()
    if key not in w._contexts:
        _op_open_context(w, proxy)
    page = w._contexts[key]["page"]
    path = f"/api/trpc/{procedure}?batch=1"
    body = {"0": {"json": payload}}

    # rate-limit: ждём пока с прошлого submit пройдёт _TRPC_MIN_SPACING_SEC.
    if procedure == "faucet.requestFaucetFunds":
        now = time.time()
        wait = (_TRPC_LAST_SUBMIT_AT + _TRPC_MIN_SPACING_SEC) - now
        if wait > 0:
            logger.info(f"[litvm-vercel] rate-limit: подожду {wait:.1f}s "
                        f"перед submit (proxy={key or 'direct'})")
            time.sleep(wait)
        _TRPC_LAST_SUBMIT_AT = time.time()

    # AbortController в js: 60s — некоторые ответы хаба занимают 30+ сек,
    # 30s было слишком жёстко (мы видели AbortError).
    js = """async ({path, body, timeoutMs}) => {
        try {
            const ctrl = new AbortController();
            const t = setTimeout(() => ctrl.abort(), timeoutMs);
            const r = await fetch(path, {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify(body),
                signal: ctrl.signal,
            });
            clearTimeout(t);
            const txt = await r.text();
            return {ok: true, status: r.status, body: txt};
        } catch (e) {
            return {ok: false, error: String(e)};
        }
    }"""
    t0 = time.time()
    try:
        result = page.evaluate(js, {"path": path, "body": body, "timeoutMs": 60000})
    except Exception as e:
        # Браузерный процесс мог умереть (EPIPE на node-стороне, Target closed,
        # ProtocolError и т.д.). Сносим context и browser, чтобы следующая
        # операция собрала всё заново. Без этого worker'ы будут бесконечно
        # ловить ту же ошибку на мёртвой странице.
        msg = str(e)
        marker = ("Target page" in msg or "Target closed" in msg or
                  "Browser has been closed" in msg or
                  "Connection closed" in msg or
                  "page has been closed" in msg or
                  "EPIPE" in msg or "ECONNRESET" in msg)
        if marker:
            logger.warning(f"[litvm-vercel] браузер потерял связь "
                           f"({msg[:120]}), пересоздаю context")
            _op_close_context(w, proxy)
            # Если умер сам browser — тоже пересоздадим (на следующем open_context)
            try:
                if w._browser is not None and not w._browser.is_connected():
                    try:
                        w._browser.close()
                    except Exception:
                        pass
                    w._browser = None
                    if w._pw is not None:
                        try:
                            w._pw.stop()
                        except Exception:
                            pass
                        w._pw = None
            except Exception:
                # is_connected() сам может бросать на оборванной связи
                w._browser = None
                w._pw = None
            raise VercelBypassError(f"browser disconnected: {msg[:160]}") from e
        raise
    elapsed = time.time() - t0
    logger.info(f"[litvm-vercel] tRPC {procedure} · {elapsed:.1f}s · proxy={key or 'direct'}")
    if not result.get("ok"):
        raise VercelBypassError(f"in-page fetch failed: {result.get('error')}")
    status = int(result.get("status") or 0)
    raw = result.get("body") or ""
    if status == 429 or "Vercel Security Checkpoint" in raw:
        raise VercelCheckpointError(f"HTTP {status} от /api/trpc/{procedure}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise VercelBypassError(f"невалидный JSON (HTTP {status}): {raw[:200]} — {e}")
    if not isinstance(parsed, list) or not parsed:
        raise VercelBypassError(f"непредвиденный shape: {raw[:300]}")
    first = parsed[0]
    if "error" in first:
        err = (first.get("error") or {}).get("json", {})
        return {"_trpc_error": True, "status": status, **err}
    data = ((first.get("result") or {}).get("data") or {}).get("json") or {}
    return {"_trpc_error": False, "status": status, **data}


# ---------------------------------------------------------------------------
# Public client (called from worker threads)
# ---------------------------------------------------------------------------

class VercelClient:
    """Singleton-обёртка над _BrowserWorker. Безопасна из любого потока."""

    _instance: Optional["VercelClient"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "VercelClient":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._worker = _BrowserWorker()

    def warmup(self, proxy: Optional[str]) -> None:
        self._worker.submit(_op_open_context, proxy)

    def close(self) -> None:
        self._worker.stop()
        # Освободить singleton чтобы следующий get_client() создал новый воркер.
        with VercelClient._instance_lock:
            VercelClient._instance = None

    def submit_faucet_request(
        self,
        proxy: Optional[str],
        rollup_subdomain: str,
        recipient_address: str,
        turnstile_token: str,
    ) -> dict:
        payload = {
            "rollupSubdomain": rollup_subdomain,
            "recipientAddress": recipient_address,
            "turnstileToken": turnstile_token,
        }
        try:
            return self._worker.submit(
                _op_trpc_call, proxy, "faucet.requestFaucetFunds", payload,
            )
        except VercelCheckpointError:
            logger.warning(
                f"[litvm-vercel] checkpoint в ответе — пересоздаю context "
                f"proxy={proxy or 'direct'}"
            )
            self._worker.submit(_op_close_context, proxy)
            db.invalidate_vcrcs(proxy)
            # Один retry с свежим context
            return self._worker.submit(
                _op_trpc_call, proxy, "faucet.requestFaucetFunds", payload,
            )


def get_client() -> VercelClient:
    return VercelClient.instance()


# Backwards-compat алиас
def get_fetcher() -> VercelClient:
    return get_client()
