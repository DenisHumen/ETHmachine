"""Воркер: параллельная обработка кошельков + циклический запуск."""
import asyncio
import random
from datetime import datetime

from config.modules.cfg_pharos import (
    DELAY_BETWEEN_ACCOUNTS, DELAY_BETWEEN_CYCLES, DELAY_BETWEEN_CYCLES_CHECKIN,
    MAX_CONCURRENT_WALLETS, SHUFFLE_WALLETS,
)
from modules.pharos.pharos_proxy import PharosProxyManager
from modules.pharos.pharos_client import PharosClient
from modules.pharos import database as db
from modules.pharos import pharos_logger as logger


async def _process_wallet(
    semaphore: asyncio.Semaphore,
    wallet: dict,
    index: int,
    proxy_mgr: PharosProxyManager,
    mode: str,
) -> dict:
    """Обработать один кошелёк под семафором."""
    async with semaphore:
        start_delay = random.uniform(*DELAY_BETWEEN_ACCOUNTS)
        await asyncio.sleep(start_delay)

        client = PharosClient(wallet["private_key"], proxy_mgr, index)
        if wallet.get("jwt_token"):
            client.jwt_token = wallet["jwt_token"]

        addr = wallet["address"]
        result = {"address": addr, "success": False, "stats": {}}

        try:
            if mode == "checkin":
                ok = await client.run_checkin_workflow()
                result["success"] = ok
            elif mode == "faucet":
                ok = await client.run_faucet_workflow()
                result["success"] = ok
            elif mode == "all_faucet":
                ok = await client.run_all_faucet_workflow()
                result["success"] = ok
            elif mode == "quests":
                stats = await client.run_quest_workflow()
                result["stats"] = stats
                result["success"] = "error" not in stats
        except Exception as e:
            logger.log(f"Ошибка воркера: {e}", "error", addr)

        return result


async def run_parallel(mode: str, max_workers: int = None):
    """Запуск всех кошельков параллельно с ограничением по семафору."""
    wallets = db.get_all_wallets()
    if not wallets:
        logger.log("База данных пуста! Сначала выполните пункт 'Создать/обновить БД'.", "error")
        return

    indexed_wallets = list(enumerate(wallets))

    if SHUFFLE_WALLETS:
        random.shuffle(indexed_wallets)
        logger.log("Порядок кошельков перемешан", "info")

    workers = max_workers or MAX_CONCURRENT_WALLETS
    semaphore = asyncio.Semaphore(workers)
    proxy_mgr = PharosProxyManager()

    mode_names = {
        "checkin": "Check-in",
        "faucet": "Краны (Pharos + FaroSwap)",
        "all_faucet": "Faucet + Check-in",
        "quests": "Квесты",
    }
    mode_name = mode_names.get(mode, mode)
    logger.log(f"Запуск: {mode_name} | {len(wallets)} кошельков | {workers} потоков", "cycle")

    tasks = [
        _process_wallet(semaphore, w, orig_idx, proxy_mgr, mode)
        for orig_idx, w in indexed_wallets
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Статистика
    success = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
    failed = len(results) - success

    if mode in ("checkin", "faucet", "all_faucet"):
        logger.stats_block({
            "Успешно": success,
            "Неудачно (fail)": failed,
            "Всего": len(wallets),
        })
    else:
        total_verified = sum(r["stats"].get("verified", 0) for r in results if isinstance(r, dict) and r.get("stats"))
        total_already = sum(r["stats"].get("already_done", 0) for r in results if isinstance(r, dict) and r.get("stats"))
        total_failed = sum(r["stats"].get("failed", 0) for r in results if isinstance(r, dict) and r.get("stats"))
        logger.stats_block({
            "Выполнено квестов": total_verified,
            "Уже выполнены (already_done)": total_already,
            "Неудачно (fail)": total_failed,
        })


async def run_loop(mode: str, cycle_delay: tuple = None, max_workers: int = None):
    """Бесконечный цикл с рандомной задержкой между циклами."""
    if mode == "checkin":
        delay_range = cycle_delay or DELAY_BETWEEN_CYCLES_CHECKIN
    else:
        delay_range = cycle_delay or DELAY_BETWEEN_CYCLES
    cycle_num = 0

    while True:
        cycle_num += 1
        logger.log(f"{'=' * 15} ЦИКЛ #{cycle_num} {'=' * 15}", "cycle")
        logger.log(f"Начало: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "cycle")

        await run_parallel(mode, max_workers)

        delay = random.uniform(*delay_range)
        hours = delay / 3600
        minutes = delay / 60
        if hours >= 1:
            logger.log(f"Цикл #{cycle_num} завершён. Следующий через {hours:.1f} ч", "cycle")
        else:
            logger.log(f"Цикл #{cycle_num} завершён. Следующий через {minutes:.1f} мин", "cycle")

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.log("Цикл остановлен пользователем", "warning")
            break
