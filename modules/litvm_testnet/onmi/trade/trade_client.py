"""Router-клиент для onmi bonding curve: buyExactIn / sellExactIn + ERC-20.

Router ABI (extract from app.onmi.fun bundle):
  • buyExactIn(token, minOut, tradeReferrer) payable -> tokensOut
  • sellExactIn(token, tokenAmount, minEth, tradeReferrer) -> ethOut
  • TradeExecuted event (token, trader, tradeType, amountIn, amountOut, ...)
  • TokenGraduated event (token, pair, liquidity, ...) — после этого
    bonding-curve-trades реверт ('AlreadyGraduated').
"""
from __future__ import annotations

import time
from typing import Optional

from eth_account import Account
from eth_utils import keccak
from web3 import Web3

from config.modules.cfg_litvm_testnet import (
    LITVM_RPCS,
    ONMI_TRADE_ROUTER,
    ONMI_TRADE_TX_TIMEOUT_SEC,
)
from modules.proxy_manager import get_proxy_dict


class TradeError(Exception):
    pass


ZERO_ADDR = "0x" + "0" * 40
MAX_UINT256 = (1 << 256) - 1


ROUTER_ABI = [
    {
        "type": "function",
        "stateMutability": "payable",
        "name": "buyExactIn",
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "minOut", "type": "uint256"},
            {"name": "tradeReferrer", "type": "address"},
        ],
        "outputs": [{"name": "tokensOut", "type": "uint256"}],
    },
    {
        "type": "function",
        "stateMutability": "nonpayable",
        "name": "sellExactIn",
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "tokenAmount", "type": "uint256"},
            {"name": "minEth", "type": "uint256"},
            {"name": "tradeReferrer", "type": "address"},
        ],
        "outputs": [{"name": "ethOut", "type": "uint256"}],
    },
]

ERC20_ABI = [
    {
        "type": "function", "stateMutability": "view", "name": "balanceOf",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function", "stateMutability": "view", "name": "allowance",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function", "stateMutability": "nonpayable", "name": "approve",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function", "stateMutability": "view", "name": "symbol",
        "inputs": [], "outputs": [{"name": "", "type": "string"}],
    },
    {
        "type": "function", "stateMutability": "view", "name": "name",
        "inputs": [], "outputs": [{"name": "", "type": "string"}],
    },
    {
        "type": "function", "stateMutability": "view", "name": "decimals",
        "inputs": [], "outputs": [{"name": "", "type": "uint8"}],
    },
]

_TRANSFER_TOPIC = "0x" + keccak(b"Transfer(address,address,uint256)").hex()
# TradeExecuted topic — для извлечения amountIn/amountOut из логов.
_TRADE_EXECUTED_TOPIC = "0x" + keccak(
    b"TradeExecuted(address,address,uint8,uint256,uint256,uint256,"
    b"uint256,uint256,uint256,address,uint256,uint256,uint256,uint256,uint256)"
).hex()


# ---------------------------------------------------------------------------
# Web3 / RPC
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
    raise TradeError(f"all LiteForge RPCs failed: {last_err}")


def account_from_private_key(pk: str):
    pk = (pk or "").strip()
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk
    return Account.from_key(pk)


def get_native_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        return int(w3.eth.get_balance(Web3.to_checksum_address(address)))
    return _call_with_rpc(_fn, proxy)


def get_token_balance(token: str, owner: str,
                      proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(token), abi=ERC20_ABI,
        )
        return int(c.functions.balanceOf(
            Web3.to_checksum_address(owner)).call())
    return _call_with_rpc(_fn, proxy)


def get_token_allowance(token: str, owner: str, spender: str,
                        proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(token), abi=ERC20_ABI,
        )
        return int(c.functions.allowance(
            Web3.to_checksum_address(owner),
            Web3.to_checksum_address(spender),
        ).call())
    return _call_with_rpc(_fn, proxy)


def get_token_symbol(token: str, proxy: Optional[str] = None) -> str:
    def _fn(w3: Web3) -> str:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(token), abi=ERC20_ABI,
        )
        try:
            return str(c.functions.symbol().call())
        except Exception:
            return ""
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
    raise TradeError(f"tx {tx_hash} pending > {timeout_sec}s")


