"""Меню модуля zkSync Lite balance checker."""

from __future__ import annotations

from colorama import Fore, Style
from questionary import Choice, select

from modules.simple_logger import logger
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
    s = get_task_statistics()
    sep = f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}"
    print()
    print(sep)
    print(f"{Fore.CYAN}zkSync Lite — СТАТИСТИКА БД{Style.RESET_ALL}")
    print(f"{Fore.CYAN}DB:{Style.RESET_ALL} {DB_FILE}")
    print(sep)

    if s["total"] == 0:
        print(f"  {Fore.YELLOW}БД пуста{Style.RESET_ALL}")
        print(sep)
        return

    print(f"  Всего:              {s['total']}")
    print(f"  Выполнено:          {Fore.GREEN}{s['completed']}{Style.RESET_ALL}")
    print(f"  Pending:            {Fore.YELLOW}{s['pending']}{Style.RESET_ALL}")
    print(f"  Ошибки:             {Fore.RED}{s['failed']}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'-' * 60}{Style.RESET_ALL}")
    print(f"  💰 Активных:        {Fore.GREEN}{s['active']}{Style.RESET_ALL}")
    print(f"  🪙 С токенами:      {Fore.GREEN}{s['with_tokens']}{Style.RESET_ALL}")
    print(f"  🖼️  С NFT:          {Fore.GREEN}{s['with_nfts']}{Style.RESET_ALL}")
    print(sep)
    print()


def _handle_start() -> None:
    init_database()
    total = get_total_tasks_count()
    if total > 0:
        if all_tasks_completed():
            print(
                f"\n{Fore.YELLOW}В БД {total} задач, все выполнены. "
                f"Очищаю и стартую заново…{Style.RESET_ALL}"
            )
            deleted = reset_database()
            logger.success(f"Очищено {deleted} задач")
        else:
            print(f"\n{Fore.CYAN}В БД {total} задач (есть невыполненные).{Style.RESET_ALL}")
            _show_db_stats()
            action = select(
                "Что делать с существующей БД?",
                choices=[
                    Choice("▶️  Продолжить работу по текущей БД", "continue"),
                    Choice("🗑️  Очистить БД и начать заново", "reset"),
                    Choice("🔙 Назад", "back"),
                ],
                qmark="📊",
                pointer="👉",
            ).ask()

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
        print(f"{Fore.YELLOW}Нет данных для экспорта{Style.RESET_ALL}")
        return
    _show_db_stats()
    path = export_results_xlsx()
    if path:
        print(f"\n{Fore.GREEN}Excel сохранён: {path}{Style.RESET_ALL}")


def _handle_clear() -> None:
    init_database()
    total = get_total_tasks_count()
    if total == 0:
        print(f"{Fore.YELLOW}БД уже пуста{Style.RESET_ALL}")
        return
    confirm = select(
        f"Удалить {total} задач из БД?",
        choices=[Choice("Да, очистить", "yes"), Choice("Нет, отмена", "no")],
        qmark="⚠️",
    ).ask()
    if confirm == "yes":
        deleted = reset_database()
        logger.success(f"Очищено {deleted} задач")
    else:
        print(f"{Fore.YELLOW}Отменено{Style.RESET_ALL}")


def _print_info() -> None:
    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗
║                zkSync Lite Balance Checker                       ║
╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}

Сайт:     https://lite.zksync.io/account
API:      https://api.zksync.io/api/v0.2/accounts/<address>

Чекер для каждого кошелька из выбранного {Fore.YELLOW}data/data*.csv{Style.RESET_ALL} напрямую
дёргает публичный REST-эндпоинт zkSync Lite (тот же, что использует
сайт после подключения MetaMask/OKX) и собирает все балансы:

  • активность аккаунта (committed/finalized)
  • балансы всех токенов (decimals подгружаются из /tokens)
  • депозиты «в пути»
  • NFT (если есть)

Кошельки берутся из поля {Fore.YELLOW}wallet_address{Style.RESET_ALL}, а если оно пустое —
выводятся из {Fore.YELLOW}private_key{Style.RESET_ALL}. У каждого кошелька свой {Fore.YELLOW}proxy{Style.RESET_ALL}
из той же строки CSV (прокси берётся через {Fore.YELLOW}modules/proxy_manager.py{Style.RESET_ALL}).

Состояние:  {Fore.YELLOW}db/zksync_lite_balance.db{Style.RESET_ALL}
Excel:      {Fore.YELLOW}result/zksync_lite/zksync_lite_*.xlsx{Style.RESET_ALL}

Можно прервать (Ctrl+C) и продолжить позже — обработаются только
оставшиеся pending/failed задачи.
""")


def zksync_lite_menu() -> None:
    while True:
        action = select(
            "🟪 zkSync Lite — выберите действие:",
            choices=[
                Choice("▶️  Запуск чекера                    🌟 Проверка/продолжение по БД", "start"),
                Choice("🆕 Начать с нуля                     🌟 Очистить БД и стартовать", "fresh"),
                Choice("📊 Статистика                        🌟 Что лежит в БД", "stats"),
                Choice("📥 Экспорт результатов в Excel       🌟 result/zksync_lite/*.xlsx", "export"),
                Choice("� Swap to Era                       🌟 Lite → Era до 4 мая", "swap"),                Choice("💧 DAI Withdraw → L1                 🌟 DAI Lite → Ethereum L1", "dai_withdraw"),                Choice("�🗑️  Очистка БД                       🌟 Сброс всех задач", "clear"),
                Choice("📖 Информация                        🌟 Описание модуля", "info"),
                Choice("🔙 Назад", "back"),
            ],
            qmark="🟪",
            pointer="👉",
        ).ask()

        if action in (None, "back"):
            return
        if action == "start":
            _handle_start()
        elif action == "fresh":
            init_database()
            deleted = reset_database()
            logger.success(f"Очищено {deleted} задач, стартую заново")
            try:
                run_zksync_lite_checker()
            except Exception as exc:  # noqa: BLE001
                logger.error(f"zkSync Lite checker сбой: {exc}")
        elif action == "stats":
            _show_db_stats()
        elif action == "export":
            _handle_export()
        elif action == "swap":
            from modules.zksync_lite.swap.swap_menu import zksync_lite_swap_menu
            zksync_lite_swap_menu()
        elif action == "dai_withdraw":
            from modules.zksync_lite.dai_withdraw.cli import main as dai_main
            dai_main()
        elif action == "clear":
            _handle_clear()
        elif action == "info":
            _print_info()

        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")


__all__ = ["zksync_lite_menu"]
