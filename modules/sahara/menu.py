"""Sahara AI submenu — claim + (optional) auto-withdraw to CEX."""

from __future__ import annotations

import random
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from colorama import Fore, Style
from questionary import Choice, select

from config.menu_config import MenuItem, SubMenu, build_submenu_choices
from config.modules.cfg_sahara import AUTO_WITHDRAW_TO_CEX
from config.modules.general_config import (
    DELAY_BETWEEN_ACCOUNTS,
    NUM_THREADS,
    SHUFLE_ACCOUNTS,
)
from modules.data_manager import load_data
from modules.simple_logger import log_simple, logger, set_auto_progress

from modules.sahara.claimer import WalletResult, run_one


SAHARA_SUBMENU = SubMenu(
    key='sahara',
    label='Sahara AI — Knowledge Drop',
    description='',
    icon='🟢',
    qmark='🟢',
    pointer='👉',
    items=[
        MenuItem(key='claim', label='Claim SAHARA',
                 description='Только on-chain claim (без вывода на CEX)',
                 icon='🪂', enabled=True),
        MenuItem(key='claim_and_withdraw', label='Claim + Withdraw → CEX',
                 description='Claim и сразу перевод SAHARA на evm_cex_address',
                 icon='💸', enabled=True),
        MenuItem(key='withdraw_only', label='Withdraw → CEX (без claim)',
                 description='Перевести имеющийся SAHARA на CEX-адрес',
                 icon='📤', enabled=True),
        MenuItem(key='info', label='Информация',
                 description='Что делает модуль и какие настройки используются',
                 icon='📖', enabled=True),
        MenuItem(key='back', label='Назад', description='', icon='🔙', enabled=True),
    ],
)


def _print_info() -> None:
    print()
    print(Fore.CYAN + "=" * 60 + Style.RESET_ALL)
    print(Fore.CYAN + "  Sahara AI — Knowledge Drop claimer" + Style.RESET_ALL)
    print(Fore.CYAN + "=" * 60 + Style.RESET_ALL)
    print()
    print("  Сайт:       https://knowledgedrop.saharaai.com")
    print("  Сеть claim: BSC (chain_id=56), claim_fee оплачивается в BNB")
    print("  Токен:      SAHARA (BEP-20)")
    print("                0xfdffb411c4a70aa7c95d5c981a6fb4da867e1111")
    print()
    print("  Данные кошельков:  data/data_sahara.csv (или другой data_*.csv)")
    print("  Поля строки:       private_key, proxy, reserve_proxy, "
          "evm_cex_address (опц.)")
    print()
    print("  Авто-вывод на CEX (config/modules/cfg_sahara.py):")
    print(f"     AUTO_WITHDRAW_TO_CEX = {AUTO_WITHDRAW_TO_CEX}")
    print("     -> при True и непустом evm_cex_address — сразу после claim "
          "переводим всё на CEX-адрес.")
    print()
    print(Fore.CYAN + "=" * 60 + Style.RESET_ALL)
    input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")


def _ask_thread_count(default: int) -> int:
    try:
        raw = input(
            f"{Fore.CYAN}Количество потоков [{default}]: {Style.RESET_ALL}"
        ).strip()
    except EOFError:
        return default
    if not raw:
        return default
    try:
        n = int(raw)
        return max(1, n)
    except ValueError:
        return default


def _filter_records(rows: List[dict]) -> List[dict]:
    out = []
    for r in rows:
        if (r.get('private_key') or '').strip():
            out.append(r)
    return out


# --- режим withdraw-only ------------------------------------------------------

