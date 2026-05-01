"""Проверка прихода средств на zkSync Era через JSON-RPC."""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Optional

from web3 import Web3

ERA_RPC = "https://mainnet.era.zksync.io"

# Контракты ERC-20 на Era (mainnet).
# Ключи — символы как они приходят из destination_token Layerswap.
ERA_TOKENS: Dict[str, Dict[str, object]] = {
    "USDT": {"address": "0x493257fD37EDB34451f62EDf8D2a0C418852bA4C", "decimals": 6},
    # Layerswap отправляет USDC→USDC.e (bridged USDC); native USDC отдельно
    "USDC.e": {"address": "0x3355df6D4c9C3035724Fd0e3914dE96A5a83aaf4", "decimals": 6},
    "USDC":   {"address": "0x1d17CBcF0D6D143135aE902365D2E5e2A16538D4", "decimals": 6},
    "DAI":    {"address": "0x4B9eb6c0b6ea15176BBF62841C6B2A8a398cb656", "decimals": 18},
    "ETH":    {"address": None, "decimals": 18},
}

ERC20_BALANCEOF_ABI = [{
    "constant": True,
    "inputs": [{"name": "_owner", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "balance", "type": "uint256"}],
    "type": "function",
}]


class EraVerifier:
    def __init__(self, rpc_url: str = ERA_RPC, timeout: int = 20):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))

    def get_balance_raw(self, address: str, token: str) -> int:
        # case-insensitive lookup, чтобы не путаться с USDC.e/USDC.E
        info = ERA_TOKENS.get(token) or next(
            (v for k, v in ERA_TOKENS.items() if k.lower() == token.lower()),
            None,
        )
        if not info:
            raise ValueError(f"unknown token on Era: {token}")
        addr = Web3.to_checksum_address(address)
        if info["address"] is None:
            return int(self.w3.eth.get_balance(addr))
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(info["address"]),
            abi=ERC20_BALANCEOF_ABI,
        )
        return int(contract.functions.balanceOf(addr).call())

    def get_decimals(self, token: str) -> int:
        info = ERA_TOKENS.get(token) or next(
            (v for k, v in ERA_TOKENS.items() if k.lower() == token.lower()),
            None,
        )
        if not info:
            raise ValueError(f"unknown token on Era: {token}")
        return int(info["decimals"])

    def get_balance_human(self, address: str, token: str) -> Decimal:
        raw = self.get_balance_raw(address, token)
        return Decimal(raw) / (Decimal(10) ** self.get_decimals(token))


__all__ = ["EraVerifier", "ERA_TOKENS", "ERA_RPC"]
