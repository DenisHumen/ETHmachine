"""LiteForge faucet worker — основная логика claim per-wallet.

Архитектура зеркальная modules/fhenix/alchemy_faucet/worker.py, с одной важной
особенностью: успешным считается не приём заявки, а ФАКТИЧЕСКОЕ зачисление
zkLTC на кошелёк. Время ожидания зачисления адаптивное — среднее по последним
LITVM_FAUCET_AVG_SAMPLES запросам, плюс LITVM_FAUCET_AVG_MARGIN (по умолчанию +20%).
"""
from __future__ import annotations

import time
from typing import Optional

from eth_account import Account
from web3 import Web3

from config.modules.general_config import RETRY_COUNT, SLEEP_BETWEEN_ACTIONS
from config.modules.cfg_litvm_testnet import (
    LITVM_FAUCET_AVG_MARGIN,
    LITVM_FAUCET_AVG_SAMPLES,
    LITVM_FAUCET_ARRIVAL_FALLBACK_SEC,
    LITVM_FAUCET_ARRIVAL_MAX_SEC,
    LITVM_FAUCET_ARRIVAL_MIN_SEC,
    LITVM_FAUCET_BALANCE_POLL_INTERVAL,
    LITVM_FAUCET_CAPTCHA_SITEKEY,
    LITVM_FAUCET_CAPTCHA_TYPE,
    LITVM_FAUCET_COOLDOWN_HOURS,
    LITVM_RPCS,
)
from modules.captcha.manager import CaptchaManager
from modules.proxy_manager import get_proxy_dict
from modules.simple_logger import log_simple, log_wallet_task
from modules.litvm_testnet.faucet import database as db
from modules.litvm_testnet.faucet.faucet_client import (
    CAPTCHA_PAGEURL,
    LitvmFaucetCaptchaError,
    LitvmFaucetCooldownError,
    LitvmFaucetError,
    LitvmFaucetVercelChallenge,
    classify_error,
    is_test_sitekey,
    submit_claim,
    warmup_proxy,
)
from modules.litvm_testnet.vercel_bypass import (
    VercelBypassError,
    get_client,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fmt_remaining(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _short_tx(tx_hash: Optional[str]) -> str:
    if not tx_hash:
        return ""
    h = tx_hash[2:] if tx_hash.startswith("0x") else tx_hash
    return f"{h[:8]}…{h[-6:]}" if len(h) > 16 else h


def _get_balance_wei(address: str, proxy: Optional[str] = None) -> Optional[int]:
    """Получить native-balance на LiteForge через round-robin RPC."""
    proxy_dict = get_proxy_dict(proxy)
    request_kwargs: dict = {"timeout": 15}
    if proxy_dict:
        request_kwargs["proxies"] = proxy_dict
    last_err: Optional[Exception] = None
    for rpc in LITVM_RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs=request_kwargs))
            return int(w3.eth.get_balance(Web3.to_checksum_address(address)))
        except Exception as e:
            last_err = e
            continue
    if last_err:
        log_simple(f"⚠ RPC error: {last_err}", "warning")
    return None


def _arrival_timeout_seconds() -> float:
    """Адаптивный таймаут ожидания зачисления.
    avg(последние N успешных arrival) * (1 + margin), зажат [min, max].
    Если статистики нет — fallback из конфига."""
    avg = db.avg_arrival_seconds(LITVM_FAUCET_AVG_SAMPLES)
    if avg is None:
        base = float(LITVM_FAUCET_ARRIVAL_FALLBACK_SEC)
    else:
        base = float(avg) * (1.0 + float(LITVM_FAUCET_AVG_MARGIN))
    return max(
        float(LITVM_FAUCET_ARRIVAL_MIN_SEC),
        min(float(LITVM_FAUCET_ARRIVAL_MAX_SEC), base),
    )


def _wait_for_arrival(address: str, balance_before: int,
                      idx: int, total: int, account_name: Optional[str],
                      proxy: Optional[str], timeout_sec: float) -> tuple[Optional[int], float]:
    """Ждать пополнения native-баланса. Возвращает (new_balance | None, elapsed_seconds).
    elapsed считается от старта функции до факта обнаружения зачисления."""
    started = time.time()
    deadline = started + timeout_sec
    next_progress = time.time() + 60
    while time.time() < deadline:
        time.sleep(LITVM_FAUCET_BALANCE_POLL_INTERVAL)
        bal = _get_balance_wei(address, proxy)
        if bal is not None and bal > balance_before:
            return bal, time.time() - started
        if time.time() >= next_progress:
            left = deadline - time.time()
            log_wallet_task(
                address, idx, total,
                f"⏳ ещё нет zkLTC, осталось {_fmt_remaining(left)}",
                "info", account_name=account_name,
            )
            next_progress = time.time() + 60
    return None, time.time() - started


