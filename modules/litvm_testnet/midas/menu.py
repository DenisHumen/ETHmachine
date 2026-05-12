"""Midas Prediction Market — UI меню пресета."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.general_config import NUM_THREADS
from config.modules.cfg_litvm_testnet import (
    MIDAS_BET_AMOUNT_USDC,
    MIDAS_BETS_PER_WALLET,
    MIDAS_FAUCET_NATIVE_COOLDOWN_SEC,
    MIDAS_FAUCET_USDC_COOLDOWN_SEC,
    MIDAS_SITE_URL,
    MIDAS_TURNSTILE_SITEKEY,
)
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.midas import database as db
from modules.litvm_testnet.midas import excel_export
from modules.litvm_testnet.midas.worker import (
    plan_wallet, process_wallet, run_checkin_streak_loop,
)


def _build_menu() -> str | None:
    return select(
        "🎯 Midas Prediction Market:",
        choices=[
            Choice("📋 План: создать записи кошельков + nickname (без I/O)", "plan"),
            Choice("▶️  Запуск: регистрация → faucets → check-in → ставки", "run"),
            Choice("� Check-in loop (держать стрик, UTC-day)", "checkin_loop"),
            Choice("�📊 Статистика БД", "stats"),
            Choice("📑 Экспорт Excel-отчёта", "export"),
            Choice("🗑️  Очистить таблицы Midas", "reset"),
            Choice("ℹ️  Параметры", "info"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="🎯",
        pointer="👉",
    ).ask()


def _show_info() -> None:
    n_lo, n_hi = MIDAS_BETS_PER_WALLET
    a_lo, a_hi = MIDAS_BET_AMOUNT_USDC
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Midas Prediction Market — параметры{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
    print(f"  Сайт                     {MIDAS_SITE_URL}")
    print(f"  Turnstile sitekey        {MIDAS_TURNSTILE_SITEKEY}")
    print(f"  USDC faucet кулдаун      {MIDAS_FAUCET_USDC_COOLDOWN_SEC // 60}m")
    print(f"  zkLTC faucet кулдаун     {MIDAS_FAUCET_NATIVE_COOLDOWN_SEC // 3600}h")
    print(f"  Ставок на кошелёк        {n_lo}..{n_hi} (random)")
    print(f"  Размер ставки            {a_lo}..{a_hi} USDC (random)")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _show_stats() -> None:
    s = db.get_statistics()
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Midas — статистика{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
    if s.get("wallet_total", 0) == 0:
        print(f"  {Fore.YELLOW}БД пуста{Style.RESET_ALL}")
    else:
        print(f"  {Fore.WHITE}Кошельки:{Style.RESET_ALL}")
        print(f"    {'total':<22} {s.get('wallet_total', 0)}")
        print(f"    {'registered':<22} {s.get('wallet_registered', 0)}")
        for k, v in s.items():
            if not k.startswith("wallet_") or k in ("wallet_total",
                                                     "wallet_registered"):
                continue
            print(f"    {k.replace('wallet_',''):<22} {v}")
        print(f"  {Fore.WHITE}Ставки:{Style.RESET_ALL}")
        print(f"    {'total':<22} {s.get('bet_total', 0)}")
        for k, v in s.items():
            if not k.startswith("bet_") or k == "bet_total":
                continue
            print(f"    {k.replace('bet_',''):<22} {v}")
        print(f"  {Fore.WHITE}Faucets:{Style.RESET_ALL}")
        print(f"    {'requests':<22} {s.get('faucet_total', 0)}")
        print(f"    {'success':<22} {s.get('faucet_success', 0)}")
        print(f"  {Fore.WHITE}Check-ins:{Style.RESET_ALL}")
        print(f"    {'requests':<22} {s.get('checkin_total', 0)}")
        print(f"    {'success':<22} {s.get('checkin_success', 0)}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _records_with_keys() -> list[dict]:
    return [r for r in load_data() if (r.get("private_key") or "").strip()]


def _run_threaded(records: list[dict], fn, label: str, threads: int) -> bool:
    total = len(records)
    set_auto_progress(False)
    log_simple(
        f"🎯 Midas {label}: {total} кошельков · threads={threads}", "info")
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
                                thread_name_prefix="litvm-midas") as ex:
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
            f"registered={s.get('wallet_registered', 0)} "
            f"bets_ok={s.get('bet_confirmed', 0)} "
            f"bets_failed={s.get('bet_failed', 0)}")


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


def _handle_checkin_loop() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    threads = max(1, min(int(NUM_THREADS), len(records)))
    set_auto_progress(False)
    log_simple(
        "ℹ Check-in loop работает бесконечно. "
        "Нажмите Ctrl+C чтобы остановить (состояние в БД).",
        "info",
    )
    stop_flag = {"v": False}
    try:
        run_checkin_streak_loop(
            records, threads, should_stop=lambda: stop_flag["v"],
        )
    except KeyboardInterrupt:
        stop_flag["v"] = True
        log_simple("⚠ check-in loop прерван пользователем", "warning")


def run_litvm_midas() -> None:
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
        elif action == "checkin_loop":
            try:
                _handle_checkin_loop()
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
                "Очистить все Midas-таблицы?",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_tasks()
                log_simple("🗑️ midas_* таблицы очищены", "success")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
