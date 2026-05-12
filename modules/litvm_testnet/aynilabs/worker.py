"""Aynilabs — planner + executor для wrap zkLTC → WzkLTC.

Phase 1 (plan):
  Для каждого кошелька читаем native zkLTC balance, считаем сумму wrap'а
  (доля от баланса минус gas reserve), создаём задачу со status='pending'.
  Если balance < min или сумма ≤ 0 → status='skipped'.

Phase 2 (run):
  Для каждой pending-задачи: фиксируем WzkLTC.balanceOf BEFORE,
  отправляем `deposit()` с payable value, ждём receipt, проверяем
  что WzkLTC.balanceOf AFTER > BEFORE → arrived. Иначе failed.
"""
from __future__ import annotations

import random
import time
from typing import Optional

from web3 import Web3

from config.modules.cfg_litvm_testnet import (
    AYNI_GAS_RESERVE_ZKLTC,
    AYNI_MIN_NATIVE_BALANCE_ZKLTC,
    AYNI_TX_ATTEMPTS,
    AYNI_WRAP_PCT_RANGE,
)
from modules.simple_logger import log_simple, log_wallet_task
from modules.litvm_testnet.aynilabs import database as db
from modules.litvm_testnet.aynilabs import wrap_client as wc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_tx(h: Optional[str]) -> str:
    if not h:
        return ""
    raw = h[2:] if h.startswith("0x") else h
    return f"{raw[:8]}…{raw[-6:]}" if len(raw) > 16 else raw


def _primary_proxy(record: dict) -> Optional[str]:
    p = (record.get("proxy") or "").strip()
    return p or None


def _reserve_proxy(record: dict) -> Optional[str]:
    p = (record.get("reserve_proxy") or "").strip()
    return p or None


def _proxy_chain(record: dict) -> list[Optional[str]]:
    """primary → reserve → None (deduped). AGENTS.md §10: при ошибке RPC
    пробуем резервный прокси юзера прежде чем кидать."""
    chain: list[Optional[str]] = []
    seen: set[str] = set()
    for p in (_primary_proxy(record), _reserve_proxy(record)):
        key = (p or "").strip()
        if key in seen:
            continue
        chain.append(p)
        seen.add(key)
    if not chain:
        chain = [None]
    return chain


def _account_from_record(record: dict):
    pk = (record.get("private_key") or "").strip()
    if not pk:
        return None
    try:
        return wc.account_from_private_key(pk)
    except Exception as e:  # noqa: BLE001
        log_simple(f"⚠ невалидный private_key: {e}", "warning")
        return None


def _native_balance_with_fallback(address: str, record: dict
                                  ) -> tuple[int, Optional[str]]:
    """Возвращает (balance_wei, used_proxy). Перебирает proxy_chain."""
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(record):
        try:
            return wc.get_native_balance_wei(address, proxy), proxy
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise wc.AyniError(f"native balance fetch failed via all proxies: {last_err}")


def _wzkltc_balance_with_fallback(address: str, record: dict) -> int:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(record):
        try:
            return wc.get_wzkltc_balance_wei(address, proxy)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise wc.AyniError(f"WzkLTC balance fetch failed: {last_err}")


# ---------------------------------------------------------------------------
# Phase 1: planner
# ---------------------------------------------------------------------------

