"""Меню swap-all zkSync Era → Base USDC (Rhino.fi)."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from modules.simple_logger import (
    logger, log_wallet_task, log_simple, set_auto_progress,
)
from modules.ui.module_menu import MenuAction, ModuleMenu
from modules.eth.swap_all_zksync_era_to_base import (
    database as db, planner, excel_export,
)
from modules.eth.swap_all_zksync_era_to_base.executor import SwapAllExecutor
from config.modules.general_config import NUM_THREADS as _CFG_NUM_THREADS

PLAN_NUM_THREADS = max(1, int(_CFG_NUM_THREADS))
SWAP_NUM_THREADS = max(1, int(_CFG_NUM_THREADS))

set_auto_progress(False)


def _plan_all(records, num_threads: int = PLAN_NUM_THREADS) -> dict:
    total = len(records)
    counters = {"planned": 0, "with_tasks": 0, "skipped_no_tokens": 0,
                "errors": 0}
    lock = threading.Lock()
    threads = max(1, min(int(num_threads), total)) if total else 1
    log_simple(
        f"📋 планирование: создаём задачи для {total} кошельков "
        f"(threads={threads})", "info",
    )
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
                             thread_name_prefix="plan_zk") as ex:
        futs = [ex.submit(_one, i, rec)
                for i, rec in enumerate(records, 1)]
        try:
            for fut in as_completed(futs):
                fut.result()
        except KeyboardInterrupt:
            for f in futs:
                f.cancel()
            raise
    return counters


def _swap_all(records, executor: SwapAllExecutor,
              num_threads: int = SWAP_NUM_THREADS) -> dict:
    total = len(records)
    pending_set = {w.lower() for w in db.list_wallets_with_pending()}
    counters = {"swapped": 0, "skipped": 0, "errors": 0, "failed": 0}
    todo = [(i, rec) for i, rec in enumerate(records, 1)
            if rec["wallet"].lower() in pending_set]
    counters["skipped"] = total - len(todo)
    threads = max(1, min(int(num_threads), len(todo))) if todo else 1
    log_simple(
        f"💱 swap-all: всего {total} кошельков, "
        f"к работе {len(todo)} (threads={threads})", "info",
    )
    if not todo:
        return counters
    lock = threading.Lock()

    def _one(idx: int, rec) -> None:
        wallet = rec["wallet"]
        name = rec.get("name") or ""
        log_wallet_task(wallet, idx, total, "💱 swapping…", "info",
                        account_name=name)
        try:
            executor.run_wallet(wallet, task_index=idx, task_total=total)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            with lock:
                log_wallet_task(wallet, idx, total,
                                f"unhandled error: {exc}", "error",
                                account_name=name)
                counters["errors"] += 1
            return
        failed_tokens = db.list_failed_tokens_for_wallet(wallet)
        if failed_tokens:
            with lock:
                counters["failed"] += 1
            log_wallet_task(
                wallet, idx, total,
                f"⚠ failed tokens: {','.join(failed_tokens)} — будут "
                f"повторены при следующем запуске",
                "error", account_name=name,
            )
            return
        with lock:
            counters["swapped"] += 1
        log_wallet_task(wallet, idx, total, "✅ done", "success",
                        account_name=name)

    if threads <= 1 or len(todo) <= 1:
        for idx, rec in todo:
            _one(idx, rec)
        return counters

    with ThreadPoolExecutor(max_workers=threads,
                             thread_name_prefix="swap_zk") as ex:
        futs = [ex.submit(_one, idx, rec) for idx, rec in todo]
        try:
            for fut in as_completed(futs):
                fut.result()
        except KeyboardInterrupt:
            for f in futs:
                f.cancel()
            raise
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
    records = planner._build_records()
    if not records:
        log_simple("data/data.csv пуст или не содержит приватных ключей",
                   "warning")
        return

    total = len(records)
    log_simple(f"загружено {total} кошельков из data.csv", "info")

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

    try:
        swap_stats = _swap_all(records, SwapAllExecutor())
    except KeyboardInterrupt:
        log_simple("прервано — состояние в БД сохранено, "
                   "запустите авто-режим для продолжения", "warning")
        _handle_export()
        return
    log_simple(
        f"свап завершён: swapped={swap_stats['swapped']} "
        f"failed={swap_stats.get('failed', 0)} "
        f"skipped={swap_stats['skipped']} errors={swap_stats['errors']}",
        "info",
    )

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


def _info_sections() -> dict:
    return {
        "Маршруты Rhino.fi (mode=pay)": [
            "USDC (zkSync Era) → USDC (Base)",
            "USDT (zkSync Era) → USDC (Base)",
            "нативный ETH не свапается — нужен на газ",
        ],
        "On-chain": [
            "depositWithId(token, amount, commitmentId) на bridge-контракте",
            "Rhino.fi — 0x1fa66e2b38d0cc496ec51f81c3e05e6a6708986f",
            "commitmentId = uint256(quoteId)",
        ],
        "Откуда данные": [
            "балансы — OKLink (web-internal API, chain=zksync_era)",
            "кошельки — data/data.csv",
            f"задачи — {db.DB_PATH}",
        ],
        "Отчёт": [
            "result/swap_all_zksync_era_to_base/run_<timestamp>/"
            "swap_all_report.xlsx",
        ],
    }


def run_swap_all_zksync_era_to_base() -> None:
    ModuleMenu(
        title="zkSync Era → Base USDC",
        subtitle="swap-all через Rhino.fi",
        icon="💱",
        actions=[
            MenuAction("auto", "Авто-режим", _handle_auto,
                       "план, свап и Excel одной кнопкой", icon="🤖"),
            MenuAction("plan", "Планирование", _handle_plan,
                       "снять балансы и создать задачи", icon="📋"),
            MenuAction("run", "Запуск свапа", _handle_run,
                       "выполнить незавершённые задачи", icon="▶️"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по результатам прогона", icon="📑"),
        ],
        stats=db.get_statistics,
        stats_title=str(db.DB_PATH),
        reset=db.reset_database,
        info=_info_sections,
    ).run()


__all__ = ["run_swap_all_zksync_era_to_base"]
