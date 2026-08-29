"""Воркер: параллельная обработка кошельков + бесконечный цикл GM.

Режимы:
  - run_registration(...)  — регистрация всех незарегистрированных кошельков
  - run_connect_sol(...)   — подключение Solana кошельков
  - run_gm_once(...)       — однократный GM для всех готовых кошельков
  - run_gm_loop(...)       — бесконечный цикл GM (основной режим)
  - run_stats(...)         — сбор статистики
"""
import asyncio
import random
from datetime import datetime

from config.modules.cfg_xstocks import (
    SHUFFLE_WALLETS, LOOP_CHECK_INTERVAL,
    REFERRAL_MAX_USAGE_DIFF_PERCENT,
)
from config.modules.general_config import DELAY_BETWEEN_ACCOUNTS, NUM_THREADS
from modules.xstocks.xstocks_proxy import XStocksProxyManager
from modules.xstocks.client import XStocksClient
from modules.xstocks import database as db
from modules.xstocks import xstocks_logger as logger
from modules.data_manager import get_referral_code_for_key


# ---------------------------------------------------------------
# Подготовка кошельков
# ---------------------------------------------------------------

def _get_referral_for_wallet(private_key: str) -> str | None:
    """Получить реферальный код для кошелька.
    Приоритет: data.csv -> случайный из БД -> None."""
    # 1. Из data.csv
    code = get_referral_code_for_key(private_key)
    if code:
        return code

    # 2. Случайный из БД с балансировкой
    code = db.get_random_referral_code(REFERRAL_MAX_USAGE_DIFF_PERCENT)
    return code


# ---------------------------------------------------------------
# Обработка одного кошелька
# ---------------------------------------------------------------

async def _process_registration(
    semaphore: asyncio.Semaphore,
    wallet: dict,
    index: int,
    total: int,
    proxy_mgr: XStocksProxyManager,
    max_workers: int = 1,
) -> dict:
    """Зарегистрировать один кошелёк."""
    result = {"address": wallet.get("address", "?"), "success": False}
    try:
        async with semaphore:
            # Разнос старта параллельных воркеров (2-5с на каждый слот)
            slot = index % max_workers
            if slot > 0:
                await asyncio.sleep(random.uniform(2, 5) * slot)

            client = XStocksClient(
                private_key=wallet["private_key"],
                proxy_manager=proxy_mgr,
                wallet_index=index,
                sol_private_key=wallet.get("sol_private_key"),
                account_name=wallet.get("account_name"),
                task_index=index + 1,
                task_total=total,
            )

            referral_code = _get_referral_for_wallet(wallet["private_key"])
            result["address"] = wallet["address"]

            try:
                ok = await client.run_registration_workflow(referral_code)
                result["success"] = ok
            except Exception as e:
                logger.log(f"Ошибка регистрации: {e}", "error", client._short(),
                           index=index + 1, total=total, account_name=wallet.get("account_name"))
                result["error"] = str(e)
                db.log_action(wallet["address"], "registration", "failed", error=str(e))

            # Задержка между аккаунтами
            if index < total - 1:
                delay = random.uniform(DELAY_BETWEEN_ACCOUNTS[0], DELAY_BETWEEN_ACCOUNTS[1])
                await asyncio.sleep(delay)

    except Exception as e:
        result["error"] = f"Task crashed: {type(e).__name__}: {e}"

    return result


async def _process_gm(
    semaphore: asyncio.Semaphore,
    wallet: dict,
    index: int,
    total: int,
    proxy_mgr: XStocksProxyManager,
    max_workers: int = 1,
) -> dict:
    """Саy GM для одного кошелька."""
    result = {"address": wallet.get("address", "?"), "success": False}
    try:
        async with semaphore:
            # Разнос старта параллельных воркеров
            slot = index % max_workers
            if slot > 0:
                await asyncio.sleep(random.uniform(2, 5) * slot)

            client = XStocksClient(
                private_key=wallet["private_key"],
                proxy_manager=proxy_mgr,
                wallet_index=wallet.get("id", index),
                sol_private_key=wallet.get("sol_private_key"),
                account_name=wallet.get("account_name"),
                task_index=index + 1,
                task_total=total,
            )

            result["address"] = wallet["address"]

            try:
                gm_result = await client.run_gm_workflow()
                result["success"] = gm_result.get("success", False)
                result["next_gm_at"] = gm_result.get("next_gm_at")
            except Exception as e:
                logger.log(f"Ошибка GM: {e}", "error", client._short(),
                           index=index + 1, total=total, account_name=wallet.get("account_name"))
                result["error"] = str(e)
                db.log_action(wallet["address"], "gm", "failed", error=str(e))

            if index < total - 1:
                delay = random.uniform(DELAY_BETWEEN_ACCOUNTS[0], DELAY_BETWEEN_ACCOUNTS[1])
                await asyncio.sleep(delay)

    except Exception as e:
        result["error"] = f"Task crashed: {type(e).__name__}: {e}"

    return result


