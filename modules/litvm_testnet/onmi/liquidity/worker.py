"""Onmi Liquidity · ADD (random small) + REMOVE-ALL (one button).

ADD-стратегия (для каждой операции):
  1. выбираем кошелёк (native ≥ min);
  2. выбираем случайную pair из onmi_swap_known_pairs (если кэш пуст — auto
     scan factory);
  3. native budget N = random(ONMI_LIQ_ADD_VALUE_RANGE);
     buy_part = N * 0.5 — этим покупаем токен через router;
  4. addLiquidityETH(token, T, T*(1-slip), (N-buy_part)*(1-slip),
                      wallet, deadline) value=(N - buy_part);
  5. читаем pair.balanceOf(after) − before → lp_received;
  6. пишем positions + history.

REMOVE-ALL стратегия:
  Для каждого кошелька:
    a) собираем pair-кандидаты:
         • все pairs из onmi_lp_positions (lp_net > 0)
         • плюс все pairs из onmi_swap_known_pairs (на случай ADD'ов вне БД)
    b) для каждой pair смотрим on-chain pair.balanceOf(wallet);
       если > 0 — вызываем approve + removeLiquidityETH с amountMin=0;
    c) пишем history(side='remove'), upsert_position_after_remove.
"""
from __future__ import annotations

import random
import time
from typing import Optional

from web3 import Web3

from config.modules.cfg_litvm_testnet import (
    ONMI_LIQ_ADD_OPS_RANGE,
    ONMI_LIQ_ADD_VALUE_RANGE,
    ONMI_LIQ_DEADLINE_SEC,
    ONMI_LIQ_GAS_RESERVE,
    ONMI_LIQ_MIN_NATIVE_BALANCE,
    ONMI_LIQ_OPS_PER_WALLET_RANGE,
    ONMI_LIQ_SLEEP_BETWEEN_OPS,
    ONMI_LIQ_SLIPPAGE,
    ONMI_LIQ_TX_ATTEMPTS,
    ONMI_SWAP_MIN_RESERVE_NATIVE_WEI,
)
from config.modules.general_config import SHUFLE_ACCOUNTS
from modules.simple_logger import log_simple, log_wallet_task
from modules.litvm_testnet.onmi.liquidity import database as db
from modules.litvm_testnet.onmi.swap import database as swap_db
from modules.litvm_testnet.onmi.swap import swap_client as sc
from modules.litvm_testnet.onmi.swap.worker import refresh_pairs_cache


# ---------------------------------------------------------------------------
# Helpers (shared style with swap/trade workers)
# ---------------------------------------------------------------------------

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
        return sc.account_from_private_key(pk)
    except Exception as e:
        log_simple(f"⚠ невалидный private_key: {e}", "warning")
        return None


def _native_balance(addr: str, rec: dict) -> int:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(rec):
        try:
            return sc.get_native_balance_wei(addr, proxy)
        except Exception as e:
            last_err = e
    raise sc.SwapError(f"native balance fetch failed: {last_err}")


# ---------------------------------------------------------------------------
# ADD session
# ---------------------------------------------------------------------------

