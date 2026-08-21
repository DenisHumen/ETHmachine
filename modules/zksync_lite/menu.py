"""Меню модуля zkSync Lite balance checker."""

from __future__ import annotations

from modules.simple_logger import logger
from modules.ui import ui
from modules.ui.module_menu import MenuAction, ModuleMenu
from modules.zksync_lite.checker import run_zksync_lite_checker
from modules.zksync_lite.database import (
    DB_FILE,
    all_tasks_completed,
    get_task_statistics,
    get_total_tasks_count,
    init_database,
    reset_database,
)
from modules.zksync_lite.exporter import export_results_xlsx


def _show_db_stats() -> None:
    ui.print_lines(ui.stats_panel("zkSync Lite — состояние БД",
                                  get_task_statistics(), footer=str(DB_FILE)))


def _handle_start() -> None:
    init_database()
    total = get_total_tasks_count()
    if total > 0:
        if all_tasks_completed():
            logger.info(f"В БД {total} задач и все выполнены — "
                        f"очищаю и стартую заново")
            deleted = reset_database()
            logger.success(f"Очищено {deleted} задач")
        else:
            logger.info(f"В БД {total} задач, среди них есть невыполненные")
            _show_db_stats()
            action = ui.choose("Что делать с существующей БД?", [
                ("▶️ Продолжить работу по текущей БД", "continue"),
                ("🗑️ Очистить БД и начать заново", "reset"),
            ])

            if action in (None, "back"):
                return
            if action == "reset":
                deleted = reset_database()
                logger.success(f"Очищено {deleted} задач")

    try:
        run_zksync_lite_checker()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"zkSync Lite checker сбой: {exc}")


def _handle_export() -> None:
    init_database()
    if get_total_tasks_count() == 0:
        logger.warning("Нет данных для экспорта")
        return
    _show_db_stats()
    path = export_results_xlsx()
    if path:
        logger.success(f"Excel сохранён: {path}")


def _handle_fresh() -> None:
    """Стереть прогресс и сразу запустить чекер с нуля."""
    init_database()
    deleted = reset_database()
    logger.success(f"Очищено {deleted} задач, стартую заново")
    try:
        run_zksync_lite_checker()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"zkSync Lite checker сбой: {exc}")


def _handle_swap() -> None:
    from modules.zksync_lite.swap.swap_menu import zksync_lite_swap_menu
    zksync_lite_swap_menu()


def _handle_dai_withdraw() -> None:
    from modules.zksync_lite.dai_withdraw.cli import main as dai_main
    dai_main()


def _info_sections() -> dict:
    return {
        "Что делает": [
            "для каждого кошелька дёргает публичный REST zkSync Lite —",
            "тот же, что сайт после подключения MetaMask/OKX",
        ],
        "Что собирает": [
            "активность аккаунта (committed/finalized)",
            "балансы всех токенов (decimals подгружаются из /tokens)",
            "депозиты «в пути»",
            "NFT, если есть",
        ],
        "Откуда кошельки": [
            "поле wallet_address выбранного data/data*.csv,",
            "а если оно пустое — адрес выводится из private_key",
            "у каждого кошелька свой proxy из той же строки CSV",
        ],
        "Адреса": [
            "сайт — https://lite.zksync.io/account",
            "API — https://api.zksync.io/api/v0.2/accounts/<address>",
            f"состояние — {DB_FILE}",
            "Excel — result/zksync_lite/zksync_lite_*.xlsx",
        ],
        "Прерывание": [
            "Ctrl+C безопасен: при следующем запуске обработаются",
            "только оставшиеся pending/failed задачи",
        ],
    }


def zksync_lite_menu() -> None:
    ModuleMenu(
        title="zkSync Lite",
        subtitle="проверка балансов",
        icon="🟪",
        actions=[
            MenuAction("start", "Запуск чекера", _handle_start,
                       "проверить или продолжить по БД", icon="▶️"),
            MenuAction("fresh", "Начать с нуля", _handle_fresh,
                       "очистить БД и сразу стартовать", icon="🆕",
                       confirm="Очистить БД и запустить проверку заново?"),
            MenuAction("export", "Экспорт в Excel", _handle_export,
                       "result/zksync_lite/*.xlsx", icon="📥"),
            MenuAction("swap", "Swap to Era", _handle_swap,
                       "перевод Lite → Era", icon="💱"),
            MenuAction("dai_withdraw", "DAI Withdraw → L1",
                       _handle_dai_withdraw,
                       "вывод DAI из Lite в Ethereum L1", icon="💧"),
        ],
        stats=get_task_statistics,
        stats_title=str(DB_FILE),
        reset=reset_database,
        info=_info_sections,
    ).run()


__all__ = ["zksync_lite_menu"]
