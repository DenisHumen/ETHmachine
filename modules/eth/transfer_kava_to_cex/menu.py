"""Меню modules.eth.transfer_kava_to_cex."""
from __future__ import annotations

from colorama import Fore, Style
from questionary import Choice, select

from modules.simple_logger import (
    logger, log_simple, set_auto_progress,
)
from modules.eth.transfer_kava_to_cex import (
    database as db, planner, executor, excel_export,
)

set_auto_progress(False)


def _show_stats() -> None:
    stats = db.get_statistics()
    sep = f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}"
    print()
    print(sep)
    print(f"{Fore.CYAN}Transfer KAVA → CEX (Kava EVM){Style.RESET_ALL}")
    print(f"{Fore.CYAN}DB:{Style.RESET_ALL} {db.DB_PATH}")
    print(sep)
    if stats.get("wallets_total", 0) == 0:
        print(f"  {Fore.YELLOW}БД пуста — выполните «📋 Планирование»{Style.RESET_ALL}")
    else:
        print(f"  {'wallets_total':<22} {stats.get('wallets_total', 0)}")
        for k in (db.STATUS_PENDING, db.STATUS_TX_SENT, db.STATUS_AWAITING,
                  db.STATUS_ARRIVED, db.STATUS_FAILED, db.STATUS_SKIPPED):
            print(f"  {k:<22} {stats.get(k, 0)}")
        print(f"  {'-' * 40}")
        print(f"  {'total tasks':<22} {stats.get('total', 0)}")
    print(sep)
    print()


def _handle_plan() -> None:
    log_simple("📋 планирование: загружаем data.csv, декодируем kava1 → 0x…", "info")
    c = planner.plan_all()
    log_simple(
        f"📋 готово: valid={c['valid']} skipped={c['skipped']} total={c['total']}",
        "success" if c["valid"] > 0 else "warning",
    )


def _handle_run() -> None:
    try:
        summary = executor.run_all()
    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем — состояние сохранено в БД", "warning")
        return
    if summary["halted"]:
        log_simple(
            f"🛑 модуль остановлен: {summary['halt_reason']}. "
            f"executed={summary['executed']} arrived={summary['arrived']} "
            f"failed={summary['failed']}",
            "error",
        )
    else:
        log_simple(
            f"✅ цикл завершён: executed={summary['executed']} "
            f"arrived={summary['arrived']} skipped={summary['skipped']} "
            f"failed={summary['failed']} "
            f"recovered_on_recheck={summary['recovered_on_recheck']}",
            "success",
        )


def _handle_auto() -> None:
    _handle_plan()
    _handle_run()
    _handle_export()


def _handle_export() -> None:
    log_simple("📑 экспорт Excel-отчёта…", "info")
    try:
        path = excel_export.export_report()
    except Exception as exc:
        logger.exception(f"excel export: {exc}")
        return
    log_simple(f"📑 сохранено: {path}", "success")


def _handle_reset() -> None:
    db.reset_database()
    logger.success("🗑️  kava_wallets + kava_transfer_tasks очищены")


def _print_info() -> None:
    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗
║   Transfer KAVA → CEX  (Kava EVM, native KAVA)                   ║
╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}

Логика:
  • Источник: data/data.csv. Поле {Fore.YELLOW}evm_cex_address{Style.RESET_ALL} = `kava1...`
    (Cosmos bech32) — декодируется в {Fore.YELLOW}0x...{Style.RESET_ALL} (Kava EVM).
  • Сумма: {Fore.YELLOW}transfer_amount{Style.RESET_ALL} (`100-100%` = весь баланс минус газ).
  • Отправка: native KAVA, sequential (halt-on-failure).
  • Подтверждение: ждём, пока баланс на dst-адресе СТРОГО увеличится
    относительно snapshot'а до отправки. Таймаут — 5 минут.
  • При неудаче — HALT всего модуля (остальные кошельки не трогаем).
  • На повторном запуске: re-check «зависших» (вдруг пришло позже),
    затем probe на следующем кошельке — если успех, продолжаем штатно.

БД (SQLite, db/transfer_kava_to_cex.db):
  • kava_wallets         — справочник (UNIQUE wallet_address)
  • kava_transfer_tasks  — задачи (FK → kava_wallets, UNIQUE wallet_id)

Excel-отчёт:
  {Fore.YELLOW}result/transfer_kava_to_cex/run_<ts>/transfer_kava_to_cex_report.xlsx{Style.RESET_ALL}
""")


def run_transfer_kava_to_cex() -> None:
    while True:
        action = select(
            "💱 Transfer KAVA → CEX (Kava EVM):",
            choices=[
                Choice("🤖 Авто-режим (план + запуск + Excel)", "auto"),
                Choice("📋 Планирование (загрузка CSV в БД)",   "plan"),
                Choice("▶️  Запуск переводов",                   "run"),
                Choice("📊 Статистика БД",                       "stats"),
                Choice("📑 Экспорт Excel-отчёта",                "export"),
                Choice("🗑️  Очистить БД",                       "reset"),
                Choice("📖 Информация",                          "info"),
                Choice("🔙 Назад",                                "back"),
            ],
            qmark="💱",
            pointer="👉",
        ).ask()

        if action in (None, "back"):
            return
        try:
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
        except KeyboardInterrupt:
            log_simple("⚠ прервано пользователем", "warning")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")


__all__ = ["run_transfer_kava_to_cex"]
