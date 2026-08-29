"""Меню SafePal X1 Eligibility Checker."""

from __future__ import annotations

from config.modules.cfg_safepal_x1_checker import ACT_CODE, CHAIN_ID, CHANNEL_CODE
from modules.eth.safepal_x1_checker.checker import (
    export_results_xlsx,
    run_checker,
)
from modules.eth.safepal_x1_checker.database import (
    DB_PATH,
    all_tasks_completed,
    get_task_statistics,
    get_total_tasks_count,
    init_database,
    reset_database,
)
from modules.simple_logger import logger
from modules.ui import ui
from modules.ui.menu_model import BACK_KEY
from modules.ui.module_menu import MenuAction, ModuleMenu


def _show_db_stats() -> None:
    ui.print_lines(ui.stats_panel(
        "SafePal X1 — состояние БД", get_task_statistics(),
        footer=f"{DB_PATH} · actCode={ACT_CODE} · "
               f"channelCode={CHANNEL_CODE} · chainId={CHAIN_ID}"))


def _handle_start() -> None:
    init_database()
    total = get_total_tasks_count()

    if total > 0:
        if all_tasks_completed():
            logger.info(f"В БД {total} задач и все выполнены")
            action = ui.choose("Что делать?", [
                ("🗑️ Очистить БД и проверить заново", "reset"),
            ])
        else:
            _show_db_stats()
            action = ui.choose("Что делать с существующей БД?", [
                ("▶️ Продолжить — только pending и failed", "continue"),
                ("🗑️ Очистить и начать заново", "reset"),
            ])

        if action in (None, BACK_KEY):
            return
        if action == "reset":
            deleted = reset_database()
            logger.success(f"Очищено {deleted} задач из БД")

    try:
        run_checker()
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Сбой SafePal X1 checker: {exc}")


def _handle_export() -> None:
    init_database()
    if get_total_tasks_count() == 0:
        logger.warning("Нет данных для экспорта")
        return
    _show_db_stats()
    path = export_results_xlsx()
    if path:
        logger.success(f"Файл сохранён: {path}")


def _info_sections() -> dict:
    return {
        "Что делает": [
            "проверяет право на клейм SafePal X1 для каждого EVM-кошелька",
            f"сайт — https://www.safepal.com/en/claimX1/v2/#/v/"
            f"{ACT_CODE}/{CHANNEL_CODE}",
        ],
        "Как проверяет": [
            "1. checkChannelCode → channelName и sku",
            "2. getSignMsg → nonce, msg и serverTime",
            "3. personal_sign(msg) приватным ключом локально (eth_account)",
            "4. authSign → session_id",
            "5. activityShopingToken → token",
            "6. checkIsCanOrder → YES или NO",
        ],
        "Откуда кошельки": [
            "адрес выводится из private_key — поле wallet_address",
            "в data.csv игнорируется",
            "прокси: proxy → reserve_proxy → напрямую",
        ],
        "Настройки": [
            "config/modules/cfg_safepal_x1_checker.py —",
            "ACT_CODE, CHANNEL_CODE, CHAIN_ID, HTTP_TIMEOUT",
            "config/modules/general_config.py —",
            "NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS",
        ],
        "Состояние": [
            f"задачи — {DB_PATH}",
            "Excel — result/safepal_x1_checker/*.xlsx",
            "Ctrl+C безопасен: прогресс остаётся в БД",
        ],
    }


def safepal_x1_checker_menu() -> None:
    ModuleMenu(
        title="SafePal X1",
        subtitle="проверка права на клейм",
        icon="🟪",
        actions=[
            MenuAction("start", "Запуск чекера", _handle_start,
                       "проверить или продолжить по БД", icon="▶️"),
            MenuAction("export", "Экспорт в Excel", _handle_export,
                       "result/safepal_x1_checker/", icon="📥"),
        ],
        stats=get_task_statistics,
        stats_title=str(DB_PATH),
        reset=reset_database,
        info=_info_sections,
    ).run()


run_safepal_x1_checker = safepal_x1_checker_menu
