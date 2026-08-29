"""Меню modules.eth.transfer_kava_to_cex."""
from __future__ import annotations

from modules.eth.transfer_kava_to_cex import (
    database as db, excel_export, executor, planner,
)
from modules.simple_logger import log_simple, logger, set_auto_progress
from modules.ui.module_menu import MenuAction, ModuleMenu

# В логах уже есть [i/N] — второй индикатор прогресса не нужен.
set_auto_progress(False)


def _handle_plan() -> None:
    log_simple("📋 планирование: загружаем data.csv, декодируем kava1 → 0x…", "info")
    counters = planner.plan_all()
    log_simple(
        f"📋 готово: valid={counters['valid']} skipped={counters['skipped']} "
        f"total={counters['total']}",
        "success" if counters["valid"] > 0 else "warning",
    )


def _handle_run() -> None:
    summary = executor.run_all()
    if summary["halted"]:
        log_simple(
            f"🛑 модуль остановлен: {summary['halt_reason']}. "
            f"executed={summary['executed']} arrived={summary['arrived']} "
            f"failed={summary['failed']}",
            "error",
        )
        return
    log_simple(
        f"✅ цикл завершён: executed={summary['executed']} "
        f"arrived={summary['arrived']} skipped={summary['skipped']} "
        f"failed={summary['failed']} "
        f"recovered_on_recheck={summary['recovered_on_recheck']}",
        "success",
    )


def _handle_export() -> None:
    log_simple("📑 экспорт Excel-отчёта…", "info")
    try:
        path = excel_export.export_report()
    except Exception as exc:
        logger.exception(f"excel export: {exc}")
        return
    log_simple(f"📑 сохранено: {path}", "success")


def _handle_auto() -> None:
    _handle_plan()
    _handle_run()
    _handle_export()


def _stats() -> dict:
    """Статистика в порядке жизненного цикла задачи, а не в алфавитном."""
    raw = db.get_statistics()
    ordered = {"кошельков": raw.get("wallets_total", 0)}
    labels = {
        db.STATUS_PENDING: "ожидают",
        db.STATUS_TX_SENT: "отправлено",
        db.STATUS_AWAITING: "ждём зачисления",
        db.STATUS_ARRIVED: "зачислено",
        db.STATUS_FAILED: "ошибка",
        db.STATUS_SKIPPED: "пропущено",
    }
    for status, label in labels.items():
        ordered[label] = raw.get(status, 0)
    ordered["total"] = raw.get("total", 0)
    return ordered


def _info() -> dict:
    return {
        "Как это работает": [
            "Источник — data/data.csv: в evm_cex_address ожидается адрес "
            "кошелька Kava в формате kava1… (Cosmos bech32).",
            "Адрес декодируется в 0x-форму сети Kava EVM.",
            "Сумма берётся из transfer_amount: «100-100%» — весь баланс "
            "за вычетом газа.",
            "Переводы идут последовательно; после каждого ждём, пока баланс "
            "получателя реально вырастет (таймаут 5 минут).",
            "Если перевод не подтвердился — модуль останавливается целиком, "
            "остальные кошельки не трогает.",
            "При повторном запуске сначала перепроверяются «зависшие» "
            "переводы — деньги могли дойти позже.",
        ],
        "Где что лежит": [
            f"База задач: db/{db.DB_PATH.name}",
            "Справочник кошельков: таблица kava_wallets",
            "Задачи: таблица kava_transfer_tasks",
            "Отчёт: result/transfer_kava_to_cex/run_<время>/"
            "transfer_kava_to_cex_report.xlsx",
        ],
    }


def run_transfer_kava_to_cex() -> None:
    ModuleMenu(
        title="Перевод KAVA на биржу",
        subtitle="нативный KAVA, сеть Kava EVM",
        icon="🌊",
        actions=[
            MenuAction("auto", "Авто-режим", _handle_auto,
                       "планирование, переводы и отчёт подряд", icon="🤖"),
            MenuAction("plan", "Планирование", _handle_plan,
                       "загрузить кошельки из data.csv в базу", icon="📋"),
            MenuAction("run", "Запуск переводов", _handle_run,
                       "отправить и дождаться зачисления", icon="▶️"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title=f"Прогресс · {db.DB_PATH.name}",
        reset=db.reset_database,
        info=_info,
    ).run()


__all__ = ["run_transfer_kava_to_cex"]
