"""Воркер: параллельная обработка кошельков + циклический запуск.

Режимы:
  - run_parallel(mode, ...)     — однократный запуск всех кошельков
  - run_loop(mode, ...)         — бесконечный цикл
  - run_stretched(mode, hours)  — растяжка на N часов с автопаузами и resume
"""
import asyncio
import json
import random
from datetime import datetime, timedelta

from config.modules.cfg_pharos import (
    DELAY_BETWEEN_CYCLES, DELAY_BETWEEN_CYCLES_CHECKIN,
    SHUFFLE_WALLETS,
)
from config.modules.cfg_base import DELAY_BETWEEN_ACCOUNTS, NUM_THREADS
from modules.pharos.pharos_proxy import PharosProxyManager
from modules.pharos.pharos_client import PharosClient
from modules.pharos import database as db
from modules.pharos import pharos_logger as logger


# ═══════════════════════════════════════════════════════════
# Обработка одного кошелька
# ═══════════════════════════════════════════════════════════

async def _process_wallet(
    semaphore: asyncio.Semaphore,
    wallet: dict,
    index: int,
    proxy_mgr: PharosProxyManager,
    mode: str,
    task_id: int = None,
) -> dict:
    """Обработать один кошелёк под семафором."""
    async with semaphore:
        # Пометить задачу как running в БД
        if task_id:
            db.update_task_status(task_id, "running")

        client = PharosClient(wallet["private_key"], proxy_mgr, index)
        if wallet.get("jwt_token"):
            client.jwt_token = wallet["jwt_token"]

        addr = wallet.get("address") or wallet.get("wallet_address", "")
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
            elif mode == "send_verify":
                sv_result = await client.run_send_verify_workflow()
                result["success"] = sv_result.get("success", False)
                result["stats"] = sv_result
        except Exception as e:
            logger.log(f"Ошибка воркера: {e}", "error", addr)
            result["error"] = str(e)

        # Сохранить результат в БД
        if task_id:
            status = "completed" if result["success"] else "failed"
            result_json = json.dumps(result.get("stats") or {}, default=str)
            error = result.get("error") or (None if result["success"] else "task failed")
            db.update_task_status(task_id, status, result_json=result_json, error=error)

        return result


# ═══════════════════════════════════════════════════════════
# Параллельный запуск (однократный)
# ═══════════════════════════════════════════════════════════

async def run_parallel(mode: str, max_workers: int = None) -> list[dict]:
    """Запуск всех кошельков параллельно с ограничением по семафору.
    Автоматически инициализирует БД и создаёт cycle_run."""
    wallets = db.get_all_wallets()
    if not wallets:
        logger.log("База данных пуста! Добавьте приватные ключи в data/data.csv", "error")
        return []

    workers = max_workers or NUM_THREADS
    semaphore = asyncio.Semaphore(workers)
    proxy_mgr = PharosProxyManager()

    mode_names = {
        "checkin": "Check-in",
        "faucet": "Краны (Pharos + FaroSwap)",
        "all_faucet": "Faucet + Check-in",
        "quests": "Квесты",
        "send_verify": "Send & Verify (Pharos Auto)",
    }
    mode_name = mode_names.get(mode, mode)

    # Создать цикл в БД
    cycle_num = db.get_last_cycle_number(mode) + 1
    run_id = db.create_cycle_run(mode, len(wallets), cycle_num)

    indexed_wallets = list(enumerate(wallets))
    if SHUFFLE_WALLETS:
        random.shuffle(indexed_wallets)
        logger.log("Порядок кошельков перемешан", "info")

    # Создать задачи в БД
    ordered_wallets = [w for _, w in indexed_wallets]
    db.create_wallet_tasks(run_id, ordered_wallets)

    logger.log(f"Запуск: {mode_name} | {len(wallets)} кошельков | {workers} потоков", "cycle")

    # Получить задачи из БД (pending)
    pending = db.get_pending_tasks(run_id)

    tasks = []
    for t in pending:
        wallet_data = {
            "private_key": t["private_key"],
            "address": t["wallet_address"],
            "proxy": t["proxy"],
            "jwt_token": t["jwt_token"],
            "account_name": t["account_name"],
        }
        delay = random.uniform(*DELAY_BETWEEN_ACCOUNTS)
        tasks.append(_delayed_process(semaphore, wallet_data, t["wallet_index"],
                                      proxy_mgr, mode, t["id"], delay))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Финализация
    success, failed = db.get_completed_task_count(run_id)
    results_table = db.finish_cycle_run(run_id, success, failed)

    # Статистика
    valid = [r for r in results if isinstance(r, dict)]
    _print_stats(mode, valid, len(wallets), success, failed)

    # Собрать send_verify результаты для экспорта
    sv_results = [r["stats"] for r in valid if r.get("stats") and mode == "send_verify"]
    return sv_results if mode == "send_verify" else valid