def _send_signed(w3: Web3, account, tx: dict) -> str:
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h_bytes = w3.eth.send_raw_transaction(raw)
    h = h_bytes.hex() if hasattr(h_bytes, "hex") else str(h_bytes)
    if not h.startswith("0x"):
        h = "0x" + h
    return h


def _topic_to_addr(t) -> str:
    h = t.hex() if hasattr(t, "hex") else str(t)
    if not h.startswith("0x"):
        h = "0x" + h
    return "0x" + h[-40:]


def _extract_trade_amounts(receipt: dict, *, trader: str,
                           token: str) -> tuple[int, int]:
    """Из логов TradeExecuted достаём (amountIn, amountOut).

    TradeExecuted layout: topics=[sig, token, trader, tradeReferrer],
    data = abi-encoded (tradeType, amountIn, amountOut, ...).
    """
    token_lower = (token or "").lower()
    trader_lower = (trader or "").lower()
    for log in (receipt.get("logs") or []):
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        t0 = topics[0]
        t0_hex = t0.hex() if hasattr(t0, "hex") else str(t0)
        if not t0_hex.startswith("0x"):
            t0_hex = "0x" + t0_hex
        if t0_hex.lower() != _TRADE_EXECUTED_TOPIC.lower():
            continue
        # topic1 = token, topic2 = trader
        if _topic_to_addr(topics[1]).lower() != token_lower:
            continue
        if _topic_to_addr(topics[2]).lower() != trader_lower:
            continue
        data = log.get("data")
        data_hex = data.hex() if hasattr(data, "hex") else str(data)
        if not data_hex.startswith("0x"):
            data_hex = "0x" + data_hex
        raw = data_hex[2:]
        # uint8 tradeType (padded 32), then uint256 amountIn, uint256 amountOut
        try:
            amount_in = int(raw[64:128], 16)
            amount_out = int(raw[128:192], 16)
            return amount_in, amount_out
        except Exception:
            return 0, 0
    # Fallback: scan Transfer logs from/to trader
    in_amt = 0
    out_amt = 0
    for log in (receipt.get("logs") or []):
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        t0 = topics[0]
        t0_hex = t0.hex() if hasattr(t0, "hex") else str(t0)
        if not t0_hex.startswith("0x"):
            t0_hex = "0x" + t0_hex
        if t0_hex.lower() != _TRANSFER_TOPIC.lower():
            continue
        addr = (log.get("address") or "").lower()
        if addr != token_lower:
            continue
        from_a = _topic_to_addr(topics[1]).lower()
        to_a = _topic_to_addr(topics[2]).lower()
        data = log.get("data")
        data_hex = data.hex() if hasattr(data, "hex") else str(data)
        if not data_hex.startswith("0x"):
            data_hex = "0x" + data_hex
        try:
            val = int(data_hex, 16)
        except Exception:
            continue
        if to_a == trader_lower:
            out_amt += val
        elif from_a == trader_lower:
            in_amt += val
    return in_amt, out_amt


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------

def ensure_approve(*, account, token: str, amount_wei: int,
                   proxy: Optional[str] = None,
                   spender: Optional[str] = None) -> Optional[str]:
    """Если allowance(account, spender) < amount_wei — approve max.

    Возвращает tx_hash при отправке approve, иначе None.
    """
    spender = spender or ONMI_TRADE_ROUTER
    addr = account.address

    def _fn(w3: Web3) -> Optional[str]:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(token), abi=ERC20_ABI,
        )
        current = int(c.functions.allowance(
            Web3.to_checksum_address(addr),
            Web3.to_checksum_address(spender),
        ).call())
        if current >= int(amount_wei):
            return None
        gas_price = int(w3.eth.gas_price)
        nonce = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"))
        tx = c.functions.approve(
            Web3.to_checksum_address(spender), int(MAX_UINT256),
        ).build_transaction({
            "from": Web3.to_checksum_address(addr),
            "nonce": nonce,
            "gasPrice": gas_price,
            "chainId": int(w3.eth.chain_id),
        })
        try:
            est = int(w3.eth.estimate_gas(tx))
            tx["gas"] = int(est * 1.3)
        except Exception:
            tx["gas"] = 120_000
        h = _send_signed(w3, account, tx)
        receipt = _wait_receipt(w3, h, int(ONMI_TRADE_TX_TIMEOUT_SEC))
        if int(receipt.get("status", 0)) != 1:
            raise TradeError(f"approve {h} reverted")
        return h

    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# Buy
