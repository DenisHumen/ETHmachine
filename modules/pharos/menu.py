"""Pharos Testnet Faucet & Quest Bot — меню интеграции с ETHmachine."""
import asyncio

from colorama import Fore, Style
from questionary import Choice, select
from eth_account import Account

from config.modules.cfg_pharos import (
    DELAY_BETWEEN_CYCLES, DELAY_BETWEEN_CYCLES_CHECKIN,
    SEND_AMOUNT, SEND_REPEATS, VERIFY_TASK_IDS_AUTO,
    STRETCH_HOURS,
)
from config.modules.cfg_base import NUM_THREADS, DELAY_BETWEEN_ACCOUNTS, SLEEP_BETWEEN_ACTIONS
from config.menu_config import SubMenu, MenuItem, build_submenu_choices
from modules.pharos import database as db
from modules.pharos import pharos_logger as logger
from modules.pharos.worker import run_parallel, run_loop, run_stretched, run_stretched_loop
from modules.pharos.stats import collect_stats, export_csv
from modules.pharos.excel_export import export_send_verify_results, export_cycle_results, export_wallet_stats_xlsx

from modules.data_manager import load_data


# ═══════════════════════════════════════════════════════════
# Подменю Pharos (стиль как у главного меню)
# ═══════════════════════════════════════════════════════════

PHAROS_MENU = SubMenu(
    key='pharos',
    label='Pharos Testnet',
    description='Квесты, Send & Verify',
    icon='🔮',
    qmark='🔮',
    pointer='👉',
    items=[
        # Однократные действия
        MenuItem(key='checkin', label='Check-in', description='Ежедневный чек-ин', icon='✅'),
        MenuItem(key='faucet', label='Краны (Pharos + FaroSwap)', description='Клейм тестовых токенов', icon='🚰'),
        MenuItem(key='all_faucet', label='Faucet + Check-in', description='Всё вместе', icon='🔥'),
        MenuItem(key='quests', label='Квесты', description='Верификация квестов', icon='🎯'),
        MenuItem(key='send_verify', label='Send & Verify', description='Send PHRS + Verify task (быстрый)', icon='🚀'),
        # Циклы
        MenuItem(key='loop_checkin', label='Check-in (цикл 24ч)', description='Автоматический чек-ин', icon='🔄'),
        MenuItem(key='loop_faucet', label='Краны (цикл)', description='Автоматические краны', icon='🔄'),
        MenuItem(key='loop_all_faucet', label='Faucet + Check-in (цикл)', description='Всё в цикле', icon='🔄'),
        MenuItem(key='loop_quests', label='Квесты (цикл)', description='Автоматические квесты', icon='🔄'),
        # Авто-фарм 25ч
        MenuItem(key='auto_farm', label='Авто-фарм (25ч цикл)', description='Send + Verify растяжка на 25ч, бесконечный цикл', icon='♾️'),
        # Привязки
        MenuItem(key='discord_connect', label='Discord Connect', description='Авторизация + привязка Discord', icon='🔗'),
        # Дополнительно
        MenuItem(key='stats', label='Статистика', description='Сбор и вывод статистики (обновляет БД)', icon='📊'),
        MenuItem(key='export_stats', label='Экспорт в XLSX', description='Экспорт статистики из БД в Excel', icon='📄'),
        MenuItem(key='export_results', label='Экспорт цикла', description='Экспорт завершённого цикла в XLSX', icon='📋'),
        MenuItem(key='back', label='Назад', description='', icon='🔙'),
    ]
)


# ═══════════════════════════════════════════════════════════
# Автоматическая инициализация БД
# ═══════════════════════════════════════════════════════════

def _ensure_db() -> bool:
    """Автоматическая инициализация/синхронизация БД из data.csv.
    Вызывается перед каждой операцией. Возвращает True если есть кошельки."""
    wallets = load_wallets()
    if not wallets:
        logger.log("Нет данных в data.csv! Добавьте приватные ключи в data/data.csv", "error")
        return False

    total = db.ensure_wallets(wallets)
    logger.log(f"БД синхронизирована: {total} кошельков", "info")
    return True


