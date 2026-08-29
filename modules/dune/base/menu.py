"""Меню Dune Base Network Analytics чекера."""
from __future__ import annotations

from modules.dune.base.checker import export_results_xlsx, run_base_checker
from modules.dune.base.database import (
    DB_FILE, all_tasks_completed, get_task_statistics, get_total_tasks_count,
    init_database, reset_database,
)
from modules.simple_logger import logger
from modules.ui import ui
from modules.ui.module_menu import MenuAction, ModuleMenu

_STATS_TITLE = f"Прогресс · {DB_FILE.name}"


# ── Статистика и справка ─────────────────────────────────────────────────

def _stats() -> dict:
    """Состояние базы в порядке жизненного цикла задачи."""
    raw = get_task_statistics()
    return {
        "проверено": raw["completed"],
        "ожидают": raw["pending"],
        "ошибка": raw["failed"],
        "есть в ranking": raw["found_ranking"],
        "есть в volume": raw["found_volume"],
        "найдено всего": raw["found_any"],
        "total": raw["total"],
    }


def _info() -> dict:
    return {
        "Как это работает": [
            "Для каждого кошелька поднимается свой Chromium со своим прокси, "
            "открывается публичный дашборд и адрес вводится в поиск обеих "
            "таблиц: Top 2,500,000 Wallet Ranking и то же самое по объёму.",
            "API-ключ Dune не нужен: Cloudflare обходит patchright, окно "
            "браузера уводится за пределы экрана — визуально ничего не "
            "появляется.",
            "Адрес берётся из private_key выбранного data/data*.csv; если "
            "ключа нет — из wallet_address. Прокси берётся из той же строки.",
            "Прогон можно прервать Ctrl+C и продолжить позже: обработаются "
            "только оставшиеся задачи со статусом «ожидают» и «ошибка».",
        ],
        "Настройки (config/modules/general_config.py)": [
            "NUM_THREADS — сколько браузеров работает одновременно",
            "SLEEP_BETWEEN_ACTIONS — пауза между кошельками в одном потоке",
            "DELAY_BETWEEN_ACCOUNTS — разброс старта потоков",
            "RETRY_COUNT — попытки при сетевых ошибках и сбоях разбора",
        ],
        "Где что лежит": [
            "Дашборд:",
            "https://dune.com/nvthao/base-network-analytics-dashboard",
            f"База задач: db/{DB_FILE.name}",
            "Задачи и результаты: таблица check_tasks",
            "Отчёт: result/dune/dune_base_<время>.xlsx",
        ],
    }


# ── Действия ─────────────────────────────────────────────────────────────

def _handle_start() -> None:
    init_database()
    total = get_total_tasks_count()

    if total > 0:
        if all_tasks_completed():
            logger.info(
                f"В базе {total} задач и все выполнены — очищаем перед новым прогоном"
            )
            deleted = reset_database()
            logger.success(f"Очищено задач: {deleted}")
        else:
            ui.print_lines(ui.stats_panel(_STATS_TITLE, _stats()))
            action = ui.choose(f"В базе {total} задач — что с ними делать?", [
                ("▶️ Продолжить с места остановки", "continue"),
                ("🗑️ Очистить базу и начать заново", "reset"),
            ])
            if action in (None, "back"):
                return
            if action == "reset":
                deleted = reset_database()
                logger.success(f"Очищено задач: {deleted}")

    try:
        run_base_checker()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Сбой Dune Base checker: {exc}")


def _handle_export() -> None:
    path = export_results_xlsx()
    if path:
        logger.success(f"Файл сохранён: {path}")


def base_menu() -> None:
    """Меню действий для проекта Base в Dune."""
    ModuleMenu(
        title="Dune · Base Network Analytics",
        subtitle="поиск кошельков в топе дашборда",
        icon="🟦",
        actions=[
            MenuAction("start", "Запуск чекера", _handle_start,
                       "проверить новые кошельки и добить незавершённые",
                       icon="▶️"),
            MenuAction("export", "Экспорт результатов", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title=_STATS_TITLE,
        reset=reset_database,
        info=_info,
    ).run()


__all__ = ["base_menu"]