async def _process_sol_connect(
    semaphore: asyncio.Semaphore,
    wallet: dict,
    index: int,
    total: int,
    proxy_mgr: XStocksProxyManager,
) -> dict:
    """Подключить (зарегистрировать) Solana кошелёк."""
    async with semaphore:
        client = XStocksClient(
            private_key=wallet["private_key"],
            proxy_manager=proxy_mgr,
            wallet_index=wallet.get("id", index),
            sol_private_key=wallet.get("sol_private_key"),
            account_name=wallet.get("account_name"),
            task_index=index + 1,
            task_total=total,
        )

        result = {"address": wallet["address"], "success": False}

        try:
            # Используем реферальный код EVM кошелька
            ref_code = wallet.get("referral_code") or _get_referral_for_wallet(wallet["private_key"])
            ok = await client.register_solana(ref_code)
            result["success"] = ok
        except Exception as e:
            logger.log(f"Ошибка Solana: {e}", "error", client._short(),
                       index=index + 1, total=total, account_name=wallet.get("account_name"))
            result["error"] = str(e)

        if index < total - 1:
            delay = random.uniform(DELAY_BETWEEN_ACCOUNTS[0], DELAY_BETWEEN_ACCOUNTS[1])
            await asyncio.sleep(delay)

        return result


async def _process_stats(
    semaphore: asyncio.Semaphore,
    wallet: dict,
    index: int,
    total: int,
    proxy_mgr: XStocksProxyManager,
) -> dict:
    """Получить статистику для одного кошелька."""
    async with semaphore:
        client = XStocksClient(
            private_key=wallet["private_key"],
            proxy_manager=proxy_mgr,
            wallet_index=wallet.get("id", index),
            account_name=wallet.get("account_name"),
            task_index=index + 1,
            task_total=total,
        )

        result = {"address": wallet["address"], "success": False, "stats": {}}

        try:
            stats = await client.run_stats_workflow()
            result["stats"] = stats
            result["success"] = bool(stats)
        except Exception as e:
            logger.log(f"Ошибка статистики: {e}", "error", client._short(),
                       index=index + 1, total=total, account_name=wallet.get("account_name"))
            result["error"] = str(e)

        return result


# ---------------------------------------------------------------
# Запуск регистрации
# ---------------------------------------------------------------

async def run_registration(max_workers: int = None) -> list[dict]:
    """Зарегистрировать все незарегистрированные кошельки."""
    wallets = db.get_wallets_needing_registration()
    if not wallets:
        logger.log("Все кошельки уже зарегистрированы!", "success")
        return []

    workers = max_workers or NUM_THREADS
    semaphore = asyncio.Semaphore(workers)
    proxy_mgr = XStocksProxyManager()

    indexed = list(enumerate(wallets))
    if SHUFFLE_WALLETS:
        random.shuffle(indexed)
        logger.log("Порядок кошельков перемешан", "info")

    total = len(wallets)
    logger.log(f"Регистрация: {total} кошельков | {workers} потоков", "cycle")

    # Счётчик завершённых задач — для отметок о ходе работы в логе.
    completed_counter = {"value": 0}

    async def _tracked_task(i, w):
        """Обёртка вокруг _process_registration с трекингом завершения."""
        result = await _process_registration(semaphore, w, i, total, proxy_mgr, workers)
        completed_counter["value"] += 1
        done = completed_counter["value"]
        # Отмечаем каждые 50 задач и последнюю — иначе лог тонет в деталях.
        if done % 50 == 0 or done == total:
            logger.log(f"Завершено задач: {done}/{total}", "info")
        return result

    tasks = [_tracked_task(i, w) for i, w in indexed]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Подсчёт результатов с логированием ошибок
    success = 0
    failed = 0
    exceptions = 0
    error_types = {}
    for r in results:
        if isinstance(r, BaseException):
            exceptions += 1
            etype = type(r).__name__
            error_types[etype] = error_types.get(etype, 0) + 1
            if exceptions <= 5:
                logger.log(f"Исключение в таске: {etype}: {r}", "error")
        elif isinstance(r, dict) and r.get("success"):
            success += 1
        else:
            failed += 1
            # Логировать ошибки из dict
            if isinstance(r, dict) and r.get("error") and failed <= 5:
                logger.log(f"Ошибка задачи: {r['error']}", "warning")

    if exceptions > 5:
        logger.log(f"... и ещё {exceptions - 5} исключений", "error")
    if error_types:
        logger.log(f"Типы исключений: {error_types}", "warning")

    logger.stats_block({
        "всего": total,
        "успешно": success,
        "неудачно": failed,
        "исключений": exceptions,
    }, title="Итог регистрации")

    return [r for r in results if isinstance(r, dict)]