def _solve_captcha(proxy: Optional[str], sitekey: str) -> Optional[str]:
    cm = CaptchaManager(proxy=proxy)
    if not cm.is_available:
        return None
    captcha_type = (LITVM_FAUCET_CAPTCHA_TYPE or "turnstile").lower()
    try:
        if captcha_type == "turnstile":
            return cm.solve_turnstile(sitekey=sitekey, pageurl=CAPTCHA_PAGEURL)
        if captcha_type == "hcaptcha":
            return cm.solve_hcaptcha(sitekey=sitekey, pageurl=CAPTCHA_PAGEURL)
        if captcha_type == "recaptcha_v2":
            return cm.solve_recaptcha_v2(sitekey=sitekey, pageurl=CAPTCHA_PAGEURL)
        if captcha_type == "recaptcha_v3":
            return cm.solve_recaptcha_v3(sitekey=sitekey, pageurl=CAPTCHA_PAGEURL)
        log_simple(f"❌ Неизвестный LITVM_FAUCET_CAPTCHA_TYPE='{captcha_type}'", "error")
        return None
    except Exception as e:
        # CapSolver/2captcha могут вернуть "task data has expired",
        # "ERROR_NO_SLOT_AVAILABLE" и пр. — это retriable. Не даём
        # исключению порвать worker-thread, возвращаем None — worker
        # переcолвит на следующей попытке.
        log_simple(f"⚠ captcha solver error: {str(e)[:200]}", "warning")
        return None


def _mark_arrived(address: str, balance_before: int, balance_after: int,
                  idx: int, total: int, account_name: Optional[str],
                  origin: str = "",
                  request_id: Optional[int] = None,
                  arrival_seconds: Optional[float] = None) -> None:
    db.update_task(address, status="arrived",
                   balance_after=str(balance_after), error_message=None)
    if request_id is not None and arrival_seconds is not None:
        db.mark_request_arrived(request_id, arrival_seconds)
    delta = max(0, balance_after - balance_before) / 1e18
    suffix = f" ({origin})" if origin else ""
    timing = f" · arrival {arrival_seconds:.0f}s" if arrival_seconds is not None else ""
    log_wallet_task(
        address, idx, total,
        f"✅ получено +{delta:.4f} zkLTC{suffix}{timing}",
        "success", account_name=account_name,
    )


def _balance_before_from_task(task: dict) -> int:
    try:
        return int(task.get("balance_before") or 0)
    except (TypeError, ValueError):
        return 0


def _check_arrival_now(address: str, proxy: Optional[str], balance_before: int) -> Optional[int]:
    """Однократная проверка зачисления (без ожидания)."""
    cur = _get_balance_wei(address, proxy)
    if cur is None:
        return None
    return cur if cur > balance_before else None


def _get_balance_with_fallback(address: str, record: dict) -> Optional[int]:
    """Балансная проверка через primary, затем reserve_proxy. Используется на
    стадии cooldown-проверки до полного warmup'а — чтобы дешёво подтвердить
    зачисление даже если primary прокси упал."""
    for proxy in _proxy_candidates(record):
        bal = _get_balance_wei(address, proxy)
        if bal is not None:
            return bal
    return None


# ---------------------------------------------------------------------------
# main flow
# ---------------------------------------------------------------------------

def _proxy_candidates(record: dict) -> list[Optional[str]]:
    """Возвращает упорядоченный список прокси для кошелька:
    primary `proxy` → fallback `reserve_proxy` (если заполнен и отличается).
    Если оба пусты — `[None]` (direct connection, на свой страх и риск)."""
    primary = (record.get("proxy") or "").strip() or None
    reserve = (record.get("reserve_proxy") or "").strip() or None
    out: list[Optional[str]] = []
    if primary:
        out.append(primary)
    if reserve and reserve != primary:
        out.append(reserve)
    if not out:
        out.append(None)
    return out


