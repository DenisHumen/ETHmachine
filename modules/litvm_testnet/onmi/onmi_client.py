"""Onmi.fun web3-клиент: TokenLaunch factory + API uploads.

Factory `createToken(name, symbol, tokenURI, nonce, deadline, createReferrer)`
и `createTokenAndBuy(name, symbol, tokenURI, minTokensOut, nonce, deadline,
createReferrer, tradeReferrer)` payable.

Параметры (из JS-бандла сайта):
  • nonce          — `eth_getTransactionCount(self, "pending")` (используется
                     как уникальный ключ; контракт его проверяет в маппинге).
  • deadline       — `40 * (time.time() + 120)` ≈ далёкое будущее.
  • createReferrer — для createToken: zero-address. Для createTokenAndBuy: self.
  • tradeReferrer  — self.
  • minTokensOut   — 0 (без slippage-защиты, как делает сайт по умолчанию).

API:
  • POST `/api/upload/image?chainId=4441` multipart, поле `imageUrl` = bytes.
    → `{"imageUrl": "https://onmi.s3.ap-southeast-2.amazonaws.com/...png"}`.
  • POST `/api/upload/metadata?chainId=4441` JSON:
    `{name, symbol, description, image, website, twitter, telegram}`.
    → `{"success": true, "url": {"metadataURI": "https://onmi.s3.../json"}}`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests
from eth_account import Account
from eth_utils import keccak
from web3 import Web3

from config.modules.cfg_litvm_testnet import (
    LITVM_RPCS,
    ONMI_API_BASE,
    ONMI_CHAIN_ID,
    ONMI_HTTP_TIMEOUT,
    ONMI_TOKEN_FACTORY,
    ONMI_TX_TIMEOUT_SEC,
)
from modules.proxy_manager import get_proxy_dict, parse_proxy


class OnmiError(Exception):
    pass


ZERO_ADDR = "0x" + "0" * 40

# Factory ABI (минимальный — только функции, которые мы вызываем).
FACTORY_ABI = [
    {
        "type": "function",
        "stateMutability": "nonpayable",
        "name": "createToken",
        "inputs": [
            {"name": "name", "type": "string"},
            {"name": "symbol", "type": "string"},
            {"name": "tokenURI", "type": "string"},
            {"name": "nonce", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "createReferrer", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function",
        "stateMutability": "payable",
        "name": "createTokenAndBuy",
        "inputs": [
            {"name": "name", "type": "string"},
            {"name": "symbol", "type": "string"},
            {"name": "tokenURI", "type": "string"},
            {"name": "minTokensOut", "type": "uint256"},
            {"name": "nonce", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "createReferrer", "type": "address"},
            {"name": "tradeReferrer", "type": "address"},
        ],
        "outputs": [
            {"name": "", "type": "address"},
            {"name": "", "type": "uint256"},
        ],
    },
]

# ERC-20 Transfer(address indexed from, address indexed to, uint256 value)
_TRANSFER_TOPIC = "0x" + keccak(b"Transfer(address,address,uint256)").hex()
_ZERO_TOPIC = "0x" + "0" * 64


# ---------------------------------------------------------------------------
# RPC pool
# ---------------------------------------------------------------------------

def _w3_for(proxy: Optional[str], rpc_index: int = 0) -> Web3:
    proxy_dict = get_proxy_dict(proxy)
    kw: dict = {"timeout": 30}
    if proxy_dict:
        kw["proxies"] = proxy_dict
    rpc = LITVM_RPCS[rpc_index % len(LITVM_RPCS)]
    return Web3(Web3.HTTPProvider(rpc, request_kwargs=kw))


def _call_with_rpc(fn, proxy: Optional[str]):
    last_err: Optional[Exception] = None
    for i in range(len(LITVM_RPCS)):
        try:
            return fn(_w3_for(proxy, i))
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise OnmiError(f"all LiteForge RPCs failed: {last_err}")


# ---------------------------------------------------------------------------
# Account / balance helpers
# ---------------------------------------------------------------------------

def account_from_private_key(pk: str):
    pk = (pk or "").strip()
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk
    return Account.from_key(pk)


def get_native_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        return int(w3.eth.get_balance(Web3.to_checksum_address(address)))
    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# Onmi HTTP API
# ---------------------------------------------------------------------------

def _http_session(proxy: Optional[str]) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Origin": ONMI_API_BASE,
        "Referer": f"{ONMI_API_BASE}/?chain=LITVM",
    })
    parsed = parse_proxy(proxy) if proxy else None
    if parsed:
        s.proxies = {"http": parsed, "https": parsed}
    return s


def upload_image(
    *,
    image_path: Path,
    chain_id: int = ONMI_CHAIN_ID,
    proxy: Optional[str] = None,
) -> str:
    """Multipart upload картинки на onmi (поле `imageUrl` = binary).

    Возвращает CDN-URL вида `https://onmi.s3.ap-southeast-2.amazonaws.com/...`.
    """
    path = Path(image_path)
    if not path.exists():
        raise OnmiError(f"image not found: {path}")
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else (
        "image/png" if path.suffix.lower() == ".png" else (
            "image/gif" if path.suffix.lower() == ".gif" else "application/octet-stream"
        )
    )
    session = _http_session(proxy)
    try:
        with open(path, "rb") as f:
            r = session.post(
                f"{ONMI_API_BASE}/api/upload/image",
                params={"chainId": int(chain_id)},
                files={"imageUrl": (path.name, f, mime)},
                timeout=int(ONMI_HTTP_TIMEOUT),
            )
        if r.status_code != 200:
            raise OnmiError(
                f"image upload HTTP {r.status_code}: {r.text[:300]}"
            )
        body = r.json()
        url = body.get("imageUrl") or body.get("url")
        if not url:
            raise OnmiError(f"no imageUrl in response: {body}")
        return str(url)
    finally:
        session.close()


def upload_metadata(
    *,
    name: str,
    symbol: str,
    description: str,
    image_url: str,
    website: str = "",
    twitter: str = "",
    telegram: str = "",
    chain_id: int = ONMI_CHAIN_ID,
    proxy: Optional[str] = None,
) -> str:
    """JSON upload метаданных. Возвращает `metadataURI` (URL на S3)."""
    session = _http_session(proxy)
    try:
        r = session.post(
            f"{ONMI_API_BASE}/api/upload/metadata",
            params={"chainId": int(chain_id)},
            json={
                "name": name,
                "symbol": symbol,
                "description": description or "",
                "image": image_url,
                "website": website or "",
                "twitter": twitter or "",
                "telegram": telegram or "",
            },
            timeout=int(ONMI_HTTP_TIMEOUT),
        )
        if r.status_code != 200:
            raise OnmiError(
                f"metadata upload HTTP {r.status_code}: {r.text[:300]}"
            )
        body = r.json()
        if not body.get("success"):
            raise OnmiError(f"metadata upload not success: {body}")
        url = (body.get("url") or {}).get("metadataURI")
        if not url:
            raise OnmiError(f"no metadataURI: {body}")
        return str(url)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# On-chain: createToken / createTokenAndBuy
# ---------------------------------------------------------------------------

def _wait_receipt(w3: Web3, tx_hash: str, timeout_sec: int) -> dict:
    deadline = time.time() + int(timeout_sec)
    while time.time() < deadline:
        try:
            r = w3.eth.get_transaction_receipt(tx_hash)
            if r is not None:
                return dict(r)
        except Exception:
            pass
        time.sleep(3)
    raise OnmiError(f"tx {tx_hash} pending > {timeout_sec}s")


def _extract_token_address(receipt: dict) -> Optional[str]:
    """Из receipt'а тащим адрес созданного токена.

    Логика: новый токен-контракт эмитит Transfer(0x0 → owner) при минте supply.
    Берём первый лог с topic[0]=Transfer и topic[1]=zero, чей адрес НЕ совпадает
    с фабрикой/менеджером.
    """
    factory = (ONMI_TOKEN_FACTORY or "").lower()
    for log in (receipt.get("logs") or []):
        addr = log.get("address")
        addr_str = addr if isinstance(addr, str) else None
        if not addr_str:
            continue
        if addr_str.lower() == factory:
            continue
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        t0 = topics[0]
        t0_hex = t0.hex() if hasattr(t0, "hex") else str(t0)
        if not t0_hex.startswith("0x"):
            t0_hex = "0x" + t0_hex
        if t0_hex.lower() != _TRANSFER_TOPIC.lower():
            continue
        t1 = topics[1]
        t1_hex = t1.hex() if hasattr(t1, "hex") else str(t1)
        if not t1_hex.startswith("0x"):
            t1_hex = "0x" + t1_hex
        if t1_hex.lower() != _ZERO_TOPIC.lower():
            continue
        # это первый Transfer от созданного токена
        return Web3.to_checksum_address(addr_str)
    return None


def _tokens_received_from_logs(receipt: dict, token_address: str,
                               recipient: str) -> int:
    """Сумма Transfer'ов из token_address с topic2=recipient."""
    if not token_address:
        return 0
    target = (token_address or "").lower()
    recip_topic = "0x" + "0" * 24 + recipient.lower().replace("0x", "")
    total = 0
    for log in (receipt.get("logs") or []):
        addr = log.get("address")
        addr_str = addr if isinstance(addr, str) else None
        if not addr_str or addr_str.lower() != target:
            continue
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        t0 = topics[0]
        t0_hex = t0.hex() if hasattr(t0, "hex") else str(t0)
        if not t0_hex.startswith("0x"):
            t0_hex = "0x" + t0_hex
        if t0_hex.lower() != _TRANSFER_TOPIC.lower():
            continue
        t2 = topics[2]
        t2_hex = t2.hex() if hasattr(t2, "hex") else str(t2)
        if not t2_hex.startswith("0x"):
            t2_hex = "0x" + t2_hex
        if t2_hex.lower() != recip_topic.lower():
            continue
        data = log.get("data")
        data_hex = data.hex() if hasattr(data, "hex") else str(data)
        if not data_hex.startswith("0x"):
            data_hex = "0x" + data_hex
        try:
            total += int(data_hex, 16)
        except Exception:
            continue
    return total


