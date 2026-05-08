"""Rhino.fi client (quote/commit flow) для swap-all zkSync Era → Base USDC.

Использует публичный widget-key, извлечённый из бандла app.rhino.fi.
Поток:
  1. POST /authentication/auth/apiKey { apiKey } → { jwt }
  2. POST /bridge/quote/user { mode: 'pay', chainIn, chainOut, token, tokenOut,
                               amount, depositor, recipient } → { quoteId, ... }
  3. POST /bridge/quote/commit/{quoteId} → { quoteId } (фиксирует у Rhino цену)
  4. on-chain depositWithId(token, amount, BigInt('0x'+quoteId))
     или depositNativeWithId(BigInt('0x'+quoteId)) для native
  5. GET /bridge/history/bridge/{quoteId} polling до state in {COMPLETED|FAILED|...}
"""
from __future__ import annotations

import threading
import time
from decimal import Decimal
from typing import Any, Dict, Optional

import requests

DEFAULT_BASE_URL = "https://api.rhino.fi"

# {source_token_on_zksync: dest_token_on_base}
SUPPORTED_PAIRS: Dict[str, str] = {
    "USDC": "USDC",
    "USDT": "USDC",
}

CHAIN_IN = "ZKSYNC"
CHAIN_OUT = "BASE"

DEFAULT_TIMEOUT = 30

# Терминальные состояния истории Rhino.fi (state в /bridge/history/bridge/{id}).
TERMINAL_OK = {"COMPLETED", "SUCCESS", "DONE", "EXECUTED"}
TERMINAL_FAIL = {"FAILED", "CANCELLED", "EXPIRED", "REFUNDED", "ERROR"}


class RhinoFiError(RuntimeError):
    pass


