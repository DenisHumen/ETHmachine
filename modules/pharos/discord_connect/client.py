"""Pharos Discord Connect — HTTP клиент для авторизации и привязки Discord."""
import json
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from eth_account import Account
from eth_account.messages import encode_defunct
from fake_useragent import FakeUserAgent

from config.modules.cfg_pharos_discord import (
    PHAROS_BASE_URL, PHAROS_HEADERS, DISCORD_HEADERS,
    SIGN_MESSAGE, SESSION_TTL_SECONDS, REF_CODE, REQUEST_TIMEOUT,
)
from modules.proxy_manager import get_proxy_dict
from modules.pharos.discord_connect import database as db


class PharosDiscordClient:
    """Клиент для одного кошелька: авторизация Pharos + привязка Discord."""

    def __init__(self, private_key: str, proxy: str | None = None,
                 discord_token: str | None = None, wallet_index: int = 0):
        self.private_key = private_key
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.proxy = proxy
        self.discord_token = discord_token
        self.wallet_index = wallet_index
        self.jwt_token: str | None = None
        self.user_agent = FakeUserAgent().random
        self._log_func = None

    def set_logger(self, log_func):
        """Установить функцию логирования: log_func(message, status)."""
        self._log_func = log_func

    def log(self, msg: str, level: str = "info"):
        if self._log_func:
            self._log_func(msg, level)

    # ─────────────────── SESSION ───────────────────

    def _create_session(self) -> requests.Session:
        """Создать requests.Session с прокси и retry."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[502, 503, 504, 520, 521, 522, 523, 524],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        if self.proxy:
            proxy_dict = get_proxy_dict(self.proxy)
            if proxy_dict:
                session.proxies.update(proxy_dict)

        return session

    def _pharos_headers(self, with_auth: bool = True) -> dict:
        headers = {**PHAROS_HEADERS, "User-Agent": self.user_agent}
        if with_auth and self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"
        return headers

    def _discord_headers(self, referer: str = "https://discord.com/") -> dict:
        headers = {**DISCORD_HEADERS, "User-Agent": self.user_agent}
        if self.discord_token:
            headers["Authorization"] = self.discord_token
        if referer:
            headers["Referer"] = referer
        return headers

    # ─────────────────── JWT SESSION MANAGEMENT ───────────────────

    def _is_session_valid(self) -> bool:
        """Проверить есть ли сохранённая валидная сессия."""
        jwt_token, jwt_created = db.get_saved_jwt(self.address)
        if not jwt_token or not jwt_created:
            return False
        try:
            created_dt = datetime.fromisoformat(jwt_created)
            if datetime.now() - created_dt < timedelta(seconds=SESSION_TTL_SECONDS):
                self.jwt_token = jwt_token
                self.log("Используем сохранённую сессию (JWT)", "info")
                return True
            self.log("Сессия истекла, пересоздаём", "warning")
            return False
        except (ValueError, TypeError):
            return False

    # ─────────────────── DISCORD TOKEN VALIDATION ───────────────────

    def validate_discord_token(self) -> dict | None:
        """Проверить валидность Discord токена. Возвращает user info или None."""
        if not self.discord_token:
            return None
        try:
            session = self._create_session()
            headers = self._discord_headers()
            resp = session.get(
                "https://discord.com/api/v9/users/@me",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json()
            self.log(f"Discord токен невалиден (HTTP {resp.status_code})", "error")
            return None
        except Exception as e:
            self.log(f"Ошибка проверки Discord токена: {e}", "error")
            return None

    # ─────────────────── PHAROS AUTH (MetaMask emulation) ───────────────────

    def authenticate(self) -> bool:
        """Авторизация на Pharos: подпись сообщения + login API.
        Эмулирует подключение MetaMask кошелька.
        """
        if self._is_session_valid():
            return True

        try:
            message = encode_defunct(text=SIGN_MESSAGE)
            signed = self.account.sign_message(message)
            signature = signed.signature.hex()

            ref = f"&invite_code={REF_CODE}" if REF_CODE else ""
            url = (f"{PHAROS_BASE_URL}/user/login"
                   f"?address={self.address}&signature={signature}{ref}")

            session = self._create_session()
            resp = session.post(
                url,
                headers=self._pharos_headers(with_auth=False),
                timeout=REQUEST_TIMEOUT,
            )
            result = resp.json()

            if result and result.get("data", {}).get("jwt"):
                self.jwt_token = result["data"]["jwt"]
                db.update_task_auth(self.address, self.jwt_token)
                self.log("Авторизация Pharos успешна", "success")
                return True

            msg = result.get("msg", "unknown") if result else "нет ответа"
            self.log(f"Ошибка авторизации Pharos: {msg}", "error")
            return False
        except Exception as e:
            self.log(f"Ошибка авторизации Pharos: {e}", "error")
            return False

    # ─────────────────── CHECK IF DISCORD ALREADY BOUND ───────────────────

    def _check_already_bound(self) -> bool:
        """Проверить через профиль, не привязан ли уже Discord."""
        try:
            session = self._create_session()
            resp = session.get(
                f"{PHAROS_BASE_URL}/user/profile?address={self.address}",
                headers=self._pharos_headers(),
                timeout=REQUEST_TIMEOUT,
            )
            profile = resp.json()
            if profile and profile.get("data"):
                user_info = profile["data"].get("user_info", {})
                discord_id = user_info.get("DiscordId", "")
                if discord_id and str(discord_id).strip():
                    username = user_info.get("UserName", "")
                    self.log(f"Discord уже привязан: {username} (ID: {discord_id})", "success")
                    db.update_task_discord_connected(
                        self.address,
                        discord_username=username,
                        discord_id=str(discord_id),
                    )
                    return True
            return False
        except Exception:
            return False

    # ─────────────────── STEP 1: GET DISCORD OAUTH URL ───────────────────

    def _get_discord_oauth_url(self) -> str | None:
        """GET /auth/discord → 307 redirect на Discord OAuth2 URL.
        Сервер генерирует PKCE code_challenge и state.
        """
        try:
            session = self._create_session()
            resp = session.get(
                f"{PHAROS_BASE_URL}/auth/discord",
                headers=self._pharos_headers(),
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )

            if resp.status_code == 307:
                location = resp.headers.get("Location", "")
                if "discord.com" in location:
                    return location

            self.log(f"Неожиданный ответ /auth/discord: HTTP {resp.status_code}", "error")
            return None
        except Exception as e:
            self.log(f"Ошибка получения OAuth URL: {e}", "error")
            return None

    # ─────────────────── STEP 2: AUTHORIZE ON DISCORD ───────────────────

    def _authorize_discord_oauth(self, oauth_url: str) -> tuple[str | None, str | None]:
        """POST на Discord OAuth2 authorize с Discord токеном.
        Эмулирует нажатие 'Authorize' в браузере.
        Возвращает (code, state).
        """
        if not self.discord_token:
            self.log("Discord токен не указан", "error")
            return None, None

        try:
            session = self._create_session()

            payload = {
                "permissions": "0",
                "authorize": True,
                "guild_id": None,
            }

            headers = self._discord_headers(referer=oauth_url)
            resp = session.post(
                oauth_url,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )

            if resp.status_code != 200:
                self.log(f"Discord OAuth ошибка: HTTP {resp.status_code}", "error")
                try:
                    err = resp.json()
                    self.log(f"Discord ответ: {err}", "error")
                except Exception:
                    pass
                return None, None

            result = resp.json()
            location = result.get("location", "")

            if location:
                parsed_loc = urlparse(location)
                loc_params = parse_qs(parsed_loc.query)
                code = loc_params.get("code", [None])[0]
                state = loc_params.get("state", [None])[0]
                if code:
                    self.log("Discord OAuth авторизован", "success")
                    return code, state

            self.log(f"Не удалось получить code из Discord: {result}", "error")
            return None, None
        except Exception as e:
            self.log(f"Ошибка Discord OAuth: {e}", "error")
            return None, None

    # ─────────────────── STEP 3: BIND ON PHAROS ───────────────────

    def _bind_discord(self, code: str, state: str) -> tuple[bool, str]:
        """POST /auth/bind/discord с code, state, address.
        Завершает привязку Discord к аккаунту Pharos.
        Возвращает (success, error_message).
        """
        try:
            session = self._create_session()
            payload = {
                "code": code,
                "state": state,
                "address": self.address,
            }

            resp = session.post(
                f"{PHAROS_BASE_URL}/auth/bind/discord",
                json=payload,
                headers=self._pharos_headers(),
                timeout=REQUEST_TIMEOUT,
            )

            result = resp.json()
            msg = result.get("msg", "")
            api_code = result.get("code", -1)

            if api_code == 0 or "success" in msg.lower():
                data = result.get("data", {})
                discord_username = data.get("username", "")
                discord_id = data.get("discordID", "") or data.get("discord_id", "")
                db.update_task_discord_connected(
                    self.address,
                    discord_username=discord_username,
                    discord_id=str(discord_id),
                )
                self.log(f"Discord привязан: {discord_username} (ID: {discord_id})", "success")
                return True, ""

            # "already bound to another address" — это ошибка, Discord занят другим аккаунтом
            if "another" in msg.lower():
                self.log(f"Discord уже привязан к другому адресу: {msg}", "error")
                return False, msg

            # "already bound" (к этому же адресу) — это успех
            if "already" in msg.lower() or "bound" in msg.lower():
                self.log(f"Discord уже привязан к этому адресу: {msg}", "success")
                self._check_already_bound()
                return True, ""

            self.log(f"Ошибка привязки Discord: {msg}", "error")
            return False, msg
        except Exception as e:
            self.log(f"Ошибка bind Discord: {e}", "error")
            return False, str(e)

    # ─────────────────── MAIN WORKFLOW ───────────────────

    def connect_discord(self) -> bool:
        """Полный workflow:
        1. Авторизация на Pharos (подпись сообщения, эмуляция MetaMask)
        2. Проверка не привязан ли уже Discord
        3. GET /auth/discord → Discord OAuth URL (307 redirect)
        4. POST на Discord OAuth authorize (с Discord токеном)
        5. POST /auth/bind/discord с code + state + address
        """
        # Шаг 1: Авторизация на Pharos
        self.log("Авторизация на Pharos (эмуляция MetaMask)...")
        if not self.authenticate():
            db.update_task_failed(self.address, "Ошибка авторизации Pharos")
            return False

        # Шаг 2: Проверка — не привязан ли уже
        if self._check_already_bound():
            return True

        # Шаг 3: Проверяем валидность Discord токена
        discord_user = self.validate_discord_token()
        if not discord_user:
            db.update_task_failed(self.address, "Discord токен невалиден")
            return False
        self.log(f"Discord токен валиден: {discord_user.get('username')} ({discord_user.get('id')})", "info")

        # Шаг 4: Получить OAuth URL от Pharos
        self.log("Получение Discord OAuth URL от Pharos...")
        oauth_url = self._get_discord_oauth_url()
        if not oauth_url:
            db.update_task_failed(self.address, "Не удалось получить Discord OAuth URL")
            return False

        # Шаг 5: Авторизовать на Discord
        self.log("Авторизация Discord OAuth...")
        code, state = self._authorize_discord_oauth(oauth_url)
        if not code or not state:
            db.update_task_failed(self.address, "Не удалось авторизовать Discord OAuth")
            return False

        # Шаг 6: Привязать на Pharos
        self.log("Завершение привязки Discord на Pharos...")
        success, error_msg = self._bind_discord(code, state)
        if not success:
            db.update_task_failed(self.address, error_msg or "Не удалось завершить привязку Discord")
            return False

        return True
