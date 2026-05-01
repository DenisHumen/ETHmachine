"""Меню «zkSync Lite → Era swap» — отдельный sub-menu в zksync_lite."""
from __future__ import annotations

from colorama import Fore, Style
from questionary import Choice, select

from modules.simple_logger import logger
from modules.zksync_lite.swap import planner, swap_database


def _show_stats() -> None:
    stats = swap_database.get_statistics()
    sep = f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}"
    print()
    print(sep)
    print(f"{Fore.CYAN}zkSync Lite → Era — СВОПЫ (БД){Style.RESET_ALL}")
    print(f"{Fore.CYAN}DB:{Style.RESET_ALL} {swap_database.DB_PATH}")
    print(sep)
    if stats.get("total", 0) == 0:
        print(f"  {Fore.YELLOW}БД пуста{Style.RESET_ALL}")
    else:
        for k, v in stats.items():
            if k == "total":
                continue
            print(f"  {k:<22} {v}")
        print(f"  {'-'*40}")
        print(f"  total                  {stats['total']}")
    print(sep)
    print()


def _handle_plan(*, dry_run: bool) -> None:
    print(f"\n{Fore.CYAN}Планирование задач свопа из balance-БД…{Style.RESET_ALL}\n")
    summary = planner.plan_tasks(reset=False, dry_run=dry_run)
    print(f"  кошельков всего:           {summary['total_wallets']}")
    print(f"  кошельков с задачами:      {summary['wallets_with_tasks']}")
    print(f"  пропущено (нет приватника):{summary['skipped_no_priv']}")
    print(f"  пропущено (мало баланса):  {summary['skipped_no_balance']}")
    print(f"  создано задач:             {Fore.GREEN}{summary['created']}{Style.RESET_ALL}")
    print(f"  по токенам:                {summary['by_token']}")
    print(f"  по маршрутам:              {summary['by_route']}")
    if dry_run and summary.get("preview"):
        print(f"\n{Fore.YELLOW}Превью первых 20 задач:{Style.RESET_ALL}")
        for p in summary["preview"][:20]:
            print(f"   {p['wallet']}  {p['token']:<5} {p['amount']:<14} → {p['route']}")


def _handle_auto() -> None:
    """Полный авто-режим: спланировать новые задачи + запустить всё без подтверждений."""
    print(f"\n{Fore.CYAN}Авто-режим: планирование…{Style.RESET_ALL}")
    summary = planner.plan_tasks(reset=False, dry_run=False)
    print(f"  created: {Fore.GREEN}{summary['created']}{Style.RESET_ALL} | "
          f"wallets_with_tasks: {summary['wallets_with_tasks']} | "
          f"by_token: {summary['by_token']}")

    stats = swap_database.get_statistics()
    pending = stats.get("pending", 0)
    if pending == 0:
        print(f"{Fore.YELLOW}Нет pending задач (нечего свопить).{Style.RESET_ALL}")
        return

    print(f"\n{Fore.CYAN}Авто-режим: запускаем {pending} задач{Style.RESET_ALL}\n")
    try:
        from modules.zksync_lite.swap.executor import SwapExecutor
    except Exception as e:
        logger.error(f"executor import: {e}")
        return
    try:
        ex = SwapExecutor(stop_on_failure=False)
    except Exception as e:
        logger.error(f"executor init: {e}")
        return
    try:
        result = ex.run_all()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Прервано пользователем{Style.RESET_ALL}")
        return
    print(f"\n{Fore.GREEN}=== Авто-режим завершён ==={Style.RESET_ALL}")
    print(f"  итоги:        {result['stats']}")
    if result["failures"]:
        print(f"\n{Fore.RED}Провалы ({len(result['failures'])}):{Style.RESET_ALL}")
        for f in result["failures"]:
            print(f"  • {f['wallet']}  {f['token']}  ({f['route']}): {f['error']}")


