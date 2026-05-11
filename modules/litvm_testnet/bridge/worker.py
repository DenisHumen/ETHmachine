"""LiteForge bridge worker — plan + execute + auto-finalize per-wallet.

Сценарии:
  L1→L2: approve → deposit → polling баланса L2 → dst_status='arrived'.
  L2→L1: withdraw на L2 → dst_status='submitted' (обязательная фаза)
         → фаза финализации (Outbox.executeTransaction) на L1.
           Если выполняется сразу — dst_status='finalized'.
           Если вывод ещё не готов (challenge window) — остаётся
           submitted, и повторяется при следующих запусках модуля.

Resumable: каждый шаг апсертится в БД, interrupt не теряет прогресс.
"""
from __future__ import annotations

import random
import time
from typing import Optional

from eth_account import Account

from config.modules.cfg_litvm_testnet import (
    LITVM_BRIDGE_AMOUNT_PCT_RANGE,
    LITVM_BRIDGE_ARRIVAL_TIMEOUT_SEC,
    LITVM_BRIDGE_AUTO_FINALIZE_L1,
    LITVM_BRIDGE_BALANCE_POLL_INTERVAL,
    LITVM_BRIDGE_FINALIZE_RETRY_INTERVAL_SEC,
    LITVM_BRIDGE_GAS_RESERVE_ETH,
    LITVM_BRIDGE_GAS_RESERVE_ZKLTC,
    LITVM_BRIDGE_MIN_AMOUNT_ZKLTC,
    LITVM_BRIDGE_PRIMARY_DIRECTION,
    LITVM_BRIDGE_RETURN_ENABLED,
    LITVM_BRIDGE_RETURN_PCT,
    LITVM_BRIDGE_SLEEP_BETWEEN_TX,
    LITVM_BRIDGE_TX_COUNT_RANGE,
)
from modules.litvm_testnet.bridge import bridge_client as bc
from modules.litvm_testnet.bridge import database as db
from modules.simple_logger import log_simple, log_wallet_task


_VALID_DIRECTIONS = ("l1_to_l2", "l2_to_l1")


def _primary_direction() -> str:
    d = str(LITVM_BRIDGE_PRIMARY_DIRECTION or "l2_to_l1").lower()
    return d if d in _VALID_DIRECTIONS else "l2_to_l1"


def _opposite(direction: str) -> str:
    return "l1_to_l2" if direction == "l2_to_l1" else "l2_to_l1"


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


def _proxy_of(record: dict) -> Optional[str]:
    return (record.get("proxy") or "").strip() or None


def _account_from_record(record: dict):
    pk = (record.get("private_key") or "").strip()
    if not pk:
        return None
    if not pk.startswith("0x"):
        pk = "0x" + pk
    return Account.from_key(pk)


def _pct_of(balance_wei: int, pct: float) -> int:
    """Целочисленный процент от balance_wei (без потери точности)."""
    return int(balance_wei * pct) // 100


# ---------------------------------------------------------------------------
# planner
# ---------------------------------------------------------------------------

def _source_balance_wei(direction: str, address: str, proxy: Optional[str]) -> int:
    """L1 zkLTC ERC-20 для l1_to_l2, L2 native для l2_to_l1."""
    if direction == "l1_to_l2":
        return bc.l1_zkltc_balance_wei(address, proxy)
    return bc.l2_native_balance_wei(address, proxy)


def _source_label(direction: str) -> str:
    return "L1 zkLTC" if direction == "l1_to_l2" else "L2 zkLTC"


def _src_gas_reserve_wei(direction: str) -> int:
    """Резерв gas-токена ИСХОДНОЙ сети. Для L1→L2 газ платится Sepolia ETH
    (отдельный токен, не учитываем при расчёте % от zkLTC). Для L2→L1 газ
    платится тем же native zkLTC, поэтому реально нужно вычесть из баланса."""
    if direction == "l2_to_l1":
        return int(LITVM_BRIDGE_GAS_RESERVE_ZKLTC * 1e18)
    return 0  # L1: gas в ETH, не пересекается с zkLTC балансом


