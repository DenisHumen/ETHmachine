"""
Zora Claimer Menu
Интерактивное меню для модуля клейма Zora Protocol Rewards
"""

from colorama import Fore, Style
from questionary import Choice, select

from modules.simple_logger import logger
from modules.claim.zora_claimer.database import (
    init_database, get_task_statistics, reset_database,
    all_tasks_completed, get_total_tasks_count,
)
from modules.claim.zora_claimer.worker import (
    run_claimer, export_results_xlsx, print_run_statistics,
)
from config.modules.cfg_claimer import CLAIMER_NETWORKS


def _show_db_stats():
    """Показать статистику из БД"""
    db_stats = get_task_statistics()
    total = get_total_tasks_count()

    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}СТАТИСТИКА ZORA CLAIMER{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")

    if not db_stats:
        print(f"  {Fore.YELLOW}Нет данных в БД{Style.RESET_ALL}")
        return

    total_claimed = 0.0
    total_gas = 0.0

    for network, statuses in db_stats.items():
        net_name = CLAIMER_NETWORKS.get(network, {}).get('name', network)
        print(f"\n  {Fore.CYAN}{net_name}:{Style.RESET_ALL}")

        for status, data in statuses.items():
            if status == 'completed':
                color = Fore.GREEN
                icon = '  '
            elif status == 'failed':
                color = Fore.RED
                icon = '  '
            elif status == 'skipped':
                color = Fore.YELLOW
                icon = '  '
            else:
                color = Fore.WHITE
                icon = '  '

            print(
                f"    {icon} {color}{status}: {data['count']} | "
                f"Заклеймлено: {data['total_claimed']:.8f} ETH | "
                f"Газ: {data['total_gas']:.8f} ETH{Style.RESET_ALL}"
            )

            total_claimed += data['total_claimed']
            total_gas += data['total_gas']

    print(f"\n  {Fore.GREEN}Всего заклеймлено: {total_claimed:.8f} ETH{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}Всего газ: {total_gas:.8f} ETH{Style.RESET_ALL}")
    print(f"  {Fore.GREEN}Чистая прибыль: {total_claimed - total_gas:.8f} ETH{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Всего задач в БД: {total}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}\n")


def _handle_start():
    """Обработка запуска клеймера"""
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
                qmark='💰',
                pointer='👉'
            ).ask()

            if action == 'back' or action is None:
                return
            elif action == 'reset':
                deleted = reset_database()
                logger.success(f"Очищено {deleted} задач из БД")

    # Запускаем клеймер
    run_claimer()


def claimer_menu():
    """Главное меню клеймера"""
    while True:
        action = select(
            "Zora Claimer - выберите действие:",
            choices=[
                Choice('▶️  Запуск клеймера                 Клейм наград Zora Protocol', 'start'),
                Choice('🗑️  Очистка базы данных             Сброс всех задач', 'clear_db'),
                Choice('📊 Выгрузка результатов             Экспорт в Excel', 'export'),
                Choice('🔙 Назад', 'back'),
            ],
            qmark='💰',
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
