"""Ghost Faucet worker — основная логика claim per-wallet."""
from __future__ import annotations

import time
from typing import Optional

import requests
from eth_account import Account
from web3 import Web3

from config.modules.general_config import RETRY_COUNT, SLEEP_BETWEEN_ACTIONS
from config.modules.cfg_fhenix import (
    GHOST_FAUCET_COOLDOWN_HOURS,
    GHOST_FAUCET_ARRIVAL_TIMEOUT_MIN,
    GHOST_FAUCET_BALANCE_POLL_INTERVAL,
    GHOST_FAUCET_SEPOLIA_RPCS,
)
from modules.captcha.manager import CaptchaManager
from modules.proxy_manager import get_proxy_dict
from modules.simple_logger import log_wallet_task, log_simple
from modules.fhenix.ghost_faucet import database as db
from modules.fhenix.ghost_faucet.faucet_client import (
    GhostFaucetCooldownError,
    GhostFaucetError,
    TURNSTILE_PAGEURL,
    TURNSTILE_SITEKEY,
    fetch_nonce,
    make_session,
    submit_claim,
)


def _fmt_remaining(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _get_balance_wei(address: str, proxy: Optional[str] = None) -> Optional[int]:
    """Получить баланс на Sepolia через round-robin RPC. Все RPC-запросы идут через proxy кошелька."""
    proxy_dict = get_proxy_dict(proxy)
    request_kwargs: dict = {"timeout": 15}
    if proxy_dict:
        request_kwargs["proxies"] = proxy_dict
    last_err: Optional[Exception] = None
    for rpc in GHOST_FAUCET_SEPOLIA_RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs=request_kwargs))
            return int(w3.eth.get_balance(Web3.to_checksum_address(address)))
        except Exception as e:
            last_err = e
            continue
    if last_err:
        log_simple(f"⚠ RPC error: {last_err}", "warning")
    return None


def _wait_for_arrival(address: str, balance_before: int,
                      idx: int, total: int, account_name: str | None,
                      proxy: Optional[str] = None) -> Optional[int]:
    """Ждать пополнения баланса. Возвращает new_balance или None при таймауте."""
    deadline = time.time() + GHOST_FAUCET_ARRIVAL_TIMEOUT_MIN * 60
    next_progress = time.time() + 120  # печатать «ещё ждём» не чаще раза в 2 мин
    while time.time() < deadline:
        time.sleep(GHOST_FAUCET_BALANCE_POLL_INTERVAL)
        bal = _get_balance_wei(address, proxy)
        if bal is None:
            continue
        if bal > balance_before:
            return bal
        if time.time() >= next_progress:
            left = int(deadline - time.time())
            log_wallet_task(address, idx, total,
                            f"⏳ ещё нет зачисления, осталось {_fmt_remaining(left)}",
                            "info", account_name=account_name)
            next_progress = time.time() + 120
    return None


def _solve_captcha(proxy: Optional[str]) -> Optional[str]:
    cm = CaptchaManager(proxy=proxy)
    if not cm.is_available:
        return None
    return cm.solve_turnstile(
        sitekey=TURNSTILE_SITEKEY,
        pageurl=TURNSTILE_PAGEURL,
    )


def _balance_before_from_task(task: dict) -> int:
    try:
        return int(task.get("balance_before") or 0)
    except (TypeError, ValueError):
        return 0


def _check_arrival_now(address: str, proxy: Optional[str], balance_before: int) -> Optional[int]:
    """Однократная проверка зачисления (без ожидания). True если баланс вырос."""
    cur = _get_balance_wei(address, proxy)
    if cur is None:
        return None
    if cur > balance_before:
        return cur
    return None


def _mark_arrived(address: str, balance_before: int, balance_after: int,
                  idx: int, total: int, account_name: Optional[str],
                  origin: str = "") -> None:
    db.update_task(address, status="arrived",
                   balance_after=str(balance_after), error_message=None)
    delta = max(0, balance_after - balance_before) / 1e18
    suffix = f" ({origin})" if origin else ""
    log_wallet_task(
        address, idx, total,
        f"✅ получено +{delta:.4f} sepETH{suffix}",
        "success", account_name=account_name,
    )


def _short_tx(tx_hash: Optional[str]) -> str:
    if not tx_hash:
        return ""
    h = tx_hash[2:] if tx_hash.startswith("0x") else tx_hash
    return f"{h[:8]}…{h[-6:]}" if len(h) > 16 else h


def _attempt_claim(wallet: str, proxy: Optional[str],
                   idx: int, total: int, account_name: str | None) -> tuple[bool, Optional[str], str]:
    """Один полный цикл: captcha + nonce + POST. Возвращает (ok, tx_hash, message)."""
    token = _solve_captcha(proxy)
    if not token:
        return False, None, "captcha не решена (нет API ключа или сервис вернул ошибку)"

    session = make_session(proxy)
    nonce = fetch_nonce(session)
    success, tx_hash, msg = submit_claim(session, wallet, nonce, token)

    db.record_request(wallet, success=success, tx_hash=tx_hash, response=msg)
    return success, tx_hash, msg


