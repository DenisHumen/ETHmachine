"""Pharos Discord Connect — интерактивное меню."""
from colorama import Fore, Style
from questionary import Choice, select, confirm

from config.modules.cfg_base import (
    NUM_THREADS, RETRY_COUNT,
    SLEEP_BETWEEN_ACTIONS, DELAY_BETWEEN_ACCOUNTS,
)
from modules.simple_logger import log_simple
from modules.pharos.discord_connect import database as db
from modules.pharos.discord_connect.worker import (
    create_tasks_from_csv,
    run_discord_connect,
    export_results_xlsx,
)


def _print_task_summary():
    """Вывести сводку по задачам в БД."""
    counts = db.get_task_counts()
    total = counts.get("total", 0)
    if total == 0:
        print(f"  {Fore.YELLOW}База данных пуста{Style.RESET_ALL}")
        return

    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    pending = counts.get("pending", 0)
    auth_ok = counts.get("auth_ok", 0)

    print(f"\n  {Fore.CYAN}╔══════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║  📊 Статус задач в базе данных       ║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}╠══════════════════════════════════════╣{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║{Style.RESET_ALL}  Всего:     {Fore.WHITE}{total:<24}{Fore.CYAN}║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║{Style.RESET_ALL}  Pending:   {Fore.YELLOW}{pending:<24}{Fore.CYAN}║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║{Style.RESET_ALL}  Auth OK:   {Fore.BLUE}{auth_ok:<24}{Fore.CYAN}║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║{Style.RESET_ALL}  Completed: {Fore.GREEN}{completed:<24}{Fore.CYAN}║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║{Style.RESET_ALL}  Failed:    {Fore.RED}{failed:<24}{Fore.CYAN}║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}╚══════════════════════════════════════╝{Style.RESET_ALL}\n")


def _print_current_settings():
    """Вывести текущие настройки из cfg_base."""
    print(f"\n  {Fore.CYAN}╔══════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║  ⚙️  Настройки (cfg_base.py)         ║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}╠══════════════════════════════════════╣{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║{Style.RESET_ALL}  Потоки:        {Fore.WHITE}{NUM_THREADS:<20}{Fore.CYAN}║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║{Style.RESET_ALL}  Ретраи:        {Fore.WHITE}{RETRY_COUNT:<20}{Fore.CYAN}║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║{Style.RESET_ALL}  Задержка (дей):{Fore.WHITE} {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}с{'':<15}{Fore.CYAN}║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}║{Style.RESET_ALL}  Задержка (акк):{Fore.WHITE} {DELAY_BETWEEN_ACCOUNTS[0]}-{DELAY_BETWEEN_ACCOUNTS[1]}с{'':<15}{Fore.CYAN}║{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}╚══════════════════════════════════════╝{Style.RESET_ALL}\n")


def _ask_run_params() -> dict:
    """Запросить параметры запуска: потоки, ретраи, задержки."""
    _print_current_settings()

    params = {}

    # Потоки
    try:
        raw = input(
            f"  {Fore.WHITE}Потоки [{NUM_THREADS}]: {Style.RESET_ALL}"
        ).strip()
        params["max_workers"] = int(raw) if raw else NUM_THREADS
    except ValueError:
        params["max_workers"] = NUM_THREADS

    # Ретраи
    try:
        raw = input(
            f"  {Fore.WHITE}Ретраи [{RETRY_COUNT}]: {Style.RESET_ALL}"
        ).strip()
        params["retry_count"] = int(raw) if raw else RETRY_COUNT
    except ValueError:
        params["retry_count"] = RETRY_COUNT

    # Задержка между действиями
    try:
        raw = input(
            f"  {Fore.WHITE}Задержка между действиями (сек) [{SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}]: {Style.RESET_ALL}"
        ).strip()
        if raw:
            parts = [x.strip() for x in raw.replace("-", ",").replace(" ", ",").split(",") if x.strip()]
            if len(parts) == 2:
                params["sleep_between_actions"] = [float(parts[0]), float(parts[1])]
            elif len(parts) == 1:
                val = float(parts[0])
                params["sleep_between_actions"] = [val, val]
            else:
                params["sleep_between_actions"] = SLEEP_BETWEEN_ACTIONS
        else:
            params["sleep_between_actions"] = SLEEP_BETWEEN_ACTIONS
    except (ValueError, IndexError):
        params["sleep_between_actions"] = SLEEP_BETWEEN_ACTIONS

    # Задержка между аккаунтами
    try:
        raw = input(
            f"  {Fore.WHITE}Задержка между аккаунтами (сек) [{DELAY_BETWEEN_ACCOUNTS[0]}-{DELAY_BETWEEN_ACCOUNTS[1]}]: {Style.RESET_ALL}"
        ).strip()
        if raw:
            parts = [x.strip() for x in raw.replace("-", ",").replace(" ", ",").split(",") if x.strip()]
            if len(parts) == 2:
                params["delay_between_accounts"] = [float(parts[0]), float(parts[1])]
            elif len(parts) == 1:
                val = float(parts[0])
                params["delay_between_accounts"] = [val, val]
            else:
                params["delay_between_accounts"] = DELAY_BETWEEN_ACCOUNTS
        else:
            params["delay_between_accounts"] = DELAY_BETWEEN_ACCOUNTS
    except (ValueError, IndexError):
        params["delay_between_accounts"] = DELAY_BETWEEN_ACCOUNTS

    print(
        f"\n  {Fore.GREEN}→ Потоки: {params['max_workers']}, "
        f"Ретраи: {params['retry_count']}, "
        f"Задержка дей: {params['sleep_between_actions'][0]}-{params['sleep_between_actions'][1]}с, "
        f"Задержка акк: {params['delay_between_accounts'][0]}-{params['delay_between_accounts'][1]}с"
        f"{Style.RESET_ALL}\n"
    )
    return params


