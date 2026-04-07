"""Воркер: параллельная обработка кошельков для Abstract Portal.

Режимы:
  - run_stats(...)     — сбор статистики всех кошельков (профиль, бейджи, XP)
  - run_resume(...)    — продолжить незавершённую работу
  - run_reset(...)     — очистить и начать заново
"""
import asyncio
import random

from config.modules.cfg_abs import SHUFFLE_WALLETS
from config.modules.cfg_base import DELAY_BETWEEN_ACCOUNTS, NUM_THREADS
from modules.abs.abs_proxy import AbsProxyManager
from modules.abs.abs_client import AbsClient
from modules.abs import database as db
from modules.abs import abs_logger as logger


# ---------------------------------------------------------------
# Обработка одного кошелька
# ---------------------------------------------------------------

async def _process_stats(
    semaphore: asyncio.Semaphore,
    wallet: dict,
    index: int,
    total: int,
    proxy_mgr: AbsProxyManager,
    max_workers: int = 1,
) -> dict:
    """Собрать статистику одного кошелька."""
    result = {"address": wallet.get("address", "?"), "success": False}
    try:
        async with semaphore:
            # Разнос старта — первый кошелёк стартует сразу,
            # остальные — с задержкой
            slot = index % max_workers
            if slot > 0:
                delay = random.uniform(
                    DELAY_BETWEEN_ACCOUNTS[0],
                    DELAY_BETWEEN_ACCOUNTS[1],
                ) * slot
                await asyncio.sleep(delay)

            client = AbsClient(
                private_key=wallet["private_key"],
                proxy_manager=proxy_mgr,
                wallet_index=index,
                account_name=wallet.get("account_name"),
                task_index=index + 1,
                task_total=total,
            )

            try:
                stats = await client.collect_full_stats()
                if stats:
                    result.update(stats)
                    result["success"] = stats.get("success", False)
            except Exception as e:
                logger.log(
                    f"Ошибка сбора статистики: {e}", "error",
                    client._short(), index=index + 1, total=total,
                    account_name=wallet.get("account_name"),
                )
                result["error"] = str(e)
                db.log_action(wallet["address"], "stats", "failed", error=str(e))

            # Задержка между аккаунтами
            if index < total - 1:
                delay = random.uniform(
                    DELAY_BETWEEN_ACCOUNTS[0],
                    DELAY_BETWEEN_ACCOUNTS[1],
                )
                await asyncio.sleep(delay)

    except Exception as e:
        result["error"] = f"Task crashed: {type(e).__name__}: {e}"

    return result


# ---------------------------------------------------------------
# Публичные функции запуска
# ---------------------------------------------------------------

