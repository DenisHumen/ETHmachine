"""Клиент для взаимодействия с Abstract Portal.

Backend API: https://backend.portal.abs.xyz
Авторизация: Privy SIWE (Sign-In with Ethereum) через privy.abs.xyz
Подписание: EIP-191 personal_sign

Эндпоинты:
  /api/user/me               — профиль пользователя (tier, XP, socials, badges)
  /api/user                   — создание/обновление пользователя
  /api/badge                  — список бейджей
  /api/badge/flash            — flash бейджи
  /api/badge/{id}/claim       — клейм бейджа
  /api/badge/{id}/validate    — проверка доступности бейджа
  /api/user/me/experience     — XP по эпохам (недельная история)
  /api/experience/period      — текущий период XP
  /api/tiers/v2               — уровни/ранги
  /api/oracle/eth             — курс ETH
"""
import ssl
import asyncio
import json
import random
import uuid
from datetime import datetime

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from eth_account import Account
from eth_account.messages import encode_defunct
from fake_useragent import FakeUserAgent

from config.modules.cfg_abs import (
    PORTAL_URL, BACKEND_URL, PRIVY_APP_ID, PRIVY_API_URL,
    DEFAULT_HEADERS, PRIVY_HEADERS, PRIVY_CLIENT_ID, REQUEST_TIMEOUT, CHAIN_ID,
    RPC_URL, MIN_CLAIM_BALANCE,
)
from config.modules.cfg_base import RETRY_COUNT, SLEEP_BETWEEN_ACTIONS
from modules.abs.abs_proxy import AbsProxyManager
from modules.abs import abs_logger as logger
from modules.abs import database as db

# SSL контекст (для совместимости с прокси)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# Кеш tier names
_TIER_NAMES: dict[int, str] = {}