def plan_wallet(record: dict, idx: int, total: int) -> bool:
    """Создаёт N tx-задач для кошелька в направлении PRIMARY_DIRECTION.
    Если у кошелька уже есть план — НЕ перепланируем (resume).
    Возвращает True если есть что делать."""
    account = _account_from_record(record)
    if account is None:
        return False
    address = account.address
    account_name = record.get("name") or None
    proxy = _proxy_of(record)
    direction = _primary_direction()
    src_label = _source_label(direction)

    db.upsert_wallet(
        address, account_name,
        direction=direction, return_enabled=bool(LITVM_BRIDGE_RETURN_ENABLED),
    )

    existing = db.list_tx_for_wallet(address, direction)
    if existing:
        log_wallet_task(
            address, idx, total,
            f"♻️ план уже есть: {len(existing)} tx ({direction}) — продолжаем (resume)",
            "info", account_name=account_name,
        )
        return True

    # Баланс источника
    try:
        src_bal = _source_balance_wei(direction, address, proxy)
    except bc.BridgeError as e:
        log_wallet_task(address, idx, total,
                        f"❌ не удалось снять баланс {src_label}: {e}",
                        "error", account_name=account_name)
        db.update_wallet(address, status="failed",
                         error_message=f"plan: src balance fetch: {e}")
        return False

    reserve = _src_gas_reserve_wei(direction)
    spendable = max(0, src_bal - reserve)
    if spendable <= 0:
        log_wallet_task(
            address, idx, total,
            f"⏭ {src_label} баланс {src_bal/1e18:.6f} ≤ резерв {reserve/1e18:.6f} — пропускаю",
            "warning", account_name=account_name,
        )
        db.update_wallet(address, status="failed",
                         error_message=f"empty {src_label} balance (after reserve)")
        return False

    min_wei = int(LITVM_BRIDGE_MIN_AMOUNT_ZKLTC * 1e18)
    pct_lo, pct_hi = float(LITVM_BRIDGE_AMOUNT_PCT_RANGE[0]), float(LITVM_BRIDGE_AMOUNT_PCT_RANGE[1])
    cnt_lo, cnt_hi = int(LITVM_BRIDGE_TX_COUNT_RANGE[0]), int(LITVM_BRIDGE_TX_COUNT_RANGE[1])

    n = random.randint(cnt_lo, cnt_hi)
    sim_balance = spendable
    planned = []
    for i in range(1, n + 1):
        pct = round(random.uniform(pct_lo, pct_hi), 4)
        amount = _pct_of(sim_balance, pct)
        if amount < min_wei:
            break
        planned.append((i, pct, amount))
        sim_balance -= amount

    if not planned:
        log_wallet_task(
            address, idx, total,
            f"⏭ {src_label} {src_bal/1e18:.6f} слишком мал для {pct_lo}-{pct_hi}% "
            f"(min={LITVM_BRIDGE_MIN_AMOUNT_ZKLTC})",
            "warning", account_name=account_name,
        )
        db.update_wallet(address, status="failed",
                         error_message="balance below min_amount")
        return False

    for i, pct, amount in planned:
        db.insert_tx_task(
            address=address, tx_index=i, direction=direction,
            amount_wei=amount, amount_human=amount / 1e18, pct=pct,
        )

    db.update_wallet(address, status="planned",
                     planned_count=len(planned), error_message=None)
    total_human = sum(a for _, _, a in planned) / 1e18
    log_wallet_task(
        address, idx, total,
        f"📋 план: {len(planned)} tx {direction} · сумма {total_human:.6f} zkLTC "
        f"({pct_lo}-{pct_hi}% от {spendable/1e18:.6f})",
        "success", account_name=account_name,
    )
    return True


# ---------------------------------------------------------------------------
# executor — one tx
# ---------------------------------------------------------------------------

