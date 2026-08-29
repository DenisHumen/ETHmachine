"""LiteForge bridge — меню пресета (Sepolia ⇄ LiteForge)."""
from __future__ import annotations

from config.modules.cfg_litvm_testnet import (
    LITVM_BRIDGE_AMOUNT_PCT_RANGE,
    LITVM_BRIDGE_AUTO_FINALIZE_L1,
    LITVM_BRIDGE_MIN_AMOUNT_ZKLTC,
    LITVM_BRIDGE_RETURN_ENABLED,
    LITVM_BRIDGE_TX_COUNT_RANGE,
)
from modules.core.runner import resolve_threads, run_parallel
from modules.data_manager import load_data
from modules.litvm_testnet.bridge import database as db
from modules.litvm_testnet.bridge.worker import (
    _primary_direction, plan_wallet, process_wallet,
)
from modules.litvm_testnet.database import DB_PATH
from modules.simple_logger import log_simple, set_auto_progress
from modules.ui.module_menu import MenuAction, ModuleMenu

# Как называется направление моста в интерфейсе. Раньше справка всегда
# писала «Sepolia → LiteForge», даже когда конфиг вёл в обратную сторону.
_DIRECTION_LABELS = {
    "l1_to_l2": "Sepolia → LiteForge (L1 → L2)",
    "l2_to_l1": "LiteForge → Sepolia (L2 → L1)",
}


def _records_with_keys() -> list[dict]:
    rows = load_data()
    return [r for r in rows if (r.get("private_key") or "").strip()]


def _run_threaded(records: list[dict], fn, label: str, threads: int) -> bool:
    """Возвращает True если завершилось без KeyboardInterrupt."""
    total = len(records)
    set_auto_progress(False)
    log_simple(f"🌉 LiteForge Bridge {label}: {total} кошельков · threads={threads}",
               "info")
    try:
        run_parallel(
            records,
            lambda index, record: fn(record, index, total),
            threads=threads,
            thread_name_prefix="litvm-bridge",
        )
    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем (состояние в БД сохранено)",
                   "warning")
        return False
    return True


def _summary() -> str:
    s = db.get_statistics()
    return (f"wallets={s.get('wallet_total',0)} "
            f"tx_done={s.get('tx_done',0)} tx_total={s.get('tx_total',0)} "
            f"failed={s.get('tx_failed',0)} inflight={s.get('tx_inflight',0)}")


def _handle_plan() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    threads = resolve_threads(total=len(records))
    _run_threaded(records, plan_wallet, "PLAN", threads)
    log_simple(f"🏁 plan завершён · {_summary()}", "success")


def _handle_run() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    threads = resolve_threads(total=len(records))
    ok = _run_threaded(records, process_wallet, "RUN", threads)
    log_simple(f"🏁 {'готово' if ok else 'остановлено'} · {_summary()}",
               "success" if ok else "warning")


# ── Экраны меню ─────────────────────────────────────────────────────────

_WALLET_LABELS = {
    "wallet_pending": "кошельков ожидают",
    "wallet_planned": "кошельков запланировано",
    "wallet_in_progress": "кошельков в работе",
    "wallet_completed": "кошельков завершено",
    "wallet_failed": "кошельков с ошибкой",
}

_RETURN_LABELS = {
    "return_pending": "обратный мост ожидает",
    "return_sent": "обратный мост отправлен",
    "return_confirmed": "обратный мост подтверждён",
    "return_failed": "обратный мост с ошибкой",
    "return_skipped": "обратный мост пропущен",
}


def _stats() -> dict:
    raw = db.get_statistics()
    ordered = {"кошельков в базе": raw.get("wallet_total", 0)}
    for key, label in _WALLET_LABELS.items():
        ordered[label] = raw.get(key, 0)
    ordered["транзакций в плане"] = raw.get("tx_total", 0)
    ordered["транзакций выполнено"] = raw.get("tx_done", 0)
    ordered["транзакций в полёте"] = raw.get("tx_inflight", 0)
    ordered["транзакций с ошибкой"] = raw.get("tx_failed", 0)
    for key, value in raw.items():
        if not key.startswith("return_"):
            continue
        ordered[_RETURN_LABELS.get(key, key)] = value
    return ordered


def _info() -> dict:
    pct_lo, pct_hi = LITVM_BRIDGE_AMOUNT_PCT_RANGE
    cnt_lo, cnt_hi = LITVM_BRIDGE_TX_COUNT_RANGE
    direction = _primary_direction()
    return {
        "Как это работает": [
            f"Направление: {_DIRECTION_LABELS[direction]}.",
            "«Планирование» снимает баланс источника и раскладывает его на "
            "несколько транзакций случайного размера. Повторный запуск план "
            "не переписывает — модуль продолжает с того места, где остановился.",
            "«Запуск моста» выполняет транзакции по плану; каждый шаг "
            "сохраняется в базе, поэтому прерывание не теряет прогресс.",
            "L1 → L2: approve, затем depositERC20 в ERC20Inbox, затем ожидание "
            "кредита на LiteForge.",
            "L2 → L1: withdrawEth через ArbSys. Финализация на Sepolia "
            "(Outbox) происходит автоматически при следующих запусках — "
            "раньше не даёт challenge-окно Arbitrum Orbit.",
        ],
        "Параметры (config/modules/cfg_litvm_testnet.py)": [
            f"Транзакций на кошелёк: {cnt_lo}–{cnt_hi}, выбирается случайно",
            f"Сумма транзакции: {pct_lo}–{pct_hi}% от баланса, случайно",
            f"Минимальная сумма: {LITVM_BRIDGE_MIN_AMOUNT_ZKLTC} zkLTC",
            "Обратный мост: "
            + ("включён" if LITVM_BRIDGE_RETURN_ENABLED else "выключен"),
            "Авто-финализация на L1: "
            + ("включена" if LITVM_BRIDGE_AUTO_FINALIZE_L1 else "выключена"),
        ],
        "Где что лежит": [
            f"База: db/{DB_PATH.name}",
            "Кошельки: таблица bridge_wallet_tasks",
            "Транзакции: таблица bridge_tx_tasks",
            "«Очистить базу» удаляет обе таблицы; кэш cookie Vercel остаётся.",
        ],
    }


def run_litvm_bridge() -> None:
    db.init_database()
    ModuleMenu(
        title="Мост Sepolia ⇄ LiteForge",
        subtitle="перенос zkLTC через ERC20Inbox",
        icon="🌉",
        actions=[
            MenuAction("plan", "Планирование", _handle_plan,
                       "рассчитать транзакции, ничего не отправляя", icon="📋"),
            MenuAction("run", "Запуск моста", _handle_run,
                       "выполнить или продолжить задачи из плана", icon="▶️"),
        ],
        stats=_stats,
        stats_title=f"Прогресс · {DB_PATH.name}",
        reset=db.reset_tasks,
        info=_info,
    ).run()


__all__ = ["run_litvm_bridge"]