def _handle_run() -> None:
    stats = swap_database.get_statistics()
    pending = stats.get("pending", 0)
    if pending == 0:
        print(f"{Fore.YELLOW}Нет pending задач — сначала выполните «Планирование».{Style.RESET_ALL}")
        return
    print(f"\n{Fore.CYAN}Стартуем executor: {pending} pending задач{Style.RESET_ALL}\n")
    # Импорт лениво — чтобы меню не падало, если node_modules не поставлены
    try:
        from modules.zksync_lite.swap.executor import SwapExecutor
    except Exception as e:
        logger.error(f"executor import: {e}")
        return
    try:
        ex = SwapExecutor(stop_on_failure=True)
    except Exception as e:
        logger.error(f"executor init: {e}")
        return
    try:
        result = ex.run_all()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Прервано пользователем{Style.RESET_ALL}")
        return
    print(f"\n{Fore.GREEN}=== Готово ==={Style.RESET_ALL}")
    print(f"  итог по кошелькам: {result['results']}")
    print(f"  статистика БД:     {result['stats']}")
    if result["failures"]:
        print(f"\n{Fore.RED}Провалы:{Style.RESET_ALL}")
        for f in result["failures"]:
            print(f"  • {f['wallet']}  {f['token']}  ({f['route']}): {f['error']}")


def _handle_reset() -> None:
    swap_database.reset_database()
    logger.success("swap_tasks очищена")


def _print_info() -> None:
    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗
║              zkSync Lite → Era — миграция средств                ║
╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}

Маршруты:
  {Fore.GREEN}Layerswap{Style.RESET_ALL}        ETH → ETH, USDT → USDT
  {Fore.YELLOW}Manual withdraw{Style.RESET_ALL}  USDC, DAI — вывод в L1, бридж в Era вручную

Пороги (~$0.15): ETH ≥ 0.00005, USDT/USDC/DAI ≥ 0.15.
Сначала исполняются стейблы, ETH — последним (для запаса газа Lite).
Резерв ETH на газ: 0.00003 ETH × (кол-во операций + 2).

Авто-режим: один пункт меню — план (только новые) + запуск без
подтверждений; при ошибке отдельной задачи не останавливаемся,
просто двигаемся дальше с баннером.

Перед запуском:
  1. Запустить «zkSync Lite Balance Checker», чтобы наполнить
     {Fore.YELLOW}db/zksync_lite_balance.db{Style.RESET_ALL}.
  2. В этом меню — «Планирование» (создаст {Fore.YELLOW}db/zksync_lite_swap.db{Style.RESET_ALL}).
  3. «Запуск свопов».

При первой задаче: если у аккаунта нет ChangePubKey, он будет
выполнен автоматически (комиссия в ETH).

При фейле задачи — баннер с подробностями. Остальные задачи
кошелька помечаются «skipped», работа переходит на следующий
кошелёк.

Ожидание прихода в Era — до 20 минут на пару Layerswap. Сверка
по eth_getBalance / balanceOf на {Fore.YELLOW}https://mainnet.era.zksync.io{Style.RESET_ALL}.
""")


def zksync_lite_swap_menu() -> None:
    while True:
        action = select(
            "💱 zkSync Lite → Era — выберите действие:",
            choices=[
                Choice("🤖 Авто-режим (план + запуск, без подтверждений)", "auto"),
                Choice("📋 Планирование (создать задачи из balance-БД)", "plan"),
                Choice("👁️  Превью плана (dry-run, без записи в БД)",   "dry"),
                Choice("▶️  Запуск свопов",                              "run"),
                Choice("📊 Статистика swap-БД",                          "stats"),
                Choice("🗑️  Очистить swap-БД",                          "reset"),
                Choice("📖 Информация",                                  "info"),
                Choice("🔙 Назад",                                       "back"),
            ],
            qmark="💱",
            pointer="👉",
        ).ask()

        if action in (None, "back"):
            return
        if action == "auto":
            _handle_auto()
        elif action == "plan":
            _handle_plan(dry_run=False)
        elif action == "dry":
            _handle_plan(dry_run=True)
        elif action == "run":
            _handle_run()
        elif action == "stats":
            _show_stats()
        elif action == "reset":
            _handle_reset()
        elif action == "info":
            _print_info()
        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")


__all__ = ["zksync_lite_swap_menu"]
