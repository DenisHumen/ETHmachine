"""Pharos Claim Checker — HTTP-клиент одного кошелька.

Эмулирует подключение кошелька через OKX/WalletConnect (SIWE-подобное
сообщение + personal_sign) БЕЗ запуска настоящего браузера. Используется
curl_cffi с TLS-импресонацией Chrome, поэтому Cloudflare/CloudFront не
режет запросы. Каждый кошелёк идёт через свой прокси из data.csv.

Флоу:
  warmup GET https://claim.pharos.xyz/
  POST   https://api.claim.pharos.xyz/accounts/sign_in_blockchain
         → {success, data:{verified, token}}
  GET    https://api.claim.pharos.xyz/airdrop/airdrop_info
         Authorization: TOKEN <token>
         → {code, message, data:{...}}     eligible
           {code:40001, message:"no data"} not eligible
"""
from __future__ import annotations

import random
import time
from typing import Callable, Optional

from curl_cffi import requests as curl_requests
from eth_account import Account
from eth_account.messages import encode_defunct
from fake_useragent import FakeUserAgent

from config.modules.cfg_base import RETRY_COUNT, SLEEP_BETWEEN_ACTIONS
from config.modules.cfg_pharos_claim import (
    API_BASE_URL,
    AUTH_ENDPOINT,
    AUTH_MESSAGE_TEMPLATE,
    CLAIM_HEADERS,
    CLAIM_IMPERSONATE,
    CLAIM_REQUEST_TIMEOUT,
    CLAIM_WARMUP_SESSION,
    INFO_ENDPOINT,
    SITE_URL,
)
from modules.proxy_manager import parse_proxy
from modules.simple_logger import logger as _logger

_ua = FakeUserAgent()


# ─────────────────── результат ───────────────────