# ---------------------------------------------------------------------------

def buy_exact_in(
    *,
    account,
    token: str,
    value_wei: int,
    proxy: Optional[str] = None,
    trade_referrer: Optional[str] = None,
) -> tuple[str, dict, int]:
    """router.buyExactIn(token, 0, tradeReferrer) payable.

    Возвращает (tx_hash, receipt, tokens_received_wei)."""
    addr = account.address
    ref = trade_referrer or addr  # как делает сайт

    def _fn(w3: Web3) -> tuple[str, dict, int]:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_TRADE_ROUTER),
            abi=ROUTER_ABI,
        )
        nonce = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"))
        gas_price = int(w3.eth.gas_price)
        tx = c.functions.buyExactIn(
            Web3.to_checksum_address(token),
            0,
            Web3.to_checksum_address(ref),
        ).build_transaction({
            "from": Web3.to_checksum_address(addr),
            "value": int(value_wei),
            "nonce": nonce,
            "gasPrice": gas_price,
            "chainId": int(w3.eth.chain_id),
        })
        try:
            est = int(w3.eth.estimate_gas(tx))
            tx["gas"] = int(est * 1.3)
        except Exception:
            tx["gas"] = 600_000

        h = _send_signed(w3, account, tx)
        receipt = _wait_receipt(w3, h, int(ONMI_TRADE_TX_TIMEOUT_SEC))
        if int(receipt.get("status", 0)) != 1:
            raise TradeError(f"buy tx {h} reverted")
        _, tokens_out = _extract_trade_amounts(receipt, trader=addr, token=token)
        return h, receipt, int(tokens_out)

    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# Sell
# ---------------------------------------------------------------------------

def sell_exact_in(
    *,
    account,
    token: str,
    token_amount_wei: int,
    proxy: Optional[str] = None,
    trade_referrer: Optional[str] = None,
) -> tuple[str, dict, int]:
    """router.sellExactIn(token, tokenAmount, 0, tradeReferrer).

    Перед этим выполняется ensure_approve(). Возвращает (tx_hash, receipt,
    eth_received_wei)."""
    addr = account.address
    ref = trade_referrer or addr

    # approve first (отдельным колом, в собственном tx)
    ensure_approve(account=account, token=token, amount_wei=int(token_amount_wei),
                   proxy=proxy)

    def _fn(w3: Web3) -> tuple[str, dict, int]:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_TRADE_ROUTER),
            abi=ROUTER_ABI,
        )
        nonce = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"))
        gas_price = int(w3.eth.gas_price)
        tx = c.functions.sellExactIn(
            Web3.to_checksum_address(token),
            int(token_amount_wei),
            0,
            Web3.to_checksum_address(ref),
        ).build_transaction({
            "from": Web3.to_checksum_address(addr),
            "nonce": nonce,
            "gasPrice": gas_price,
            "chainId": int(w3.eth.chain_id),
        })
        try:
            est = int(w3.eth.estimate_gas(tx))
            tx["gas"] = int(est * 1.3)
        except Exception:
            tx["gas"] = 600_000

        h = _send_signed(w3, account, tx)
        receipt = _wait_receipt(w3, h, int(ONMI_TRADE_TX_TIMEOUT_SEC))
        if int(receipt.get("status", 0)) != 1:
            raise TradeError(f"sell tx {h} reverted")
        _, eth_out = _extract_trade_amounts(receipt, trader=addr, token=token)
        return h, receipt, int(eth_out)

    return _call_with_rpc(_fn, proxy)