def _build_deadline() -> int:
    # Сайт: BigInt(40*(Math.floor(Date.now()/1e3)+120)).
    # Это не unix-timestamp в обычном смысле, но контракт принимает его как-есть
    # (это просто uint256, проверяющийся на «не в прошлом» по их кастомной формуле).
    return int(40 * (int(time.time()) + 120))


def send_create_token_and_buy(
    *,
    account,
    name: str,
    symbol: str,
    token_uri: str,
    value_wei: int,
    proxy: Optional[str] = None,
) -> tuple[str, dict, Optional[str], int]:
    """`createTokenAndBuy` payable. Возвращает (tx_hash, receipt, token_address,
    tokens_received_wei)."""
    addr = account.address

    def _fn(w3: Web3) -> tuple[str, dict, Optional[str], int]:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_TOKEN_FACTORY),
            abi=FACTORY_ABI,
        )
        nonce_param = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"
        ))
        deadline = _build_deadline()
        gas_price = int(w3.eth.gas_price)

        tx_nonce = nonce_param  # tx-level nonce совпадает с pending-count
        tx = contract.functions.createTokenAndBuy(
            name, symbol, token_uri, 0, int(nonce_param), int(deadline),
            Web3.to_checksum_address(addr),  # createReferrer = self
            Web3.to_checksum_address(addr),  # tradeReferrer = self
        ).build_transaction({
            "from": Web3.to_checksum_address(addr),
            "value": int(value_wei),
            "nonce": int(tx_nonce),
            "gasPrice": gas_price,
            "chainId": int(w3.eth.chain_id),
        })
        try:
            est = int(w3.eth.estimate_gas(tx))
            tx["gas"] = int(est * 1.3)
        except Exception:
            tx["gas"] = 4_000_000

        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h_bytes = w3.eth.send_raw_transaction(raw)
        h = h_bytes.hex() if hasattr(h_bytes, "hex") else str(h_bytes)
        if not h.startswith("0x"):
            h = "0x" + h
        receipt = _wait_receipt(w3, h, int(ONMI_TX_TIMEOUT_SEC))
        if int(receipt.get("status", 0)) != 1:
            raise OnmiError(f"tx {h} reverted")
        token_addr = _extract_token_address(receipt)
        tokens = _tokens_received_from_logs(receipt, token_addr or "", addr) if token_addr else 0
        return h, receipt, token_addr, int(tokens)

    return _call_with_rpc(_fn, proxy)