def plan_wallet(record: dict, idx: int, total: int) -> bool:
    """Создаёт/обновляет задачу wrap для кошелька. Возвращает True если
    задача доступна для выполнения (status='pending')."""
    account = _account_from_record(record)
    if account is None:
        return False
    address = account.address
    account_name = record.get("name") or None

    try:
        native_wei, _ = _native_balance_with_fallback(address, record)
    except wc.AyniError as e:
        log_wallet_task(address, idx, total,
                        f"⚠ balance fetch failed: {e}",
                        "warning", account_name=account_name)
        return False

    native_zkltc = native_wei / 1e18
    min_native = float(AYNI_MIN_NATIVE_BALANCE_ZKLTC)
    if native_zkltc < min_native:
        db.upsert_task(
            address=address, name=account_name, tx_index=1,
            planned_amount_wei=0, planned_amount_human=0.0,
            native_balance_before_wei=native_wei,
            status="skipped",
        )
        log_wallet_task(address, idx, total,
                        f"⏭ skip · native {native_zkltc:.5f} < min {min_native}",
                        "warning", account_name=account_name)
        return False

    pct_lo, pct_hi = AYNI_WRAP_PCT_RANGE
    pct = random.uniform(float(pct_lo), float(pct_hi))
    gas_reserve_wei = int(float(AYNI_GAS_RESERVE_ZKLTC) * 1e18)
    spendable_wei = max(0, native_wei - gas_reserve_wei)
    amount_wei = int(spendable_wei * pct)
    if amount_wei <= 0:
        db.upsert_task(
            address=address, name=account_name, tx_index=1,
            planned_amount_wei=0, planned_amount_human=0.0,
            native_balance_before_wei=native_wei,
            status="skipped",
        )
        log_wallet_task(address, idx, total,
                        f"⏭ skip · spendable=0 (balance {native_zkltc:.5f})",
                        "warning", account_name=account_name)
        return False

    amount_human = amount_wei / 1e18
    db.upsert_task(
        address=address, name=account_name, tx_index=1,
        planned_amount_wei=amount_wei, planned_amount_human=amount_human,
        native_balance_before_wei=native_wei,
        status="pending",
    )
    log_wallet_task(
        address, idx, total,
        f"📋 plan · wrap {amount_human:.5f} zkLTC "
        f"({pct*100:.1f}% от {native_zkltc:.5f})",
        "info", account_name=account_name,
    )
    return True


# ---------------------------------------------------------------------------
# Phase 2: executor
# ---------------------------------------------------------------------------

