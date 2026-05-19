"""UX-меню для SafePal X1 Eligibility Checker."""

from __future__ import annotations

from colorama import Fore, Style
from questionary import Choice, select

from config.modules.cfg_safepal_x1_checker import ACT_CODE, CHAIN_ID, CHANNEL_CODE
from modules.eth.safepal_x1_checker.checker import (
    export_results_xlsx,
    print_run_statistics,
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


def _show_db_stats() -> None:
    s = get_task_statistics()
    sep = f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}"
    print()
    print(sep)
    print(f"{Fore.CYAN}SAFEPAL X1 CHECKER — СТАТИСТИКА{Style.RESET_ALL}")
    print(f"{Fore.CYAN}DB:{Style.RESET_ALL} {DB_PATH}")
    print(f"{Fore.CYAN}actCode:{Style.RESET_ALL} {ACT_CODE}  "
          f"{Fore.CYAN}channelCode:{Style.RESET_ALL} {CHANNEL_CODE}  "
          f"{Fore.CYAN}chainId:{Style.RESET_ALL} {CHAIN_ID}")
    print(sep)
    if s["total"] == 0:
        print(f"  {Fore.YELLOW}Нет данных в БД{Style.RESET_ALL}")
        print(sep)
        return
    print(f"  Всего кошельков:    {s['total']}")
    print(f"  Проверено:          {Fore.GREEN}{s['completed']}{Style.RESET_ALL}")
    print(f"  Ожидают:            {Fore.YELLOW}{s['pending']}{Style.RESET_ALL}")
    print(f"  Ошибки:             {Fore.RED}{s['failed']}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'-' * 40}{Style.RESET_ALL}")
    print(f"  ✅ Eligible:         {Fore.GREEN}{s['eligible']}{Style.RESET_ALL}")
    print(f"  ❌ Not eligible:     {Fore.RED}{s['not_eligible']}{Style.RESET_ALL}")
    print(sep)
    print()


def _handle_start() -> None:
    init_database()
    total = get_total_tasks_count()
    if total > 0:
        if all_tasks_completed():
            print(f"\n{Fore.YELLOW}БД содержит {total} задач, все выполнены.{Style.RESET_ALL}")
            action = select(
                "Что делать?",
                choices=[
                    Choice("🗑️  Очистить БД и проверить заново", "reset"),
                    Choice("🔙 Назад", "back"),
                ],
                qmark="📊", pointer="👉",
            ).ask()
            if action in (None, "back"):
                return
            if action == "reset":
                deleted = reset_database()
                logger.success(f"Очищено {deleted} задач из БД")
        else:
            _show_db_stats()
            action = select(
                "Что делать с существующей БД?",
                choices=[
                    Choice("▶️  Продолжить (только pending/failed)", "continue"),
                    Choice("🗑️  Очистить и начать заново", "reset"),
                    Choice("🔙 Назад", "back"),
                ],
                qmark="📊", pointer="👉",
            ).ask()
            if action in (None, "back"):
                return
            if action == "reset":
                deleted = reset_database()
                logger.success(f"Очищено {deleted} задач из БД")

    try:
        run_checker()
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Сбой SafePal X1 checker: {exc}")


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
║   SafePal X1 — Eligibility Checker (Nansen и др. кампании)      ║
╚══════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}

Сайт:  https://www.safepal.com/en/claimX1/v2/#/v/{ACT_CODE}/{CHANNEL_CODE}

Чекер для каждого EVM-кошелька из {Fore.YELLOW}data/data.csv{Style.RESET_ALL}:
  1) POST checkChannelCode → channelName/sku
  2) POST getSignMsg → nonce + msg + serverTime
  3) personal_sign(msg) приватным ключом локально (eth_account)
  4) POST authSign → session_id
  5) POST activityShopingToken → token
  6) POST checkIsCanOrder → 'YES' / 'NO'

Адрес кошелька выводится из {Fore.YELLOW}private_key{Style.RESET_ALL} (поле wallet_address из CSV
игнорируется). Прокси берутся из {Fore.YELLOW}proxy{Style.RESET_ALL} → {Fore.YELLOW}reserve_proxy{Style.RESET_ALL} → direct.

Настройки в {Fore.YELLOW}config/modules/cfg_safepal_x1_checker.py{Style.RESET_ALL}:
  ACT_CODE        — код активности (часть URL после /v/)
  CHANNEL_CODE    — код канала
  CHAIN_ID        — chainId для подписи (по умолчанию 1 — Ethereum)
  HTTP_TIMEOUT    — таймаут запросов

Параллелизм и ретраи берутся из {Fore.YELLOW}config/modules/general_config.py{Style.RESET_ALL}:
  NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS.

Состояние:  {Fore.YELLOW}db/safepal_x1_checker.db{Style.RESET_ALL}
Excel:      {Fore.YELLOW}result/safepal_x1_checker/*.xlsx{Style.RESET_ALL}

Можно прервать (Ctrl+C) и продолжить позже — БД сохраняет прогресс.
"""
    print(text)


def safepal_x1_checker_menu() -> None:
    while True:
        action = select(
            "🟪 SafePal X1 Eligibility Checker:",
            choices=[
                Choice("▶️  Запуск чекера                    🌟 Проверка/продолжение по БД", "start"),
                Choice("📊 Статистика                        🌟 Что лежит в БД", "stats"),
                Choice("📥 Экспорт в Excel                   🌟 result/safepal_x1_checker/", "export"),
                Choice("🗑️  Очистка БД                       🌟 Сброс всех задач", "clear_db"),
                Choice("📖 Информация                        🌟 Описание модуля", "info"),
                Choice("🔙 Назад", "back"),
            ],
            qmark="🟪", pointer="👉",
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


run_safepal_x1_checker = safepal_x1_checker_menu
