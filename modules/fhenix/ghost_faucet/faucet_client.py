"""HTTP-клиент для Ghost Faucet (ghostchain.io)."""
import re
import time
from typing import Optional, Tuple

import requests

from config.modules.cfg_fhenix import (
    GHOST_FAUCET_URL,
    GHOST_FAUCET_AJAX_URL,
    GHOST_FAUCET_NETWORK_KEY,
    GHOST_FAUCET_TURNSTILE_SITEKEY,
    GHOST_FAUCET_HTTP_TIMEOUT,
)
from modules.proxy_manager import get_proxy_dict


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_NONCE_RE = re.compile(
    r'name="ghost_faucet_nonce"[^>]*value="([a-f0-9]+)"', re.IGNORECASE
)


class GhostFaucetError(Exception):
    pass


class GhostFaucetCooldownError(GhostFaucetError):
    """Сервер ответил, что лимит исчерпан (24h)."""


def make_session(proxy: Optional[str] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    })
    proxy_dict = get_proxy_dict(proxy)
    if proxy_dict:
        s.proxies = proxy_dict
    return s


def fetch_nonce(session: requests.Session) -> str:
    """Загрузить страницу крана и достать `ghost_faucet_nonce` из формы."""
    resp = session.get(GHOST_FAUCET_URL, timeout=GHOST_FAUCET_HTTP_TIMEOUT)
    resp.raise_for_status()
    m = _NONCE_RE.search(resp.text)
    if not m:
        raise GhostFaucetError("ghost_faucet_nonce не найден в HTML формы")
    return m.group(1)


def submit_claim(
    session: requests.Session,
    wallet: str,
    nonce: str,
    turnstile_token: str,
) -> Tuple[bool, Optional[str], str]:
    """POST на admin-ajax.php. Возвращает (success, tx_hash, raw_message).

    Поднимает GhostFaucetCooldownError, если сервер ответил «Request limit reached».
    """
    # Минимальная пауза от старта сессии — фронт проверяет timeDiff>=2.5s
    time.sleep(3.0)

    payload = {
        "action": "submit_ghost_faucet",
        "wallet": wallet,
        "network": GHOST_FAUCET_NETWORK_KEY,
        "ghost_faucet_nonce": nonce,
        "ghost_hp_field": "",
        "cf-turnstile-response": turnstile_token,
    }
    headers = {
        "Origin": "https://ghostchain.io",
        "Referer": GHOST_FAUCET_URL,
        "X-Requested-With": "XMLHttpRequest",
    }
    resp = session.post(
        GHOST_FAUCET_AJAX_URL,
        data=payload,
        headers=headers,
        timeout=GHOST_FAUCET_HTTP_TIMEOUT,
    )
    resp.raise_for_status()

    try:
        data = resp.json()
    except ValueError:
        raise GhostFaucetError(f"Невалидный JSON от сервера: {resp.text[:200]}")

    success = bool(data.get("success"))
    payload_data = data.get("data")

    if success and isinstance(payload_data, dict):
        return True, payload_data.get("hash"), "ok"

    if isinstance(payload_data, dict):
        inner = payload_data.get("message") or payload_data.get("error")
        msg = str(inner) if inner else str(payload_data)
    elif payload_data is None:
        msg = ""
    else:
        msg = str(payload_data)
    lower = msg.lower()
    if "limit reached" in lower or "one submission" in lower or "24 hour" in lower:
        raise GhostFaucetCooldownError(msg)
    return False, None, msg


# Турникет публикует sitekey в HTML; вынесли как константу для модуля капчи.
TURNSTILE_SITEKEY = GHOST_FAUCET_TURNSTILE_SITEKEY
TURNSTILE_PAGEURL = GHOST_FAUCET_URL