def process_wallet(record: dict, idx: int, total: int) -> None:
    """Полная обработка одного кошелька.

    Lifecycle wallet_tasks.status:
      pending → cooldown / requested → arrived
                                     → failed
    """
    pk = record.get("private_key", "").strip()
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
    proxy = record.get("proxy") or None

    db.upsert_wallet(address, account_name)
    task = db.get_task(address) or {}
    status = task.get("status", "pending")

    if status == "arrived":
        log_wallet_task(address, idx, total, "✅ уже получено ранее, пропуск",
                        "success", account_name=account_name)
        return

    # Проверка кулдауна по истории запросов (НЕ зависит от reset_tasks).
    remaining = db.cooldown_remaining(address, GHOST_FAUCET_COOLDOWN_HOURS)
    if remaining is not None:
        # Прошлый запрос мог уже зачислиться — сначала проверим баланс.
        bb = _balance_before_from_task(task)
        arrived = _check_arrival_now(address, proxy, bb)
        if arrived is not None:
            _mark_arrived(address, bb, arrived, idx, total, account_name,
                          origin="по прошлому запросу")
            return
        msg = (f"⏭ кулдаун, осталось {_fmt_remaining(int(remaining.total_seconds()))} "
               f"· баланс ещё не пришёл")
        log_wallet_task(address, idx, total, msg, "warning", account_name=account_name)
        db.update_task(address, status="cooldown",
                       error_message=f"cooldown {int(remaining.total_seconds())}s")
        return

    balance_before = _get_balance_wei(address, proxy) or 0
    db.update_task(address, status="in_progress", balance_before=str(balance_before))

    max_attempts = max(1, int(RETRY_COUNT))
    last_error: str = ""

    for attempt in range(1, max_attempts + 1):
        db.increment_attempts(address)
        log_wallet_task(address, idx, total,
                        f"🚰 попытка {attempt}/{max_attempts} · captcha + submit…",
                        "info", account_name=account_name)
        try:
            ok, tx_hash, msg = _attempt_claim(address, proxy, idx, total, account_name)
        except GhostFaucetCooldownError as e:
            # «Request limit reached» = прошлая заявка УЖЕ принята краном. Дождёмся зачисления.
            log_wallet_task(address, idx, total,
                            f"⏭ сервер: {str(e)[:120]} — проверяю/жду зачисление",
                            "warning", account_name=account_name)
            # Записываем в request_history, чтобы следующий запуск сразу видел кулдаун локально.
            db.record_request(address, success=False, response=str(e)[:300])

            arrived_now = _check_arrival_now(address, proxy, balance_before)
            if arrived_now is not None:
                _mark_arrived(address, balance_before, arrived_now, idx, total, account_name,
                              origin="по прошлой заявке")
                return
            if balance_before > 0:
                # До запуска уже что-то было — считаем зачисленным ранее.
                _mark_arrived(address, 0, balance_before, idx, total, account_name,
                              origin="зачислено ранее")
                return
            # Баланс пустой — заявка только что была (или давно), подождём появления.
            new_balance = _wait_for_arrival(address, balance_before, idx, total, account_name, proxy)
            if new_balance is not None:
                _mark_arrived(address, balance_before, new_balance, idx, total, account_name)
                return
            db.update_task(address, status="cooldown", error_message=str(e)[:300])
            log_wallet_task(address, idx, total,
                            f"⏭ кулдаун от сервера, не зачислилось за {GHOST_FAUCET_ARRIVAL_TIMEOUT_MIN}m",
                            "warning", account_name=account_name)
            return
        except (GhostFaucetError, requests.RequestException) as e:
            last_error = f"{type(e).__name__}: {e}"
            log_wallet_task(address, idx, total,
                            f"⚠ ошибка сети: {str(e)[:140]}",
                            "warning", account_name=account_name)
            time.sleep(SLEEP_BETWEEN_ACTIONS[0] if SLEEP_BETWEEN_ACTIONS else 2)
            continue

        if not ok:
            last_error = msg
            log_wallet_task(address, idx, total,
                            f"⚠ отказ: {(msg or 'unknown')[:140]}",
                            "warning", account_name=account_name)
            time.sleep(SLEEP_BETWEEN_ACTIONS[0] if SLEEP_BETWEEN_ACTIONS else 2)
            continue

        # Сервер принял заявку — ждём фактическое зачисление.
        db.update_task(address, status="requested", last_tx_hash=tx_hash,
                       error_message=None)
        log_wallet_task(address, idx, total,
                        f"📤 заявка принята · tx={_short_tx(tx_hash)} · ждём баланс",
                        "success", account_name=account_name)

        new_balance = _wait_for_arrival(address, balance_before, idx, total, account_name, proxy)
        if new_balance is not None:
            _mark_arrived(address, balance_before, new_balance, idx, total, account_name)
            return

        last_error = f"timeout {GHOST_FAUCET_ARRIVAL_TIMEOUT_MIN}m, токены не пришли"
        log_wallet_task(address, idx, total, f"⚠ {last_error}",
                        "warning", account_name=account_name)
        # Если сервер уже принял один запрос, повторная отправка упрётся
        # в server-side кулдаун — выходим, чтобы не жечь капчу.
        db.update_task(address, status="failed", error_message=last_error)
        return

    db.update_task(address, status="failed", error_message=last_error or "unknown")
    log_wallet_task(address, idx, total,
                    f"❌ все попытки исчерпаны · last={last_error[:140]}",
                    "error", account_name=account_name)
