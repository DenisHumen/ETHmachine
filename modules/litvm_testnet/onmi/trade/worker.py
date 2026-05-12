"""Onmi trade · random-walk session.

Стратегия (выглядит «живой»):
  • за сессию совершаем случайное число операций (uniform N из
    ONMI_TRADE_TOTAL_OPS_RANGE);
  • на каждой итерации:
      1. выбираем случайный кошелёк (из data.csv, с private_key + native ≥ min);
      2. выбираем случайный токен из onmi_known_tokens (или из портфеля
         кошелька с вероятностью ONMI_TRADE_PROB_REUSE_PORTFOLIO_TOKEN);
      3. если у кошелька есть token-баланс > dust:
            sell с вероятностью ONMI_TRADE_PROB_SELL_IF_HAS, иначе buy;
         иначе → buy;
      4. для buy: random value в ONMI_TRADE_BUY_VALUE_RANGE_ZKLTC (clamp под
         оставшийся native − gas reserve); для sell — pct баланса токена;
      5. отправляем tx, лоигируем, спим случайное время.

Состояние идемпотентно — все попытки пишутся в onmi_trade_history, любая ошибка
не валит всю сессию (логируется и продолжаем).
"""
from __future__ import annotations

import random
import time
from typing import Optional

from config.modules.cfg_litvm_testnet import (
    ONMI_TRADE_BUY_VALUE_RANGE_ZKLTC,
    ONMI_TRADE_ERC20_DUST_WEI,
    ONMI_TRADE_GAS_RESERVE_ZKLTC,
    ONMI_TRADE_MIN_NATIVE_BALANCE_ZKLTC,
    ONMI_TRADE_PROB_REUSE_PORTFOLIO_TOKEN,
    ONMI_TRADE_PROB_SELL_IF_HAS,
    ONMI_TRADE_SELL_PCT_RANGE,
    ONMI_TRADE_SLEEP_BETWEEN_OPS,
    ONMI_TRADE_TOTAL_OPS_RANGE,
    ONMI_TRADE_TX_ATTEMPTS,
)
from modules.simple_logger import log_simple, log_wallet_task
from modules.litvm_testnet.onmi.trade import database as db
from modules.litvm_testnet.onmi.trade import trade_client as tc


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
        return tc.account_from_private_key(pk)
    except Exception as e:  # noqa: BLE001
        log_simple(f"⚠ невалидный private_key: {e}", "warning")
        return None


def _native_balance_with_fallback(address: str,
                                  record: dict) -> tuple[int, Optional[str]]:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(record):
        try:
            return tc.get_native_balance_wei(address, proxy), proxy
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise tc.TradeError(f"native balance fetch failed: {last_err}")


def _token_balance_with_fallback(token: str, owner: str,
                                 record: dict) -> int:
    last_err: Optional[Exception] = None
    for proxy in _proxy_chain(record):
        try:
            return tc.get_token_balance(token, owner, proxy)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise tc.TradeError(f"token balance fetch failed: {last_err}")


# ---------------------------------------------------------------------------
# Main session
# ---------------------------------------------------------------------------

