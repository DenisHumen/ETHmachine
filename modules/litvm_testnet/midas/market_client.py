"""Web3-клиент для USDC + Midas Market контрактов на LiteForge.

Контракт каждого маркета (IMidasMarket) предоставляет:
  buy(uint8[] outcomes, uint256[] amounts, uint256 maxCost) payable
  getOutcomePurchaseCost(uint8[], uint256[]) view returns (uint256)
  getOutcomeCount() view returns (uint256)
  getCollateralToken() view returns (address)
  getStatus() view returns (uint8)
  getPrices() view returns (uint256[])

Для USDC-маркета value=0; стоимость списывается с allowance USDC → market.
"""
from __future__ import annotations

import time
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from config.modules.cfg_litvm_testnet import LITVM_RPCS
from config.modules.cfg_litvm_testnet import MIDAS_USDC_ADDRESS, MIDAS_USDC_DECIMALS
from modules.proxy_manager import get_proxy_dict


class MarketError(Exception):
    pass


# ---------------------------------------------------------------------------
# ABIs (только нужное; полный ABI огромен)
# ---------------------------------------------------------------------------

ERC20_ABI = [
    {"type": "function", "stateMutability": "view", "name": "balanceOf",
     "inputs": [{"name": "owner", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "stateMutability": "view", "name": "allowance",
     "inputs": [{"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "stateMutability": "view", "name": "decimals",
     "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
    {"type": "function", "stateMutability": "nonpayable", "name": "approve",
     "inputs": [{"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
]

MARKET_ABI = [
    {"type": "function", "stateMutability": "payable", "name": "buy",
     "inputs": [
         {"name": "outcomes", "type": "uint8[]"},
         {"name": "amounts", "type": "uint256[]"},
         {"name": "maxCost", "type": "uint256"},
     ],
     "outputs": []},
    {"type": "function", "stateMutability": "view",
     "name": "getOutcomePurchaseCost",
     "inputs": [
         {"name": "outcomes", "type": "uint8[]"},
         {"name": "amounts", "type": "uint256[]"},
     ],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "stateMutability": "view", "name": "getOutcomeCount",
     "inputs": [], "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "stateMutability": "view", "name": "getCollateralToken",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "stateMutability": "view", "name": "getStatus",
     "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
    {"type": "function", "stateMutability": "view", "name": "getPrices",
     "inputs": [],
     "outputs": [{"name": "prices", "type": "uint256[]"}]},
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def account_from_private_key(pk: str):
    pk = (pk or "").strip()
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk
    return Account.from_key(pk)


def sign_login_message(pk: str, message: str) -> str:
    """personal_sign — для /auth/wallet/register."""
    acct = account_from_private_key(pk)
    signed = acct.sign_message(encode_defunct(text=message))
    sig = signed.signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    return sig


def _w3_for(proxy: Optional[str], rpc_index: int = 0) -> Web3:
    kw: dict = {"timeout": 30}
    proxy_dict = get_proxy_dict(proxy) if proxy else None
    if proxy_dict:
        kw["proxies"] = proxy_dict
    rpc = LITVM_RPCS[rpc_index % len(LITVM_RPCS)]
    return Web3(Web3.HTTPProvider(rpc, request_kwargs=kw))


def _call_with_rpc(fn, proxy: Optional[str]):
    last: Optional[Exception] = None
    for i in range(max(1, len(LITVM_RPCS))):
        try:
            return fn(_w3_for(proxy, i))
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    raise MarketError(f"all LiteForge RPCs failed: {last}")


# ---------------------------------------------------------------------------
# native balance
# ---------------------------------------------------------------------------

def get_native_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        return int(w3.eth.get_balance(Web3.to_checksum_address(address)))
    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# USDC
# ---------------------------------------------------------------------------

def usdc_balance(address: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(MIDAS_USDC_ADDRESS), abi=ERC20_ABI
        )
        return int(c.functions.balanceOf(
            Web3.to_checksum_address(address)).call())
    return _call_with_rpc(_fn, proxy)


def usdc_allowance(owner: str, spender: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(MIDAS_USDC_ADDRESS), abi=ERC20_ABI
        )
        return int(c.functions.allowance(
            Web3.to_checksum_address(owner),
            Web3.to_checksum_address(spender)).call())
    return _call_with_rpc(_fn, proxy)


def usdc_approve(*, account, spender: str, amount_raw: int,
                 proxy: Optional[str] = None,
                 wait_timeout: int = 180) -> tuple[str, dict]:
    addr = account.address
    def _fn(w3: Web3) -> tuple[str, dict]:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(MIDAS_USDC_ADDRESS), abi=ERC20_ABI
        )
        nonce = w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending")
        gas_price = w3.eth.gas_price
        tx = c.functions.approve(
            Web3.to_checksum_address(spender), int(amount_raw)
        ).build_transaction({
            "from": Web3.to_checksum_address(addr),
            "nonce": int(nonce),
            "gasPrice": int(gas_price),
            "chainId": w3.eth.chain_id,
        })
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.3)
        except Exception:
            tx["gas"] = 120000
        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h = w3.eth.send_raw_transaction(raw).hex()
        if not h.startswith("0x"):
            h = "0x" + h
        deadline = time.time() + wait_timeout
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
            raise MarketError(f"approve tx {h} pending >{wait_timeout}s")
        if int(receipt.get("status", 0)) != 1:
            raise MarketError(f"approve tx {h} reverted")
        return h, dict(receipt)
    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# Market views
# ---------------------------------------------------------------------------

def market_outcome_count(market_address: str,
                         proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(market_address), abi=MARKET_ABI
        )
        return int(c.functions.getOutcomeCount().call())
    return _call_with_rpc(_fn, proxy)


def market_collateral_token(market_address: str,
                            proxy: Optional[str] = None) -> str:
    def _fn(w3: Web3) -> str:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(market_address), abi=MARKET_ABI
        )
        return str(c.functions.getCollateralToken().call())
    return _call_with_rpc(_fn, proxy)


def market_status(market_address: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(market_address), abi=MARKET_ABI
        )
        return int(c.functions.getStatus().call())
    return _call_with_rpc(_fn, proxy)


def market_purchase_cost(market_address: str, outcomes: list[int],
                         amounts: list[int],
                         proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(market_address), abi=MARKET_ABI
        )
        return int(c.functions.getOutcomePurchaseCost(
            [int(o) for o in outcomes], [int(a) for a in amounts]).call())
    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# Bet sizing
# ---------------------------------------------------------------------------

def quote_shares_for_target_usdc(market_address: str, outcome: int,
                                 target_usdc_raw: int,
                                 proxy: Optional[str] = None) -> tuple[int, int]:
    """Подобрать `shares` так, чтобы getOutcomePurchaseCost(shares) ≈ target.

    Возвращает (shares, cost_raw). Гарантирует cost <= target * 1.01.
    Алгоритм: линейная экстраполяция на 1e18 шарах + 1–2 коррекции.
    """
    if target_usdc_raw <= 0:
        raise MarketError("target_usdc_raw must be positive")
    # Initial guess — 1 целая «share» в 1e18 нотации.
    shares = 10 ** 18
    cost = market_purchase_cost(market_address, [outcome], [shares], proxy)
    if cost <= 0:
        # цена 0 — что-то странное, пробуем удвоить shares до получения цены
        for _ in range(20):
            shares *= 2
            cost = market_purchase_cost(market_address, [outcome], [shares], proxy)
            if cost > 0:
                break
        if cost <= 0:
            raise MarketError("market price is zero for this outcome")
    # линейная экстраполяция
    new_shares = max(1, shares * target_usdc_raw // cost)
    cost = market_purchase_cost(market_address, [outcome], [new_shares], proxy)
    shares = new_shares
    # Если перебор > 1%, ужмём.
    if cost > target_usdc_raw:
        # уменьшаем по линейному предсказанию, цена выпукла → достаточно
        # одной коррекции с небольшим запасом 2%
        shares = max(1, shares * target_usdc_raw * 98 // (cost * 100))
        cost = market_purchase_cost(market_address, [outcome], [shares], proxy)
        # если всё ещё больше — итеративно режем
        while cost > target_usdc_raw and shares > 1:
            shares = max(1, shares * 95 // 100)
            cost = market_purchase_cost(market_address, [outcome], [shares], proxy)
    if cost <= 0:
        raise MarketError("could not size shares: cost stays 0")
    return int(shares), int(cost)


# ---------------------------------------------------------------------------
# Buy
# ---------------------------------------------------------------------------

def market_buy(*, account, market_address: str, outcomes: list[int],
               amounts: list[int], max_cost_raw: int,
               value_wei: int = 0,
               proxy: Optional[str] = None,
               wait_timeout: int = 240) -> tuple[str, dict]:
    addr = account.address
    def _fn(w3: Web3) -> tuple[str, dict]:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(market_address), abi=MARKET_ABI
        )
        nonce = w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending")
        gas_price = w3.eth.gas_price
        tx = c.functions.buy(
            [int(o) for o in outcomes], [int(a) for a in amounts],
            int(max_cost_raw),
        ).build_transaction({
            "from": Web3.to_checksum_address(addr),
            "value": int(value_wei),
            "nonce": int(nonce),
            "gasPrice": int(gas_price),
            "chainId": w3.eth.chain_id,
        })
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.3)
        except Exception:
            tx["gas"] = 600000
        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h = w3.eth.send_raw_transaction(raw).hex()
        if not h.startswith("0x"):
            h = "0x" + h
        deadline = time.time() + wait_timeout
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
            raise MarketError(f"buy tx {h} pending >{wait_timeout}s")
        if int(receipt.get("status", 0)) != 1:
            raise MarketError(f"buy tx {h} reverted")
        return h, dict(receipt)
    return _call_with_rpc(_fn, proxy)


# Convenience: USDC amount human → raw
def usdc_to_raw(amount_human: float) -> int:
    return int(round(float(amount_human) * (10 ** int(MIDAS_USDC_DECIMALS))))


def raw_to_usdc(amount_raw: int) -> float:
    return float(amount_raw) / (10 ** int(MIDAS_USDC_DECIMALS))