def run_add_liquidity_session(
    records: list[dict],
    *,
    total_ops_override: Optional[int] = None,
) -> dict:
    db.init_database()
    swap_db.init_database()

    pairs = swap_db.list_known_pairs(
        min_reserve_native_wei=int(ONMI_SWAP_MIN_RESERVE_NATIVE_WEI),
    )
    if not pairs:
        log_simple("⚠ Список пар пуст — делаю factory scan...", "info")
        refresh_pairs_cache(records=records)
        pairs = swap_db.list_known_pairs(
            min_reserve_native_wei=int(ONMI_SWAP_MIN_RESERVE_NATIVE_WEI),
        )
    if not pairs:
        log_simple("Не удалось получить пары", "error")
        return {"ops": 0, "adds": 0, "failures": 0}

    eligible = [r for r in records if (r.get("private_key") or "").strip()]
    if not eligible:
        log_simple("Нет кошельков с private_key", "error")
        return {"ops": 0, "adds": 0, "failures": 0}

    wallets = list(eligible)
    if SHUFLE_ACCOUNTS:
        random.shuffle(wallets)

    ops_lo, ops_hi = ONMI_LIQ_OPS_PER_WALLET_RANGE
    if total_ops_override is not None:
        per_wallet_plan = [int(total_ops_override)] * len(wallets)
    else:
        per_wallet_plan = [
            random.randint(int(ops_lo), int(ops_hi)) for _ in wallets
        ]
    total_ops = sum(per_wallet_plan)
    log_simple(
        f"💧 LP add session: {len(wallets)} кошельков · "
        f"{total_ops} операций ({ops_lo}..{ops_hi} на кошелёк) · "
        f"{len(pairs)} пар",
        "info",
    )

    min_native_wei = int(float(ONMI_LIQ_MIN_NATIVE_BALANCE) * 1e18)
    gas_reserve_wei = int(float(ONMI_LIQ_GAS_RESERVE) * 1e18)
    val_lo, val_hi = ONMI_LIQ_ADD_VALUE_RANGE
    sleep_lo, sleep_hi = ONMI_LIQ_SLEEP_BETWEEN_OPS
    attempts_per_op = max(1, int(ONMI_LIQ_TX_ATTEMPTS))
    slippage = float(ONMI_LIQ_SLIPPAGE)

    adds = failures = ops_done = 0
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
        wallet_skips = 0
        for _w_op in range(ops_for_wallet):
         op_idx += 1
         if wallet_skips >= 5:
             break
         try:
            addr = account.address
            name = record.get("name") or None

            try:
                native_wei = _native_balance(addr, record)
            except sc.SwapError as e:
                log_wallet_task(addr, op_idx, total_ops,
                                f"⚠ native: {e}", "warning",
                                account_name=name)
                wallet_skips += 1
                continue
            if native_wei < min_native_wei + gas_reserve_wei:
                log_wallet_task(
                    addr, op_idx, total_ops,
                    f"⏭ native {native_wei/1e18:.6f} < min — skip wallet",
                    "warning", account_name=name,
                )
                break

            pair = random.choice(pairs)
            token_addr = pair["token_address"]
            symbol = pair.get("token_symbol") or "?"
            pair_addr = pair["pair_address"]

            # Бюджет (clamp под available)
            N = int(random.uniform(float(val_lo), float(val_hi)) * 1e18)
            spendable = max(0, native_wei - gas_reserve_wei)
            if N > spendable:
                N = spendable
            min_total = int(float(val_lo) * 1e18 * 0.5)
            if N < min_total:
                wallet_skips += 1
                continue
            buy_part = N // 2
            add_eth_part = N - buy_part
            wallet_skips = 0

            log_wallet_task(
                addr, op_idx, total_ops,
                f"📤 LP-ADD {symbol} · budget={N/1e18:.6f} zkLTC "
                f"(buy {buy_part/1e18:.6f} + add {add_eth_part/1e18:.6f})",
                "info", account_name=name,
            )

            proxy = _primary_proxy(record)
            deadline_ts = int(time.time()) + int(ONMI_LIQ_DEADLINE_SEC)

            # --- 1) buy needed token via swap router
            try:
                quote = sc.get_amounts_out(
                    int(buy_part),
                    [Web3.to_checksum_address(p) for p in
                     [pair["weth_address"], token_addr]],
                    proxy=proxy,
                )
                expected_token = int(quote[-1])
                min_out_buy = int(expected_token * (1.0 - slippage))
                if min_out_buy <= 0:
                    min_out_buy = 1
                buy_tx, _, token_received = sc.swap_exact_eth_for_tokens(
                    account=account, token=token_addr,
                    value_wei=int(buy_part), min_out_wei=int(min_out_buy),
                    deadline_ts=deadline_ts, proxy=proxy,
                )
                log_wallet_task(
                    addr, op_idx, total_ops,
                    f"   • pre-buy {token_received/1e18:.4f} {symbol} · "
                    f"tx={_short_tx(buy_tx)}",
                    "info", account_name=name,
                )
            except sc.SwapError as e:
                log_wallet_task(addr, op_idx, total_ops,
                                f"⚠ pre-buy failed: {e}", "warning",
                                account_name=name)
                failures += 1
                continue

            if token_received <= 0:
                failures += 1
                continue

            # --- 2) addLiquidityETH
            history_id = db.insert_history(
                wallet_address=addr, wallet_name=name,
                pair_address=pair_addr, token_address=token_addr,
                token_symbol=symbol, side="add",
                amount_eth_wei=add_eth_part,
                amount_token_wei=token_received, lp_tokens_wei=0,
            )
            amount_token_min = int(token_received * (1.0 - slippage))
            amount_eth_min = int(add_eth_part * (1.0 - slippage))

            tx_hash: Optional[str] = None
            receipt: Optional[dict] = None
            lp_received = 0
            last_err: Optional[str] = None
            for attempt in range(1, attempts_per_op + 1):
                db.update_history(history_id, status="sent", attempts=attempt,
                                  sent_at=time.time())
                try:
                    tx_hash, receipt, lp_received = sc.add_liquidity_eth(
                        account=account, token=token_addr,
                        amount_token_desired=int(token_received),
                        value_wei=int(add_eth_part),
                        amount_token_min=int(amount_token_min),
                        amount_eth_min=int(amount_eth_min),
                        deadline_ts=deadline_ts, proxy=proxy,
                    )
                    break
                except sc.SwapError as e:
                    last_err = str(e)
                    log_wallet_task(
                        addr, op_idx, total_ops,
                        f"⚠ add attempt {attempt}/{attempts_per_op}: {e}",
                        "warning", account_name=name,
                    )
                    if attempt < attempts_per_op:
                        time.sleep(min(15, 3 * attempt))

            if tx_hash is None or receipt is None:
                db.update_history(history_id, status="failed",
                                  error_message=(last_err or "unknown")[:500])
                failures += 1
                log_wallet_task(
                    addr, op_idx, total_ops,
                    f"❌ LP-ADD failed: {last_err}",
                    "error", account_name=name,
                )
            else:
                gas_used = int(receipt.get("gasUsed") or 0)
                db.update_history(
                    history_id, tx_hash=tx_hash, gas_used=gas_used,
                    lp_tokens_wei=str(int(lp_received)),
                    status="arrived", confirmed_at=time.time(),
                )
                db.upsert_position_after_add(
                    wallet_address=addr, pair_address=pair_addr,
                    token_address=token_addr, token_symbol=symbol,
                    eth_added_wei=int(add_eth_part),
                    token_added_wei=int(token_received),
                    lp_received_wei=int(lp_received),
                )
                log_wallet_task(
                    addr, op_idx, total_ops,
                    f"✅ LP-ADD · tx={_short_tx(tx_hash)} · gas={gas_used} "
                    f"· LP={lp_received/1e18:.6f}",
                    "success", account_name=name,
                )
                adds += 1

            ops_done += 1
            time.sleep(random.uniform(float(sleep_lo), float(sleep_hi)))

         except KeyboardInterrupt:
             raise
         except Exception as e:  # noqa: BLE001
             log_simple(f"⚠ op {op_idx} unexpected: {e}", "warning")
             failures += 1
             wallet_skips += 1
             continue
    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем", "warning")
        interrupted = True

    summary = {
        "ops": ops_done, "adds": adds, "failures": failures,
        "interrupted": interrupted,
    }
    log_simple(
        f"🏁 LP-add session done · ops={ops_done} adds={adds} "
        f"failures={failures}",
        "success" if not interrupted else "warning",
    )
    return summary


