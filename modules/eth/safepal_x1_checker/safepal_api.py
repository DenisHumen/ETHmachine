"""Низкоуровневый клиент API SafePal Claim X1.

Реверс-инжинирен из бандла https://www.safepal.com/claimX1/V2/assets/index-*.js.

Эндпоинты:
  POST  https://www.safepal.com/mshopapi/V2/party/checkChannelCode    (multipart)
  POST  https://www.safepal.com/mshopapi/V1/getSignMsg                (json)
  POST  https://www.safepal.com/mshopapi/V1/authSign                  (json)
  POST  https://www.safepal.com/mshopapi/V2/party/activityShopingToken (multipart, session-id)
  POST  https://www.safepal.com/mshopapi/V2/party/checkIsCanOrder     (multipart, session-id)

Подпись — personal_sign (EIP-191) сообщения, возвращённого getSignMsg.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from eth_account import Account
from eth_account.messages import encode_defunct

from config.modules.cfg_safepal_x1_checker import HTTP_TIMEOUT

V1 = "https://www.safepal.com/mshopapi/V1"
V2 = "https://www.safepal.com/mshopapi/V2"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_BASE_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.safepal.com",
    "Referer": "https://www.safepal.com/en/claimX1/v2/",
}


class SafepalError(Exception):
    pass


# ──────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────

def _parse_response(r: requests.Response) -> Any:
    ct = (r.headers.get("Content-Type") or "").lower()
    text = r.text
    if "json" in ct:
        return r.json()
    stripped = text.strip()
    # Иногда сервер отдаёт JSON без json content-type
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return r.json()
        except Exception:
            pass
    # plain text (например "YES" / "NO" / токен)
    return stripped.strip('"')


def _post_form(
    url: str,
    fields: Dict[str, Any],
    *,
    headers: Optional[Dict[str, str]] = None,
    proxies: Optional[Dict[str, str]] = None,
) -> Any:
    files = {k: (None, str(v)) for k, v in fields.items()}
    h = dict(_BASE_HEADERS)
    if headers:
        h.update(headers)
    r = requests.post(url, files=files, headers=h, proxies=proxies, timeout=HTTP_TIMEOUT)
    if r.status_code >= 500:
        raise SafepalError(f"{url} -> HTTP {r.status_code}: {r.text[:200]}")
    return _parse_response(r)


def _post_json(
    url: str,
    payload: Dict[str, Any],
    *,
    headers: Optional[Dict[str, str]] = None,
    proxies: Optional[Dict[str, str]] = None,
) -> Any:
    h = dict(_BASE_HEADERS)
    h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    r = requests.post(url, json=payload, headers=h, proxies=proxies, timeout=HTTP_TIMEOUT)
    if r.status_code >= 500:
        raise SafepalError(f"{url} -> HTTP {r.status_code}: {r.text[:200]}")
    return _parse_response(r)


# ──────────────────────────────────────────────────────────────────────
# public API
# ──────────────────────────────────────────────────────────────────────

def check_channel_code(act_code: str, channel_code: str,
                       proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Возвращает {code, msg, channelName, sku, chainType}."""
    res = _post_form(f"{V2}/party/checkChannelCode",
                     {"actCode": act_code, "channelCode": channel_code},
                     proxies=proxies)
    if not isinstance(res, dict):
        raise SafepalError(f"checkChannelCode unexpected response: {res!r}")
    if res.get("code") not in (0, None):
        raise SafepalError(f"checkChannelCode code={res.get('code')} msg={res.get('msg')}")
    return res


def get_sign_msg(chain_id: int | str, wallet_address: str,
                 proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Возвращает {nonce, msg, serverTime, signType, domain}."""
    res = _post_json(f"{V1}/getSignMsg",
                    {"signType": 1, "chainId": chain_id, "walletAddress": wallet_address},
                    proxies=proxies)
    if not isinstance(res, dict) or "msg" not in res or "nonce" not in res:
        raise SafepalError(f"getSignMsg failed: {res!r}")
    return res


def sign_personal_message(private_key: str, message: str) -> str:
    """personal_sign (EIP-191). Возвращает hex-сигнатуру с префиксом 0x."""
    encoded = encode_defunct(text=message)
    signed = Account.sign_message(encoded, private_key=private_key)
    sig = signed.signature
    h = sig.hex() if hasattr(sig, "hex") else bytes(sig).hex()
    return h if h.startswith("0x") else f"0x{h}"


def auth_sign(chain_id: int | str, wallet_address: str, signature: str,
              server_time: int, message: str, nonce: str,
              proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Подтверждение подписи. Возвращает объект с session_id."""
    payload = {
        "signType": 1,
        "chainId": chain_id,
        "walletAddress": wallet_address,
        "signature": signature,
        "serverTime": server_time,
        "message": message,
        "nonce": nonce,
    }
    res = _post_json(f"{V1}/authSign", payload, proxies=proxies)
    if not isinstance(res, dict) or not res.get("session_id"):
        raise SafepalError(f"authSign failed: {res!r}")
    return res


def get_activity_shopping_token(chain_id: int | str, address: str,
                                act_code: str, channel_code: str,
                                session_id: str,
                                proxies: Optional[Dict[str, str]] = None) -> str:
    """Получение token для проверки заказа. Может вернуть строку или dict."""
    res = _post_form(
        f"{V2}/party/activityShopingToken",
        {"chain": chain_id, "address": address,
         "actCode": act_code, "channelCode": channel_code},
        headers={"session-id": session_id},
        proxies=proxies,
    )
    if isinstance(res, dict):
        if res.get("code") not in (0, None):
            raise SafepalError(f"activityShopingToken code={res.get('code')} msg={res.get('msg')}")
        token = res.get("data") or res.get("token") or res.get("msg") or ""
    else:
        token = str(res)
    token = (token or "").strip()
    if not token or token.upper() in ("OK", "NO", "YES"):
        raise SafepalError(f"activityShopingToken empty/invalid token: {res!r}")
    return token


def check_is_can_order(token: str, chain_id: int | str, address: str,
                       session_id: str,
                       proxies: Optional[Dict[str, str]] = None) -> str:
    """Финальная проверка элигбла. Возвращает 'YES' или 'NO' (или raw)."""
    res = _post_form(
        f"{V2}/party/checkIsCanOrder",
        {"token": token, "chainId": chain_id, "address": address},
        headers={"session-id": session_id},
        proxies=proxies,
    )
    if isinstance(res, dict):
        if res.get("code") not in (0, None):
            raise SafepalError(f"checkIsCanOrder code={res.get('code')} msg={res.get('msg')}")
        v = res.get("data") or res.get("msg") or ""
        return str(v).strip().upper()
    return str(res).strip().upper()
