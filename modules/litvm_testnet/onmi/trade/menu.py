"""Меню modules.litvm_testnet.onmi.trade — торговля на bonding curve."""
from __future__ import annotations

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
from modules.litvm_testnet.onmi.trade import database as db
from modules.litvm_testnet.onmi.trade import excel_export
from modules.litvm_testnet.onmi.trade.worker import run_random_session
from modules.simple_logger import log_simple, set_auto_progress
from modules.ui.module_menu import MenuAction, ModuleMenu


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
    try:
        out = excel_export.build_report()
    except Exception as exc:  # noqa: BLE001 — отчёт не должен ронять меню
        log_simple(f"⚠ export failed: {exc}", "warning")
        return
    log_simple(f"📑 trade-отчёт сохранён: {out}", "success")


def _stats() -> dict:
    raw = db.get_statistics()
    return {
        "токенов известно": raw.get("known_tokens", 0),
        "из них graduated": raw.get("graduated", 0),
        "сделок всего": raw.get("trades_total", 0),
        "зачислено": raw.get("status_arrived", 0),
        "ошибка": raw.get("status_failed", 0),
        "отправлено": raw.get("status_sent", 0),
        "ожидают": raw.get("status_pending", 0),
        "успешных покупок": raw.get("side_buy", 0),
        "успешных продаж": raw.get("side_sell", 0),
    }


def _info() -> dict:
    buy_lo, buy_hi = ONMI_TRADE_BUY_VALUE_RANGE_ZKLTC
    sell_lo, sell_hi = ONMI_TRADE_SELL_PCT_RANGE
    ops_lo, ops_hi = ONMI_TRADE_TOTAL_OPS_RANGE
    sleep_lo, sleep_hi = ONMI_TRADE_SLEEP_BETWEEN_OPS
    return {
        "Как это работает": [
            "Случайные покупки и продажи на bonding curve onmi.fun. Кошельки "
            "торгуют друг у друга монеты, созданные модулем Onmi или "
            "добавленные вручную в onmi_known_tokens.",
            "Цель — органическая активность, поэтому сессия идёт случайным "
            "блужданием: случайный кошелёк, случайный токен, покупка или "
            "продажа, случайный объём и случайная пауза.",
            "Очистка базы стирает историю сделок; список известных токенов "
            "остаётся.",
        ],
        "Параметры": [
            f"Router — {ONMI_TRADE_ROUTER}",
            f"Минимальный баланс — {ONMI_TRADE_MIN_NATIVE_BALANCE_ZKLTC} zkLTC",
            f"Сумма покупки — {buy_lo} – {buy_hi} zkLTC",
            f"Доля продажи — {sell_lo} – {sell_hi} %",
            f"Вероятность продажи, если токен есть — "
            f"{ONMI_TRADE_PROB_SELL_IF_HAS * 100:.0f}%",
            f"Операций за сессию — {ops_lo} – {ops_hi}",
            f"Пауза между операциями — {sleep_lo} – {sleep_hi} сек",
        ],
        "Ссылки": [
            f"Board, торговля — {ONMI_SITE_BOARD}",
            f"Свапы graduated-токенов — {ONMI_SITE_SWAP}",
        ],
        "Где что лежит": [
            "База: db/litvm.db, таблицы onmi_known_tokens и onmi_trade_history",
            "Отчёт: result/onmi_trade/run_<время>/",
        ],
    }


def _menu() -> ModuleMenu:
    return ModuleMenu(
        title="Onmi Trade",
        subtitle="покупки и продажи на bonding curve",
        icon="🎲",
        actions=[
            MenuAction("run", "Запуск сессии", _handle_run,
                       "случайные сделки по известным токенам", icon="🤖"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title="Прогресс · onmi_trade_history",
        reset=db.reset_trade_history,
        info=_info,
    )


def run_litvm_onmi_trade() -> None:
    db.init_database()
    _menu().run()


__all__ = ["run_litvm_onmi_trade"]
