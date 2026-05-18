"""Phase-2: исполнение native KAVA transfer'ов через Cosmos SDK MsgSend.

Биржевые `kava1...` адреса — это Cosmos-side банковские аккаунты. CEX
индексирует депозиты по событиям `cosmos.bank.v1beta1.MsgSend`, а не по
EVM Transfer-логам. Хотя баланс «зеркалится» через precisebank-модуль,
для гарантированного кредита депозита нужна именно Cosmos-транзакция.

Поток:
  • src balance = ukava из Cosmos bank (через REST).
  • account_number/sequence = `/cosmos/auth/v1beta1/accounts/{kava1...}`.
  • build MsgSend, sign (eth_secp256k1, SHA256+ECDSA, 64-байт r||s),
    broadcast через `/cosmos/tx/v1beta1/txs` (SYNC).
  • Дождаться tx в блоке (poll `/cosmos/tx/v1beta1/txs/{hash}`, code=0).
  • Дождаться роста dst-баланса на Cosmos-стороне (`/balances/.../by_denom`).

Орхестрация (run_all/_recheck_unfinished/halt+probe) сохраняется как было.
Числовая семантика старых колонок `*_wei` ПЕРЕОПРЕДЕЛЕНА: теперь там
хранятся ukava-units (1 KAVA = 1_000_000 ukava). Имена не мигрируем
ради совместимости со старой БД, но пересоздание БД через «🗑 Очистить»
рекомендовано после апгрейда.
"""
from __future__ import annotations

import math
import random
import re
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from modules.simple_logger import logger, log_wallet_task, log_simple
from modules.eth.transfer_kava_to_cex import database as db
from modules.eth.transfer_kava_to_cex.kava_address import evm_to_kava_bech32
from modules.eth.transfer_kava_to_cex.cosmos_tx import (
    KavaRestClient, KavaRestError, build_signed_msgsend, tx_hash_hex,
)
from config.modules.general_config import (
    SLEEP_BETWEEN_ACTIONS as _CFG_SLEEP_BETWEEN_ACTIONS,
    DELAY_BETWEEN_ACCOUNTS as _CFG_DELAY_BETWEEN_ACCOUNTS,
    RETRY_COUNT as _CFG_RETRY_COUNT,
)
from config.modules.cfg_transfer_kava_to_cex import (
    NATIVE_SYMBOL, NATIVE_DECIMALS_COSMOS,
    COSMOS_CHAIN_ID, COSMOS_DENOM, COSMOS_LCD_URLS,
    COSMOS_GAS_PRICE_UKAVA, COSMOS_GAS_LIMIT, BROADCAST_MODE,
    TX_POLL_INTERVAL_SEC, TX_POLL_TIMEOUT_SEC,
    ARRIVAL_TIMEOUT_SEC, ARRIVAL_POLL_INTERVAL_SEC,
    GAS_RESERVE_MULTIPLIER, MIN_KEEP_UKAVA,
    MIN_TRANSFER_AMOUNT_KAVA, PROBE_NEXT_ON_RESUME, TEST_OVERRIDE_AMOUNT_KAVA,
)

SLEEP_BETWEEN_ACTIONS = list(_CFG_SLEEP_BETWEEN_ACTIONS)
DELAY_BETWEEN_ACCOUNTS = list(_CFG_DELAY_BETWEEN_ACCOUNTS)
RETRY_COUNT = max(1, int(_CFG_RETRY_COUNT))

ONE_KAVA_UKAVA = 10 ** NATIVE_DECIMALS_COSMOS   # = 1_000_000
FEE_UKAVA = max(1, math.ceil(COSMOS_GAS_LIMIT * COSMOS_GAS_PRICE_UKAVA))


# ----------------------------------------------------------------------------
# REST pool helpers
# ----------------------------------------------------------------------------

def _client_pool(proxy: Optional[str], reserve: Optional[str]) -> List[KavaRestClient]:
    urls = list(COSMOS_LCD_URLS)
    random.shuffle(urls)
    out: List[KavaRestClient] = []
    for u in urls:
        for p in (proxy, reserve, None):
            out.append(KavaRestClient(u, proxy=p))
    return out


