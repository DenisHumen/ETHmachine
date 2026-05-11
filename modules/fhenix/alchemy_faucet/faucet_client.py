"""HTTP-клиент для Alchemy Base Sepolia faucet (alchemy.com/faucets/base-sepolia).

Реверс-инжинирные данные собраны из чанка _next/static/chunks/0b_y0tnec2m-9.js:
  POST  /api/faucets/{faucetId}/send       body={"address": "0x..", "turnstileToken": ".."}
  GET   /api/faucets/{faucetId}/status?transactionHash=0x..
  Captcha — Cloudflare Turnstile, sitekey 0x4AAAAAAB_Xdru0nbY8rQu_
  faucetId соответствует slug в URL: для https://www.alchemy.com/faucets/base-sepolia → "base-sepolia"
"""
from typing import Optional, Tuple

import requests

from config.modules.cfg_fhenix import (
    ALCHEMY_FAUCET_URL,
    ALCHEMY_FAUCET_API_SEND,
    ALCHEMY_FAUCET_TURNSTILE_SITEKEY,
    ALCHEMY_FAUCET_HTTP_TIMEOUT,
)
from modules.proxy_manager import get_proxy_dict


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class AlchemyFaucetError(Exception):
    pass


class AlchemyFaucetCooldownError(AlchemyFaucetError):
    """Сервер ответил, что заявка уже подана (кулдаун 24h)."""


# Сообщения, по которым определяем серверный кулдаун.
# Подбираем по ключевым словам — Alchemy может менять формулировки.
_COOLDOWN_MARKERS = (
    "rate limit",
    "rate-limit",
    "already claim",
    "already received",
    "wait 24",
    "24 hour",
    "24h",
    "try again later",
    "cooldown",
    "limit reached",
    "one request",
    "one claim",
)

# Сообщения о неподходящем кошельке (mainnet-balance / activity check).
# По сути — ошибки конкретного аккаунта, ретрай не поможет.
_INELIGIBLE_MARKERS = (
    "insufficient",
    "mainnet balance",
    "transaction history",
    "activity",
    "not eligible",
    "qualify",
)


def make_session(proxy: Optional[str] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.alchemy.com",
        "Referer": ALCHEMY_FAUCET_URL,
    })
    proxy_dict = get_proxy_dict(proxy)
    if proxy_dict:
        s.proxies = proxy_dict
    return s


def classify_error(message: str) -> str:
    """Возвращает 'cooldown' | 'ineligible' | 'transient' по тексту ошибки."""
    low = (message or "").lower()
    for m in _COOLDOWN_MARKERS:
        if m in low:
            return "cooldown"
    for m in _INELIGIBLE_MARKERS:
        if m in low:
            return "ineligible"
    return "transient"


def submit_claim(
    session: requests.Session,
    wallet: str,
    turnstile_token: str,
) -> Tuple[bool, Optional[str], str]:
    """POST /api/faucets/base-sepolia/send. Возвращает (success, tx_hash, raw_message).

    Поднимает AlchemyFaucetCooldownError, если ответ выглядит как server-side cooldown.
    """
    payload = {
        "address": wallet,
        "turnstileToken": turnstile_token,
    }
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "X-Requested-With": "XMLHttpRequest",
    }
    resp = session.post(
        ALCHEMY_FAUCET_API_SEND,
        json=payload,
        headers=headers,
        timeout=ALCHEMY_FAUCET_HTTP_TIMEOUT,
    )

    raw = resp.text or ""
    try:
        data = resp.json() if raw else {}
    except ValueError:
        # Неожиданный HTML/текст — возможно cloudflare interstitial / 5xx
        if resp.status_code == 429:
            raise AlchemyFaucetCooldownError(f"HTTP 429: {raw[:200]}")
        resp.raise_for_status()
        raise AlchemyFaucetError(f"Невалидный JSON от сервера (HTTP {resp.status_code}): {raw[:200]}")

    tx_hash = data.get("transactionHash") if isinstance(data, dict) else None
    if tx_hash:
        return True, tx_hash, "ok"

    msg = ""
    if isinstance(data, dict):
        msg = (data.get("error") or data.get("message") or "").strip()
    if not msg:
        msg = f"HTTP {resp.status_code}: {raw[:200]}".strip()

    kind = classify_error(msg)
    if kind == "cooldown" or resp.status_code == 429:
        raise AlchemyFaucetCooldownError(msg or f"HTTP {resp.status_code}")

    # Прочие отказы (включая ineligible) возвращаем как failure — хендлер решит.
    return False, None, msg


# Турникет публикует sitekey в HTML; вынесли как константу для модуля капчи.
TURNSTILE_SITEKEY = ALCHEMY_FAUCET_TURNSTILE_SITEKEY
TURNSTILE_PAGEURL = ALCHEMY_FAUCET_URL