def _execute_l1_to_l2_tx(task: dict, account, proxy: Optional[str],
                         idx: int, total: int, account_name: Optional[str]) -> bool:
    """Выполняет одну L1→L2 tx-задачу. Возвращает True если completed."""
    address = account.address
    tx_id = int(task["id"])
    tx_index = int(task["tx_index"])
    amount_wei = int(task["amount_wei"])
    db.increment_attempts(tx_id)

    label = f"tx#{tx_index} · {amount_wei/1e18:.6f} zkLTC ({task['pct']:.2f}%)"
    log_wallet_task(address, idx, total, f"💱 {label} · старт",
                    "info", account_name=account_name)

    # Снимаем balance_before (источник — L1 zkLTC, dst — L2 native)
    try:
        src_before = bc.l1_zkltc_balance_wei(address, proxy)
        dst_before = bc.l2_native_balance_wei(address, proxy)
    except bc.BridgeError as e:
        log_wallet_task(address, idx, total,
                        f"❌ {label} · balance fetch failed: {e}",
                        "error", account_name=account_name)
        db.update_tx_task(tx_id, send_status="failed",
                          error_message=f"balance fetch: {str(e)[:300]}")
        return False
    db.update_tx_task(tx_id,
                      src_balance_before_wei=str(src_before),
                      dst_balance_before_wei=str(dst_before))

    if src_before < amount_wei:
        msg = (f"L1 баланс {src_before/1e18:.6f} меньше планируемой суммы "
               f"{amount_wei/1e18:.6f}")
        log_wallet_task(address, idx, total, f"❌ {label} · {msg}",
                        "error", account_name=account_name)
        db.update_tx_task(tx_id, send_status="failed", error_message=msg[:300])
        return False

    send_status = task.get("send_status") or "pending"

    # 1) approve (если не делали или allowance мал)
    if send_status in ("pending",):
        try:
            ah, rc = bc.send_l1_approve(account=account,
                                        amount_wei=amount_wei, proxy=proxy)
            if rc and rc.get("skipped"):
                log_wallet_task(address, idx, total,
                                f"🔓 {label} · allowance достаточен, approve не нужен",
                                "info", account_name=account_name)
                db.update_tx_task(tx_id, send_status="approved")
            else:
                log_wallet_task(address, idx, total,
                                f"🔓 {label} · approve tx={_short_tx(ah)}",
                                "success", account_name=account_name)
                db.update_tx_task(tx_id, send_status="approved",
                                  approve_tx_hash=ah)
        except bc.BridgeError as e:
            log_wallet_task(address, idx, total,
                            f"❌ {label} · approve failed: {e}",
                            "error", account_name=account_name)
            db.update_tx_task(tx_id, send_status="failed",
                              error_message=f"approve: {str(e)[:300]}")
            return False
        send_status = "approved"

    # 2) depositERC20
    if send_status in ("approved", "pending"):
        try:
            dh, _rc = bc.send_l1_deposit(account=account,
                                          amount_wei=amount_wei, proxy=proxy)
            log_wallet_task(address, idx, total,
                            f"📤 {label} · deposit tx={_short_tx(dh)} (Sepolia подтверждён)",
                            "success", account_name=account_name)
            db.update_tx_task(tx_id, send_status="confirmed",
                              src_tx_hash=dh,
                              src_balance_after_wei=str(
                                  bc.l1_zkltc_balance_wei(address, proxy)))
            send_status = "confirmed"
        except bc.BridgeError as e:
            log_wallet_task(address, idx, total,
                            f"❌ {label} · deposit failed: {e}",
                            "error", account_name=account_name)
            db.update_tx_task(tx_id, send_status="failed",
                              error_message=f"deposit: {str(e)[:300]}")
            return False

    # 3) Wait for L2 credit
    if send_status == "confirmed" and task.get("dst_status") != "arrived":
        log_wallet_task(
            address, idx, total,
            f"⏳ {label} · ждём L2 кредит до {_fmt_remaining(LITVM_BRIDGE_ARRIVAL_TIMEOUT_SEC)}",
            "info", account_name=account_name,
        )
        started = time.time()
        deadline = started + float(LITVM_BRIDGE_ARRIVAL_TIMEOUT_SEC)
        next_progress = time.time() + 90
        arrived = False
        new_balance = dst_before
        while time.time() < deadline:
            time.sleep(LITVM_BRIDGE_BALANCE_POLL_INTERVAL)
            try:
                cur = bc.l2_native_balance_wei(address, proxy)
            except bc.BridgeError:
                continue
            if cur > dst_before:
                # Допускаем, что L2 баланс мог увеличиться меньше чем на amount
                # (gas-fee на стороне inbox), но обычно для Orbit-deposit
                # кредит == полная сумма amount. Считаем «пришло» по строгому росту.
                new_balance = cur
                arrived = True
                break
            if time.time() >= next_progress:
                left = deadline - time.time()
                log_wallet_task(
                    address, idx, total,
                    f"⏳ {label} · ждём L2, осталось {_fmt_remaining(left)}",
                    "info", account_name=account_name,
                )
                next_progress = time.time() + 90

        elapsed = time.time() - started
        if arrived:
            delta = (new_balance - dst_before) / 1e18
            db.update_tx_task(tx_id, dst_status="arrived",
                              dst_balance_after_wei=str(new_balance),
                              dst_arrival_seconds=elapsed)
            log_wallet_task(
                address, idx, total,
                f"✅ {label} · +{delta:.6f} zkLTC на L2 за {_fmt_remaining(elapsed)}",
                "success", account_name=account_name,
            )
            return True
        else:
            db.update_tx_task(tx_id, dst_status="timeout",
                              error_message=f"L2 not credited within "
                                            f"{_fmt_remaining(LITVM_BRIDGE_ARRIVAL_TIMEOUT_SEC)}")
            log_wallet_task(
                address, idx, total,
                f"⚠ {label} · L2 кредит не пришёл за "
                f"{_fmt_remaining(LITVM_BRIDGE_ARRIVAL_TIMEOUT_SEC)} (deposit виден на Sepolia, "
                f"возможно увеличить таймаут)",
                "warning", account_name=account_name,
            )
            return False

    if task.get("dst_status") == "arrived":
        return True
    return False