def _resolve_working_proxy(record: dict, idx: int, total: int,
                           account_name: Optional[str],
                           address: str) -> Optional[Optional[str]]:
    """Подбирает рабочий прокси (primary → reserve) прогревая браузерный
    контекст. Возвращает строку прокси, или None если работает direct,
    либо False если ВСЕ варианты провалились."""
    candidates = _proxy_candidates(record)
    is_reserve = False
    for proxy in candidates:
        label = proxy if proxy else "direct"
        kind = "reserve" if is_reserve else "primary"
        log_wallet_task(
            address, idx, total,
            f"🌐 warmup через {kind} proxy: {label}",
            "info", account_name=account_name,
        )
        try:
            warmup_proxy(proxy)
            if is_reserve:
                log_wallet_task(
                    address, idx, total,
                    f"✅ переключился на reserve_proxy ({label})",
                    "success", account_name=account_name,
                )
            return proxy
        except (VercelBypassError, LitvmFaucetError) as e:
            log_wallet_task(
                address, idx, total,
                f"⚠ {kind} proxy не работает: {str(e)[:160]}",
                "warning", account_name=account_name,
            )
            is_reserve = True
            continue
    log_wallet_task(
        address, idx, total,
        "❌ ни primary, ни reserve proxy не работают",
        "error", account_name=account_name,
    )
    return False  # sentinel: всё провалилось


def _attempt_claim(wallet: str, proxy: Optional[str],
                   sitekey: str) -> tuple[bool, Optional[str], str, Optional[int]]:
    """Один цикл: captcha + tRPC mutation через браузер.
    Возвращает (ok, tx_hash, message, request_history_id)."""
    token = _solve_captcha(proxy, sitekey)
    if not token:
        return False, None, "captcha не решена (нет API ключа или сервис вернул ошибку)", None
    success, tx_hash, msg = submit_claim(proxy, wallet, token)
    request_id = db.record_request_sent(wallet, success=success, tx_hash=tx_hash, response=msg)
    return success, tx_hash, msg, request_id