async def _delayed_process(semaphore, wallet, index, proxy_mgr, mode, task_id, delay):
    """Обёртка с задержкой перед стартом."""
    await asyncio.sleep(delay)
    return await _process_wallet(semaphore, wallet, index, proxy_mgr, mode, task_id)


def _print_stats(mode, results, total, success, failed):
    """Вывести статистику по завершении."""
    if mode in ("checkin", "faucet", "all_faucet"):
        logger.stats_block({
            "Успешно": success,
            "Неудачно (fail)": failed,
            "Всего": total,
        })
    elif mode == "send_verify":
        sv = [r["stats"] for r in results if r.get("stats")]
        logger.stats_block({
            "Успешно": success,
            "Неудачно (fail)": failed,
            "Отправок TX": sum(s.get("sends", 0) for s in sv),
            "Верификаций": sum(s.get("verifies", 0) for s in sv),
            "XP получено": sum(s.get("xp_gained", 0) for s in sv),
            "Всего": total,
        })
    else:
        logger.stats_block({
            "Выполнено квестов": sum(r.get("stats", {}).get("verified", 0) for r in results),
            "Уже выполнены": sum(r.get("stats", {}).get("already_done", 0) for r in results),
            "Неудачно (fail)": failed,
        })


# ═══════════════════════════════════════════════════════════
# Бесконечный цикл
# ═══════════════════════════════════════════════════════════

async def run_loop(mode: str, cycle_delay: tuple = None, max_workers: int = None):
    """Бесконечный цикл с рандомной задержкой между циклами."""
    if mode == "checkin":
        delay_range = cycle_delay or DELAY_BETWEEN_CYCLES_CHECKIN
    else:
        delay_range = cycle_delay or DELAY_BETWEEN_CYCLES

    cycle_num = db.get_last_cycle_number(mode)

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


# ═══════════════════════════════════════════════════════════
# Режим растяжки на N часов (25h по умолчанию)
# ═══════════════════════════════════════════════════════════

