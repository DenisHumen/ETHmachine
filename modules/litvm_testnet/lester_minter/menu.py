"""Lester Minter — UI меню пресета."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.general_config import NUM_THREADS
from config.modules.cfg_litvm_testnet import (
    LITVM_MINTER_DEPLOY_FEE_WEI,
    LITVM_MINTER_FACTORY,
    LITVM_MINTER_SUPPLY_RANGE,
    LITVM_MINTER_TX_PER_WALLET,
)
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.lester_minter import database as db
from modules.litvm_testnet.lester_minter import excel_export
from modules.litvm_testnet.lester_minter.worker import plan_wallet, process_wallet


def _build_menu() -> str | None:
    return select(
        "🪙 LiteForge Lester Minter (ERC-20 фабрика):",
        choices=[
            Choice("📋 План: сгенерировать токены для всех кошельков (без отправки)", "plan"),
            Choice("▶️  Запуск: задеплоить (или продолжить) токены", "run"),
            Choice("📊 Статистика БД", "stats"),
            Choice("📑 Экспорт Excel-отчёта", "export"),
            Choice("🗑️  Очистить таблицы Lester Minter", "reset"),
            Choice("ℹ️  Параметры", "info"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="🪙",
        pointer="👉",
    ).ask()


def _show_info() -> None:
    cnt_lo, cnt_hi = LITVM_MINTER_TX_PER_WALLET
    sup_lo, sup_hi = LITVM_MINTER_SUPPLY_RANGE
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Lester Minter — параметры{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
    print(f"  Фабрика                  {LITVM_MINTER_FACTORY}")
    print(f"  Комиссия (на 1 deploy)   {LITVM_MINTER_DEPLOY_FEE_WEI/1e18:.4f} zkLTC")
    print(f"  Токенов на кошелёк       {cnt_lo}..{cnt_hi} (random)")
    print(f"  Total supply диапазон    {sup_lo:,}..{sup_hi:,}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _show_stats() -> None:
    s = db.get_statistics()
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Lester Minter — статистика{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
    if s.get("wallet_total", 0) == 0:
        print(f"  {Fore.YELLOW}БД пуста{Style.RESET_ALL}")
    else:
        print(f"  {Fore.WHITE}Кошельки:{Style.RESET_ALL}")
        for k, v in s.items():
            if not k.startswith("wallet_"):
                continue
            print(f"    {k.replace('wallet_',''):<20} {v}")
        print(f"  {Fore.WHITE}Деплои:{Style.RESET_ALL}")
        print(f"    {'total':<20} {s.get('deploy_total', 0)}")
        for k, v in s.items():
            if not k.startswith("deploy_"):
                continue
            if k == "deploy_total":
                continue
            print(f"    {k.replace('deploy_',''):<20} {v}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _records_with_keys() -> list[dict]:
    rows = load_data()
    return [r for r in rows if (r.get("private_key") or "").strip()]


def _run_threaded(records: list[dict], fn, label: str, threads: int) -> bool:
    total = len(records)
    set_auto_progress(False)
    log_simple(f"🪙 Lester Minter {label}: {total} кошельков · threads={threads}",
               "info")
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
                                thread_name_prefix="litvm-minter") as ex:
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
    return (f"wallets={s.get('wallet_total', 0)} "
            f"confirmed={s.get('deploy_confirmed', 0)} "
            f"failed={s.get('deploy_failed', 0)} "
            f"pending={s.get('deploy_pending', 0)}")


def _handle_plan() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    threads = max(1, min(int(NUM_THREADS), len(records)))
    _run_threaded(records, plan_wallet, "PLAN", threads)
    log_simple(f"🏁 plan завершён · {_summary()}", "success")


def _handle_run() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    threads = max(1, min(int(NUM_THREADS), len(records)))
    ok = _run_threaded(records, process_wallet, "RUN", threads)
    log_simple(f"🏁 {'готово' if ok else 'остановлено'} · {_summary()}",
               "success" if ok else "warning")


def _handle_export() -> None:
    out = excel_export.build_report()
    log_simple(f"📑 отчёт сохранён: {out}", "success")


def run_litvm_minter() -> None:
    db.init_database()
    while True:
        action = _build_menu()
        if action is None or action == "back":
            return
        if action == "plan":
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
            _handle_export()
        elif action == "info":
            _show_info()
        elif action == "reset":
            confirm = select(
                "Очистить все Lester Minter таблицы?",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_tasks()
                log_simple("🗑️ minter_wallet_tasks + minter_deployments очищены",
                           "success")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