async def run_stats(max_workers: int = None, resume: bool = False) -> list[dict]:
    """Запустить сбор статистики для всех кошельков.

    Args:
        max_workers: Количество параллельных потоков
        resume: True = продолжить только незавершённые кошельки

    Returns:
        Список результатов [{address, success, profile, badges, ...}, ...]
    """
    if max_workers is None:
        max_workers = NUM_THREADS

    proxy_mgr = AbsProxyManager()

    if resume:
        wallets = db.get_incomplete_wallets()
        if not wallets:
            logger.log("Все кошельки уже обработаны!", "success")
            return []
        logger.log(f"Продолжаем: {len(wallets)} незавершённых кошельков", "info")
    else:
        wallets = db.get_all_wallets()

    if not wallets:
        logger.log("Нет кошельков для обработки", "warning")
        return []

    total = len(wallets)
    logger.log(
        f"Запуск сбора статистики: {total} кошельков, {max_workers} потоков",
        "info",
    )

    # Перемешивание
    if SHUFFLE_WALLETS and not resume:
        random.shuffle(wallets)

    semaphore = asyncio.Semaphore(max_workers)

    tasks = [
        _process_stats(semaphore, w, i, total, proxy_mgr, max_workers)
        for i, w in enumerate(wallets)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Обработка результатов
    final = []
    success_count = 0
    fail_count = 0
    for r in results:
        if isinstance(r, Exception):
            fail_count += 1
            final.append({"address": "?", "success": False, "error": str(r)})
        else:
            final.append(r)
            if r.get("success"):
                success_count += 1
            else:
                fail_count += 1

    logger.log(
        f"Готово: {success_count} успешно, {fail_count} ошибок из {total}",
        "success" if fail_count == 0 else "warning",
    )

    return final


# ---------------------------------------------------------------
# Клейм бейджей
# ---------------------------------------------------------------

async def _process_claim_badges(
    semaphore: asyncio.Semaphore,
    wallet: dict,
    index: int,
    total: int,
    proxy_mgr: AbsProxyManager,
    max_workers: int = 1,
) -> dict:
    """Заклеймить доступные бейджи для одного кошелька."""
    result = {"address": wallet.get("address", "?"), "success": False}
    try:
        async with semaphore:
            slot = index % max_workers
            if slot > 0:
                delay = random.uniform(
                    DELAY_BETWEEN_ACCOUNTS[0],
                    DELAY_BETWEEN_ACCOUNTS[1],
                ) * slot
                await asyncio.sleep(delay)

            client = AbsClient(
                private_key=wallet["private_key"],
                proxy_manager=proxy_mgr,
                wallet_index=index,
                account_name=wallet.get("account_name"),
                task_index=index + 1,
                task_total=total,
            )

            try:
                claim_result = await client.claim_available_badges()
                if claim_result:
                    result.update(claim_result)
                    result["success"] = claim_result.get("success", False)
            except Exception as e:
                logger.log(
                    f"Ошибка клейма бейджей: {e}", "error",
                    client._short(), index=index + 1, total=total,
                    account_name=wallet.get("account_name"),
                )
                result["error"] = str(e)
                db.log_action(wallet["address"], "claim_badges", "failed", error=str(e))

            if index < total - 1:
                delay = random.uniform(
                    DELAY_BETWEEN_ACCOUNTS[0],
                    DELAY_BETWEEN_ACCOUNTS[1],
                )
                await asyncio.sleep(delay)

    except Exception as e:
        result["error"] = f"Task crashed: {type(e).__name__}: {e}"

    return result


async def run_claim_badges(max_workers: int = None) -> list[dict]:
    """Запустить клейм бейджей для всех кошельков.

    Args:
        max_workers: Количество параллельных потоков

    Returns:
        Список результатов [{address, success, claimed, failed, skipped}, ...]
    """
    if max_workers is None:
        max_workers = NUM_THREADS

    proxy_mgr = AbsProxyManager()
    wallets = db.get_all_wallets()

    if not wallets:
        logger.log("Нет кошельков для обработки", "warning")
        return []

    total = len(wallets)
    logger.log(
        f"Запуск клейма бейджей: {total} кошельков, {max_workers} потоков",
        "info",
    )

    if SHUFFLE_WALLETS:
        random.shuffle(wallets)

    semaphore = asyncio.Semaphore(max_workers)

    tasks = [
        _process_claim_badges(semaphore, w, i, total, proxy_mgr, max_workers)
        for i, w in enumerate(wallets)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    final = []
    total_claimed = 0
    total_failed = 0
    total_skipped = 0
    success_count = 0

    for r in results:
        if isinstance(r, Exception):
            final.append({"address": "?", "success": False, "error": str(r)})
        else:
            final.append(r)
            if r.get("success"):
                success_count += 1
            total_claimed += len(r.get("claimed", []))
            total_failed += len(r.get("failed", []))
            total_skipped += len(r.get("skipped", []))

    logger.log(
        f"Итого: {success_count}/{total} аккаунтов обработано | "
        f"+{total_claimed} заклеймлено, {total_failed} ошибок, "
        f"{total_skipped} не готовы",
        "success" if total_failed == 0 else "warning",
    )

    return final
