"""Меню Dune Base Network Analytics чекера."""
from colorama import Fore, Style
from questionary import Choice, select

from modules.dune.base.checker import (
    export_results_xlsx,
    print_run_statistics,
    run_base_checker,
)
from modules.dune.base.database import (
    DB_FILE,
    all_tasks_completed,
    get_task_statistics,
    get_total_tasks_count,
    init_database,
    reset_database,
)
from modules.simple_logger import logger


# ───────────────────────── Helpers ─────────────────────────

def _show_db_stats() -> None:
    s = get_task_statistics()
    sep = f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}"
    print()
    print(sep)
    print(f"{Fore.CYAN}DUNE BASE CHECKER — СТАТИСТИКА ИЗ БД{Style.RESET_ALL}")
    print(f"{Fore.CYAN}DB:{Style.RESET_ALL} {DB_FILE}")
    print(sep)

    if s["total"] == 0:
        print(f"  {Fore.YELLOW}Нет данных в БД{Style.RESET_ALL}")
        print(sep)
        return

    print(f"  Всего кошельков:    {s['total']}")
    print(f"  Проверено:          {Fore.GREEN}{s['completed']}{Style.RESET_ALL}")
    print(f"  Ожидают:            {Fore.YELLOW}{s['pending']}{Style.RESET_ALL}")
    print(f"  Ошибки:             {Fore.RED}{s['failed']}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'-' * 60}{Style.RESET_ALL}")
    print(f"  ✅ В Ranking:        {Fore.GREEN}{s['found_ranking']}{Style.RESET_ALL}")
    print(f"  ✅ В Volume:         {Fore.GREEN}{s['found_volume']}{Style.RESET_ALL}")
    print(f"  ✅ Найдено всего:    {Fore.GREEN}{s['found_any']}{Style.RESET_ALL}")
    print(sep)
    print()


# ───────────────────────── Actions ─────────────────────────

def _handle_start() -> None:
    init_database()
    total = get_total_tasks_count()

    if total > 0:
        if all_tasks_completed():
            print(
                f"\n{Fore.YELLOW}БД содержит {total} задач, все выполнены на 100%."
                f"{Style.RESET_ALL}"
            )
            print(f"{Fore.YELLOW}Автоматическая очистка БД...{Style.RESET_ALL}")
            deleted = reset_database()
            logger.success(f"Очищено {deleted} задач из БД")
        else:
            print(f"\n{Fore.CYAN}В БД найдено {total} задач.{Style.RESET_ALL}")
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
                logger.success(f"Очищено {deleted} задач из БД")

    try:
        run_base_checker()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Сбой Dune Base checker: {exc}")


def _handle_clear() -> None:
    init_database()
    total = get_total_tasks_count()
    if total == 0:
        print(f"{Fore.YELLOW}БД уже пуста{Style.RESET_ALL}")
        return

    confirm = select(
        f"Удалить {total} задач из БД?",
        choices=[
            Choice("Да, очистить", "yes"),
            Choice("Нет, отмена", "no"),
        ],
        qmark="⚠️",
    ).ask()

    if confirm == "yes":
        deleted = reset_database()
        logger.success(f"Очищено {deleted} задач из БД")
    else:
        print(f"{Fore.YELLOW}Отменено{Style.RESET_ALL}")


def _handle_export() -> None:
    init_database()
    total = get_total_tasks_count()
    if total == 0:
        print(f"{Fore.YELLOW}Нет данных для экспорта{Style.RESET_ALL}")
        return
    _show_db_stats()
    path = export_results_xlsx()
    if path:
        print(f"\n{Fore.GREEN}Файл сохранён: {path}{Style.RESET_ALL}")


def _handle_stats() -> None:
    init_database()
    _show_db_stats()
    print_run_statistics()


def _print_info() -> None:
    text = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗
║      Dune → Base Network Analytics Wallet Checker               ║
╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}

Дашборд:  https://dune.com/nvthao/base-network-analytics-dashboard

Чекер для каждого кошелька из выбранного {Fore.YELLOW}data/data*.csv{Style.RESET_ALL}
открывает публичный дашборд через локальный Chromium (без API-ключа,
обход Cloudflare выполняется библиотекой {Fore.YELLOW}patchright{Style.RESET_ALL}) и вводит
адрес в строку поиска каждой из двух таблиц:

  • Top 2,500,000 Wallet Ranking
  • Top 2,500,000 Wallets Ranking by Volume

Окно браузера размещается вне экрана — визуально ничего не появляется.

Источник адресов: поле {Fore.YELLOW}private_key{Style.RESET_ALL} (конвертируется в EVM-адрес).
Если private_key пуст, используется поле {Fore.YELLOW}wallet_address{Style.RESET_ALL}.
У каждого кошелька свой {Fore.YELLOW}proxy{Style.RESET_ALL} из той же строки CSV — пробрасывается
в browser-context.

Все настройки берутся из {Fore.YELLOW}config/modules/cfg_base.py{Style.RESET_ALL}:

  NUM_THREADS              — количество потоков (каждому поднимается свой Chromium)
  SLEEP_BETWEEN_ACTIONS    — пауза между кошельками в одном потоке
  DELAY_BETWEEN_ACCOUNTS   — стаггер между стартом потоков
  RETRY_COUNT              — попытки при сетевых/парсинг ошибках

Состояние и результаты:  {Fore.YELLOW}db/dune_base_checker.db{Style.RESET_ALL}
Excel выгрузки:          {Fore.YELLOW}result/dune/dune_base_*.xlsx{Style.RESET_ALL}

Можно прервать (Ctrl+C) и продолжить позже — обработаются только
оставшиеся pending/failed задачи.
"""
    print(text)


# ───────────────────────── Menu ─────────────────────────

def base_menu():
    """Меню действий для проекта Base в Dune."""
    while True:
        action = select(
            "🟦 Dune → Base — выберите действие:",
            choices=[
                Choice("▶️  Запуск чекера                    🌟 Проверка/продолжение по БД", "start"),
                Choice("📊 Статистика                        🌟 Что лежит в БД", "stats"),
                Choice("📥 Экспорт результатов в Excel       🌟 Из БД в result/dune/*.xlsx", "export"),
                Choice("🗑️  Очистка базы данных              🌟 Сброс всех задач", "clear_db"),
                Choice("📖 Информация                        🌟 Описание модуля и настроек", "info"),
                Choice("🔙 Назад", "back"),
            ],
            qmark="🟦",
            pointer="👉",
        ).ask()

        if action in (None, "back"):
            return

        if action == "start":
            _handle_start()
        elif action == "stats":
            _handle_stats()
        elif action == "export":
            _handle_export()
        elif action == "clear_db":
            _handle_clear()
        elif action == "info":
            _print_info()

        input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