def process_wallet(record: dict, idx: int, total: int) -> None:
    """Полная обработка одного кошелька.

    Lifecycle faucet_wallet_tasks.status:
      pending → in_progress → requested → arrived
                                       ↘ cooldown
                                       ↘ failed / ineligible
    """
    pk = (record.get("private_key") or "").strip()
    if not pk:
        return
    if not pk.startswith("0x"):
        pk = "0x" + pk
    try:
        address = Account.from_key(pk).address
    except Exception as e:
        log_simple(f"❌ Невалидный private_key #{idx}: {e}", "error")
        return

    account_name = record.get("name") or None

    db.upsert_wallet(address, account_name)
    task = db.get_task(address) or {}
    status = task.get("status", "pending")

    # Сначала — проверка кулдауна. Кран Caldera Hub: 1 запрос / 24h на адрес.
    # Решение «можно/нельзя запрашивать» = есть ли в request_history успешная
    # заявка моложе LITVM_FAUCET_COOLDOWN_HOURS. Status='arrived' сам по себе
    # ничего не значит — если 24h уже прошли, можно идти снова. Эта проверка
    # стоит выше всех остальных, чтобы не тратить ни одного запроса до решения.
    remaining = db.cooldown_remaining(address, LITVM_FAUCET_COOLDOWN_HOURS)
    if remaining is not None:
        remaining_s = remaining.total_seconds()
        # Если статус ещё не 'arrived' — возможно, прошлый запрос дошёл, но
        # код упал между tx_sent и mark_arrived. Подтвердим по балансу.
        if status != "arrived":
            bb = _balance_before_from_task(task)
            cur_bal = _get_balance_with_fallback(address, record)
            if cur_bal is not None and cur_bal > bb:
                _mark_arrived(address, bb, cur_bal, idx, total, account_name,
                              origin="по прошлому запросу")
                return
        msg = (f"⏭ кулдаун · можно повторно через "
               f"{_fmt_remaining(remaining_s)}")
        log_wallet_task(address, idx, total, msg, "success" if status == "arrived" else "warning",
                        account_name=account_name)
        if status != "arrived":
            db.update_task(address, status="cooldown",
                           error_message=f"cooldown {int(remaining_s)}s")
        return

    # Кулдаун прошёл (или его не было). Если статус был 'arrived' / 'cooldown' —
    # стартуем новый цикл, как с нуля.
    if status in ("arrived", "cooldown"):
        log_wallet_task(
            address, idx, total,
            "♻️ кулдаун истёк — запрашиваю кран повторно",
            "info", account_name=account_name,
        )
        db.update_task(address, status="pending", error_message=None)

    # Pre-step: подбираем рабочий прокси (primary → reserve), прогревая
    # browser-контекст. Дальше ВСЕ запросы кошелька (captcha API, tRPC POST,
    # web3 balance check) идут через эту строку — единая точка
    # входа/выхода чтобы не палить автоматизацию.
    resolved = _resolve_working_proxy(record, idx, total, account_name, address)
    if resolved is False:
        db.update_task(address, status="failed",
                       error_message="all proxies failed warmup")
        return
    proxy = resolved  # может быть None если data.csv не содержит прокси

    balance_before = _get_balance_wei(address, proxy) or 0
    db.update_task(address, status="in_progress", balance_before=str(balance_before))

    # Sitekey зашит в конфиг (Turnstile sitekey стабильный — не парсим из HTML).
    sitekey = LITVM_FAUCET_CAPTCHA_SITEKEY
    if not (sitekey or "").strip():
        msg = ("LITVM_FAUCET_CAPTCHA_SITEKEY пустой. Положи Turnstile sitekey "
               "в config/modules/cfg_litvm_testnet.py.")
        log_wallet_task(address, idx, total, f"❌ {msg}",
                        "error", account_name=account_name)
        db.update_task(address, status="failed", error_message=msg[:300])
        return
    if is_test_sitekey(sitekey):
        msg = (f"sitekey '{sitekey}' — это публичный test-ключ, CapSolver/2captcha/etc "
               f"отказываются его решать. Положи реальный sitekey в "
               f"LITVM_FAUCET_CAPTCHA_SITEKEY.")
        log_wallet_task(address, idx, total, f"❌ {msg}",
                        "error", account_name=account_name)
        db.update_task(address, status="failed", error_message=msg[:300])
        return

    max_attempts = max(1, int(RETRY_COUNT))
    last_error = ""
    arrival_timeout = _arrival_timeout_seconds()
    log_wallet_task(
        address, idx, total,
        f"🚰 старт · timeout zkLTC = {_fmt_remaining(arrival_timeout)} "
        f"(avg+{int(LITVM_FAUCET_AVG_MARGIN * 100)}%)",
        "info", account_name=account_name,
    )

    for attempt in range(1, max_attempts + 1):
        db.increment_attempts(address)
        log_wallet_task(
            address, idx, total,
            f"🚰 попытка {attempt}/{max_attempts} · captcha ({LITVM_FAUCET_CAPTCHA_TYPE}) + tRPC submit…",
            "info", account_name=account_name,
        )
        try:
            ok, tx_hash, msg, request_id = _attempt_claim(address, proxy, sitekey)
        except LitvmFaucetCaptchaError as e:
            # Turnstile token отвергнут — пересолвить и попробовать снова
            last_error = f"captcha rejected: {e}"
            log_wallet_task(
                address, idx, total,
                f"🔁 капча отвергнута сервером, пересолвлю · {str(e)[:140]}",
                "warning", account_name=account_name,
            )
            time.sleep(SLEEP_BETWEEN_ACTIONS[0] if SLEEP_BETWEEN_ACTIONS else 2)
            continue
        except LitvmFaucetVercelChallenge as e:
            # Vercel BotID порвал сессию — браузер сам пересоздаст context
            # на следующем submit_claim (см. submit_faucet_request retry).
            last_error = f"vercel_checkpoint: {e}"
            log_wallet_task(
                address, idx, total,
                f"🛡 Vercel BotID — браузер пересоздаст сессию · {str(e)[:120]}",
                "warning", account_name=account_name,
            )
            time.sleep(SLEEP_BETWEEN_ACTIONS[0] if SLEEP_BETWEEN_ACTIONS else 2)
            continue
        except LitvmFaucetCooldownError as e:
            log_wallet_task(
                address, idx, total,
                f"⏭ сервер: {str(e)[:120]} — проверяю/жду зачисление",
                "warning", account_name=account_name,
            )
            db.record_request_sent(address, success=False, response=str(e)[:300])

            arrived_now = _check_arrival_now(address, proxy, balance_before)
            if arrived_now is not None:
                _mark_arrived(address, balance_before, arrived_now, idx, total, account_name,
                              origin="по прошлой заявке")
                return
            new_balance, elapsed = _wait_for_arrival(
                address, balance_before, idx, total, account_name, proxy, arrival_timeout,
            )
            if new_balance is not None:
                _mark_arrived(address, balance_before, new_balance, idx, total, account_name,
                              arrival_seconds=elapsed)
                return
            db.update_task(address, status="cooldown", error_message=str(e)[:300])
            log_wallet_task(
                address, idx, total,
                f"⏭ кулдаун от сервера, баланс не пришёл за {_fmt_remaining(arrival_timeout)}",
                "warning", account_name=account_name,
            )
            return
        except LitvmFaucetError as e:
            last_error = f"{type(e).__name__}: {e}"
            log_wallet_task(
                address, idx, total,
                f"⚠ ошибка: {str(e)[:140]}",
                "warning", account_name=account_name,
            )
            time.sleep(SLEEP_BETWEEN_ACTIONS[0] if SLEEP_BETWEEN_ACTIONS else 2)
            continue

        if not ok:
            last_error = msg
            kind = classify_error(msg)
            if kind == "ineligible":
                log_wallet_task(
                    address, idx, total,
                    f"⛔ кошелёк не подходит: {(msg or 'unknown')[:140]}",
                    "error", account_name=account_name,
                )
                db.update_task(address, status="ineligible", error_message=msg[:300])
                return

            # На сервере faucet (Caldera Hub) случился nonce/RPC сбой —
            # turnstile token валиден, captcha-solve переделывать не нужно.
            # Делаем нарастающий backoff и сначала проверяем баланс: может
            # предыдущий "failed" реально дошёл до блокчейна.
            if kind == "server_busy":
                # 30s, 60s, 90s, ..., capped at 180s
                backoff = min(180, 30 * attempt)
                arrived_now = _check_arrival_now(address, proxy, balance_before)
                if arrived_now is not None:
                    _mark_arrived(address, balance_before, arrived_now,
                                  idx, total, account_name,
                                  origin="по предыдущей заявке")
                    return
                log_wallet_task(
                    address, idx, total,
                    f"⏳ server-busy: {(msg or '')[:80]} · ждём {backoff}s "
                    f"и проверяем баланс перед повтором",
                    "warning", account_name=account_name,
                )
                # Спим, периодически проверяя баланс — если zkLTC всё-таки
                # пришли (server-side faucet всё-таки протолкнул tx), сразу
                # выходим, не тратим CapSolver-кредит.
                slept = 0
                step = max(1, int(LITVM_FAUCET_BALANCE_POLL_INTERVAL))
                while slept < backoff:
                    time.sleep(step)
                    slept += step
                    cur = _check_arrival_now(address, proxy, balance_before)
                    if cur is not None:
                        _mark_arrived(address, balance_before, cur,
                                      idx, total, account_name,
                                      origin="по предыдущей заявке")
                        return
                continue

            log_wallet_task(
                address, idx, total,
                f"⚠ отказ: {(msg or 'unknown')[:140]}",
                "warning", account_name=account_name,
            )
            time.sleep(SLEEP_BETWEEN_ACTIONS[0] if SLEEP_BETWEEN_ACTIONS else 2)
            continue

        # Сервер принял заявку — ждём фактическое зачисление.
        db.update_task(address, status="requested", last_tx_hash=tx_hash,
                       error_message=None)
        log_wallet_task(
            address, idx, total,
            f"📤 заявка принята · tx={_short_tx(tx_hash)} · ждём zkLTC до "
            f"{_fmt_remaining(arrival_timeout)}",
            "success", account_name=account_name,
        )

        new_balance, elapsed = _wait_for_arrival(
            address, balance_before, idx, total, account_name, proxy, arrival_timeout,
        )
        if new_balance is not None:
            _mark_arrived(
                address, balance_before, new_balance, idx, total, account_name,
                request_id=request_id, arrival_seconds=elapsed,
            )
            return

        last_error = f"timeout {_fmt_remaining(arrival_timeout)}, zkLTC не пришли"
        log_wallet_task(address, idx, total, f"⚠ {last_error}",
                        "warning", account_name=account_name)
        db.update_task(address, status="failed", error_message=last_error)
        return

    db.update_task(address, status="failed", error_message=last_error or "unknown")
    log_wallet_task(
        address, idx, total,
        f"❌ все попытки исчерпаны · last={last_error[:140]}",
        "error", account_name=account_name,
    )
