"""Sahara AI — Knowledge Drop: claim и вывод SAHARA на биржу."""

from __future__ import annotations

import random
import threading
import time
from collections import Counter
from typing import List

from config.modules.cfg_sahara import AUTO_WITHDRAW_TO_CEX, SAHARA_TOKEN_ADDRESS
from config.modules.general_config import (
    DELAY_BETWEEN_ACCOUNTS,
    NUM_THREADS,
    SHUFLE_ACCOUNTS,
)
from modules.core.runner import run_parallel
from modules.data_manager import load_data
from modules.sahara.claimer import WalletResult, run_one
from modules.simple_logger import log_simple, logger, set_auto_progress
from modules.ui import ui
from modules.ui.module_menu import MenuAction, ModuleMenu

# Итоговые статусы кошелька из claimer.WalletResult — по-русски.
_STATUS_LABELS = {
    "claimed": "заклеймлено",
    "claimed+withdrawn": "заклеймлено и выведено",
    "already_claimed": "клеймили ранее",
    "not_eligible": "нечего клеймить",
    "failed": "ошибка",
    "pending": "не обработано",
}


def _filter_records(rows: List[dict]) -> List[dict]:
    return [r for r in rows if (r.get("private_key") or "").strip()]


# --- режим withdraw-only ------------------------------------------------------

def _run_withdraw_only(record: dict, *, index: int, total: int) -> WalletResult:
    """Только withdraw существующего SAHARA, без claim. Реализован поверх
    того же claimer'а — для этого минимальный shim, который зовёт ту же
    логику transfer/wait, минуя earndrop API.
    """
    from eth_account import Account
    from web3 import Web3
    from config.modules.cfg_sahara import (
        WITHDRAW_BALANCE_POLL_INTERVAL,
        WITHDRAW_BALANCE_WAIT_TIMEOUT,
    )
    from modules.proxy_manager import parse_proxy
    from modules.sahara import claimer as _c
    from modules.simple_logger import log_wallet_task

    name = (record.get('name') or '').strip()
    pk_raw = (record.get('private_key') or '').strip()
    pk = pk_raw if pk_raw.startswith('0x') else f'0x{pk_raw}'
    addr = Account.from_key(pk).address
    short = f"{addr[:6]}…{addr[-4:]}"
    proxy = parse_proxy(record.get('proxy')) or parse_proxy(record.get('reserve_proxy'))
    cex_address = (record.get('evm_cex_address') or '').strip()

    res = WalletResult(name=name, address=addr)

    def _log(msg, level='info'):
        log_wallet_task(short, index, total, msg, level, account_name=name or '')

    if not cex_address:
        res.status = 'failed'
        res.errors.append('empty evm_cex_address')
        _log("❌ evm_cex_address пуст", 'error')
        return res
    try:
        Web3.to_checksum_address(cex_address)
    except Exception as e:
        res.status = 'failed'
        res.errors.append(f"bad cex_address: {e}")
        _log(f"❌ bad evm_cex_address: {e}", 'error')
        return res

    try:
        bal = _c._balance_of(SAHARA_TOKEN_ADDRESS, addr, proxy=proxy)
    except Exception as e:
        res.status = 'failed'
        res.errors.append(f"balanceOf: {e}")
        _log(f"❌ balanceOf: {e}", 'error')
        return res

    if bal == 0:
        res.status = 'not_eligible'
        _log("⏭ 0 SAHARA на кошельке — нечего выводить", 'warning')
        return res

    try:
        cex_baseline = _c._balance_of(SAHARA_TOKEN_ADDRESS, cex_address, proxy=proxy)
    except Exception:
        cex_baseline = 0

    try:
        _log(f"💸 withdraw {bal / 1e18:.4f} SAHARA → "
             f"{cex_address[:6]}…{cex_address[-4:]}", 'info')
        tx_hash = _c._do_token_transfer(
            sender=addr, private_key=pk,
            to_address=cex_address, amount_raw=bal, proxy=proxy,
        )
    except Exception as e:
        res.status = 'failed'
        res.errors.append(f"withdraw: {e}")
        _log(f"❌ withdraw: {e}", 'error')
        return res

    res.withdraw_tx = tx_hash
    res.withdraw_amount = bal
    _log(f"🧾 withdraw tx: 0x{tx_hash.lstrip('0x')}", 'info')

    new_cex = _c._wait_balance_growth(
        SAHARA_TOKEN_ADDRESS, cex_address, cex_baseline,
        timeout=WITHDRAW_BALANCE_WAIT_TIMEOUT,
        poll=WITHDRAW_BALANCE_POLL_INTERVAL,
        proxy=proxy,
    )
    res.cex_balance_after = new_cex
    if new_cex > cex_baseline:
        res.status = 'claimed+withdrawn'
        _log(f"✅ CEX +{(new_cex - cex_baseline) / 1e18:.4f} SAHARA",
             'success')
    else:
        res.errors.append("cex balance did not grow within timeout")
        _log("⚠ CEX balance не подтвердился в таймаут", 'warning')
    return res


# --- общий runner -------------------------------------------------------------

