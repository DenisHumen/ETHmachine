"""LiteForge bridge — меню пресета (Sepolia ⇄ LiteForge)."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.general_config import NUM_THREADS
from config.modules.cfg_litvm_testnet import (
    LITVM_BRIDGE_AMOUNT_PCT_RANGE,
    LITVM_BRIDGE_RETURN_ENABLED,
    LITVM_BRIDGE_TX_COUNT_RANGE,
)
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.bridge import database as db
from modules.litvm_testnet.bridge.worker import plan_wallet, process_wallet


def _build_menu() -> str | None:
    return select(
        "🌉 LiteForge Bridge (Sepolia ⇄ LiteForge zkLTC):",
        choices=[
            Choice("📋 План: рассчитать tx-задачи (без отправки)", "plan"),
            Choice("▶️  Запуск: выполнить (или продолжить) bridge-задачи", "run"),
            Choice("📊 Статистика БД", "stats"),
            Choice("🗑️  Очистить таблицы bridge и начать заново", "reset"),
            Choice("ℹ️  Параметры моста", "info"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="🌉",
        pointer="👉",
    ).ask()


def _show_info() -> None:
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}LiteForge Bridge — параметры (cfg_litvm_testnet){Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
    pct_lo, pct_hi = LITVM_BRIDGE_AMOUNT_PCT_RANGE
    cnt_lo, cnt_hi = LITVM_BRIDGE_TX_COUNT_RANGE
    print(f"  Количество tx на кошелёк   {cnt_lo}..{cnt_hi} (random)")
    print(f"  Сумма tx (% от баланса)    {pct_lo}..{pct_hi}% (random)")
    print(f"  Обратный мост L2→L1        {'ON' if LITVM_BRIDGE_RETURN_ENABLED else 'off'}")
    print(f"  Направление                Sepolia → LiteForge (L1→L2)")
    print(f"  Контракт inbox (Sepolia)   ERC20Inbox Arbitrum-Orbit")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _show_stats() -> None:
    stats = db.get_statistics()
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}LiteForge Bridge — статистика{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
    if not stats or stats.get("wallet_total", 0) == 0:
        print(f"  {Fore.YELLOW}БД пуста{Style.RESET_ALL}")
    else:
        print(f"  {Fore.WHITE}Кошельки:{Style.RESET_ALL}")
        for key, val in stats.items():
            if not key.startswith("wallet_"):
                continue
            label = key.replace("wallet_", "")
            print(f"    {label:<20} {val}")
        print(f"  {Fore.WHITE}Транзакции (план):{Style.RESET_ALL}")
        print(f"    {'total':<20} {stats.get('tx_total', 0)}")
        print(f"    {'done (l1+l2)':<20} {stats.get('tx_done', 0)}")
        print(f"    {'in-flight':<20} {stats.get('tx_inflight', 0)}")
        print(f"    {'failed/timeout':<20} {stats.get('tx_failed', 0)}")
        ret_keys = [k for k in stats if k.startswith("return_")]
        if ret_keys:
            print(f"  {Fore.WHITE}Return (L2→L1):{Style.RESET_ALL}")
            for k in ret_keys:
                print(f"    {k.replace('return_',''):<20} {stats[k]}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _records_with_keys() -> list[dict]:
    rows = load_data()
    return [r for r in rows if (r.get("private_key") or "").strip()]


def _run_threaded(records: list[dict], fn, label: str, threads: int) -> bool:
    """Возвращает True если завершилось без KeyboardInterrupt."""
    total = len(records)
    set_auto_progress(False)
    log_simple(f"🌉 LiteForge Bridge {label}: {total} кошельков · threads={threads}",
               "info")
    interrupted = False
    if threads <= 1 or total <= 1:
        for i, rec in enumerate(records, 1):
            try:
                fn(rec, i, total)
            except KeyboardInterrupt:
                log_simple("⚠ прервано пользователем (состояние в БД сохранено)",
                           "warning")
                interrupted = True
                break
    else:
        with ThreadPoolExecutor(max_workers=threads,
                                thread_name_prefix="litvm-bridge") as ex:
            futs = [ex.submit(fn, rec, i, total)
                    for i, rec in enumerate(records, 1)]
            try:
                for fut in as_completed(futs):
                    fut.result()
            except KeyboardInterrupt:
                for f in futs:
                    f.cancel()
                log_simple("⚠ прервано пользователем (состояние в БД сохранено)",
                           "warning")
                interrupted = True
    return not interrupted


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


def _summary() -> str:
    s = db.get_statistics()
    return (f"wallets={s.get('wallet_total',0)} "
            f"tx_done={s.get('tx_done',0)} tx_total={s.get('tx_total',0)} "
            f"failed={s.get('tx_failed',0)} inflight={s.get('tx_inflight',0)}")


def run_litvm_bridge() -> None:
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
        elif action == "info":
            _show_info()
        elif action == "reset":
            confirm = select(
                "Очистить все bridge-таблицы? (vcrcs/cookies НЕ трогаем)",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_tasks()
                log_simple("🗑️ bridge_wallet_tasks + bridge_tx_tasks очищены", "success")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
