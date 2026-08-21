"""Меню вывода DAI из zkSync Lite в L1 (план / запуск / статистика).

Запускается из главного меню или напрямую::

    python -m modules.zksync_lite.dai_withdraw.cli
"""
from __future__ import annotations

import sys

from modules.simple_logger import logger
from modules.ui import ui
from modules.ui.module_menu import MenuAction, ModuleMenu
from modules.zksync_lite.dai_withdraw import database as dai_db
from modules.zksync_lite.dai_withdraw.executor import DaiWithdrawExecutor
from modules.zksync_lite.dai_withdraw.planner import plan_tasks, MIN_DAI_HUMAN


def cmd_plan(reset: bool = False, dry_run: bool = False) -> None:
    logger.info(f"Планирование: min_dai={MIN_DAI_HUMAN}, reset={reset}, "
                f"dry_run={dry_run}")
    summary = plan_tasks(reset=reset, dry_run=dry_run)

    ui.print_lines(ui.panel("Итог планирования", [
        f"{key}: {value}" for key, value in summary.items() if key != "preview"
    ]))

    if dry_run and summary.get("preview"):
        ui.print_lines(ui.panel("Первые 20 кошельков", [
            f"{row['wallet']}  {row['amount']} DAI"
            for row in summary["preview"][:20]
        ]))


def cmd_plan_dry() -> None:
    cmd_plan(reset=False, dry_run=True)


def cmd_run() -> None:
    dai_db.init_database()
    result = DaiWithdrawExecutor().run_all()
    ui.print_lines(ui.panel("Готово", [
        f"результаты: {len(result['results'])}",
        f"фейлы:      {len(result['failures'])}",
        f"статусы:    {result['stats']}",
    ]))


def cmd_auto() -> None:
    cmd_plan(reset=False, dry_run=False)
    cmd_run()


def _info_sections() -> dict:
    return {
        "Что делает": [
            "выводит DAI из zkSync Lite в Ethereum L1,",
            f"порог — от {MIN_DAI_HUMAN} DAI на кошелёк",
        ],
        "Порядок": [
            "1. «zkSync Lite Balance Checker» — наполнить balance-БД",
            "2. «Планирование» — создать задачи",
            "3. «Запуск» — выполнить pending-задачи",
        ],
        "Состояние": [f"задачи — {dai_db.DB_FILE}"],
    }


def main() -> None:
    ModuleMenu(
        title="DAI withdraw: Lite → L1",
        subtitle="вывод DAI в Ethereum",
        icon="💧",
        actions=[
            MenuAction("auto", "Авто-режим", cmd_auto,
                       "план и сразу запуск", icon="🤖"),
            MenuAction("plan", "Планирование", cmd_plan,
                       "создать задачи из balance-БД", icon="📋"),
            MenuAction("dry", "Превью плана", cmd_plan_dry,
                       "dry-run, в БД ничего не пишется", icon="👁️"),
            MenuAction("run", "Запуск задач", cmd_run,
                       "выполнить pending-задачи", icon="▶️"),
        ],
        stats=dai_db.get_statistics,
        stats_title=str(dai_db.DB_FILE),
        reset=dai_db.reset_database,
        info=_info_sections,
    ).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
