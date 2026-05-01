"""Layerswap v2 client для пары zkSync Lite → zkSync Era.

Используется только режим `use_deposit_address=true`: Layerswap выдаёт нам
адрес в Lite, на который кошелёк сам пушит средства L2-transfer'ом.

Поддерживаемые пары (проверено `scripts/probe_layerswap_routes.py`):
  ZKSYNC_MAINNET/ETH  → ZKSYNCERA_MAINNET/ETH
  ZKSYNC_MAINNET/USDT → ZKSYNCERA_MAINNET/USDT
  ZKSYNC_MAINNET/USDC → ZKSYNCERA_MAINNET/USDC.e   (cross-symbol;
    USDC.e — это «канонический USDC на Era»; маршрут USDC→USDT с
    `use_deposit_address` Layerswap не выдаёт)

DAI как source-токен Layerswap не поддерживает ни в каком режиме.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, Optional

import requests

API_BASE = "https://api.layerswap.io/api/v2"
SOURCE_NETWORK = "ZKSYNC_MAINNET"
DEST_NETWORK = "ZKSYNCERA_MAINNET"

# source_symbol → destination_symbol
SUPPORTED_PAIRS: Dict[str, str] = {
    "ETH": "ETH",
    "USDT": "USDT",
    "USDC": "USDC.e",
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

    # ───────── helpers ─────────

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None,
             proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        url = API_BASE + path
        r = self.session.get(url, params=params, timeout=self.timeout, proxies=proxies)
        return _parse(r)

    def _post(self, path: str, body: Dict[str, Any],
              proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        url = API_BASE + path
        r = self.session.post(url, json=body, timeout=self.timeout, proxies=proxies)
        return _parse(r)

    # ───────── public API ─────────

    def is_pair_supported(self, source_token: str) -> bool:
        return source_token.upper() in SUPPORTED_PAIRS

    def quote(self, source_token: str, amount: Decimal,
              proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        src = source_token.upper()
        dst = SUPPORTED_PAIRS[src]
        return self._get("/quote", params={
            "source_network": SOURCE_NETWORK,
            "source_token": src,
            "destination_network": DEST_NETWORK,
            "destination_token": dst,
            "amount": str(amount),
            "use_deposit_address": "true",
            "refuel": "false",
        }, proxies=proxies)

    def limits(self, source_token: str,
               proxies: Optional[Dict[str, str]] = None) -> Dict[str, Decimal]:
        """Возвращает min/max для пары source→destination в режиме deposit_address.

        Ответ нормализуется в Decimal:
          {min_amount, max_amount, min_usd, max_usd}
        """
        src = source_token.upper()
        if src not in SUPPORTED_PAIRS:
            raise LayerswapError(f"unsupported source token: {src}")
        dst = SUPPORTED_PAIRS[src]
        data = self._get("/limits", params={
            "source_network": SOURCE_NETWORK,
            "source_token": src,
            "destination_network": DEST_NETWORK,
            "destination_token": dst,
            "use_deposit_address": "true",
            "refuel": "false",
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

    def create_swap(self, *, source_token: str, amount: Decimal,
                    destination_address: str,
                    proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Создаёт swap. Возвращает dict со swap_id и deposit_address."""
        src = source_token.upper()
        if src not in SUPPORTED_PAIRS:
            raise LayerswapError(f"unsupported source token: {src}")
        dst = SUPPORTED_PAIRS[src]
        body = {
            "source_network": SOURCE_NETWORK,
            "source_token": src,
            "destination_network": DEST_NETWORK,
            "destination_token": dst,
            "destination_address": destination_address,
            "refuel": False,
            "use_deposit_address": True,
            "amount": str(amount),
            "source_address": destination_address,
        }
        data = self._post("/swaps", body, proxies=proxies)
        swap = data.get("data") if isinstance(data, dict) else None
        if not swap:
            raise LayerswapError(f"unexpected create_swap response: {data}")
        return _normalize_swap(swap)

    def get_swap(self, swap_id: str,
                 proxies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        data = self._get(f"/swaps/{swap_id}", proxies=proxies)
        swap = data.get("data") if isinstance(data, dict) else None
        if not swap:
            raise LayerswapError(f"unexpected get_swap response: {data}")
        return _normalize_swap(swap)

    def wait_completed(self, swap_id: str, *, timeout: float = 1200.0,
                       interval: float = 15.0,
                       proxies: Optional[Dict[str, str]] = None,
                       on_status: Optional[callable] = None) -> Dict[str, Any]:
        """Ждёт COMPLETED либо терминальный фейл. Возвращает финальный swap."""
        deadline = time.monotonic() + timeout
        last_status = None
        while time.monotonic() < deadline:
            try:
                swap = self.get_swap(swap_id, proxies=proxies)
            except LayerswapError:
                time.sleep(interval)
                continue
            status = (swap.get("status") or "").lower()
            if status != last_status and on_status:
                try:
                    on_status(status, swap)
                except Exception:
                    pass
                last_status = status
            if status in ("completed",):
                return swap
            if status in ("failed", "cancelled", "expired"):
                raise LayerswapError(f"swap terminal status: {status}")
            time.sleep(interval)
        raise LayerswapError(f"timeout waiting for swap {swap_id}")


def _normalize_swap(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Извлекает ключевые поля из ответа.

    Структура (Layerswap v2):
      raw = {
        "deposit_actions": [{"to_address": "0x..", "amount": ..., ...}],
        "swap": {
          "id": "uuid",
          "status": "user_transfer_pending|completed|failed|...",
          "destination_address": "0x..",
          "requested_amount": ...,
          "transactions": [
              {"type": "input"|"output", "transaction_hash": "0x..", "status": ...}
          ]
        },
        "quote": {...},
        ...
      }
    """
    swap_obj = raw.get("swap") if isinstance(raw, dict) else None
    if not isinstance(swap_obj, dict):
        # формат GET /swaps возвращает то же самое: {"data": {"swap": {...}, "deposit_actions": [...]}}
        swap_obj = {}

    deposit_addr = None
    for act in raw.get("deposit_actions") or []:
        addr = act.get("to_address") or act.get("deposit_address")
        if addr:
            deposit_addr = addr
            break

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
        "raw": raw,
        "source_tx": src_tx,
        "destination_tx": dst_tx,
        "requested_amount": swap_obj.get("requested_amount"),
        "destination_amount": swap_obj.get("destination_amount") or swap_obj.get("output_amount"),
        "fail_reason": swap_obj.get("fail_reason"),
    }


def _parse(r: requests.Response) -> Dict[str, Any]:
    try:
        data = r.json()
    except ValueError:
        raise LayerswapError(f"non-JSON {r.status_code}: {r.text[:300]}")
    if not r.ok:
        msg = (data.get("error") or data.get("message") or data) if isinstance(data, dict) else data
        raise LayerswapError(f"HTTP {r.status_code}: {msg}")
    return data


__all__ = ["LayerswapClient", "LayerswapError", "SUPPORTED_PAIRS"]
