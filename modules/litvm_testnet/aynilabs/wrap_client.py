"""Web3-клиент для контракта WzkLTC (`deposit()` payable) на LiteForge.

Контракт: 0x60a84ebc3483fefb251b76aea5bb458026ef4bea (chain_id=4441).
Минимальный ABI — `deposit() payable` + ERC-20 `balanceOf` + `decimals` + `symbol`.
"""
from __future__ import annotations

import time
from typing import Optional

from eth_account import Account
from web3 import Web3

from config.modules.cfg_litvm_testnet import (
    AYNI_TX_TIMEOUT_SEC,
    AYNI_WZKLTC_DEPOSIT_TARGET,
    AYNI_WZKLTC_TOKEN_ADDRESS,
    LITVM_RPCS,
)
from modules.proxy_manager import get_proxy_dict


class AyniError(Exception):
    pass


WZKLTC_ABI = [
    {
        "inputs": [],
        "name": "deposit",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]


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
    raise AyniError(f"all LiteForge RPCs failed: {last_err}")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def account_from_private_key(pk: str) -> "Account":
    pk = (pk or "").strip()
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk
    return Account.from_key(pk)


def get_native_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        return int(w3.eth.get_balance(Web3.to_checksum_address(address)))
    return _call_with_rpc(_fn, proxy)


def get_wzkltc_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    """Читаем balanceOf с РЕАЛЬНОГО ERC-20 (AYNI_WZKLTC_TOKEN_ADDRESS).

    Сайт может его не кредитовать (mint off-chain) — это нормально, используется
    как информационный сигнал, не failure-критерий.
    """
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(AYNI_WZKLTC_TOKEN_ADDRESS),
            abi=WZKLTC_ABI,
        )
        return int(c.functions.balanceOf(
            Web3.to_checksum_address(address)
        ).call())
    return _call_with_rpc(_fn, proxy)


def send_deposit(
    *,
    account,
    value_wei: int,
    proxy: Optional[str] = None,
) -> tuple[str, dict]:
    """Подписывает + отправляет `WzkLTC.deposit()` payable c заданным `value`.

    Возвращает (tx_hash_hex, receipt_dict). Кидает AyniError при reverte/timeout.
    """
    addr = account.address

    def _fn(w3: Web3) -> tuple[str, dict]:
        # Сайт зашит на DEPOSIT_TARGET (EOA с опечаткой). Повторяем его поведение:
        # формируем raw-tx с selector deposit() в data + value. На EOA EVM
        # проигнорирует data и просто примет нативные средства (тратится дешевле
        # минимально, как у обычного transfer).
        deposit_selector = "0xd0e30db0"
        nonce = w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"
        )
        gas_price = w3.eth.gas_price
        tx = {
            "from": Web3.to_checksum_address(addr),
            "to": Web3.to_checksum_address(AYNI_WZKLTC_DEPOSIT_TARGET),
            "value": int(value_wei),
            "data": deposit_selector,
            "nonce": int(nonce),
            "gasPrice": int(gas_price),
            "chainId": int(w3.eth.chain_id),
        }
        # estimate с запасом
        try:
            est = int(w3.eth.estimate_gas(tx))
            tx["gas"] = int(est * 1.3)
        except Exception:  # noqa: BLE001
            tx["gas"] = 60_000

        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h_bytes = w3.eth.send_raw_transaction(raw)
        h = h_bytes.hex() if hasattr(h_bytes, "hex") else str(h_bytes)
        if not h.startswith("0x"):
            h = "0x" + h

        deadline = time.time() + int(AYNI_TX_TIMEOUT_SEC)
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
            raise AyniError(f"tx {h} pending > {AYNI_TX_TIMEOUT_SEC}s")
        if int(receipt.get("status", 0)) != 1:
            raise AyniError(f"tx {h} reverted")
        return h, dict(receipt)

    return _call_with_rpc(_fn, proxy)
