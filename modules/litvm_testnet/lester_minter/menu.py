"""Меню modules.litvm_testnet.lester_minter — фабрика ERC-20 на LiteForge."""
from __future__ import annotations

from config.modules.cfg_litvm_testnet import (
    LITVM_MINTER_DEPLOY_FEE_WEI,
    LITVM_MINTER_FACTORY,
    LITVM_MINTER_SUPPLY_RANGE,
    LITVM_MINTER_TX_PER_WALLET,
)
from config.modules.general_config import NUM_THREADS
from modules.core.runner import resolve_threads, run_parallel
from modules.data_manager import load_data
from modules.litvm_testnet.lester_minter import database as db
from modules.litvm_testnet.lester_minter import excel_export
from modules.litvm_testnet.lester_minter.worker import (
    plan_wallet, process_wallet,
)
from modules.simple_logger import log_simple, set_auto_progress
from modules.ui.module_menu import MenuAction, ModuleMenu


def _records_with_keys() -> list[dict]:
    rows = load_data()
    return [r for r in rows if (r.get("private_key") or "").strip()]


def _run_threaded(records: list[dict], fn, label: str) -> bool:
    """Обходит кошельки; False — пользователь прервал обход."""
    total = len(records)
    threads = resolve_threads(NUM_THREADS, total)
    set_auto_progress(False)
    log_simple(
        f"🪙 Lester Minter {label}: {total} кошельков · threads={threads}",
        "info",
    )
    try:
        run_parallel(records, lambda index, rec: fn(rec, index, total),
                     threads=threads, thread_name_prefix="litvm-minter")
    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем (состояние сохранено в БД)",
                   "warning")
        return False
    return True


def _summary() -> str:
    s = db.get_statistics()
    return (f"wallets={s.get('wallet_total', 0)} "
            f"confirmed={s.get('deploy_confirmed', 0)} "
            f"failed={s.get('deploy_failed', 0)} "
            f"pending={s.get('deploy_pending', 0)}")


def _handle_plan() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    _run_threaded(records, plan_wallet, "PLAN")
    log_simple(f"🏁 plan завершён · {_summary()}", "success")


def _handle_run() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    ok = _run_threaded(records, process_wallet, "RUN")
    log_simple(f"🏁 {'готово' if ok else 'остановлено'} · {_summary()}",
               "success" if ok else "warning")


def _handle_export() -> None:
    out = excel_export.build_report()
    log_simple(f"📑 отчёт сохранён: {out}", "success")


def _stats() -> dict:
    raw = db.get_statistics()
    if not raw.get("wallet_total", 0):
        return {"total": 0}
    ordered = {"кошельков": raw.get("wallet_total", 0)}
    for key, value in raw.items():
        if key.startswith("wallet_") and key != "wallet_total":
            ordered[f"кошельки · {key[len('wallet_'):]}"] = value
    ordered["деплоев"] = raw.get("deploy_total", 0)
    for key, value in raw.items():
        if key.startswith("deploy_") and key != "deploy_total":
            ordered[f"деплои · {key[len('deploy_'):]}"] = value
    return ordered


def _info() -> dict:
    count_lo, count_hi = LITVM_MINTER_TX_PER_WALLET
    supply_lo, supply_hi = LITVM_MINTER_SUPPLY_RANGE
    return {
        "Как это работает": [
            "Lester Minter — фабрика ERC-20 на LiteForge: один вызов "
            "создаёт токен с заданным именем, символом и эмиссией.",
            "Планирование придумывает токены на каждый кошелёк и складывает "
            "их в базу — сеть при этом не трогается.",
            "Запуск деплоит запланированные токены и продолжает с того "
            "места, где остановился прошлый прогон.",
        ],
        "Параметры": [
            f"Фабрика — {LITVM_MINTER_FACTORY}",
            f"Комиссия за деплой — "
            f"{LITVM_MINTER_DEPLOY_FEE_WEI / 1e18:.4f} zkLTC",
            f"Токенов на кошелёк — {count_lo}..{count_hi}, случайно",
            f"Эмиссия — {supply_lo:,}..{supply_hi:,}",
        ],
        "Где что лежит": [
            "База: db/litvm.db, таблицы minter_wallet_tasks и "
            "minter_deployments",
            "Отчёт: result/lester_minter/run_<время>/"
            "lester_minter_report.xlsx",
        ],
    }


def _menu() -> ModuleMenu:
    return ModuleMenu(
        title="Lester Minter",
        subtitle="фабрика ERC-20 на LiteForge",
        icon="🪙",
        actions=[
            MenuAction("plan", "Планирование", _handle_plan,
                       "придумать токены на каждый кошелёк", icon="📋"),
            MenuAction("run", "Запуск деплоя", _handle_run,
                       "задеплоить или продолжить запланированные токены",
                       icon="▶️"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title="Прогресс · minter_*",
        reset=db.reset_tasks,
        info=_info,
    )


def run_litvm_minter() -> None:
    db.init_database()
    _menu().run()


__all__ = ["run_litvm_minter"]
