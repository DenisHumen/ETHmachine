"""Клиент для взаимодействия с xStocks DeFi Points.

API: https://api.backed.fi/xdrop-api/api/v1
Подписание: personal_sign (EVM) / solana_signMessage (Solana) с timestamp.
Капча: Cloudflare Turnstile (при 403).
"""
import ssl
import asyncio
import random
import time
from datetime import datetime, timedelta

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from eth_account import Account
from eth_account.messages import encode_defunct
from fake_useragent import FakeUserAgent

from config.modules.cfg_xstocks import (
    BASE_URL, API_BASE_URL, DEFAULT_HEADERS, REQUEST_TIMEOUT,
    SIGN_MESSAGES, GM_COOLDOWN_HOURS,
)
from config.modules.cfg_base import RETRY_COUNT, SLEEP_BETWEEN_ACTIONS
from modules.xstocks.xstocks_proxy import XStocksProxyManager
from modules.xstocks import xstocks_logger as logger
from modules.xstocks import database as db

# SSL контекст (для совместимости с прокси)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# Turnstile site key (загружается при первом запросе к /xdrop-config)
_turnstile_site_key: str | None = None


class XStocksClient:
    """Клиент для одного кошелька."""

    def __init__(self, private_key: str, proxy_manager: XStocksProxyManager,
                 wallet_index: int = 0, sol_private_key: str = None,
                 account_name: str = None, task_index: int = None, task_total: int = None):
        self.private_key = private_key
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.proxy_manager = proxy_manager
        self.wallet_index = wallet_index
        self.proxy = proxy_manager.get_proxy_for_wallet(private_key, self.address, wallet_index)

        # Загрузить сессию из БД (user_agent, cookies, browser_data)
        session_data = db.get_session(self.address)
        if session_data and session_data.get("user_agent"):
            self.user_agent = session_data["user_agent"]
            self._session_valid = True
        else:
            self.user_agent = FakeUserAgent().random
            self._session_valid = False
            # Сохранить новый user_agent в БД
            db.save_session(self.address, user_agent=self.user_agent)

        # Solana
        self.sol_private_key = sol_private_key
        self.sol_keypair = None
        self.sol_address = None
        if sol_private_key:
            self._init_solana(sol_private_key)

        self.referral_code: str | None = None

        # Logging context
        self.account_name = account_name
        self.task_index = task_index
        self.task_total = task_total

    def _init_solana(self, sol_private_key: str):
        """Инициализировать Solana keypair."""
        try:
            import base58
            from solders.keypair import Keypair
            key_bytes = base58.b58decode(sol_private_key)
            self.sol_keypair = Keypair.from_bytes(key_bytes)
            self.sol_address = str(self.sol_keypair.pubkey())
        except Exception as e:
            self.log(f"Ошибка инициализации Solana: {e}", "warning")

    def _short(self) -> str:
        return self.address

    def log(self, msg: str, level: str = "info"):
        logger.log(msg, level, self._short(),
                   index=self.task_index, total=self.task_total,
                   account_name=self.account_name)

    def _get_headers(self, captcha_token: str = None) -> dict:
        headers = {**DEFAULT_HEADERS, "User-Agent": self.user_agent}
        if captcha_token:
            headers["x-captcha-token"] = captcha_token
        return headers

    # ─────────────────── HTTP ───────────────────

    async def _request(self, method: str, url: str, data: dict = None,
                       retries: int = None) -> dict | None:
        """Выполнить HTTP-запрос с ретраями, ротацией прокси и решением капчи."""
        if retries is None:
            retries = RETRY_COUNT

        proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
        captcha_token = None

        for attempt in range(retries + 1):
            connector = None
            try:
                socks_url = proxy_config.get("socks_url")
                if socks_url:
                    from aiohttp_socks import ProxyConnector
                    connector = ProxyConnector.from_url(socks_url, ssl=_ssl_ctx)
                else:
                    connector = TCPConnector(ssl=_ssl_ctx)

                timeout = ClientTimeout(total=REQUEST_TIMEOUT)
                headers = self._get_headers(captcha_token)

                async with ClientSession(
                    connector=connector,
                    timeout=timeout,
                    headers=headers,
                ) as session:
                    kwargs = {}
                    if data is not None:
                        kwargs["json"] = data
                    if proxy_config.get("proxy"):
                        kwargs["proxy"] = proxy_config["proxy"]
                    if proxy_config.get("proxy_auth"):
                        kwargs["proxy_auth"] = proxy_config["proxy_auth"]

                    async with session.request(method, url, **kwargs) as resp:
                        if resp.status in (200, 201):
                            try:
                                return await resp.json()
                            except Exception:
                                text = await resp.text()
                                return {"raw": text, "status": resp.status}

                        elif resp.status == 403:
                            try:
                                body = await resp.json()
                            except Exception:
                                body = {}
                            if "captcha" in str(body).lower():
                                self.log("Требуется Turnstile капча, решаем...", "warning")
                                captcha_token = await self._solve_turnstile()
                                if captcha_token:
                                    continue
                                else:
                                    self.log("Не удалось решить капчу", "error")
                                    return None
                            text = await resp.text()
                            self.log(f"HTTP 403: {text[:200]}", "warning")

                        elif resp.status == 400:
                            # 400 = ошибка бизнес-логики, ретрай не поможет
                            try:
                                return await resp.json()
                            except Exception:
                                text = await resp.text()
                                self.log(f"HTTP 400: {text[:200]}", "warning")
                                return None

                        elif resp.status == 429:
                            self.log(f"Rate limit, ждём 30с (попытка {attempt+1})", "warning")
                            await asyncio.sleep(30)
                            continue

                        else:
                            text = await resp.text()
                            self.log(f"HTTP {resp.status}: {text[:200]}", "warning")

                        if attempt < retries:
                            self.proxy = self.proxy_manager.rotate_proxy(
                                self.private_key, self.address)
                            proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
                            self.log(f"Ротация прокси, попытка {attempt+2}", "warning")
                        continue

            except Exception as e:
                self.log(f"Ошибка запроса: {e} (попытка {attempt+1})", "error")
                if attempt < retries:
                    self.proxy = self.proxy_manager.rotate_proxy(self.private_key, self.address)
                    proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
                    await asyncio.sleep(random.uniform(2, 5))
            finally:
                if connector and not connector.closed:
                    await connector.close()

        return None

    async def _get(self, url: str, **kwargs) -> dict | None:
        return await self._request("GET", url, **kwargs)

    async def _post(self, url: str, data: dict = None, **kwargs) -> dict | None:
        return await self._request("POST", url, data=data, **kwargs)

    async def _put(self, url: str, data: dict = None, **kwargs) -> dict | None:
        return await self._request("PUT", url, data=data, **kwargs)

    # ─────────────────── Captcha ───────────────────

    async def _solve_turnstile(self) -> str | None:
        """Решить Cloudflare Turnstile через внешний сервис."""
        global _turnstile_site_key
        if not _turnstile_site_key:
            config = await self._get_xdrop_config()
            if config:
                _turnstile_site_key = config.get("turnstileSiteKey")
        if not _turnstile_site_key:
            self.log("Turnstile site key не найден", "error")
            return None
        try:
            from modules.captcha import CaptchaManager
            manager = CaptchaManager(proxy=self.proxy)
            if not manager.is_available:
                self.log("Captcha solver не настроен (нет API ключа)", "error")
                return None
            token = manager.solve_turnstile(
                sitekey=_turnstile_site_key,
                pageurl=f"{BASE_URL}/points",
                user_agent=self.user_agent,
            )
            if token:
                self.log("Turnstile капча решена", "success")
            return token
        except Exception as e:
            self.log(f"Ошибка решения капчи: {e}", "error")
            return None

    # ─────────────────── EVM Signing ───────────────────

    def _sign_with_timestamp(self, message: str) -> tuple[str, int]:
        """Подписать сообщение с меткой времени.
        Формат: "{message} | {unix_timestamp}"
        Возвращает (signature_hex_with_0x, timestamp)."""
        ts = int(time.time())
        full_msg = f"{message} | {ts}"
        msg_encoded = encode_defunct(text=full_msg)
        signed = self.account.sign_message(msg_encoded)
        sig = signed.signature.hex()
        # API ожидает подпись С 0x префиксом (HexBytes.hex() уже включает его)
        return sig, ts

    # ─────────────────── Solana Signing ───────────────────

    def _sign_solana_with_timestamp(self, message: str) -> tuple[str, int] | tuple[None, None]:
        """Подписать сообщение Solana кошельком с меткой времени."""
        if not self.sol_keypair:
            return None, None
        try:
            import base58
            ts = int(time.time())
            full_msg = f"{message} | {ts}"
            msg_bytes = full_msg.encode('utf-8')
            signature = self.sol_keypair.sign_message(msg_bytes)
            sig_b58 = base58.b58encode(bytes(signature)).decode()
            return sig_b58, ts
        except Exception as e:
            self.log(f"Ошибка подписи Solana: {e}", "error")
            return None, None

    # ─────────────────── Задержка ───────────────────

    async def _delay(self, label: str = ""):
        """Случайная задержка между действиями."""
        delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
        if label:
            self.log(f"Задержка {delay:.1f}с ({label})")
        await asyncio.sleep(delay)

    # ─────────────────── Парсинг кулдауна ───────────────────

    @staticmethod
    def _parse_cooldown_hours(resp: dict) -> float:
        """Извлечь количество часов ожидания из ответа API.

        Ищет:
          - data.nextAvailableAt / data.nextGmAt (ISO timestamp)
          - data.cooldownHours / data.hoursRemaining (число)
          - текст вида 'See you in N hours' / 'N hours remaining'
          - message / error поля
        Если ничего не найдено — возвращает GM_COOLDOWN_HOURS из конфига.
        """
        import re

        if not resp or not isinstance(resp, dict):
            return GM_COOLDOWN_HOURS

        data = resp.get("data", {}) if isinstance(resp.get("data"), dict) else {}

        # 1. Прямое поле-timestamp
        for field in ("nextAvailableAt", "nextGmAt", "next_available_at", "nextGmAvailableAt"):
            ts_val = data.get(field)
            if ts_val:
                try:
                    next_dt = datetime.fromisoformat(str(ts_val).replace("Z", "+00:00"))
                    # Убираем tzinfo для сравнения с naive datetime
                    if next_dt.tzinfo:
                        next_dt = next_dt.replace(tzinfo=None)
                    diff = (next_dt - datetime.now()).total_seconds() / 3600
                    if diff > 0:
                        return diff
                except (ValueError, TypeError):
                    pass

        # 2. Прямое поле-число (часы)
        for field in ("cooldownHours", "hoursRemaining", "remainingHours", "cooldown_hours"):
            val = data.get(field)
            if val is not None:
                try:
                    h = float(val)
                    if h > 0:
                        return h
                except (ValueError, TypeError):
                    pass

        # 3. Парсинг текста «See you in N hours» из всех текстовых полей
        text_sources = [
            str(resp.get("message", "")),
            str(resp.get("error", "")),
            str(data.get("message", "")),
            str(resp),
        ]
        pattern = re.compile(r"(\d+)\s*hour", re.IGNORECASE)
        for text in text_sources:
            m = pattern.search(text)
            if m:
                return float(m.group(1))

        # 4. Парсинг минут (если < 1 часа)
        pattern_min = re.compile(r"(\d+)\s*min", re.IGNORECASE)
        for text in text_sources:
            m = pattern_min.search(text)
            if m:
                return float(m.group(1)) / 60

        return GM_COOLDOWN_HOURS

    # ─────────────────── Валидация сессии ───────────────────

    async def validate_session(self) -> bool:
        """Проверить валидность текущей сессии через лёгкий запрос.
        Возвращает True если сессия рабочая."""
        try:
            resp = await self._get(f"{API_BASE_URL}/xdrop-user/{self.address}")
            if resp and resp.get("success"):
                return True
        except Exception:
            pass
        return False

    async def ensure_session(self) -> bool:
        """Проверить сессию; если невалидна — переавторизоваться.
        Возвращает True при успешной авторизации."""
        if await self.validate_session():
            self.log("Сессия валидна", "info")
            return True

        self.log("Сессия невалидна, переавторизация...", "warning")
        # Переподписание (фактически re-auth — сайт stateless по подписи)
        ok = await self.register_evm()
        if ok:
            self.log("Переавторизация успешна", "success")
            # Сохранить актуальную сессию
            db.save_session(self.address, user_agent=self.user_agent)
        else:
            self.log("Переавторизация не удалась", "error")
        return ok

    # ===============================================================
    # API ENDPOINTS
    # ===============================================================

    async def _get_xdrop_config(self) -> dict | None:
        """GET /xdrop-config — конфигурация проекта."""
        resp = await self._get(f"{API_BASE_URL}/xdrop-config")
        if resp and resp.get("success"):
            return resp.get("data", {})
        return None

    async def register_evm(self, referral_code: str = None) -> bool:
        """POST /xdrop-user — Регистрация EVM кошелька.
        Подписывает REGISTRATION сообщение и создаёт пользователя."""
        self.log("Регистрация EVM кошелька...")

        signature, ts = self._sign_with_timestamp(SIGN_MESSAGES["REGISTRATION"])

        payload = {
            "walletAddress": self.address,
            "walletType": "Evm",
            "signature": signature,
            "signMethod": "message",
            "signTimestamp": ts,
        }
        if referral_code:
            payload["referredBy"] = referral_code
            self.log(f"Реферальный код: {referral_code}")

        resp = await self._post(f"{API_BASE_URL}/xdrop-user", data=payload)

        if resp and resp.get("success"):
            data = resp.get("data", {})
            ref_code = data.get("referralCode")

            # POST /xdrop-user не возвращает referralCode — подгружаем через GET
            if not ref_code:
                user_info = await self.get_user_info()
                if user_info:
                    ref_code = user_info.get("referralCode")

            ref_link = f"{BASE_URL}/points?ref={ref_code}" if ref_code else None
            db.mark_evm_registered(self.address, referral_link=ref_link, referral_code=ref_code)
            if ref_code:
                db.save_referral_code(self.address, ref_code, ref_link)
                self.referral_code = ref_code
            if referral_code:
                db.increment_referral_usage(referral_code)
                db.update_wallet(self.address, used_referral_code=referral_code)

            self.log(f"Регистрация успешна! Реф. код: {ref_code}", "success")
            return True

        # Может уже зарегистрирован
        if resp and "already" in str(resp).lower():
            self.log("Уже зарегистрирован", "warning")
            await self.get_user_info()
            return True

        self.log(f"Ошибка регистрации: {resp}", "error")
        return False

    async def register_solana(self, referral_code: str = None) -> bool:
        """POST /xdrop-user — Регистрация Solana кошелька (walletType: Svm)."""
        if not self.sol_keypair or not self.sol_address:
            self.log("Solana ключ не указан, пропускаем", "warning")
            return False

        self.log(f"Регистрация Solana: {self.sol_address[:8]}...")

        signature, ts = self._sign_solana_with_timestamp(SIGN_MESSAGES["REGISTRATION"])
        if not signature:
            self.log("Не удалось подписать Solana сообщение", "error")
            return False

        payload = {
            "walletAddress": self.sol_address,
            "walletType": "Svm",
            "signature": signature,
            "signMethod": "message",
            "signTimestamp": ts,
        }
        if referral_code:
            payload["referredBy"] = referral_code

        resp = await self._post(f"{API_BASE_URL}/xdrop-user", data=payload)

        if resp and resp.get("success"):
            db.mark_sol_connected(self.address, True)
            self.log(f"Solana зарегистрирован: {self.sol_address[:8]}...", "success")
            return True

        if resp and "already" in str(resp).lower():
            db.mark_sol_connected(self.address, True)
            self.log("Solana уже зарегистрирован", "warning")
            return True

        self.log(f"Ошибка регистрации Solana: {resp}", "error")
        return False

    async def get_user_info(self) -> dict | None:
        """GET /xdrop-user/{addr} — Информация о пользователе."""
        resp = await self._get(f"{API_BASE_URL}/xdrop-user/{self.address}")

        if resp and resp.get("success"):
            data = resp.get("data", {})
            ref_code = data.get("referralCode")
            if ref_code:
                self.referral_code = ref_code
                ref_link = f"{BASE_URL}/points?ref={ref_code}"
                db.mark_evm_registered(self.address, referral_link=ref_link, referral_code=ref_code)
                db.save_referral_code(self.address, ref_code, ref_link)

            # Обновить статистику из user info
            db.update_stats(
                self.address,
                today_points=int(float(data.get("totalBasePoints", 0))),
            )
            return data

        # 404 = не зарегистрирован
        return None

    async def get_dashboard(self) -> dict:
        """GET /xdrop-user/{addr}/dashboard — Дашборд с очками, бустом, GM."""
        resp = await self._get(f"{API_BASE_URL}/xdrop-user/{self.address}/dashboard")

        stats = {}
        if resp and resp.get("success"):
            data = resp.get("data", {})

            stats["total_points"] = data.get("totalPoints", "0")
            stats["quest_points"] = data.get("questPoints", "0")
            stats["xboost_multiplier"] = data.get("xboostMultiplier", "1")
            stats["daily_spin_multiplier"] = data.get("dailySpinMultiplier", "1")
            stats["daily_spin_revealed"] = data.get("dailySpinMultiplierRevealed", False)
            stats["current_snapshot"] = data.get("currentSnapshotNumber")
            stats["latest_user_snapshot"] = data.get("latestUserSnapshotNumber")
            stats["last_spin_snapshot"] = data.get("lastSpinSnapshotNumber")

            db.update_stats(
                self.address,
                xboost=str(stats.get("xboost_multiplier", "1")),
                today_points=int(float(stats.get("total_points", 0))),
            )

            self.log(
                f"Dashboard: {stats['total_points']} pts | "
                f"xBoost: x{stats['xboost_multiplier']} | "
                f"Spin: x{stats['daily_spin_multiplier']} | "
                f"Snapshot: #{stats.get('current_snapshot', '?')}"
            )
        return stats

    async def say_gm(self) -> dict:
        """POST /xdrop-user/say-gm — Say GM с подписью."""
        self.log("Say GM...")

        signature, ts = self._sign_with_timestamp(SIGN_MESSAGES["SAY_GM"])

        payload = {
            "walletAddress": self.address,
            "signature": signature,
            "signMethod": "message",
            "signTimestamp": ts,
        }

        resp = await self._post(f"{API_BASE_URL}/xdrop-user/say-gm", data=payload)

        result = {"success": False, "next_gm_at": None}
        now = datetime.now()

        if resp and resp.get("success"):
            data = resp.get("data", {})
            points_added = data.get("totalPointsAdded") or data.get("pointsAdded", 0)
            clicks_remaining = data.get("clicksRemaining", 0)

            # Парсим кулдаун из ответа API, если есть
            cooldown_hours = self._parse_cooldown_hours(resp)
            # Добавляем случайный разброс 1-2ч
            jitter_hours = random.uniform(1, 2)
            next_gm = (now + timedelta(hours=cooldown_hours + jitter_hours)).isoformat()

            gm_at = now.isoformat()
            db.update_gm(self.address, gm_at, next_gm)
            db.record_gm_history(self.address, gm_at, next_gm, success=True)
            db.log_action(self.address, "gm", "success")

            self.log(
                f"GM успешно! +{points_added} pts | "
                f"Осталось кликов: {clicks_remaining} | "
                f"Следующий: {next_gm[:16]} (+{jitter_hours:.1f}ч jitter)",
                "success"
            )
            result["success"] = True
            result["next_gm_at"] = next_gm
            result["points_added"] = points_added

        elif resp and ("cooldown" in str(resp).lower() or "already" in str(resp).lower()
                       or "limit" in str(resp).lower()):
            # Парсим оставшееся время кулдауна из ответа
            cooldown_hours = self._parse_cooldown_hours(resp)
            jitter_hours = random.uniform(1, 2)
            next_gm = (now + timedelta(hours=cooldown_hours + jitter_hours)).isoformat()
            db.update_wallet(self.address, next_gm_at=next_gm)
            self.log(
                f"GM на кулдауне ({cooldown_hours:.1f}ч). "
                f"Следующий: {next_gm[:16]} (+{jitter_hours:.1f}ч jitter)",
                "warning"
            )
            result["next_gm_at"] = next_gm
        else:
            db.record_gm_history(self.address, now.isoformat(), None, success=False,
                                 error=str(resp)[:200] if resp else "no response")
            self.log(f"Ошибка Say GM: {resp}", "error")

        return result

    async def reveal_daily_spin(self, dashboard: dict = None) -> dict | None:
        """PUT /xdrop-user/daily-spin-multiplier — Раскрыть ежедневный спин.
        Пропускает если спин уже раскрыт или snapshot ещё не доступен."""
        # Проверить доступность по данным dashboard
        if dashboard:
            if dashboard.get("daily_spin_revealed"):
                self.log("Daily spin уже раскрыт", "info")
                return None
            current = dashboard.get("current_snapshot")
            last_spin = dashboard.get("last_spin_snapshot")
            if current is not None and last_spin is not None and current <= last_spin:
                self.log("Daily spin: ожидание следующего snapshot", "info")
                return None

        self.log("Reveal daily spin multiplier...")

        signature, ts = self._sign_with_timestamp(SIGN_MESSAGES["DAILY_SPIN_MULTIPLIER"])

        payload = {
            "walletAddress": self.address,
            "signature": signature,
            "signMethod": "message",
            "signTimestamp": ts,
        }

        resp = await self._put(f"{API_BASE_URL}/xdrop-user/daily-spin-multiplier", data=payload)

        if resp and resp.get("success"):
            data = resp.get("data", {})
            multiplier = data.get("newDailySpinMultiplier")
            pts_diff = data.get("pointsDifference", 0)
            self.log(f"Spin: x{multiplier} | +{pts_diff} pts", "success")
            return data

        # Ожидаемые ошибки — не логировать как проблему
        error_msg = str(resp.get("error", "")) if resp else ""
        if "snapshot" in error_msg.lower() or "not found" in error_msg.lower():
            self.log("Daily spin пока недоступен (нет snapshot)", "info")
        else:
            self.log(f"Ошибка spin: {error_msg or resp}", "warning")
        return None

    async def get_points_breakdown(self) -> dict | None:
        """GET /xdrop-user/{addr}/points-breakdown — Детальная разбивка очков."""
        resp = await self._get(f"{API_BASE_URL}/xdrop-user/{self.address}/points-breakdown")
        if resp and resp.get("success"):
            return resp.get("data", {})
        return None

    # ===============================================================
    # ПОЛНЫЕ WORKFLOW
    # ===============================================================

    async def run_registration_workflow(self, referral_code: str = None) -> bool:
        """Полный воркфлоу: регистрация EVM -> Solana -> dashboard."""
        self.log("=== Начало регистрации ===")

        # Шаг 1: Регистрация EVM
        if not await self.register_evm(referral_code):
            db.log_action(self.address, "registration", "failed", error="evm registration failed")
            return False
        await self._delay("после регистрации EVM")

        # Шаг 2: Регистрация Solana (если есть ключ)
        if self.sol_private_key and self.sol_keypair:
            sol_ref = self.referral_code or referral_code
            await self.register_solana(sol_ref)
            await self._delay("после регистрации Solana")

        # Шаг 3: Получить dashboard
        dashboard = await self.get_dashboard()
        await self._delay("после dashboard")

        # Шаг 4: Раскрыть daily spin (если доступен)
        await self.reveal_daily_spin(dashboard)

        db.log_action(self.address, "registration", "success")
        self.log("=== Регистрация завершена ===", "success")
        return True

    async def run_gm_workflow(self) -> dict:
        """Воркфлоу Say GM: проверка сессии -> GM -> dashboard update."""
        # Валидация сессии перед GM
        if not await self.validate_session():
            self.log("Сессия невалидна, переавторизация...", "warning")
            if not await self.register_evm():
                return {"success": False, "next_gm_at": None}
            db.save_session(self.address, user_agent=self.user_agent)
            await self._delay("после переавторизации")

        result = await self.say_gm()

        if result.get("success"):
            await self._delay("после GM")
            await self.get_dashboard()

        return result

    async def run_stats_workflow(self) -> dict:
        """Только получить и обновить статистику."""
        return await self.get_dashboard()
