"""Layerswap v2 client adapted for Polygon zkEVM → Base."""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, Optional

import requests

API_BASE = "https://api.layerswap.io/api/v2"
SOURCE_NETWORK = "POLYGONZK_MAINNET"
DEST_NETWORK = "BASE_MAINNET"

# Verified live (2026-05-07): USDC and ETH routes work; USDT route not found.
SUPPORTED_PAIRS: Dict[str, str] = {
    "USDC": "USDC",
    "ETH": "ETH",
}

DEFAULT_TIMEOUT = 30


class LayerswapError(RuntimeError):
    pass


class LayerswapClient:
    def __init__(self, *, api_key: Optional[str] = None,
                 timeout: int = DEFAULT_TIMEOUT,
                 session: Optional[requests.Session] = None) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "ETHmachine/1.0",
        })
        if api_key:
            self.session.headers["X-LS-APIKEY"] = api_key

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None,
             proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        r = self.session.get(API_BASE + path, params=params,
                             timeout=self.timeout, proxies=proxies)
        return _parse(r)

    def _post(self, path: str, body: Dict[str, Any],
              proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        r = self.session.post(API_BASE + path, json=body,
                              timeout=self.timeout, proxies=proxies)
        return _parse(r)

    def is_supported(self, token: str) -> bool:
        return token.upper() in SUPPORTED_PAIRS

    def limits(self, source_token: str,
               proxies: Optional[Dict[str, str]] = None) -> Dict[str, Decimal]:
        src = source_token.upper()
        if src not in SUPPORTED_PAIRS:
            raise LayerswapError(f"unsupported source token: {src}")
        dst = SUPPORTED_PAIRS[src]
        data = self._get("/limits", params={
            "source_network": SOURCE_NETWORK, "source_token": src,
            "destination_network": DEST_NETWORK, "destination_token": dst,
            "use_deposit_address": "true", "refuel": "false",
        }, proxies=proxies)
        d = data.get("data") if isinstance(data, dict) else None
        if not isinstance(d, dict):
            raise LayerswapError(f"unexpected limits response: {data}")

        def _dec(v: Any) -> Decimal:
            try:
                return Decimal(str(v))
            except Exception:
                return Decimal("0")
        return {
            "min_amount": _dec(d.get("min_amount")),
            "max_amount": _dec(d.get("max_amount")),
            "min_usd": _dec(d.get("min_amount_in_usd")),
            "max_usd": _dec(d.get("max_amount_in_usd")),
        }

    def quote(self, source_token: str, amount: Decimal,
              proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        src = source_token.upper()
        dst = SUPPORTED_PAIRS[src]
        return self._get("/quote", params={
            "source_network": SOURCE_NETWORK, "source_token": src,
            "destination_network": DEST_NETWORK, "destination_token": dst,
            "amount": str(amount), "use_deposit_address": "true",
            "refuel": "false",
        }, proxies=proxies)

    def create_swap(self, *, source_token: str, amount: Decimal,
                    destination_address: str,
                    proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        src = source_token.upper()
        if src not in SUPPORTED_PAIRS:
            raise LayerswapError(f"unsupported source token: {src}")
        dst = SUPPORTED_PAIRS[src]
        body = {
            "source_network": SOURCE_NETWORK, "source_token": src,
            "destination_network": DEST_NETWORK, "destination_token": dst,
            "destination_address": destination_address,
            "source_address": destination_address,
            "refuel": False, "use_deposit_address": True,
            "amount": str(amount),
        }
        data = self._post("/swaps", body, proxies=proxies)
        swap = data.get("data") if isinstance(data, dict) else None
        if not swap:
            raise LayerswapError(f"unexpected create_swap response: {data}")
        return _normalize(swap)

    def get_swap(self, swap_id: str,
                 proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        data = self._get(f"/swaps/{swap_id}", proxies=proxies)
        swap = data.get("data") if isinstance(data, dict) else None
        if not swap:
            raise LayerswapError(f"unexpected get_swap response: {data}")
        return _normalize(swap)


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    swap_obj = raw.get("swap") if isinstance(raw, dict) else None
    if not isinstance(swap_obj, dict):
        swap_obj = {}

    deposit_addr = None
    deposit_amount = None
    for act in raw.get("deposit_actions") or []:
        addr = act.get("to_address") or act.get("deposit_address")
        if addr and not deposit_addr:
            deposit_addr = addr
            deposit_amount = act.get("amount")

    src_tx = dst_tx = None
    for t in swap_obj.get("transactions") or []:
        ttype = (t.get("type") or "").lower()
        h = t.get("transaction_hash") or t.get("transaction_id")
        if ttype in ("input", "deposit", "source") and not src_tx:
            src_tx = h
        if ttype in ("output", "withdraw", "destination") and not dst_tx:
            dst_tx = h

    return {
        "swap_id": swap_obj.get("id"),
        "status": swap_obj.get("status"),
        "deposit_address": deposit_addr,
        "deposit_amount": deposit_amount,
        "raw": raw,
        "source_tx": src_tx,
        "destination_tx": dst_tx,
        "requested_amount": swap_obj.get("requested_amount"),
        "destination_amount": (swap_obj.get("destination_amount")
                                or swap_obj.get("output_amount")),
        "fail_reason": swap_obj.get("fail_reason"),
    }


def _parse(r: requests.Response) -> Dict[str, Any]:
    try:
        data = r.json()
    except ValueError:
        raise LayerswapError(f"non-JSON {r.status_code}: {r.text[:300]}")
    if not r.ok:
        msg = (data.get("error") or data.get("message") or data) \
            if isinstance(data, dict) else data
        raise LayerswapError(f"HTTP {r.status_code}: {msg}")
    return data


__all__ = ["LayerswapClient", "LayerswapError", "SUPPORTED_PAIRS",
           "SOURCE_NETWORK", "DEST_NETWORK"]
