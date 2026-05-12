"""Onmi Trade · CLI submenu."""
from __future__ import annotations

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.cfg_litvm_testnet import (
    ONMI_SITE_BOARD,
    ONMI_SITE_SWAP,
    ONMI_TRADE_BUY_VALUE_RANGE_ZKLTC,
    ONMI_TRADE_MIN_NATIVE_BALANCE_ZKLTC,
    ONMI_TRADE_PROB_SELL_IF_HAS,
    ONMI_TRADE_ROUTER,
    ONMI_TRADE_SELL_PCT_RANGE,
    ONMI_TRADE_SLEEP_BETWEEN_OPS,
    ONMI_TRADE_TOTAL_OPS_RANGE,
)
from config.modules.general_config import SHUFLE_ACCOUNTS
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.onmi.trade import database as db
from modules.litvm_testnet.onmi.trade import excel_export
from modules.litvm_testnet.onmi.trade.worker import run_random_session


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
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    set_auto_progress(False)
    try:
        run_random_session(records)
    except KeyboardInterrupt:
        log_simple("⚠ session прервана", "warning")


def _handle_export() -> None:
    out = excel_export.build_report()
    log_simple(f"📑 trade-отчёт сохранён: {out}", "success")


def _show_stats() -> None:
    s = db.get_statistics()
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Onmi Trade · статистика{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"  {'known tokens':<26} {s.get('known_tokens', 0)}")
    print(f"  {'  · graduated':<26} {s.get('graduated', 0)}")
    print(f"  {'trades total':<26} {s.get('trades_total', 0)}")
    for k in ("arrived", "failed", "sent", "pending"):
        print(f"  {('  · ' + k):<26} {s.get(f'status_{k}', 0)}")
    print(f"  {'successful buys':<26} {s.get('side_buy', 0)}")
    print(f"  {'successful sells':<26} {s.get('side_sell', 0)}")
    print()


def _show_info() -> None:
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Onmi.fun · Trade module{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(
        "  Случайные buy/sell-операции на bonding curve onmi.fun. Кошельки\n"
        "  торгуют друг у друга токены, созданные модулем Onmi (или вручную\n"
        "  добавленные в onmi_known_tokens). Цель — органическая активность.\n"
        "  Random walk: случайный кошелёк × случайный токен × buy/sell ×\n"
        "  случайный объём × случайная пауза.\n"
    )
    print(f"  {'Router':<26} {ONMI_TRADE_ROUTER}")
    print(f"  {'Min native':<26} {ONMI_TRADE_MIN_NATIVE_BALANCE_ZKLTC} zkLTC")
    print(f"  {'Buy range':<26} "
          f"{ONMI_TRADE_BUY_VALUE_RANGE_ZKLTC[0]}–"
          f"{ONMI_TRADE_BUY_VALUE_RANGE_ZKLTC[1]} zkLTC")
    print(f"  {'Sell pct range':<26} "
          f"{ONMI_TRADE_SELL_PCT_RANGE[0]}–{ONMI_TRADE_SELL_PCT_RANGE[1]} %")
    print(f"  {'P(sell|has)':<26} {ONMI_TRADE_PROB_SELL_IF_HAS*100:.0f}%")
    print(f"  {'Total ops range':<26} "
          f"{ONMI_TRADE_TOTAL_OPS_RANGE[0]}–{ONMI_TRADE_TOTAL_OPS_RANGE[1]}")
    print(f"  {'Sleep between ops':<26} "
          f"{ONMI_TRADE_SLEEP_BETWEEN_OPS[0]}–"
          f"{ONMI_TRADE_SLEEP_BETWEEN_OPS[1]} sec")
    print()
    print(f"  {Fore.YELLOW}Ссылки:{Style.RESET_ALL}")
    print(f"  {'  • board (торговля)':<26} {ONMI_SITE_BOARD}")
    print(f"  {'  • swap (graduated)':<26} {ONMI_SITE_SWAP}")
    print()


def _build_menu() -> str | None:
    return select(
        "🎲 Onmi Trade · выберите действие:",
        choices=[
            Choice("🤖 Запустить random-walk сессию", "run"),
            Choice("📊 Статистика БД", "stats"),
            Choice("📑 Экспорт Excel-отчёта", "export"),
            Choice("🗑️  Очистить trade-history (known tokens НЕ удаляются)",
                   "reset"),
            Choice("📖 Информация о модуле", "info"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="🎲", pointer="👉",
    ).ask()


def run_litvm_onmi_trade() -> None:
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
                "Очистить onmi_trade_history? (known tokens сохраняются)",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_trade_history()
                log_simple("🗑️ onmi_trade_history очищена "
                           "(known tokens сохранены)", "success")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
