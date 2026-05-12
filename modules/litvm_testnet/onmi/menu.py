"""Onmi · submenu (auto / plan / run / stats / export / reset / info)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.cfg_litvm_testnet import (
    ONMI_DESCRIPTION_PROBABILITY,
    ONMI_GAS_RESERVE_ZKLTC,
    ONMI_INITIAL_BUY_PROBABILITY,
    ONMI_INITIAL_BUY_RANGE_ZKLTC,
    ONMI_MIN_NATIVE_BALANCE_ZKLTC,
    ONMI_SITE_BOARD,
    ONMI_SITE_CREATE,
    ONMI_SITE_DOCS,
    ONMI_SITE_LIQUIDITY,
    ONMI_SITE_SWAP,
    ONMI_TOKEN_FACTORY,
    ONMI_TX_ATTEMPTS,
)
from config.modules.general_config import NUM_THREADS, SHUFLE_ACCOUNTS
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.onmi import database as db
from modules.litvm_testnet.onmi import excel_export
from modules.litvm_testnet.onmi.worker import plan_wallet, process_wallet


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


def _run_threaded(records: list[dict],
                  fn: Callable[[dict, int, int], object],
                  label: str, threads: int) -> bool:
    total = len(records)
    set_auto_progress(False)
    log_simple(f"🪙 Onmi {label}: {total} кошельков · threads={threads}", "info")
    interrupted = False
    if threads <= 1 or total <= 1:
        for i, rec in enumerate(records, 1):
            try:
                fn(rec, i, total)
            except KeyboardInterrupt:
                log_simple("⚠ прервано пользователем (состояние сохранено в БД)",
                           "warning")
                interrupted = True
                break
    else:
        with ThreadPoolExecutor(max_workers=threads,
                                thread_name_prefix="onmi") as ex:
            futs = [ex.submit(fn, rec, i, total)
                    for i, rec in enumerate(records, 1)]
            try:
                for fut in as_completed(futs):
                    fut.result()
            except KeyboardInterrupt:
                for f in futs:
                    f.cancel()
                log_simple("⚠ прервано пользователем (состояние сохранено в БД)",
                           "warning")
                interrupted = True
    return not interrupted


def _summary() -> str:
    s = db.get_statistics()
    return (f"total={s.get('total', 0)} "
            f"pending={s.get('pending', 0)} "
            f"image_ready={s.get('image_ready', 0)} "
            f"metadata_ready={s.get('metadata_ready', 0)} "
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
    log_simple(f"🏁 {'готово' if ok else 'прервано'} · {_summary()}",
               "success" if ok else "warning")


def _handle_auto() -> None:
    _handle_plan()
    _handle_run()
    _handle_export()


def _handle_export() -> None:
    out = excel_export.build_report()
    log_simple(f"📑 отчёт сохранён: {out}", "success")


def _show_stats() -> None:
    s = db.get_statistics()
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Onmi · статистика{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    keys = ("pending", "image_ready", "metadata_ready",
            "tx_sent", "arrived", "failed", "skipped")
    for k in keys:
        print(f"  {k:<22} {s.get(k, 0)}")
    print(f"  {'-' * 40}")
    print(f"  {'TOTAL':<22} {s.get('total', 0)}")
    print()


def _show_info() -> None:
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Onmi.fun · описание{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(
        "  Лаунчпад мем-токенов на LITVM (https://app.onmi.fun/?chain=LITVM).\n"
        "  Модуль повторяет полный flow создания монеты:\n"
        "    1. генерация name / symbol (description в ~5% случаев)\n"
        "    2. скачивание картинки с Pinterest, ресайз 1:1 ≥ 1000×1000, ≤1 MB\n"
        "    3. POST /api/upload/image     → S3 URL картинки\n"
        "    4. POST /api/upload/metadata  → metadataURI (JSON на S3)\n"
        "    5. on-chain factory.createTokenAndBuy() / createToken()\n"
        "    6. парсинг receipt → token address + tokens_received\n"
        "  AI Magic на сегодня отключён сервером (AI_MAGIC_ENABLED=false)."
    )
    print(f"  {'TokenLaunch factory':<26} {ONMI_TOKEN_FACTORY}")
    print(f"  {'min native balance':<26} {ONMI_MIN_NATIVE_BALANCE_ZKLTC} zkLTC")
    print(f"  {'gas reserve':<26} {ONMI_GAS_RESERVE_ZKLTC} zkLTC")
    print(f"  {'initial buy prob':<26} {ONMI_INITIAL_BUY_PROBABILITY*100:.0f}%")
    print(f"  {'initial buy range':<26} "
          f"{ONMI_INITIAL_BUY_RANGE_ZKLTC[0]} – {ONMI_INITIAL_BUY_RANGE_ZKLTC[1]} zkLTC")
    print(f"  {'description prob':<26} {ONMI_DESCRIPTION_PROBABILITY*100:.0f}%")
    print(f"  {'tx attempts':<26} {ONMI_TX_ATTEMPTS}")
    print()
    print(f"  {Fore.YELLOW}Сайты Onmi.fun (LITVM):{Style.RESET_ALL}")
    print(f"  {'  • создать токен':<26} {ONMI_SITE_CREATE}")
    print(f"  {'  • board (торговля)':<26} {ONMI_SITE_BOARD}")
    print(f"  {'  • swap':<26} {ONMI_SITE_SWAP}")
    print(f"  {'  • liquidity':<26} {ONMI_SITE_LIQUIDITY}")
    print(f"  {'  • docs':<26} {ONMI_SITE_DOCS}")
    print()


def _build_menu() -> str | None:
    return select(
        "🪙 Onmi.fun · выберите действие:",
        choices=[
            Choice("🤖 Авто-режим (plan → run → Excel)", "auto"),
            Choice("📋 Планирование (баланс + генерация метаданных)", "plan"),
            Choice("▶️  Запуск создания монет", "run"),
            Choice("📊 Статистика БД", "stats"),
            Choice("📑 Экспорт Excel-отчёта", "export"),
            Choice("🗑️  Очистить БД", "reset"),
            Choice("📖 Информация о модуле", "info"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="🪙", pointer="👉",
    ).ask()


def run_litvm_onmi() -> None:
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
                "Очистить таблицу onmi_coin_tasks?",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_database()
                log_simple("🗑️ onmi_coin_tasks очищена", "success")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