def _handle_start():
    """Обработка запуска: проверка БД, создание задач, запуск."""
    is_empty = db.is_database_empty()

    if not is_empty:
        _print_task_summary()

        action = select(
            "База данных не пуста. Что делать?",
            choices=[
                Choice("▶️  Продолжить работу по текущим задачам", "continue"),
                Choice("🗑️  Очистить БД и пересоздать задачи из CSV", "recreate"),
                Choice("🔙 Назад", "back"),
            ],
            qmark="🔮",
            pointer="👉",
        ).ask()

        if action == "back" or action is None:
            return

        if action == "recreate":
            if not confirm("Вы уверены? Все текущие результаты будут удалены.").ask():
                return
            db.clear_database()
            log_simple("База данных очищена", "info")
            count = create_tasks_from_csv()
            if count == 0:
                log_simple("Нет данных для создания задач", "error")
                return
            log_simple(f"Создано {count} задач из CSV", "success")
    else:
        count = create_tasks_from_csv()
        if count == 0:
            log_simple("Нет данных в data.csv для создания задач", "error")
            return
        log_simple(f"Создано {count} задач из CSV", "success")

    _print_task_summary()
    params = _ask_run_params()
    run_discord_connect(
        max_workers=params["max_workers"],
        retry_count=params["retry_count"],
        sleep_between_actions=params["sleep_between_actions"],
        delay_between_accounts=params["delay_between_accounts"],
    )


def _handle_export():
    """Экспорт результатов в Excel."""
    if db.is_database_empty():
        log_simple("База данных пуста, нечего экспортировать", "warning")
        return

    _print_task_summary()
    path = export_results_xlsx()
    if path:
        print(f"\n  {Fore.GREEN}📁 Файл сохранён: {path}{Style.RESET_ALL}\n")


def discord_connect_menu():
    """Главное меню модуля Pharos Discord Connect."""
    print(f"\n  {Fore.CYAN}{'═' * 50}{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}  🔗 Pharos Discord Connect{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}  Авторизация + привязка Discord{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'═' * 50}{Style.RESET_ALL}")

    while True:
        action = select(
            "🔗 Pharos Discord — выберите действие:",
            choices=[
                Choice("▶️  Запуск привязки Discord       🌟 Авторизация + Discord OAuth", "start"),
                Choice("📊 Статус задач                   🌟 Сводка по текущим задачам", "status"),
                Choice("📥 Выгрузка результатов в Excel   🌟 Экспорт в result/pharos_discord/", "export"),
                Choice("🗑️  Очистить БД                    🌟 Удалить все задачи", "clear"),
                Choice("🔙 Назад", "back"),
            ],
            qmark="🔗",
            pointer="👉",
        ).ask()

        if action is None or action == "back":
            return

        match action:
            case "start":
                _handle_start()

            case "status":
                _print_task_summary()

            case "export":
                _handle_export()

            case "clear":
                if db.is_database_empty():
                    log_simple("База данных уже пуста", "info")
                    continue
                _print_task_summary()
                if confirm("Очистить базу данных? Все результаты будут удалены.").ask():
                    db.clear_database()
                    log_simple("База данных очищена", "success")