async def run_stretched(mode: str, stretch_hours: float = 25.0,
                        max_workers: int = 1) -> str | None:
    """Запуск кошельков с автоматической растяжкой на stretch_hours часов.

    Паузы между стартами кошельков рассчитываются так, чтобы
    все кошельки отработали за stretch_hours.
    При непредвиденной остановке — resume с того же места.

    Returns:
        results_table name или None
    """
    wallets = db.get_all_wallets()
    if not wallets:
        logger.log("База данных пуста! Добавьте приватные ключи в data/data.csv", "error")
        return None

    proxy_mgr = PharosProxyManager()
    total = len(wallets)

    # Проверить: есть ли незавершённый цикл (resume)
    active_run = db.get_active_cycle_run(mode)
    resuming = False

    if active_run:
        run_id = active_run["id"]
        pending = db.get_pending_tasks(run_id)
        if pending:
            done_count = total - len(pending)
            logger.log(
                f"Найден незавершённый цикл #{active_run['cycle_number']} "
                f"({done_count}/{total} выполнено). Продолжаем...",
                "warning"
            )
            resuming = True
        else:
            # Все задачи выполнены — завершить старый, начать новый
            success, failed = db.get_completed_task_count(run_id)
            db.finish_cycle_run(run_id, success, failed)
            active_run = None

    if not active_run:
        cycle_num = db.get_last_cycle_number(mode) + 1
        run_id = db.create_cycle_run(mode, total, cycle_num, stretch_hours)

        wallet_list = list(wallets)
        if SHUFFLE_WALLETS:
            random.shuffle(wallet_list)
            logger.log("Порядок кошельков перемешан", "info")

        # Рассчитать расписание: распределить кошельки на stretch_hours
        total_seconds = stretch_hours * 3600
        now = datetime.now()
        scheduled_times = []
        for i in range(total):
            if total > 1:
                # Равномерное распределение с случайным джиттером
                base_delay = (total_seconds / total) * i
                jitter = random.uniform(0, total_seconds / total * 0.3)
                delay_sec = base_delay + jitter
            else:
                delay_sec = 0
            scheduled = (now + timedelta(seconds=delay_sec)).isoformat()
            scheduled_times.append(scheduled)

        db.create_wallet_tasks(run_id, wallet_list, scheduled_times)

    # Получить задачи
    pending = db.get_pending_tasks(run_id)

    if not pending:
        logger.log("Все задачи уже выполнены", "success")
        success, failed = db.get_completed_task_count(run_id)
        return db.finish_cycle_run(run_id, success, failed)

    mode_names = {
        "checkin": "Check-in",
        "faucet": "Краны (Pharos + FaroSwap)",
        "all_faucet": "Faucet + Check-in",
        "quests": "Квесты",
        "send_verify": "Send & Verify",
    }
    mode_name = mode_names.get(mode, mode)

    remaining = len(pending)
    logger.log(
        f"Stretch-режим: {mode_name} | {remaining} кошельков "
        f"| {stretch_hours}ч | {max_workers} поток(ов)",
        "cycle"
    )

    semaphore = asyncio.Semaphore(max_workers)
    processed = total - remaining

    for task in pending:
        # Ждать до запланированного времени
        scheduled = task.get("scheduled_at")
        if scheduled and not resuming:
            scheduled_dt = datetime.fromisoformat(scheduled)
            now = datetime.now()
            wait_sec = (scheduled_dt - now).total_seconds()
            if wait_sec > 0:
                next_time = scheduled_dt.strftime("%H:%M:%S")
                logger.log(
                    f"[{processed + 1}/{total}] Ожидание до {next_time} "
                    f"({wait_sec / 60:.1f} мин)...",
                    "info"
                )
                try:
                    await asyncio.sleep(wait_sec)
                except asyncio.CancelledError:
                    logger.log("Stretch остановлен (прогресс сохранён в БД)", "warning")
                    return None
        elif resuming:
            # При resume — небольшая пауза между кошельками
            await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS))

        wallet_data = {
            "private_key": task["private_key"],
            "address": task["wallet_address"],
            "proxy": task["proxy"],
            "jwt_token": task["jwt_token"],
            "account_name": task["account_name"],
        }

        result = await _process_wallet(
            semaphore, wallet_data, task["wallet_index"],
            proxy_mgr, mode, task["id"]
        )

        processed += 1
        db.update_cycle_progress(run_id, processed)

        addr_short = task["wallet_address"][:8] + "..." + task["wallet_address"][-4:]
        status_icon = "OK" if result.get("success") else "FAIL"
        logger.log(f"[{processed}/{total}] {addr_short} — {status_icon}", "success" if result.get("success") else "error")

    # Финализация
    success, failed = db.get_completed_task_count(run_id)
    results_table = db.finish_cycle_run(run_id, success, failed)

    _print_stats(mode, [], total, success, failed)
    logger.log(f"Stretch завершён! Результаты: {results_table}", "success")

    return results_table


async def run_stretched_loop(mode: str, stretch_hours: float = 25.0, max_workers: int = 1):
    """Бесконечный цикл stretch-режима. После каждого цикла —
    автоматический перезапуск."""
    while True:
        logger.log(f"{'=' * 15} STRETCH ЦИКЛ {'=' * 15}", "cycle")
        logger.log(f"Начало: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "cycle")

        results_table = await run_stretched(mode, stretch_hours, max_workers)

        if results_table:
            logger.log(
                f"Цикл завершён. Следующий stretch на {stretch_hours}ч начнётся сразу.",
                "cycle"
            )
        else:
            logger.log("Цикл не завершён. Повторная попытка через 60 сек...", "warning")
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                logger.log("Stretch-цикл остановлен пользователем", "warning")
                break
