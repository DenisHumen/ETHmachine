"""Lester Minter — per-wallet worker.

Этап 1 (plan):
  Для каждого кошелька генерируется N = random(LITVM_MINTER_TX_PER_WALLET)
  деплоев. На каждый — случайные name/symbol/decimals/supply/features.
  Записывается в БД (status='pending'); сами tx не отправляются.

Этап 2 (run):
  Идёт по pending-деплоям кошелька. Для каждого: проверяет баланс ≥
  fee + reserve + gas, отправляет createToken, ждёт receipt, парсит адрес
  созданного токена, обновляет БД (status='confirmed'/'failed').

Идемпотентно: при повторном запуске пропускает confirmed, продолжает
pending/sending (мы не теряем прогресс при interrupt).
"""
from __future__ import annotations

import random
import time
from typing import Optional

from web3 import Web3

from config.modules.cfg_litvm_testnet import (
    LITVM_MINTER_DECIMALS_CHOICES,
    LITVM_MINTER_DEPLOY_FEE_WEI,
    LITVM_MINTER_FEATURE_TRUE_PROB,
    LITVM_MINTER_GAS_RESERVE_ZKLTC,
    LITVM_MINTER_SLEEP_BETWEEN_TX,
    LITVM_MINTER_SUPPLY_RANGE,
    LITVM_MINTER_TX_ATTEMPTS,
    LITVM_MINTER_TX_PER_WALLET,
)
from modules.proxy_manager import get_proxy_dict  # noqa: F401  (для совместимости)
from modules.simple_logger import log_simple, log_wallet_task
from modules.litvm_testnet.lester_minter import database as db
from modules.litvm_testnet.lester_minter import minter_client as mc
from modules.litvm_testnet.lester_minter.name_generator import (
    generate_features,
    generate_token_metadata,
    generate_total_supply,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _short_tx(h: Optional[str]) -> str:
    if not h:
        return ""
    raw = h[2:] if h.startswith("0x") else h
    return f"{raw[:8]}…{raw[-6:]}" if len(raw) > 16 else raw


def _proxy_of(record: dict) -> Optional[str]:
    p = (record.get("proxy") or "").strip()
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


def _format_supply(supply_int: int, decimals: int) -> str:
    """Человекочитаемое отображение supply (1_000_000 → '1M', 1B → '1B')."""
    if supply_int >= 1_000_000_000:
        return f"{supply_int / 1_000_000_000:.2f}B".rstrip("0").rstrip(".")
    if supply_int >= 1_000_000:
        return f"{supply_int / 1_000_000:.2f}M".rstrip("0").rstrip(".")
    if supply_int >= 1_000:
        return f"{supply_int / 1_000:.1f}k".rstrip("0").rstrip(".")
    return str(supply_int)


def _features_label(m: bool, b: bool, p: bool) -> str:
    flags = []
    if m: flags.append("M")
    if b: flags.append("B")
    if p: flags.append("P")
    return "+".join(flags) or "—"


# ---------------------------------------------------------------------------
# Phase 1: planner
# ---------------------------------------------------------------------------

def plan_wallet(record: dict, idx: int, total: int) -> bool:
    """Создаёт N pending-деплоев в БД для кошелька. Возвращает True если был
    создан план (или он уже есть)."""
    account = _account_from_record(record)
    if account is None:
        return False
    address = account.address
    account_name = record.get("name") or None

    db.upsert_wallet(address, name=account_name)

    existing = db.list_deployments_for_wallet(address)
    if existing:
        log_wallet_task(
            address, idx, total,
            f"📋 план уже существует ({len(existing)} деплоев) — пропуск",
            "info", account_name=account_name,
        )
        return True

    lo, hi = LITVM_MINTER_TX_PER_WALLET
    n = random.randint(int(lo), int(hi))
    used_symbols: set[str] = set()
    for tx_idx in range(1, n + 1):
        meta = generate_token_metadata(used_symbols=used_symbols)
        used_symbols.add(meta["symbol"])
        decimals = random.choice(list(LITVM_MINTER_DECIMALS_CHOICES))
        supply_lo, supply_hi = LITVM_MINTER_SUPPLY_RANGE
        supply_int = generate_total_supply(lo=int(supply_lo), hi=int(supply_hi))
        feats = generate_features(true_prob=float(LITVM_MINTER_FEATURE_TRUE_PROB))
        # total supply в wei = supply_int * 10**decimals
        total_supply_wei = int(supply_int) * (10 ** int(decimals))
        db.insert_deployment({
            "address": address,
            "tx_index": tx_idx,
            "token_name": meta["name"],
            "token_symbol": meta["symbol"],
            "decimals": decimals,
            "total_supply": str(total_supply_wei),
            "mintable": feats["mintable"],
            "burnable": feats["burnable"],
            "pausable": feats["pausable"],
            "logo_url": None,
            "fee_wei": str(LITVM_MINTER_DEPLOY_FEE_WEI),
        })

    db.update_wallet(address, planned=n, status="pending")
    log_wallet_task(
        address, idx, total,
        f"🪙 план создан · {n} токенов",
        "info", account_name=account_name,
    )
    return True


# ---------------------------------------------------------------------------
# Phase 2: executor
# ---------------------------------------------------------------------------

def _execute_one(dep: dict, account, proxy: Optional[str],
                 idx: int, total: int, account_name: Optional[str]) -> bool:
    address = account.address
    dep_id = int(dep["id"])
    tx_idx = int(dep["tx_index"])
    name = dep["token_name"]
    symbol = dep["token_symbol"]
    decimals = int(dep["decimals"])
    supply_wei = int(dep["total_supply"])
    mintable = bool(dep["mintable"])
    burnable = bool(dep["burnable"])
    pausable = bool(dep["pausable"])

    # supply_int для отображения (без decimals)
    supply_int = supply_wei // (10 ** decimals) if decimals > 0 else supply_wei
    label = (f"tx#{tx_idx} · {name} ({symbol}) "
             f"· {_format_supply(supply_int, decimals)} "
             f"· d={decimals} · [{_features_label(mintable, burnable, pausable)}]")

    # баланс
    try:
        bal = mc.get_balance_wei(address, proxy)
    except Exception as e:  # noqa: BLE001
        log_wallet_task(address, idx, total,
                        f"⚠ {label} · balance fetch failed: {e}",
                        "warning", account_name=account_name)
        return False
    need = int(LITVM_MINTER_DEPLOY_FEE_WEI) + int(
        float(LITVM_MINTER_GAS_RESERVE_ZKLTC) * 10**18
    )
    if bal < need:
        msg = (f"⚠ {label} · недостаточно баланса "
               f"({bal/1e18:.4f} < {need/1e18:.4f} zkLTC) · пропуск")
        log_wallet_task(address, idx, total, msg, "warning",
                        account_name=account_name)
        db.update_deployment(dep_id, status="failed",
                             error_message="insufficient balance")
        return False

    # отправка с ретраями
    db.update_deployment(
        dep_id,
        status="sending",
        attempts=int(dep.get("attempts") or 0) + 1,
        sent_at=time.time(),
    )
    attempts = int(LITVM_MINTER_TX_ATTEMPTS)
    last_err: Optional[str] = None
    for attempt in range(1, attempts + 1):
        try:
            h, receipt = mc.send_create_token(
                account=account, name=name, symbol=symbol,
                total_supply_wei=supply_wei, decimals=decimals,
                mintable=mintable, burnable=burnable, pausable=pausable,
                proxy=proxy,
            )
        except mc.MinterError as e:
            last_err = str(e)
            log_wallet_task(
                address, idx, total,
                f"⚠ {label} · attempt {attempt}/{attempts}: {e}",
                "warning", account_name=account_name,
            )
            if attempt < attempts:
                time.sleep(min(15, 3 * attempt))
            continue
        except Exception as e:  # noqa: BLE001
            last_err = f"unexpected: {e}"
            log_wallet_task(
                address, idx, total,
                f"⚠ {label} · attempt {attempt}/{attempts}: {e}",
                "warning", account_name=account_name,
            )
            if attempt < attempts:
                time.sleep(min(15, 3 * attempt))
            continue
        # успех
        token_addr = mc.extract_token_address_from_receipt(receipt)
        gas_used = int(receipt.get("gasUsed") or 0)
        db.update_deployment(
            dep_id,
            status="confirmed",
            tx_hash=h,
            token_address=token_addr,
            gas_used=gas_used,
            confirmed_at=time.time(),
            error_message=None,
        )
        log_wallet_task(
            address, idx, total,
            f"✅ {label} · tx={_short_tx(h)} "
            f"· token={token_addr or '?'} · gas={gas_used}",
            "success", account_name=account_name,
        )
        return True

    # все попытки исчерпаны
    db.update_deployment(dep_id, status="failed",
                         error_message=(last_err or "unknown")[:500])
    log_wallet_task(
        address, idx, total,
        f"❌ {label} · failed после {attempts} попыток: {last_err}",
        "error", account_name=account_name,
    )
    return False


def process_wallet(record: dict, idx: int, total: int) -> None:
    account = _account_from_record(record)
    if account is None:
        return
    address = account.address
    account_name = record.get("name") or None
    proxy = _proxy_of(record)

    # план создаём если ещё нет
    if not db.list_deployments_for_wallet(address):
        if not plan_wallet(record, idx, total):
            return

    wallet = db.get_wallet(address) or {}
    if wallet.get("status") == "pending":
        db.update_wallet(address, status="in_progress")

    pending = db.list_pending_for_wallet(address)
    if not pending:
        log_wallet_task(
            address, idx, total,
            "✅ все токены этого кошелька уже задеплоены — нечего делать",
            "success", account_name=account_name,
        )
        db.recompute_wallet_counters(address)
        return

    log_wallet_task(
        address, idx, total,
        f"🪙 старт деплоя · {len(pending)} pending токенов",
        "info", account_name=account_name,
    )

    for i, dep in enumerate(pending, 1):
        try:
            _execute_one(dep, account, proxy, idx, total, account_name)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            log_wallet_task(
                address, idx, total,
                f"❌ tx#{dep['tx_index']} · unexpected: {e}",
                "error", account_name=account_name,
            )
            db.update_deployment(int(dep["id"]), status="failed",
                                 error_message=f"unexpected: {str(e)[:300]}")
        db.recompute_wallet_counters(address)
        if i < len(pending):
            lo, hi = LITVM_MINTER_SLEEP_BETWEEN_TX
            time.sleep(random.uniform(float(lo), float(hi)))

    final = db.recompute_wallet_counters(address)
    if final["status"] == "completed":
        log_wallet_task(
            address, idx, total,
            f"🎯 готово · {final['completed']}/{final['planned']} токенов",
            "success", account_name=account_name,
        )
    elif final["status"] == "failed":
        log_wallet_task(
            address, idx, total,
            f"⚠ завершено с ошибками · {final['completed']} ok / "
            f"{final['failed']} fail / {final['planned']} планировалось",
            "warning", account_name=account_name,
        )
    else:
        log_wallet_task(
            address, idx, total,
            f"⏸ не завершён · {final['completed']}/{final['planned']} ok",
            "info", account_name=account_name,
        )