# ---------------------------------------------------------------------------
# REMOVE-ALL (one button)
# ---------------------------------------------------------------------------

def _candidate_pairs_for_wallet(wallet_addr: str) -> list[dict]:
    """Объединяем positions из БД и весь pair-кэш swap-модуля.

    Дубликаты по pair_address фильтруются. Каждый dict содержит
    pair_address, token_address, token_symbol.
    """
    out: dict[str, dict] = {}
    for p in db.list_positions(wallet_address=wallet_addr, with_lp_only=False):
        out[p["pair_address"].lower()] = {
            "pair_address": p["pair_address"],
            "token_address": p["token_address"],
            "token_symbol": p.get("token_symbol") or "",
        }
    # fallback: все известные пары
    for p in swap_db.list_known_pairs(only_enabled=False):
        key = p["pair_address"].lower()
        if key not in out:
            out[key] = {
                "pair_address": p["pair_address"],
                "token_address": p["token_address"],
                "token_symbol": p.get("token_symbol") or "",
            }
    return list(out.values())


def run_withdraw_all(records: list[dict]) -> dict:
    """Для каждого кошелька удаляет всю LP-ликвидность.

    Шаги:
      1. список кандидатных пар = positions ∪ known_pairs
      2. для каждой pair проверяем on-chain pair.balanceOf(wallet)
      3. если > 0 — approve + removeLiquidityETH(amountMin=0)
    """
    db.init_database()
    swap_db.init_database()

    eligible = [r for r in records if (r.get("private_key") or "").strip()]
    if not eligible:
        log_simple("Нет кошельков с private_key", "error")
        return {"wallets": 0, "removed": 0, "skipped": 0, "failures": 0}

    log_simple(
        f"🧹 LP withdraw-all: {len(eligible)} кошельков", "info",
    )

    removed_total = failures = skipped = 0
    interrupted = False
    deadline_ts = int(time.time()) + int(ONMI_LIQ_DEADLINE_SEC)

    for w_idx, record in enumerate(eligible, 1):
        try:
            account = _account_from_record(record)
            if account is None:
                continue
            addr = account.address
            name = record.get("name") or None
            proxy = _primary_proxy(record)

            candidates = _candidate_pairs_for_wallet(addr)
            log_wallet_task(
                addr, w_idx, len(eligible),
                f"🔎 проверка {len(candidates)} пар",
                "info", account_name=name,
            )

            for p in candidates:
                pair_addr = p["pair_address"]
                token_addr = p["token_address"]
                symbol = p.get("token_symbol") or "?"
                try:
                    lp_bal = sc.get_lp_balance(pair_addr, addr, proxy=proxy)
                except Exception as e:
                    log_wallet_task(addr, w_idx, len(eligible),
                                    f"⚠ balanceOf({pair_addr[:10]}…): {e}",
                                    "warning", account_name=name)
                    continue
                if lp_bal <= 0:
                    skipped += 1
                    continue

                history_id = db.insert_history(
                    wallet_address=addr, wallet_name=name,
                    pair_address=pair_addr, token_address=token_addr,
                    token_symbol=symbol, side="remove",
                    amount_eth_wei=0, amount_token_wei=0,
                    lp_tokens_wei=lp_bal,
                )
                log_wallet_task(
                    addr, w_idx, len(eligible),
                    f"📤 remove {symbol} · LP={lp_bal/1e18:.6f}",
                    "info", account_name=name,
                )

                try:
                    tx_hash, receipt, eth_recv, tok_recv = sc.remove_liquidity_eth(
                        account=account, token=token_addr,
                        liquidity_wei=int(lp_bal),
                        amount_token_min=0, amount_eth_min=0,
                        deadline_ts=int(time.time()) + int(ONMI_LIQ_DEADLINE_SEC),
                        proxy=proxy,
                    )
                except sc.SwapError as e:
                    db.update_history(history_id, status="failed",
                                      error_message=str(e)[:500])
                    failures += 1
                    log_wallet_task(addr, w_idx, len(eligible),
                                    f"❌ remove failed: {e}", "error",
                                    account_name=name)
                    continue

                gas_used = int(receipt.get("gasUsed") or 0)
                db.update_history(
                    history_id, tx_hash=tx_hash, gas_used=gas_used,
                    amount_eth_wei=str(int(eth_recv)),
                    amount_token_wei=str(int(tok_recv)),
                    status="arrived", confirmed_at=time.time(),
                )
                db.upsert_position_after_remove(
                    wallet_address=addr, pair_address=pair_addr,
                    token_address=token_addr, token_symbol=symbol,
                    eth_received_wei=int(eth_recv),
                    token_received_wei=int(tok_recv),
                    lp_burned_wei=int(lp_bal),
                )
                log_wallet_task(
                    addr, w_idx, len(eligible),
                    f"✅ remove · tx={_short_tx(tx_hash)} · "
                    f"eth={eth_recv/1e18:.6f} · {symbol}={tok_recv/1e18:.4f}",
                    "success", account_name=name,
                )
                removed_total += 1
                time.sleep(random.uniform(1.0, 4.0))

        except KeyboardInterrupt:
            log_simple("⚠ прервано пользователем", "warning")
            interrupted = True
            break
        except Exception as e:  # noqa: BLE001
            log_simple(f"⚠ wallet {w_idx} error: {e}", "warning")
            failures += 1
            continue

    log_simple(
        f"🏁 withdraw-all done · removed={removed_total} skipped={skipped} "
        f"failures={failures}",
        "success" if not interrupted else "warning",
    )
    return {
        "wallets": len(eligible), "removed": removed_total,
        "skipped": skipped, "failures": failures,
        "interrupted": interrupted,
    }
