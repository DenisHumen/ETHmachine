"""Pharos Testnet Faucet & Quest Bot — меню интеграции с ETHmachine."""
import asyncio
import os
import sys

from colorama import Fore, Style
from eth_account import Account

from config.modules.cfg_pharos import (
    DELAY_BETWEEN_CYCLES, DELAY_BETWEEN_CYCLES_CHECKIN,
)
from config.modules.cfg_base import NUM_THREADS
from modules.pharos import database as db
from modules.pharos import pharos_logger as logger
from modules.pharos.worker import run_parallel, run_loop
from modules.pharos.stats import collect_stats, export_csv

from modules.data_manager import load_data


def load_wallets() -> list[dict]:
    """Загрузить кошельки и прокси из data.csv."""
    rows = load_data()

    if not rows:
        logger.log("Нет данных в data.csv!", "error")
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
            wallets.append({"private_key": pk, "address": account.address, "proxy": proxy})
        except Exception as e:
            logger.log(f"Ошибка ключа #{i + 1}: {e}", "error")
    return wallets


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
            f"  {Fore.WHITE}Задержка между циклами (мин) "
            f"[{DELAY_BETWEEN_CYCLES[0] // 60}-{DELAY_BETWEEN_CYCLES[1] // 60}]: {Style.RESET_ALL}"
        ).strip()
        if raw:
            parts = [x.strip() for x in raw.replace("-", ",").replace(" ", ",").split(",") if x.strip()]
            if len(parts) == 2:
                cycle_delay = (float(parts[0]) * 60, float(parts[1]) * 60)
            elif len(parts) == 1:
                val = float(parts[0]) * 60
                cycle_delay = (val, val)
            else:
                cycle_delay = DELAY_BETWEEN_CYCLES
        else:
            cycle_delay = DELAY_BETWEEN_CYCLES
    except (ValueError, IndexError):
        cycle_delay = DELAY_BETWEEN_CYCLES

    workers = _ask_workers()

    print(
        f"  {Fore.GREEN}→ Задержка: {cycle_delay[0] / 60:.1f}-{cycle_delay[1] / 60:.1f} мин, "
        f"Потоки: {workers}{Style.RESET_ALL}"
    )
    return cycle_delay, workers


def _menu_create_db():
    """Создание базы данных."""
    logger.log("Загрузка кошельков...", "cycle")
    wallets = load_wallets()

    if not wallets:
        logger.log(f"Нет кошельков. Добавьте приватные ключи в data/data.csv", "error")
        return

    proxies_count = sum(1 for w in wallets if w.get("proxy"))
    logger.log(f"Найдено кошельков: {len(wallets)}, прокси: {proxies_count}", "info")

    db.create_database(wallets)
    logger.log("База данных создана/обновлена!", "success")

    all_w = db.get_all_wallets()
    for w in all_w:
        addr = w["address"]
        proxy_ok = "✓" if w.get("proxy") else "✗"
        faucet = w.get("faucet_status", "pending")
        faroswap = w.get("faroswap_faucet_status", "pending")
        checkin = w.get("checkin_status", "pending")
        print(
            f"  {Fore.WHITE}{addr[:8]}...{addr[-6:]}  "
            f"Proxy: {Fore.GREEN if proxy_ok == '✓' else Fore.RED}{proxy_ok}  "
            f"{Fore.WHITE}Pharos: {faucet}  FaroSwap: {faroswap}  Check-in: {checkin}{Style.RESET_ALL}"
        )


def _menu_stats():
    """Статистика XP + Level → CSV."""
    wallets = load_wallets()
    if not wallets:
        logger.log("Нет кошельков. Добавьте приватные ключи в data/data.csv", "error")
        return

    workers = _ask_workers()
    stats = asyncio.run(collect_stats(wallets, workers))
    if stats:
        export_csv(stats)
        print(f"\n{Fore.CYAN}{'─' * 70}{Style.RESET_ALL}")
        print(f"  {Fore.WHITE}{'address':<44} {'xp':>8}  {'lvl':<5}  {'quests'}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}{'─' * 70}{Style.RESET_ALL}")
        for s in stats:
            qd = s.get('quests_done', 0)
            qt = s.get('quests_total', 0)
            q_color = Fore.GREEN if qd == qt else Fore.YELLOW
            print(
                f"  {Fore.WHITE}{s['address']:<44} {s['xp']:>8}  "
                f"{Fore.GREEN}{s['lvl']:<5}  "
                f"{q_color}{qd}/{qt}{Style.RESET_ALL}"
            )
        print(f"  {Fore.CYAN}{'─' * 70}{Style.RESET_ALL}")
    else:
        logger.log("Не удалось собрать статистику", "error")


def pharos_menu():
    """Главное меню Pharos — вызывается из projects_menu ETHmachine."""
    from questionary import Choice, select

    logger.banner()

    while True:
        action = select(
            "🔮 Pharos Testnet — выберите действие:",
            choices=[
                Choice('🔹 Создать/обновить БД        🌟 Инициализация кошельков', 'create_db'),
                Choice('──── ОДНОКРАТНО ────', disabled=True),
                Choice('🔹 Check-in                    🌟 Ежедневный чек-ин', 'checkin'),
                Choice('🔹 Краны (Pharos + FaroSwap)   🌟 Клейм тестовых токенов', 'faucet'),
                Choice('🔹 Faucet + Check-in           🌟 Всё вместе', 'all_faucet'),
                Choice('🔹 Квесты                      🌟 Верификация квестов', 'quests'),
                Choice('──── ЦИКЛ ────', disabled=True),
                Choice('🔄 Check-in (цикл 12ч)         🌟 Автоматический чек-ин', 'loop_checkin'),
                Choice('🔄 Краны (цикл)                🌟 Автоматические краны', 'loop_faucet'),
                Choice('🔄 Faucet + Check-in (цикл)    🌟 Всё в цикле', 'loop_all_faucet'),
                Choice('🔄 Квесты (цикл)               🌟 Автоматические квесты', 'loop_quests'),
                Choice('──── ДОПОЛНИТЕЛЬНО ────', disabled=True),
                Choice('📊 Статистика XP + Level → CSV 🌟 Экспорт в result/statistics/', 'stats'),
                Choice('🔙 Назад', 'back'),
            ],
            qmark='🔮',
            pointer='👉'
        ).ask()

        if action is None or action == 'back':
            return

        match action:
            # Создание БД
            case 'create_db':
                _menu_create_db()

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

            # ЦИКЛ
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
                print(f"  {Fore.GREEN}→ Задержка: {h_min:.1f}-{h_max:.1f} ч, Потоки: {workers}{Style.RESET_ALL}")
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

            # ДОПОЛНИТЕЛЬНО
            case 'stats':
                _menu_stats()