def load_wallets() -> list[dict]:
    """Загрузить кошельки и прокси из data.csv."""
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
            proxy = row.get('proxy', '').strip() or None
            account_name = row.get('name', '').strip() or None
            wallets.append({"private_key": pk, "address": account.address,
                            "account_name": account_name, "proxy": proxy})
        except Exception as e:
            logger.log(f"Ошибка ключа #{i + 1}: {e}", "error")
    return wallets


# ═══════════════════════════════════════════════════════════
# Вспомогательные функции
# ═══════════════════════════════════════════════════════════

def _ask_workers() -> int:
    """Запросить кол-во потоков."""
    try:
        raw = input(
            f"  {Fore.WHITE}Макс. параллельных кошельков [{NUM_THREADS}]: {Style.RESET_ALL}"
        ).strip()
        return int(raw) if raw else NUM_THREADS
    except ValueError:
        return NUM_THREADS


def _ask_cycle_params() -> tuple[tuple, int]:
    """Запросить параметры цикла."""
    print(f"\n{Fore.CYAN}Настройка цикла:{Style.RESET_ALL}")
    try:
        raw = input(
            f"  {Fore.WHITE}Задержка между циклами (час) "
            f"[{DELAY_BETWEEN_CYCLES[0] // 3600}-{DELAY_BETWEEN_CYCLES[1] // 3600}]: {Style.RESET_ALL}"
        ).strip()
        if raw:
            parts = [x.strip() for x in raw.replace("-", ",").replace(" ", ",").split(",") if x.strip()]
            if len(parts) == 2:
                cycle_delay = (float(parts[0]) * 3600, float(parts[1]) * 3600)
            elif len(parts) == 1:
                val = float(parts[0]) * 3600
                cycle_delay = (val, val)
            else:
                cycle_delay = DELAY_BETWEEN_CYCLES
        else:
            cycle_delay = DELAY_BETWEEN_CYCLES
    except (ValueError, IndexError):
        cycle_delay = DELAY_BETWEEN_CYCLES

    workers = _ask_workers()
    h_min = cycle_delay[0] / 3600
    h_max = cycle_delay[1] / 3600
    print(f"  {Fore.GREEN}-> Задержка: {h_min:.1f}-{h_max:.1f} ч, Потоки: {workers}{Style.RESET_ALL}")
    return cycle_delay, workers


def _show_menu(title: str, choices: list, qmark: str = '🔮', pointer: str = '👉'):
    """Показать меню."""
    return select(title, choices=choices, qmark=qmark, pointer=pointer).ask()


# ═══════════════════════════════════════════════════════════
# Обработчики меню
# ═══════════════════════════════════════════════════════════

def _menu_send_verify():
    """Send & Verify (быстрый) — берёт задержки и потоки из cfg_base."""
    print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════╗")
    print(f"║{Fore.WHITE}       SEND & VERIFY — быстрый режим              {Fore.CYAN}║")
    print(f"╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Сумма: {SEND_AMOUNT} PHRS x {SEND_REPEATS} повтор(ов)")
    print(f"  Tasks: {VERIFY_TASK_IDS_AUTO}")
    print(f"  Потоки: {NUM_THREADS} | Задержка между аккаунтами: {DELAY_BETWEEN_ACCOUNTS}с")
    print(f"  Задержка между действиями: {SLEEP_BETWEEN_ACTIONS}с{Style.RESET_ALL}\n")

    workers = _ask_workers()
    sv_results = asyncio.run(run_parallel("send_verify", workers))

    if sv_results:
        filepath = export_send_verify_results(sv_results)
        if filepath:
            print(f"\n  {Fore.GREEN}Результаты: {filepath}{Style.RESET_ALL}")


