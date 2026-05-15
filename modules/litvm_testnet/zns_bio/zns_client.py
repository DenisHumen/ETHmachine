"""ZNS Connect registry client (LiteForge).

Address: 0x1c6C28403400c44D8D351dEaBcF7B1365F96EbF1 (Registry, ERC-721).
Function used: registerDomains(address[], string[], uint256[], address, uint256) payable.

Pricing read on-chain via priceToRegister(uint16) + priceToRenew(uint16).
"""
from __future__ import annotations

import time
from typing import Optional

from eth_account import Account
from web3 import Web3

from config.modules.cfg_litvm_testnet import (
    LITVM_RPCS,
    ZNS_REGISTRY,
    ZNS_TX_TIMEOUT_SEC,
)
from modules.proxy_manager import get_proxy_dict


class ZnsError(Exception):
    pass


REGISTRY_ABI = [
    {"type": "function", "name": "registerDomains", "stateMutability": "payable",
     "inputs": [
         {"name": "owners", "type": "address[]"},
         {"name": "domainNames", "type": "string[]"},
         {"name": "expiries", "type": "uint256[]"},
         {"name": "referral", "type": "address"},
         {"name": "credits", "type": "uint256"}],
     "outputs": []},
    {"type": "function", "name": "priceToRegister", "stateMutability": "view",
     "inputs": [{"name": "length", "type": "uint16"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "priceToRenew", "stateMutability": "view",
     "inputs": [{"name": "length", "type": "uint16"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "domainLookup", "stateMutability": "view",
     "inputs": [{"name": "", "type": "string"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "tld", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "string"}]},
    {"type": "function", "name": "tokenID", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "ownerOf", "stateMutability": "view",
     "inputs": [{"name": "tokenId", "type": "uint256"}],
     "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "getOraclePrice", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "event", "name": "MintedDomain",
     "inputs": [
         {"name": "domainName", "type": "string", "indexed": False},
         {"name": "tokenId", "type": "uint256", "indexed": False},
         {"name": "owner", "type": "address", "indexed": False},
         {"name": "expirationDate", "type": "uint256", "indexed": False}],
     "anonymous": False},
]


# ---------------------------------------------------------------------------
# RPC helpers
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
    raise ZnsError(f"all LiteForge RPCs failed: {last_err}")


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
# Reads
# ---------------------------------------------------------------------------

def _registry(w3: Web3):
    return w3.eth.contract(
        address=Web3.to_checksum_address(ZNS_REGISTRY), abi=REGISTRY_ABI)


def is_name_available(name: str, proxy: Optional[str] = None) -> bool:
    """domainLookup(name)==0 means free."""
    def _fn(w3: Web3) -> bool:
        c = _registry(w3)
        return int(c.functions.domainLookup(name).call()) == 0
    return _call_with_rpc(_fn, proxy)


def compute_price_wei(name: str, years: int,
                      proxy: Optional[str] = None) -> int:
    L = max(1, min(65535, len(name)))
    years = max(1, int(years))

    def _fn(w3: Web3) -> int:
        c = _registry(w3)
        reg = int(c.functions.priceToRegister(L).call())
        if years <= 1:
            return reg
        ren = int(c.functions.priceToRenew(L).call())
        return reg + ren * (years - 1)
    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# Tx helpers
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
    raise ZnsError(f"tx {tx_hash} pending > {timeout_sec}s")


def _send_signed(w3: Web3, account, tx: dict) -> str:
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h_bytes = w3.eth.send_raw_transaction(raw)
    h = h_bytes.hex() if hasattr(h_bytes, "hex") else str(h_bytes)
    if not h.startswith("0x"):
        h = "0x" + h
    return h


def _parse_minted_token_id(w3: Web3, receipt: dict,
                           expected_name: str) -> Optional[int]:
    """Fetch tokenId via on-chain domainLookup(expected_name) — robust against
    event ABI variations."""
    try:
        c = _registry(w3)
        tid = int(c.functions.domainLookup(expected_name.lower()).call())
        return tid if tid > 0 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def register_domain(
    *, account, name: str, years: int, referral: str = "0x" + "0" * 40,
    credits_wei: int = 0, price_wei: Optional[int] = None,
    proxy: Optional[str] = None,
) -> tuple[str, dict, int, Optional[int]]:
    """Один домен → owners=[account.address], names=[name], expiries=[years].
    Возвращает (tx_hash, receipt, paid_wei, token_id_or_None)."""
    name = name.lower()
    addr = account.address
    if price_wei is None:
        price_wei = compute_price_wei(name, years, proxy=proxy)

    def _fn(w3: Web3) -> tuple[str, dict, int, Optional[int]]:
        c = _registry(w3)
        nonce = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"))
        gas_price = int(w3.eth.gas_price)
        owners = [Web3.to_checksum_address(addr)]
        names = [name]
        years_arr = [int(years)]
        ref = Web3.to_checksum_address(referral or ("0x" + "0" * 40))
        tx = c.functions.registerDomains(
            owners, names, years_arr, ref, int(credits_wei),
        ).build_transaction({
            "from": Web3.to_checksum_address(addr),
            "value": int(price_wei),
            "nonce": nonce,
            "gasPrice": gas_price,
            "chainId": int(w3.eth.chain_id),
        })
        try:
            est = int(w3.eth.estimate_gas(tx))
            tx["gas"] = int(est * 1.3)
        except Exception:
            tx["gas"] = 500_000
        h = _send_signed(w3, account, tx)
        rcpt = _wait_receipt(w3, h, int(ZNS_TX_TIMEOUT_SEC))
        if int(rcpt.get("status", 0)) != 1:
            raise ZnsError(f"registerDomains {h} reverted")
        token_id = _parse_minted_token_id(w3, rcpt, name)
        return h, rcpt, int(price_wei), token_id

    return _call_with_rpc(_fn, proxy)
