"""Меню дрейнера Polygon zkEVM → Base USDC."""
from __future__ import annotations

from colorama import Fore, Style
from questionary import Choice, select

from modules.simple_logger import (
    logger, log_wallet_task, log_simple, set_auto_progress,
)
from modules.eth.drainer_polygonzk_to_base import (
    database as db, planner, excel_export,
)
from modules.eth.drainer_polygonzk_to_base.executor import DrainerExecutor

# В этом модуле прогресс по кошелькам читается из [i/N] в каждой строке —
# отдельный tqdm-бар не нужен.
set_auto_progress(False)


def _show_stats() -> None:
    stats = db.get_statistics()
    sep = f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}"
    print()
    print(sep)
    print(f"{Fore.CYAN}Polygon zkEVM → Base USDC — Drainer{Style.RESET_ALL}")
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


def _plan_all(records) -> dict:
    """Phase 1: создать задачи в БД для всех кошельков. Возвращает счётчики."""
    total = len(records)
    counters = {"planned": 0, "with_tasks": 0, "skipped_no_tokens": 0,
                "errors": 0}
    log_simple(f"📋 планирование: создаём задачи для {total} кошельков", "info")
    for i, rec in enumerate(records, 1):
        wallet = rec["wallet"]
        name = rec.get("name") or ""
        try:
            plan = planner.plan_one_wallet(rec, refresh=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log_wallet_task(wallet, i, total, f"⚠ plan error: {exc}",
                            "error", account_name=name)
            counters["errors"] += 1
            continue
        counters["planned"] += 1
        if plan["supported_count"] > 0:
            counters["with_tasks"] += 1
            status = "success" if plan["ok"] else "warning"
            log_wallet_task(
                wallet, i, total,
                f"📋 tokens={plan['tokens_total']} swap={plan['supported_count']} "
                f"USD={plan['total_usd']:.2f}",
                status, account_name=name,
            )
        else:
            counters["skipped_no_tokens"] += 1
            log_wallet_task(wallet, i, total,
                            f"⏭  no supported tokens (tokens={plan['tokens_total']})",
                            "warning", account_name=name)
    return counters


def _drain_all(records, executor: DrainerExecutor) -> dict:
    """Phase 2: пройтись по всем кошелькам и задрейнить тех, у кого
    есть pending-задачи. Счётчик [i/N] — по всем кошелькам из data.csv."""
    total = len(records)
    pending_set = {w.lower() for w in db.list_wallets_with_pending()}
    counters = {"drained": 0, "skipped": 0, "errors": 0}
    log_simple(
        f"🩸 дрейнер: всего {total} кошельков, "
        f"к работе {len(pending_set)} (с pending-задачами)", "info",
    )
    for i, rec in enumerate(records, 1):
        wallet = rec["wallet"]
        name = rec.get("name") or ""
        if wallet.lower() not in pending_set:
            counters["skipped"] += 1
            continue
        log_wallet_task(wallet, i, total, "🩸 draining…", "info",
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
        counters["drained"] += 1
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
        _drain_all(records, DrainerExecutor())
    except KeyboardInterrupt:
        log_simple("прервано пользователем", "warning")
        return
    log_simple(f"готово: {db.get_statistics()}", "success")


def _handle_auto() -> None:
    """Авто-режим: 1) план для ВСЕХ кошельков (создаём все задачи в БД),
    2) дрейн всех кошельков с pending, 3) Excel."""
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

    # Phase 2: drain
    try:
        drain_stats = _drain_all(records, DrainerExecutor())
    except KeyboardInterrupt:
        log_simple("прервано — состояние в БД сохранено, "
                   "запустите авто-режим для продолжения", "warning")
        _handle_export()
        return
    log_simple(
        f"дрейн завершён: drained={drain_stats['drained']} "
        f"skipped={drain_stats['skipped']} errors={drain_stats['errors']}",
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
    logger.success("drainer_tasks очищена")


def _print_info() -> None:
    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗
║   Polygon zkEVM → Base USDC — Drainer (Layerswap)                ║
╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}

Маршруты Layerswap:
  {Fore.GREEN}USDC{Style.RESET_ALL} (Polygon zkEVM) → {Fore.GREEN}USDC{Style.RESET_ALL} (Base)
  {Fore.GREEN}ETH{Style.RESET_ALL}  (Polygon zkEVM) → {Fore.GREEN}ETH{Style.RESET_ALL}  (Base)
  Прочие токены — пропускаются («skipped»).

Pipeline-режим: для каждого кошелька — план балансов → сразу дрейн →
переход к следующему. Если процесс прерван, при повторном запуске
авто-режима он сначала доделает кошельки с pending-задачами в БД.

Источник балансов: OKLink (web-internal API).
Источник кошельков: {Fore.YELLOW}data/data.csv{Style.RESET_ALL}.
БД задач:           {Fore.YELLOW}db/drainer_polygonzk_to_base.db{Style.RESET_ALL}.

Excel-отчёт:
  {Fore.YELLOW}result/drainer_polygonzk_to_base/run_<timestamp>/drainer_report.xlsx{Style.RESET_ALL}
""")


def run_drainer_polygonzk_to_base() -> None:
    while True:
        action = select(
            "🩸 Polygon zkEVM → Base USDC drainer:",
            choices=[
                Choice("🤖 Авто-режим (pipeline + резюм + Excel)", "auto"),
                Choice("📋 Планирование (баланс + классификация)", "plan"),
                Choice("▶️  Запуск дрейнера",                    "run"),
                Choice("📊 Статистика БД",                       "stats"),
                Choice("📑 Экспорт Excel-отчёта",                "export"),
                Choice("🗑️  Очистить БД",                       "reset"),
                Choice("📖 Информация",                          "info"),
                Choice("🔙 Назад",                                "back"),
            ],
            qmark="🩸",
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


__all__ = ["run_drainer_polygonzk_to_base"]