def run_random_session(
    records: list[dict],
    *,
    total_ops_override: Optional[int] = None,
) -> dict:
    """Главный random-walk цикл.

    records: список dict'ов из data.csv (поля name/private_key/proxy/reserve_proxy).
    total_ops_override: если задано — используется вместо случайного выбора.

    Returns dict с финальной статистикой сессии.
    """
    db.init_database()

    known = db.list_known_tokens(include_graduated=False)
    if not known:
        log_simple(
            "⚠ В onmi_known_tokens нет токенов. Сначала создай монеты модулем "
            "Onmi (или дождись seed из onmi_coin_tasks).",
            "warning",
        )
        return {"ops": 0, "buys": 0, "sells": 0, "failures": 0}

    eligible = [r for r in records if (r.get("private_key") or "").strip()]
    if not eligible:
        log_simple("Нет кошельков с private_key", "error")
        return {"ops": 0, "buys": 0, "sells": 0, "failures": 0}

    lo, hi = ONMI_TRADE_TOTAL_OPS_RANGE
    total_ops = int(total_ops_override) if total_ops_override else random.randint(
        int(lo), int(hi))
    log_simple(
        f"🎲 Onmi trade session: {total_ops} операций · "
        f"{len(known)} токенов · {len(eligible)} кошельков",
        "info",
    )

    min_native_wei = int(float(ONMI_TRADE_MIN_NATIVE_BALANCE_ZKLTC) * 1e18)
    gas_reserve_wei = int(float(ONMI_TRADE_GAS_RESERVE_ZKLTC) * 1e18)
    dust = int(ONMI_TRADE_ERC20_DUST_WEI)
    buy_lo, buy_hi = ONMI_TRADE_BUY_VALUE_RANGE_ZKLTC
    sell_lo_pct, sell_hi_pct = ONMI_TRADE_SELL_PCT_RANGE
    sleep_lo, sleep_hi = ONMI_TRADE_SLEEP_BETWEEN_OPS
    attempts_per_op = max(1, int(ONMI_TRADE_TX_ATTEMPTS))
    prob_sell = float(ONMI_TRADE_PROB_SELL_IF_HAS)
    prob_reuse = float(ONMI_TRADE_PROB_REUSE_PORTFOLIO_TOKEN)

    buys = sells = failures = ops_done = 0
    interrupted = False
    consecutive_skips = 0
    MAX_CONSECUTIVE_SKIPS = max(50, total_ops * 3)

    for op_idx in range(1, total_ops + 1):
        if consecutive_skips >= MAX_CONSECUTIVE_SKIPS:
            log_simple(
                f"⚠ слишком много подряд пропущенных попыток "
                f"({consecutive_skips}) — завершаю сессию",
                "warning",
            )
            break

        try:
            record = random.choice(eligible)
            account = _account_from_record(record)
            if account is None:
                consecutive_skips += 1
                continue
            address = account.address
            account_name = record.get("name") or None

            # --- native баланс
            try:
                native_wei, _ = _native_balance_with_fallback(address, record)
            except tc.TradeError as e:
                log_wallet_task(
                    address, op_idx, total_ops,
                    f"⚠ native balance: {e}", "warning",
                    account_name=account_name,
                )
                consecutive_skips += 1
                continue

            if native_wei < min_native_wei:
                consecutive_skips += 1
                continue

            # --- выбор токена
            chosen_token: Optional[dict] = None
            chosen_side: Optional[str] = None
            chosen_token_balance: int = 0

            # 1) с вероятностью prob_reuse — попробуем токен из портфеля
            if random.random() < prob_reuse:
                portfolio_candidates = list(known)
                random.shuffle(portfolio_candidates)
                for tok in portfolio_candidates[:8]:  # не более 8 проб, чтобы не молотить RPC
                    try:
                        bal = _token_balance_with_fallback(
                            tok["address"], address, record)
                    except tc.TradeError:
                        continue
                    if bal > dust:
                        chosen_token = tok
                        chosen_token_balance = bal
                        # с prob_sell — продаём, иначе докупим
                        chosen_side = "sell" if random.random() < prob_sell else "buy"
                        break

            # 2) если портфель не сработал — берём случайный токен и покупаем
            if chosen_token is None:
                chosen_token = random.choice(known)
                chosen_side = "buy"

            assert chosen_token is not None and chosen_side in ("buy", "sell")
            token_addr = chosen_token["address"]
            token_symbol = chosen_token.get("symbol") or "?"

            # --- размер
            if chosen_side == "buy":
                amount_native = random.uniform(float(buy_lo), float(buy_hi))
                amount_in_wei = int(amount_native * 1e18)
                # clamp под available
                spendable = max(0, native_wei - gas_reserve_wei)
                if amount_in_wei > spendable:
                    amount_in_wei = spendable
                if amount_in_wei < int(float(buy_lo) * 1e18 * 0.3):
                    # денег не хватает — пропускаем
                    consecutive_skips += 1
                    continue
            else:  # sell
                pct = random.uniform(float(sell_lo_pct), float(sell_hi_pct))
                amount_in_wei = int(chosen_token_balance * pct / 100.0)
                # клипануть, чтобы не было 0
                if amount_in_wei < dust:
                    amount_in_wei = chosen_token_balance  # продай всё что есть
                if amount_in_wei < dust:
                    consecutive_skips += 1
                    continue

            consecutive_skips = 0

            # --- запись в БД (pending)
            trade_id = db.insert_trade(
                wallet_address=address, wallet_name=account_name,
                token_address=token_addr, token_symbol=token_symbol,
                side=chosen_side, amount_in_wei=amount_in_wei,
            )

            human_amount = (
                f"{amount_in_wei/1e18:.6f} zkLTC" if chosen_side == "buy"
                else f"{amount_in_wei/1e18:.2f} {token_symbol}"
            )
            log_wallet_task(
                address, op_idx, total_ops,
                f"📤 {chosen_side.upper()} {token_symbol} · {human_amount}",
                "info", account_name=account_name,
            )

            # --- exec
            last_err: Optional[str] = None
            tx_hash: Optional[str] = None
            receipt: Optional[dict] = None
            amount_out_wei = 0

            for attempt in range(1, attempts_per_op + 1):
                db.update_trade(trade_id, status="sent",
                                attempts=attempt, sent_at=time.time())
                try:
                    proxy = _primary_proxy(record)
                    if chosen_side == "buy":
                        tx_hash, receipt, amount_out_wei = tc.buy_exact_in(
                            account=account, token=token_addr,
                            value_wei=int(amount_in_wei), proxy=proxy,
                        )
                    else:
                        tx_hash, receipt, amount_out_wei = tc.sell_exact_in(
                            account=account, token=token_addr,
                            token_amount_wei=int(amount_in_wei), proxy=proxy,
                        )
                    break
                except tc.TradeError as e:
                    last_err = str(e)
                    msg = str(e).lower()
                    # если token graduated — пометить и больше не торговать
                    if "graduated" in msg:
                        db.mark_token_graduated(token_addr)
                        log_wallet_task(
                            address, op_idx, total_ops,
                            f"⚠ {token_symbol} graduated — pruning",
                            "warning", account_name=account_name,
                        )
                        # перечитаем known tokens
                        known = db.list_known_tokens(include_graduated=False)
                        break
                    log_wallet_task(
                        address, op_idx, total_ops,
                        f"⚠ attempt {attempt}/{attempts_per_op}: {e}",
                        "warning", account_name=account_name,
                    )
                    if attempt < attempts_per_op:
                        time.sleep(min(15, 3 * attempt))

            if tx_hash is None or receipt is None:
                db.update_trade(
                    trade_id, status="failed",
                    error_message=(last_err or "unknown")[:500],
                )
                failures += 1
                log_wallet_task(
                    address, op_idx, total_ops,
                    f"❌ {chosen_side.upper()} failed: {last_err}",
                    "error", account_name=account_name,
                )
            else:
                gas_used = int(receipt.get("gasUsed") or 0)
                db.update_trade(
                    trade_id,
                    tx_hash=tx_hash,
                    gas_used=gas_used,
                    amount_out_wei=str(int(amount_out_wei)),
                    status="arrived", confirmed_at=time.time(),
                )
                out_human = (
                    f"{amount_out_wei/1e18:.4f} {token_symbol}"
                    if chosen_side == "buy"
                    else f"{amount_out_wei/1e18:.6f} zkLTC"
                )
                log_wallet_task(
                    address, op_idx, total_ops,
                    f"✅ {chosen_side.upper()} · tx={_short_tx(tx_hash)} · "
                    f"gas={gas_used} · out={out_human}",
                    "success", account_name=account_name,
                )
                if chosen_side == "buy":
                    buys += 1
                else:
                    sells += 1

            ops_done += 1

            # --- рандом-пауза
            sleep_s = random.uniform(float(sleep_lo), float(sleep_hi))
            time.sleep(sleep_s)

        except KeyboardInterrupt:
            log_simple("⚠ прервано пользователем", "warning")
            interrupted = True
            break
        except Exception as e:  # noqa: BLE001
            log_simple(f"⚠ op {op_idx} unexpected error: {e}", "warning")
            failures += 1
            consecutive_skips += 1
            continue

    summary = {
        "ops": ops_done, "buys": buys, "sells": sells,
        "failures": failures, "interrupted": interrupted,
    }
    log_simple(
        f"🏁 trade session done · ops={ops_done} buys={buys} sells={sells} "
        f"failures={failures}",
        "success" if not interrupted else "warning",
    )
    return summary
