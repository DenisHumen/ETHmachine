"""Общее меню кранов Fhenix.

Ghost Faucet и Alchemy Faucet делают одно и то же: пройти по кошелькам из
``data/data.csv``, решить капчу, отправить заявку и дождаться зачисления.
Раньше у каждого была своя копия меню — со своими рамками из ``'=' * 60``,
своим «Нажмите Enter» и своим циклом ``ThreadPoolExecutor``. Здесь кран —
это данные (:class:`Faucet`), а меню одно на оба.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import ModuleType
from typing import Callable, Iterable, Mapping, Sequence

from modules.captcha.manager import (
    SERVICE_CONFIG_FIELDS,
    configured_services_for_type,
    services_for_captcha_type,
)
from modules.core.runner import resolve_threads, run_parallel
from modules.data_manager import load_data
from modules.simple_logger import log_simple, set_auto_progress
from modules.ui.module_menu import MenuAction, ModuleMenu

# Человекочитаемые названия статусов задачи. Порядок ключей у конкретного
# крана задаётся в Faucet.statuses — он же порядок жизненного цикла.
_STATUS_LABELS = {
    "pending": "ожидают",
    "in_progress": "в работе",
    "requested": "заявка принята",
    "cooldown": "кулдаун",
    "arrived": "получено",
    "ineligible": "кошелёк не подходит",
    "failed": "ошибка",
}

# Порядок статусов в однострочной сводке для лога.
_SUMMARY_ORDER = ("arrived", "requested", "cooldown", "ineligible",
                  "failed", "in_progress", "pending")


@dataclass(frozen=True)
class Faucet:
    """Описание крана: всё, чем один кран отличается от другого."""

    # Короткий идентификатор — попадает в имена потоков.
    key: str
    title: str
    subtitle: str
    # Модуль database конкретного крана (init_database / get_statistics /
    # reset_tasks) и его worker.process_wallet.
    db: ModuleType
    process_wallet: Callable[[dict, int, int], None]
    # Статусы, которые кран реально выставляет, в порядке жизненного цикла.
    statuses: Sequence[str]
    info: Mapping[str, Iterable[str]] = field(default_factory=dict)
    icon: str = "🚰"


# ── служебное ────────────────────────────────────────────────────────────

def _captcha_ready(captcha_type: str = "turnstile") -> bool:
    """True, если настроен хотя бы один сервис с поддержкой ``captcha_type``."""
    if configured_services_for_type(captcha_type):
        return True
    supported = services_for_captcha_type(captcha_type)
    log_simple(
        f"❌ Нет API-ключа ни для одного сервиса, поддерживающего '{captcha_type}'.",
        "error",
    )
    if supported:
        log_simple(f"   Поддерживают '{captcha_type}': {', '.join(supported)}", "info")
        fields = ", ".join(f"{s} → {SERVICE_CONFIG_FIELDS[s]}" for s in supported)
        log_simple(
            f"   Заполните любой ключ в config/modules/general_config.py: {fields}",
            "info",
        )
    return False


def _summary(stats: Mapping[str, int]) -> str:
    """Однострочная сводка для итогового лога: только ненулевые статусы."""
    parts = [f"{key}={int(stats.get(key, 0) or 0)}"
             for key in _SUMMARY_ORDER if int(stats.get(key, 0) or 0)]
    parts.append(f"total={int(stats.get('total', 0) or 0)}")
    return " · ".join(parts)


def _stats(faucet: Faucet) -> dict:
    """Статистика в порядке жизненного цикла задачи, а не в алфавитном."""
    raw = faucet.db.get_statistics()
    if not raw or not raw.get("total"):
        return {"total": 0}
    ordered = {_STATUS_LABELS.get(status, status): raw.get(status, 0)
               for status in faucet.statuses}
    ordered["total"] = raw.get("total", 0)
    return ordered


# ── действия ─────────────────────────────────────────────────────────────

def _run_claims(faucet: Faucet) -> None:
    if not _captcha_ready():
        return

    rows = load_data()
    if not rows:
        log_simple("Нет данных в data/data.csv", "error")
        return

    records = [r for r in rows if (r.get("private_key") or "").strip()]
    total = len(records)
    if total == 0:
        log_simple("Нет кошельков с private_key", "error")
        return

    # В логах уже есть [i/N] — второй индикатор прогресса не нужен.
    set_auto_progress(False)
    threads = resolve_threads(None, total)
    log_simple(
        f"{faucet.icon} {faucet.title}: старт для {total} кошельков "
        f"(потоков: {threads})",
        "info",
    )

    interrupted = False
    try:
        run_parallel(
            records,
            lambda index, record: faucet.process_wallet(record, index, total),
            threads=threads,
            thread_name_prefix=f"fhenix-{faucet.key}",
        )
    except KeyboardInterrupt:
        log_simple("⚠ прервано пользователем — состояние сохранено в базе",
                   "warning")
        interrupted = True

    summary = _summary(faucet.db.get_statistics())
    log_simple(f"🏁 {'остановлено' if interrupted else 'готово'} · {summary}",
               "warning" if interrupted else "success")


def run_faucet_menu(faucet: Faucet) -> None:
    """Меню одного крана. Единственная точка входа модуля-крана."""
    faucet.db.init_database()

    ModuleMenu(
        title=faucet.title,
        subtitle=faucet.subtitle,
        icon=faucet.icon,
        actions=[
            MenuAction("run", "Запросить токены",
                       lambda: _run_claims(faucet),
                       "пройти по кошелькам из data.csv", icon="▶️"),
        ],
        stats=lambda: _stats(faucet),
        stats_title=f"Прогресс · {faucet.db.DB_PATH.name}",
        reset=faucet.db.reset_tasks,
        info=faucet.info,
    ).run()


__all__ = ["Faucet", "run_faucet_menu"]
