"""Меню modules.litvm_testnet.midas — Midas Prediction Market."""
from __future__ import annotations

from config.modules.cfg_litvm_testnet import (
    MIDAS_BET_AMOUNT_USDC,
    MIDAS_BETS_PER_WALLET,
    MIDAS_FAUCET_NATIVE_COOLDOWN_SEC,
    MIDAS_FAUCET_USDC_COOLDOWN_SEC,
    MIDAS_SITE_URL,
    MIDAS_TURNSTILE_SITEKEY,
)
from config.modules.general_config import NUM_THREADS
from modules.core.runner import resolve_threads, run_parallel
from modules.data_manager import load_data
from modules.litvm_testnet.midas import database as db
from modules.litvm_testnet.midas import excel_export
from modules.litvm_testnet.midas.worker import (
    plan_wallet, process_wallet, run_checkin_streak_loop,
)
from modules.simple_logger import log_simple, set_auto_progress
from modules.ui.module_menu import MenuAction, ModuleMenu


def _records_with_keys() -> list[dict]:
    return [r for r in load_data() if (r.get("private_key") or "").strip()]


def _run_threaded(records: list[dict], fn, label: str) -> bool:
    """Обходит кошельки; False — пользователь прервал обход."""
    total = len(records)
    threads = resolve_threads(NUM_THREADS, total)
    set_auto_progress(False)
    log_simple(f"🎯 Midas {label}: {total} кошельков · threads={threads}",
               "info")
    try:
        run_parallel(records, lambda index, rec: fn(rec, index, total),
                     threads=threads, thread_name_prefix="litvm-midas")
    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем (состояние сохранено в БД)",
                   "warning")
        return False
    return True


def _summary() -> str:
    s = db.get_statistics()
    return (f"wallets={s.get('wallet_total', 0)} "
            f"registered={s.get('wallet_registered', 0)} "
            f"bets_ok={s.get('bet_confirmed', 0)} "
            f"bets_failed={s.get('bet_failed', 0)}")


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


def _handle_checkin_loop() -> None:
    records = _records_with_keys()
    if not records:
        log_simple("Нет кошельков с private_key в data/data.csv", "error")
        return
    threads = resolve_threads(NUM_THREADS, len(records))
    set_auto_progress(False)
    log_simple(
        "ℹ Check-in loop работает бесконечно. "
        "Нажмите Ctrl+C чтобы остановить (состояние в БД).",
        "info",
    )
    stop_flag = {"v": False}
    try:
        run_checkin_streak_loop(
            records, threads, should_stop=lambda: stop_flag["v"],
        )
    except KeyboardInterrupt:
        stop_flag["v"] = True
        log_simple("⚠ check-in loop прерван пользователем", "warning")


def _handle_export() -> None:
    out = excel_export.build_report()
    log_simple(f"📑 отчёт сохранён: {out}", "success")


def _stats() -> dict:
    raw = db.get_statistics()
    if not raw.get("wallet_total", 0):
        return {"total": 0}
    ordered = {
        "кошельков": raw.get("wallet_total", 0),
        "зарегистрировано": raw.get("wallet_registered", 0),
    }
    for key, value in raw.items():
        if key.startswith("wallet_") and key not in ("wallet_total",
                                                     "wallet_registered"):
            ordered[f"кошельки · {key[len('wallet_'):]}"] = value
    ordered["ставок"] = raw.get("bet_total", 0)
    for key, value in raw.items():
        if key.startswith("bet_") and key != "bet_total":
            ordered[f"ставки · {key[len('bet_'):]}"] = value
    ordered["faucet · запросов"] = raw.get("faucet_total", 0)
    ordered["faucet · успешно"] = raw.get("faucet_success", 0)
    ordered["check-in · запросов"] = raw.get("checkin_total", 0)
    ordered["check-in · успешно"] = raw.get("checkin_success", 0)
    return ordered


def _info() -> dict:
    bets_lo, bets_hi = MIDAS_BETS_PER_WALLET
    amount_lo, amount_hi = MIDAS_BET_AMOUNT_USDC
    return {
        "Как это работает": [
            "Планирование создаёт запись на каждый кошелёк и придумывает "
            "никнейм — сеть при этом не трогается.",
            "Запуск проходит по кошелькам: регистрация, оба крана, "
            "ежедневный check-in и ставки на рынке предсказаний.",
            "Check-in loop крутится бесконечно и держит стрик: как только "
            "начинается новый день по UTC, кошельки отмечаются заново. "
            "Остановка — Ctrl+C, прогресс остаётся в базе.",
        ],
        "Параметры": [
            f"Сайт — {MIDAS_SITE_URL}",
            f"Turnstile sitekey — {MIDAS_TURNSTILE_SITEKEY}",
            f"Кулдаун крана USDC — {MIDAS_FAUCET_USDC_COOLDOWN_SEC // 60} мин",
            f"Кулдаун крана zkLTC — "
            f"{MIDAS_FAUCET_NATIVE_COOLDOWN_SEC // 3600} ч",
            f"Ставок на кошелёк — {bets_lo}..{bets_hi}, случайно",
            f"Размер ставки — {amount_lo}..{amount_hi} USDC, случайно",
        ],
        "Где что лежит": [
            "База: db/litvm.db, таблицы midas_wallets, midas_bets, "
            "midas_faucet_claims, midas_checkins",
            "Отчёт: result/midas/run_<время>/midas_report.xlsx",
        ],
    }


def _menu() -> ModuleMenu:
    return ModuleMenu(
        title="Midas Prediction Market",
        subtitle="ставки на рынке предсказаний LITVM",
        icon="🎯",
        actions=[
            MenuAction("plan", "Планирование", _handle_plan,
                       "завести кошельки в базе и придумать никнеймы",
                       icon="📋"),
            MenuAction("run", "Запуск", _handle_run,
                       "регистрация, краны, check-in и ставки", icon="▶️"),
            MenuAction("checkin_loop", "Check-in без остановки",
                       _handle_checkin_loop,
                       "держать стрик, отмечаясь каждый день по UTC",
                       icon="🔁"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title="Прогресс · midas_*",
        reset=db.reset_tasks,
        info=_info,
    )


def run_litvm_midas() -> None:
    db.init_database()
    _menu().run()


__all__ = ["run_litvm_midas"]
