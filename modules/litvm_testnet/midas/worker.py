"""Midas Prediction Market — per-wallet worker.

Workflow для одного кошелька (выполняется в `process_wallet`):
  1. Регистрация:
       - получить /auth/nonce → message
       - personal_sign(message)
       - решить Cloudflare Turnstile
       - POST /auth/wallet/register → accessToken
     Если кошелёк уже зарегистрирован (есть запись в БД + JWT не истёк):
       - повторно подписываем nonce и логинимся (получить свежий JWT).
  2. Faucets:
       - USDC: если now - last_usdc_faucet_at >= 1h → POST /users/faucet_usdc
       - Native (zkLTC): если now - last_native_faucet_at >= 24h И баланс
         < MIDAS_NATIVE_SUFFICIENT_BALANCE → POST /users/faucet_native
  3. Check-in:
       - если last_checkin_day != today_utc_str → POST /login/checkin
  4. Bets:
       - запрашиваем /markets (sortBy=trending, limit=50)
       - фильтруем USDC-маркеты с TTL > MIDAS_MARKET_MIN_TTL_SEC
       - случайно выбираем bets_count из MIDAS_BETS_PER_WALLET
       - на каждый: random outcome, random target USDC из MIDAS_BET_AMOUNT_USDC
         → quote_shares → approve USDC → buy → log

Все промежуточные результаты сохраняются в БД сразу после I/O — модуль
резюмируем при KeyboardInterrupt / RPC-фейле.
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from typing import Optional

from config.modules.general_config import MAIN_PROXY
from config.modules.cfg_litvm_testnet import (
    MIDAS_BET_AMOUNT_USDC,
    MIDAS_BET_MAX_COST_MULTIPLIER,
    MIDAS_BETS_PER_WALLET,
    MIDAS_CHECKIN_ENABLED,
    MIDAS_FAUCET_NATIVE_COOLDOWN_SEC,
    MIDAS_FAUCET_USDC_COOLDOWN_SEC,
    MIDAS_GAS_RESERVE_ZKLTC,
    MIDAS_MARKET_MIN_TTL_SEC,
    MIDAS_MARKETS_FETCH_LIMIT,
    MIDAS_MIN_MARKETS_TO_BET,
    MIDAS_NATIVE_SUFFICIENT_BALANCE,
    MIDAS_SITE_URL,
    MIDAS_SLEEP_BETWEEN_BETS,
    MIDAS_TURNSTILE_SITEKEY,
    MIDAS_TX_ATTEMPTS,
    MIDAS_USDC_ADDRESS,
    MIDAS_USDC_DECIMALS,
    MIDAS_USDC_MIN_TRADE_RAW,
)
from modules.captcha.manager import CaptchaManager
from modules.nickname_generator import NicknameGenerator
from modules.simple_logger import log_simple, log_wallet_task
from modules.litvm_testnet.midas import database as db
from modules.litvm_testnet.midas.api_client import MidasApiError, MidasClient
from modules.litvm_testnet.midas import market_client as mc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _short_tx(h: Optional[str]) -> str:
    if not h:
        return ""
    raw = h[2:] if h.startswith("0x") else h
    return f"{raw[:8]}…{raw[-6:]}" if len(raw) > 16 else raw


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _proxy_of(record: dict) -> Optional[str]:
    p = (record.get("proxy") or "").strip()
    return p or None


def _reserve_proxy_of(record: dict) -> Optional[str]:
    p = (record.get("reserve_proxy") or "").strip()
    return p or None


def _account_from_record(record: dict):
    pk = (record.get("private_key") or "").strip()
    if not pk:
        return None
    try:
        return mc.account_from_private_key(pk)
    except Exception as e:  # noqa: BLE001
        log_simple(f"⚠ невалидный private_key: {e}", "warning")
        return None


def _new_api_client(proxy: Optional[str],
                    reserve_proxy: Optional[str] = None) -> MidasClient:
    return MidasClient(proxy=proxy, reserve_proxy=reserve_proxy)


# ---------------------------------------------------------------------------
# Phase 1: planner
# ---------------------------------------------------------------------------

def plan_wallet(record: dict, idx: int, total: int) -> bool:
    """Минимальный план: создаём запись о кошельке + генерим nickname.

    Реальная работа (регистрация / ставки) делается в `process_wallet`,
    так как зависит от внешнего состояния (API / on-chain).
    """
    account = _account_from_record(record)
    if account is None:
        return False
    address = account.address
    account_name = record.get("name") or None
    db.upsert_wallet(address, name=account_name)
    w = db.get_wallet(address) or {}
    if not w.get("nickname"):
        nick = NicknameGenerator().generate_nickname()
        db.update_wallet(address, nickname=nick)
        log_wallet_task(address, idx, total,
                        f"📋 план готов · nickname='{nick}'",
                        "info", account_name=account_name)
    else:
        log_wallet_task(address, idx, total,
                        f"📋 план уже есть · nickname='{w['nickname']}'",
                        "info", account_name=account_name)
    return True


# ---------------------------------------------------------------------------
# Registration / login
# ---------------------------------------------------------------------------

def _solve_turnstile(proxy: Optional[str]) -> Optional[str]:
    """Решает Cloudflare Turnstile. Прокси для solver-сервиса — MAIN_PROXY
    (см. AGENTS.md §12.2). Если у юзера нет API-ключа, manager сам
    предупредит — возвращаем None."""
    captcha_proxy = (MAIN_PROXY or "").strip() or None
    mgr = CaptchaManager(proxy=captcha_proxy)
    if not mgr.is_available:
        return None
    return mgr.solve_turnstile(
        sitekey=MIDAS_TURNSTILE_SITEKEY,
        pageurl=MIDAS_SITE_URL,
    )


def _ensure_registered(api: MidasClient, account, nickname: str,
                       address: str, idx: int, total: int,
                       account_name: Optional[str]) -> bool:
    """Регистрирует/логинит кошелёк, кладёт JWT в api + БД.
    Возвращает True если в результате api.token заполнен."""
    wallet = db.get_wallet(address) or {}

    # Сначала пробуем получить пользователя — если уже есть, переходим к login.
    # check_wallet() для зарегистрированного юзера сразу выдаёт accessToken,
    # поэтому отдельный login не нужен — просто фиксируем JWT.
    try:
        info = api.check_wallet(address)
        already = bool(info) and (
            bool(info.get("registered"))
            or bool(info.get("accessToken"))
            or bool(info.get("user"))
        )
    except MidasApiError as e:
        log_wallet_task(
            address, idx, total,
            f"⚠ check_wallet error: {e}",
            "warning", account_name=account_name,
        )
        already = bool(wallet.get("registered"))
        info = {}

    if already and api.token:
        log_wallet_task(
            address, idx, total,
            "🔓 уже зарегистрирован · JWT получен из /auth/wallet",
            "info", account_name=account_name,
        )
        db.update_wallet(address, registered=1, jwt_token=api.token,
                         jwt_obtained_at=time.time())
        return True

    # nonce + signature нужны и для register, и для login
    try:
        nonce_data = api.get_nonce(address)
    except MidasApiError as e:
        log_wallet_task(
            address, idx, total,
            f"❌ get_nonce failed: {e}",
            "error", account_name=account_name,
        )
        db.update_wallet(address, error_message=f"nonce: {str(e)[:300]}")
        return False
    message = nonce_data.get("message")
    if not message:
        log_wallet_task(
            address, idx, total,
            f"❌ /auth/nonce: пустой message ({nonce_data})",
            "error", account_name=account_name,
        )
        return False

    # eth_account: Account.key — HexBytes, .hex() даёт '0x...'
    try:
        pk_hex = account.key.hex()
    except Exception:
        pk_hex = "0x" + account._private_key.hex()  # type: ignore[attr-defined]
    if not pk_hex.startswith("0x"):
        pk_hex = "0x" + pk_hex
    signature = mc.sign_login_message(pk_hex, message)

    if already:
        log_wallet_task(
            address, idx, total,
            "🔓 уже зарегистрирован — пробуем login",
            "info", account_name=account_name,
        )
        try:
            api.login(wallet_address=address, signature=signature,
                      message=message)
        except MidasApiError as e:
            # Бывает что сервер не принимает login, но register идемпотентен.
            log_wallet_task(
                address, idx, total,
                f"⚠ login failed: {e} · пробуем register заново",
                "warning", account_name=account_name,
            )
            already = False

    if not already:
        # Решаем капчу для register
        log_wallet_task(
            address, idx, total,
            "🧩 решаем Cloudflare Turnstile",
            "info", account_name=account_name,
        )
        token = _solve_turnstile(None)
        if not token:
            log_wallet_task(
                address, idx, total,
                "❌ captcha solver не вернул токен (проверь CAPTCHA_SERVICE)",
                "error", account_name=account_name,
            )
            db.update_wallet(address,
                             error_message="captcha solver unavailable")
            return False
        try:
            data = api.register(
                wallet_address=address, signature=signature, message=message,
                nickname=nickname, captcha_token=token,
            )
        except MidasApiError as e:
            msg = str(e)
            lc = msg.lower()
            # Сервер видит другой wallet или check_wallet врал — пробуем login.
            if ("already" in lc and "register" in lc) or "exist" in lc:
                log_wallet_task(
                    address, idx, total,
                    "🔓 сервер: already registered · переходим на login",
                    "info", account_name=account_name,
                )
                try:
                    api.login(wallet_address=address,
                              signature=signature, message=message)
                except MidasApiError as e2:
                    log_wallet_task(
                        address, idx, total,
                        f"❌ register+login оба failed: register={e} · login={e2}",
                        "error", account_name=account_name,
                    )
                    db.update_wallet(address,
                                     error_message=f"login: {str(e2)[:300]}")
                    return False
                if not api.token:
                    log_wallet_task(
                        address, idx, total,
                        "❌ login не вернул JWT",
                        "error", account_name=account_name,
                    )
                    return False
                log_wallet_task(
                    address, idx, total,
                    "✅ login после register-fallback",
                    "success", account_name=account_name,
                )
                db.update_wallet(
                    address, registered=1,
                    jwt_token=api.token, jwt_obtained_at=time.time(),
                    error_message=None,
                )
                return True
            log_wallet_task(
                address, idx, total,
                f"❌ register failed: {e}",
                "error", account_name=account_name,
            )
            db.update_wallet(address, error_message=f"register: {str(e)[:300]}")
            return False
        log_wallet_task(
            address, idx, total,
            f"✅ зарегистрирован · nickname='{nickname}'",
            "success", account_name=account_name,
        )
        db.update_wallet(
            address, registered=1,
            jwt_token=api.token, jwt_obtained_at=time.time(),
            error_message=None,
        )
    else:
        db.update_wallet(
            address, registered=1,
            jwt_token=api.token, jwt_obtained_at=time.time(),
        )

    return bool(api.token)


# ---------------------------------------------------------------------------
# Faucets
# ---------------------------------------------------------------------------

def _maybe_faucet_usdc(api: MidasClient, address: str, idx: int, total: int,
                      account_name: Optional[str]) -> None:
    w = db.get_wallet(address) or {}
    last = float(w.get("last_usdc_faucet_at") or 0)
    if last and (time.time() - last) < MIDAS_FAUCET_USDC_COOLDOWN_SEC:
        remain = int(MIDAS_FAUCET_USDC_COOLDOWN_SEC - (time.time() - last))
        log_wallet_task(
            address, idx, total,
            f"⏭ USDC faucet · кулдаун ещё {remain//60}m {remain%60}s",
            "info", account_name=account_name,
        )
        return
    try:
        resp = api.faucet_usdc(address)
        db.log_faucet_claim(address, "usdc", "success",
                            response=json.dumps(resp)[:500])
        db.update_wallet(address, last_usdc_faucet_at=time.time())
        log_wallet_task(
            address, idx, total,
            "💰 USDC faucet · success",
            "success", account_name=account_name,
        )
    except MidasApiError as e:
        msg = str(e)
        # cooldown — это не fatal, просто пишем и идём дальше
        lc = msg.lower()
        if "cooldown" in lc or "too soon" in lc or "wait" in lc:
            db.log_faucet_claim(address, "usdc", "cooldown",
                                error_message=msg[:300])
            db.update_wallet(address, last_usdc_faucet_at=time.time())
            log_wallet_task(
                address, idx, total,
                f"⏭ USDC faucet · сервер cooldown: {msg}",
                "info", account_name=account_name,
            )
        else:
            db.log_faucet_claim(address, "usdc", "failed",
                                error_message=msg[:300])
            log_wallet_task(
                address, idx, total,
                f"⚠ USDC faucet failed: {msg}",
                "warning", account_name=account_name,
            )


def _maybe_faucet_native(api: MidasClient, address: str, proxy: Optional[str],
                        idx: int, total: int,
                        account_name: Optional[str]) -> None:
    # Если на балансе уже достаточно нативки — не зовём faucet.
    try:
        bal_wei = mc.get_native_balance_wei(address, proxy)
    except Exception as e:  # noqa: BLE001
        log_wallet_task(
            address, idx, total,
            f"⚠ native balance fetch failed: {e}",
            "warning", account_name=account_name,
        )
        bal_wei = 0
    if bal_wei >= int(MIDAS_NATIVE_SUFFICIENT_BALANCE * 10**18):
        log_wallet_task(
            address, idx, total,
            f"⏭ zkLTC faucet · баланса хватает ({bal_wei/1e18:.4f})",
            "info", account_name=account_name,
        )
        return
    w = db.get_wallet(address) or {}
    last = float(w.get("last_native_faucet_at") or 0)
    if last and (time.time() - last) < MIDAS_FAUCET_NATIVE_COOLDOWN_SEC:
        remain = int(MIDAS_FAUCET_NATIVE_COOLDOWN_SEC - (time.time() - last))
        log_wallet_task(
            address, idx, total,
            f"⏭ zkLTC faucet · кулдаун ещё {remain//3600}h {(remain%3600)//60}m",
            "info", account_name=account_name,
        )
        return
    try:
        resp = api.faucet_native(address)
        db.log_faucet_claim(address, "native", "success",
                            response=json.dumps(resp)[:500])
        db.update_wallet(address, last_native_faucet_at=time.time())
        log_wallet_task(
            address, idx, total,
            "💰 zkLTC faucet · success",
            "success", account_name=account_name,
        )
    except MidasApiError as e:
        msg = str(e); lc = msg.lower()
        if "cooldown" in lc or "too soon" in lc or "wait" in lc:
            db.log_faucet_claim(address, "native", "cooldown",
                                error_message=msg[:300])
            db.update_wallet(address, last_native_faucet_at=time.time())
            log_wallet_task(
                address, idx, total,
                f"⏭ zkLTC faucet · сервер cooldown: {msg}",
                "info", account_name=account_name,
            )
        else:
            db.log_faucet_claim(address, "native", "failed",
                                error_message=msg[:300])
            log_wallet_task(
                address, idx, total,
                f"⚠ zkLTC faucet failed: {msg}",
                "warning", account_name=account_name,
            )


# ---------------------------------------------------------------------------
# Check-in
# ---------------------------------------------------------------------------

def _maybe_checkin(api: MidasClient, address: str, idx: int, total: int,
                  account_name: Optional[str]) -> None:
    if not MIDAS_CHECKIN_ENABLED:
        return
    w = db.get_wallet(address) or {}
    today = _today_utc()
    if (w.get("last_checkin_day") or "") == today:
        log_wallet_task(
            address, idx, total,
            f"⏭ check-in · уже сделан сегодня ({today})",
            "info", account_name=account_name,
        )
        return
    try:
        resp = api.checkin()
        streak_v = None
        if isinstance(resp, dict):
            streak_v = (resp.get("count") or resp.get("streak")
                        or resp.get("currentStreak") or resp.get("days"))
        db.log_checkin(address, "success",
                       streak=int(streak_v) if isinstance(streak_v, (int, float)) else None,
                       response=json.dumps(resp)[:500])
        db.update_wallet(address, last_checkin_at=time.time(),
                         last_checkin_day=today)
        log_wallet_task(
            address, idx, total,
            f"✅ check-in · streak={streak_v}",
            "success", account_name=account_name,
        )
    except MidasApiError as e:
        msg = str(e); lc = msg.lower()
        if ("already" in lc or "done" in lc or "checked" in lc
                or "cooldown" in lc):
            db.log_checkin(address, "already", error_message=msg[:300])
            db.update_wallet(address, last_checkin_at=time.time(),
                             last_checkin_day=today)
            log_wallet_task(
                address, idx, total,
                f"⏭ check-in · уже сделан (сервер): {msg}",
                "info", account_name=account_name,
            )
        else:
            db.log_checkin(address, "failed", error_message=msg[:300])
            log_wallet_task(
                address, idx, total,
                f"⚠ check-in failed: {msg}",
                "warning", account_name=account_name,
            )


# ---------------------------------------------------------------------------
# Bets
# ---------------------------------------------------------------------------

def _filter_usdc_markets(markets: list[dict]) -> list[dict]:
    """Оставляем активные USDC-маркеты с TTL > MIDAS_MARKET_MIN_TTL_SEC."""
    out: list[dict] = []
    now = int(time.time())
    usdc_lc = MIDAS_USDC_ADDRESS.lower()
    for m in markets:
        if not isinstance(m, dict):
            continue
        # address маркета (контрактный) — основное поле API называется "market"
        addr = (m.get("market") or m.get("marketAddress")
                or m.get("market_address") or m.get("address")
                or m.get("contract") or m.get("contractAddress"))
        if not isinstance(addr, str) or not addr.startswith("0x") or len(addr) != 42:
            continue
        # collateralToken
        coll = (m.get("collateralToken") or m.get("collateral_token")
                or m.get("collateral"))
        if not isinstance(coll, str) or coll.lower() != usdc_lc:
            continue
        # status — оставляем только активные
        st = (m.get("status") or "").upper()
        if st and st not in ("ACTIVE", "OPEN", "TRADING"):
            continue
        # expiresAt
        exp = (m.get("expiresAt") or m.get("expires_at")
               or m.get("expiryDate"))
        try:
            exp_ts = int(float(exp)) if exp is not None else 0
        except Exception:
            exp_ts = 0
        if exp_ts > 0 and (exp_ts - now) < MIDAS_MARKET_MIN_TTL_SEC:
            continue
        out.append({"address": addr, "raw": m})
    return out


def _market_title(raw: dict) -> str:
    for k in ("question", "title", "name", "description"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:200]
    return ""


def _do_bets(api: MidasClient, account, proxy: Optional[str],
             idx: int, total: int, account_name: Optional[str]) -> None:
    address = account.address
    lo_n, hi_n = MIDAS_BETS_PER_WALLET
    n = random.randint(int(lo_n), int(hi_n))
    if n <= 0:
        return

    # 1. Получаем список маркетов
    try:
        markets = api.list_markets(sort_by="trending", page=1,
                                   limit=int(MIDAS_MARKETS_FETCH_LIMIT))
    except MidasApiError as e:
        log_wallet_task(
            address, idx, total,
            f"⚠ /markets failed: {e}",
            "warning", account_name=account_name,
        )
        return

    usdc_markets = _filter_usdc_markets(markets)
    if len(usdc_markets) < int(MIDAS_MIN_MARKETS_TO_BET):
        log_wallet_task(
            address, idx, total,
            f"⚠ USDC-маркетов мало ({len(usdc_markets)} < "
            f"{MIDAS_MIN_MARKETS_TO_BET}) — пропуск bet-phase",
            "warning", account_name=account_name,
        )
        return

    # 2. Балансы и резервы
    try:
        usdc_bal = mc.usdc_balance(address, proxy)
    except Exception as e:  # noqa: BLE001
        log_wallet_task(
            address, idx, total,
            f"⚠ usdc balance fetch failed: {e}",
            "warning", account_name=account_name,
        )
        return
    if usdc_bal <= 0:
        log_wallet_task(
            address, idx, total,
            "⚠ USDC balance = 0 — пропуск bet-phase",
            "warning", account_name=account_name,
        )
        return

    # 3. Обновим планируемое число ставок
    db.update_wallet(address, bets_planned=n)

    chosen: list[dict] = random.sample(usdc_markets, min(n, len(usdc_markets)))

    for bet_i, item in enumerate(chosen, 1):
        market_addr = item["address"]
        raw = item["raw"]
        try:
            _place_one_bet(api, account, proxy, market_addr, raw,
                           idx, total, account_name, bet_i, len(chosen))
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            log_wallet_task(
                address, idx, total,
                f"❌ bet#{bet_i}/{len(chosen)} unexpected: {e}",
                "error", account_name=account_name,
            )
        db.recompute_wallet_counters(address)
        if bet_i < len(chosen):
            lo, hi = MIDAS_SLEEP_BETWEEN_BETS
            time.sleep(random.uniform(float(lo), float(hi)))


def _place_one_bet(api: MidasClient, account, proxy: Optional[str],
                   market_addr: str, raw: dict,
                   idx: int, total: int, account_name: Optional[str],
                   bet_i: int, bet_total: int) -> None:
    address = account.address
    title = _market_title(raw)
    short_title = (title[:48] + "…") if len(title) > 50 else title

    # outcome_count из контракта (надёжнее, чем raw)
    try:
        oc = mc.market_outcome_count(market_addr, proxy)
    except mc.MarketError as e:
        log_wallet_task(
            address, idx, total,
            f"⚠ bet#{bet_i}/{bet_total} market={market_addr[:10]}… "
            f"outcomeCount failed: {e} · skip",
            "warning", account_name=account_name,
        )
        return
    if oc < 2:
        log_wallet_task(
            address, idx, total,
            f"⏭ bet#{bet_i}/{bet_total} outcomes={oc} · skip",
            "info", account_name=account_name,
        )
        return

    # native баланс должен покрыть газ
    try:
        native = mc.get_native_balance_wei(address, proxy)
    except Exception:
        native = 0
    if native < int(MIDAS_GAS_RESERVE_ZKLTC * 10**18):
        log_wallet_task(
            address, idx, total,
            f"⚠ bet#{bet_i}/{bet_total} мало native ({native/1e18:.5f} zkLTC) · skip",
            "warning", account_name=account_name,
        )
        return

    outcome = random.randint(0, oc - 1)
    lo_a, hi_a = MIDAS_BET_AMOUNT_USDC
    target_human = round(random.uniform(float(lo_a), float(hi_a)), 4)
    target_raw = mc.usdc_to_raw(target_human)
    # Жёсткий floor «минимальный размер сделки» из collateral-tokens ·
    # контракт ревертит всё ниже (0x613970e0). Берём с запасом 20%.
    floor = int(MIDAS_USDC_MIN_TRADE_RAW * 1.2)
    if target_raw < floor:
        target_raw = floor
        target_human = mc.raw_to_usdc(target_raw)

    # Проверим, что хватает USDC
    try:
        usdc_bal = mc.usdc_balance(address, proxy)
    except Exception:
        usdc_bal = 0
    if usdc_bal < target_raw:
        log_wallet_task(
            address, idx, total,
            f"⚠ bet#{bet_i}/{bet_total} USDC бал={mc.raw_to_usdc(usdc_bal):.3f} < "
            f"{target_human} · уменьшаю до 80% баланса",
            "warning", account_name=account_name,
        )
        target_raw = max(1, usdc_bal * 8 // 10)
        target_human = mc.raw_to_usdc(target_raw)
        if target_raw < int(MIDAS_USDC_MIN_TRADE_RAW * 1.1):
            log_wallet_task(
                address, idx, total,
                f"⏭ bet#{bet_i}/{bet_total} ниже минимума "
                f"(~{MIDAS_USDC_MIN_TRADE_RAW/10**MIDAS_USDC_DECIMALS:.2f} USDC) · skip",
                "info", account_name=account_name,
            )
            return

    # Создаём запись
    bet_id = db.insert_bet({
        "address": address, "market_address": market_addr,
        "market_title": title, "outcome_index": outcome,
        "amount_usdc_raw": target_raw,
        "amount_usdc_human": float(target_human),
    })

    # Quote shares
    try:
        shares, cost_raw = mc.quote_shares_for_target_usdc(
            market_addr, outcome, target_raw, proxy)
    except mc.MarketError as e:
        log_wallet_task(
            address, idx, total,
            f"⚠ bet#{bet_i}/{bet_total} quote failed: {e}",
            "warning", account_name=account_name,
        )
        db.update_bet(bet_id, status="failed", error_message=f"quote: {str(e)[:300]}")
        return
    # Если вычисленный cost < минимума — увеличим shares до порога.
    min_cost = int(MIDAS_USDC_MIN_TRADE_RAW * 1.1)
    if cost_raw < min_cost and shares > 0:
        scale = (min_cost * 110) // max(cost_raw, 1) // 100 + 1
        new_shares = max(shares * scale, shares + 1)
        try:
            new_cost = mc.market_purchase_cost(
                market_addr, [outcome], [new_shares], proxy)
        except mc.MarketError:
            new_cost = 0
        if new_cost >= min_cost:
            shares, cost_raw = new_shares, new_cost
    # max_cost — щедро поверх view-cost (alpha-fee может добавить накладных)
    max_cost = int(cost_raw * float(MIDAS_BET_MAX_COST_MULTIPLIER))
    # И всё равно не ниже floor’а мин-сделки.
    max_cost = max(max_cost, int(MIDAS_USDC_MIN_TRADE_RAW * 1.2))
    # Не выходим за баланс USDC.
    if max_cost > usdc_bal:
        max_cost = usdc_bal
    db.update_bet(bet_id, shares=str(shares), max_cost_raw=str(max_cost))

    label = (f"bet#{bet_i}/{bet_total} · {market_addr[:8]}… "
             f"o={outcome}/{oc} · {target_human:.3f} USDC "
             f"(cost={mc.raw_to_usdc(cost_raw):.3f}, "
             f"max={mc.raw_to_usdc(max_cost):.3f})")
    if short_title:
        label += f" · «{short_title}»"

    # 1) Approve USDC, если allowance мал
    try:
        allow = mc.usdc_allowance(address, market_addr, proxy)
    except Exception:
        allow = 0
    if allow < max_cost:
        try:
            ah, _ = mc.usdc_approve(
                account=account, spender=market_addr,
                amount_raw=max_cost,
                proxy=proxy,
            )
            db.update_bet(bet_id, approve_tx_hash=ah, status="approved",
                          attempts=1)
            log_wallet_task(
                address, idx, total,
                f"🔓 approve · {_short_tx(ah)}",
                "info", account_name=account_name,
            )
        except mc.MarketError as e:
            log_wallet_task(
                address, idx, total,
                f"❌ {label} approve failed: {e}",
                "error", account_name=account_name,
            )
            db.update_bet(bet_id, status="failed",
                          error_message=f"approve: {str(e)[:300]}")
            return

    # 2) Buy с ретраями
    db.update_bet(bet_id, status="sending", sent_at=time.time())
    last_err: Optional[str] = None
    for attempt in range(1, int(MIDAS_TX_ATTEMPTS) + 1):
        try:
            h, receipt = mc.market_buy(
                account=account, market_address=market_addr,
                outcomes=[outcome], amounts=[shares],
                max_cost_raw=max_cost, value_wei=0,
                proxy=proxy,
            )
        except mc.MarketError as e:
            last_err = str(e)
            log_wallet_task(
                address, idx, total,
                f"⚠ {label} attempt {attempt}/{MIDAS_TX_ATTEMPTS}: {e}",
                "warning", account_name=account_name,
            )
            if attempt < int(MIDAS_TX_ATTEMPTS):
                time.sleep(min(15, 3 * attempt))
            continue
        except Exception as e:  # noqa: BLE001
            last_err = f"unexpected: {e}"
            log_wallet_task(
                address, idx, total,
                f"⚠ {label} attempt {attempt}/{MIDAS_TX_ATTEMPTS}: {e}",
                "warning", account_name=account_name,
            )
            if attempt < int(MIDAS_TX_ATTEMPTS):
                time.sleep(min(15, 3 * attempt))
            continue
        gas_used = int(receipt.get("gasUsed") or 0)
        db.update_bet(bet_id, status="confirmed", buy_tx_hash=h,
                      gas_used=gas_used, confirmed_at=time.time(),
                      error_message=None)
        log_wallet_task(
            address, idx, total,
            f"✅ {label} · buy={_short_tx(h)} · gas={gas_used}",
            "success", account_name=account_name,
        )
        return

    db.update_bet(bet_id, status="failed",
                  error_message=(last_err or "unknown")[:500])
    log_wallet_task(
        address, idx, total,
        f"❌ {label} failed после {MIDAS_TX_ATTEMPTS} попыток: {last_err}",
        "error", account_name=account_name,
    )


# ---------------------------------------------------------------------------
# Main per-wallet entrypoint
# ---------------------------------------------------------------------------

def process_wallet(record: dict, idx: int, total: int) -> None:
    account = _account_from_record(record)
    if account is None:
        return
    address = account.address
    account_name = record.get("name") or None
    proxy = _proxy_of(record)
    reserve_proxy = _reserve_proxy_of(record)

    # план: nickname / запись в БД
    plan_wallet(record, idx, total)
    w = db.get_wallet(address) or {}
    nickname = w.get("nickname") or NicknameGenerator().generate_nickname()
    if not w.get("nickname"):
        db.update_wallet(address, nickname=nickname)

    api = _new_api_client(proxy, reserve_proxy)
    # пробуем переиспользовать JWT (короткое окно, без проверки exp)
    if w.get("jwt_token") and w.get("jwt_obtained_at"):
        if (time.time() - float(w["jwt_obtained_at"])) < 6 * 3600:
            api.set_token(str(w["jwt_token"]))

    # 1) Регистрация (или login)
    if not _ensure_registered(api, account, nickname, address, idx, total,
                              account_name):
        log_wallet_task(
            address, idx, total,
            "❌ не удалось получить JWT — дальнейшие шаги пропущены",
            "error", account_name=account_name,
        )
        db.recompute_wallet_counters(address)
        return

    # Небольшая пауза после получения JWT — серверу нужно время
    # прописать юзера в БД, иначе faucet/checkin падают с 'Something went wrong'.
    time.sleep(random.uniform(1.5, 3.5))

    # 2) Faucets
    _maybe_faucet_usdc(api, address, idx, total, account_name)
    _maybe_faucet_native(api, address, proxy, idx, total, account_name)

    # 3) Check-in
    _maybe_checkin(api, address, idx, total, account_name)

    # 4) Bets
    try:
        _do_bets(api, account, proxy, idx, total, account_name)
    except KeyboardInterrupt:
        raise
    except Exception as e:  # noqa: BLE001
        log_wallet_task(
            address, idx, total,
            f"❌ bet-phase unexpected: {e}",
            "error", account_name=account_name,
        )

    final = db.recompute_wallet_counters(address)
    if final["planned"] > 0 and final["status"] == "completed":
        log_wallet_task(
            address, idx, total,
            f"🎯 готово · ставок {final['completed']}/{final['planned']}",
            "success", account_name=account_name,
        )
    elif final["planned"] > 0 and final["status"] == "failed":
        log_wallet_task(
            address, idx, total,
            f"⚠ завершено с ошибками · "
            f"{final['completed']} ok / {final['failed']} fail",
            "warning", account_name=account_name,
        )
    else:
        log_wallet_task(
            address, idx, total,
            f"📋 цикл завершён · ставок не было",
            "info", account_name=account_name,
        )


# ---------------------------------------------------------------------------
# Check-in only loop (streak holder)
# ---------------------------------------------------------------------------

def _ensure_login_only(api: MidasClient, account, address: str,
                       idx: int, total: int,
                       account_name: Optional[str]) -> bool:
    """Облегчённый login без register (для check-in loop).

    Бэкенд Midas выдаёт accessToken прямо в ответе POST /auth/wallet
    для уже зарегистрированных кошельков — отдельного login-эндпоинта нет.
    Кэшируем JWT в БД на 6 часов, потом обновляем через check_wallet.
    """
    _ = account  # signature больше не нужна
    w = db.get_wallet(address) or {}
    if w.get("jwt_token") and w.get("jwt_obtained_at"):
        if (time.time() - float(w["jwt_obtained_at"])) < 6 * 3600:
            api.set_token(str(w["jwt_token"]))
            return True
    try:
        data = api.check_wallet(address)
    except MidasApiError as e:
        log_wallet_task(address, idx, total,
                        f"❌ check_wallet failed: {e}",
                        "error", account_name=account_name)
        return False
    if not data or not data.get("accessToken"):
        log_wallet_task(address, idx, total,
                        "⏭ не зарегистрирован на Midas · "
                        "пропускаем (запусти full pipeline сначала)",
                        "warning", account_name=account_name)
        return False
    if not api.token:
        api.set_token(str(data["accessToken"]))
    db.update_wallet(address, registered=1, jwt_token=api.token,
                     jwt_obtained_at=time.time())
    return True


def checkin_only_wallet(record: dict, idx: int, total: int) -> bool:
    """Один проход чек-ина для одного кошелька. Возвращает True, если
    чек-ин выполнен сегодня (либо был сделан ранее в этот UTC-день)."""
    account = _account_from_record(record)
    if account is None:
        return False
    address = account.address
    account_name = record.get("name") or None
    proxy = _proxy_of(record)
    reserve_proxy = _reserve_proxy_of(record)

    db.upsert_wallet(address, name=account_name)
    w = db.get_wallet(address) or {}
    today = _today_utc()
    if (w.get("last_checkin_day") or "") == today:
        log_wallet_task(address, idx, total,
                        f"⏭ check-in уже сегодня ({today})",
                        "info", account_name=account_name)
        return True

    api = _new_api_client(proxy, reserve_proxy)
    if not _ensure_login_only(api, account, address, idx, total, account_name):
        return False
    _maybe_checkin(api, address, idx, total, account_name)
    w2 = db.get_wallet(address) or {}
    return (w2.get("last_checkin_day") or "") == today


def _seconds_until_next_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    nxt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # next midnight = today midnight + 1 day
    from datetime import timedelta
    nxt = nxt + timedelta(days=1)
    return max(1, int((nxt - now).total_seconds()))


def run_checkin_streak_loop(records: list[dict], threads: int,
                            should_stop) -> None:
    """Бесконечный цикл «держим стрик»: делаем check-in каждому кошельку
    раз в UTC-сутки. Состояние и история — в БД.

    `should_stop()` — callable, возвращающий True для досрочного выхода.
    `threads`        — параллелизм одного прохода.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    total = len(records)
    log_simple(f"🔁 check-in loop: {total} кошельков · threads={threads}",
               "info")
    iter_n = 0
    while True:
        if should_stop():
            log_simple("⚠ check-in loop остановлен пользователем", "warning")
            return
        iter_n += 1
        today = _today_utc()
        # фильтр: только те, у кого last_checkin_day != today
        pending: list[tuple[int, dict]] = []
        for i, rec in enumerate(records, 1):
            pk = (rec.get("private_key") or "").strip()
            if not pk:
                continue
            try:
                addr = mc.account_from_private_key(pk).address
            except Exception:
                continue
            w = db.get_wallet(addr) or {}
            if (w.get("last_checkin_day") or "") != today:
                pending.append((i, rec))
        done_today = total - len(pending)
        log_simple(
            f"📊 iter#{iter_n} · {done_today}/{total} уже сделали check-in "
            f"сегодня ({today}) · обрабатываем {len(pending)}",
            "info",
        )
        if pending:
            t = max(1, min(int(threads), len(pending)))
            with ThreadPoolExecutor(max_workers=t,
                                    thread_name_prefix="midas-checkin") as ex:
                futs = [ex.submit(checkin_only_wallet, rec, i, total)
                        for i, rec in pending]
                try:
                    for fut in as_completed(futs):
                        if should_stop():
                            break
                        try:
                            fut.result()
                        except Exception as e:  # noqa: BLE001
                            log_simple(f"⚠ checkin worker: {e}", "warning")
                except KeyboardInterrupt:
                    for f in futs:
                        f.cancel()
                    log_simple(
                        "⚠ check-in loop прерван (Ctrl+C) — состояние в БД",
                        "warning",
                    )
                    return
        # Сон до следующего UTC-midnight + лёгкий jitter
        sleep_s = _seconds_until_next_utc_midnight() + random.randint(30, 300)
        h = sleep_s // 3600
        m = (sleep_s % 3600) // 60
        log_simple(
            f"💤 жду до следующего UTC-дня · ~{h}h {m}m (затем повторяю)",
            "info",
        )
        # дробим сон чтобы реагировать на should_stop()
        step = 5
        slept = 0
        while slept < sleep_s:
            if should_stop():
                log_simple(
                    "⚠ check-in loop остановлен во время ожидания",
                    "warning",
                )
                return
            time.sleep(step)
            slept += step

