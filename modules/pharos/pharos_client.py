"""Клиент для взаимодействия с Pharos Testnet API."""
import json
import ssl
import asyncio
import random
from datetime import datetime

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from eth_account import Account
from eth_account.messages import encode_defunct
from fake_useragent import FakeUserAgent

from config.modules.cfg_pharos import (
    BASE_URL, DEFAULT_HEADERS, REF_CODE, REQUEST_TIMEOUT,
    VERIFIABLE_TASK_IDS, ALL_TASK_IDS, FOLLOW_SUB_TASK_IDS,
    FAROSWAP_FAUCET_URL, FAROSWAP_CHAIN_ID,
    FAROSWAP_CAPTCHA_URL, FAROSWAP_WEBSITE_KEY,
    EXPLORER_URL,
)
from config.modules.cfg_base import RETRY_COUNT
from config.modules.cfg_base import SLEEP_BETWEEN_ACTIONS as DELAY_BETWEEN_ACTIONS
from modules.pharos.pharos_proxy import PharosProxyManager
from modules.captcha import get_captcha_solver
from modules.pharos import pharos_logger as logger
from modules.pharos import database as db

# SSL контекст с отключённой верификацией (для совместимости с прокси)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


class PharosClient:
    """Клиент для одного кошелька."""

    def __init__(self, private_key: str, proxy_manager: PharosProxyManager, wallet_index: int = 0):
        self.private_key = private_key
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.proxy_manager = proxy_manager
        self.wallet_index = wallet_index
        self.jwt_token: str | None = None
        self.user_agent = FakeUserAgent().random
        self.proxy = proxy_manager.get_proxy_for_wallet(self.address, wallet_index)

    def _short(self) -> str:
        return f"{self.address[:6]}...{self.address[-4:]}"

    def log(self, msg: str, level: str = "info"):
        logger.log(msg, level, self.address)

    def _get_headers(self, with_auth: bool = True) -> dict:
        headers = {**DEFAULT_HEADERS, "User-Agent": self.user_agent}
        if with_auth and self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"
        return headers

    # ─────────────────── HTTP ───────────────────
    async def _request(self, method: str, url: str, data: dict = None,
                       with_auth: bool = True, retries: int = None) -> dict | None:
        if retries is None:
            retries = RETRY_COUNT

        headers = self._get_headers(with_auth)
        proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)

        for attempt in range(retries):
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
                    kwargs = {"url": url, "headers": headers}
                    if not socks_url:
                        kwargs["proxy"] = proxy_config.get("proxy")
                        kwargs["proxy_auth"] = proxy_config.get("proxy_auth")
                    if method.lower() == "post":
                        kwargs["data"] = json.dumps(data) if data else "{}"

                    async with getattr(session, method.lower())(**kwargs) as resp:
                        resp.raise_for_status()
                        return await resp.json()

            except Exception as e:
                if attempt < retries - 1:
                    old_proxy = self.proxy
                    self.proxy = self.proxy_manager.rotate_proxy(self.address)
                    proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
                    if old_proxy != self.proxy:
                        db.update_proxy(self.address, self.proxy or "")
                        self.log(f"Прокси сменён -> {self.proxy[:30] if self.proxy else 'нет'}...", "warning")
                    await asyncio.sleep(3)
                else:
                    self.log(f"Запрос неудачен ({retries} попыток): {str(e)[:80]}", "error")
        return None

    # ─────────────────── AUTH ───────────────────
    async def login(self) -> bool:
        try:
            message = encode_defunct(text="pharos")
            signed = self.account.sign_message(message)
            signature = signed.signature.hex()
            url = f"{BASE_URL}/user/login?address={self.address}&signature={signature}&invite_code={REF_CODE}"

            result = await self._request("post", url, with_auth=False)
            if result and result.get("data", {}).get("jwt"):
                self.jwt_token = result["data"]["jwt"]
                db.update_jwt(self.address, self.jwt_token)
                self.log("Авторизация успешна", "success")
                return True

            msg = result.get("msg", "unknown") if result else "нет ответа"
            self.log(f"Ошибка авторизации: {msg}", "error")
            return False
        except Exception as e:
            self.log(f"Ошибка авторизации: {e}", "error")
            return False

    # ─────────────────── CHECK-IN ───────────────────
    async def check_in(self) -> bool:
        try:
            status = await self._request("get", f"{BASE_URL}/sign/status?address={self.address}")
            if status and status.get("data", {}).get("status"):
                status_str = str(status["data"]["status"])
                if status_str and status_str[-1] == "0":
                    self.log("Чек-ин уже выполнен сегодня", "warning")
                    db.update_checkin_status(self.address, "done")
                    return True

            result = await self._request("post", f"{BASE_URL}/sign/in?address={self.address}")
            if result and result.get("msg") == "ok":
                self.log("Чек-ин выполнен!", "success")
                db.update_checkin_status(self.address, "done")
                return True
            if result and "already" in str(result.get("msg", "")).lower():
                self.log("Чек-ин уже выполнен", "warning")
                db.update_checkin_status(self.address, "done")
                return True

            msg = result.get("msg", "failed") if result else "no response"
            self.log(f"Чек-ин неудачен: {msg}", "error")
            return False
        except Exception as e:
            self.log(f"Ошибка чек-ина: {e}", "error")
            return False

    # ─────────────────── PHAROS FAUCET ───────────────────
    async def claim_faucet(self) -> bool:
        try:
            status = await self._request("get", f"{BASE_URL}/faucet/status?address={self.address}")
            if not status:
                self.log("Не удалось получить статус крана", "error")
                return False

            is_able = status.get("data", {}).get("is_able_to_faucet", False)
            if not is_able:
                ts = status.get("data", {}).get("avaliable_timestamp")
                if ts:
                    next_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                    self.log(f"Pharos кран: кулдаун до {next_time}", "warning")
                else:
                    self.log("Pharos кран: недоступен", "warning")
                db.update_faucet_status(self.address, "cooldown")
                return False

            result = await self._request(
                "post", f"{BASE_URL}/faucet/daily?address={self.address}",
                data={"address": self.address},
            )
            if not result or (result and result.get("code") == 1):
                result = await self._request("post", f"{BASE_URL}/faucet/daily?address={self.address}")

            if result and result.get("msg") == "ok":
                self.log("Pharos кран: токены получены!", "success")
                db.update_faucet_status(self.address, "claimed", datetime.now().isoformat())
                return True

            msg = result.get("msg", "failed") if result else "no response"
            if result and "not bound" in str(msg).lower():
                self.log("Pharos кран: требуется привязка X/Twitter", "warning")
                db.update_faucet_status(self.address, "need_twitter")
                return False

            self.log(f"Pharos кран: {msg}", "error")
            return False
        except Exception as e:
            self.log(f"Ошибка Pharos крана: {e}", "error")
            return False

    # ─────────────────── FAROSWAP FAUCET ───────────────────
    async def claim_faroswap_faucet(self) -> bool:
        try:
            self.log("FaroSwap: решаем капчу...")
            solver = get_captcha_solver(self.proxy)
            if not solver:
                self.log("FaroSwap: сервис капчи не настроен (нет API ключа)", "error")
                db.update_faroswap_faucet_status(self.address, "captcha_fail")
                return False
            turnstile_token = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: solver.solve_turnstile(
                    sitekey=FAROSWAP_WEBSITE_KEY,
                    pageurl=FAROSWAP_CAPTCHA_URL,
                )
            )
            if not turnstile_token:
                self.log("FaroSwap: капча не решена", "error")
                db.update_faroswap_faucet_status(self.address, "captcha_fail")
                return False

            self.log("FaroSwap: капча решена, клеймим...")
            payload = {
                "chainId": FAROSWAP_CHAIN_ID,
                "address": self.address,
                "turnstileToken": turnstile_token,
            }
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://faroswap.xyz",
                "Referer": "https://faroswap.xyz/",
                "User-Agent": self.user_agent,
            }

            proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
            socks_url = proxy_config.get("socks_url")

            consecutive_fails = 0
            for attempt in range(RETRY_COUNT):
                try:
                    conn = None
                    if socks_url:
                        from aiohttp_socks import ProxyConnector
                        conn = ProxyConnector.from_url(socks_url, ssl=_ssl_ctx)
                    else:
                        conn = TCPConnector(ssl=_ssl_ctx)

                    async with ClientSession(
                        connector=conn,
                        timeout=ClientTimeout(total=REQUEST_TIMEOUT),
                    ) as session:
                        kwargs = {"url": FAROSWAP_FAUCET_URL, "headers": headers, "data": json.dumps(payload)}
                        if not socks_url:
                            kwargs["proxy"] = proxy_config.get("proxy")
                            kwargs["proxy_auth"] = proxy_config.get("proxy_auth")

                        async with session.post(**kwargs) as resp:
                            result = await resp.json()
                            code = result.get("code", -1)

                            if code == 0:
                                tx = result.get("data", {}).get("txHash", "")
                                self.log(f"FaroSwap: получено! TX: {EXPLORER_URL}{tx}", "success")
                                db.update_faroswap_faucet_status(self.address, "claimed", datetime.now().isoformat())
                                return True
                            else:
                                msg = result.get("msg", result.get("message", str(result)))
                                msg_lower = str(msg).lower()
                                # IP лимит — меняем прокси и пробуем снова
                                if "ip request limit" in msg_lower or ("ip" in msg_lower and "limit" in msg_lower):
                                    consecutive_fails += 1
                                    self.log(f"FaroSwap: IP лимит ({consecutive_fails}/{RETRY_COUNT}), смена прокси...", "warning")
                                    if consecutive_fails >= RETRY_COUNT:
                                        self.log(f"FaroSwap: {RETRY_COUNT} IP-лимитов подряд, пропуск", "error")
                                        db.update_faroswap_faucet_status(self.address, "ip_limit")
                                        return False
                                    self.proxy = self.proxy_manager.rotate_proxy(self.address)
                                    proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
                                    socks_url = proxy_config.get("socks_url")
                                    db.update_proxy(self.address, self.proxy or "")
                                    await asyncio.sleep(2)
                                    continue
                                # Настоящий кулдаун — не ретраим
                                if any(kw in msg_lower for kw in ["cooldown", "wait", "hour", "already", "too frequent"]):
                                    self.log(f"FaroSwap: кулдаун — {msg}", "warning")
                                    db.update_faroswap_faucet_status(self.address, "cooldown")
                                    return False
                                self.log(f"FaroSwap: ошибка — {msg}", "error")
                                consecutive_fails += 1

                except Exception as e:
                    consecutive_fails += 1
                    if attempt < RETRY_COUNT - 1:
                        old = self.proxy
                        self.proxy = self.proxy_manager.rotate_proxy(self.address)
                        proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
                        socks_url = proxy_config.get("socks_url")
                        if old != self.proxy:
                            db.update_proxy(self.address, self.proxy or "")
                        await asyncio.sleep(3)
                    else:
                        self.log(f"FaroSwap: {RETRY_COUNT} попыток: {str(e)[:80]}", "error")

            db.update_faroswap_faucet_status(self.address, "failed")
            return False
        except Exception as e:
            self.log(f"FaroSwap: критическая ошибка — {e}", "error")
            db.update_faroswap_faucet_status(self.address, "failed")
            return False

    # ─────────────────── PROFILE & QUESTS ───────────────────
    async def get_profile(self) -> dict | None:
        result = await self._request("get", f"{BASE_URL}/user/profile?address={self.address}")
        if result and result.get("msg") == "ok":
            return result.get("data", {})
        return None

    async def get_tasks(self) -> tuple[list, set]:
        result = await self._request("get", f"{BASE_URL}/user/tasks?address={self.address}")
        if not result or not result.get("data"):
            return [], set()

        user_tasks = result.get("data", {}).get("user_tasks", [])
        completed_ids = set()
        for task in user_tasks:
            if isinstance(task, dict):
                tid = task.get("TaskId") or task.get("task_id") or task.get("id")
                if tid is not None:
                    completed_ids.add(int(tid))
            elif isinstance(task, (int, str)):
                completed_ids.add(int(task))
        return user_tasks, completed_ids

    async def follow_task(self, task_id: int) -> bool:
        """Проклацать квест через /task/follow."""
        url = f"{BASE_URL}/task/follow"
        body = {"task_id": task_id, "address": self.address}
        result = await self._request("post", url, data=body)
        if result and result.get("code") == 0:
            return True
        return False

    async def verify_task(self, task_id: int) -> tuple[bool, str, list]:
        url = f"{BASE_URL}/task/verify?address={self.address}&task_id={task_id}"
        body = {"address": self.address, "task_id": task_id}
        result = await self._request("post", url, data=body)
        if result:
            msg = result.get("msg", "")
            code = result.get("code", -1)
            items = result.get("items", [])
            if code == 0 or msg in ("ok", "success"):
                return True, msg, items or []
            if "already completed" in msg.lower():
                return True, msg, []
            return False, msg, []
        return False, "no response", []

    async def complete_quests(self) -> dict:
        stats = {"verified": 0, "skipped": 0, "failed": 0, "already_done": 0}

        profile = await self.get_profile()
        if profile:
            user_info = profile.get("user_info", {})
            points = user_info.get("TotalPoints", 0)
            db.update_wallet(self.address, total_points=points)

        _, completed_ids = await self.get_tasks()
        local_completed = db.get_completed_quests(self.address)
        all_completed = completed_ids.union(set(local_completed))

        # API никогда не возвращает 205 в completed — считаем выполненным,
        # если все суб-квесты (301-304) уже завершены
        all_subs_done = all(tid in all_completed for tid in FOLLOW_SUB_TASK_IDS)
        if all_subs_done:
            all_completed.add(205)

        # --- Шаг 1: Follow (проклацать) суб-квесты ---
        follow_ids = [201] + FOLLOW_SUB_TASK_IDS
        follow_needed = [tid for tid in follow_ids if tid not in all_completed]

        if follow_needed:
            self.log(f"Проклацываем {len(follow_needed)} follow-квестов...")
            for task_id in follow_needed:
                ok = await self.follow_task(task_id)
                if ok:
                    self.log(f"  Follow #{task_id}: ок", "success")
                else:
                    self.log(f"  Follow #{task_id}: ошибка", "warning")
                await asyncio.sleep(1)

        # --- Шаг 2: Verify квестов ---
        sub_tasks_missing = any(tid not in all_completed for tid in FOLLOW_SUB_TASK_IDS)
        force_verify_205 = bool(follow_needed) or sub_tasks_missing

        verify_order = [205, 202, 203]
        tasks_to_verify = []
        for tid in verify_order:
            if tid == 205 and force_verify_205:
                tasks_to_verify.append(tid)
            elif tid not in all_completed:
                tasks_to_verify.append(tid)

        if 204 not in all_completed:
            tasks_to_verify.append(204)

        if not tasks_to_verify and not follow_needed:
            self.log("Все квесты уже выполнены", "success")
            stats["already_done"] = len(ALL_TASK_IDS)
            return stats

        if tasks_to_verify:
            self.log(f"Верифицируем {len(tasks_to_verify)} квестов...")

        for task_id in tasks_to_verify:
            await asyncio.sleep(2)
            success, msg, items = await self.verify_task(task_id)

            if success:
                self.log(f"Квест #{task_id} выполнен!", "success")
                all_completed.add(task_id)
                stats["verified"] += 1
                if items:
                    for item in items:
                        sub_id = item.get("task_id")
                        sub_ok = item.get("completed", False)
                        if sub_id and sub_ok:
                            all_completed.add(int(sub_id))
                            self.log(f"  └─ Суб-квест #{sub_id} выполнен", "success")
                            stats["verified"] += 1
                        elif sub_id and not sub_ok:
                            self.log(f"  └─ Суб-квест #{sub_id} не выполнен", "warning")
            elif "already completed" in msg.lower():
                all_completed.add(task_id)
                stats["already_done"] += 1
            elif "invalid task_id" in msg:
                stats["skipped"] += 1
            elif "not bound" in msg.lower():
                self.log(f"Квест #{task_id}: требуется привязка ({msg})", "warning")
                stats["skipped"] += 1
            else:
                self.log(f"Квест #{task_id}: {msg}", "warning")
                stats["failed"] += 1

        db.update_quests(self.address, list(all_completed))
        return stats

    # ─────────────────── WORKFLOWS ───────────────────
    async def run_checkin_workflow(self) -> bool:
        """Только чек-ин: авторизация → ежедневный чек-ин."""
        if not await self.login():
            return False
        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACTIONS))
        return await self.check_in()

    async def run_faucet_workflow(self) -> bool:
        """Только краны: авторизация → Pharos кран → FaroSwap кран."""
        if not await self.login():
            return False
        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACTIONS))
        await self.claim_faucet()
        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACTIONS))
        await self.claim_faroswap_faucet()
        return True

    async def run_all_faucet_workflow(self) -> bool:
        """Полный цикл: авторизация → чек-ин → Pharos кран → FaroSwap кран."""
        if not await self.login():
            return False
        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACTIONS))
        await self.check_in()
        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACTIONS))
        await self.claim_faucet()
        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACTIONS))
        await self.claim_faroswap_faucet()
        return True

    async def run_quest_workflow(self) -> dict:
        """Полный цикл квестов: авторизация → выполнение."""
        if not await self.login():
            return {"error": "auth_failed"}
        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_ACTIONS))
        return await self.complete_quests()
