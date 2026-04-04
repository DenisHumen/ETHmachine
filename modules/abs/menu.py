"""Abstract Portal — меню интеграции с ETHmachine."""
import asyncio

from colorama import Fore, Style
from questionary import Choice, select
from eth_account import Account

from config.modules.cfg_base import NUM_THREADS, DELAY_BETWEEN_ACCOUNTS, SLEEP_BETWEEN_ACTIONS
from config.menu_config import SubMenu, MenuItem, build_submenu_choices
from modules.abs import database as db
from modules.abs import abs_logger as logger
from modules.abs.worker import run_stats
from modules.abs.excel_export import export_stats

from modules.data_manager import load_data


# ---------------------------------------------------------------
# Подменю Abstract Portal
# ---------------------------------------------------------------

ABS_MENU = SubMenu(
    key='abs_portal',
    label='Abstract Portal',
    description='Stats, Badges, XP Recap',
    icon='🟢',
    qmark='🟢',
    pointer='👉',
    items=[
        MenuItem(key='stats', label='Check Stats', description='Сбор статистики (профиль, бейджи, XP)', icon='📊'),
        MenuItem(key='resume', label='Resume', description='Продолжить незавершённые кошельки', icon='▶️'),
        MenuItem(key='export', label='Export XLSX', description='Экспорт всех данных в Excel', icon='📄'),
        MenuItem(key='db_info', label='Database Info', description='Показать состояние базы данных', icon='🗄️'),
        MenuItem(key='reset', label='Reset & Start Over', description='Очистить задачи и начать заново', icon='🔄'),
        MenuItem(key='back', label='Назад', description='', icon='🔙'),
    ]
)


# ---------------------------------------------------------------
# Загрузка кошельков
# ---------------------------------------------------------------

def load_wallets() -> list[dict]:
    """Загрузить кошельки из data.csv."""
    rows = load_data()
    if not rows:
        return []

    wallets = []
    for i, row in enumerate(rows):
        pk = row.get('private_key', '').strip()
        if not pk:
            continue
        if not pk.startswith("0x"):
            pk = "0x" + pk
        try:
            account = Account.from_key(pk)
            wallets.append({
                "private_key": pk,
                "address": account.address,
                "account_name": row.get('name', '').strip() or None,
                "proxy": row.get('proxy', '').strip() or None,
                "reserve_proxy": row.get('reserve_proxy', '').strip() or None,
            })
        except Exception as e:
            logger.log(f"Ошибка ключа #{i + 1}: {e}", "error")
    return wallets


# ---------------------------------------------------------------
# Инициализация БД
# ---------------------------------------------------------------

def _ensure_db() -> bool:
    """Инициализация/синхронизация БД из data.csv."""
    wallets = load_wallets()
    if not wallets:
        logger.log("Нет данных в data.csv! Добавьте приватные ключи", "error")
        return False

    total = db.ensure_wallets(wallets)
    logger.log(f"БД синхронизирована: {total} кошельков", "info")
    return True


# ---------------------------------------------------------------
# Вспомогательные
# ---------------------------------------------------------------

def _ask_workers() -> int:
    """Запросить кол-во потоков."""
    try:
        raw = input(
            f"  {Fore.WHITE}Макс. параллельных кошельков [{NUM_THREADS}]: {Style.RESET_ALL}"
        ).strip()
        return int(raw) if raw else NUM_THREADS
    except ValueError:
        return NUM_THREADS


def _show_menu(title: str, choices: list, qmark: str = '🟢', pointer: str = '👉'):
    """Показать меню."""
    return select(title, choices=choices, qmark=qmark, pointer=pointer).ask()


def _show_db_info():
    """Показать информацию о БД."""
    stats = db.get_db_stats()
    print(f"\n{Fore.GREEN}{'=' * 55}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Abstract Portal Database Info{Style.RESET_ALL}")
    print(f"  {Fore.GREEN}{'─' * 55}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Всего кошельков:      {Fore.GREEN}{stats['total_wallets']}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Авторизовано:         {Fore.GREEN}{stats['logged_in']}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Статистика собрана:   {Fore.GREEN}{stats['with_stats']}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Уникальных бейджей:   {Fore.GREEN}{stats['unique_badges']}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Бейджей заклеймлено:  {Fore.GREEN}{stats['claimed_badges']}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Общий XP:             {Fore.GREEN}{stats['total_xp']}{Style.RESET_ALL}")
    print(f"  {Fore.GREEN}{'=' * 55}{Style.RESET_ALL}\n")
    input(f"  {Fore.WHITE}Нажмите Enter...{Style.RESET_ALL}")


