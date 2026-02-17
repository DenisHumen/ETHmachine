"""Модуль статистики: сбор XP и уровня аккаунтов, экспорт в CSV."""
import csv
import ssl
import asyncio
import os
from datetime import datetime
from pathlib import Path

import aiohttp
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from eth_account import Account
from eth_account.messages import encode_defunct
from fake_useragent import FakeUserAgent

from config.modules.cfg_pharos import (
    BASE_URL, DEFAULT_HEADERS, REQUEST_TIMEOUT, REF_CODE,
    ALL_TASK_IDS,
)
from config.modules.cfg_base import NUM_THREADS
from config.modules.cfg_base import RETRY_COUNT
from modules.pharos.pharos_proxy import PharosProxyManager
from modules.pharos import pharos_logger as logger

# Путь для сохранения статистики
STATS_DIR = Path(__file__).parent.parent.parent / "result" / "statistics"
STATS_FILE = str(STATS_DIR / "pharos_stats.csv")

# API URLs
LEVEL_LIST_URL = f"{BASE_URL}/info/progress"
PROFILE_URL = f"{BASE_URL}/user/profile"
LOGIN_URL = f"{BASE_URL}/user/login"
USER_TASKS_URL = f"{BASE_URL}/user/tasks"

# SSL контекст
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


async def _do_request(session, method, url, headers, proxy_kw, **kwargs):
    """Выполнить один HTTP-запрос через aiohttp сессию."""
    if method == "get":
        async with session.get(url, headers=headers, **proxy_kw, **kwargs) as resp:
            return await resp.json()
    else:
        async with session.post(url, headers=headers, **proxy_kw, **kwargs) as resp:
            return await resp.json()


async def _request_with_retry(
    proxy_manager: PharosProxyManager,
    address: str,
    wallet_index: int,
    method: str,
    url: str,
    headers: dict,
    retries: int = None,
    **kwargs,
) -> dict | list | None:
    """HTTP-запрос с ретраями и ротацией прокси."""
    if retries is None:
        retries = RETRY_COUNT

    proxy = proxy_manager.get_proxy_for_wallet(address, wallet_index)

    for attempt in range(retries):
        proxy_config = proxy_manager.get_aiohttp_proxy_config(proxy)
        connector = None
        try:
            socks_url = proxy_config.get("socks_url")
            if socks_url:
                from aiohttp_socks import ProxyConnector
                connector = ProxyConnector.from_url(socks_url, ssl=_ssl_ctx)
            else:
                connector = TCPConnector(ssl=_ssl_ctx)

            async with ClientSession(
                connector=connector,
                timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            ) as session:
                proxy_kw = {}
                if not socks_url:
                    proxy_kw["proxy"] = proxy_config.get("proxy")
                    proxy_kw["proxy_auth"] = proxy_config.get("proxy_auth")

                return await _do_request(session, method, url, headers, proxy_kw, **kwargs)

        except Exception as e:
            if attempt < retries - 1:
                old_proxy = proxy
                proxy = proxy_manager.rotate_proxy(address)
                if old_proxy != proxy:
                    logger.log(
                        f"Прокси не работает, ротация ({attempt + 1}/{retries})...",
                        "warning",
                    )
                await asyncio.sleep(2)
            else:
                raise
    return None


