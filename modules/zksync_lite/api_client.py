"""Лёгкий клиент публичного REST API zkSync Lite (v0.2).

Эмулирует работу сайта https://lite.zksync.io/account: страница после
подключения кошелька получает данные именно через этот endpoint
(`/api/v0.2/accounts/{address}`), поэтому фактический MetaMask/OKX
не нужен — мы запрашиваем баланс напрямую.

Поддержка прокси: каждому кошельку — свой прокси из data.csv.
"""

from __future__ import annotations

import threading
from decimal import Decimal
from typing import Any, Dict, Optional

import requests

from modules.proxy_manager import parse_proxy

API_BASE = "https://api.zksync.io/api/v0.2"
DEFAULT_TIMEOUT = 20

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://lite.zksync.io",
    "Referer": "https://lite.zksync.io/",
}


# ────────────────────── Token decimals cache ──────────────────────

_token_decimals: Dict[str, int] = {}
_token_decimals_lock = threading.Lock()
_token_decimals_loaded = False


def _proxies_dict(proxy_raw: Optional[str]) -> Optional[Dict[str, str]]:
    url = parse_proxy(proxy_raw)
    if not url:
        return None
    return {"http": url, "https": url}


def load_token_decimals(proxy_raw: Optional[str] = None, force: bool = False) -> Dict[str, int]:
    """Один раз загружает все токены zkSync Lite и кэширует их decimals.

    Эндпоинт листает страницами по 100 шт. Всего ≈185 токенов.
    """
    global _token_decimals_loaded
    with _token_decimals_lock:
        if _token_decimals_loaded and not force and _token_decimals:
            return _token_decimals

        proxies = _proxies_dict(proxy_raw)
        decimals: Dict[str, int] = {}
        cursor = "0"
        for _ in range(50):  # safety hard limit
            try:
                resp = requests.get(
                    f"{API_BASE}/tokens",
                    params={"from": cursor, "limit": 100, "direction": "newer"},
                    headers=_HEADERS,
                    proxies=proxies,
                    timeout=DEFAULT_TIMEOUT,
                )
            except Exception:
                break
            if resp.status_code != 200:
                break
            data = resp.json()
            if data.get("status") != "success":
                break
            tokens = (data.get("result") or {}).get("list") or []
            if not tokens:
                break
            for t in tokens:
                sym = t.get("symbol")
                dec = t.get("decimals")
                if sym is not None and dec is not None:
                    decimals[sym] = int(dec)
            if len(tokens) < 100:
                break
            cursor = str(int(tokens[-1]["id"]) + 1)

        if decimals:
            _token_decimals.update(decimals)
            _token_decimals_loaded = True
        return _token_decimals


def get_decimals(symbol: str) -> int:
    """Decimals для токена (0 если неизвестен)."""
    return _token_decimals.get(symbol, 0)


def format_amount(raw: str | int, decimals: int) -> str:
    """raw → human-readable (Decimal). Возвращает str без e-нотации."""
    try:
        n = Decimal(str(raw))
    except Exception:
        return str(raw)
    if decimals <= 0:
        return f"{n.normalize():f}"
    scaled = n / (Decimal(10) ** decimals)
    s = format(scaled.normalize(), "f")
    return s


# ────────────────────── Account fetch ──────────────────────


class ZkSyncLiteAPIError(Exception):
    pass


def fetch_account(address: str, proxy_raw: Optional[str] = None) -> Dict[str, Any]:
    """Возвращает «сырой» result из ответа /accounts/{address}.

    Бросает ZkSyncLiteAPIError при сетевых/HTTP/API ошибках.
    """
    proxies = _proxies_dict(proxy_raw)
    try:
        resp = requests.get(
            f"{API_BASE}/accounts/{address}",
            headers=_HEADERS,
            proxies=proxies,
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ZkSyncLiteAPIError(f"network: {exc}") from exc

    if resp.status_code != 200:
        raise ZkSyncLiteAPIError(f"HTTP {resp.status_code}: {resp.text[:120]}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise ZkSyncLiteAPIError(f"bad json: {exc}") from exc

    if data.get("status") != "success":
        err = (data.get("error") or {}).get("message") or "unknown api error"
        raise ZkSyncLiteAPIError(err)

    return data.get("result") or {}


def parse_account(raw_result: Dict[str, Any]) -> Dict[str, Any]:
    """Преобразует ответ API в структуру для записи в БД.

    Возвращает dict со следующими ключами:
        account_id, pubkey_hash, account_type, nonce, is_active,
        eth_balance (human-readable str), balances (symbol → {raw, amount, decimals}),
        nfts (id → {symbol, address, contentHash})
    """
    committed = raw_result.get("committed") or {}
    depositing = (raw_result.get("depositing") or {}).get("balances") or {}

    is_active = bool(committed)
    account_id = committed.get("accountId") if committed else None
    pubkey_hash = committed.get("pubKeyHash") if committed else None
    account_type = committed.get("accountType") if committed else None
    nonce = committed.get("nonce") if committed else None

    raw_balances: Dict[str, str] = dict(committed.get("balances") or {})
    # объединяем с депозитами «в пути»
    for sym, val in depositing.items():
        if sym not in raw_balances:
            raw_balances[sym] = str(val)

    balances: Dict[str, Dict[str, Any]] = {}
    for sym, raw in raw_balances.items():
        dec = get_decimals(sym)
        amount = format_amount(raw, dec)
        balances[sym] = {"raw": str(raw), "amount": amount, "decimals": dec}

    eth_balance = balances.get("ETH", {}).get("amount") if "ETH" in balances else None

    nfts_raw = (committed.get("nfts") or {}) if committed else {}
    nfts: Dict[str, Dict[str, Any]] = {}
    for nft_id, nft in nfts_raw.items():
        nfts[str(nft_id)] = {
            "symbol": nft.get("symbol"),
            "address": nft.get("address"),
            "content_hash": nft.get("contentHash"),
            "creator_address": nft.get("creatorAddress"),
        }

    return {
        "account_id": account_id,
        "pubkey_hash": pubkey_hash,
        "account_type": account_type,
        "nonce": nonce,
        "is_active": is_active,
        "eth_balance": eth_balance,
        "balances": balances,
        "nfts": nfts,
    }


__all__ = [
    "API_BASE",
    "ZkSyncLiteAPIError",
    "load_token_decimals",
    "get_decimals",
    "format_amount",
    "fetch_account",
    "parse_account",
]