def _show_stats_table(results: list[dict]):
    """Вывести таблицу результатов."""
    print(f"\n{Fore.GREEN}{'=' * 78}{Style.RESET_ALL}")
    print(
        f"  {Fore.WHITE}{'Address':<44} {'Rank':<15} {'XP':>8} "
        f"{'Badges':>8}{Style.RESET_ALL}"
    )
    print(f"  {Fore.GREEN}{'=' * 78}{Style.RESET_ALL}")

    for r in results:
        if not r.get("success"):
            print(
                f"  {Fore.RED}{r.get('address', '?'):<44} "
                f"{'ERROR':<15} {'-':>8} {'-':>8}{Style.RESET_ALL}"
            )
            continue

        profile = r.get("profile", {})
        tier_name = r.get("tier_name", "?")
        total_xp = profile.get("totalExperiencePoints", 0)

        badges = r.get("badges", [])
        claimed = sum(1 for b in badges if b.get("claimed"))
        badge_str = f"{claimed}/{len(badges)}"

        # Color based on tier
        tier_lower = tier_name.lower()
        if "diamond" in tier_lower:
            color = Fore.CYAN
        elif "gold" in tier_lower:
            color = Fore.YELLOW
        elif "silver" in tier_lower:
            color = Fore.WHITE
        else:
            color = Fore.LIGHTBLACK_EX

        print(
            f"  {Fore.WHITE}{r['address']:<44} "
            f"{color}{tier_name:<15} "
            f"{Fore.GREEN}{total_xp:>8} "
            f"{Fore.CYAN}{badge_str:>8}{Style.RESET_ALL}"
        )

    print(f"  {Fore.GREEN}{'=' * 78}{Style.RESET_ALL}")


# ---------------------------------------------------------------
# Главное меню Abstract Portal
# ---------------------------------------------------------------

def abs_menu():
    """Главное меню Abstract Portal — вызывается из projects_menu ETHmachine."""
    logger.banner()

    while True:
        action = _show_menu(
            "Abstract Portal — выберите действие:",
            build_submenu_choices(ABS_MENU),
            qmark=ABS_MENU.qmark,
            pointer=ABS_MENU.pointer,
        )

        if action is None or action == 'back':
            return

        # Инициализация БД перед действиями
        if action not in ('export', 'db_info'):
            if not _ensure_db():
                continue

        match action:
            case 'stats':
                print(f"\n{Fore.GREEN}╔══════════════════════════════════════════════════╗")
                print(f"║{Fore.WHITE}       ABSTRACT PORTAL — CHECK STATS              {Fore.GREEN}║")
                print(f"╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")
                print(f"  {Fore.WHITE}Режим: Сбор статистики (профиль, бейджи, XP)")
                print(f"  Потоки: {NUM_THREADS} | Задержка: {DELAY_BETWEEN_ACCOUNTS}с{Style.RESET_ALL}\n")

                workers = _ask_workers()
                try:
                    results = asyncio.run(run_stats(workers))
                    if results:
                        _show_stats_table(results)
                        # Автоэкспорт
                        filepath = export_stats()
                        if filepath:
                            print(f"\n  {Fore.GREEN}Результаты: {filepath}{Style.RESET_ALL}")
                except KeyboardInterrupt:
                    logger.log("Сбор статистики остановлен (Ctrl+C)", "warning")

            case 'resume':
                print(f"\n{Fore.GREEN}╔══════════════════════════════════════════════════╗")
                print(f"║{Fore.WHITE}       ABSTRACT PORTAL — RESUME                   {Fore.GREEN}║")
                print(f"╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")
                print(f"  {Fore.WHITE}Продолжаем только незавершённые кошельки{Style.RESET_ALL}\n")

                workers = _ask_workers()
                try:
                    results = asyncio.run(run_stats(workers, resume=True))
                    if results:
                        _show_stats_table(results)
                        filepath = export_stats()
                        if filepath:
                            print(f"\n  {Fore.GREEN}Результаты: {filepath}{Style.RESET_ALL}")
                except KeyboardInterrupt:
                    logger.log("Продолжение остановлено (Ctrl+C)", "warning")

            case 'export':
                filepath = export_stats()
                if filepath:
                    print(f"\n  {Fore.GREEN}Экспорт сохранён: {filepath}{Style.RESET_ALL}")
                else:
                    print(f"\n  {Fore.RED}Нет данных для экспорта{Style.RESET_ALL}")

            case 'db_info':
                _show_db_info()

            case 'reset':
                confirm = input(
                    f"  {Fore.RED}Вы уверены? Все задачи будут очищены (y/N): {Style.RESET_ALL}"
                ).strip().lower()
                if confirm == 'y':
                    db.clear_all_tasks()
                    logger.log("Все задачи очищены. Можно начинать заново.", "success")
                else:
                    logger.log("Отменено", "info")