async def fetch_level_list(proxy_manager: PharosProxyManager) -> list[dict]:
    """Загрузить список уровней с пороговыми значениями XP."""
    headers = {**DEFAULT_HEADERS, "User-Agent": FakeUserAgent().random}
    try:
        data = await _request_with_retry(
            proxy_manager, "level_list", 0, "get", LEVEL_LIST_URL, headers,
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return []
    except Exception as e:
        logger.log(f"Ошибка загрузки level list: {e}", "error")
        return []


def calculate_level(total_points: int, level_list: list[dict]) -> str:
    """Определить уровень по TotalPoints."""
    if not level_list:
        return "Lv.1"

    if total_points <= level_list[0]["min"]:
        return level_list[0]["name"]

    if total_points >= level_list[-1]["max"]:
        return level_list[-1]["name"]

    for entry in level_list:
        if entry["min"] <= total_points <= entry["max"]:
            return entry["name"]

    return "Lv.1"


async def get_wallet_stats(
    private_key: str,
    proxy_manager: PharosProxyManager,
    wallet_index: int,
    level_list: list[dict],
    semaphore: asyncio.Semaphore,
) -> dict | None:
    """Получить XP и уровень для одного кошелька."""
    account = Account.from_key(private_key)
    address = account.address
    short = f"{address[:6]}...{address[-4:]}"

    async with semaphore:
        ua = FakeUserAgent().random
        headers = {**DEFAULT_HEADERS, "User-Agent": ua}

        try:
            # 1. Логин
            msg = encode_defunct(text="pharos")
            signed = account.sign_message(msg)
            signature = signed.signature.hex()
            if not signature.startswith("0x"):
                signature = "0x" + signature

            login_url = f"{LOGIN_URL}?address={address}&signature={signature}&invite_code={REF_CODE}"
            login_data = await _request_with_retry(
                proxy_manager, address, wallet_index,
                "post", login_url, headers, data="{}",
            )

            jwt = None
            if isinstance(login_data, dict):
                if login_data.get("code") == 0:
                    jwt = login_data.get("data", {}).get("jwt")

            if not jwt:
                logger.log(f"[{short}] Ошибка логина: {login_data}", "error")
                return None

            # 2. Профиль
            auth_headers = {**headers, "Authorization": f"Bearer {jwt}"}
            profile_url = f"{PROFILE_URL}?address={address}"
            profile_data = await _request_with_retry(
                proxy_manager, address, wallet_index,
                "get", profile_url, auth_headers,
            )

            total_points = 0
            if isinstance(profile_data, dict) and profile_data.get("code") == 0:
                user_info = profile_data.get("data", {}).get("user_info", {})
                total_points = user_info.get("TotalPoints", 0) or 0
            else:
                logger.log(f"[{short}] Ошибка профиля: {profile_data}", "error")
                return None

            level = calculate_level(total_points, level_list)

            # 3. Квесты
            tasks_url = f"{USER_TASKS_URL}?address={address}"
            tasks_data = await _request_with_retry(
                proxy_manager, address, wallet_index,
                "get", tasks_url, auth_headers,
            )

            completed_ids = set()
            if isinstance(tasks_data, dict) and tasks_data.get("code") == 0:
                user_tasks = tasks_data.get("data", {}).get("user_tasks", [])
                for task in user_tasks:
                    if isinstance(task, dict):
                        tid = task.get("TaskId") or task.get("task_id")
                        if tid is not None:
                            completed_ids.add(int(tid))

            known = set(ALL_TASK_IDS)
            done = known & completed_ids
            not_done = known - completed_ids
            quests_done = len(done)
            quests_total = len(known)

            logger.log(
                f"[{short}] XP: {total_points}, Level: {level}, "
                f"Квесты: {quests_done}/{quests_total}",
                "success",
            )
            return {
                "address": address,
                "xp": total_points,
                "lvl": level,
                "quests_done": quests_done,
                "quests_total": quests_total,
                "quests_not_done": sorted(not_done),
            }

        except Exception as e:
            logger.log(f"[{short}] Ошибка ({RETRY_COUNT} попыток): {e}", "error")
            return None


async def collect_stats(wallets: list[dict], max_workers: int = NUM_THREADS) -> list[dict]:
    """Собрать статистику по всем кошелькам параллельно."""
    proxy_manager = PharosProxyManager()
    semaphore = asyncio.Semaphore(max_workers)

    logger.log("Загрузка таблицы уровней...", "cycle")
    level_list = await fetch_level_list(proxy_manager)

    if level_list:
        logger.log(f"Уровней загружено: {len(level_list)} (макс. {level_list[-1]['name']})", "info")
    else:
        logger.log("Не удалось загрузить уровни, будет Lv.1 по умолчанию", "warning")

    tasks = []
    for i, w in enumerate(wallets):
        t = asyncio.create_task(
            get_wallet_stats(w["private_key"], proxy_manager, i, level_list, semaphore)
        )
        tasks.append(t)

    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


def export_csv(stats: list[dict], filename: str = None):
    """Экспортировать статистику в CSV файл."""
    if not stats:
        logger.log("Нет данных для экспорта", "warning")
        return

    if filename is None:
        filename = STATS_FILE

    # Создать директорию если нужно
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["address", "xp", "lvl", "quests_done", "quests_total", "quests_not_done"])
        for s in stats:
            not_done_str = ";".join(str(x) for x in s.get("quests_not_done", []))
            writer.writerow([
                s["address"], s["xp"], s["lvl"],
                s.get("quests_done", 0), s.get("quests_total", 0),
                not_done_str,
            ])

    logger.log(f"Статистика сохранена в {filename} ({len(stats)} аккаунтов)", "success")