def _menu_auto_farm():
    """Авто-фарм (25ч цикл) — бесконечный stretch-цикл."""
    print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════╗")
    print(f"║{Fore.WHITE}       АВТО-ФАРМ — бесконечный цикл              {Fore.CYAN}║")
    print(f"╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Режим: Send + Verify")
    print(f"  Растяжка: {STRETCH_HOURS}ч (равномерное распределение)")
    print(f"  После завершения цикла — автоматический перезапуск")
    print(f"  При остановке — прогресс сохраняется, продолжит с того же места{Style.RESET_ALL}\n")

    try:
        raw = input(
            f"  {Fore.WHITE}Растяжка (часов) [{STRETCH_HOURS}]: {Style.RESET_ALL}"
        ).strip()
        hours = float(raw) if raw else STRETCH_HOURS
    except ValueError:
        hours = STRETCH_HOURS

    workers = _ask_workers()

    print(f"\n  {Fore.GREEN}-> Stretch: {hours}ч | {workers} поток(ов){Style.RESET_ALL}")
    print(f"  {Fore.CYAN}Для остановки нажмите Ctrl+C{Style.RESET_ALL}\n")

    try:
        asyncio.run(run_stretched_loop("send_verify", hours, workers))
    except KeyboardInterrupt:
        logger.log("Авто-фарм остановлен (Ctrl+C). Прогресс сохранён в БД.", "warning")


def _menu_stats():
    """Статистика — сбор XP, Level, квестов и сохранение в БД."""
    wallets = load_wallets()
    if not wallets:
        logger.log("Нет кошельков. Добавьте приватные ключи в data/data.csv", "error")
        return

    workers = _ask_workers()
    stats = asyncio.run(collect_stats(wallets, workers))
    if stats:
        export_csv(stats)
        print(f"\n{Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")
        print(f"  {Fore.WHITE}{'address':<44} {'xp':>8}  {'lvl':<5}  {'quests'}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")
        for s in stats:
            qd = s.get('quests_done', 0)
            qt = s.get('quests_total', 0)
            q_color = Fore.GREEN if qd == qt else Fore.YELLOW
            print(
                f"  {Fore.WHITE}{s['address']:<44} {s['xp']:>8}  "
                f"{Fore.GREEN}{s['lvl']:<5}  "
                f"{q_color}{qd}/{qt}{Style.RESET_ALL}"
            )
        print(f"  {Fore.CYAN}{'=' * 70}{Style.RESET_ALL}")
        print(f"\n  {Fore.GREEN}Данные сохранены в БД. Используйте 'Экспорт в XLSX' для экспорта.{Style.RESET_ALL}")
    else:
        logger.log("Не удалось собрать статистику", "error")


def _menu_export_stats():
    """Экспорт статистики из БД в XLSX."""
    filepath = export_wallet_stats_xlsx()
    if filepath:
        print(f"\n  {Fore.GREEN}Экспорт: {filepath}{Style.RESET_ALL}")


def _menu_export_results():
    """Экспорт результатов завершённого цикла из БД."""
    tables = db.list_results_tables()
    if not tables:
        logger.log("Нет завершённых циклов для экспорта", "warning")
        return

    choices = []
    for t in tables:
        label = (
            f"{t['started_at'][:16]} | {t['mode']} | "
            f"#{t['cycle_number']} | {t['successful']}/{t['total_wallets']}"
        )
        if t.get('stretch_hours'):
            label += f" | stretch {t['stretch_hours']}h"
        choices.append(Choice(label, t['results_table']))
    choices.append(Choice(f'🔙 Назад', 'back'))

    selected = _show_menu("Выберите цикл для экспорта:", choices)
    if selected and selected != 'back':
        filepath = export_cycle_results(selected)
        if filepath:
            print(f"\n  {Fore.GREEN}Экспорт: {filepath}{Style.RESET_ALL}")


# ═══════════════════════════════════════════════════════════
# Главное меню Pharos
# ═══════════════════════════════════════════════════════════

