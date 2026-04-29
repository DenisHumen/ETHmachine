"""Главный чекер балансов zkSync Lite.

Многопоточно для каждого кошелька запрашивает API
``/api/v0.2/accounts/{address}`` через персональный прокси из data.csv,
сохраняет результаты в SQLite (db/zksync_lite_balance.db) и поддерживает
докатку (pending/failed) — можно прервать Ctrl+C и продолжить.
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from threading import Event, Lock
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Dict, List, Optional, Tuple

from colorama import Fore, Style
from eth_account import Account
from tqdm import tqdm

from config.modules.cfg_base import (
    DELAY_BETWEEN_ACCOUNTS,
    NUM_THREADS,
    RETRY_COUNT,
    SLEEP_BETWEEN_ACTIONS,
)
from modules.data_manager import load_data
from modules.proxy_manager import mask_proxy
from modules.simple_logger import logger, tqdm_safe_logging

from modules.zksync_lite.api_client import (
    ZkSyncLiteAPIError,
    fetch_account,
    load_token_decimals,
    parse_account,
)
from modules.zksync_lite.database import (
    create_tasks,
    get_pending_tasks,
    get_task_statistics,
    init_database,
    update_task_failed,
    update_task_success,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULT_DIR = PROJECT_ROOT / "result" / "zksync_lite"

_stop_event = Event()


# ────────────────────────── загрузка кошельков ──────────────────────────


def _derive_address(private_key: str) -> Optional[str]:
    pk = (private_key or "").strip()
    if not pk:
        return None
    if not pk.startswith("0x"):
        pk = "0x" + pk
    try:
        return Account.from_key(pk).address
    except Exception as exc:  # noqa: BLE001
        logger.error(f"private_key → address: {exc}")
        return None


def _load_wallets() -> List[Dict[str, Optional[str]]]:
    """Возвращает [{wallet_address, account_name, proxy}, ...] из data.csv."""
    rows = load_data()
    wallets: List[Dict[str, Optional[str]]] = []
    for r in rows:
        addr = (r.get("wallet_address") or "").strip()
        if not addr:
            addr = _derive_address(r.get("private_key", "")) or ""
        if not addr:
            continue
        wallets.append(
            {
                "wallet_address": addr,
                "account_name": (r.get("name") or "").strip() or None,
                "proxy": (r.get("proxy") or "").strip() or None,
            }
        )
    return wallets


def _build_proxy_map(wallets: List[Dict[str, Optional[str]]]) -> Dict[str, Optional[str]]:
    """address (lower) → proxy (raw string)."""
    return {w["wallet_address"].lower(): w.get("proxy") for w in wallets}


def _build_name_map(wallets: List[Dict[str, Optional[str]]]) -> Dict[str, Optional[str]]:
    return {w["wallet_address"].lower(): w.get("account_name") for w in wallets}


# ────────────────────────── прогресс-бар ──────────────────────────

_pbar: Optional[tqdm] = None
_pbar_lock = Lock()
_counts: Dict[str, int] = {"active": 0, "empty": 0, "failed": 0}

_BAR_FORMAT = (
    "{desc}  {percentage:5.1f}% {bar:32} "
    "{n_fmt}/{total_fmt} │ ⏱ {elapsed}<{remaining} │ {stats}"
)


class _ZkLTqdm(tqdm):
    @property
    def format_dict(self) -> Dict[str, Any]:
        d = super().format_dict
        d["stats"] = (
            f"💰{_counts['active']} ○{_counts['empty']} ✗{_counts['failed']}"
        )
        return d


def _pbar_tick(kind: str) -> None:
    with _pbar_lock:
        _counts[kind] = _counts.get(kind, 0) + 1
        if _pbar is not None:
            _pbar.update(1)


# ────────────────────────── обработка одного кошелька ──────────────────────────


def _process_wallet(
    address: str,
    proxy: Optional[str],
    account_name: Optional[str],
    index: int,
    total: int,
) -> Tuple[str, str, Optional[str]]:
    """Возвращает (address, kind, error_message_or_none).

    kind: 'active' | 'empty' | 'failed' | 'stopped'
    """
    short = f"{address[:6]}…{address[-4:]}"
    pname = mask_proxy(proxy) if proxy else "direct"
    last_error: Optional[str] = None

    for attempt in range(1, max(RETRY_COUNT, 1) + 1):
        if _stop_event.is_set():
            update_task_failed(address, "stopped by user")
            return address, "failed", "stopped"

        try:
            raw = fetch_account(address, proxy)
            parsed = parse_account(raw)

            update_task_success(
                address,
                account_id=parsed["account_id"],
                pubkey_hash=parsed["pubkey_hash"],
                account_type=parsed["account_type"],
                nonce=parsed["nonce"],
                is_active=parsed["is_active"],
                eth_balance=parsed["eth_balance"],
                balances=parsed["balances"],
                nfts=parsed["nfts"],
            )

            if parsed["is_active"] and parsed["balances"]:
                tokens_summary = ", ".join(
                    f"{sym}={info['amount']}" for sym, info in parsed["balances"].items()
                )
                logger.bind(wallet=short, account_name=account_name or "",
                            task_index=index, task_total=total).success(
                    f"[zkL/{pname}] active · {tokens_summary}"
                )
                return address, "active", None
            else:
                logger.bind(wallet=short, account_name=account_name or "",
                            task_index=index, task_total=total).info(
                    f"[zkL/{pname}] empty (no committed account or zero balances)"
                )
                return address, "empty", None

        except ZkSyncLiteAPIError as exc:
            last_error = str(exc)
            logger.bind(wallet=short, task_index=index, task_total=total).warning(
                f"[zkL/{pname}] try {attempt}/{RETRY_COUNT}: {last_error}"
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"unexpected: {exc!r}"
            logger.bind(wallet=short, task_index=index, task_total=total).error(
                f"[zkL/{pname}] try {attempt}/{RETRY_COUNT}: {last_error}"
            )

        # пауза между ретраями
        if attempt < max(RETRY_COUNT, 1):
            time.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

    update_task_failed(address, last_error or "unknown")
    return address, "failed", last_error


# ────────────────────────── публичный entry-point ──────────────────────────


def run_zksync_lite_checker() -> None:
    """Запуск проверки. Грузит pending/failed из БД и обрабатывает их."""
    global _pbar
    _stop_event.clear()
    for k in _counts:
        _counts[k] = 0

    init_database()
    wallets = _load_wallets()
    if not wallets:
        logger.error("В data.csv нет ни одного кошелька (wallet_address/private_key).")
        return

    create_tasks(wallets)
    proxy_map = _build_proxy_map(wallets)
    name_map = _build_name_map(wallets)

    pending = get_pending_tasks()
    if not pending:
        logger.success("Все задачи в БД уже выполнены — нечего делать.")
        return

    # один раз грузим decimals (через прокси первого кошелька, если есть)
    bootstrap_proxy = next((p for p in proxy_map.values() if p), None)
    decimals = load_token_decimals(bootstrap_proxy)
    logger.info(f"zkSync Lite: загружено {len(decimals)} токенов (decimals)")

    total = len(pending)
    logger.info(
        f"zkSync Lite: к обработке {total} кошельков "
        f"(потоков: {NUM_THREADS}, ретраев: {RETRY_COUNT})"
    )

    with tqdm_safe_logging():
        _pbar = _ZkLTqdm(
            total=total,
            desc=f"{Fore.CYAN}🟪 zkSync Lite{Style.RESET_ALL}",
            bar_format=_BAR_FORMAT,
            ascii=" ╸━",
            ncols=120,
            leave=True,
        )
        try:
            max_workers = max(1, min(NUM_THREADS, total))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                pending_iter = iter(enumerate(pending, 1))
                in_flight = set()

                def _submit_next() -> bool:
                    if _stop_event.is_set():
                        return False
                    try:
                        i, task = next(pending_iter)
                    except StopIteration:
                        return False

                    addr = task["wallet_address"]
                    proxy = proxy_map.get(addr.lower())
                    name = name_map.get(addr.lower())
                    in_flight.add(ex.submit(_process_wallet, addr, proxy, name, i, total))

                    # Легкий стаггер старта без блокировки прогресс-бара.
                    if DELAY_BETWEEN_ACCOUNTS:
                        time.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS) / max_workers)
                    return True

                # Заполняем пул начальными задачами.
                for _ in range(max_workers):
                    if not _submit_next():
                        break

                while in_flight:
                    done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                    for fut in done:
                        in_flight.discard(fut)
                        try:
                            _, kind, _ = fut.result()
                        except Exception as exc:  # noqa: BLE001
                            logger.error(f"worker error: {exc}")
                            kind = "failed"
                        if kind in ("active", "empty", "failed"):
                            _pbar_tick(kind)

                    while len(in_flight) < max_workers and _submit_next():
                        pass
        except KeyboardInterrupt:
            _stop_event.set()
            logger.warning("Получен Ctrl+C — стопаем после текущих задач…")
        finally:
            if _pbar is not None:
                _pbar.close()
                _pbar = None

    print_run_statistics()

    # авто-экспорт после каждого запуска (как требовано в ТЗ)
    try:
        from modules.zksync_lite.exporter import export_results_xlsx
        path = export_results_xlsx()
        if path:
            logger.success(f"Excel-отчёт: {path}")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Excel экспорт не выполнен: {exc}")


def request_stop() -> None:
    _stop_event.set()


def print_run_statistics() -> None:
    s = get_task_statistics()
    sep = f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}"
    print()
    print(sep)
    print(f"{Fore.CYAN}zkSync Lite — РЕЗУЛЬТАТЫ ЗАПУСКА{Style.RESET_ALL}")
    print(sep)
    print(f"  Всего:              {s['total']}")
    print(f"  Выполнено:          {Fore.GREEN}{s['completed']}{Style.RESET_ALL}")
    print(f"  Pending:            {Fore.YELLOW}{s['pending']}{Style.RESET_ALL}")
    print(f"  Ошибки:             {Fore.RED}{s['failed']}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'-' * 60}{Style.RESET_ALL}")
    print(f"  💰 Активных:        {Fore.GREEN}{s['active']}{Style.RESET_ALL}")
    print(f"  🪙 С токенами:      {Fore.GREEN}{s['with_tokens']}{Style.RESET_ALL}")
    print(f"  🖼️  С NFT:          {Fore.GREEN}{s['with_nfts']}{Style.RESET_ALL}")
    print(sep)
    print()


__all__ = [
    "run_zksync_lite_checker",
    "request_stop",
    "print_run_statistics",
    "RESULT_DIR",
]