def _with_clients(clients: List[KavaRestClient], call):
    last_err: Optional[Exception] = None
    for c in clients:
        try:
            return call(c)
        except KavaRestError as exc:
            # 404 на /accounts/ — НЕ retry-able; пробрасываем сразу.
            if "not found (404)" in str(exc):
                raise
            last_err = exc
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"all LCD endpoints failed: {last_err!r}")


def _get_cosmos_balance(addr_bech32: str, proxy: Optional[str],
                        reserve: Optional[str]) -> int:
    clients = _client_pool(proxy, reserve)
    return _with_clients(clients, lambda c: c.get_balance(addr_bech32, COSMOS_DENOM))


def _get_account_info(addr_bech32: str, proxy: Optional[str],
                      reserve: Optional[str]) -> Tuple[int, int]:
    clients = _client_pool(proxy, reserve)
    return _with_clients(clients, lambda c: c.get_account(addr_bech32))


def _broadcast(tx_bytes: bytes, proxy: Optional[str],
               reserve: Optional[str]) -> dict:
    clients = _client_pool(proxy, reserve)
    return _with_clients(clients,
                          lambda c: c.broadcast_tx(tx_bytes, mode=BROADCAST_MODE))


def _get_tx(tx_hash: str, proxy: Optional[str],
            reserve: Optional[str]) -> Optional[dict]:
    clients = _client_pool(proxy, reserve)
    return _with_clients(clients, lambda c: c.get_tx(tx_hash))


# ----------------------------------------------------------------------------
# Amount spec parsing (ukava units)
# ----------------------------------------------------------------------------

_PCT_RE = re.compile(r"^\s*\"?\s*([\d.]+)\s*-\s*([\d.]+)\s*\"?\s*%?\s*$")


def _parse_amount_spec(spec: str, balance_ukava: int) -> Tuple[int, str]:
    """Возвращает (target_ukava, mode). mode = 'percent' | 'fixed'."""
    s = (spec or "").strip()
    if not s:
        s = "100-100%"
    raw = s
    if re.fullmatch(r"[\d.]+", s):
        v = Decimal(s)
        return (int(v * ONE_KAVA_UKAVA), "fixed")
    m = _PCT_RE.match(s)
    if not m:
        return (balance_ukava, "percent")
    lo = Decimal(m.group(1))
    hi = Decimal(m.group(2))
    is_pct = raw.endswith("%") or raw.startswith('"') or (lo >= 1 and hi <= 100 and lo + hi >= 100)
    rnd = Decimal(str(random.uniform(float(lo), float(hi))))
    if is_pct:
        target = (Decimal(balance_ukava) * rnd) / Decimal(100)
        return (int(target), "percent")
    return (int(rnd * ONE_KAVA_UKAVA), "fixed")


# ----------------------------------------------------------------------------
# Misc helpers
# ----------------------------------------------------------------------------

def _sleep_between_accounts() -> None:
    lo, hi = DELAY_BETWEEN_ACCOUNTS[0], DELAY_BETWEEN_ACCOUNTS[-1]
    time.sleep(random.uniform(float(lo), float(hi)))


def _human_kava(ukava: int) -> str:
    return str((Decimal(ukava) / Decimal(ONE_KAVA_UKAVA)).quantize(Decimal("0.000001")))


def _kavascan_link(tx_hash: str) -> str:
    h = tx_hash.upper().removeprefix("0x")
    return f"https://www.mintscan.io/kava/tx/{h}"


def _check_arrival(wallet: Dict[str, Any], task: Dict[str, Any]) -> Optional[int]:
    if not task.get("dst_balance_before_wei"):
        return None
    snapshot = int(task["dst_balance_before_wei"])
    try:
        cur = _get_cosmos_balance(
            wallet["cex_address_bech32"],
            wallet.get("proxy"), wallet.get("reserve_proxy"),
        )
    except Exception as exc:
        log_wallet_task(
            wallet["wallet_address"], wallet["csv_index"], 0,
            f"⚠ dst balance check error: {exc}", "warning",
            account_name=wallet.get("account_name") or "",
        )
        return None
    if cur > snapshot:
        return cur
    return None


