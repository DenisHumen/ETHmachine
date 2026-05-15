"""ZNS.bio random-session worker.

Каждый кошелёк регистрирует random.randint(ZNS_OPS_PER_WALLET_RANGE) доменов.
- Имя: генерируется через modules.nickname_generator + sanitise [a-z0-9].
- Years: weighted random по ZNS_YEARS_WEIGHTS (по умолчанию 89/10/1).
- Цена: priceToRegister + priceToRenew*(years-1) (учитывая ZNS_PRICE_MULTIPLIER).
"""
from __future__ import annotations

import random
import re
import time
from typing import Optional

from config.modules.cfg_litvm_testnet import (
    ZNS_GAS_RESERVE,
    ZNS_MIN_NATIVE_BALANCE,
    ZNS_NAME_LENGTH_RANGE,
    ZNS_NAME_MAX_TRIES,
    ZNS_OPS_PER_WALLET_RANGE,
    ZNS_PRICE_MULTIPLIER,
    ZNS_REFERRAL_ADDRESS,
    ZNS_SLEEP_BETWEEN_OPS,
    ZNS_TLD,
    ZNS_TX_ATTEMPTS,
    ZNS_YEARS_WEIGHTS,
)
from config.modules.general_config import SHUFLE_ACCOUNTS
from modules.nickname_generator import NicknameGenerator
from modules.simple_logger import log_simple, log_wallet_task
from modules.litvm_testnet.zns_bio import database as db
from modules.litvm_testnet.zns_bio import zns_client as zc


_NAME_GEN = NicknameGenerator()
_ALLOWED_RE = re.compile(r"[^a-z0-9]")


def _short_tx(h: Optional[str]) -> str:
    if not h:
        return ""
    raw = h[2:] if h.startswith("0x") else h
    return f"{raw[:8]}…{raw[-6:]}" if len(raw) > 16 else raw


def _primary_proxy(rec: dict) -> Optional[str]:
    p = (rec.get("proxy") or "").strip()
    return p or None


def _reserve_proxy(rec: dict) -> Optional[str]:
    p = (rec.get("reserve_proxy") or "").strip()
    return p or None


def _proxy_chain(rec: dict) -> list[Optional[str]]:
    chain: list[Optional[str]] = []
    seen: set[str] = set()
    for p in (_primary_proxy(rec), _reserve_proxy(rec)):
        k = (p or "").strip()
        if k in seen:
            continue
        chain.append(p)
        seen.add(k)
    if not chain:
        chain = [None]
    return chain


def _account_from_record(rec: dict):
    pk = (rec.get("private_key") or "").strip()
    if not pk:
        return None
    try:
        return zc.account_from_private_key(pk)
    except Exception as e:
        log_simple(f"⚠ невалидный private_key: {e}", "warning")
        return None


def _native_balance(addr: str, rec: dict) -> int:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(rec):
        try:
            return zc.get_native_balance_wei(addr, proxy)
        except Exception as e:
            last_err = e
    raise zc.ZnsError(f"native balance fetch failed: {last_err}")


def _sanitize_name(raw: str, min_len: int, max_len: int) -> str:
    s = (raw or "").lower()
    s = _ALLOWED_RE.sub("", s)
    if len(s) > max_len:
        s = s[:max_len]
    while len(s) < min_len:
        s += str(random.randint(0, 9))
    return s


def _pick_years() -> int:
    items = list(ZNS_YEARS_WEIGHTS.items())
    years = [int(k) for k, _ in items]
    weights = [int(v) for _, v in items]
    return int(random.choices(years, weights=weights, k=1)[0])


def _generate_free_name(proxy: Optional[str], min_len: int,
                       max_len: int, max_tries: int) -> Optional[str]:
    for _ in range(max_tries):
        try:
            raw = _NAME_GEN.generate_nickname()
        except Exception:
            raw = ""
        name = _sanitize_name(raw, min_len, max_len)
        if not name:
            continue
        if db.domain_already_used(f"{name}.{ZNS_TLD}"):
            continue
        try:
            if zc.is_name_available(name, proxy=proxy):
                return name
        except Exception:
            continue
    return None


