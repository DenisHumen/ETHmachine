"""Onmi swap · random-walk session (UniswapV2 AMM).

Стратегия по образу trade/worker.py:
  • за сессию совершаем случайное число операций;
  • на каждой итерации:
      1. случайный кошелёк (с private_key + native ≥ min);
      2. случайная graduated-pair из onmi_swap_known_pairs (резерв ≥ threshold);
      3. если у кошелька есть token-баланс > dust → SELL с prob_sell, иначе BUY;
      4. для BUY: random value в ONMI_SWAP_NATIVE_VALUE_RANGE (clamp под доступный native);
         для SELL: pct баланса токена;
      5. min_out_wei считается через router.getAmountsOut с slippage;
      6. отправляем tx, логируем, спим случайное время.

Всегда сначала вызываем `discover_pairs` если кэш пуст или маленький.
"""
from __future__ import annotations

import random
import time
from typing import Optional

from config.modules.cfg_litvm_testnet import (
    ONMI_SWAP_ERC20_DUST_WEI,
    ONMI_SWAP_DEADLINE_SEC,
    ONMI_SWAP_GAS_RESERVE,
    ONMI_SWAP_MIN_NATIVE_BALANCE,
    ONMI_SWAP_MIN_RESERVE_NATIVE_WEI,
    ONMI_SWAP_NATIVE_VALUE_RANGE,
    ONMI_SWAP_OPS_PER_WALLET_RANGE,
    ONMI_SWAP_PROB_SELL_IF_HAS,
    ONMI_SWAP_SELL_PCT_RANGE,
    ONMI_SWAP_SLEEP_BETWEEN_OPS,
    ONMI_SWAP_SLIPPAGE,
    ONMI_SWAP_TX_ATTEMPTS,
    ONMI_SWAP_WETH,
)
from config.modules.general_config import SHUFLE_ACCOUNTS
from modules.simple_logger import log_simple, log_wallet_task
from modules.litvm_testnet.onmi.swap import database as db
from modules.litvm_testnet.onmi.swap import swap_client as sc


# ---------------------------------------------------------------------------
# Helpers
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


def _native_balance(addr: str, rec: dict) -> tuple[int, Optional[str]]:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(rec):
        try:
            return sc.get_native_balance_wei(addr, proxy), proxy
        except Exception as e:
            last_err = e
    raise sc.SwapError(f"native balance fetch failed: {last_err}")


def _token_balance(token: str, addr: str, rec: dict) -> int:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(rec):
        try:
            return sc.get_erc20_balance(token, addr, proxy)
        except Exception as e:
            last_err = e
    raise sc.SwapError(f"token balance fetch failed: {last_err}")


# ---------------------------------------------------------------------------
# Pair discovery (caches into DB)
# ---------------------------------------------------------------------------

def refresh_pairs_cache(*, records: list[dict],
                        max_pairs: Optional[int] = None) -> int:
    """Перечитывает factory.allPairs и кэширует в onmi_swap_known_pairs.

    Использует первый доступный proxy_chain из записей.
    Возвращает число добавленных/обновлённых пар.
    """
    db.init_database()
    proxies_to_try: list[Optional[str]] = []
    seen = set()
    for r in records:
        for p in _proxy_chain(r):
            k = (p or "").strip()
            if k in seen:
                continue
            proxies_to_try.append(p)
            seen.add(k)
    if not proxies_to_try:
        proxies_to_try = [None]

    def _on_pair(d: dict) -> None:
        db.upsert_pair(
            pair_address=d["pair_address"],
            token_address=d["token_address"],
            token_symbol=d.get("token_symbol") or "",
            token_decimals=int(d.get("token_decimals") or 18),
            weth_address=d["weth_address"],
            reserve_native_wei=int(d["reserve_native_wei"]),
            reserve_token_wei=int(d["reserve_token_wei"]),
        )

    last_err: Optional[Exception] = None
    for proxy in proxies_to_try:
        try:
            log_simple("🔎 OnmiSwap: сканирую factory.allPairs…", "info")
            last_logged = [0]

            def _on_progress(i: int, n: int, accepted: int) -> None:
                # Лог каждые 10 пар + первая + последняя
                if i == 1 or i == n or i - last_logged[0] >= 10:
                    last_logged[0] = i
                    log_simple(
                        f"   pair {i}/{n} · принято {accepted}",
                        "info",
                    )

            count = sc.discover_pairs(
                proxy=proxy, limit=max_pairs, on_pair=_on_pair,
                on_progress=_on_progress,
            )
            log_simple(
                f"🔎 OnmiSwap: обнаружено {count} активных WETH-пар",
                "success",
            )
            return count
        except Exception as e:
            last_err = e
            continue
    log_simple(f"⚠ discover_pairs failed: {last_err}", "error")
    return 0


# ---------------------------------------------------------------------------
# Main session
# ---------------------------------------------------------------------------