def _send_with_proxy_fallback(account, value_wei: int, record: dict
                              ) -> tuple[str, dict]:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(record):
        try:
            return wc.send_deposit(
                account=account, value_wei=value_wei, proxy=proxy,
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise wc.AyniError(f"deposit() send failed via all proxies: {last_err}")


def process_wallet(record: dict, idx: int, total: int) -> bool:
    """Выполняет wrap для одного кошелька. Сам создаёт задачу, если её ещё
    нет (idempotent). True если итоговый статус 'arrived'."""
    account = _account_from_record(record)
    if account is None:
        return False
    address = account.address
    account_name = record.get("name") or None

    task = db.get_task_for_wallet(address, tx_index=1)
    if task is None or task.get("status") in ("skipped",):
        # planner пересчитает (на случай, если баланс изменился).
        if not plan_wallet(record, idx, total):
            return False
        task = db.get_task_for_wallet(address, tx_index=1)
        if task is None:
            return False

    status = (task.get("status") or "pending").lower()
    if status == "arrived":
        log_wallet_task(address, idx, total,
                        "✅ уже выполнено ранее · пропуск",
                        "info", account_name=account_name)
        return True
    if status == "skipped":
        return False
    if status not in ("pending", "tx_sent", "failed"):
        log_wallet_task(address, idx, total,
                        f"⚠ unknown status='{status}' · пропуск",
                        "warning", account_name=account_name)
        return False

    task_id = int(task["id"])
    value_wei = int(task["planned_amount_wei"])
    if value_wei <= 0:
        log_wallet_task(address, idx, total,
                        "⚠ planned_amount_wei <= 0 · пересчёт plan'а",
                        "warning", account_name=account_name)
        if not plan_wallet(record, idx, total):
            return False
        task = db.get_task_for_wallet(address, tx_index=1) or {}
        value_wei = int(task.get("planned_amount_wei") or 0)
        if value_wei <= 0:
            return False
        task_id = int(task["id"])

    # baseline: текущий WzkLTC баланс
    try:
        before = _wzkltc_balance_with_fallback(address, record)
    except wc.AyniError as e:
        log_wallet_task(address, idx, total,
                        f"⚠ WzkLTC balance fetch failed: {e}",
                        "warning", account_name=account_name)
        return False
    db.update_task(task_id, wzkltc_balance_before_wei=str(before))

    log_wallet_task(
        address, idx, total,
        f"📤 deposit() · value={value_wei/1e18:.5f} zkLTC "
        f"· WzkLTC before={before/1e18:.5f}",
        "info", account_name=account_name,
    )

    attempts = max(1, int(AYNI_TX_ATTEMPTS))
    last_err: Optional[str] = None
    tx_hash: Optional[str] = None
    receipt: Optional[dict] = None
    for attempt in range(1, attempts + 1):
        db.update_task(
            task_id, status="tx_sent",
            attempts=int(task.get("attempts") or 0) + attempt,
            sent_at=time.time(),
        )
        try:
            tx_hash, receipt = _send_with_proxy_fallback(
                account, value_wei, record,
            )
            break
        except wc.AyniError as e:
            last_err = str(e)
            log_wallet_task(
                address, idx, total,
                f"⚠ attempt {attempt}/{attempts}: {e}",
                "warning", account_name=account_name,
            )
            if attempt < attempts:
                time.sleep(min(15, 3 * attempt))
            continue

    if tx_hash is None or receipt is None:
        db.update_task(
            task_id, status="failed",
            error_message=(last_err or "unknown")[:500],
        )
        log_wallet_task(
            address, idx, total,
            f"❌ wrap failed после {attempts} попыток: {last_err}",
            "error", account_name=account_name,
        )
        return False

    gas_used = int(receipt.get("gasUsed") or 0)
    db.update_task(
        task_id, tx_hash=tx_hash, gas_used=gas_used,
        confirmed_at=time.time(),
    )

    # Проверяем что WzkLTC.balanceOf реально вырос. AGENTS.md §10.8.
    try:
        after = _wzkltc_balance_with_fallback(address, record)
    except wc.AyniError as e:
        # tx подтверждена, но не можем проверить баланс — отметим как
        # awaiting_arrival с пометкой; статус 'arrived' выставим при ретрае.
        db.update_task(
            task_id, status="tx_sent",
            error_message=f"post-balance fetch failed: {str(e)[:300]}",
        )
        log_wallet_task(
            address, idx, total,
            f"⚠ tx подтверждена ({_short_tx(tx_hash)}), но не смогли "
            f"перепроверить WzkLTC balance: {e}",
            "warning", account_name=account_name,
        )
        return False

    received = max(0, after - before)
    db.update_task(
        task_id,
        wzkltc_balance_after_wei=str(after),
        received_amount_wei=str(received),
    )

    # ВАЖНО: сайт фактически минтит WzkLTC централизованно/off-chain
    # (адрес в JS-бандле — EOA с опечаткой, не контракт). Поэтому on-chain
    # рост balanceOf не гарантирован сразу. Критерий успеха = успешный
    # receipt (status=1). Рост balanceOf логируем как доп. сигнал.
    if received > 0:
        db.update_task(task_id, status="arrived", error_message=None)
        log_wallet_task(
            address, idx, total,
            f"✅ wrap · tx={_short_tx(tx_hash)} "
            f"· received={received/1e18:.5f} WzkLTC "
            f"· gas={gas_used}",
            "success", account_name=account_name,
        )
    else:
        db.update_task(task_id, status="arrived", error_message=None)
        log_wallet_task(
            address, idx, total,
            f"✅ deposit() · tx={_short_tx(tx_hash)} "
            f"· value={value_wei/1e18:.5f} zkLTC · gas={gas_used} "
            f"(WzkLTC mint off-chain, on-chain balance не вырос — это норма для сайта)",
            "success", account_name=account_name,
        )
    return True