def send_create_token(
    *,
    account,
    name: str,
    symbol: str,
    token_uri: str,
    proxy: Optional[str] = None,
) -> tuple[str, dict, Optional[str]]:
    """`createToken` (без buy). Возвращает (tx_hash, receipt, token_address)."""
    addr = account.address

    def _fn(w3: Web3) -> tuple[str, dict, Optional[str]]:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_TOKEN_FACTORY),
            abi=FACTORY_ABI,
        )
        nonce_param = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"
        ))
        deadline = _build_deadline()
        gas_price = int(w3.eth.gas_price)

        tx = contract.functions.createToken(
            name, symbol, token_uri, int(nonce_param), int(deadline),
            Web3.to_checksum_address(ZERO_ADDR),
        ).build_transaction({
            "from": Web3.to_checksum_address(addr),
            "nonce": int(nonce_param),
            "gasPrice": gas_price,
            "chainId": int(w3.eth.chain_id),
        })
        try:
            est = int(w3.eth.estimate_gas(tx))
            tx["gas"] = int(est * 1.3)
        except Exception:
            tx["gas"] = 4_000_000

        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h_bytes = w3.eth.send_raw_transaction(raw)
        h = h_bytes.hex() if hasattr(h_bytes, "hex") else str(h_bytes)
        if not h.startswith("0x"):
            h = "0x" + h
        receipt = _wait_receipt(w3, h, int(ONMI_TX_TIMEOUT_SEC))
        if int(receipt.get("status", 0)) != 1:
            raise OnmiError(f"tx {h} reverted")
        token_addr = _extract_token_address(receipt)
        return h, receipt, token_addr

    return _call_with_rpc(_fn, proxy)