# ---------------------------------------------------------------------------
# executor — L2 → L1 (ArbSys.withdrawEth)
# ---------------------------------------------------------------------------

def _execute_l2_to_l1_tx(task: dict, account, proxy: Optional[str],
                         idx: int, total: int, account_name: Optional[str]) -> bool:
    """Выполняет одну L2→L1 tx (ArbSys.withdrawEth на L2). После receipt
    ставим dst_status='submitted'; L1-финализация (Outbox.executeTransaction)
    делается автоматически отдельной фазой при последующих запусках модуля."""
    address = account.address
    tx_id = int(task["id"])
    tx_index = int(task["tx_index"])
    amount_wei = int(task["amount_wei"])
    db.increment_attempts(tx_id)

    label = f"tx#{tx_index} · {amount_wei/1e18:.6f} zkLTC ({task['pct']:.2f}%)"
    log_wallet_task(address, idx, total, f"💱 {label} · L2→L1 старт",
                    "info", account_name=account_name)

    try:
        src_before = bc.l2_native_balance_wei(address, proxy)
        # L1 native ETH (как proxy метрика, чтобы видеть что на L1 пользователь есть)
        dst_before = bc.l1_zkltc_balance_wei(address, proxy)
    except bc.BridgeError as e:
        log_wallet_task(address, idx, total,
                        f"❌ {label} · balance fetch failed: {e}",
                        "error", account_name=account_name)
        db.update_tx_task(tx_id, send_status="failed",
                          error_message=f"balance fetch: {str(e)[:300]}")
        return False
    db.update_tx_task(tx_id,
                      src_balance_before_wei=str(src_before),
                      dst_balance_before_wei=str(dst_before))

    reserve = int(LITVM_BRIDGE_GAS_RESERVE_ZKLTC * 1e18)
    if src_before < amount_wei + reserve:
        msg = (f"L2 zkLTC {src_before/1e18:.6f} < amount {amount_wei/1e18:.6f} "
               f"+ reserve {reserve/1e18:.6f}")
        log_wallet_task(address, idx, total, f"❌ {label} · {msg}",
                        "error", account_name=account_name)
        db.update_tx_task(tx_id, send_status="failed", error_message=msg[:300])
        return False

    try:
        h, _rc = bc.send_l2_withdraw(account=account, amount_wei=amount_wei,
                                      destination=address, proxy=proxy)
    except bc.BridgeError as e:
        log_wallet_task(address, idx, total,
                        f"❌ {label} · withdraw failed: {e}",
                        "error", account_name=account_name)
        db.update_tx_task(tx_id, send_status="failed",
                          error_message=f"withdraw: {str(e)[:300]}")
        return False

    try:
        src_after = bc.l2_native_balance_wei(address, proxy)
    except bc.BridgeError:
        src_after = src_before - amount_wei  # best-effort

    db.update_tx_task(tx_id,
                      send_status="confirmed",
                      dst_status="submitted",
                      src_tx_hash=h,
                      src_balance_after_wei=str(src_after))
    log_wallet_task(
        address, idx, total,
        f"✅ {label} · L2 withdraw tx={_short_tx(h)} подтверждён "
        f"· L1-финализация автоматически при следующих запусках",
        "success", account_name=account_name,
    )
    return True


