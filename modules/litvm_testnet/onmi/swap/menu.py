"""Меню modules.litvm_testnet.onmi.swap — свапы graduated-токенов."""
from __future__ import annotations

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
from modules.litvm_testnet.onmi.swap import database as db
from modules.litvm_testnet.onmi.swap import excel_export
from modules.litvm_testnet.onmi.swap.worker import (
    refresh_pairs_cache,
    run_random_session,
)
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
    try:
        out = excel_export.build_report()
    except Exception as exc:  # noqa: BLE001 — отчёт не должен ронять меню
        log_simple(f"⚠ export failed: {exc}", "warning")
        return
    log_simple(f"📑 swap-отчёт сохранён: {out}", "success")


def _stats() -> dict:
    raw = db.get_statistics()
    return {
        "пар известно": raw.get("pairs_total", 0),
        "из них активных": raw.get("pairs_enabled", 0),
        "свапов всего": raw.get("swaps_total", 0),
        "зачислено": raw.get("status_arrived", 0),
        "ошибка": raw.get("status_failed", 0),
        "отправлено": raw.get("status_sent", 0),
        "ожидают": raw.get("status_pending", 0),
        "успешных покупок": raw.get("side_buy", 0),
        "успешных продаж": raw.get("side_sell", 0),
    }


def _info() -> dict:
    buy_lo, buy_hi = ONMI_SWAP_NATIVE_VALUE_RANGE
    sell_lo, sell_hi = ONMI_SWAP_SELL_PCT_RANGE
    ops_lo, ops_hi = ONMI_SWAP_TOTAL_OPS_RANGE
    sleep_lo, sleep_hi = ONMI_SWAP_SLEEP_BETWEEN_OPS
    return {
        "Как это работает": [
            "Когда токен проходит bonding curve, ликвидность переезжает в "
            "пару на AMM, и дальше торговля идёт обычным свапом в стиле "
            "UniswapV2.",
            "Сессия — случайное блуждание: случайный кошелёк, случайная пара, "
            "покупка или продажа, случайный объём и случайная пауза.",
            "Список пар собирается сканом фабрики и хранится в базе; "
            "очистка базы стирает историю свапов, но пары остаются.",
        ],
        "Параметры": [
            f"Сайт — {ONMI_SITE_SWAP}",
            f"Router — {ONMI_SWAP_ROUTER}",
            f"Factory — {ONMI_SWAP_FACTORY}",
            f"WETH (WzkLTC) — {ONMI_SWAP_WETH}",
            f"Минимальный баланс — {ONMI_SWAP_MIN_NATIVE_BALANCE} zkLTC",
            f"Сумма покупки — {buy_lo} – {buy_hi} zkLTC",
            f"Доля продажи — {sell_lo} – {sell_hi} %",
            f"Проскальзывание — {ONMI_SWAP_SLIPPAGE * 100:.1f}%",
            f"Вероятность продажи, если токен есть — "
            f"{ONMI_SWAP_PROB_SELL_IF_HAS * 100:.0f}%",
            f"Операций за сессию — {ops_lo} – {ops_hi}",
            f"Пауза между операциями — {sleep_lo} – {sleep_hi} сек",
        ],
        "Где что лежит": [
            "База: db/litvm.db, таблицы onmi_swap_known_pairs и "
            "onmi_swap_history",
            "Отчёт: result/onmi_swap/run_<время>/",
        ],
    }


def _menu() -> ModuleMenu:
    return ModuleMenu(
        title="Onmi Swap",
        subtitle="торговля graduated-токенами на AMM",
        icon="💱",
        actions=[
            MenuAction("run", "Запуск сессии", _handle_run,
                       "случайные покупки и продажи по известным парам",
                       icon="🤖"),
            MenuAction("refresh", "Обновить список пар", _handle_refresh,
                       "просканировать фабрику и дополнить базу", icon="🔎"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title="Прогресс · onmi_swap_history",
        reset=db.reset_history,
        info=_info,
    )


def run_litvm_onmi_swap() -> None:
    db.init_database()
    _menu().run()


__all__ = ["run_litvm_onmi_swap"]
