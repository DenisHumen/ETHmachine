"""Меню modules.litvm_testnet.onmi.liquidity — ликвидность на AMM Onmi."""
from __future__ import annotations

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
from modules.litvm_testnet.onmi.liquidity import database as db
from modules.litvm_testnet.onmi.liquidity import excel_export
from modules.litvm_testnet.onmi.liquidity.worker import (
    run_add_liquidity_session,
    run_withdraw_all,
)
from modules.simple_logger import log_simple, set_auto_progress
from modules.ui import ui
from modules.ui.module_menu import MenuAction, ModuleMenu

# Длинный список позиций в терминале всё равно не читается — показываем начало.
_POSITIONS_SHOWN = 40


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
    if not ui.confirm(
        "Снять всю ликвидность со всех кошельков по всем известным парам?",
        default=False,
    ):
        return
    set_auto_progress(False)
    try:
        run_withdraw_all(records)
    except KeyboardInterrupt:
        log_simple("⚠ прервано", "warning")


def _handle_positions() -> None:
    positions = db.list_positions(with_lp_only=True)
    if not positions:
        ui.print_lines(ui.panel("Открытые позиции",
                                ["Кошельков с ненулевым LP сейчас нет."]))
        return
    shown = positions[:_POSITIONS_SHOWN]
    symbol_width = max(len(p.get("token_symbol") or "?") for p in shown)
    lines = [
        f"{p['wallet_address']}  "
        f"{ui.pad(p.get('token_symbol') or '?', symbol_width)}  "
        f"LP {(p.get('lp_net_wei') or 0) / 1e18:.6f}"
        for p in shown
    ]
    footer = (f"показаны первые {_POSITIONS_SHOWN} из {len(positions)}"
              if len(positions) > _POSITIONS_SHOWN else None)
    ui.print_lines(ui.panel("Открытые позиции", lines, footer=footer))


def _handle_export() -> None:
    try:
        out = excel_export.build_report()
    except Exception as exc:  # noqa: BLE001 — отчёт не должен ронять меню
        log_simple(f"⚠ export failed: {exc}", "warning")
        return
    log_simple(f"📑 LP-отчёт сохранён: {out}", "success")


def _stats() -> dict:
    raw = db.get_statistics()
    return {
        "позиций всего": raw.get("positions_total", 0),
        "из них с LP": len(db.list_positions(with_lp_only=True)),
        "операций всего": raw.get("history_total", 0),
        "зачислено": raw.get("status_arrived", 0),
        "ошибка": raw.get("status_failed", 0),
        "отправлено": raw.get("status_sent", 0),
        "ожидают": raw.get("status_pending", 0),
        "успешных добавлений": raw.get("side_add", 0),
        "успешных выводов": raw.get("side_remove", 0),
    }


def _info() -> dict:
    add_lo, add_hi = ONMI_LIQ_ADD_VALUE_RANGE
    ops_lo, ops_hi = ONMI_LIQ_ADD_OPS_RANGE
    sleep_lo, sleep_hi = ONMI_LIQ_SLEEP_BETWEEN_OPS
    return {
        "Как добавляется ликвидность": [
            "1. берётся случайный бюджет из диапазона ниже;",
            "2. на половину бюджета покупается токен через роутер;",
            "3. вторая половина и купленные токены уходят в "
            "addLiquidityETH().",
        ],
        "Как выводится ликвидность": [
            "Для каждого кошелька обходятся все известные пары и проверяется "
            "pair.balanceOf(). Если баланс больше нуля — вызывается "
            "removeLiquidityETH() с amountMin=0.",
            "Поэтому вывод подхватывает и ту ликвидность, которая была "
            "добавлена вручную, мимо скрипта.",
        ],
        "Параметры": [
            f"Сайт — {ONMI_SITE_LIQUIDITY}",
            f"Router — {ONMI_SWAP_ROUTER}",
            f"Factory — {ONMI_SWAP_FACTORY}",
            f"WETH (WzkLTC) — {ONMI_SWAP_WETH}",
            f"Минимальный баланс — {ONMI_LIQ_MIN_NATIVE_BALANCE} zkLTC",
            f"Бюджет на добавление — {add_lo} – {add_hi} zkLTC",
            f"Проскальзывание — {ONMI_LIQ_SLIPPAGE * 100:.0f}%",
            f"Операций за сессию — {ops_lo} – {ops_hi}",
            f"Пауза между операциями — {sleep_lo} – {sleep_hi} сек",
        ],
        "Где что лежит": [
            "База: db/litvm.db, таблицы onmi_lp_positions и onmi_lp_history",
            "Очистка базы стирает историю операций, позиции остаются",
            "Отчёт: result/onmi_liquidity/run_<время>/",
        ],
    }


def _menu() -> ModuleMenu:
    return ModuleMenu(
        title="Onmi Liquidity",
        subtitle="добавление и вывод ликвидности",
        icon="💧",
        actions=[
            MenuAction("add", "Добавить ликвидность", _handle_add,
                       "случайные пары и суммы в пределах бюджета", icon="➕"),
            MenuAction("withdraw", "Вывести всю ликвидность",
                       _handle_withdraw_all,
                       "снять LP со всех кошельков по всем парам", icon="🧹"),
            MenuAction("positions", "Открытые позиции", _handle_positions,
                       "кошельки, у которых сейчас есть LP", icon="📃"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title="Прогресс · onmi_lp_history",
        reset=db.reset_history,
        info=_info,
    )


def run_litvm_onmi_liquidity() -> None:
    db.init_database()
    _menu().run()


__all__ = ["run_litvm_onmi_liquidity"]