def _run_pool(records: List[dict], *, num_threads: int,
              worker) -> List[WalletResult]:
    total = len(records)
    if total == 0:
        return []

    # Старты аккаунтов разносим по времени; спит по одному потоку за раз,
    # иначе задержка перестаёт быть задержкой между аккаунтами.
    start_lock = threading.Lock()

    def _call(index: int, record: dict) -> WalletResult:
        if index > 1 and DELAY_BETWEEN_ACCOUNTS:
            with start_lock:
                time.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS))
        try:
            return worker(record, index=index, total=total)
        except Exception as exc:
            logger.exception(f"worker crashed for record #{index}")
            return WalletResult(
                name=(record.get('name') or '').strip(),
                address='', status='failed', errors=[str(exc)],
            )

    results = run_parallel(records, _call, threads=num_threads,
                           thread_name_prefix="sahara")
    return [r for r in results if r is not None]


def _print_summary(results: List[WalletResult]) -> None:
    if not results:
        return
    counter = Counter(r.status for r in results)
    stats = {_STATUS_LABELS.get(status, status): count
             for status, count in counter.most_common()}
    stats["total"] = len(results)

    claimed = sum((r.claim_amount or 0) for r in results) / 1e18
    withdrawn = sum((r.withdraw_amount or 0) for r in results) / 1e18
    ui.print_lines(ui.stats_panel(
        "Sahara — итоги", stats,
        footer=f"заклеймлено {claimed:.4f} SAHARA · "
               f"выведено {withdrawn:.4f} SAHARA",
    ))


def _prepare(title: str) -> tuple[List[dict], int] | None:
    """Кошельки и число потоков. ``None`` — запускать нечего или отмена."""
    rows = _filter_records(load_data())
    if not rows:
        log_simple("data/data_*.csv пуст — нет кошельков с private_key", 'warning')
        return None
    if SHUFLE_ACCOUNTS:
        random.shuffle(rows)

    threads = ui.ask_int("Количество потоков", minimum=1, default=int(NUM_THREADS))
    if threads is None:
        return None

    # В логах уже есть [i/N] — второй индикатор прогресса не нужен.
    set_auto_progress(False)
    log_simple(f"{title}: {len(rows)} кошельков, потоков: {threads}", 'info')
    return rows, threads


# --- handlers -----------------------------------------------------------------

def _run_claim_mode(*, auto_withdraw: bool) -> None:
    prepared = _prepare("🤖 Sahara claim" + (" + withdraw" if auto_withdraw else ""))
    if prepared is None:
        return
    rows, threads = prepared

    def _worker(rec, *, index, total):
        return run_one(rec, index=index, total=total,
                       auto_withdraw_override=auto_withdraw)

    try:
        results = _run_pool(rows, num_threads=threads, worker=_worker)
    except KeyboardInterrupt:
        log_simple("⏹ прервано пользователем", 'warning')
        return
    _print_summary(results)


def _run_withdraw_mode() -> None:
    prepared = _prepare("📤 Sahara withdraw-only")
    if prepared is None:
        return
    rows, threads = prepared

    try:
        results = _run_pool(rows, num_threads=threads, worker=_run_withdraw_only)
    except KeyboardInterrupt:
        log_simple("⏹ прервано пользователем", 'warning')
        return
    _print_summary(results)


def _info() -> dict:
    return {
        "Как это работает": [
            "Сайт: https://knowledgedrop.saharaai.com",
            "Claim идёт в сети BSC (chain_id 56), комиссия контракта "
            "оплачивается в BNB.",
            f"Токен SAHARA (BEP-20): {SAHARA_TOKEN_ADDRESS}",
            "После claim модуль ждёт, пока токены реально появятся на "
            "кошельке, и только потом переводит их на биржу.",
            "Вывод идёт на evm_cex_address той же строки data.csv — у "
            "каждого кошелька свой суб-адрес.",
        ],
        "Что нужно в data.csv": [
            "private_key — обязательно, адрес выводится из него;",
            "proxy и reserve_proxy — запросы кошелька идут через них;",
            "evm_cex_address — нужен только для режимов с выводом.",
        ],
        "Настройки": [
            f"AUTO_WITHDRAW_TO_CEX = {AUTO_WITHDRAW_TO_CEX} "
            "(config/modules/cfg_sahara.py) — вывод сразу после claim, "
            "когда режим не задан пунктом меню.",
            "Число потоков спрашивается перед запуском, по умолчанию — "
            "NUM_THREADS из config/modules/general_config.py.",
        ],
    }


def run_sahara() -> None:
    """Главное меню Sahara — вызывается из main.py."""
    ModuleMenu(
        title="Sahara AI",
        subtitle="Knowledge Drop",
        icon="🏜️",
        actions=[
            MenuAction("claim", "Claim SAHARA",
                       lambda: _run_claim_mode(auto_withdraw=False),
                       "забрать токены на кошелёк, без вывода", icon="🪂"),
            MenuAction("claim_and_withdraw", "Claim и вывод на биржу",
                       lambda: _run_claim_mode(auto_withdraw=True),
                       "забрать и сразу отправить на evm_cex_address",
                       icon="💸"),
            MenuAction("withdraw_only", "Вывод на биржу",
                       _run_withdraw_mode,
                       "отправить уже полученный SAHARA на биржу",
                       icon="📤"),
        ],
        info=_info,
    ).run()


__all__ = ["run_sahara"]