# ----------------------------------------------------------------------------
# Single-wallet execution (Cosmos path)
# ----------------------------------------------------------------------------

def _execute_one_wallet(wallet: Dict[str, Any], idx: int, total: int) -> bool:
    name = wallet.get("account_name") or ""
    addr = wallet["wallet_address"]
    pk = wallet["private_key"]
    proxy = wallet.get("proxy")
    reserve = wallet.get("reserve_proxy")
    dst_bech32 = wallet["cex_address_bech32"]
    src_bech32 = evm_to_kava_bech32(addr)

    task = db.get_or_create_task(wallet["id"])
    task_id = task["id"]
    db.increment_attempts(task_id)

    log_wallet_task(addr, idx, total,
                    f"📤 {src_bech32} → {dst_bech32}",
                    "info", account_name=name)

    # --- balances snapshot (Cosmos bank, ukava) ---
    try:
        src_ukava = _get_cosmos_balance(src_bech32, proxy, reserve)
        dst_ukava_before = _get_cosmos_balance(dst_bech32, proxy, reserve)
    except Exception as exc:
        db.update_task(task_id, status=db.STATUS_FAILED,
                        error_message=f"balance read: {exc}")
        log_wallet_task(addr, idx, total, f"❌ balance read: {exc}",
                        "error", account_name=name)
        return False

    db.update_task(task_id,
                    src_balance_before_wei=str(src_ukava),
                    dst_balance_before_wei=str(dst_ukava_before))

    if src_ukava <= 0:
        db.update_task(task_id, status=db.STATUS_SKIPPED,
                        error_message="zero src cosmos balance")
        log_wallet_task(addr, idx, total, "⏭  skip: zero ukava balance",
                        "warning", account_name=name)
        return True

    # --- amount ---
    if TEST_OVERRIDE_AMOUNT_KAVA and TEST_OVERRIDE_AMOUNT_KAVA > 0:
        target_ukava = int(Decimal(str(TEST_OVERRIDE_AMOUNT_KAVA)) * ONE_KAVA_UKAVA)
    else:
        target_ukava, _ = _parse_amount_spec(
            wallet.get("transfer_amount_spec") or "", src_ukava,
        )

    fee_reserve = int(FEE_UKAVA * GAS_RESERVE_MULTIPLIER)
    max_sendable = src_ukava - fee_reserve - MIN_KEEP_UKAVA
    if max_sendable <= 0:
        db.update_task(task_id, status=db.STATUS_SKIPPED,
                        error_message=f"insufficient ukava for fee (bal={src_ukava}, fee_reserve={fee_reserve})")
        log_wallet_task(addr, idx, total,
                        f"⏭  skip: dust ({_human_kava(src_ukava)} {NATIVE_SYMBOL}, fee≈{_human_kava(fee_reserve)})",
                        "warning", account_name=name)
        return True

    amount_ukava = min(target_ukava, max_sendable)
    min_ukava = int(Decimal(str(MIN_TRANSFER_AMOUNT_KAVA)) * ONE_KAVA_UKAVA)
    if amount_ukava < min_ukava:
        db.update_task(task_id, status=db.STATUS_SKIPPED,
                        error_message=f"below MIN_TRANSFER_AMOUNT_KAVA ({_human_kava(amount_ukava)})")
        log_wallet_task(addr, idx, total,
                        f"⏭  skip: amount {_human_kava(amount_ukava)} < min {MIN_TRANSFER_AMOUNT_KAVA}",
                        "warning", account_name=name)
        return True

    # --- account info (account_number / sequence) ---
    try:
        account_number, sequence = _get_account_info(src_bech32, proxy, reserve)
    except KavaRestError as exc:
        db.update_task(task_id, status=db.STATUS_FAILED,
                        error_message=f"sender not in chain state: {exc}")
        log_wallet_task(addr, idx, total,
                        f"❌ sender аккаунт не зарегистрирован в Cosmos state",
                        "error", account_name=name)
        return False
    except Exception as exc:
        db.update_task(task_id, status=db.STATUS_FAILED,
                        error_message=f"get_account: {exc}")
        log_wallet_task(addr, idx, total, f"❌ get_account: {exc}",
                        "error", account_name=name)
        return False

    # --- build & sign ---
    try:
        tx_bytes = build_signed_msgsend(
            priv_hex=pk,
            from_addr=src_bech32,
            to_addr=dst_bech32,
            denom=COSMOS_DENOM,
            amount=amount_ukava,
            chain_id=COSMOS_CHAIN_ID,
            account_number=account_number,
            sequence=sequence,
            fee_amount=FEE_UKAVA,
            gas_limit=COSMOS_GAS_LIMIT,
            memo="",
        )
        expected_hash = tx_hash_hex(tx_bytes)
    except Exception as exc:
        db.update_task(task_id, status=db.STATUS_FAILED,
                        error_message=f"build/sign: {exc}")
        log_wallet_task(addr, idx, total, f"❌ build/sign: {exc}",
                        "error", account_name=name)
        return False

    # --- broadcast ---
    try:
        resp = _broadcast(tx_bytes, proxy, reserve)
    except Exception as exc:
        db.update_task(task_id, status=db.STATUS_FAILED,
                        error_message=f"broadcast: {exc}",
                        gas_price_wei=str(FEE_UKAVA),
                        gas_limit=int(COSMOS_GAS_LIMIT),
                        nonce=int(sequence),
                        sent_amount_wei=str(amount_ukava),
                        sent_amount_human=_human_kava(amount_ukava))
        log_wallet_task(addr, idx, total, f"❌ broadcast: {exc}",
                        "error", account_name=name)
        return False

    tx_resp = resp.get("tx_response", {}) or {}
    code = int(tx_resp.get("code") or 0)
    server_hash = (tx_resp.get("txhash") or "").upper()
    final_hash = server_hash or expected_hash
    raw_log = tx_resp.get("raw_log", "") or ""
    explorer = _kavascan_link(final_hash)

    db.update_task(task_id,
                    tx_hash=final_hash,
                    explorer_link=explorer,
                    gas_price_wei=str(FEE_UKAVA),
                    gas_limit=int(COSMOS_GAS_LIMIT),
                    nonce=int(sequence),
                    sent_amount_wei=str(amount_ukava),
                    sent_amount_human=_human_kava(amount_ukava))

    if code != 0:
        db.update_task(task_id, status=db.STATUS_FAILED,
                        receipt_status=int(code),
                        error_message=f"broadcast code={code}: {raw_log[:300]}")
        log_wallet_task(addr, idx, total,
                        f"❌ mempool reject code={code}: {raw_log[:160]}",
                        "error", account_name=name)
        return False

    db.update_task(task_id, status=db.STATUS_TX_SENT)
    log_wallet_task(addr, idx, total,
                    f"📤 broadcast {_human_kava(amount_ukava)} {NATIVE_SYMBOL} → {explorer}",
                    "info", account_name=name)

    # --- wait inclusion in block ---
    block_deadline = time.time() + TX_POLL_TIMEOUT_SEC
    included = False
    while time.time() < block_deadline:
        try:
            tx_data = _get_tx(final_hash, proxy, reserve)
        except Exception as exc:
            log_wallet_task(addr, idx, total,
                            f"⚠ get_tx error: {exc}", "warning",
                            account_name=name)
            time.sleep(TX_POLL_INTERVAL_SEC)
            continue
        if tx_data is None:
            time.sleep(TX_POLL_INTERVAL_SEC)
            continue
        tr = tx_data.get("tx_response", {}) or {}
        rcode = int(tr.get("code") or 0)
        db.update_task(task_id, receipt_status=int(rcode))
        if rcode != 0:
            rlog = tr.get("raw_log", "") or ""
            db.update_task(task_id, status=db.STATUS_FAILED,
                            error_message=f"tx code={rcode}: {rlog[:300]}")
            log_wallet_task(addr, idx, total,
                            f"❌ tx in block but failed: code={rcode} {rlog[:160]}",
                            "error", account_name=name)
            return False
        included = True
        log_wallet_task(addr, idx, total,
                        f"✅ tx в блоке (code=0)",
                        "info", account_name=name)
        break

    if not included:
        log_wallet_task(addr, idx, total,
                        f"⚠ tx ещё не в блоке после {TX_POLL_TIMEOUT_SEC}s — переходим к polling баланса",
                        "warning", account_name=name)

    db.update_task(task_id, status=db.STATUS_AWAITING)

    # --- arrival polling (Cosmos bank balance) ---
    deadline = time.time() + ARRIVAL_TIMEOUT_SEC
    log_wallet_task(addr, idx, total,
                    f"⏳ awaiting Cosmos-bank arrival (timeout {ARRIVAL_TIMEOUT_SEC}s)",
                    "info", account_name=name)
    while time.time() < deadline:
        try:
            cur = _get_cosmos_balance(dst_bech32, proxy, reserve)
        except Exception as exc:
            log_wallet_task(addr, idx, total,
                            f"⚠ dst balance check: {exc}", "warning",
                            account_name=name)
            time.sleep(ARRIVAL_POLL_INTERVAL_SEC)
            continue
        if cur > dst_ukava_before:
            db.update_task(task_id, status=db.STATUS_ARRIVED,
                            dst_balance_after_wei=str(cur),
                            arrival_detected_at=int(time.time()),
                            error_message=None)
            try:
                src_after = _get_cosmos_balance(src_bech32, proxy, reserve)
                db.update_task(task_id, src_balance_after_wei=str(src_after))
            except Exception:
                pass
            delta = cur - dst_ukava_before
            log_wallet_task(addr, idx, total,
                            f"✅ arrived: +{_human_kava(delta)} {NATIVE_SYMBOL} on dst (Cosmos)",
                            "success", account_name=name)
            return True
        time.sleep(ARRIVAL_POLL_INTERVAL_SEC)

    db.update_task(task_id, status=db.STATUS_AWAITING,
                    error_message=f"arrival timeout after {ARRIVAL_TIMEOUT_SEC}s")
    log_wallet_task(addr, idx, total,
                    f"❌ arrival timeout — Cosmos bank balance dst не вырос за {ARRIVAL_TIMEOUT_SEC}s",
                    "error", account_name=name)
    return False


