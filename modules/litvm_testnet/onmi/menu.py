"""Меню modules.litvm_testnet.onmi — создание мем-токенов на onmi.fun."""
from __future__ import annotations

from typing import Callable

from config.modules.cfg_litvm_testnet import (
    ONMI_DESCRIPTION_PROBABILITY,
    ONMI_GAS_RESERVE_ZKLTC,
    ONMI_INITIAL_BUY_PROBABILITY,
    ONMI_INITIAL_BUY_RANGE_ZKLTC,
    ONMI_MIN_NATIVE_BALANCE_ZKLTC,
    ONMI_SITE_BOARD,
    ONMI_SITE_CREATE,
    ONMI_SITE_DOCS,
    ONMI_SITE_LIQUIDITY,
    ONMI_SITE_SWAP,
    ONMI_TOKEN_FACTORY,
    ONMI_TX_ATTEMPTS,
)
from config.modules.general_config import NUM_THREADS, SHUFLE_ACCOUNTS
from modules.core.runner import resolve_threads, run_parallel
from modules.data_manager import load_data
from modules.litvm_testnet.onmi import database as db
from modules.litvm_testnet.onmi import excel_export
from modules.litvm_testnet.onmi.worker import plan_wallet, process_wallet
from modules.simple_logger import log_simple, set_auto_progress
from modules.ui.module_menu import MenuAction, ModuleMenu


def _records_with_keys() -> list[dict]:
    rows = load_data()
    records = [r for r in rows if (r.get("private_key") or "").strip()]
    if SHUFLE_ACCOUNTS:
        import random as _r
        _r.shuffle(records)
    return records


def _run_threaded(records: list[dict],
                  fn: Callable[[dict, int, int], object],
                  label: str) -> bool:
    """Обходит кошельки; False — пользователь прервал обход."""
    total = len(records)
    threads = resolve_threads(NUM_THREADS, total)
    set_auto_progress(False)
    log_simple(f"🪙 Onmi {label}: {total} кошельков · threads={threads}", "info")
    try:
        run_parallel(records, lambda index, rec: fn(rec, index, total),
                     threads=threads, thread_name_prefix="onmi")
    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем (состояние сохранено в БД)",
                   "warning")
        return False
    return True


def _summary() -> str:
    s = db.get_statistics()
    return (f"total={s.get('total', 0)} "
            f"pending={s.get('pending', 0)} "
            f"image_ready={s.get('image_ready', 0)} "
            f"metadata_ready={s.get('metadata_ready', 0)} "
            f"arrived={s.get('arrived', 0)} "
            f"failed={s.get('failed', 0)} "
            f"skipped={s.get('skipped', 0)}")


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
    log_simple(f"🏁 {'готово' if ok else 'прервано'} · {_summary()}",
               "success" if ok else "warning")


def _handle_export() -> None:
    try:
        out = excel_export.build_report()
    except Exception as exc:  # noqa: BLE001 — отчёт не должен ронять меню
        log_simple(f"⚠ export failed: {exc}", "warning")
        return
    log_simple(f"📑 отчёт сохранён: {out}", "success")


def _handle_auto() -> None:
    _handle_plan()
    _handle_run()
    _handle_export()


def _stats() -> dict:
    """Статистика в порядке жизненного цикла задачи, а не в алфавитном."""
    raw = db.get_statistics()
    labels = {
        "pending": "ожидают",
        "image_ready": "картинка готова",
        "metadata_ready": "метаданные готовы",
        "tx_sent": "отправлено",
        "arrived": "создано",
        "failed": "ошибка",
        "skipped": "пропущено",
    }
    ordered = {label: raw.get(status, 0) for status, label in labels.items()}
    ordered["total"] = raw.get("total", 0)
    return ordered


def _info() -> dict:
    buy_lo, buy_hi = ONMI_INITIAL_BUY_RANGE_ZKLTC
    return {
        "Как это работает": [
            "Onmi.fun — лаунчпад мем-токенов на LITVM. Модуль повторяет тот же "
            "путь создания монеты, что и сайт:",
            "1. название и символ генерируются локально, описание — примерно "
            "в 5% случаев;",
            "2. картинка берётся с Pinterest, приводится к квадрату не меньше "
            "1000×1000 и весу до 1 МБ;",
            "3. картинка уходит на S3 через /api/upload/image;",
            "4. метаданные уходят через /api/upload/metadata;",
            "5. on-chain вызывается createTokenAndBuy() или createToken();",
            "6. из receipt достаются адрес токена и количество монет.",
            "AI Magic на стороне сайта отключён, поэтому названия всегда "
            "локальные.",
        ],
        "Параметры": [
            f"Фабрика TokenLaunch — {ONMI_TOKEN_FACTORY}",
            f"Минимальный баланс — {ONMI_MIN_NATIVE_BALANCE_ZKLTC} zkLTC",
            f"Резерв на газ — {ONMI_GAS_RESERVE_ZKLTC} zkLTC",
            f"Вероятность initial buy — {ONMI_INITIAL_BUY_PROBABILITY * 100:.0f}%",
            f"Сумма initial buy — {buy_lo} – {buy_hi} zkLTC",
            f"Вероятность описания — {ONMI_DESCRIPTION_PROBABILITY * 100:.0f}%",
            f"Попыток на транзакцию — {ONMI_TX_ATTEMPTS}",
        ],
        "Ссылки": [
            f"Создание токена — {ONMI_SITE_CREATE}",
            f"Board, торговля — {ONMI_SITE_BOARD}",
            f"Свапы — {ONMI_SITE_SWAP}",
            f"Ликвидность — {ONMI_SITE_LIQUIDITY}",
            f"Документация — {ONMI_SITE_DOCS}",
        ],
        "Где что лежит": [
            "База задач: db/litvm.db, таблица onmi_coin_tasks",
            "Отчёт: result/onmi/run_<время>/",
        ],
    }


def _menu() -> ModuleMenu:
    return ModuleMenu(
        title="Onmi.fun",
        subtitle="создание мем-токенов на LITVM",
        icon="🪙",
        actions=[
            MenuAction("auto", "Авто-режим", _handle_auto,
                       "планирование, создание монет и отчёт подряд",
                       icon="🤖"),
            MenuAction("plan", "Планирование", _handle_plan,
                       "снять балансы и подготовить метаданные", icon="📋"),
            MenuAction("run", "Запуск создания", _handle_run,
                       "создать монеты по подготовленным задачам", icon="▶️"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title="Прогресс · onmi_coin_tasks",
        reset=db.reset_database,
        info=_info,
    )


def run_litvm_onmi() -> None:
    db.init_database()
    _menu().run()


__all__ = ["run_litvm_onmi"]
