"""xStocks DeFi Points — меню интеграции с ETHmachine."""
import asyncio

from colorama import Fore, Style
from questionary import select
from eth_account import Account

from config.modules.cfg_xstocks import GM_COOLDOWN_HOURS
from config.modules.general_config import NUM_THREADS, DELAY_BETWEEN_ACCOUNTS
from config.menu_config import SubMenu, MenuItem, build_submenu_choices
from modules.xstocks import database as db
from modules.xstocks import xstocks_logger as logger
from modules.xstocks.worker import (
    run_registration, run_connect_sol, run_gm_once,
    run_gm_loop, run_stats, run_full_auto,
)
from modules.xstocks.excel_export import export_results

from modules.data_manager import load_data


# ---------------------------------------------------------------
# Подменю xStocks
# ---------------------------------------------------------------

XSTOCKS_MENU = SubMenu(
    key='xstocks',
    label='xStocks DeFi Points',
    description='Register, GM, Referrals, Stats',
    icon='📈',
    qmark='📈',
    pointer='👉',
    items=[
        # Основные действия
        MenuItem(key='full_auto', label='Full Auto', description='Регистрация + Solana + бесконечный GM', icon='♾️'),
        MenuItem(key='register', label='Register', description='Регистрация EVM кошельков', icon='✅'),
        MenuItem(key='connect_sol', label='Connect Solana', description='Подключить Solana кошельки', icon='☀️'),
        MenuItem(key='gm_once', label='Say GM (однократно)', description='Say GM для всех готовых', icon='🌅'),
        MenuItem(key='gm_loop', label='Say GM (бесконечный цикл)', description='Автоматический GM каждые 14ч', icon='🔄'),
        # Данные
        MenuItem(key='stats', label='Статистика', description='Сбор и вывод статистики', icon='📊'),
        MenuItem(key='export', label='Экспорт в XLSX', description='Экспорт всех данных в Excel', icon='📄'),
        MenuItem(key='db_info', label='Информация о БД', description='Показать состояние базы данных', icon='🗄️'),
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
                "sol_private_key": row.get('sol_private_key', '').strip() or None,
                "sol_address": row.get('sol_address', '').strip() or None,
                "referral_code": row.get('referral_code', '').strip() or None,
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


def _show_menu(title: str, choices: list, qmark: str = '📈', pointer: str = '👉'):
    """Показать меню."""
    return select(title, choices=choices, qmark=qmark, pointer=pointer).ask()


def _show_db_info():
    """Показать информацию о БД."""
    stats = db.get_db_stats()
    print(f"\n{Fore.CYAN}{'=' * 50}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}xStocks Database Info{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'─' * 50}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Всего кошельков:      {Fore.GREEN}{stats['total_wallets']}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}EVM зарегистрировано: {Fore.GREEN}{stats['evm_registered']}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}SOL подключено:       {Fore.GREEN}{stats['sol_connected']}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Всего GM:             {Fore.GREEN}{stats['total_gm']}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Реферальных кодов:    {Fore.GREEN}{stats['referral_codes']}{Style.RESET_ALL}")

    next_gm = db.get_next_gm_time()
    if next_gm:
        print(f"  {Fore.WHITE}Ближайший GM:         {Fore.YELLOW}{next_gm[:16]}{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}{'=' * 50}{Style.RESET_ALL}\n")
    input(f"  {Fore.WHITE}Нажмите Enter...{Style.RESET_ALL}")


# ---------------------------------------------------------------
# Главное меню xStocks
# ---------------------------------------------------------------

def xstocks_menu():
    """Главное меню xStocks — вызывается из projects_menu ETHmachine."""
    logger.banner()

    while True:
        action = _show_menu(
            "xStocks DeFi Points — выберите действие:",
            build_submenu_choices(XSTOCKS_MENU),
            qmark=XSTOCKS_MENU.qmark,
            pointer=XSTOCKS_MENU.pointer,
        )

        if action is None or action == 'back':
            return

        # Инициализация БД перед действиями
        if action not in ('export', 'db_info'):
            if not _ensure_db():
                continue

        match action:
            case 'full_auto':
                print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════╗")
                print(f"║{Fore.WHITE}       xStocks FULL AUTO MODE                     {Fore.CYAN}║")
                print(f"╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")
                print(f"  {Fore.WHITE}Режим: Регистрация -> Solana -> GM бесконечный цикл")
                print(f"  GM кулдаун: {GM_COOLDOWN_HOURS}ч")
                print(f"  Потоки: {NUM_THREADS} | Задержка: {DELAY_BETWEEN_ACCOUNTS}с")
                print(f"  Для остановки нажмите Ctrl+C{Style.RESET_ALL}\n")

                workers = _ask_workers()
                try:
                    asyncio.run(run_full_auto(workers))
                except KeyboardInterrupt:
                    logger.log("Авто-режим остановлен (Ctrl+C). Прогресс сохранён в БД.", "warning")

            case 'register':
                workers = _ask_workers()
                print(f"  [DIAG] asyncio.run(run_registration({workers})) — СТАРТ", flush=True)
                try:
                    results = asyncio.run(run_registration(workers))
                except BaseException as e:
                    print(f"  [DIAG] asyncio.run() вызвал {type(e).__name__}: {e}", flush=True)
                    results = []
                print(f"  [DIAG] asyncio.run() — ФИНИШ, результатов: {len(results)}", flush=True)
                if results:
                    filepath = export_results()
                    if filepath:
                        print(f"\n  {Fore.GREEN}Результаты: {filepath}{Style.RESET_ALL}")

            case 'connect_sol':
                workers = _ask_workers()
                asyncio.run(run_connect_sol(workers))

            case 'gm_once':
                workers = _ask_workers()
                asyncio.run(run_gm_once(workers))

            case 'gm_loop':
                print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════╗")
                print(f"║{Fore.WHITE}       xStocks GM LOOP (бесконечный)              {Fore.CYAN}║")
                print(f"╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")
                print(f"  {Fore.WHITE}GM каждые ~{GM_COOLDOWN_HOURS}ч для каждого кошелька")
                print(f"  Для остановки нажмите Ctrl+C{Style.RESET_ALL}\n")

                workers = _ask_workers()
                try:
                    asyncio.run(run_gm_loop(workers))
                except KeyboardInterrupt:
                    logger.log("GM цикл остановлен (Ctrl+C). Прогресс сохранён в БД.", "warning")

            case 'stats':
                workers = _ask_workers()
                results = asyncio.run(run_stats(workers))
                if results:
                    # Вывести таблицу
                    print(f"\n{Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")
                    print(f"  {Fore.WHITE}{'Address':<44} {'xBoost':>7} {'Refs':>5} {'Points':>7}{Style.RESET_ALL}")
                    print(f"  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")
                    for r in results:
                        s = r.get("stats", {})
                        xboost = s.get('xboost_multiplier') or s.get('xboost', '?')
                        points = s.get('total_points') or s.get('today_points', 0)
                        print(
                            f"  {Fore.WHITE}{r['address']:<44} "
                            f"{Fore.GREEN}{'x' + str(xboost):>7} "
                            f"{Fore.YELLOW}{s.get('referrals_count', 0):>5} "
                            f"{Fore.CYAN}{points:>7}{Style.RESET_ALL}"
                        )
                    print(f"  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")

            case 'export':
                filepath = export_results()
                if filepath:
                    print(f"\n  {Fore.GREEN}Экспорт сохранён: {filepath}{Style.RESET_ALL}")
                else:
                    print(f"\n  {Fore.RED}Нет данных для экспорта{Style.RESET_ALL}")

            case 'db_info':
                _show_db_info()