# ----------------------------------------------------------------------------
# Resume helpers + orchestrator (unchanged semantics)
# ----------------------------------------------------------------------------

def _recheck_unfinished() -> Dict[str, int]:
    counters = {"recovered": 0, "still_pending": 0}
    wallets = db.list_wallets_ordered()
    total = len(wallets)
    for w in wallets:
        task = db.get_task_by_wallet(w["id"])
        if not task:
            continue
        if task["status"] in db.TERMINAL:
            continue
        if task["status"] == db.STATUS_PENDING:
            counters["still_pending"] += 1
            continue
        cur = _check_arrival(w, task)
        if cur is not None:
            db.update_task(task["id"], status=db.STATUS_ARRIVED,
                            dst_balance_after_wei=str(cur),
                            arrival_detected_at=int(time.time()),
                            error_message=None)
            counters["recovered"] += 1
            log_wallet_task(
                w["wallet_address"], w["csv_index"], total,
                f"✅ late arrival detected (dst now > snapshot)",
                "success", account_name=w.get("account_name") or "",
            )
        else:
            counters["still_pending"] += 1
            log_wallet_task(
                w["wallet_address"], w["csv_index"], total,
                f"⏳ still no arrival (status={task['status']})",
                "warning", account_name=w.get("account_name") or "",
            )
    return counters


