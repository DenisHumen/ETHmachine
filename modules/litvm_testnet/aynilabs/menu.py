"""Aynilabs — submenu (plan / run / auto / stats / export / reset / info)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.cfg_litvm_testnet import (
    AYNI_GAS_RESERVE_ZKLTC,
    AYNI_MIN_NATIVE_BALANCE_ZKLTC,
    AYNI_TX_ATTEMPTS,
    AYNI_WRAP_PCT_RANGE,
    AYNI_WZKLTC_ADDRESS,
)
from config.modules.general_config import NUM_THREADS, SHUFLE_ACCOUNTS
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.aynilabs import database as db
from modules.litvm_testnet.aynilabs import excel_export
from modules.litvm_testnet.aynilabs.worker import plan_wallet, process_wallet


_PLAN_THREADS = max(1, int(NUM_THREADS))
_RUN_THREADS = max(1, int(NUM_THREADS))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _records_with_keys() -> list[dict]:
    rows = load_data()
    records = [r for r in rows if (r.get("private_key") or "").strip()]
    if SHUFLE_ACCOUNTS:
        import random as _r
        _r.shuffle(records)
    return records


def _run_threaded(records: list[dict], fn: Callable[[dict, int, int], object],
                  label: str, threads: int) -> bool:
    total = len(records)
    set_auto_progress(False)
    log_simple(
        f"🪙 Aynilabs {label}: {total} кошельков · threads={threads}",
        "info",
    )
    interrupted = False
    if threads <= 1 or total <= 1:
        for i, rec in enumerate(records, 1):
            try:
                fn(rec, i, total)
            except KeyboardInterrupt:
                log_simple(
                    "⚠ прервано пользователем (состояние сохранено в БД)",
                    "warning",
                )
                interrupted = True
                break
    else:
        with ThreadPoolExecutor(
            max_workers=threads, thread_name_prefix="ayni"
        ) as ex:
            futs = [ex.submit(fn, rec, i, total)
                    for i, rec in enumerate(records, 1)]
            try:
                for fut in as_completed(futs):
                    fut.result()
            except KeyboardInterrupt:
                for f in futs:
                    f.cancel()
                log_simple(
                    "⚠ прервано пользователем (состояние сохранено в БД)",
                    "warning",
                )
                interrupted = True
    return not interrupted


def _summary() -> str:
    s = db.get_statistics()
    return (f"total={s.get('total', 0)} "
            f"pending={s.get('pending', 0)} "
            f"arrived={s.get('arrived', 0)} "
            f"failed={s.get('failed', 0)} "
            f"skipped={s.get('skipped', 0)}")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_plan() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    threads = max(1, min(_PLAN_THREADS, len(records)))
    _run_threaded(records, plan_wallet, "PLAN", threads)
    log_simple(f"🏁 plan завершён · {_summary()}", "success")


def _handle_run() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    threads = max(1, min(_RUN_THREADS, len(records)))
    ok = _run_threaded(records, process_wallet, "RUN", threads)
    log_simple(
        f"🏁 {'готово' if ok else 'прервано'} · {_summary()}",
        "success" if ok else "warning",
    )


def _handle_auto() -> None:
    """Pipeline: plan → run → export."""
    _handle_plan()
    _handle_run()
    _handle_export()


def _handle_export() -> None:
    out = excel_export.build_report()
    log_simple(f"📑 отчёт сохранён: {out}", "success")


def _show_stats() -> None:
    s = db.get_statistics()
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Aynilabs · статистика{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    keys = ("pending", "tx_sent", "arrived", "failed", "skipped")
    for k in keys:
        print(f"  {k:<22} {s.get(k, 0)}")
    print(f"  {'-' * 40}")
    print(f"  {'TOTAL':<22} {s.get('total', 0)}")
    print()


def _show_info() -> None:
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Aynilabs · описание{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(
        "  Сайт https://www.aynilabs.xyz/dashboard/ имеет один полезный\n"
        "  on-chain action — обёртка native zkLTC в WzkLTC (1:1) через\n"
        "  вызов WzkLTC.deposit() payable. Этот модуль автоматизирует:\n"
        "    1. чтение native zkLTC баланса (через прокси кошелька)\n"
        "    2. подпись и отправка deposit() с payable value\n"
        "    3. проверка, что WzkLTC.balanceOf реально вырос\n"
    )
    print(f"  {'WzkLTC contract':<26} {AYNI_WZKLTC_ADDRESS}")
    print(f"  {'wrap fraction range':<26} "
          f"{AYNI_WRAP_PCT_RANGE[0]*100:.0f}% – {AYNI_WRAP_PCT_RANGE[1]*100:.0f}%")
    print(f"  {'min native balance':<26} {AYNI_MIN_NATIVE_BALANCE_ZKLTC} zkLTC")
    print(f"  {'gas reserve':<26} {AYNI_GAS_RESERVE_ZKLTC} zkLTC")
    print(f"  {'tx attempts':<26} {AYNI_TX_ATTEMPTS}")
    print()


def _build_menu() -> str | None:
    return select(
        "🪙 Aynilabs · выберите действие:",
        choices=[
            Choice("🤖 Авто-режим (plan → run → Excel)", "auto"),
            Choice("📋 Планирование (баланс + сумма wrap'а)", "plan"),
            Choice("▶️  Запуск wrap'а (deposit + проверка)", "run"),
            Choice("📊 Статистика БД", "stats"),
            Choice("📑 Экспорт Excel-отчёта", "export"),
            Choice("🗑️  Очистить БД", "reset"),
            Choice("📖 Информация о модуле", "info"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="🪙", pointer="👉",
    ).ask()


def run_litvm_aynilabs() -> None:
    db.init_database()
    while True:
        action = _build_menu()
        if action is None or action == "back":
            return
        if action == "auto":
            try:
                _handle_auto()
            except KeyboardInterrupt:
                pass
        elif action == "plan":
            try:
                _handle_plan()
            except KeyboardInterrupt:
                pass
        elif action == "run":
            try:
                _handle_run()
            except KeyboardInterrupt:
                pass
        elif action == "stats":
            _show_stats()
        elif action == "export":
            try:
                _handle_export()
            except Exception as e:  # noqa: BLE001
                log_simple(f"⚠ export failed: {e}", "warning")
        elif action == "info":
            _show_info()
        elif action == "reset":
            confirm = select(
                "Очистить таблицу ayni_wrap_tasks?",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_database()
                log_simple("🗑️ ayni_wrap_tasks очищена", "success")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
