"""HTTP-клиент Midas Prediction Market (predict-testnet-api.midashand.xyz).

Все маршруты выглядят как `<MIDAS_API_BASE><path>`, где path начинается со
слеша (без префикса `/api`). API возвращает JSON формата
`{"success": bool, "data": {...}, "error": {"message": str}?}`.

Auth: для протектед-эндпоинтов используется `Authorization: Bearer <JWT>`.
JWT получается после POST /auth/wallet/register или /auth/wallet/login.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import requests

from config.modules.cfg_litvm_testnet import (
    MIDAS_API_BASE,
    MIDAS_HTTP_ATTEMPTS,
    MIDAS_HTTP_RETRY_DELAY,
    MIDAS_HTTP_TIMEOUT,
)
from modules.proxy_manager import get_proxy_dict


class MidasApiError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None,
                 body: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class MidasClient:
    """Тонкая обёртка над requests.Session с retry и JWT-кэшем.

    Если первичный proxy выдаёт network error / 5xx на всех attempts —
    автоматически переключаемся на reserve_proxy (если передан).
    Собираем всего MIDAS_HTTP_ATTEMPTS по каждому прокси.
    """

    def __init__(self, proxy: Optional[str] = None,
                 user_agent: Optional[str] = None,
                 reserve_proxy: Optional[str] = None):
        self.proxy = proxy
        self.reserve_proxy = reserve_proxy or None
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": user_agent or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Origin": "https://www.midashand.xyz",
            "Referer": "https://www.midashand.xyz/",
        })
        self.token: Optional[str] = None
        self.active_proxy: Optional[str] = proxy  # текущий выбранный

    def set_token(self, token: Optional[str]) -> None:
        self.token = token

    def _proxy_chain(self) -> list[Optional[str]]:
        chain: list[Optional[str]] = []
        seen: set[str] = set()
        for p in (self.proxy, self.reserve_proxy):
            key = (p or "").strip()
            if key in seen:
                continue
            chain.append(p if key else None)
            seen.add(key)
        if not chain:
            chain = [None]
        return chain

    # ------------------------------------------------------------------ low level
    def _request(self, method: str, path: str, *,
                 params: Optional[dict] = None,
                 json: Optional[dict] = None,
                 auth_required: bool = False,
                 expected_codes: tuple = (200, 201)) -> dict:
        url = MIDAS_API_BASE.rstrip("/") + path
        last_exc: Optional[Exception] = None
        proxies_chain = self._proxy_chain()
        for proxy_idx, proxy in enumerate(proxies_chain):
            proxies = get_proxy_dict(proxy) if proxy else None
            self.active_proxy = proxy
            transient = False
            for attempt in range(1, int(MIDAS_HTTP_ATTEMPTS) + 1):
                headers = dict(self._session.headers)
                if auth_required and self.token:
                    headers["Authorization"] = f"Bearer {self.token}"
                try:
                    resp = self._session.request(
                        method, url, params=params, json=json, headers=headers,
                        proxies=proxies, timeout=MIDAS_HTTP_TIMEOUT,
                    )
                except requests.RequestException as e:
                    last_exc = e
                    transient = True
                    if attempt < MIDAS_HTTP_ATTEMPTS:
                        time.sleep(MIDAS_HTTP_RETRY_DELAY)
                        continue
                    break  # уйдём на следующий proxy в chain

                # Парсим тело (json или text)
                try:
                    body = resp.json()
                except Exception:
                    body = {"raw": resp.text}

                if resp.status_code in expected_codes:
                    if isinstance(body, dict) and body.get("success") is False:
                        err = (body.get("error") or {})
                        msg = (err.get("message") or err.get("code")
                               or "API failed")
                        raise MidasApiError(msg, resp.status_code, body)
                    return body if isinstance(body, dict) else {"data": body}

                # 5xx → retry на текущем proxy, потом переключим
                if resp.status_code >= 500:
                    last_exc = MidasApiError(
                        f"HTTP {resp.status_code}", resp.status_code, body)
                    transient = True
                    if attempt < MIDAS_HTTP_ATTEMPTS:
                        time.sleep(MIDAS_HTTP_RETRY_DELAY)
                        continue
                    break

                # 4xx / финал — НЕ ретраим, не переключаем proxy
                msg = "HTTP " + str(resp.status_code)
                if isinstance(body, dict):
                    err = body.get("error") or {}
                    if isinstance(err, dict):
                        msg = err.get("message") or err.get("code") or msg
                    elif isinstance(err, str):
                        msg = err
                    elif body.get("message"):
                        msg = body["message"]
                raise MidasApiError(msg, resp.status_code, body)

            # \u044d\u0442\u043e\u0442 proxy \u0438\u0441\u0447\u0435\u0440\u043f\u0430\u043b attempts \u0438\u043b\u0438 \u043b\u043e\u0432\u0438\u043b transient
            if not transient or proxy_idx >= len(proxies_chain) - 1:
                break  # последний proxy → выходим во внешний raise

        if isinstance(last_exc, MidasApiError):
            raise last_exc
        raise MidasApiError(f"network error: {last_exc}") from last_exc

    # ------------------------------------------------------------------ public
    def get_nonce(self, wallet_address: str) -> dict:
        """GET /auth/nonce?walletAddress=...
        Returns dict: {nonce, message, timestamp}."""
        r = self._request("GET", "/auth/nonce",
                          params={"walletAddress": wallet_address})
        return r.get("data") or {}

    def check_wallet(self, wallet_address: str) -> dict:
        """POST /auth/wallet — «логин-и-проверка».

        Сервер принимает только {walletAddress} и возвращает:
          {registered: bool, accessToken?, refreshToken?, user?}
        Если registered=true · accessToken уже выдан (это и есть логин).
        Если registered=false · нужна регистрация (signature + captcha).

        Как побочный эффект — если выдан accessToken, сохраняем его в self.token.
        """
        try:
            r = self._request("POST", "/auth/wallet",
                              json={"walletAddress": wallet_address})
        except MidasApiError as e:
            if e.status_code in (400, 404):
                return {}
            msg = (str(e) or "").lower()
            if "not_found" in msg or "not found" in msg or "no user" in msg:
                return {}
            raise
        data = r.get("data") or {}
        token = (data.get("accessToken") or data.get("token")
                 or data.get("authToken"))
        if token:
            self.set_token(token)
        return data

    def login(self, *, wallet_address: str, signature: str | None = None,
              message: str | None = None) -> dict:
        """Совместимый wrapper. Реальный login — это check_wallet().

        signature/message игнорируются (сервер их не принимает
        на этом маршруте), оставлены для обратной совместимости.
        """
        _ = (signature, message)
        data = self.check_wallet(wallet_address)
        if not data.get("accessToken"):
            raise MidasApiError(
                "login: wallet не вернул accessToken (возможно не зарегистрирован)",
                400, data,
            )
        return data

    def register(self, *, wallet_address: str, signature: str, message: str,
                 nickname: str, captcha_token: str,
                 referral_code: Optional[str] = None) -> dict:
        """POST /auth/wallet/register — возвращает {accessToken, ...}."""
        body = {
            "walletAddress": wallet_address,
            "signature": signature,
            "message": message,
            "displayName": nickname,
            "captchaToken": captcha_token,
        }
        if referral_code:
            body["referralCode"] = referral_code
        r = self._request("POST", "/auth/wallet/register", json=body)
        data = r.get("data") or {}
        token = (data.get("accessToken") or data.get("token") or
                 data.get("authToken"))
        if token:
            self.set_token(token)
        return data


    # ---- faucets ------------------------------------------------------
    def faucet_usdc(self, wallet_address: str) -> dict:
        r = self._request("POST", "/users/faucet_usdc",
                          json={"walletAddress": wallet_address},
                          auth_required=True)
        return r.get("data") or r

    def faucet_native(self, wallet_address: str) -> dict:
        r = self._request("POST", "/users/faucet_native",
                          json={"walletAddress": wallet_address},
                          auth_required=True)
        return r.get("data") or r

    # ---- check-in -----------------------------------------------------
    def checkin(self) -> dict:
        r = self._request("POST", "/login/checkin", json={},
                          auth_required=True)
        return r.get("data") or r

    def streak(self) -> dict:
        r = self._request("GET", "/login/streak", auth_required=True)
        return r.get("data") or r

    # ---- markets ------------------------------------------------------
    def list_markets(self, *, sort_by: str = "trending",
                     page: int = 1, limit: int = 50) -> list[dict]:
        r = self._request("GET", "/markets",
                          params={"sortBy": sort_by, "page": page,
                                  "limit": limit})
        data = r.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("markets", "items", "results"):
                v = data.get(key)
                if isinstance(v, list):
                    return v
        return []

    def collateral_tokens(self) -> list[dict]:
        r = self._request("GET", "/markets/collateral-tokens")
        data = r.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("tokens", "items"):
                v = data.get(key)
                if isinstance(v, list):
                    return v
        return []

    def get_user_me(self) -> dict:
        r = self._request("GET", "/users/me", auth_required=True)
        return r.get("data") or r