# ---------------------------------------------------------------------------
# executor — optional return (L2 → L1)
# ---------------------------------------------------------------------------

def _execute_return(address: str, account, proxy: Optional[str],
                    idx: int, total: int, account_name: Optional[str]) -> None:
    """Опциональный обратный мост — направление, противоположное primary.
    Делает ОДНУ tx (% от баланса)."""
    if not LITVM_BRIDGE_RETURN_ENABLED:
        return
    ret_dir = _opposite(_primary_direction())
    pct = max(1.0, min(100.0, float(LITVM_BRIDGE_RETURN_PCT)))

    if ret_dir == "l2_to_l1":
        # вернуть с L2 на L1
        try:
            l2_bal = bc.l2_native_balance_wei(address, proxy)
        except bc.BridgeError as e:
            log_wallet_task(address, idx, total,
                            f"⚠ return · L2 balance fetch: {e}",
                            "warning", account_name=account_name)
            db.update_wallet(address, return_status="failed",
                             error_message=f"return: {str(e)[:200]}")
            return
        reserve = int(LITVM_BRIDGE_GAS_RESERVE_ZKLTC * 1e18)
        avail = max(0, l2_bal - reserve)
        amount = int(avail * pct) // 100
        if amount < int(LITVM_BRIDGE_MIN_AMOUNT_ZKLTC * 1e18):
            log_wallet_task(
                address, idx, total,
                f"⏭ return пропущен · L2 {l2_bal/1e18:.6f} (за вычетом резерва) "
                f"< min {LITVM_BRIDGE_MIN_AMOUNT_ZKLTC}",
                "warning", account_name=account_name,
            )
            db.update_wallet(address, return_status="skipped")
            return
        log_wallet_task(
            address, idx, total,
            f"🔁 return L2→L1 · withdrawEth {amount/1e18:.6f} zkLTC "
            f"(L1-финализация автоматически позже)",
            "info", account_name=account_name,
        )
        db.update_wallet(address, return_status="pending")
        try:
            h, _ = bc.send_l2_withdraw(account=account, amount_wei=amount,
                                        destination=address, proxy=proxy)
            log_wallet_task(
                address, idx, total,
                f"✅ return L2→L1 · tx={_short_tx(h)} (финализация автоматическая)",
                "success", account_name=account_name,
            )
            db.update_wallet(address, return_status="confirmed")
        except bc.BridgeError as e:
            log_wallet_task(address, idx, total,
                            f"❌ return L2→L1 failed: {e}",
                            "error", account_name=account_name)
            db.update_wallet(address, return_status="failed",
                             error_message=f"return: {str(e)[:300]}")
        return

    # ret_dir == "l1_to_l2": вернуть с L1 на L2
    try:
        l1_bal = bc.l1_zkltc_balance_wei(address, proxy)
        l1_eth = bc.l1_native_balance_wei(address, proxy)
    except bc.BridgeError as e:
        log_wallet_task(address, idx, total,
                        f"⚠ return · L1 balance fetch: {e}",
                        "warning", account_name=account_name)
        db.update_wallet(address, return_status="failed",
                         error_message=f"return: {str(e)[:200]}")
        return
    if l1_eth < int(LITVM_BRIDGE_GAS_RESERVE_ETH * 1e18):
        log_wallet_task(
            address, idx, total,
            f"⏭ return пропущен · L1 ETH {l1_eth/1e18:.6f} < резерв на газ",
            "warning", account_name=account_name,
        )
        db.update_wallet(address, return_status="skipped")
        return
    amount = int(l1_bal * pct) // 100
    if amount < int(LITVM_BRIDGE_MIN_AMOUNT_ZKLTC * 1e18):
        log_wallet_task(
            address, idx, total,
            f"⏭ return пропущен · L1 zkLTC {l1_bal/1e18:.6f} < min",
            "warning", account_name=account_name,
        )
        db.update_wallet(address, return_status="skipped")
        return
    log_wallet_task(
        address, idx, total,
        f"🔁 return L1→L2 · approve+deposit {amount/1e18:.6f} zkLTC",
        "info", account_name=account_name,
    )
    db.update_wallet(address, return_status="pending")
    try:
        bc.send_l1_approve(account=account, amount_wei=amount, proxy=proxy)
        h, _ = bc.send_l1_deposit(account=account, amount_wei=amount, proxy=proxy)
        log_wallet_task(
            address, idx, total,
            f"✅ return L1→L2 · deposit tx={_short_tx(h)} (L2 кредит ~10-15 мин)",
            "success", account_name=account_name,
        )
        db.update_wallet(address, return_status="confirmed")
    except bc.BridgeError as e:
        log_wallet_task(address, idx, total,
                        f"❌ return L1→L2 failed: {e}",
                        "error", account_name=account_name)
        db.update_wallet(address, return_status="failed",
                         error_message=f"return: {str(e)[:300]}")