class RhinoFiClient:
    def __init__(self, *, api_key: Optional[str] = None,
                 base_url: str = DEFAULT_BASE_URL,
                 timeout: int = DEFAULT_TIMEOUT,
                 session: Optional[requests.Session] = None) -> None:
        self.api_key = (api_key or "").strip() or None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://app.rhino.fi",
            "Referer": "https://app.rhino.fi/",
        })
        self._jwt: Optional[str] = None
        self._jwt_ts: float = 0.0
        self._jwt_lock = threading.Lock()

    # ---- auth ----
    def _ensure_jwt(self, proxies: Optional[Dict[str, str]] = None) -> None:
        # Re-auth раз в ~10 минут на всякий случай (TTL точно не известен).
        if self._jwt and (time.time() - self._jwt_ts) < 540:
            return
        if not self.api_key:
            raise RhinoFiError("RHINOFI_API_KEY is empty — cannot get JWT")
        with self._jwt_lock:
            if self._jwt and (time.time() - self._jwt_ts) < 540:
                return
            r = self.session.post(
                f"{self.base_url}/authentication/auth/apiKey",
                json={"apiKey": self.api_key},
                headers={"Content-Type": "application/json"},
                timeout=self.timeout, proxies=proxies,
            )
            data = _parse(r)
            jwt = data.get("jwt") if isinstance(data, dict) else None
            if not jwt:
                raise RhinoFiError(f"auth: no jwt in response: {data}")
            self._jwt = jwt
            self._jwt_ts = time.time()
            self.session.headers["Authorization"] = jwt

    # ---- helpers ----
    def _get(self, path: str, *, params: Optional[Dict[str, Any]] = None,
             proxies: Optional[Dict[str, str]] = None,
             auth: bool = True) -> Dict[str, Any]:
        if auth:
            self._ensure_jwt(proxies)
        r = self.session.get(self.base_url + path, params=params,
                             timeout=self.timeout, proxies=proxies)
        return _parse(r)

    def _post(self, path: str, body: Optional[Dict[str, Any]] = None,
              *, proxies: Optional[Dict[str, str]] = None,
              auth: bool = True) -> Dict[str, Any]:
        if auth:
            self._ensure_jwt(proxies)
        r = self.session.post(self.base_url + path, json=body or {},
                              timeout=self.timeout, proxies=proxies)
        return _parse(r)

    # ---- public API ----
    def is_supported(self, token: str) -> bool:
        return token.upper() in SUPPORTED_PAIRS

    def get_configs(self, proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        # Configs публичный (без auth).
        r = self.session.get(f"{self.base_url}/bridge/configs",
                             timeout=self.timeout, proxies=proxies)
        return _parse(r)

    def quote(self, *, source_token: str, amount: Decimal,
              depositor: str, recipient: str,
              proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        src = source_token.upper()
        if src not in SUPPORTED_PAIRS:
            raise RhinoFiError(f"unsupported source token: {src}")
        dst = SUPPORTED_PAIRS[src]
        if src == dst:
            body = {
                "amount": str(amount),
                "chainIn": CHAIN_IN,
                "chainOut": CHAIN_OUT,
                "token": src,
                "depositor": depositor,
                "recipient": recipient,
                "mode": "pay",
            }
            return self._post("/bridge/quote/user", body, proxies=proxies)
        # Cross-token: USDT in zkSync → USDC on Base
        body = {
            "amount": str(amount),
            "chainIn": CHAIN_IN,
            "chainOut": CHAIN_OUT,
            "tokenIn": src,
            "tokenOut": dst,
            "depositor": depositor,
            "recipient": recipient,
            "mode": "pay",
        }
        return self._post("/bridge/quote/bridge-swap/user", body,
                           proxies=proxies)

    def commit(self, quote_id: str,
               proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self._post(f"/bridge/quote/commit/{quote_id}",
                          {}, proxies=proxies)

    def get_status(self, quote_id: str,
                   proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self._get(f"/bridge/history/bridge/{quote_id}", proxies=proxies)

    # ---- compatibility shim (executor calls .create_swap) ----
    def create_swap(self, *, source_token: str, amount: Decimal,
                    destination_address: str, depositor: Optional[str] = None,
                    proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Quote + commit; returns normalized dict.

        Rhino.fi не выдаёт deposit_address — депозит идёт в фиксированный
        bridge-контракт; сам контракт известен из /bridge/configs (поле
        contractAddress для chain ZKSYNC).
        """
        depositor = depositor or destination_address
        q = self.quote(source_token=source_token, amount=amount,
                       depositor=depositor, recipient=destination_address,
                       proxies=proxies)
        qid = q.get("quoteId")
        if not qid:
            raise RhinoFiError(f"quote response missing quoteId: {q}")
        c = self.commit(qid, proxies=proxies)
        return {
            "swap_id": qid,
            "quote": q,
            "commit": c,
            "status": "PENDING",
            "pay_amount": q.get("payAmount"),
            "receive_amount": q.get("receiveAmount"),
            "raw": {"quote": q, "commit": c},
        }

    def get_swap(self, swap_id: str,
                 proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        raw = self.get_status(swap_id, proxies=proxies)
        state = (raw.get("state") or "").upper() if isinstance(raw, dict) else ""
        return {
            "swap_id": swap_id,
            "status": state,
            "destination_amount": raw.get("amountOut") if isinstance(raw, dict) else None,
            "destination_tx": (raw.get("withdrawTxHash")
                                or raw.get("destinationTxHash")
                                or raw.get("dstTxHash")) if isinstance(raw, dict) else None,
            "source_tx": (raw.get("depositTxHash")
                           or raw.get("sourceTxHash")
                           or raw.get("srcTxHash")) if isinstance(raw, dict) else None,
            "fail_reason": raw.get("failReason") if isinstance(raw, dict) else None,
            "raw": raw,
        }


def _parse(r: requests.Response) -> Dict[str, Any]:
    try:
        data = r.json()
    except ValueError:
        raise RhinoFiError(f"non-JSON {r.status_code}: {r.text[:300]}")
    if not r.ok:
        msg = (data.get("error") or data.get("message") or data) \
            if isinstance(data, dict) else data
        raise RhinoFiError(f"HTTP {r.status_code}: {msg}")
    return data


__all__ = [
    "RhinoFiClient", "RhinoFiError", "SUPPORTED_PAIRS",
    "CHAIN_IN", "CHAIN_OUT", "TERMINAL_OK", "TERMINAL_FAIL",
]