def _run_withdraw_only(record: dict, *, index: int, total: int) -> WalletResult:
    """Только withdraw существующего SAHARA, без claim. Реализован поверх
    того же claimer'а — для этого минимальный shim, который зовёт ту же
    логику transfer/wait, минуя earndrop API.
    """
    from eth_account import Account
    from web3 import Web3
    from config.modules.cfg_sahara import (
        CLAIM_BALANCE_POLL_INTERVAL,
        SAHARA_TOKEN_ADDRESS,
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

    threads = max(1, min(num_threads, total))
    results: List[WalletResult] = []
    lock = threading.Lock()
    start_lock = threading.Lock()

    def _wrapped(i: int, rec: dict) -> WalletResult:
        # рандомизированная задержка старта между аккаунтами
        if i > 1 and DELAY_BETWEEN_ACCOUNTS:
            with start_lock:
                time.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS))
        try:
            r = worker(rec, index=i, total=total)
        except Exception as e:
            logger.exception(f"worker crashed for record #{i}")
            r = WalletResult(
                name=(rec.get('name') or '').strip(),
                address='', status='failed', errors=[str(e)],
            )
        with lock:
            results.append(r)
        return r

    if threads <= 1:
        for i, rec in enumerate(records, 1):
            _wrapped(i, rec)
        return results

    with ThreadPoolExecutor(max_workers=threads,
                            thread_name_prefix="sahara") as ex:
        futs = [ex.submit(_wrapped, i, rec) for i, rec in enumerate(records, 1)]
        try:
            for fut in as_completed(futs):
                fut.result()
        except KeyboardInterrupt:
            for f in futs:
                f.cancel()
            raise
    return results


def _print_summary(results: List[WalletResult]) -> None:
    if not results:
        return
    counter = Counter(r.status for r in results)

    total_claimed = sum((r.claim_amount or 0) for r in results)
    total_withdrawn = sum((r.withdraw_amount or 0) for r in results)

    print()
    print(Fore.CYAN + "=" * 60 + Style.RESET_ALL)
    print(Fore.CYAN + "  Sahara — итоги" + Style.RESET_ALL)
    print(Fore.CYAN + "=" * 60 + Style.RESET_ALL)
    for status, count in counter.most_common():
        print(f"  {status:<22} {count}")
    print("-" * 40)
    print(f"  {'total wallets':<22} {len(results)}")
    print(f"  {'claimed (SAHARA)':<22} {total_claimed / 1e18:.4f}")
    print(f"  {'withdrawn (SAHARA)':<22} {total_withdrawn / 1e18:.4f}")
    print(Fore.CYAN + "=" * 60 + Style.RESET_ALL)


# --- handlers -----------------------------------------------------------------

def _run_claim_mode(*, auto_withdraw: bool) -> None:
    rows = _filter_records(load_data())
    if not rows:
        log_simple("data/data_*.csv пуст — нет кошельков с private_key", 'warning')
        return
    if SHUFLE_ACCOUNTS:
        random.shuffle(rows)

    threads = _ask_thread_count(NUM_THREADS)
    set_auto_progress(False)

    log_simple(f"🤖 Sahara claim{' + withdraw' if auto_withdraw else ''}: "
               f"{len(rows)} кошельков, потоков={threads}", 'info')

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
    rows = _filter_records(load_data())
    if not rows:
        log_simple("data/data_*.csv пуст — нет кошельков с private_key", 'warning')
        return
    if SHUFLE_ACCOUNTS:
        random.shuffle(rows)

    threads = _ask_thread_count(NUM_THREADS)
    set_auto_progress(False)

    log_simple(f"📤 Sahara withdraw-only: {len(rows)} кошельков, "
               f"потоков={threads}", 'info')

    try:
        results = _run_pool(rows, num_threads=threads, worker=_run_withdraw_only)
    except KeyboardInterrupt:
        log_simple("⏹ прервано пользователем", 'warning')
        return
    _print_summary(results)


def run_sahara() -> None:
    """Главное меню Sahara — вызывается из main.py."""
    while True:
        action = select(
            "🟢 Sahara AI — Knowledge Drop:",
            choices=build_submenu_choices(SAHARA_SUBMENU),
            qmark=SAHARA_SUBMENU.qmark,
            pointer=SAHARA_SUBMENU.pointer,
        ).ask()

        if action is None or action == 'back':
            return

        if action == 'claim':
            _run_claim_mode(auto_withdraw=False)
        elif action == 'claim_and_withdraw':
            _run_claim_mode(auto_withdraw=True)
        elif action == 'withdraw_only':
            _run_withdraw_mode()
        elif action == 'info':
            _print_info()
            continue

        try:
            input(f"\n{Fore.CYAN}Нажмите Enter для продолжения..."
                  f"{Style.RESET_ALL}")
        except EOFError:
            return