# ---------------------------------------------------------------
# Подключение Solana
# ---------------------------------------------------------------

async def run_connect_sol(max_workers: int = None) -> list[dict]:
    """Подключить Solana для всех кошельков, где есть sol_private_key."""
    wallets = db.get_wallets_needing_sol()
    if not wallets:
        logger.log("Нет кошельков для подключения Solana", "warning")
        return []

    workers = max_workers or NUM_THREADS
    semaphore = asyncio.Semaphore(workers)
    proxy_mgr = XStocksProxyManager()

    logger.log(f"Подключение Solana: {len(wallets)} кошельков | {workers} потоков", "cycle")

    tasks = [
        _process_sol_connect(semaphore, w, i, len(wallets), proxy_mgr)
        for i, w in enumerate(wallets)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    success = sum(1 for r in results if isinstance(r, dict) and r.get("success"))

    logger.stats_block({
        "всего": len(wallets),
        "подключено": success,
        "не подключено": len(results) - success,
    }, title="Итог подключения Solana")

    return [r for r in results if isinstance(r, dict)]


# ---------------------------------------------------------------
# Однократный GM
# ---------------------------------------------------------------

async def run_gm_once(max_workers: int = None) -> list[dict]:
    """Однократный Say GM для всех готовых кошельков."""
    wallets = db.get_wallets_needing_gm()
    if not wallets:
        next_gm = db.get_next_gm_time()
        if next_gm:
            logger.log(f"Нет кошельков для GM. Ближайший: {next_gm[:16]}", "warning")
        else:
            logger.log("Нет зарегистрированных кошельков для GM", "warning")
        return []

    workers = max_workers or NUM_THREADS
    semaphore = asyncio.Semaphore(workers)
    proxy_mgr = XStocksProxyManager()

    logger.log(f"Say GM: {len(wallets)} кошельков | {workers} потоков", "cycle")

    tasks = [
        _process_gm(semaphore, w, i, len(wallets), proxy_mgr, workers)
        for i, w in enumerate(wallets)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    success = sum(1 for r in results if isinstance(r, dict) and r.get("success"))

    logger.stats_block({
        "всего": len(wallets),
        "отметились": success,
        "не отметились": len(results) - success,
    }, title="Итог отметки GM")

    return [r for r in results if isinstance(r, dict)]


# ---------------------------------------------------------------
# Бесконечный цикл GM
# ---------------------------------------------------------------

async def run_gm_loop(max_workers: int = None):
    """Бесконечный цикл: GM -> ждать до ближайшего кулдауна -> GM -> ...

    Логика:
    1. Регистрация / Solana если нужно
    2. Say GM для всех готовых кошельков
    3. Ждать до ближайшего next_gm_at из БД (кулдаун парсится из ответа API)
    4. Когда кошелёк(и) «спадают» с таймаута — обработать их
    """
    workers = max_workers or NUM_THREADS
    cycle = 0

    logger.log("Бесконечный цикл GM запущен (Ctrl+C для остановки)", "cycle")

    while True:
        cycle += 1
        logger.log(f"--- Цикл #{cycle} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---", "cycle")

        # 1. Регистрация (если есть незарегистрированные)
        unreg = db.get_wallets_needing_registration()
        if unreg:
            logger.log(f"Найдено {len(unreg)} незарегистрированных кошельков", "warning")
            await run_registration(workers)
            await asyncio.sleep(random.uniform(3, 7))

        # 2. Подключение Solana (если нужно)
        need_sol = db.get_wallets_needing_sol()
        if need_sol:
            logger.log(f"Найдено {len(need_sol)} кошельков для подключения Solana", "info")
            await run_connect_sol(workers)
            await asyncio.sleep(random.uniform(2, 5))

        # 3. Say GM для готовых кошельков
        gm_wallets = db.get_wallets_needing_gm()
        if gm_wallets:
            logger.log(f"Готовы к GM: {len(gm_wallets)} кошельков", "info")
            await run_gm_once(workers)

        # 4. Определить время ожидания по ближайшему next_gm_at из БД
        next_gm = db.get_next_gm_time()
        if next_gm:
            try:
                next_dt = datetime.fromisoformat(next_gm)
                now = datetime.now()
                wait_seconds = (next_dt - now).total_seconds()

                if wait_seconds > 0:
                    hours = wait_seconds / 3600
                    mins = wait_seconds / 60
                    if hours >= 1:
                        logger.log(
                            f"Ожидание {hours:.1f}ч до ближайшего GM "
                            f"({next_dt.strftime('%Y-%m-%d %H:%M')})",
                            "info"
                        )
                    else:
                        logger.log(
                            f"Ожидание {mins:.0f} мин до ближайшего GM "
                            f"({next_dt.strftime('%H:%M')})",
                            "info"
                        )

                    # Проверяем каждые check_interval секунд — может кто-то готов раньше
                    while wait_seconds > 0:
                        check_interval = random.uniform(
                            LOOP_CHECK_INTERVAL[0], LOOP_CHECK_INTERVAL[1]
                        )
                        sleep_time = min(check_interval, wait_seconds)
                        await asyncio.sleep(sleep_time)
                        wait_seconds -= sleep_time

                        # Проверяем: может кошельки уже спали с таймаута
                        ready = db.get_wallets_needing_gm()
                        if ready:
                            logger.log(f"Обнаружено {len(ready)} кошельков готовых к GM", "info")
                            break
                    continue
            except (ValueError, TypeError):
                pass

        # Если нет next_gm_at (все кошельки без GM данных) — короткий интервал
        wait = random.uniform(LOOP_CHECK_INTERVAL[0], LOOP_CHECK_INTERVAL[1])
        logger.log(f"Проверка через {wait/60:.1f} мин", "info")
        await asyncio.sleep(wait)


# ---------------------------------------------------------------
# Сбор статистики
# ---------------------------------------------------------------

async def run_stats(max_workers: int = None) -> list[dict]:
    """Сбор и обновление статистики для всех зарегистрированных кошельков."""
    wallets = db.get_all_wallets()
    registered = [w for w in wallets if w.get("evm_registered")]
    if not registered:
        logger.log("Нет зарегистрированных кошельков", "warning")
        return []

    workers = max_workers or NUM_THREADS
    semaphore = asyncio.Semaphore(workers)
    proxy_mgr = XStocksProxyManager()

    logger.log(f"Сбор статистики: {len(registered)} кошельков | {workers} потоков", "cycle")

    indexed = list(enumerate(registered))
    if SHUFFLE_WALLETS:
        random.shuffle(indexed)
        logger.log("Порядок кошельков перемешан", "info")

    tasks = [
        _process_stats(semaphore, w, i, len(registered), proxy_mgr)
        for i, w in indexed
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


# ---------------------------------------------------------------
# Полный автоматический режим
# ---------------------------------------------------------------

async def run_full_auto(max_workers: int = None):
    """Полный автомат: регистрация + Solana + бесконечный GM.
    Это основной режим работы модуля."""
    workers = max_workers or NUM_THREADS

    logger.log("xStocks FULL AUTO MODE", "cycle")
    logger.log("Регистрация -> Solana -> GM бесконечный цикл", "info")

    # Запуск бесконечного цикла (внутри сам регистрирует и подключает sol)
    await run_gm_loop(workers)
