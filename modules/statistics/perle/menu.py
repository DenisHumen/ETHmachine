"""
Perle Eligibility Checker Menu
Интерактивное меню для проверки элигибельности SOL кошельков на Perle airdrop
"""

from colorama import Fore, Style
from questionary import Choice, select

from modules.simple_logger import logger
from modules.statistics.perle.database import (
    init_database, get_task_statistics, reset_database,
    all_tasks_completed, get_total_tasks_count,
)
from modules.statistics.perle.worker import (
    run_checker, export_results_xlsx, print_run_statistics,
)


def _show_db_stats():
    """Показать статистику из БД"""
    stats = get_task_statistics()

    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}PERLE ELIGIBILITY CHECKER — СТАТИСТИКА{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")

    if stats['total'] == 0:
        print(f"  {Fore.YELLOW}Нет данных в БД{Style.RESET_ALL}")
        return

    print(f"  Всего кошельков:   {stats['total']}")
    print(f"  Проверено:         {Fore.GREEN}{stats['completed']}{Style.RESET_ALL}")
    print(f"  Ожидают:           {Fore.YELLOW}{stats['pending']}{Style.RESET_ALL}")
    print(f"  Ошибки:            {Fore.RED}{stats['failed']}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'-' * 60}{Style.RESET_ALL}")
    print(f"  ✅ Eligible:        {Fore.GREEN}{stats['eligible']}{Style.RESET_ALL}")
    print(f"  ❌ Not eligible:    {Fore.RED}{stats['not_eligible']}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _handle_start():
    """Обработка запуска чекера"""
    init_database()
    total = get_total_tasks_count()

    if total > 0:
        is_completed = all_tasks_completed()

        if is_completed:
            print(f"\n{Fore.YELLOW}БД содержит {total} задач, все выполнены на 100%.{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Автоматическая очистка БД...{Style.RESET_ALL}")
            deleted = reset_database()
            logger.success(f"Очищено {deleted} задач из БД")
        else:
            print(f"\n{Fore.CYAN}В БД найдено {total} задач.{Style.RESET_ALL}")
            _show_db_stats()

            action = select(
                "Что делать с существующей БД?",
                choices=[
                    Choice('▶️  Продолжить работу по текущей БД', 'continue'),
                    Choice('🗑️  Очистить БД и начать заново', 'reset'),
                    Choice('🔙 Назад', 'back'),
                ],
                qmark='📊',
                pointer='👉'
            ).ask()

            if action == 'back' or action is None:
                return
            elif action == 'reset':
                deleted = reset_database()
                logger.success(f"Очищено {deleted} задач из БД")

    # Запускаем чекер
    run_checker()


def perle_menu():
    """Главное меню Perle Eligibility Checker"""
    while True:
        action = select(
            "Perle Eligibility Checker - выберите действие:",
            choices=[
                Choice('▶️  Запуск чекера                   Проверка элигибельности SOL кошельков', 'start'),
                Choice('🗑️  Очистка базы данных             Сброс всех задач', 'clear_db'),
                Choice('📊 Выгрузка результатов             Экспорт в Excel', 'export'),
                Choice('🔙 Назад', 'back'),
            ],
            qmark='📊',
            pointer='👉'
        ).ask()

        if action is None or action == 'back':
            return

        match action:
            case 'start':
                _handle_start()
                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")

            case 'clear_db':
                init_database()
                total = get_total_tasks_count()

                if total == 0:
                    print(f"{Fore.YELLOW}БД уже пуста{Style.RESET_ALL}")
                else:
                    confirm = select(
                        f"Удалить {total} задач из БД?",
                        choices=[
                            Choice('Да, очистить', 'yes'),
                            Choice('Нет, отмена', 'no'),
                        ],
                        qmark='⚠️'
                    ).ask()

                    if confirm == 'yes':
                        deleted = reset_database()
                        logger.success(f"Очищено {deleted} задач из БД")
                    else:
                        print(f"{Fore.YELLOW}Отменено{Style.RESET_ALL}")

                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")

            case 'export':
                init_database()
                total = get_total_tasks_count()

                if total == 0:
                    print(f"{Fore.YELLOW}Нет данных для экспорта{Style.RESET_ALL}")
                else:
                    _show_db_stats()
                    path = export_results_xlsx()
                    if path:
                        print(f"\n{Fore.GREEN}Файл сохранён: {path}{Style.RESET_ALL}")

                input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