def run_random_session(
    records: list[dict],
    *,
    total_ops_override: Optional[int] = None,
) -> dict:
    """Каждый кошелёк делает random.randint(ONMI_SWAP_OPS_PER_WALLET_RANGE)
    свапов на случайных парах со случайными суммами.

    `total_ops_override` — если задан, используется как фиксированное число
    операций НА КАЖДЫЙ кошелёк (а не суммарно).
    """
    db.init_database()

    pairs = db.list_known_pairs(
        min_reserve_native_wei=int(ONMI_SWAP_MIN_RESERVE_NATIVE_WEI),
    )
    if not pairs:
        log_simple(
            "⚠ В onmi_swap_known_pairs нет пар. Запусти «🔎 Обновить пары» "
            "из меню (или будет авто-discover сейчас).",
            "warning",
        )
        refresh_pairs_cache(records=records)
        pairs = db.list_known_pairs(
            min_reserve_native_wei=int(ONMI_SWAP_MIN_RESERVE_NATIVE_WEI),
        )
        if not pairs:
            log_simple("Не удалось получить список пар", "error")
            return {"ops": 0, "buys": 0, "sells": 0, "failures": 0}

    eligible = [r for r in records if (r.get("private_key") or "").strip()]
    if not eligible:
        log_simple("Нет кошельков с private_key", "error")
        return {"ops": 0, "buys": 0, "sells": 0, "failures": 0}

    wallets = list(eligible)
    if SHUFLE_ACCOUNTS:
        random.shuffle(wallets)

    ops_lo, ops_hi = ONMI_SWAP_OPS_PER_WALLET_RANGE
    # план: сколько ops у каждого кошелька
    if total_ops_override is not None:
        per_wallet_plan = [int(total_ops_override)] * len(wallets)
    else:
        per_wallet_plan = [
            random.randint(int(ops_lo), int(ops_hi)) for _ in wallets
        ]
    total_ops = sum(per_wallet_plan)

    log_simple(
        f"🎲 OnmiSwap session: {len(wallets)} кошельков · "
        f"{total_ops} операций ({ops_lo}..{ops_hi} на кошелёк) · "
        f"{len(pairs)} пар",
        "info",
    )

    min_native_wei = int(float(ONMI_SWAP_MIN_NATIVE_BALANCE) * 1e18)
    gas_reserve_wei = int(float(ONMI_SWAP_GAS_RESERVE) * 1e18)
    dust = int(ONMI_SWAP_ERC20_DUST_WEI)
    buy_lo, buy_hi = ONMI_SWAP_NATIVE_VALUE_RANGE
    sell_lo_pct, sell_hi_pct = ONMI_SWAP_SELL_PCT_RANGE
    sleep_lo, sleep_hi = ONMI_SWAP_SLEEP_BETWEEN_OPS
    attempts_per_op = max(1, int(ONMI_SWAP_TX_ATTEMPTS))
    prob_sell = float(ONMI_SWAP_PROB_SELL_IF_HAS)
    slippage = float(ONMI_SWAP_SLIPPAGE)

    buys = sells = failures = ops_done = 0
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

            # native check 1 раз на кошелёк
            try:
                native_wei, _ = _native_balance(addr, record)
            except sc.SwapError as e:
                op_idx += 1  # покажем в логе
                log_wallet_task(addr, op_idx, total_ops,
                                f"⚠ native balance: {e} — skip wallet",
                                "warning", account_name=name)
                continue
            if native_wei < min_native_wei:
                op_idx += 1
                log_wallet_task(
                    addr, op_idx, total_ops,
                    f"⏭ native {native_wei/1e18:.6f} < min "
                    f"{ONMI_SWAP_MIN_NATIVE_BALANCE} — skip wallet",
                    "warning", account_name=name,
                )
                continue

            wallet_skips = 0
            for w_op in range(ops_for_wallet):
                op_idx += 1
                if wallet_skips >= 5:
                    # уходим к следующему кошельку, если у этого всё пропускается
                    break
                try:
                    # refresh native между операциями
                    try:
                        native_wei, _ = _native_balance(addr, record)
                    except sc.SwapError:
                        pass
                    if native_wei < min_native_wei:
                        break

                    # случайная пара
                    pair = random.choice(pairs)
                    token_addr = pair["token_address"]
                    symbol = pair.get("token_symbol") or "?"

                    # token balance?
                    try:
                        tok_bal = _token_balance(token_addr, addr, record)
                    except sc.SwapError:
                        tok_bal = 0

                    if tok_bal > dust and random.random() < prob_sell:
                        side = "sell"
                    else:
                        side = "buy"

                    # размер
                    if side == "buy":
                        amt_native = random.uniform(float(buy_lo), float(buy_hi))
                        amount_in_wei = int(amt_native * 1e18)
                        spendable = max(0, native_wei - gas_reserve_wei)
                        if amount_in_wei > spendable:
                            amount_in_wei = spendable
                        if amount_in_wei < int(float(buy_lo) * 1e18 * 0.3):
                            wallet_skips += 1
                            continue
                        path = [ONMI_SWAP_WETH, token_addr]
                    else:
                        pct = random.uniform(
                            float(sell_lo_pct), float(sell_hi_pct))
                        amount_in_wei = int(tok_bal * pct / 100.0)
                        if amount_in_wei < dust:
                            amount_in_wei = tok_bal
                        if amount_in_wei < dust:
                            wallet_skips += 1
                            continue
                        path = [token_addr, ONMI_SWAP_WETH]

                    # min_out
                    try:
                        quote = sc.get_amounts_out(
                            int(amount_in_wei), path,
                            proxy=_primary_proxy(record),
                        )
                        expected_out = int(quote[-1])
                        min_out = int(expected_out * (1.0 - slippage))
                        if min_out <= 0:
                            min_out = 1
                    except Exception as e:
                        log_wallet_task(addr, op_idx, total_ops,
                                        f"⚠ quote failed: {e}", "warning",
                                        account_name=name)
                        wallet_skips += 1
                        continue

                    wallet_skips = 0
                    swap_id = db.insert_swap(
                        wallet_address=addr, wallet_name=name,
                        pair_address=pair["pair_address"],
                        token_address=token_addr,
                        token_symbol=symbol, side=side,
                        amount_in_wei=amount_in_wei, min_out_wei=min_out,
                    )

                    human_in = (f"{amount_in_wei/1e18:.6f} zkLTC"
                                if side == "buy"
                                else f"{amount_in_wei/1e18:.4f} {symbol}")
                    log_wallet_task(
                        addr, op_idx, total_ops,
                        f"📤 SWAP {side.upper()} {symbol} · in={human_in} · "
                        f"minOut={min_out}",
                        "info", account_name=name,
                    )

                    tx_hash: Optional[str] = None
                    receipt: Optional[dict] = None
                    amount_out = 0
                    last_err: Optional[str] = None
                    deadline_ts = int(time.time()) + int(ONMI_SWAP_DEADLINE_SEC)

                    for attempt in range(1, attempts_per_op + 1):
                        db.update_swap(swap_id, status="sent", attempts=attempt,
                                       sent_at=time.time())
                        try:
                            proxy = _primary_proxy(record)
                            if side == "buy":
                                tx_hash, receipt, amount_out = (
                                    sc.swap_exact_eth_for_tokens(
                                        account=account, token=token_addr,
                                        value_wei=int(amount_in_wei),
                                        min_out_wei=int(min_out),
                                        deadline_ts=deadline_ts, proxy=proxy,
                                    )
                                )
                            else:
                                tx_hash, receipt, amount_out = (
                                    sc.swap_exact_tokens_for_eth(
                                        account=account, token=token_addr,
                                        amount_in_wei=int(amount_in_wei),
                                        min_out_wei=int(min_out),
                                        deadline_ts=deadline_ts, proxy=proxy,
                                    )
                                )
                            break
                        except sc.SwapError as e:
                            last_err = str(e)
                            log_wallet_task(
                                addr, op_idx, total_ops,
                                f"⚠ attempt {attempt}/{attempts_per_op}: {e}",
                                "warning", account_name=name,
                            )
                            if attempt < attempts_per_op:
                                time.sleep(min(15, 3 * attempt))

                    if tx_hash is None or receipt is None:
                        db.update_swap(
                            swap_id, status="failed",
                            error_message=(last_err or "unknown")[:500],
                        )
                        failures += 1
                        log_wallet_task(
                            addr, op_idx, total_ops,
                            f"❌ SWAP {side.upper()} failed: {last_err}",
                            "error", account_name=name,
                        )
                    else:
                        gas_used = int(receipt.get("gasUsed") or 0)
                        db.update_swap(
                            swap_id, tx_hash=tx_hash, gas_used=gas_used,
                            amount_out_wei=str(int(amount_out)),
                            status="arrived", confirmed_at=time.time(),
                        )
                        out_human = (f"{amount_out/1e18:.4f} {symbol}"
                                     if side == "buy"
                                     else f"{amount_out/1e18:.6f} zkLTC")
                        log_wallet_task(
                            addr, op_idx, total_ops,
                            f"✅ SWAP {side.upper()} · "
                            f"tx={_short_tx(tx_hash)} · gas={gas_used} · "
                            f"out={out_human}",
                            "success", account_name=name,
                        )
                        if side == "buy":
                            buys += 1
                        else:
                            sells += 1

                    ops_done += 1
                    time.sleep(random.uniform(float(sleep_lo), float(sleep_hi)))

                except Exception as e:  # noqa: BLE001
                    log_wallet_task(
                        addr, op_idx, total_ops,
                        f"⚠ op error: {e}", "warning", account_name=name,
                    )
                    failures += 1
                    wallet_skips += 1
                    continue

    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем", "warning")
        interrupted = True

    summary = {
        "ops": ops_done, "buys": buys, "sells": sells,
        "failures": failures, "interrupted": interrupted,
    }
    log_simple(
        f"🏁 swap session done · ops={ops_done} buys={buys} sells={sells} "
        f"failures={failures}",
        "success" if not interrupted else "warning",
    )
    return summary