class ClaimCheckResult:
    """Структурированный результат одной проверки."""

    __slots__ = (
        "eligible", "amount", "claimed", "tiers",
        "raw", "endpoint", "error",
    )

    def __init__(
        self,
        *,
        eligible: bool = False,
        amount: Optional[str] = None,
        claimed: Optional[bool] = None,
        tiers: Optional[list] = None,
        raw: Optional[dict] = None,
        endpoint: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        self.eligible = eligible
        self.amount = amount
        self.claimed = claimed
        self.tiers = tiers
        self.raw = raw
        self.endpoint = endpoint
        self.error = error


def _short(addr: str) -> str:
    return f"{addr[:6]}...{addr[-4:]}"


def _log(level: str, msg: str, address: str) -> None:
    # Важно: НЕ подставляем {address} внутрь msg как плейсхолдер —
    # иначе loguru попытается отформатировать и кинет KeyError.
    getattr(_logger.bind(wallet=_short(address)), level)(msg)


# ─────────────────── парсинг /airdrop/airdrop_info ───────────────────

def _parse_airdrop_info(body: dict) -> ClaimCheckResult:
    """Разобрать ответ GET /airdrop/airdrop_info.

    Известные формы:
      eligible:     {"code":0, "success":true, "data":{
                        "airdrop_amount":"9228637895000000000",  # wei
                        "airdrop_token":"0x0",
                        "claim_tier":"now",
                        "is_checked":0,
                        ...
                    }}
      not eligible: {"code":40001, "message":"no data", "data":null, "success":true}
    """
    if not isinstance(body, dict):
        return ClaimCheckResult(raw=None, eligible=False)

    code = body.get("code")
    data = body.get("data")

    # Явный «не в списке»
    if code == 40001 or data is None:
        return ClaimCheckResult(eligible=False, raw=body)

    if not isinstance(data, dict):
        return ClaimCheckResult(eligible=False, raw=body)

    amount: Optional[str] = None
    claimed: Optional[bool] = None
    tiers: Optional[list] = None

    # ── amount: приоритет у airdrop_amount (wei, 18 decimals → PHRS) ──
    raw_amount = data.get("airdrop_amount")
    if raw_amount not in (None, "", 0, "0"):
        try:
            wei = int(str(raw_amount))
            # Человекочитаемо: 4 знака после запятой, без хвостовых нулей.
            amt = wei / 10 ** 18
            amount = f"{amt:.4f}".rstrip("0").rstrip(".") or "0"
            amount = f"{amount} PHRS"
        except (TypeError, ValueError):
            amount = str(raw_amount)

    # ── fallback на старые/альтернативные ключи ──
    if amount is None:
        for k in ("amount", "allocation", "total", "reward", "points", "phrs", "total_amount"):
            v = data.get(k)
            if v not in (None, "", 0, "0"):
                amount = str(v)
                break

    # ── claimed: ИСТИННОЕ он-чейн-состояние НЕ известно API claim.pharos.xyz ──
    # Поле `is_checked` означает "tier выбран/зарегистрирован", а НЕ "дроп заклеймлен".
    # Раньше это путало логи ("claimed") и отфильтровывало кошельки от реального claim.
    # Истинный флаг ставит только claimer (после успешного on-chain receipt).
    # Оставляем fallback на явные клейм-поля, если сервер когда-либо их введёт.
    for k in ("claimed", "is_claimed", "isClaimed", "has_claimed", "hasClaimed"):
        if k in data and data[k] is not None:
            claimed = bool(data[k])
            break

    # ── tiers: сохраняем claim_tier/airdrop_type/claim_total как структурированный список ──
    tier_entry: dict = {}
    for k in ("claim_tier", "airdrop_type", "claim_total", "airdrop_token", "gas_sent"):
        if k in data and data[k] is not None:
            tier_entry[k] = data[k]
    if tier_entry:
        tiers = [tier_entry]
    else:
        for k in ("tiers", "tier_list", "allocations", "breakdown"):
            v = data.get(k)
            if isinstance(v, list) and v:
                tiers = v
                break

    eligible = bool(
        amount or tiers
        or data.get("eligible") or data.get("is_eligible")
        or data.get("airdrop_amount") or data.get("airdrop_account")
    )

    return ClaimCheckResult(
        eligible=eligible,
        amount=amount,
        claimed=claimed,
        tiers=tiers,
        raw=body,
    )


# ─────────────────── клиент ───────────────────

class ClaimChecker:
    """Одна curl_cffi-сессия = один кошелёк = один прокси."""

    def __init__(self, private_key: str, proxy: Optional[str]) -> None:
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        self._account = Account.from_key(private_key)
        self.address: str = self._account.address
        self.proxy: Optional[str] = proxy
        self.user_agent: str = _ua.random
        self._session: curl_requests.Session = self._build_session()

    def _build_session(self) -> curl_requests.Session:
        sess = curl_requests.Session(impersonate=CLAIM_IMPERSONATE)
        sess.headers.update({**CLAIM_HEADERS, "User-Agent": self.user_agent})
        normalized = parse_proxy(self.proxy)
        if normalized:
            sess.proxies = {"http": normalized, "https": normalized}
        return sess

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    # ───────── warmup ─────────
    def warmup(self) -> bool:
        if not CLAIM_WARMUP_SESSION:
            return True
        try:
            resp = self._session.get(
                SITE_URL,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1",
                },
                timeout=CLAIM_REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            return resp.status_code < 500
        except Exception as e:
            _log("debug", f"warmup: {type(e).__name__}: {e}", self.address)
            return False

    # ───────── auth ─────────
    def _build_and_sign_message(self) -> tuple[str, str]:
        ts = int(time.time() * 1000)
        message = AUTH_MESSAGE_TEMPLATE.format(address=self.address, timestamp=ts)
        signed = self._account.sign_message(encode_defunct(text=message))
        sig = signed.signature.hex()
        if not sig.startswith("0x"):
            sig = "0x" + sig
        return message, sig

    def authenticate(self) -> tuple[Optional[str], Optional[str]]:
        """Подписать сообщение и получить токен. Возвращает (token, error_or_none)."""
        message, signature = self._build_and_sign_message()
        url = API_BASE_URL + AUTH_ENDPOINT
        payload = {
            "address": self.address,
            "message": message,
            "mode": "evm",
            "signature": signature,
        }
        try:
            resp = self._session.post(url, json=payload, timeout=CLAIM_REQUEST_TIMEOUT)
        except Exception as e:
            return None, f"auth request failed: {type(e).__name__}: {str(e)[:160]}"

        preview = (resp.text or "")[:200].replace("\n", " ")
        if resp.status_code != 200:
            return None, f"auth HTTP {resp.status_code}: {preview}"
        try:
            body = resp.json()
        except Exception as e:
            return None, f"auth json parse: {e} | {preview}"

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return None, f"auth no data: {preview}"
        if not data.get("verified"):
            return None, f"auth not verified: {preview}"
        token = data.get("token")
        if not token:
            return None, f"auth empty token: {preview}"
        return token, None

    # ───────── airdrop_info ─────────
    def fetch_airdrop_info(self, token: str) -> tuple[Optional[dict], Optional[str]]:
        url = API_BASE_URL + INFO_ENDPOINT
        try:
            resp = self._session.get(
                url,
                headers={"Authorization": f"TOKEN {token}"},
                timeout=CLAIM_REQUEST_TIMEOUT,
            )
        except Exception as e:
            return None, f"info request failed: {type(e).__name__}: {str(e)[:160]}"

        preview = (resp.text or "")[:200].replace("\n", " ")
        if resp.status_code != 200:
            return None, f"info HTTP {resp.status_code}: {preview}"
        try:
            return resp.json(), None
        except Exception as e:
            return None, f"info json parse: {e} | {preview}"

    # ───────── главный метод ─────────
    def check(self) -> ClaimCheckResult:
        self.warmup()
        time.sleep(random.uniform(0.3, 1.2))

        token, err = self.authenticate()
        if err:
            return ClaimCheckResult(
                eligible=False,
                endpoint=API_BASE_URL + AUTH_ENDPOINT,
                error=err,
            )

        body, err = self.fetch_airdrop_info(token)
        if err:
            return ClaimCheckResult(
                eligible=False,
                endpoint=API_BASE_URL + INFO_ENDPOINT,
                error=err,
            )

        result = _parse_airdrop_info(body or {})
        result.endpoint = API_BASE_URL + INFO_ENDPOINT
        return result


# ─────────────────── ретраи + ротация прокси ───────────────────

def check_wallet_with_retry(
    private_key: str,
    proxy: Optional[str],
    on_proxy_rotate: Optional[Callable[[], Optional[str]]] = None,
) -> ClaimCheckResult:
    """Проверить один кошелёк с ретраями и ротацией прокси между попытками."""
    current_proxy = proxy
    last_error: Optional[str] = None
    address_for_log = "0x????"

    attempts = max(1, int(RETRY_COUNT))
    for attempt in range(1, attempts + 1):
        checker = ClaimChecker(private_key, current_proxy)
        address_for_log = checker.address
        try:
            result = checker.check()
        finally:
            checker.close()

        if result.error is None:
            return result

        last_error = result.error
        _log(
            "warning",
            f"Попытка {attempt}/{attempts}: {result.error}",
            address_for_log,
        )

        if attempt < attempts:
            if on_proxy_rotate is not None:
                new_proxy = on_proxy_rotate()
                if new_proxy and new_proxy != current_proxy:
                    current_proxy = new_proxy
                    _log("info", "Прокси заменён, повтор…", address_for_log)
            time.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

    return ClaimCheckResult(eligible=False, error=last_error or "unknown error")
