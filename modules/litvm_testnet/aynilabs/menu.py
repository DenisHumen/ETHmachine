"""Меню modules.litvm_testnet.aynilabs — обёртка zkLTC в WzkLTC."""
from __future__ import annotations

from typing import Callable

from config.modules.cfg_litvm_testnet import (
    AYNI_GAS_RESERVE_ZKLTC,
    AYNI_MIN_NATIVE_BALANCE_ZKLTC,
    AYNI_TX_ATTEMPTS,
    AYNI_WRAP_PCT_RANGE,
    AYNI_WZKLTC_ADDRESS,
)
from config.modules.general_config import NUM_THREADS, SHUFLE_ACCOUNTS
from modules.core.runner import resolve_threads, run_parallel
from modules.data_manager import load_data
from modules.litvm_testnet.aynilabs import database as db
from modules.litvm_testnet.aynilabs import excel_export
from modules.litvm_testnet.aynilabs.worker import plan_wallet, process_wallet
from modules.simple_logger import log_simple, set_auto_progress
from modules.ui.module_menu import MenuAction, ModuleMenu


def _records_with_keys() -> list[dict]:
    rows = load_data()
    records = [r for r in rows if (r.get("private_key") or "").strip()]
    if SHUFLE_ACCOUNTS:
        import random as _r
        _r.shuffle(records)
    return records


def _run_threaded(records: list[dict],
                  fn: Callable[[dict, int, int], object],
                  label: str) -> bool:
    """Обходит кошельки; False — пользователь прервал обход."""
    total = len(records)
    threads = resolve_threads(NUM_THREADS, total)
    set_auto_progress(False)
    log_simple(f"🪙 Aynilabs {label}: {total} кошельков · threads={threads}",
               "info")
    try:
        run_parallel(records, lambda index, rec: fn(rec, index, total),
                     threads=threads, thread_name_prefix="ayni")
    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем (состояние сохранено в БД)",
                   "warning")
        return False
    return True


def _summary() -> str:
    s = db.get_statistics()
    return (f"total={s.get('total', 0)} "
            f"pending={s.get('pending', 0)} "
            f"arrived={s.get('arrived', 0)} "
            f"failed={s.get('failed', 0)} "
            f"skipped={s.get('skipped', 0)}")


def _handle_plan() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    _run_threaded(records, plan_wallet, "PLAN")
    log_simple(f"🏁 plan завершён · {_summary()}", "success")


def _handle_run() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    ok = _run_threaded(records, process_wallet, "RUN")
    log_simple(f"🏁 {'готово' if ok else 'прервано'} · {_summary()}",
               "success" if ok else "warning")


def _handle_export() -> None:
    try:
        out = excel_export.build_report()
    except Exception as exc:  # noqa: BLE001 — отчёт не должен ронять меню
        log_simple(f"⚠ export failed: {exc}", "warning")
        return
    log_simple(f"📑 отчёт сохранён: {out}", "success")


def _handle_auto() -> None:
    _handle_plan()
    _handle_run()
    _handle_export()


def _stats() -> dict:
    """Статистика в порядке жизненного цикла задачи, а не в алфавитном."""
    raw = db.get_statistics()
    labels = {
        "pending": "ожидают",
        "tx_sent": "отправлено",
        "arrived": "завёрнуто",
        "failed": "ошибка",
        "skipped": "пропущено",
    }
    ordered = {label: raw.get(status, 0) for status, label in labels.items()}
    ordered["total"] = raw.get("total", 0)
    return ordered


def _info() -> dict:
    wrap_lo, wrap_hi = AYNI_WRAP_PCT_RANGE
    return {
        "Как это работает": [
            "На aynilabs.xyz есть ровно одно полезное on-chain действие — "
            "обёртка нативного zkLTC в WzkLTC один к одному вызовом "
            "WzkLTC.deposit() с payable-значением.",
            "Модуль делает это сам:",
            "1. читает баланс нативного zkLTC через прокси кошелька;",
            "2. подписывает и отправляет deposit() с рассчитанной суммой;",
            "3. проверяет, что WzkLTC.balanceOf действительно вырос.",
        ],
        "Параметры": [
            f"Контракт WzkLTC — {AYNI_WZKLTC_ADDRESS}",
            f"Доля баланса на обёртку — {wrap_lo * 100:.0f}% – "
            f"{wrap_hi * 100:.0f}%",
            f"Минимальный баланс — {AYNI_MIN_NATIVE_BALANCE_ZKLTC} zkLTC",
            f"Резерв на газ — {AYNI_GAS_RESERVE_ZKLTC} zkLTC",
            f"Попыток на транзакцию — {AYNI_TX_ATTEMPTS}",
        ],
        "Где что лежит": [
            "База задач: db/litvm.db, таблица ayni_wrap_tasks",
            "Отчёт: result/aynilabs/run_<время>/",
        ],
    }


def _menu() -> ModuleMenu:
    return ModuleMenu(
        title="Aynilabs",
        subtitle="обёртка zkLTC в WzkLTC",
        icon="🪙",
        actions=[
            MenuAction("auto", "Авто-режим", _handle_auto,
                       "планирование, обёртка и отчёт подряд", icon="🤖"),
            MenuAction("plan", "Планирование", _handle_plan,
                       "снять балансы и рассчитать сумму обёртки", icon="📋"),
            MenuAction("run", "Запуск обёртки", _handle_run,
                       "отправить deposit() и проверить результат",
                       icon="▶️"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title="Прогресс · ayni_wrap_tasks",
        reset=db.reset_database,
        info=_info,
    )


def run_litvm_aynilabs() -> None:
    db.init_database()
    _menu().run()


__all__ = ["run_litvm_aynilabs"]
