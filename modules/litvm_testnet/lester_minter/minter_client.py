"""Web3 клиент для Lester Token Factory на LiteForge.

Функция-фабрика:
    createToken(string name, string symbol, uint256 totalSupply,
                uint8 decimals, bool mintable, bool burnable, bool pausable)
                payable  // value = 0.05 zkLTC

Адрес токена получаем из лог-события: контракт-токен сам эмитит
`Transfer(0x0 -> owner, totalSupply)` сразу после деплоя — этот первый
Transfer-лог НЕ от фабрики содержит адрес созданного контракта в `address`.
"""
from __future__ import annotations

import time
from typing import Optional

from eth_account import Account
from eth_utils import keccak
from web3 import Web3

from config.modules.cfg_litvm_testnet import (
    LITVM_MINTER_DEPLOY_FEE_WEI,
    LITVM_MINTER_FACTORY,
    LITVM_RPCS,
)
from modules.proxy_manager import get_proxy_dict


class MinterError(Exception):
    pass


class InsufficientBalance(MinterError):
    pass


# createToken(string,string,uint256,uint8,bool,bool,bool)
FACTORY_ABI = [
    {
        "type": "function",
        "stateMutability": "payable",
        "name": "createToken",
        "inputs": [
            {"name": "name", "type": "string"},
            {"name": "symbol", "type": "string"},
            {"name": "totalSupply", "type": "uint256"},
            {"name": "decimals", "type": "uint8"},
            {"name": "mintable", "type": "bool"},
            {"name": "burnable", "type": "bool"},
            {"name": "pausable", "type": "bool"},
        ],
        "outputs": [],
    },
]

# ERC-20 Transfer(address indexed from, address indexed to, uint256 value)
_TRANSFER_TOPIC = "0x" + keccak(b"Transfer(address,address,uint256)").hex()


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
    raise MinterError(f"all LiteForge RPCs failed: {last_err}")


def get_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        return int(w3.eth.get_balance(Web3.to_checksum_address(address)))
    return _call_with_rpc(_fn, proxy)


def estimate_create_token_gas(
    *,
    account_address: str,
    name: str,
    symbol: str,
    total_supply_wei: int,
    decimals: int,
    mintable: bool,
    burnable: bool,
    pausable: bool,
    proxy: Optional[str] = None,
) -> int:
    """Оценивает gas для createToken. Возвращает estimate × 1.2 как safety."""
    def _fn(w3: Web3) -> int:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(LITVM_MINTER_FACTORY),
            abi=FACTORY_ABI,
        )
        est = contract.functions.createToken(
            name, symbol, int(total_supply_wei), int(decimals),
            bool(mintable), bool(burnable), bool(pausable),
        ).estimate_gas({
            "from": Web3.to_checksum_address(account_address),
            "value": int(LITVM_MINTER_DEPLOY_FEE_WEI),
        })
        return int(est * 1.2)
    return _call_with_rpc(_fn, proxy)


def send_create_token(
    *,
    account,
    name: str,
    symbol: str,
    total_supply_wei: int,
    decimals: int,
    mintable: bool,
    burnable: bool,
    pausable: bool,
    proxy: Optional[str] = None,
    gas_limit: Optional[int] = None,
) -> tuple[str, dict]:
    """Подписывает и отправляет createToken-tx. Ждёт receipt.
    Возвращает (tx_hash_hex, receipt_dict)."""
    addr = account.address

    def _fn(w3: Web3) -> tuple[str, dict]:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(LITVM_MINTER_FACTORY),
            abi=FACTORY_ABI,
        )
        nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(addr), "pending")
        # LiteForge legacy gas pricing (как у bridge L2)
        gas_price = w3.eth.gas_price
        tx = contract.functions.createToken(
            name, symbol, int(total_supply_wei), int(decimals),
            bool(mintable), bool(burnable), bool(pausable),
        ).build_transaction({
            "from": Web3.to_checksum_address(addr),
            "value": int(LITVM_MINTER_DEPLOY_FEE_WEI),
            "nonce": int(nonce),
            "gasPrice": int(gas_price),
            "chainId": w3.eth.chain_id,
        })
        if gas_limit is not None:
            tx["gas"] = int(gas_limit)
        elif "gas" not in tx:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)

        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h = w3.eth.send_raw_transaction(raw).hex()
        if not h.startswith("0x"):
            h = "0x" + h
        # ждём receipt
        deadline = time.time() + 180
        receipt = None
        while time.time() < deadline:
            try:
                receipt = w3.eth.get_transaction_receipt(h)
                if receipt is not None:
                    break
            except Exception:
                pass
            time.sleep(3)
        if receipt is None:
            raise MinterError(f"tx {h} pending >180s")
        if int(receipt.get("status", 0)) != 1:
            raise MinterError(f"tx {h} reverted")
        return h, dict(receipt)

    return _call_with_rpc(_fn, proxy)


def extract_token_address_from_receipt(receipt: dict) -> Optional[str]:
    """Из receipt'а вытаскивает адрес созданного токена.

    Логика: токен-контракт сам эмитит Transfer(0x0 -> owner, totalSupply) при
    минте. Адрес этого лога — адрес самого токена (не фабрики).
    """
    factory = (LITVM_MINTER_FACTORY or "").lower()
    zero_topic = "0x" + "0" * 64
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
        # Transfer from 0x0 — это mint, что соответствует начальной эмиссии.
        if t1_hex.lower().endswith(zero_topic[2:]):
            return Web3.to_checksum_address(addr_str)
    return None


def account_from_private_key(pk: str) -> "Account":
    pk = (pk or "").strip()
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk
    return Account.from_key(pk)
