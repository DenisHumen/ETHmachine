"""Onmi Liquidity · CLI submenu."""
from __future__ import annotations

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.cfg_litvm_testnet import (
    ONMI_LIQ_ADD_OPS_RANGE,
    ONMI_LIQ_ADD_VALUE_RANGE,
    ONMI_LIQ_MIN_NATIVE_BALANCE,
    ONMI_LIQ_SLEEP_BETWEEN_OPS,
    ONMI_LIQ_SLIPPAGE,
    ONMI_SITE_LIQUIDITY,
    ONMI_SWAP_FACTORY,
    ONMI_SWAP_ROUTER,
    ONMI_SWAP_WETH,
)
from config.modules.general_config import SHUFLE_ACCOUNTS
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.litvm_testnet.onmi.liquidity import database as db
from modules.litvm_testnet.onmi.liquidity import excel_export
from modules.litvm_testnet.onmi.liquidity.worker import (
    run_add_liquidity_session,
    run_withdraw_all,
)


def _records_with_keys() -> list[dict]:
    rows = load_data()
    records = [r for r in rows if (r.get("private_key") or "").strip()]
    if SHUFLE_ACCOUNTS:
        import random as _r
        _r.shuffle(records)
    return records


def _handle_add() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key", "error")
        return
    set_auto_progress(False)
    try:
        run_add_liquidity_session(records)
    except KeyboardInterrupt:
        log_simple("⚠ session прервана", "warning")


def _handle_withdraw_all() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key", "error")
        return
    confirm = select(
        "⚠ Это снимет ВСЮ ликвидность со ВСЕХ кошельков (все известные pairs). Продолжить?",
        choices=[Choice("Нет", False), Choice("Да, вывести всё", True)],
        qmark="🧹",
    ).ask()
    if not confirm:
        return
    set_auto_progress(False)
    try:
        run_withdraw_all(records)
    except KeyboardInterrupt:
        log_simple("⚠ прервано", "warning")


def _handle_export() -> None:
    out = excel_export.build_report()
    log_simple(f"📑 LP-отчёт сохранён: {out}", "success")


def _show_stats() -> None:
    s = db.get_statistics()
    positions = db.list_positions(with_lp_only=True)
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Onmi Liquidity · статистика{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"  {'positions (всего)':<26} {s.get('positions_total', 0)}")
    print(f"  {'positions (с LP>0)':<26} {len(positions)}")
    print(f"  {'history total':<26} {s.get('history_total', 0)}")
    for k in ("arrived", "failed", "sent", "pending"):
        print(f"  {('  · ' + k):<26} {s.get(f'status_{k}', 0)}")
    print(f"  {'successful adds':<26} {s.get('side_add', 0)}")
    print(f"  {'successful removes':<26} {s.get('side_remove', 0)}")
    if positions:
        print(f"\n  {Fore.YELLOW}Открытые позиции:{Style.RESET_ALL}")
        for p in positions[:40]:
            w = p["wallet_address"]
            sym = p.get("token_symbol") or "?"
            net = (p.get("lp_net_wei", 0)) / 1e18
            print(f"    {w}  {sym:<10}  LP={net:.6f}")
    print()


def _show_info() -> None:
    print(f"\n{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(f"{Fore.CYAN}  Onmi.fun · Liquidity module{Style.RESET_ALL}")
    print(f"{Fore.CYAN}" + "=" * 60 + Style.RESET_ALL)
    print(
        "  Добавление и вывод ликвидности на UniswapV2-style роутере Onmi.\n"
        "  Логика ADD:\n"
        "    1. budget N = random(ADD_VALUE_RANGE);\n"
        "    2. на N/2 покупаем токен (swap router);\n"
        "    3. на оставшиеся N/2 + куплённые токены делаем addLiquidityETH.\n"
        "  Логика WITHDRAW-ALL:\n"
        "    для каждого кошелька — обход всех известных pairs, проверка\n"
        "    pair.balanceOf(wallet); если > 0 → removeLiquidityETH с\n"
        "    amountMin=0. Подхватывает LP, добавленный вне скрипта.\n"
    )
    print(f"  {'Сайт':<26} {ONMI_SITE_LIQUIDITY}")
    print(f"  {'Router':<26} {ONMI_SWAP_ROUTER}")
    print(f"  {'Factory':<26} {ONMI_SWAP_FACTORY}")
    print(f"  {'WETH (WzkLTC)':<26} {ONMI_SWAP_WETH}")
    print(f"  {'Min native':<26} {ONMI_LIQ_MIN_NATIVE_BALANCE} zkLTC")
    print(f"  {'Add budget range':<26} "
          f"{ONMI_LIQ_ADD_VALUE_RANGE[0]}–"
          f"{ONMI_LIQ_ADD_VALUE_RANGE[1]} zkLTC")
    print(f"  {'Slippage':<26} {ONMI_LIQ_SLIPPAGE*100:.0f}%")
    print(f"  {'Add ops range':<26} "
          f"{ONMI_LIQ_ADD_OPS_RANGE[0]}–{ONMI_LIQ_ADD_OPS_RANGE[1]}")
    print(f"  {'Sleep between ops':<26} "
          f"{ONMI_LIQ_SLEEP_BETWEEN_OPS[0]}–"
          f"{ONMI_LIQ_SLEEP_BETWEEN_OPS[1]} sec")
    print()


def _build_menu() -> str | None:
    return select(
        "💧 Onmi Liquidity · выберите действие:",
        choices=[
            Choice("➕ Добавить ликвидность (random sess.)", "add"),
            Choice("🧹 ВЫВЕСТИ ВСЮ ЛИКВИДНОСТЬ (одной кнопкой)", "withdraw"),
            Choice("📊 Статистика / открытые позиции", "stats"),
            Choice("📑 Экспорт Excel-отчёта", "export"),
            Choice("🗑️  Очистить history (positions сохраняются)", "reset"),
            Choice("📖 Информация о модуле", "info"),
            Choice("🔙 Назад", "back"),
        ],
        qmark="💧", pointer="👉",
    ).ask()


def run_litvm_onmi_liquidity() -> None:
    db.init_database()
    while True:
        action = _build_menu()
        if action is None or action == "back":
            return
        if action == "add":
            try:
                _handle_add()
            except KeyboardInterrupt:
                pass
        elif action == "withdraw":
            try:
                _handle_withdraw_all()
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
                "Очистить onmi_lp_history? (positions сохраняются)",
                choices=[Choice("Нет", False), Choice("Да, очистить", True)],
                qmark="🗑️",
            ).ask()
            if confirm:
                db.reset_history()
                log_simple("🗑️ onmi_lp_history очищена", "success")
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
