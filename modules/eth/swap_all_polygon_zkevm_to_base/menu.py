"""Меню swap-all Polygon zkEVM → Base USDC."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from colorama import Fore, Style
from questionary import Choice, select

from modules.simple_logger import (
    logger, log_wallet_task, log_simple, set_auto_progress,
)
from modules.eth.swap_all_polygonzk_to_base import (
    database as db, planner, excel_export,
)
from modules.eth.swap_all_polygonzk_to_base.executor import SwapAllExecutor
from config.modules.cfg_base import NUM_THREADS as _CFG_NUM_THREADS

PLAN_NUM_THREADS = max(1, int(_CFG_NUM_THREADS))

# В этом модуле прогресс по кошелькам читается из [i/N] в каждой строке —
# отдельный tqdm-бар не нужен.
set_auto_progress(False)


def _show_stats() -> None:
    stats = db.get_statistics()
    sep = f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}"
    print()
    print(sep)
    print(f"{Fore.CYAN}Polygon zkEVM → Base USDC — Swap All{Style.RESET_ALL}")
    print(f"{Fore.CYAN}DB:{Style.RESET_ALL} {db.DB_PATH}")
    print(sep)
    if stats.get("total", 0) == 0:
        print(f"  {Fore.YELLOW}БД пуста{Style.RESET_ALL}")
    else:
        for k, v in stats.items():
            if k == "total":
                continue
            print(f"  {k:<22} {v}")
        print(f"  {'-' * 40}")
        print(f"  total                  {stats['total']}")
    print(sep)
    print()


def _plan_all(records, num_threads: int = PLAN_NUM_THREADS) -> dict:
    """Phase 1: многопоточно создать задачи в БД для всех кошельков.

    Каждому кошельку присваивается стабильный индекс [i/total] (его позиция
    в data.csv), вне зависимости от порядка завершения worker-thread'ов.
    OKLink-вызовы — сетевой I/O → GIL не мешает, даём много потоков.
    SQLite-запись из планнера thread-safe (WAL, отдельное соединение на upsert).
    """
    total = len(records)
    counters = {"planned": 0, "with_tasks": 0, "skipped_no_tokens": 0,
                "errors": 0}
    lock = threading.Lock()

    threads = max(1, min(int(num_threads), total)) if total else 1
    log_simple(
        f"📋 планирование: создаём задачи для {total} кошельков "
        f"(threads={threads})", "info",
    )
    # Гарантируем, что схема БД создана до конкурентных upsert'ов из тредов
    db.init_database()

    def _one(idx: int, rec):
        wallet = rec["wallet"]
        name = rec.get("name") or ""
        try:
            plan = planner.plan_one_wallet(rec, refresh=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            with lock:
                log_wallet_task(wallet, idx, total, f"⚠ plan error: {exc}",
                                "error", account_name=name)
                counters["errors"] += 1
            return
        with lock:
            counters["planned"] += 1
            if plan["supported_count"] > 0:
                counters["with_tasks"] += 1
                status = "success" if plan["ok"] else "warning"
                log_wallet_task(
                    wallet, idx, total,
                    f"📋 tokens={plan['tokens_total']} swap={plan['supported_count']} "
                    f"USD={plan['total_usd']:.2f}",
                    status, account_name=name,
                )
            else:
                counters["skipped_no_tokens"] += 1
                log_wallet_task(
                    wallet, idx, total,
                    f"⏭  no supported tokens (tokens={plan['tokens_total']})",
                    "warning", account_name=name,
                )

    if threads <= 1 or total <= 1:
        for i, rec in enumerate(records, 1):
            _one(i, rec)
        return counters

    with ThreadPoolExecutor(max_workers=threads,
                             thread_name_prefix="plan") as ex:
        futs = [ex.submit(_one, i, rec)
                for i, rec in enumerate(records, 1)]
        try:
            for fut in as_completed(futs):
                # Re-raise any non-handled exception (KeyboardInterrupt etc.)
                fut.result()
        except KeyboardInterrupt:
            for f in futs:
                f.cancel()
            raise
    return counters


def _swap_all(records, executor: SwapAllExecutor) -> dict:
    """Phase 2: пройтись по всем кошелькам и свапнуть тех, у кого
    есть pending-задачи. Счётчик [i/N] — по всем кошелькам из data.csv."""
    total = len(records)
    pending_set = {w.lower() for w in db.list_wallets_with_pending()}
    counters = {"swapped": 0, "skipped": 0, "errors": 0}
    log_simple(
        f"💱 swap-all: всего {total} кошельков, "
        f"к работе {len(pending_set)} (с pending-задачами)", "info",
    )
    for i, rec in enumerate(records, 1):
        wallet = rec["wallet"]
        name = rec.get("name") or ""
        if wallet.lower() not in pending_set:
            counters["skipped"] += 1
            continue
        log_wallet_task(wallet, i, total, "💱 swapping…", "info",
                        account_name=name)
        try:
            executor.run_wallet(wallet, task_index=i, task_total=total)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log_wallet_task(wallet, i, total, f"unhandled error: {exc}",
                            "error", account_name=name)
            counters["errors"] += 1
            continue
        counters["swapped"] += 1
        log_wallet_task(wallet, i, total, "✅ done", "success",
                        account_name=name)
    return counters


def _handle_plan() -> None:
    records = planner._build_records()
    if not records:
        log_simple("data/data.csv пуст или не содержит приватных ключей",
                   "warning")
        return
    _plan_all(records)
    log_simple(f"итог в БД: {db.get_statistics()}", "info")


def _handle_run() -> None:
    pending = db.list_wallets_with_pending()
    if not pending:
        log_simple("нет pending-задач — сначала «Планирование»", "warning")
        return
    records = planner._build_records()
    if not records:
        log_simple("data/data.csv пуст", "warning")
        return
    try:
        _swap_all(records, SwapAllExecutor())
    except KeyboardInterrupt:
        log_simple("прервано пользователем", "warning")
        return
    log_simple(f"готово: {db.get_statistics()}", "success")


def _handle_auto() -> None:
    """Авто-режим: 1) план для ВСЕХ кошельков (создаём все задачи в БД),
    2) свап всех кошельков с pending, 3) Excel."""
    records = planner._build_records()
    if not records:
        log_simple("data/data.csv пуст или не содержит приватных ключей",
                   "warning")
        return

    total = len(records)
    log_simple(f"загружено {total} кошельков из data.csv", "info")

    # Phase 1: plan all (skip those уже завершённые ранее не трогаются upsert-ом)
    pending_before = {w.lower() for w in db.list_wallets_with_pending()}
    if pending_before:
        log_simple(
            f"🔁 в БД уже {len(pending_before)} незавершённых кошельков — "
            f"они будут доделаны после планирования", "info",
        )
    try:
        plan_stats = _plan_all(records)
    except KeyboardInterrupt:
        log_simple("прервано на этапе планирования — состояние в БД сохранено",
                   "warning")
        return
    log_simple(
        f"план готов: planned={plan_stats['planned']} "
        f"with_tasks={plan_stats['with_tasks']} "
        f"skipped_no_tokens={plan_stats['skipped_no_tokens']} "
        f"errors={plan_stats['errors']}", "info",
    )

    # Phase 2: swap
    try:
        swap_stats = _swap_all(records, SwapAllExecutor())
    except KeyboardInterrupt:
        log_simple("прервано — состояние в БД сохранено, "
                   "запустите авто-режим для продолжения", "warning")
        _handle_export()
        return
    log_simple(
        f"свап завершён: swapped={swap_stats['swapped']} "
        f"skipped={swap_stats['skipped']} errors={swap_stats['errors']}",
        "info",
    )

    # Phase 3: Excel
    _handle_export()
    log_simple(f"финальная статистика: {db.get_statistics()}", "success")


def _handle_export() -> None:
    log_simple("экспортируем Excel-отчёт…", "info")
    try:
        path = excel_export.export_report()
    except Exception as exc:
        logger.exception(f"excel export: {exc}")
        return
    log_simple(f"сохранено: {path}", "success")


def _handle_reset() -> None:
    db.reset_database()
    logger.success("swap_all_tasks очищена")


def _print_info() -> None:
    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗
║   Polygon zkEVM → Base USDC — Swap All (Layerswap)               ║
╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}

Маршруты Layerswap:
  {Fore.GREEN}USDC{Style.RESET_ALL} (Polygon zkEVM) → {Fore.GREEN}USDC{Style.RESET_ALL} (Base)
  {Fore.GREEN}ETH{Style.RESET_ALL}  (Polygon zkEVM) → {Fore.GREEN}ETH{Style.RESET_ALL}  (Base)
  Прочие токены — пропускаются («skipped»).

Pipeline-режим: для каждого кошелька — план балансов → сразу свап →
переход к следующему. Если процесс прерван, при повторном запуске
авто-режима он сначала доделает кошельки с pending-задачами в БД.

Источник балансов: OKLink (web-internal API).
Источник кошельков: {Fore.YELLOW}data/data.csv{Style.RESET_ALL}.
БД задач:           {Fore.YELLOW}db/swap_all_polygonzk_to_base.db{Style.RESET_ALL}.

Excel-отчёт:
  {Fore.YELLOW}result/swap_all_polygonzk_to_base/run_<timestamp>/swap_all_report.xlsx{Style.RESET_ALL}
""")


def run_swap_all_polygonzk_to_base() -> None:
    while True:
        action = select(
            "💱 Polygon zkEVM → Base USDC swap-all:",
            choices=[
                Choice("🤖 Авто-режим (pipeline + резюм + Excel)", "auto"),
                Choice("📋 Планирование (баланс + классификация)", "plan"),
                Choice("▶️  Запуск свапа",                         "run"),
                Choice("📊 Статистика БД",                         "stats"),
                Choice("📑 Экспорт Excel-отчёта",                  "export"),
                Choice("🗑️  Очистить БД",                         "reset"),
                Choice("📖 Информация",                            "info"),
                Choice("🔙 Назад",                                  "back"),
            ],
            qmark="💱",
            pointer="👉",
        ).ask()

        if action in (None, "back"):
            return
        if action == "auto":
            _handle_auto()
        elif action == "plan":
            _handle_plan()
        elif action == "run":
            _handle_run()
        elif action == "stats":
            _show_stats()
        elif action == "export":
            _handle_export()
        elif action == "reset":
            _handle_reset()
        elif action == "info":
            _print_info()
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")


__all__ = ["run_swap_all_polygonzk_to_base"]
