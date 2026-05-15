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
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from config.modules.cfg_litvm_testnet import (
    LITVM_FAUCET_SUBMIT_MAX_WAITERS,
    LITVM_FAUCET_SUBMIT_MIN_SPACING_SEC,
    LITVM_FAUCET_URL,
    LITVM_VERCEL_BROWSER_OP_TIMEOUT_SEC,
    LITVM_VERCEL_BYPASS_HEADLESS,
    LITVM_VERCEL_BYPASS_MAX_CONTEXTS,
    LITVM_VERCEL_BYPASS_RESTART_EVERY,
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


class VercelTooBusyError(VercelBypassError):
    """Слишком много worker'ов уже стоят в очереди на submit-слот.
    Worker должен откатиться, не тратя капчу, и попробовать позже."""


# ───────────────────────────────────────────────────────────────────────────
# Submit slot pacing — выполняется в WORKER-thread, НЕ в browser-thread.
#
# Раньше пейсинг (`time.sleep(15)`) был внутри `_op_trpc_call`, который
# выполняется в browser-thread'е. Это блокировало ВСЁ — пока один submit
# спал 15 секунд, остальные jobs (warmup новых contexts, balance check, etc.)
# ждали в очереди. С 5 worker-thread'ами и 15 секунд пейсинга максимальный
# throughput был ~4 submit/мин, а submit() с timeout=180s массово тайм-аутил.
#
# Теперь worker сам ждёт слот через Condition. Browser-thread свободен и
# обслуживает каждый submit за ~2s. Throughput вырос примерно в 7 раз.
# ───────────────────────────────────────────────────────────────────────────

_SLOT_LOCK = threading.Lock()
_SLOT_COND = threading.Condition(_SLOT_LOCK)
_SLOT_LAST_AT = 0.0  # timestamp (time.time()) последнего grant
_SLOT_WAITERS = 0    # сколько worker'ов прямо сейчас спят в acquire


def _acquire_submit_slot(min_spacing_sec: float, max_waiters: int) -> None:
    """Блокирует worker-thread до момента, когда пройдёт min_spacing_sec
    с прошлого grant'а слота. Если уже >= max_waiters в очереди — бросает
    VercelTooBusyError, не дожидаясь, чтобы worker не палил капчу впустую.

    Корректно работает с многими worker'ами: каждый grant двигает
    _SLOT_LAST_AT, следующий waiter будет ждать min_spacing_sec уже
    относительно этого нового момента."""
    global _SLOT_LAST_AT, _SLOT_WAITERS
    with _SLOT_COND:
        if _SLOT_WAITERS >= max(1, int(max_waiters)):
            raise VercelTooBusyError(
                f"submit-queue переполнена ({_SLOT_WAITERS} worker'ов ждут "
                f"слота, лимит {max_waiters}); попробуй позже"
            )
        _SLOT_WAITERS += 1
        try:
            while True:
                now = time.time()
                wait = (_SLOT_LAST_AT + float(min_spacing_sec)) - now
                if wait <= 0:
                    _SLOT_LAST_AT = now
                    _SLOT_COND.notify()  # разбудить следующего waiter'а
                    return
                _SLOT_COND.wait(timeout=wait)
        finally:
            _SLOT_WAITERS -= 1


def _submit_queue_status() -> tuple[int, float]:
    """Возвращает (текущее число waiters, время с прошлого grant в секундах).
    Удобно для диагностики/логирования из worker'а."""
    with _SLOT_COND:
        return _SLOT_WAITERS, time.time() - _SLOT_LAST_AT


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
        # contexts: LRU. key = proxy-string, value = dict(context, page)
        # Ограничен сверху LITVM_VERCEL_BYPASS_MAX_CONTEXTS — при переполнении
        # самый старый закрывается, чтобы не жрать ОЗУ при многих кошельках.
        self._contexts: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        # Счётчик операций для периодического перезапуска chromium.
        self._op_count: int = 0

    # ---- public API (called from any thread) ----

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop, name="litvm-browser", daemon=True,
        )
        self._thread.start()
        self._started.wait(timeout=5)

    def submit(self, fn: Callable, *args, timeout: Optional[float] = None, **kwargs) -> Any:
        """Послать функцию `fn(self, *args, **kwargs)` в browser-thread и
        дождаться результата. `fn` получает _BrowserWorker как первый arg
        чтобы пользоваться приватным состоянием (self._browser, ...).

        Если timeout не задан — берётся LITVM_VERCEL_BROWSER_OP_TIMEOUT_SEC."""
        self.start()
        if timeout is None:
            timeout = float(LITVM_VERCEL_BROWSER_OP_TIMEOUT_SEC)
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
    _evict_lru_contexts(w)
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