# ---------------------------------------------------------------------------
# Авто-финализация L2→L1 (Outbox.executeTransaction на L1)
# ---------------------------------------------------------------------------

def _try_finalize_one(task: dict, account, proxy: Optional[str],
                      idx: int, total: int, account_name: Optional[str]) -> str:
    """Возвращает 'finalized' | 'pending' | 'error'."""
    address = account.address
    tx_id = int(task["id"])
    tx_index = int(task["tx_index"])
    l2_hash = task.get("src_tx_hash")
    if not l2_hash:
        db.update_tx_task(tx_id,
                          finalize_last_at=time.time(),
                          finalize_last_reason="no L2 tx hash")
        return "error"

    try:
        result = bc.try_finalize_l2_withdraw(
            account=account, l2_tx_hash=l2_hash, proxy=proxy,
        )
    except bc.BridgeError as e:
        log_wallet_task(
            address, idx, total,
            f"⚠ finalize tx#{tx_index} · {e} · повтор автоматически позже",
            "warning", account_name=account_name,
        )
        db.update_tx_task(
            tx_id,
            finalize_attempts=int(task.get("finalize_attempts") or 0) + 1,
            finalize_last_at=time.time(),
            finalize_last_reason=str(e)[:300],
        )
        return "error"

    if result["ready"]:
        log_wallet_task(
            address, idx, total,
            f"🏁 finalize tx#{tx_index} · L1 tx={_short_tx(result['l1_tx_hash'])} "
            f"· zkLTC получен на Sepolia",
            "success", account_name=account_name,
        )
        db.update_tx_task(
            tx_id,
            dst_status="finalized",
            finalize_tx_hash=result["l1_tx_hash"],
            finalize_attempts=int(task.get("finalize_attempts") or 0) + 1,
            finalize_last_at=time.time(),
            finalize_last_reason=None,
        )
        return "finalized"

    # not ready — retry next run
    db.update_tx_task(
        tx_id,
        finalize_attempts=int(task.get("finalize_attempts") or 0) + 1,
        finalize_last_at=time.time(),
        finalize_last_reason=result.get("reason"),
    )
    log_wallet_task(
        address, idx, total,
        f"⏳ finalize tx#{tx_index} · ещё не готово: {result.get('reason')} · "
        f"повтор автоматически при следующем запуске",
        "info", account_name=account_name,
    )
    return "pending"


def finalize_pending_for_wallet(record: dict, idx: int, total: int) -> dict:
    """Пытается финализировать все submitted L2→L1 tx кошелька.
    Возвращает счётчики {finalized, pending, error}."""
    counters = {"finalized": 0, "pending": 0, "error": 0}
    if not LITVM_BRIDGE_AUTO_FINALIZE_L1:
        return counters
    account = _account_from_record(record)
    if account is None:
        return counters
    address = account.address
    account_name = record.get("name") or None
    proxy = _proxy_of(record)

    # Только submitted-tx этого кошелька, не чаще retry-интервала
    interval = float(LITVM_BRIDGE_FINALIZE_RETRY_INTERVAL_SEC)
    all_tx = db.list_tx_for_wallet(address, "l2_to_l1")
    now = time.time()
    pending = [
        t for t in all_tx
        if t.get("send_status") == "confirmed"
        and t.get("dst_status") == "submitted"
        and (not t.get("finalize_last_at")
             or (now - float(t.get("finalize_last_at") or 0)) >= interval)
    ]
    if not pending:
        return counters

    log_wallet_task(
        address, idx, total,
        f"🏁 авто-финализация L1 · {len(pending)} tx ожидают подтверждения",
        "info", account_name=account_name,
    )
    for t in pending:
        try:
            r = _try_finalize_one(t, account, proxy, idx, total, account_name)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            log_wallet_task(
                address, idx, total,
                f"⚠ finalize tx#{t['tx_index']} · unexpected: {e}",
                "warning", account_name=account_name,
            )
            db.update_tx_task(
                int(t["id"]),
                finalize_attempts=int(t.get("finalize_attempts") or 0) + 1,
                finalize_last_at=time.time(),
                finalize_last_reason=f"unexpected: {str(e)[:200]}",
            )
            r = "error"
        counters[r] = counters.get(r, 0) + 1
    return counters