def pharos_menu():
    """Главное меню Pharos — вызывается из projects_menu ETHmachine."""
    logger.banner()

    while True:
        action = _show_menu(
            "Pharos Testnet — выберите действие:",
            build_submenu_choices(PHAROS_MENU),
            qmark=PHAROS_MENU.qmark,
            pointer=PHAROS_MENU.pointer,
        )

        if action is None or action == 'back':
            return

        # Автоматическая инициализация БД перед любым действием
        if action not in ('stats', 'export_stats', 'export_results', 'discord_connect'):
            if not _ensure_db():
                continue

        match action:
            # ОДНОКРАТНО
            case 'checkin':
                workers = _ask_workers()
                asyncio.run(run_parallel("checkin", workers))

            case 'faucet':
                workers = _ask_workers()
                asyncio.run(run_parallel("faucet", workers))

            case 'all_faucet':
                workers = _ask_workers()
                asyncio.run(run_parallel("all_faucet", workers))

            case 'quests':
                workers = _ask_workers()
                asyncio.run(run_parallel("quests", workers))

            case 'send_verify':
                _menu_send_verify()

            # ЦИКЛЫ
            case 'loop_checkin':
                print(f"\n{Fore.CYAN}Настройка цикла Check-in:{Style.RESET_ALL}")
                try:
                    raw = input(
                        f"  {Fore.WHITE}Задержка между циклами (час) "
                        f"[{DELAY_BETWEEN_CYCLES_CHECKIN[0] // 3600}-{DELAY_BETWEEN_CYCLES_CHECKIN[1] // 3600}]: "
                        f"{Style.RESET_ALL}"
                    ).strip()
                    if raw:
                        parts = [x.strip() for x in raw.replace("-", ",").replace(" ", ",").split(",") if x.strip()]
                        if len(parts) == 2:
                            checkin_delay = (float(parts[0]) * 3600, float(parts[1]) * 3600)
                        elif len(parts) == 1:
                            val = float(parts[0]) * 3600
                            checkin_delay = (val, val)
                        else:
                            checkin_delay = DELAY_BETWEEN_CYCLES_CHECKIN
                    else:
                        checkin_delay = DELAY_BETWEEN_CYCLES_CHECKIN
                except (ValueError, IndexError):
                    checkin_delay = DELAY_BETWEEN_CYCLES_CHECKIN

                workers = _ask_workers()
                h_min = checkin_delay[0] / 3600
                h_max = checkin_delay[1] / 3600
                print(f"  {Fore.GREEN}-> Задержка: {h_min:.1f}-{h_max:.1f} ч, Потоки: {workers}{Style.RESET_ALL}")
                try:
                    asyncio.run(run_loop("checkin", checkin_delay, workers))
                except KeyboardInterrupt:
                    logger.log("Цикл остановлен (Ctrl+C)", "warning")

            case 'loop_faucet':
                cycle_delay, workers = _ask_cycle_params()
                try:
                    asyncio.run(run_loop("faucet", cycle_delay, workers))
                except KeyboardInterrupt:
                    logger.log("Цикл остановлен (Ctrl+C)", "warning")

            case 'loop_all_faucet':
                cycle_delay, workers = _ask_cycle_params()
                try:
                    asyncio.run(run_loop("all_faucet", cycle_delay, workers))
                except KeyboardInterrupt:
                    logger.log("Цикл остановлен (Ctrl+C)", "warning")

            case 'loop_quests':
                cycle_delay, workers = _ask_cycle_params()
                try:
                    asyncio.run(run_loop("quests", cycle_delay, workers))
                except KeyboardInterrupt:
                    logger.log("Цикл остановлен (Ctrl+C)", "warning")

            # АВТО-ФАРМ
            case 'auto_farm':
                _menu_auto_farm()

            # ПРИВЯЗКИ
            case 'discord_connect':
                from modules.pharos.discord_connect.menu import discord_connect_menu
                discord_connect_menu()

            # ДОПОЛНИТЕЛЬНО
            case 'stats':
                _menu_stats()

            case 'export_stats':
                _menu_export_stats()

            case 'export_results':
                _menu_export_results()
