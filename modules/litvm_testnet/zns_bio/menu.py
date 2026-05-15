"""ZNS.bio · CLI submenu."""
from __future__ import annotations

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.cfg_litvm_testnet import (
    ZNS_MIN_NATIVE_BALANCE,
    ZNS_NAME_LENGTH_RANGE,
    ZNS_OPS_PER_WALLET_RANGE,
    ZNS_REGISTRY,
    ZNS_SITE_CART,
    ZNS_SITE_DOCS,
    ZNS_SITE_HOME,
    ZNS_SITE_SEARCH,
    ZNS_SLEEP_BETWEEN_OPS,
    ZNS_TLD,
    ZNS_YEARS_WEIGHTS,
)
from config.modules.general_config import SHUFLE_ACCOUNTS
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.zns_bio import database as db
from modules.litvm_testnet.zns_bio import excel_export
from modules.litvm_testnet.zns_bio.worker import run_random_session


def _records_with_keys() -> list[dict]:
    rows = load_data()
    records = [r for r in rows if (r.get("private_key") or "").strip()]
    if SHUFLE_ACCOUNTS:
        import random as _r
        _r.shuffle(records)
    return records


def _handle_run() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key", "error")
        return
    set_auto_progress(False)
    try:
        run_random_session(records)
    except KeyboardInterrupt:
        log_simple("⚠ session прервана", "warning")


def _handle_export() -> None:
    out = excel_export.build_report()
    log_simple(f"📑 ZNS-отчёт сохранён: {out}", "success")


def _show_stats() -> None:
    s = db.get_statistics()
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  ZNS.bio · статистика{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"  {'total registrations':<26} {s.get('total', 0)}")
    for k in ("arrived", "failed", "sent", "pending", "skipped"):
        print(f"  {('  · ' + k):<26} {s.get(f'status_{k}', 0)}")
    print(f"  {'unique wallets done':<26} {s.get('unique_wallets_done', 0)}")
    paid = float(s.get('total_paid_wei', 0)) / 1e18
    print(f"  {'paid total':<26} {paid:.6f} zkLTC")
    print()


def _show_info() -> None:
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  ZNS.bio · регистрация .{ZNS_TLD} доменов "
          f"(LiteForge){Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(
        "  Каждый кошелёк регистрирует случайный никнейм в TLD .lit на ZNS\n"
        "  Connect. Срок аренды выбирается weighted-random:\n"
    )
    for y, w in sorted(ZNS_YEARS_WEIGHTS.items()):
        total = sum(ZNS_YEARS_WEIGHTS.values()) or 1
        print(f"    · {y}y — {w*100/total:.1f}%")
    print()
    print(f"  {'Home':<26} {ZNS_SITE_HOME}")
    print(f"  {'Search':<26} {ZNS_SITE_SEARCH}")
    print(f"  {'Cart':<26} {ZNS_SITE_CART}")
    print(f"  {'Docs':<26} {ZNS_SITE_DOCS}")
    print(f"  {'Registry':<26} {ZNS_REGISTRY}")
    print(f"  {'TLD':<26} .{ZNS_TLD}")
    print(f"  {'Name length':<26} "
          f"{ZNS_NAME_LENGTH_RANGE[0]}–{ZNS_NAME_LENGTH_RANGE[1]} chars")
    print(f"  {'Min native':<26} {ZNS_MIN_NATIVE_BALANCE} zkLTC")
    print(f"  {'Ops per wallet':<26} "
          f"{ZNS_OPS_PER_WALLET_RANGE[0]}–{ZNS_OPS_PER_WALLET_RANGE[1]}")
    print(f"  {'Sleep between ops':<26} "
          f"{ZNS_SLEEP_BETWEEN_OPS[0]}–{ZNS_SLEEP_BETWEEN_OPS[1]} sec")
    print()


def _build_menu() -> str | None:
    return select(
        "🪪 ZNS.bio · выберите действие:",
        choices=[
            Choice("🤖 Запустить регистрацию (по всем кошелькам)", "run"),
            Choice("📊 Статистика БД", "stats"),
            Choice("📑 Экспорт Excel-отчёта", "export"),
            Choice("🗑️  Очистить zns_registrations", "reset"),
            Choice("📖 Информация о модуле", "info"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="🪪", pointer="👉",
    ).ask()


def run_litvm_zns_bio() -> None:
    db.init_database()
    while True:
        action = _build_menu()
        if action is None or action == "back":
            return
        if action == "run":
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
                "Очистить zns_registrations?",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_registrations()
                log_simple("🗑️ zns_registrations очищена", "success")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
