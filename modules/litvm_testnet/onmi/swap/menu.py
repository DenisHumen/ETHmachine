"""Onmi Swap · CLI submenu."""
from __future__ import annotations

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.cfg_litvm_testnet import (
    ONMI_SITE_SWAP,
    ONMI_SWAP_FACTORY,
    ONMI_SWAP_MIN_NATIVE_BALANCE,
    ONMI_SWAP_NATIVE_VALUE_RANGE,
    ONMI_SWAP_PROB_SELL_IF_HAS,
    ONMI_SWAP_ROUTER,
    ONMI_SWAP_SELL_PCT_RANGE,
    ONMI_SWAP_SLEEP_BETWEEN_OPS,
    ONMI_SWAP_SLIPPAGE,
    ONMI_SWAP_TOTAL_OPS_RANGE,
    ONMI_SWAP_WETH,
)
from config.modules.general_config import SHUFLE_ACCOUNTS
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.onmi.swap import database as db
from modules.litvm_testnet.onmi.swap import excel_export
from modules.litvm_testnet.onmi.swap.worker import (
    refresh_pairs_cache,
    run_random_session,
)


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


def _handle_refresh() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков (нужен хотя бы 1 для proxy)", "warning")
    refresh_pairs_cache(records=records)


def _handle_export() -> None:
    out = excel_export.build_report()
    log_simple(f"📑 swap-отчёт сохранён: {out}", "success")


def _show_stats() -> None:
    s = db.get_statistics()
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Onmi Swap · статистика{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"  {'known pairs':<26} {s.get('pairs_total', 0)}")
    print(f"  {'  · enabled':<26} {s.get('pairs_enabled', 0)}")
    print(f"  {'swaps total':<26} {s.get('swaps_total', 0)}")
    for k in ("arrived", "failed", "sent", "pending"):
        print(f"  {('  · ' + k):<26} {s.get(f'status_{k}', 0)}")
    print(f"  {'successful buys':<26} {s.get('side_buy', 0)}")
    print(f"  {'successful sells':<26} {s.get('side_sell', 0)}")
    print()


def _show_info() -> None:
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Onmi.fun · Swap module (UniswapV2-style){Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(
        "  Свапы graduated-токенов на AMM-роутере Onmi. После того как\n"
        "  токен закончил bonding curve, ликвидность переезжает в pair,\n"
        "  и торговля идёт через UniswapV2-style swap. Random-walk\n"
        "  сессия: случайный кошелёк × случайная пара × buy/sell ×\n"
        "  случайный объём × случайная пауза.\n"
    )
    print(f"  {'Сайт':<26} {ONMI_SITE_SWAP}")
    print(f"  {'Router':<26} {ONMI_SWAP_ROUTER}")
    print(f"  {'Factory':<26} {ONMI_SWAP_FACTORY}")
    print(f"  {'WETH (WzkLTC)':<26} {ONMI_SWAP_WETH}")
    print(f"  {'Min native':<26} {ONMI_SWAP_MIN_NATIVE_BALANCE} zkLTC")
    print(f"  {'Buy range':<26} "
          f"{ONMI_SWAP_NATIVE_VALUE_RANGE[0]}–"
          f"{ONMI_SWAP_NATIVE_VALUE_RANGE[1]} zkLTC")
    print(f"  {'Sell pct range':<26} "
          f"{ONMI_SWAP_SELL_PCT_RANGE[0]}–{ONMI_SWAP_SELL_PCT_RANGE[1]} %")
    print(f"  {'Slippage':<26} {ONMI_SWAP_SLIPPAGE*100:.1f}%")
    print(f"  {'P(sell|has)':<26} {ONMI_SWAP_PROB_SELL_IF_HAS*100:.0f}%")
    print(f"  {'Total ops range':<26} "
          f"{ONMI_SWAP_TOTAL_OPS_RANGE[0]}–{ONMI_SWAP_TOTAL_OPS_RANGE[1]}")
    print(f"  {'Sleep between ops':<26} "
          f"{ONMI_SWAP_SLEEP_BETWEEN_OPS[0]}–"
          f"{ONMI_SWAP_SLEEP_BETWEEN_OPS[1]} sec")
    print()


def _build_menu() -> str | None:
    return select(
        "💱 Onmi Swap · выберите действие:",
        choices=[
            Choice("🤖 Запустить random-walk swap-сессию", "run"),
            Choice("🔎 Обновить список пар (factory scan)", "refresh"),
            Choice("📊 Статистика БД", "stats"),
            Choice("📑 Экспорт Excel-отчёта", "export"),
            Choice("🗑️  Очистить swap-history (pairs сохраняются)", "reset"),
            Choice("📖 Информация о модуле", "info"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="💱", pointer="👉",
    ).ask()


def run_litvm_onmi_swap() -> None:
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
        elif action == "refresh":
            _handle_refresh()
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
                "Очистить onmi_swap_history? (known pairs сохраняются)",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_history()
                log_simple("🗑️ onmi_swap_history очищена", "success")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