def _evict_lru_contexts(w: _BrowserWorker) -> None:
    """Держим не более LITVM_VERCEL_BYPASS_MAX_CONTEXTS живых contexts.
    Самые давно не использовавшиеся закрываются — это основной фикс лика."""
    cap = max(1, int(LITVM_VERCEL_BYPASS_MAX_CONTEXTS))
    while len(w._contexts) > cap:
        old_key, old_ctx = w._contexts.popitem(last=False)
        try:
            old_ctx["context"].close()
        except Exception:
            pass
        logger.info(
            f"[litvm-vercel] LRU evict context proxy={old_key or 'direct'} "
            f"(живых осталось {len(w._contexts)}/{cap})"
        )


def _maybe_restart_browser(w: _BrowserWorker) -> None:
    """Каждые N tRPC-вызовов полностью перезапускаем chromium —
    chromium сам по себе ликает память при длительной работе с разными contexts."""
    every = int(LITVM_VERCEL_BYPASS_RESTART_EVERY)
    if every <= 0:
        return
    if w._op_count < every:
        return
    logger.info(
        f"[litvm-vercel] перезапуск chromium после {w._op_count} операций "
        f"(боремся с памятью)"
    )
    w._teardown()
    w._op_count = 0


def _op_trpc_call(w: _BrowserWorker, proxy: Optional[str], procedure: str, payload: dict) -> dict:
    """Выполняет один tRPC-вызов через ранее открытый browser-context.

    ВНИМАНИЕ: пейсинг submit'ов перенесён В WORKER-ПОТОК
    (см. _acquire_submit_slot выше). Здесь больше НЕТ time.sleep —
    browser-thread свободен максимально быстро (~2s на job)."""
    _maybe_restart_browser(w)
    key = (proxy or "").strip()
    if key not in w._contexts:
        _op_open_context(w, proxy)
    else:
        # LRU touch: свежеиспользованный context — в конец OrderedDict.
        w._contexts.move_to_end(key)
    w._op_count += 1
    page = w._contexts[key]["page"]
    path = f"/api/trpc/{procedure}?batch=1"
    body = {"0": {"json": payload}}

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
    # CDN/прокси может отдать HTML вместо tRPC JSON: Framer landing,
    # Vercel maintenance, generic 404/500. Это значит наш context "отравился"
    # — конкретный proxy-IP маршрутизируется не в tRPC backend, а в статику.
    # Поднимаем VercelCheckpointError, чтобы submit_faucet_request пересоздал
    # context (на retry браузер откроет другой выходной IP пути CDN).
    raw_lstrip = raw.lstrip()
    if raw_lstrip.startswith("<") and (
        "<!doctype" in raw_lstrip[:64].lower()
        or "<html" in raw_lstrip[:64].lower()
    ):
        # Берём первую содержательную строку для diagnostic'а.
        first_line = raw_lstrip.splitlines()[0][:120] if raw_lstrip else ""
        raise VercelCheckpointError(
            f"HTML вместо tRPC (HTTP {status}, body={first_line!r}) — "
            f"context отравился, пересоздать"
        )
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
        """Acquire submit-slot (worker-side wait), затем послать tRPC-вызов
        в browser-thread. На VercelCheckpointError — один retry с пересозданием
        context'а (под тем же слотом не ждём — checkpoint редкое событие)."""
        payload = {
            "rollupSubdomain": rollup_subdomain,
            "recipientAddress": recipient_address,
            "turnstileToken": turnstile_token,
        }
        # Worker ждёт здесь свой rate-limit-слот — НЕ блокируя browser-thread.
        # При переполнении очереди ждущих — VercelTooBusyError, worker откатится.
        _acquire_submit_slot(
            min_spacing_sec=float(LITVM_FAUCET_SUBMIT_MIN_SPACING_SEC),
            max_waiters=int(LITVM_FAUCET_SUBMIT_MAX_WAITERS),
        )
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
            # Retry — слот уже использован; для checkpoint-recovery (~раз в час)
            # это терпимо, повторно ждать пейсинг было бы вреднее (token устаревает).
            return self._worker.submit(
                _op_trpc_call, proxy, "faucet.requestFaucetFunds", payload,
            )


def get_client() -> VercelClient:
    return VercelClient.instance()


# Backwards-compat алиас
def get_fetcher() -> VercelClient:
    return get_client()
