"""ZNS.bio — меню пресета (регистрация .lit доменов)."""
from __future__ import annotations

from config.modules.cfg_litvm_testnet import (
    ZNS_MIN_NATIVE_BALANCE,
    ZNS_NAME_LENGTH_RANGE,
    ZNS_OPS_PER_WALLET_RANGE,
    ZNS_REGISTRY,
    ZNS_SITE_CART,
    ZNS_SITE_DOCS,
    ZNS_SITE_HOME,
    ZNS_SITE_SEARCH,
    ZNS_SLEEP_BETWEEN_OPS,
    ZNS_TLD,
    ZNS_YEARS_WEIGHTS,
)
from config.modules.general_config import SHUFLE_ACCOUNTS
from modules.data_manager import load_data
from modules.litvm_testnet.database import DB_PATH
from modules.litvm_testnet.zns_bio import database as db
from modules.litvm_testnet.zns_bio import excel_export
from modules.litvm_testnet.zns_bio.worker import run_random_session
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


def _handle_export() -> None:
    try:
        out = excel_export.build_report()
    except Exception as exc:  # noqa: BLE001 — отчёт не должен ронять меню
        log_simple(f"⚠ не удалось собрать отчёт: {exc}", "warning")
        return
    log_simple(f"📑 ZNS-отчёт сохранён: {out}", "success")


# ── Экраны меню ─────────────────────────────────────────────────────────

_STATUS_LABELS = {
    "pending": "ожидают",
    "sent": "отправлено",
    "arrived": "зарегистрировано",
    "failed": "ошибка",
    "skipped": "пропущено",
}


def _stats() -> dict:
    raw = db.get_statistics()
    ordered = {label: raw.get(f"status_{status}", 0)
               for status, label in _STATUS_LABELS.items()}
    ordered["кошельков с доменом"] = raw.get("unique_wallets_done", 0)
    paid = float(raw.get("total_paid_wei", 0)) / 1e18
    ordered["оплачено, zkLTC"] = f"{paid:.6f}"
    ordered["total"] = raw.get("total", 0)
    return ordered


def _years_word(years: int) -> str:
    if years % 10 == 1 and years % 100 != 11:
        return "год"
    if years % 10 in (2, 3, 4) and years % 100 not in (12, 13, 14):
        return "года"
    return "лет"


def _years_lines() -> list[str]:
    total = sum(ZNS_YEARS_WEIGHTS.values()) or 1
    return [
        f"{years} {_years_word(years)} — {weight * 100 / total:.1f}%"
        for years, weight in sorted(ZNS_YEARS_WEIGHTS.items())
    ]


def _range(bounds, suffix: str = "") -> str:
    """«5–10 символов», но «1 регистрация», когда границы совпали."""
    low, high = bounds
    body = f"{low}" if low == high else f"{low}–{high}"
    return f"{body} {suffix}".strip()


def _info() -> dict:
    return {
        "Как это работает": [
            f"Каждый кошелёк из data/data.csv регистрирует случайный никнейм "
            f"в зоне .{ZNS_TLD} на ZNS Connect.",
            "Имя подбирает генератор ников; занятость проверяется и в базе "
            "модуля, и в контракте реестра.",
            "Цена берётся из контракта: регистрация плюс продление за каждый "
            "следующий год.",
            "Если на выбранный срок баланса не хватает, модуль пробует тот же "
            "домен на один год.",
            "Кошелёк с балансом ниже минимального пропускается целиком.",
        ],
        "Срок аренды выбирается случайно": _years_lines(),
        "Параметры (config/modules/cfg_litvm_testnet.py)": [
            f"Зона: .{ZNS_TLD}",
            f"Длина имени: {_range(ZNS_NAME_LENGTH_RANGE, 'символов')}",
            f"Регистраций на кошелёк: {_range(ZNS_OPS_PER_WALLET_RANGE)}",
            f"Минимальный баланс: {ZNS_MIN_NATIVE_BALANCE} zkLTC",
            f"Пауза между регистрациями: {_range(ZNS_SLEEP_BETWEEN_OPS, 'с')}",
            f"Реестр: {ZNS_REGISTRY}",
        ],
        "Ссылки": [
            f"Сайт: {ZNS_SITE_HOME}",
            f"Поиск домена: {ZNS_SITE_SEARCH}",
            f"Корзина: {ZNS_SITE_CART}",
            f"Документация: {ZNS_SITE_DOCS}",
        ],
        "Где что лежит": [
            f"База: db/{DB_PATH.name}",
            "Регистрации: таблица zns_registrations",
            "Отчёт: result/zns_bio/",
        ],
    }


def run_litvm_zns_bio() -> None:
    db.init_database()
    ModuleMenu(
        title=f"ZNS.bio · домены .{ZNS_TLD}",
        subtitle="регистрация никнеймов на LiteForge",
        icon="🪪",
        actions=[
            MenuAction("run", "Запуск регистрации", _handle_run,
                       "пройти по всем кошелькам и занять свободные имена",
                       icon="▶️"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title=f"Прогресс · {DB_PATH.name}",
        reset=db.reset_registrations,
        info=_info,
    ).run()


__all__ = ["run_litvm_zns_bio"]
