"""Alchemy Base Sepolia faucet — меню модуля."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from colorama import Fore, Style
from questionary import select, Choice

from config.modules.general_config import NUM_THREADS
from modules.captcha.manager import (
    SERVICE_CONFIG_FIELDS,
    configured_services_for_type,
    services_for_captcha_type,
)
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.fhenix.alchemy_faucet import database as db
from modules.fhenix.alchemy_faucet.worker import process_wallet


def _check_captcha_ready(captcha_type: str = "turnstile") -> bool:
    """True если хотя бы один сервис с поддержкой captcha_type настроен."""
    if configured_services_for_type(captcha_type):
        return True
    supported = services_for_captcha_type(captcha_type)
    log_simple(
        f"❌ Нет API-ключа ни для одного сервиса, поддерживающего '{captcha_type}'.",
        "error",
    )
    if supported:
        log_simple(
            f"   Поддерживают '{captcha_type}': {', '.join(supported)}",
            "info",
        )
        fields = ", ".join(f"{s} → {SERVICE_CONFIG_FIELDS[s]}" for s in supported)
        log_simple(
            f"   Заполните любой ключ в config/modules/general_config.py: {fields}",
            "info",
        )
    return False


def _build_menu() -> str | None:
    return select(
        "🚰 Alchemy Faucet (Base Sepolia):",
        choices=[
            Choice("▶️  Продолжить", "continue"),
            Choice("🗑️  Очистить статусы и начать заново", "reset"),
            Choice("📊 Статистика БД", "stats"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="🚰",
        pointer="👉",
    ).ask()


def _show_stats() -> None:
    stats = db.get_statistics()
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Alchemy Faucet (Base Sepolia) — статистика{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
    if not stats or stats.get("total", 0) == 0:
        print(f"  {Fore.YELLOW}БД пуста{Style.RESET_ALL}")
    else:
        for key, val in stats.items():
            if key == "total":
                continue
            print(f"  {key:<22} {val}")
        print(f"  {Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
        print(f"  {'total':<22} {stats.get('total', 0)}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _format_summary(stats: dict) -> str:
    parts = []
    for key in ("arrived", "requested", "cooldown", "ineligible", "failed",
                "in_progress", "pending"):
        val = int(stats.get(key, 0) or 0)
        if val:
            parts.append(f"{key}={val}")
    parts.append(f"total={int(stats.get('total', 0) or 0)}")
    return " · ".join(parts)


def _run_continue() -> None:
    if not _check_captcha_ready("turnstile"):
        return

    rows = load_data()
    if not rows:
        log_simple("Нет данных в data/data.csv", "error")
        return

    records = [r for r in rows if (r.get("private_key") or "").strip()]
    total = len(records)
    if total == 0:
        log_simple("Нет кошельков с private_key", "error")
        return

    set_auto_progress(False)
    log_simple(f"🚰 Alchemy Faucet (Base Sepolia): старт для {total} кошельков "
               f"(threads={max(1, min(int(NUM_THREADS), total))})", "info")

    interrupted = False
    threads = max(1, min(int(NUM_THREADS), total))
    if threads <= 1 or total <= 1:
        for i, rec in enumerate(records, 1):
            try:
                process_wallet(rec, i, total)
            except KeyboardInterrupt:
                log_simple("⚠ прервано пользователем (состояние сохранено в БД)", "warning")
                interrupted = True
                break
    else:
        with ThreadPoolExecutor(max_workers=threads, thread_name_prefix="fhenix-alchemy") as ex:
            futs = [ex.submit(process_wallet, rec, i, total)
                    for i, rec in enumerate(records, 1)]
            try:
                for fut in as_completed(futs):
                    fut.result()
            except KeyboardInterrupt:
                for f in futs:
                    f.cancel()
                log_simple("⚠ прервано пользователем (состояние сохранено в БД)", "warning")
                interrupted = True

    stats = db.get_statistics()
    summary = _format_summary(stats)
    if interrupted:
        log_simple(f"🏁 остановлено · {summary}", "warning")
    else:
        log_simple(f"🏁 готово · {summary}", "success")


def run_alchemy_faucet() -> None:
    db.init_database()

    while True:
        action = _build_menu()
        if action is None or action == "back":
            return
        if action == "continue":
            try:
                _run_continue()
            except KeyboardInterrupt:
                pass
        elif action == "reset":
            confirm = select(
                "Очистить статусы задач? (история запросов и кулдауны сохранятся)",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_tasks()
                log_simple("🗑️ статусы очищены, история кулдаунов сохранена", "success")
        elif action == "stats":
            _show_stats()
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
