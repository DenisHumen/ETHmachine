"""Меню «zkSync Lite → Era swap» — отдельное подменю внутри zksync_lite."""
from __future__ import annotations

from modules.simple_logger import logger
from modules.ui import ui
from modules.ui.module_menu import MenuAction, ModuleMenu
from modules.zksync_lite.swap import planner, swap_database


def _failure_lines(failures: list) -> list[str]:
    """Провалы в одном формате: кошелёк, токен, маршрут и причина."""
    return [f"{f['wallet']}  {f['token']}  ({f['route']}): {f['error']}"
            for f in failures]


def _run_executor(*, stop_on_failure: bool) -> None:
    """Запуск свопов по pending-задачам.

    Общая часть авто-режима и обычного запуска: раньше этот блок был
    скопирован дважды и различался единственным флагом.
    """
    pending = swap_database.get_statistics().get("pending", 0)
    if pending == 0:
        logger.warning("Нет pending-задач — сначала выполните «Планирование»")
        return

    logger.info(f"Стартуем executor: {pending} pending-задач")
    # Импорт лениво: без установленных node_modules меню не должно падать.
    try:
        from modules.zksync_lite.swap.executor import SwapExecutor
    except Exception as exc:  # noqa: BLE001
        logger.error(f"executor import: {exc}")
        return
    try:
        executor = SwapExecutor(stop_on_failure=stop_on_failure)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"executor init: {exc}")
        return

    try:
        result = executor.run_all()
    except KeyboardInterrupt:
        logger.warning("Прервано пользователем — прогресс сохранён в БД")
        return

    ui.print_lines(ui.panel("Свопы завершены", [
        f"итог по кошелькам: {result['results']}",
        f"статистика БД:     {result['stats']}",
    ]))
    if result["failures"]:
        ui.print_lines(ui.panel(
            f"Провалы ({len(result['failures'])})",
            _failure_lines(result["failures"]),
            color=ui.theme.FG_ERR,
        ))


def _handle_plan(*, dry_run: bool) -> None:
    logger.info("Планирование задач свопа из balance-БД")
    summary = planner.plan_tasks(reset=False, dry_run=dry_run)

    ui.print_lines(ui.panel(
        "Превью плана" if dry_run else "План создан",
        [
            f"кошельков всего:            {summary['total_wallets']}",
            f"кошельков с задачами:       {summary['wallets_with_tasks']}",
            f"пропущено (нет приватника): {summary['skipped_no_priv']}",
            f"пропущено (мало баланса):   {summary['skipped_no_balance']}",
            f"создано задач:              {summary['created']}",
            f"по токенам:                 {summary['by_token']}",
            f"по маршрутам:               {summary['by_route']}",
        ],
    ))

    if dry_run and summary.get("preview"):
        ui.print_lines(ui.panel("Первые 20 задач", [
            f"{p['wallet']}  {p['token']:<5} {p['amount']:<14} → {p['route']}"
            for p in summary["preview"][:20]
        ]))


def _handle_plan_real() -> None:
    _handle_plan(dry_run=False)


def _handle_plan_dry() -> None:
    _handle_plan(dry_run=True)


def _handle_run() -> None:
    _run_executor(stop_on_failure=True)


def _handle_auto() -> None:
    """План новых задач и сразу запуск — без подтверждений на каждом шаге."""
    logger.info("Авто-режим: планирование")
    summary = planner.plan_tasks(reset=False, dry_run=False)
    logger.info(f"создано {summary['created']} задач для "
                f"{summary['wallets_with_tasks']} кошельков: "
                f"{summary['by_token']}")
    # Ошибка отдельной задачи не должна останавливать весь прогон.
    _run_executor(stop_on_failure=False)


def _info_sections() -> dict:
    return {
        "Маршруты": [
            "Layerswap — ETH → ETH, USDT → USDT",
            "ручной вывод — USDC и DAI уходят в L1, бридж в Era вручную",
        ],
        "Пороги и порядок": [
            "минимум ~$0.15: ETH ≥ 0.00005, USDT/USDC/DAI ≥ 0.15",
            "сначала стейблы, ETH последним — чтобы остался газ в Lite",
            "резерв ETH на газ: 0.00003 × (число операций + 2)",
        ],
        "Порядок запуска": [
            "1. «zkSync Lite Balance Checker» — наполнить "
            "db/zksync_lite_balance.db",
            "2. «Планирование» — создаст db/zksync_lite_swap.db",
            "3. «Запуск свопов»",
        ],
        "Что происходит по ходу": [
            "нет ChangePubKey — он выполнится автоматически (комиссия в ETH)",
            "при фейле задачи остальные задачи кошелька идут в «skipped»,",
            "работа переходит к следующему кошельку",
            "приход в Era — до 20 минут на пару Layerswap",
        ],
    }


def zksync_lite_swap_menu() -> None:
    ModuleMenu(
        title="zkSync Lite → Era",
        subtitle="миграция средств",
        icon="💱",
        actions=[
            MenuAction("auto", "Авто-режим", _handle_auto,
                       "план и запуск без подтверждений", icon="🤖"),
            MenuAction("plan", "Планирование", _handle_plan_real,
                       "создать задачи из balance-БД", icon="📋"),
            MenuAction("dry", "Превью плана", _handle_plan_dry,
                       "dry-run, в БД ничего не пишется", icon="👁️"),
            MenuAction("run", "Запуск свопов", _handle_run,
                       "выполнить pending-задачи", icon="▶️"),
        ],
        stats=swap_database.get_statistics,
        stats_title=str(swap_database.DB_PATH),
        reset=swap_database.reset_database,
        info=_info_sections,
    ).run()


__all__ = ["zksync_lite_swap_menu"]