class AbsClient:
    """Клиент для одного кошелька."""

    def __init__(self, private_key: str, proxy_manager: AbsProxyManager,
                 wallet_index: int = 0, account_name: str = None,
                 task_index: int = None, task_total: int = None):
        self.private_key = private_key
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.proxy_manager = proxy_manager
        self.wallet_index = wallet_index
        self.proxy = proxy_manager.get_proxy_for_wallet(private_key, self.address, wallet_index)

        # Masked proxy for logging
        if self.proxy:
            _masked = self.proxy.split('@')[-1] if '@' in self.proxy else self.proxy
            self._proxy_masked = _masked.replace('http://', '').replace('https://', '').replace('socks5://', '')
        else:
            self._proxy_masked = 'NO PROXY'

        # Загрузить сессию из БД
        session_data = db.get_session(self.address)
        if session_data and session_data.get("user_agent"):
            self.user_agent = session_data["user_agent"]
            self._access_token = session_data.get("privy_access_token")
            self._id_token = session_data.get("privy_id_token")
            self._refresh_token = session_data.get("privy_refresh_token")
            self._client_id = None  # appClientId
            self._ca_id = session_data.get("client_id") or str(uuid.uuid4())
            self._session_valid = session_data.get("valid", 0) == 1
        else:
            self.user_agent = FakeUserAgent(browsers=["chrome"]).random
            self._access_token = None
            self._id_token = None
            self._refresh_token = None
            self._client_id = None  # appClientId — опционален
            self._ca_id = str(uuid.uuid4())  # privy-ca-id — UUID формат
            self._session_valid = False
            db.save_session(self.address, user_agent=self.user_agent, client_id=self._ca_id)

        # Logging context
        self.account_name = account_name
        self.task_index = task_index
        self.task_total = task_total

    def _short(self) -> str:
        return self.address

    def log(self, msg: str, level: str = "info"):
        logger.log(msg, level, self._short(),
                   index=self.task_index, total=self.task_total,
                   account_name=self.account_name)

    # ─────────────────── HTTP helpers ───────────────────

    def _get_backend_headers(self) -> dict:
        """Заголовки для запросов к backend.portal.abs.xyz."""
        headers = {**DEFAULT_HEADERS, "User-Agent": self.user_agent}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if self._id_token:
            headers["x-privy-token"] = self._id_token
        return headers

    def _get_privy_headers(self) -> dict:
        """Заголовки для запросов к Privy API (без Origin/Referer)."""
        return {
            **PRIVY_HEADERS,
            "User-Agent": self.user_agent,
            "privy-ca-id": self._ca_id,
            "privy-client-id": PRIVY_CLIENT_ID,
        }

    async def _request(self, method: str, url: str, data: dict = None,
                       headers: dict = None, retries: int = None,
                       auto_reauth: bool = True) -> dict | None:
        """Выполнить HTTP-запрос с ретраями и ротацией прокси."""
        if retries is None:
            retries = RETRY_COUNT
        if headers is None:
            headers = self._get_backend_headers()

        proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)

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

                        elif resp.status == 401:
                            body_text = ""
                            try:
                                body_text = (await resp.text())[:200]
                            except Exception:
                                pass
                            self._session_valid = False
                            db.invalidate_session(self.address)
                            if auto_reauth and attempt == 0:
                                self.log(
                                    f"Ошибка авторизации (401), повторная... [{body_text}]",
                                    "warning",
                                )
                                ok = await self._login()
                                if ok:
                                    headers = self._get_backend_headers()
                                    continue
                            else:
                                self.log(
                                    f"Ошибка авторизации (401): {body_text}",
                                    "error",
                                )
                            return None

                        elif resp.status == 403:
                            text = await resp.text()
                            self.log(f"HTTP 403 [{self._proxy_masked}]: {text[:200]}", "warning")
                            if attempt < retries:
                                self.proxy = self.proxy_manager.rotate_proxy(
                                    self.private_key, self.address)
                                proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
                                await asyncio.sleep(random.uniform(5, 10))

                        elif resp.status == 429:
                            wait = 30 + attempt * 15
                            self.log(f"Rate limit [{self._proxy_masked}], ждём {wait}с", "warning")
                            await asyncio.sleep(wait)
                            if attempt < retries:
                                self.proxy = self.proxy_manager.rotate_proxy(
                                    self.private_key, self.address)
                                proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
                            continue

                        elif resp.status in (400, 404):
                            try:
                                body = await resp.json()
                                # Пометить как ошибочный ответ чтобы вызывающий код
                                # не спутал с успешным ответом
                                if isinstance(body, dict):
                                    body["_http_status"] = resp.status
                                return body
                            except Exception:
                                text = await resp.text()
                                self.log(f"HTTP {resp.status}: {text[:200]}", "warning")
                                return None

                        else:
                            text = await resp.text()
                            self.log(f"HTTP {resp.status}: {text[:200]}", "warning")

                        if attempt < retries:
                            self.proxy = self.proxy_manager.rotate_proxy(
                                self.private_key, self.address)
                            proxy_config = self.proxy_manager.get_aiohttp_proxy_config(self.proxy)
                            self.log(f"Ротация прокси, попытка {attempt + 2}", "warning")
                        continue

            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                self.log(f"Ошибка запроса: {err_msg} (попытка {attempt + 1})", "error")
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

    async def _patch(self, url: str, data: dict = None, **kwargs) -> dict | None:
        return await self._request("PATCH", url, data=data, **kwargs)

    # ─────────────────── Privy Auth (SIWE) ───────────────────

    async def _login(self) -> bool:
        """Авторизация через Privy SIWE.
        1. GET /api/v1/apps/{app_id} — получить конфиг приложения
        2. POST /api/v1/siwe/init — получить nonce
        3. Подписать SIWE message (EIP-191)
        4. POST /api/v1/siwe/authenticate — отправить подпись, получить токены
        """
        self.log("Авторизация через Privy (SIWE)...")
        privy_headers = self._get_privy_headers()

        try:
            # 1. Init — get nonce
            init_resp = await self._request(
                "POST",
                f"{PRIVY_API_URL}/api/v1/siwe/init",
                data={"address": self.address},
                headers=privy_headers,
            )
            if not init_resp or "nonce" not in init_resp:
                self.log(f"Не удалось получить nonce: {init_resp}", "error")
                return False

            nonce = init_resp["nonce"]

            # 2. Формируем SIWE message (EIP-4361)
            # Формат из JS SDK: `${window.location.host} wants you to sign in with your Ethereum account:\n${address}\n\n...`
            issued_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            siwe_message = (
                f"portal.abs.xyz wants you to sign in with your Ethereum account:\n"
                f"{self.address}\n"
                f"\n"
                f"By signing, you are proving you own this wallet and logging in. "
                f"This does not initiate a transaction or cost any fees.\n"
                f"\n"
                f"URI: https://portal.abs.xyz\n"
                f"Version: 1\n"
                f"Chain ID: 1\n"
                f"Nonce: {nonce}\n"
                f"Issued At: {issued_at}\n"
                f"Resources:\n"
                f"- https://privy.io"
            )

            # 3. Подписываем SIWE message (EIP-191 personal_sign)
            msg_encoded = encode_defunct(text=siwe_message)
            signed = self.account.sign_message(msg_encoded)
            signature = signed.signature.hex()
            if not signature.startswith("0x"):
                signature = "0x" + signature

            # 4. Authenticate — отправить подпись
            auth_resp = await self._request(
                "POST",
                f"{PRIVY_API_URL}/api/v1/siwe/authenticate",
                data={
                    "message": siwe_message,
                    "signature": signature,
                    "chainId": "eip155:1",
                    "walletClientType": "metamask",
                    "connectorType": "injected",
                    "mode": "login-or-sign-up",
                },
                headers=privy_headers,
            )

            if not auth_resp:
                self.log("Ошибка авторизации — пустой ответ", "error")
                return False

            # Извлечь токены из ответа Privy
            # Структура: {token, refresh_token, identity_token, user, is_new_user, ...}
            self._access_token = auth_resp.get("token")
            self._id_token = auth_resp.get("identity_token")
            self._refresh_token = auth_resp.get("refresh_token")

            # Альтернативные структуры
            if not self._access_token:
                if "session" in auth_resp:
                    sess = auth_resp["session"]
                    self._access_token = sess.get("token") or sess.get("access_token")
                    self._refresh_token = sess.get("refresh_token")
                if "privy_access_token" in auth_resp:
                    self._access_token = auth_resp["privy_access_token"]

            if self._access_token:
                self._session_valid = True
                # Сохранить сессию в БД
                db.save_session(
                    self.address,
                    privy_access_token=self._access_token,
                    privy_id_token=self._id_token,
                    privy_refresh_token=self._refresh_token,
                    user_agent=self.user_agent,
                    client_id=self._ca_id,
                )
                db.update_wallet_profile(self.address, logged_in=1)
                self.log("Авторизация успешна", "success")
                return True
            else:
                self.log(f"Токен не получен: {json.dumps(auth_resp)[:300]}", "error")
                return False

        except Exception as e:
            self.log(f"Ошибка авторизации: {e}", "error")
            return False

    async def ensure_auth(self) -> bool:
        """Убедиться что авторизация валидна. Если нет — переавторизоваться."""
        if self._session_valid and self._access_token:
            # Быстрая проверка — без автоматического re-auth внутри _request
            resp = await self._get(
                f"{BACKEND_URL}/api/user/me",
                auto_reauth=False, retries=0,
            )
            if resp and "user" in resp:
                return True
            self.log("Сессия истекла, повторная авторизация...", "warning")

        self._session_valid = False
        db.invalidate_session(self.address)
        ok = await self._login()
        if ok:
            # Небольшая задержка после авторизации для пропагации токена
            await asyncio.sleep(random.uniform(1, 2))
        return ok

    # ─────────────────── Profile ───────────────────

    async def get_profile(self) -> dict | None:
        """Получить профиль пользователя (/api/user/me).

        Возвращает:
          {user: {id, name, walletAddress, tier, tierV2,
                  totalExperiencePoints, xpMultiplier, badges, socials, ...}}
        """
        resp = await self._get(f"{BACKEND_URL}/api/user/me")
        if not resp or "user" not in resp:
            # Может потребоваться создание пользователя
            if resp and ("error" in resp or "message" in resp):
                self.log("Пользователь не найден, создаём...", "info")
                create_resp = await self._post(f"{BACKEND_URL}/api/user", data={})
                if create_resp and "user" in create_resp:
                    return create_resp
                self.log(f"Ошибка создания пользователя: {create_resp}", "error")
            return None
        return resp

    async def get_eth_price(self) -> float | None:
        """Получить курс ETH."""
        resp = await self._get(f"{BACKEND_URL}/api/oracle/eth")
        if resp and "price" in resp:
            return float(resp["price"])
        return None

    async def get_eth_balance(self, wallet_address: str) -> float | None:
        """Получить баланс ETH внутреннего кошелька через RPC Abstract Chain.

        Args:
            wallet_address: Внутренний Abstract wallet address (из профиля)

        Returns:
            Баланс в ETH (float) или None
        """
        if not wallet_address:
            return None

        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_getBalance",
                "params": [wallet_address, "latest"],
                "id": 1,
            }
            # RPC запрос без авторизации — простые JSON-RPC заголовки
            rpc_headers = {
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            }
            resp = await self._post(
                RPC_URL, data=payload, headers=rpc_headers,
                auto_reauth=False, retries=1,
            )
            if resp and "result" in resp:
                balance_wei = int(resp["result"], 16)
                balance_eth = balance_wei / 10**18
                return balance_eth
        except Exception as e:
            self.log(f"Ошибка получения баланса ETH: {e}", "warning")

        return None

    # ─────────────────── Tiers / Ranks ───────────────────

    async def get_tiers(self) -> list[dict] | None:
        """Получить список уровней/рангов (/api/tiers/v2)."""
        global _TIER_NAMES
        resp = await self._get(f"{BACKEND_URL}/api/tiers/v2")
        if resp and "tiers" in resp:
            tiers = resp["tiers"]
            # Кешируем имена тиров
            for t in tiers:
                if "id" in t and "name" in t:
                    _TIER_NAMES[t["id"]] = t["name"]
            return tiers
        return None

    @staticmethod
    def get_tier_name(tier_id: int) -> str:
        """Получить имя тира из кеша."""
        return _TIER_NAMES.get(tier_id, f"Tier {tier_id}")

    # ─────────────────── Badges ───────────────────

    async def get_badges(self) -> list[dict] | None:
        """Получить все бейджи (/api/badge).

        Каждый бейдж:
          {id, name, icon, description, requirement, url?, timeStart?, timeEnd?, type?}
        """
        resp = await self._get(f"{BACKEND_URL}/api/badge")
        if resp and "items" in resp:
            return resp["items"]
        return None

    async def get_flash_badges(self) -> dict | None:
        """Получить текущий flash бейдж (/api/badge/flash)."""
        resp = await self._get(f"{BACKEND_URL}/api/badge/flash")
        return resp

    async def validate_badge(self, badge_id: int) -> dict | None:
        """Проверить доступность бейджа для клейма.

        Returns: {badgeId, isClaimed, account?}
        """
        resp = await self._post(f"{BACKEND_URL}/api/badge/{badge_id}/validate", data={})
        self.log(f"[DEBUG] validate_badge({badge_id}) response: {resp}", "info")
        if resp and isinstance(resp, dict):
            resp.pop("_http_status", None)
        return resp

    # ─────────────────── On-chain Badge Mint ───────────────────

    # SignatureMinter контракт на Abstract Chain
    BADGE_MINTER_CONTRACT = "0xAC5f79757A785579b9C593018efD6AB27cF8821F"
    # mintBadge(address account, uint256 tokenId, bytes signature)
    MINT_BADGE_SELECTOR = "0x29efcf80"  # keccak256("mintBadge(address,uint256,bytes)")[:4]

    async def mint_badge_onchain(self, agw_account: str, token_id: int,
                                  badge_signature: str) -> str | None:
        """Отправить on-chain транзакцию mintBadge через AGW (ZKSync EIP-712, тип 113).

        Args:
            agw_account: AGW адрес (smart contract wallet, отправитель и получатель)
            token_id: ID бейджа (badgeId)
            badge_signature: Подпись от бэкенда для mintBadge

        Returns:
            tx_hash при успехе, None при ошибке
        """
        from eth_abi import encode
        from eth_account.messages import encode_defunct
        import rlp
        from web3 import Web3

        GAS_PER_PUBDATA_BYTE_LIMIT = 50000  # стандарт ZKSync

        try:
            # 1. Encode calldata: mintBadge(address, uint256, bytes)
            sig_bytes = bytes.fromhex(badge_signature.replace("0x", ""))
            calldata = bytes.fromhex(self.MINT_BADGE_SELECTOR.replace("0x", ""))
            calldata += encode(
                ["address", "uint256", "bytes"],
                [agw_account, token_id, sig_bytes],
            )

            # 2. Get nonce для AGW (from = AGW)
            nonce_resp = await self._rpc_call(
                "eth_getTransactionCount", [agw_account, "latest"])
            if nonce_resp is None:
                self.log("Не удалось получить nonce AGW", "error")
                return None
            nonce = int(nonce_resp, 16)

            # 3. Get gas price
            gas_price_resp = await self._rpc_call("eth_gasPrice", [])
            if gas_price_resp is None:
                self.log("Не удалось получить gas price", "error")
                return None
            gas_price = int(gas_price_resp, 16)

            # 4. Estimate gas (from = AGW)
            estimate_tx = {
                "from": agw_account,
                "to": self.BADGE_MINTER_CONTRACT,
                "data": "0x" + calldata.hex(),
                "value": "0x0",
            }
            gas_resp = await self._rpc_call("eth_estimateGas", [estimate_tx])
            if gas_resp is None:
                self.log("Не удалось оценить газ", "error")
                return None
            gas_limit = int(int(gas_resp, 16) * 1.2)

            # 5. Build EIP-712 typed data hash (ZKSync Transaction)
            to_addr = bytes.fromhex(self.BADGE_MINTER_CONTRACT[2:])
            from_addr = bytes.fromhex(agw_account[2:].lower())

            # EIP-712 domain
            domain_type_hash = Web3.keccak(
                text="EIP712Domain(string name,string version,uint256 chainId)"
            )
            domain_hash = Web3.keccak(
                domain_type_hash
                + Web3.keccak(text="zkSync")
                + Web3.keccak(text="2")
                + encode(["uint256"], [CHAIN_ID])
            )

            # Transaction type hash
            tx_type_hash = Web3.keccak(
                text="Transaction(uint256 txType,uint256 from,uint256 to,"
                     "uint256 gasLimit,uint256 gasPerPubdataByteLimit,"
                     "uint256 maxFeePerGas,uint256 maxPriorityFeePerGas,"
                     "uint256 paymaster,uint256 nonce,uint256 value,"
                     "bytes data,bytes32[] factoryDeps,bytes paymasterInput)"
            )

            # Encode transaction struct
            from_int = int(agw_account, 16)
            to_int = int(self.BADGE_MINTER_CONTRACT, 16)
            struct_encoded = encode(
                ["bytes32",
                 "uint256", "uint256", "uint256",
                 "uint256", "uint256",
                 "uint256", "uint256",
                 "uint256", "uint256", "uint256",
                 "bytes32", "bytes32", "bytes32"],
                [tx_type_hash,
                 113, from_int, to_int,
                 gas_limit, GAS_PER_PUBDATA_BYTE_LIMIT,
                 gas_price, gas_price,
                 0, nonce, 0,
                 Web3.keccak(calldata),
                 Web3.keccak(encode(["bytes32[]"], [[]])),
                 Web3.keccak(b"")]
            )
            struct_hash = Web3.keccak(struct_encoded)

            # EIP-712 final hash
            sign_hash = Web3.keccak(
                b"\x19\x01" + domain_hash + struct_hash
            )

            # 6. Sign with EOA private key
            signed = self.account.signHash(sign_hash)
            custom_signature = bytes([signed.v]) if signed.v < 256 else b""
            custom_signature = (
                signed.r.to_bytes(32, "big")
                + signed.s.to_bytes(32, "big")
                + bytes([signed.v])
            )

            # 7. RLP encode ZKSync type 113 transaction
            rlp_fields = [
                nonce,                          # nonce
                gas_price,                      # maxPriorityFeePerGas
                gas_price,                      # maxFeePerGas
                gas_limit,                      # gasLimit
                to_addr,                        # to
                0,                              # value
                calldata,                       # data
            ]

            # Encode main tx
            tx_rlp = rlp.encode(rlp_fields)

            # ZKSync EIP-712 serialization
            # [nonce, maxPriorityFee, maxFee, gasLimit, to, value, data,
            #  chainId, empty, empty,  # EIP-155 fields
            #  chainId, from, gasPerPubdata, factoryDeps, customSignature, paymasterInput]
            full_fields = [
                nonce,
                gas_price,                      # maxPriorityFeePerGas
                gas_price,                      # maxFeePerGas
                gas_limit,
                to_addr,
                0,                              # value
                calldata,
                CHAIN_ID,                       # chainId
                b"",                            # empty (EIP-155)
                b"",                            # empty (EIP-155)
                CHAIN_ID,                       # chainId again
                from_addr,                      # from (AGW)
                GAS_PER_PUBDATA_BYTE_LIMIT,     # gasPerPubdataByteLimit
                [],                             # factoryDeps
                custom_signature,               # customSignature (EOA sig)
                b"",                            # paymasterInput
            ]
            raw_tx = b"\x71" + rlp.encode(full_fields)
            raw_tx_hex = "0x" + raw_tx.hex()

            # 8. Send transaction
            tx_hash = await self._rpc_call("eth_sendRawTransaction", [raw_tx_hex])
            if not tx_hash:
                self.log("Не удалось отправить транзакцию", "error")
                return None

            self.log(f"TX отправлена: {tx_hash}", "info")

            # 9. Wait for receipt
            for _ in range(30):
                await asyncio.sleep(2)
                receipt = await self._rpc_call(
                    "eth_getTransactionReceipt", [tx_hash])
                if receipt:
                    status = int(receipt.get("status", "0x0"), 16)
                    if status == 1:
                        self.log(f"TX подтверждена: {tx_hash}", "success")
                        return tx_hash
                    else:
                        self.log(f"TX ревёрнулась: {tx_hash}", "error")
                        return None

            self.log(f"Таймаут ожидания TX: {tx_hash}", "warning")
            return tx_hash

        except Exception as e:
            self.log(f"Ошибка mint_badge_onchain: {e}", "error")
            import traceback
            self.log(f"Traceback: {traceback.format_exc()}", "error")
            return None

    async def _rpc_call(self, method: str, params: list) -> str | dict | None:
        """Вызов JSON-RPC метода на Abstract Chain."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        rpc_headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        resp = await self._post(
            RPC_URL, data=payload, headers=rpc_headers,
            auto_reauth=False, retries=2,
        )
        if resp and "result" in resp:
            return resp["result"]
        if resp and "error" in resp:
            err = resp["error"]
            self.log(f"RPC error: {err}", "warning")
        return None

    async def claim_badge(self, badge_id: int) -> dict | None:
        """Заклеймить бейдж.

        Returns: {account, badgeId, signature} при успехе
        """
        resp = await self._post(f"{BACKEND_URL}/api/badge/{badge_id}/claim", data={})
        self.log(f"[DEBUG] claim_badge({badge_id}) raw response: {resp}", "info")
        # Если HTTP 400/404 — это ошибка, не успех
        if resp and isinstance(resp, dict) and resp.get("_http_status") in (400, 404):
            status = resp.pop("_http_status")
            self.log(f"[DEBUG] claim_badge({badge_id}) HTTP {status} error", "warning")
            # Вернуть как ошибку — оставить message/error поля для обработки
            if "badgeId" in resp:
                resp.pop("badgeId")  # Убрать badgeId из ошибочного ответа
            if "account" in resp:
                resp.pop("account")  # Убрать account из ошибочного ответа
        return resp

    # ─────────────────── Badge Claiming Workflow ───────────────────

    async def claim_available_badges(self) -> dict:
        """Проверить и заклеймить все доступные бейджи.

        Выполняет:
          1. Авторизация
          2. Получить профиль (claimed badges)
          3. Получить все бейджи + validate каждый
          4. Клеймить доступные с ретраями

        Возвращает: {address, success, claimed: [...], failed: [...], skipped: [...]}
        """
        result = {
            "address": self.address,
            "success": False,
            "claimed": [],
            "failed": [],
            "skipped": [],
            "total_badges": 0,
            "already_claimed": 0,
        }

        # 1. Auth
        if not await self.ensure_auth():
            result["error"] = "Ошибка авторизации"
            return result

        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

        # 2. Profile — получить список уже заклеймленных + бейджи из профиля
        profile_resp = await self.get_profile()
        if not profile_resp or "user" not in profile_resp:
            result["error"] = "Не удалось получить профиль"
            return result

        user = profile_resp["user"]
        user_badges = user.get("badges", [])
        claimed_ids = set()
        for ub in user_badges:
            badge_info = ub.get("badge", {})
            if ub.get("claimed"):
                claimed_ids.add(badge_info.get("id"))

        await asyncio.sleep(random.uniform(1, 2))

        # 2.5. Проверка баланса ETH — нужно минимум MIN_CLAIM_BALANCE для клейма
        abs_wallet = user.get("walletAddress", "")
        if abs_wallet:
            eth_balance = await self.get_eth_balance(abs_wallet)
            if eth_balance is not None and eth_balance < MIN_CLAIM_BALANCE:
                self.log(
                    f"Недостаточный баланс: {eth_balance:.6f} ETH "
                    f"(нужно минимум {MIN_CLAIM_BALANCE} ETH для клейма бейджа)",
                    "error",
                )
                result["error"] = (
                    f"Insufficient balance: {eth_balance:.6f} ETH "
                    f"(need at least {MIN_CLAIM_BALANCE} ETH)"
                )
                return result

        await asyncio.sleep(random.uniform(0.5, 1))

        # 3. Объединить бейджи из всех источников: /api/badge + flash + profile
        api_badges = await self.get_badges() or []
        await asyncio.sleep(random.uniform(0.5, 1))
        flash_badge = await self.get_flash_badges()

        merged: dict[int, dict] = {}

        # 1) Бейджи из профиля (основной источник — все earned/claimed)
        for ub in user_badges:
            badge_info = ub.get("badge", {})
            bid = badge_info.get("id")
            if bid:
                merged[bid] = {"id": bid, "name": badge_info.get("name", ""), "type": badge_info.get("type", "regular")}

        # 2) Бейджи из /api/badge (regular)
        for b in api_badges:
            bid = b.get("id")
            if bid not in merged:
                merged[bid] = {"id": bid, "name": b.get("name", ""), "type": b.get("type", "regular")}

        # 3) Flash бейдж
        if flash_badge and isinstance(flash_badge, dict) and "id" in flash_badge:
            fid = flash_badge["id"]
            if fid not in merged:
                merged[fid] = {"id": fid, "name": flash_badge.get("name", ""), "type": "flash"}

        all_badges = list(merged.values())
        result["total_badges"] = len(all_badges)
        result["already_claimed"] = len(claimed_ids)

        self.log(
            f"Проверка бейджей: {len(all_badges)} всего, "
            f"{len(claimed_ids)} из профиля уже заклеймлено",
            "info",
        )

        # 4. Validate каждый незаклеймленный, собрать список для клейма
        claimable_badges = []
        for b in sorted(all_badges, key=lambda x: x["id"]):
            badge_id = b.get("id")
            badge_name = b.get("name", f"Badge #{badge_id}")

            if badge_id in claimed_ids:
                continue

            await asyncio.sleep(random.uniform(0.5, 1.5))

            # Validate — account в ответе = бейдж заработан и готов к клейму
            validate_resp = await self.validate_badge(badge_id)
            if validate_resp:
                if validate_resp.get("isClaimed"):
                    claimed_ids.add(badge_id)
                    self.log(f"  {badge_name}: уже заклеймлен", "info")
                    continue
                elif "account" in validate_resp:
                    claimable_badges.append(b)
                    self.log(f"  {badge_name}: готов к клейму ✓", "success")
                    continue

            result["skipped"].append({
                "id": badge_id,
                "name": badge_name,
                "reason": "not ready",
            })
            self.log(f"  {badge_name}: не готов", "info")

        result["already_claimed"] = len(claimed_ids)

        if not claimable_badges:
            self.log(
                f"Нет бейджей для клейма ({len(claimed_ids)} уже заклеймлено, "
                f"{len(result['skipped'])} не готовы)",
                "info",
            )
            result["success"] = True
            return result

        self.log(
            f"Найдено {len(claimable_badges)} бейджей для клейма",
            "success",
        )

        # 5. Клеймить: получить подпись от API + mint on-chain
        for b in claimable_badges:
            badge_id = b.get("id")
            badge_name = b.get("name", f"Badge #{badge_id}")

            await asyncio.sleep(random.uniform(1, 2))

            self.log(f"Клейм бейджа: {badge_name}...", "info")
            claimed = False
            last_error = None

            for attempt in range(RETRY_COUNT + 1):
                await asyncio.sleep(random.uniform(1, 3))

                # Шаг 1: Получить подпись от бэкенда
                claim_resp = await self.claim_badge(badge_id)

                if not claim_resp:
                    last_error = "Пустой ответ от API"
                    self.log(
                        f"Ошибка клейма {badge_name} (попытка {attempt + 1}): {last_error}",
                        "warning",
                    )
                    if attempt < RETRY_COUNT:
                        await asyncio.sleep(random.uniform(2, 5))
                    continue

                # Проверить ошибки от API
                if claim_resp.get("error"):
                    last_error = claim_resp.get("error")
                    self.log(
                        f"Ошибка клейма {badge_name} (попытка {attempt + 1}): {last_error}",
                        "warning",
                    )
                    if attempt < RETRY_COUNT:
                        await asyncio.sleep(random.uniform(2, 5))
                    continue

                if claim_resp.get("message"):
                    last_error = claim_resp.get("message")
                    msg_lower = str(last_error).lower()
                    if "already" in msg_lower or "claimed" in msg_lower:
                        self.log(f"Бейдж {badge_name} уже заклеймлен", "info")
                        claimed = True
                        break
                    if "not earned" in msg_lower or "has not earned" in msg_lower:
                        self.log(f"Бейдж {badge_name} не заработан, пропуск", "warning")
                        break
                    self.log(
                        f"Ошибка клейма {badge_name} (попытка {attempt + 1}): {last_error}",
                        "warning",
                    )
                    if attempt < RETRY_COUNT:
                        await asyncio.sleep(random.uniform(2, 5))
                    continue

                # Шаг 2: Получены данные для минта
                mint_account = claim_resp.get("account")
                mint_signature = claim_resp.get("signature")
                mint_badge_id = claim_resp.get("badgeId")

                if not mint_account or not mint_signature:
                    last_error = f"Неполный ответ: {claim_resp}"
                    self.log(
                        f"Ошибка клейма {badge_name} (попытка {attempt + 1}): {last_error}",
                        "warning",
                    )
                    if attempt < RETRY_COUNT:
                        await asyncio.sleep(random.uniform(2, 5))
                    continue

                # Если badgeId в ответе — число, использовать его; иначе badge_id
                token_id = badge_id
                if mint_badge_id:
                    try:
                        token_id = int(mint_badge_id)
                    except (ValueError, TypeError):
                        pass

                self.log(
                    f"Подпись получена, минт на контракт: "
                    f"account={mint_account}, tokenId={token_id}",
                    "info",
                )

                # Шаг 3: On-chain mint
                tx_hash = await self.mint_badge_onchain(
                    mint_account, token_id, mint_signature,
                )

                if tx_hash:
                    claimed = True
                    self.log(
                        f"✓ Бейдж заминчен on-chain: {badge_name} (tx: {tx_hash})",
                        "success",
                    )
                    break
                else:
                    last_error = "Ошибка on-chain mint транзакции"
                    self.log(
                        f"Ошибка минта {badge_name} (попытка {attempt + 1})",
                        "warning",
                    )
                    if attempt < RETRY_COUNT:
                        await asyncio.sleep(random.uniform(3, 6))

            if claimed:
                result["claimed"].append({"id": badge_id, "name": badge_name})
                claimed_ids.add(badge_id)
                db.update_badge_claimed(self.address, badge_id)
                db.log_action(self.address, "claim_badge", "success",
                              details=badge_name)
            else:
                self.log(f"✗ Не удалось заклеймить: {badge_name}", "error")
                result["failed"].append({
                    "id": badge_id,
                    "name": badge_name,
                    "error": str(last_error),
                })
                db.log_action(self.address, "claim_badge", "failed",
                              details=badge_name, error=str(last_error))

            await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

        # Итог
        total_claimed = len(result["claimed"])
        total_failed = len(result["failed"])
        total_skipped = len(result["skipped"])

        if total_claimed > 0 or total_failed == 0:
            result["success"] = True

        self.log(
            f"Итого: +{total_claimed} заклеймлено, {total_failed} ошибок, "
            f"{total_skipped} не готовы",
            "success" if total_failed == 0 else "warning",
        )

        db.log_action(
            self.address, "claim_badges", "success" if result["success"] else "partial",
            details=f"claimed={total_claimed}, failed={total_failed}, skipped={total_skipped}",
        )

        return result

    # ─────────────────── XP / Experience ───────────────────

    async def get_xp_history(self, limit: int = None) -> dict | None:
        """Получить XP по эпохам (/api/user/me/experience).

        Каждый item:
          {userId, epoch, description?, points, referralXp?, season}
        Returns: {items: [...], lastEpoch: int}
        """
        url = f"{BACKEND_URL}/api/user/me/experience"
        if limit:
            url += f"?limit={limit}"
        return await self._get(url)

    async def get_experience_period(self) -> str | None:
        """Получить время следующего начисления XP (/api/experience/period)."""
        resp = await self._get(f"{BACKEND_URL}/api/experience/period")
        if resp and "nextEarnTime" in resp:
            return resp["nextEarnTime"]
        return None

    # ─────────────────── Full Stats Workflow ───────────────────

    async def collect_full_stats(self) -> dict | None:
        """Собрать полную статистику аккаунта.

        Выполняет:
          1. Авторизация (если нужно)
          2. Профиль (/api/user/me) — tier, XP, wallet, socials, badges
          3. Бейджи (/api/badge) + validate каждого
          4. XP история (/api/user/me/experience)
          5. Tiers (/api/tiers/v2) — имена рангов
          6. ETH price

        Сохраняет всё в БД и возвращает dict.
        """
        result = {
            "address": self.address,
            "success": False,
            "profile": None,
            "badges": [],
            "xp_history": [],
            "tier_name": "",
            "eth_balance": "",
        }

        # 1. Auth
        if not await self.ensure_auth():
            result["error"] = "Ошибка авторизации"
            return result

        # Задержка между действиями
        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

        # 2. Tiers (для имён)
        await self.get_tiers()

        await asyncio.sleep(random.uniform(1, 2))

        # 3. Profile
        profile_resp = await self.get_profile()
        if not profile_resp or "user" not in profile_resp:
            result["error"] = "Не удалось получить профиль"
            return result

        user = profile_resp["user"]
        result["profile"] = user

        tier = user.get("tier", 0)
        tier_v2 = user.get("tierV2", 0)
        tier_name = self.get_tier_name(tier_v2 or tier)
        result["tier_name"] = tier_name

        total_xp = user.get("totalExperiencePoints", 0)
        xp_mult = 1.0
        xp_mult_raw = user.get("xpMultiplier")
        if xp_mult_raw:
            if isinstance(xp_mult_raw, dict):
                xp_mult = xp_mult_raw.get("multiplier", 1.0)
            elif isinstance(xp_mult_raw, (int, float)):
                xp_mult = float(xp_mult_raw)

        # Socials
        socials = user.get("socials", {})
        twitter = bool(socials.get("twitter"))
        discord = bool(socials.get("discord"))

        # Wallet address (internal Abstract wallet)
        abs_wallet = user.get("walletAddress", "")

        self.log(
            f"Профиль: {tier_name} | XP: {total_xp} | Mult: {xp_mult}x",
            "success",
        )

        await asyncio.sleep(random.uniform(1, 2))

        # 4. ETH balance через RPC (внутренний Abstract кошелёк)
        eth_price = await self.get_eth_price()
        result["eth_price"] = eth_price

        eth_balance = None
        if abs_wallet:
            eth_balance = await self.get_eth_balance(abs_wallet)
            if eth_balance is not None:
                result["eth_balance"] = f"{eth_balance:.6f}"
                self.log(f"Баланс: {eth_balance:.6f} ETH", "info")
            else:
                result["eth_balance"] = ""

        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

        # 5. Badges — объединяем 3 источника: /api/badge, /api/badge/flash, profile
        api_badges = await self.get_badges() or []
        flash_badge = await self.get_flash_badges()

        user_badges = user.get("badges", [])
        # user_badges: [{badge: {id, name, ...}, claimed: bool}, ...]

        # Собираем единый список бейджей из всех источников
        merged_badges: dict[int, dict] = {}

        # 1) Бейджи из профиля (основной источник — все earned/claimed)
        for ub in user_badges:
            badge_info = ub.get("badge", {})
            bid = badge_info.get("id")
            if bid:
                merged_badges[bid] = {
                    "id": bid,
                    "name": badge_info.get("name", ""),
                    "icon": badge_info.get("icon", ""),
                    "description": badge_info.get("description", ""),
                    "requirement": badge_info.get("requirement", ""),
                    "type": badge_info.get("type", "regular"),
                }

        # 2) Бейджи из /api/badge (regular — могут быть ещё не earned)
        for b in api_badges:
            bid = b.get("id")
            if bid not in merged_badges:
                merged_badges[bid] = {
                    "id": bid,
                    "name": b.get("name", ""),
                    "icon": b.get("icon", ""),
                    "description": b.get("description", ""),
                    "requirement": b.get("requirement", ""),
                    "type": b.get("type", "regular"),
                }

        # 3) Flash бейдж
        if flash_badge and isinstance(flash_badge, dict) and "id" in flash_badge:
            fid = flash_badge["id"]
            if fid not in merged_badges:
                merged_badges[fid] = {
                    "id": fid,
                    "name": flash_badge.get("name", ""),
                    "icon": flash_badge.get("icon", ""),
                    "description": flash_badge.get("description", ""),
                    "requirement": flash_badge.get("requirement", ""),
                    "type": "flash",
                }

        # Claimed из профиля
        profile_claimed_ids = set()
        for ub in user_badges:
            badge_info = ub.get("badge", {})
            if ub.get("claimed"):
                profile_claimed_ids.add(badge_info.get("id"))

        # Validate каждый бейдж
        badges_result = []
        for bid in sorted(merged_badges.keys()):
            b = merged_badges[bid]
            is_claimed = bid in profile_claimed_ids
            claim_available = False

            if not is_claimed:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                validate_resp = await self.validate_badge(bid)
                if validate_resp:
                    if validate_resp.get("isClaimed"):
                        is_claimed = True
                        profile_claimed_ids.add(bid)
                    elif "account" in validate_resp:
                        claim_available = True

            badges_result.append({
                **b,
                "claimed": is_claimed,
                "claim_available": claim_available,
            })

        result["badges"] = badges_result
        claimed_count = sum(1 for b in badges_result if b["claimed"])
        claimable = sum(1 for b in badges_result if b["claim_available"])
        self.log(
            f"Бейджи: {claimed_count}/{len(badges_result)} заклеймлено"
            + (f", {claimable} доступно для клейма" if claimable else ""),
            "success" if claimable == 0 else "warning",
        )

        # Save badges to DB
        db.save_badges(self.address, badges_result)

        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

        # 6. XP History
        xp_resp = await self.get_xp_history()
        xp_items = []
        if xp_resp and "items" in xp_resp:
            xp_items = xp_resp["items"]
            result["xp_history"] = xp_items

            # Log recap
            if xp_items:
                recent = xp_items[:5]  # последние 5 эпох
                total_recent_xp = sum(item.get("points", 0) for item in recent)
                self.log(f"XP Recap: {total_recent_xp} XP за последние {len(recent)} эпох", "info")

            # Save to DB
            db.save_xp_history(self.address, xp_items)

        # 7. Save full stats to DB
        db.update_wallet_stats(
            self.address,
            tier=tier, tier_v2=tier_v2, tier_name=tier_name,
            total_xp=total_xp, xp_multiplier=xp_mult,
            current_streak=0, longest_streak=0,
            voted_today=False,
            twitter=twitter, discord=discord,
            abs_wallet=abs_wallet,
            eth_balance=result.get("eth_balance") or None,
        )

        result["success"] = True
        db.log_action(self.address, "stats", "success")
        return result