# ---------------------------------------------------------------------------
# wallet entry-point
# ---------------------------------------------------------------------------

def process_wallet(record: dict, idx: int, total: int) -> None:
    """Полная обработка одного кошелька: idempotent + resumable."""
    account = _account_from_record(record)
    if account is None:
        return
    address = account.address
    account_name = record.get("name") or None
    proxy = _proxy_of(record)
    direction = _primary_direction()

    # Фаза авто-финализации L2→L1 — пытаемся до основной работы, чтобы
    # подобрать tx, оставшиеся с прошлых запусков (если такие есть).
    finalize_pending_for_wallet(record, idx, total)

    # Если план ещё не создан — создадим.
    if not db.list_tx_for_wallet(address, direction):
        ok = plan_wallet(record, idx, total)
        if not ok:
            return

    wallet = db.get_wallet(address) or {}
    if wallet.get("status") == "pending":
        db.update_wallet(address, status="in_progress")

    pending = db.list_pending_tx_for_wallet(address, direction)
    if not pending:
        log_wallet_task(
            address, idx, total,
            f"✅ все {direction} tx уже выполнены — нечего делать",
            "success", account_name=account_name,
        )
        db.recompute_wallet_counters(address)
        if (LITVM_BRIDGE_RETURN_ENABLED
                and (wallet.get("return_status") or "pending") == "pending"):
            _execute_return(address, account, proxy, idx, total, account_name)
        return

    log_wallet_task(
        address, idx, total,
        f"💱 старт {direction} · {len(pending)} pending tx из плана",
        "info", account_name=account_name,
    )

    executor_fn = (
        _execute_l1_to_l2_tx if direction == "l1_to_l2"
        else _execute_l2_to_l1_tx
    )

    for i, task in enumerate(pending, 1):
        try:
            ok = executor_fn(task, account, proxy, idx, total, account_name)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001 — финальный safety-net
            log_wallet_task(address, idx, total,
                            f"❌ tx#{task['tx_index']} · unexpected: {e}",
                            "error", account_name=account_name)
            db.update_tx_task(int(task["id"]), send_status="failed",
                              error_message=f"unexpected: {str(e)[:300]}")
            ok = False
        db.recompute_wallet_counters(address)
        if i < len(pending):
            lo, hi = (LITVM_BRIDGE_SLEEP_BETWEEN_TX +
                      [LITVM_BRIDGE_SLEEP_BETWEEN_TX[0]])[:2]
            pause = random.uniform(float(lo), float(hi))

            time.sleep(pause)

    final = db.recompute_wallet_counters(address)
    if final["status"] == "completed":
        log_wallet_task(
            address, idx, total,
            f"🎯 завершено · {final['completed']}/{final['planned']} tx успешно",
            "success", account_name=account_name,
        )
        if LITVM_BRIDGE_RETURN_ENABLED:
            _execute_return(address, account, proxy, idx, total, account_name)
        # Попытка финализации только что отправленных L2→L1 tx
        if direction == "l2_to_l1":
            finalize_pending_for_wallet(record, idx, total)
    elif final["status"] == "failed":
        log_wallet_task(
            address, idx, total,
            f"⚠ кошелёк завершён с ошибками · "
            f"{final['completed']} ok / {final['failed']} fail / {final['planned']} планировалось",
            "warning", account_name=account_name,
        )
    else:
        log_wallet_task(
            address, idx, total,
            f"⏸ кошелёк не завершён · {final['completed']}/{final['planned']} ok, "
            f"запусти ещё раз для дозавершения",
            "info", account_name=account_name,
        )