def run_all() -> Dict[str, Any]:
    db.init_database()
    summary = {
        "recovered_on_recheck": 0,
        "executed": 0,
        "arrived": 0,
        "skipped": 0,
        "failed": 0,
        "halted": False,
        "halt_reason": None,
    }

    log_simple("🔁 recheck не-arrived задач (поиск поздних поступлений)…", "info")
    rc = _recheck_unfinished()
    summary["recovered_on_recheck"] = rc["recovered"]

    wallets = db.list_wallets_ordered()
    total = len(wallets)
    if not wallets:
        log_simple("kava_wallets пуст — сначала «📋 Планирование»", "warning")
        return summary

    pending: List[Dict[str, Any]] = []
    stuck: List[Dict[str, Any]] = []
    for w in wallets:
        t = db.get_task_by_wallet(w["id"])
        if not t:
            continue
        if t["status"] == db.STATUS_PENDING:
            pending.append(w)
        elif t["status"] in (db.STATUS_TX_SENT, db.STATUS_AWAITING, db.STATUS_FAILED):
            stuck.append(w)

    if not pending and not stuck:
        log_simple("✅ нет задач к выполнению (все terminal)", "success")
        return summary

    if stuck:
        log_simple(
            f"⚠ {len(stuck)} зависших задач(а) с прошлого запуска: "
            f"{', '.join(w['wallet_address'] for w in stuck[:3])}"
            f"{'…' if len(stuck) > 3 else ''}",
            "warning",
        )
        if not pending:
            log_simple(
                "❌ нет pending'ов для probe — модуль остаётся в halted-состоянии",
                "error",
            )
            summary["halted"] = True
            summary["halt_reason"] = "stuck wallets remain, no probe candidate"
            return summary
        if PROBE_NEXT_ON_RESUME:
            probe = pending[0]
            log_simple(
                f"🧪 probe: пробуем кошелёк {probe['wallet_address']} "
                f"[{probe['csv_index']}/{total}]",
                "info",
            )
            ok = _execute_one_wallet(probe, probe["csv_index"], total)
            summary["executed"] += 1
            if ok:
                t = db.get_task_by_wallet(probe["id"])
                if t and t["status"] == db.STATUS_ARRIVED:
                    summary["arrived"] += 1
                elif t and t["status"] == db.STATUS_SKIPPED:
                    summary["skipped"] += 1
                pending = pending[1:]
                log_simple("✅ probe прошёл — продолжаем штатно", "success")
            else:
                summary["failed"] += 1
                summary["halted"] = True
                summary["halt_reason"] = "probe failed after previous halt"
                log_simple(
                    "❌ probe тоже не дошёл — снова HALT. Перезапустите модуль позже.",
                    "error",
                )
                return summary
            _sleep_between_accounts()

    for w in pending:
        ok = _execute_one_wallet(w, w["csv_index"], total)
        summary["executed"] += 1
        t = db.get_task_by_wallet(w["id"])
        if t:
            if t["status"] == db.STATUS_ARRIVED:
                summary["arrived"] += 1
            elif t["status"] == db.STATUS_SKIPPED:
                summary["skipped"] += 1
            elif t["status"] in (db.STATUS_FAILED, db.STATUS_AWAITING):
                summary["failed"] += 1
        if not ok and t and t["status"] not in (db.STATUS_ARRIVED, db.STATUS_SKIPPED):
            summary["halted"] = True
            summary["halt_reason"] = (
                f"wallet {w['wallet_address']} not arrived "
                f"(status={t['status']})"
            )
            log_simple(
                f"🛑 HALT: {summary['halt_reason']}. "
                f"Остальные {len(pending) - summary['executed']} кошельков "
                f"пропущены до повторного запуска.",
                "error",
            )
            return summary
        _sleep_between_accounts()

    return summary


__all__ = ["run_all", "_execute_one_wallet", "_recheck_unfinished",
            "_parse_amount_spec", "_get_cosmos_balance"]