def run_random_session(records: list[dict]) -> dict:
    """Каждый кошелёк регистрирует random.randint(ops_lo..ops_hi) доменов."""
    db.init_database()

    eligible = [r for r in records if (r.get("private_key") or "").strip()]
    if not eligible:
        log_simple("Нет кошельков с private_key", "error")
        return {"ops": 0, "ok": 0, "failed": 0, "skipped": 0}

    wallets = list(eligible)
    if SHUFLE_ACCOUNTS:
        random.shuffle(wallets)

    ops_lo, ops_hi = ZNS_OPS_PER_WALLET_RANGE
    per_wallet_plan = [random.randint(int(ops_lo), int(ops_hi))
                       for _ in wallets]
    total_ops = sum(per_wallet_plan)

    log_simple(
        f"🪪 ZNS.bio session: {len(wallets)} кошельков · "
        f"{total_ops} регистраций ({ops_lo}..{ops_hi} на кошелёк) · "
        f"TLD=.{ZNS_TLD}",
        "info",
    )

    min_native_wei = int(float(ZNS_MIN_NATIVE_BALANCE) * 1e18)
    gas_reserve_wei = int(float(ZNS_GAS_RESERVE) * 1e18)
    sleep_lo, sleep_hi = ZNS_SLEEP_BETWEEN_OPS
    attempts_per_op = max(1, int(ZNS_TX_ATTEMPTS))
    min_len, max_len = ZNS_NAME_LENGTH_RANGE

    ok = failed = skipped = ops_done = 0
    interrupted = False
    op_idx = 0

    try:
        for wallet_idx, record in enumerate(wallets, 1):
            ops_for_wallet = per_wallet_plan[wallet_idx - 1]
            if ops_for_wallet <= 0:
                continue
            account = _account_from_record(record)
            if account is None:
                continue
            addr = account.address
            name = record.get("name") or None

            try:
                native_wei = _native_balance(addr, record)
            except zc.ZnsError as e:
                op_idx += 1
                log_wallet_task(addr, op_idx, total_ops,
                                f"⚠ native balance: {e}", "warning",
                                account_name=name)
                continue
            if native_wei < min_native_wei:
                op_idx += 1
                log_wallet_task(
                    addr, op_idx, total_ops,
                    f"⏭ native {native_wei/1e18:.6f} < min "
                    f"{ZNS_MIN_NATIVE_BALANCE} — skip wallet",
                    "warning", account_name=name,
                )
                continue

            for w_op in range(ops_for_wallet):
                op_idx += 1
                try:
                    proxy = _primary_proxy(record)
                    # 1. выбираем срок аренды
                    years = _pick_years()

                    # 2. ищем свободное имя
                    domain_name = _generate_free_name(
                        proxy, min_len, max_len, int(ZNS_NAME_MAX_TRIES),
                    )
                    if not domain_name:
                        skipped += 1
                        log_wallet_task(
                            addr, op_idx, total_ops,
                            "⏭ не удалось подобрать свободное имя",
                            "warning", account_name=name,
                        )
                        continue
                    full_name = f"{domain_name}.{ZNS_TLD}"

                    # 3. считаем цену
                    try:
                        base_price = zc.compute_price_wei(
                            domain_name, years, proxy=proxy)
                    except Exception as e:
                        log_wallet_task(
                            addr, op_idx, total_ops,
                            f"⚠ price fetch failed: {e}",
                            "warning", account_name=name,
                        )
                        failed += 1
                        continue
                    price_wei = int(base_price * float(ZNS_PRICE_MULTIPLIER))

                    spendable = max(0, native_wei - gas_reserve_wei)
                    if price_wei > spendable:
                        skipped += 1
                        log_wallet_task(
                            addr, op_idx, total_ops,
                            f"⏭ не хватает на {years}y "
                            f"{full_name}: нужно {price_wei/1e18:.6f}, "
                            f"есть {spendable/1e18:.6f}",
                            "warning", account_name=name,
                        )
                        # пробуем 1 год если выбрали 2/3
                        if years > 1:
                            try:
                                p1 = zc.compute_price_wei(
                                    domain_name, 1, proxy=proxy)
                                if int(p1 * float(ZNS_PRICE_MULTIPLIER)) \
                                        <= spendable:
                                    years = 1
                                    price_wei = int(
                                        p1 * float(ZNS_PRICE_MULTIPLIER))
                                    log_wallet_task(
                                        addr, op_idx, total_ops,
                                        f"↩️ снижаем до 1 года: "
                                        f"{price_wei/1e18:.6f} zkLTC",
                                        "info", account_name=name,
                                    )
                                else:
                                    continue
                            except Exception:
                                continue
                        else:
                            continue

                    reg_id = db.insert_registration(
                        wallet_address=addr, wallet_name=name,
                        domain_name=domain_name, tld=ZNS_TLD,
                        years=years, price_wei=price_wei,
                        referral=ZNS_REFERRAL_ADDRESS, credits=0,
                    )

                    log_wallet_task(
                        addr, op_idx, total_ops,
                        f"📤 REGISTER {full_name} · {years}y · "
                        f"price={price_wei/1e18:.6f} zkLTC",
                        "info", account_name=name,
                    )

                    tx_hash: Optional[str] = None
                    receipt: Optional[dict] = None
                    token_id: Optional[int] = None
                    last_err: Optional[str] = None

                    for attempt in range(1, attempts_per_op + 1):
                        db.update_registration(
                            reg_id, status="sent", attempts=attempt,
                            sent_at=time.time())
                        try:
                            tx_hash, receipt, _paid, token_id = (
                                zc.register_domain(
                                    account=account, name=domain_name,
                                    years=years, referral=ZNS_REFERRAL_ADDRESS,
                                    credits_wei=0, price_wei=price_wei,
                                    proxy=proxy,
                                )
                            )
                            break
                        except zc.ZnsError as e:
                            last_err = str(e)
                            log_wallet_task(
                                addr, op_idx, total_ops,
                                f"⚠ attempt {attempt}/{attempts_per_op}: {e}",
                                "warning", account_name=name,
                            )
                            if attempt < attempts_per_op:
                                time.sleep(min(15, 3 * attempt))

                    if tx_hash is None or receipt is None:
                        db.update_registration(
                            reg_id, status="failed",
                            error_message=(last_err or "unknown")[:500],
                        )
                        failed += 1
                        log_wallet_task(
                            addr, op_idx, total_ops,
                            f"❌ {full_name} failed: {last_err}",
                            "error", account_name=name,
                        )
                    else:
                        gas_used = int(receipt.get("gasUsed") or 0)
                        db.update_registration(
                            reg_id, tx_hash=tx_hash, gas_used=gas_used,
                            token_id=(str(token_id)
                                      if token_id is not None else None),
                            status="arrived", confirmed_at=time.time(),
                        )
                        ok += 1
                        # обновим локальный баланс
                        try:
                            native_wei = _native_balance(addr, record)
                        except Exception:
                            native_wei = max(0, native_wei - price_wei
                                             - gas_used * 1_000_000)
                        log_wallet_task(
                            addr, op_idx, total_ops,
                            f"✅ {full_name} · tokenId={token_id} · "
                            f"tx={_short_tx(tx_hash)} · gas={gas_used}",
                            "success", account_name=name,
                        )

                    ops_done += 1
                    time.sleep(random.uniform(float(sleep_lo), float(sleep_hi)))

                except Exception as e:  # noqa: BLE001
                    log_wallet_task(
                        addr, op_idx, total_ops,
                        f"⚠ op error: {e}", "warning", account_name=name,
                    )
                    failed += 1

    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем", "warning")
        interrupted = True

    summary = {
        "ops": ops_done, "ok": ok, "failed": failed, "skipped": skipped,
        "interrupted": interrupted,
    }
    log_simple(
        f"🏁 ZNS session done · ok={ok} failed={failed} skipped={skipped}",
        "success" if not interrupted else "warning",
    )
    return summary
