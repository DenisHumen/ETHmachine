"""Sahara Earndrop API client (knowledgedrop.saharaai.com / earndrop.prd.galaxy.eco).

Воспроизводит сетевой flow web-приложения:
  1) POST /sign_in          — SIWE-сообщение + подпись → JWT-токен
  2) GET  /sahara/info      — статус аллокации, stages, claimed/eligible amounts
  3) POST /sahara/prepare_claim → params + signature + contract_address + claim_fee
  4) (on-chain) claimEarndrop / multiClaimEarndrop на BSC
  5) POST /sahara/record_claim   — финализация (фиксация tx-hash на бекенде)
  6) GET  /sahara/claim_history (опционально)

Используются:
  - eth_account для SIWE-подписи (encode_defunct)
  - requests для HTTP (поддержка прокси per-call)
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from eth_account import Account
from eth_account.messages import encode_defunct

from config.modules.cfg_sahara import (
    EARNDROP_API_BASE,
    HTTP_TIMEOUT,
    SITE_DOMAIN,
    SITE_ORIGIN,
    SIWE_STATEMENT,
    CHAIN_ID,
)


class EarndropError(Exception):
    """Унифицированная ошибка взаимодействия с earndrop API."""


def _siwe_nonce() -> str:
    # SIWE требует alphanumeric nonce длиной >=8. Делаем 17-символьный hex.
    return secrets.token_hex(8) + secrets.choice("0123456789abcdef")


def build_siwe_message(address: str, nonce: Optional[str] = None,
                       expiration_hours: int = 168) -> str:
    """Собирает SIWE-сообщение, идентичное тому, что генерирует фронт сайта.

    expiration_hours=168 → 7 дней, как в JS-коде (`6048e5` мс).
    """
    nonce = nonce or _siwe_nonce()
    issued_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    expiration = (datetime.now(timezone.utc) + timedelta(hours=expiration_hours)) \
        .strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"

    return (
        f"{SITE_DOMAIN} wants you to sign in with your Ethereum account:\n"
        f"{address}\n"
        f"\n"
        f"{SIWE_STATEMENT}\n"
        f"\n"
        f"URI: {SITE_ORIGIN}\n"
        f"Version: 1\n"
        f"Chain ID: {CHAIN_ID}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}\n"
        f"Expiration Time: {expiration}"
    )


class EarndropClient:
    """Тонкая обёртка над requests с авторизацией earndrop API.

    Один инстанс — один кошелёк. Безопасно использовать в потоках:
    каждый поток создаёт свой Client (как требует AGENTS.md §11).
    """

    def __init__(self, private_key: str, proxy: Optional[str] = None,
                 user_agent: Optional[str] = None):
        pk = private_key if private_key.startswith("0x") else f"0x{private_key}"
        self._account = Account.from_key(pk)
        self.address: str = self._account.address

        self._session = requests.Session()
        if proxy:
            self._session.proxies.update({'http': proxy, 'https': proxy})
        self._session.headers.update({
            'User-Agent': user_agent or (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/123.0 Safari/537.36'
            ),
            'Accept': 'application/json, text/plain, */*',
            'Origin': SITE_ORIGIN,
            'Referer': SITE_ORIGIN + '/',
        })
        self._token: Optional[str] = None

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _auth_headers(self) -> Dict[str, str]:
        if not self._token:
            raise EarndropError("Not signed in: call sign_in() first")
        return {'Authorization': self._token}

    def _post(self, path: str, json_body: Optional[dict] = None,
              auth: bool = True) -> dict:
        headers: Dict[str, str] = {'Content-Type': 'application/json'}
        if auth:
            headers.update(self._auth_headers())
        url = EARNDROP_API_BASE + path
        try:
            r = self._session.post(url, json=json_body, headers=headers,
                                   timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            raise EarndropError(f"POST {path} network error: {e}") from e
        return self._parse(r, path)

    def _get(self, path: str, auth: bool = True) -> dict:
        headers: Dict[str, str] = {}
        if auth:
            headers.update(self._auth_headers())
        url = EARNDROP_API_BASE + path
        try:
            r = self._session.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            raise EarndropError(f"GET {path} network error: {e}") from e
        return self._parse(r, path)

    @staticmethod
    def _parse(r: requests.Response, path: str) -> dict:
        try:
            body = r.json()
        except ValueError:
            raise EarndropError(
                f"{path}: HTTP {r.status_code}, non-JSON response: "
                f"{r.text[:300]}"
            )
        if r.status_code >= 400:
            raise EarndropError(
                f"{path}: HTTP {r.status_code} {body}"
            )
        # Earndrop иногда отдаёт ошибку в поле code/msg даже при 200.
        if isinstance(body, dict):
            code = body.get('code')
            if code not in (None, 0, '0', 200, '200'):
                raise EarndropError(f"{path}: API code={code} body={body}")
        return body

    # ------------------------------------------------------------------
    # public flow
    # ------------------------------------------------------------------
    def sign_in(self) -> str:
        """SIWE-аутентификация. Сохраняет token внутри клиента и возвращает его."""
        message = build_siwe_message(self.address)
        signature = self._account.sign_message(
            encode_defunct(text=message)
        ).signature.hex()
        if not signature.startswith('0x'):
            signature = '0x' + signature

        body = self._post('/sign_in', json_body={
            'address': self.address,
            'signature': signature,
            'message': message,
            'public_key': '',
        }, auth=False)

        token = body.get('token') or (body.get('data') or {}).get('token')
        if not token:
            raise EarndropError(f"/sign_in returned no token: {body}")
        self._token = token
        return token

    def get_info(self) -> dict:
        """Аллокация и stages. data может быть None если кошелёк не eligible."""
        body = self._get('/sahara/info')
        return body.get('data') or {}

    def prepare_claim(self) -> dict:
        """Получить calldata-параметры для on-chain claim."""
        body = self._post('/sahara/prepare_claim', json_body=None)
        data = body.get('data')
        if not data:
            raise EarndropError(f"/sahara/prepare_claim empty data: {body}")
        return data

    def record_claim(self, *, tx_hash: str, address: str, amount: str) -> dict:
        body = self._post('/sahara/record_claim', json_body={
            'tx': tx_hash,
            'address': address,
            'amount': str(amount),
        })
        return body.get('data') or {}

    def claim_history(self) -> List[Dict[str, Any]]:
        body = self._get('/sahara/claim_history')
        data = body.get('data')
        return data if isinstance(data, list) else []
