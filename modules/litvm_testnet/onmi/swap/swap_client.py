"""UniswapV2-style клиент для OnmiSwap (router 0xe351…fB57).

Поддерживаемые методы router:
  • swapExactETHForTokens(amountOutMin, path, to, deadline) payable
  • swapExactTokensForETH(amountIn, amountOutMin, path, to, deadline)
  • getAmountsOut(amountIn, path) view
  • getPair(tokenA, tokenB) (через factory)
  • Pair: token0, token1, getReserves
"""
from __future__ import annotations

import time
from typing import Optional

from eth_account import Account
from eth_utils import keccak
from web3 import Web3

from config.modules.cfg_litvm_testnet import (
    LITVM_RPCS,
    ONMI_SWAP_FACTORY,
    ONMI_SWAP_ROUTER,
    ONMI_SWAP_TX_TIMEOUT_SEC,
    ONMI_SWAP_WETH,
)
from modules.proxy_manager import get_proxy_dict


class SwapError(Exception):
    pass


ZERO_ADDR = "0x" + "0" * 40
MAX_UINT256 = (1 << 256) - 1


ROUTER_ABI = [
    {
        "type": "function", "name": "swapExactETHForTokens",
        "stateMutability": "payable",
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
    {
        "type": "function", "name": "swapExactTokensForETH",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
    {
        "type": "function", "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "stateMutability": "payable",
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "type": "function", "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "type": "function", "name": "getAmountsOut",
        "stateMutability": "view",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path", "type": "address[]"},
        ],
        "outputs": [{"name": "", "type": "uint256[]"}],
    },
    {
        "type": "function", "name": "addLiquidityETH",
        "stateMutability": "payable",
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "amountTokenDesired", "type": "uint256"},
            {"name": "amountTokenMin", "type": "uint256"},
            {"name": "amountETHMin", "type": "uint256"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [
            {"name": "amountToken", "type": "uint256"},
            {"name": "amountETH", "type": "uint256"},
            {"name": "liquidity", "type": "uint256"},
        ],
    },
    {
        "type": "function", "name": "removeLiquidityETH",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "liquidity", "type": "uint256"},
            {"name": "amountTokenMin", "type": "uint256"},
            {"name": "amountETHMin", "type": "uint256"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "outputs": [
            {"name": "amountToken", "type": "uint256"},
            {"name": "amountETH", "type": "uint256"},
        ],
    },
    {
        "type": "function", "name": "WETH",
        "stateMutability": "view", "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function", "name": "factory",
        "stateMutability": "view", "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
]

FACTORY_ABI = [
    {
        "type": "function", "name": "allPairsLength", "stateMutability": "view",
        "inputs": [], "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function", "name": "allPairs", "stateMutability": "view",
        "inputs": [{"name": "i", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function", "name": "getPair", "stateMutability": "view",
        "inputs": [{"name": "a", "type": "address"},
                   {"name": "b", "type": "address"}],
        "outputs": [{"name": "", "type": "address"}],
    },
]

PAIR_ABI = [
    {"type": "function", "name": "token0", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "token1", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"type": "function", "name": "getReserves", "stateMutability": "view",
     "inputs": [], "outputs": [
         {"name": "r0", "type": "uint112"}, {"name": "r1", "type": "uint112"},
         {"name": "ts", "type": "uint32"}]},
    {"type": "function", "name": "totalSupply", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "allowance", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
]

ERC20_ABI = [
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "allowance", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "symbol", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "string"}]},
    {"type": "function", "name": "decimals", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
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
    raise SwapError(f"all LiteForge RPCs failed: {last_err}")


def account_from_private_key(pk: str):
    pk = (pk or "").strip()
    if pk and not pk.startswith("0x"):
        pk = "0x" + pk
    return Account.from_key(pk)


def get_native_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        return int(w3.eth.get_balance(Web3.to_checksum_address(address)))
    return _call_with_rpc(_fn, proxy)


def get_erc20_balance(token: str, owner: str,
                      proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(address=Web3.to_checksum_address(token),
                            abi=ERC20_ABI)
        return int(c.functions.balanceOf(
            Web3.to_checksum_address(owner)).call())
    return _call_with_rpc(_fn, proxy)


def get_erc20_symbol(token: str, proxy: Optional[str] = None) -> str:
    def _fn(w3: Web3) -> str:
        c = w3.eth.contract(address=Web3.to_checksum_address(token),
                            abi=ERC20_ABI)
        try:
            return str(c.functions.symbol().call())
        except Exception:
            return ""
    return _call_with_rpc(_fn, proxy)


def get_erc20_decimals(token: str, proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(address=Web3.to_checksum_address(token),
                            abi=ERC20_ABI)
        try:
            return int(c.functions.decimals().call())
        except Exception:
            return 18
    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# Pair discovery
# ---------------------------------------------------------------------------

def discover_pairs(*, proxy: Optional[str] = None,
                   limit: Optional[int] = None,
                   on_pair=None,
                   on_progress=None) -> int:
    """Enumerate factory.allPairs(0..len). For each pair that has WETH on one
    side and reserves > 0, calls on_pair(dict).

    on_progress(i, total, accepted) — optional callback invoked after each
    pair is processed (best-effort, exceptions swallowed).
    """

    def _fn(w3: Web3) -> int:
        fac = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_SWAP_FACTORY), abi=FACTORY_ABI,
        )
        n = int(fac.functions.allPairsLength().call())
        if limit is not None:
            n = min(n, int(limit))
        weth = Web3.to_checksum_address(ONMI_SWAP_WETH)
        count = 0
        for i in range(n):
            try:
                try:
                    pair_addr = fac.functions.allPairs(i).call()
                    pc = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
                    t0 = pc.functions.token0().call()
                    t1 = pc.functions.token1().call()
                    r0, r1, _ = pc.functions.getReserves().call()
                except Exception:
                    continue
                if Web3.to_checksum_address(t0) == weth:
                    token = t1
                    reserve_native = int(r0)
                    reserve_token = int(r1)
                elif Web3.to_checksum_address(t1) == weth:
                    token = t0
                    reserve_native = int(r1)
                    reserve_token = int(r0)
                else:
                    continue  # пропускаем не-WETH пары
                if reserve_native == 0 or reserve_token == 0:
                    continue
                sym = ""
                decs = 18
                try:
                    ec = w3.eth.contract(address=token, abi=ERC20_ABI)
                    sym = str(ec.functions.symbol().call())
                    decs = int(ec.functions.decimals().call())
                except Exception:
                    pass
                if on_pair is not None:
                    on_pair({
                        "pair_address": pair_addr,
                        "token_address": token,
                        "token_symbol": sym,
                        "token_decimals": decs,
                        "weth_address": weth,
                        "reserve_native_wei": reserve_native,
                        "reserve_token_wei": reserve_token,
                    })
                count += 1
            finally:
                if on_progress is not None:
                    try:
                        on_progress(i + 1, n, count)
                    except Exception:
                        pass
        return count

    return _call_with_rpc(_fn, proxy)


def fetch_pair_reserves(pair_address: str, weth: str,
                        proxy: Optional[str] = None) -> tuple[int, int]:
    """Return (reserve_native_wei, reserve_token_wei)."""
    def _fn(w3: Web3) -> tuple[int, int]:
        pc = w3.eth.contract(address=Web3.to_checksum_address(pair_address),
                             abi=PAIR_ABI)
        t0 = pc.functions.token0().call()
        r0, r1, _ = pc.functions.getReserves().call()
        if Web3.to_checksum_address(t0) == Web3.to_checksum_address(weth):
            return int(r0), int(r1)
        return int(r1), int(r0)
    return _call_with_rpc(_fn, proxy)


def get_amounts_out(amount_in: int, path: list[str],
                    proxy: Optional[str] = None) -> list[int]:
    def _fn(w3: Web3) -> list[int]:
        r = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_SWAP_ROUTER), abi=ROUTER_ABI,
        )
        return list(r.functions.getAmountsOut(
            int(amount_in),
            [Web3.to_checksum_address(a) for a in path],
        ).call())
    return _call_with_rpc(_fn, proxy)


def get_pair_address(token: str, proxy: Optional[str] = None,
                     weth: Optional[str] = None) -> str:
    weth = weth or ONMI_SWAP_WETH

    def _fn(w3: Web3) -> str:
        f = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_SWAP_FACTORY),
            abi=FACTORY_ABI,
        )
        return f.functions.getPair(
            Web3.to_checksum_address(token), Web3.to_checksum_address(weth),
        ).call()
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
    raise SwapError(f"tx {tx_hash} pending > {timeout_sec}s")


def _send_signed(w3: Web3, account, tx: dict) -> str:
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h_bytes = w3.eth.send_raw_transaction(raw)
    h = h_bytes.hex() if hasattr(h_bytes, "hex") else str(h_bytes)
    if not h.startswith("0x"):
        h = "0x" + h
    return h


def ensure_approve(*, account, token: str, amount_wei: int,
                   proxy: Optional[str] = None,
                   spender: Optional[str] = None) -> Optional[str]:
    """Approve max если allowance меньше нужного."""
    spender = spender or ONMI_SWAP_ROUTER
    addr = account.address

    def _fn(w3: Web3) -> Optional[str]:
        c = w3.eth.contract(address=Web3.to_checksum_address(token),
                            abi=ERC20_ABI)
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
        r = _wait_receipt(w3, h, int(ONMI_SWAP_TX_TIMEOUT_SEC))
        if int(r.get("status", 0)) != 1:
            raise SwapError(f"approve {h} reverted")
        return h

    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# Swap operations
# ---------------------------------------------------------------------------

def swap_exact_eth_for_tokens(
    *, account, token: str, value_wei: int, min_out_wei: int,
    deadline_ts: int, proxy: Optional[str] = None,
) -> tuple[str, dict, int]:
    addr = account.address

    def _fn(w3: Web3) -> tuple[str, dict, int]:
        r = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_SWAP_ROUTER),
            abi=ROUTER_ABI,
        )
        path = [Web3.to_checksum_address(ONMI_SWAP_WETH),
                Web3.to_checksum_address(token)]
        nonce = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"))
        gas_price = int(w3.eth.gas_price)
        # Read token balance before
        ec = w3.eth.contract(address=Web3.to_checksum_address(token),
                             abi=ERC20_ABI)
        bal_before = int(ec.functions.balanceOf(
            Web3.to_checksum_address(addr)).call())
        tx = r.functions.swapExactETHForTokens(
            int(min_out_wei), path,
            Web3.to_checksum_address(addr), int(deadline_ts),
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
            tx["gas"] = 350_000
        h = _send_signed(w3, account, tx)
        rcpt = _wait_receipt(w3, h, int(ONMI_SWAP_TX_TIMEOUT_SEC))
        if int(rcpt.get("status", 0)) != 1:
            raise SwapError(f"swap (ETH→token) {h} reverted")
        bal_after = int(ec.functions.balanceOf(
            Web3.to_checksum_address(addr)).call())
        return h, rcpt, max(0, bal_after - bal_before)

    return _call_with_rpc(_fn, proxy)


def swap_exact_tokens_for_eth(
    *, account, token: str, amount_in_wei: int, min_out_wei: int,
    deadline_ts: int, proxy: Optional[str] = None,
) -> tuple[str, dict, int]:
    addr = account.address
    ensure_approve(account=account, token=token,
                   amount_wei=int(amount_in_wei), proxy=proxy)

    def _fn(w3: Web3) -> tuple[str, dict, int]:
        r = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_SWAP_ROUTER),
            abi=ROUTER_ABI,
        )
        path = [Web3.to_checksum_address(token),
                Web3.to_checksum_address(ONMI_SWAP_WETH)]
        nonce = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"))
        gas_price = int(w3.eth.gas_price)
        eth_before = int(w3.eth.get_balance(Web3.to_checksum_address(addr)))
        tx = r.functions.swapExactTokensForETH(
            int(amount_in_wei), int(min_out_wei), path,
            Web3.to_checksum_address(addr), int(deadline_ts),
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
            tx["gas"] = 400_000
        h = _send_signed(w3, account, tx)
        rcpt = _wait_receipt(w3, h, int(ONMI_SWAP_TX_TIMEOUT_SEC))
        if int(rcpt.get("status", 0)) != 1:
            raise SwapError(f"swap (token→ETH) {h} reverted")
        gas_used = int(rcpt.get("gasUsed") or 0)
        eth_after = int(w3.eth.get_balance(Web3.to_checksum_address(addr)))
        # received = (after - before) + gas_cost  (т.к. gas сжёг native)
        net_received = (eth_after - eth_before) + gas_used * gas_price
        return h, rcpt, max(0, net_received)

    return _call_with_rpc(_fn, proxy)


# ---------------------------------------------------------------------------
# Add / remove liquidity (используются модулем liquidity)
# ---------------------------------------------------------------------------

def add_liquidity_eth(
    *, account, token: str, amount_token_desired: int, value_wei: int,
    amount_token_min: int, amount_eth_min: int, deadline_ts: int,
    proxy: Optional[str] = None,
) -> tuple[str, dict, int]:
    """Возвращает (tx_hash, receipt, lp_minted_wei). LP мерится через
    Pair.balanceOf(after) - Pair.balanceOf(before).
    """
    addr = account.address
    ensure_approve(account=account, token=token,
                   amount_wei=int(amount_token_desired), proxy=proxy)

    def _fn(w3: Web3) -> tuple[str, dict, int]:
        r = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_SWAP_ROUTER),
            abi=ROUTER_ABI,
        )
        # Pair lookup
        f = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_SWAP_FACTORY),
            abi=FACTORY_ABI,
        )
        pair_addr = f.functions.getPair(
            Web3.to_checksum_address(token),
            Web3.to_checksum_address(ONMI_SWAP_WETH),
        ).call()
        if int(pair_addr, 16) == 0:
            raise SwapError("pair does not exist (token not graduated)")
        pc = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
        lp_before = int(pc.functions.balanceOf(
            Web3.to_checksum_address(addr)).call())

        nonce = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"))
        gas_price = int(w3.eth.gas_price)
        tx = r.functions.addLiquidityETH(
            Web3.to_checksum_address(token),
            int(amount_token_desired),
            int(amount_token_min),
            int(amount_eth_min),
            Web3.to_checksum_address(addr),
            int(deadline_ts),
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
            tx["gas"] = 500_000
        h = _send_signed(w3, account, tx)
        rcpt = _wait_receipt(w3, h, int(ONMI_SWAP_TX_TIMEOUT_SEC))
        if int(rcpt.get("status", 0)) != 1:
            raise SwapError(f"addLiquidityETH {h} reverted")
        lp_after = int(pc.functions.balanceOf(
            Web3.to_checksum_address(addr)).call())
        return h, rcpt, max(0, lp_after - lp_before)

    return _call_with_rpc(_fn, proxy)


def remove_liquidity_eth(
    *, account, token: str, liquidity_wei: int,
    amount_token_min: int, amount_eth_min: int, deadline_ts: int,
    proxy: Optional[str] = None,
) -> tuple[str, dict, int, int]:
    """Возвращает (tx_hash, receipt, eth_received, token_received).
    Перед сделкой делает approve(LP-токена, router)."""
    addr = account.address

    def _resolve_pair(w3: Web3) -> str:
        f = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_SWAP_FACTORY),
            abi=FACTORY_ABI,
        )
        return f.functions.getPair(
            Web3.to_checksum_address(token),
            Web3.to_checksum_address(ONMI_SWAP_WETH),
        ).call()

    pair_addr = _call_with_rpc(_resolve_pair, proxy)
    if int(pair_addr, 16) == 0:
        raise SwapError("pair does not exist")
    # approve LP token to router
    ensure_approve(account=account, token=pair_addr,
                   amount_wei=int(liquidity_wei), proxy=proxy)

    def _fn(w3: Web3) -> tuple[str, dict, int, int]:
        r = w3.eth.contract(
            address=Web3.to_checksum_address(ONMI_SWAP_ROUTER),
            abi=ROUTER_ABI,
        )
        ec = w3.eth.contract(address=Web3.to_checksum_address(token),
                             abi=ERC20_ABI)
        eth_before = int(w3.eth.get_balance(Web3.to_checksum_address(addr)))
        tok_before = int(ec.functions.balanceOf(
            Web3.to_checksum_address(addr)).call())
        nonce = int(w3.eth.get_transaction_count(
            Web3.to_checksum_address(addr), "pending"))
        gas_price = int(w3.eth.gas_price)
        tx = r.functions.removeLiquidityETH(
            Web3.to_checksum_address(token),
            int(liquidity_wei),
            int(amount_token_min),
            int(amount_eth_min),
            Web3.to_checksum_address(addr),
            int(deadline_ts),
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
            tx["gas"] = 400_000
        h = _send_signed(w3, account, tx)
        rcpt = _wait_receipt(w3, h, int(ONMI_SWAP_TX_TIMEOUT_SEC))
        if int(rcpt.get("status", 0)) != 1:
            raise SwapError(f"removeLiquidityETH {h} reverted")
        gas_used = int(rcpt.get("gasUsed") or 0)
        eth_after = int(w3.eth.get_balance(Web3.to_checksum_address(addr)))
        tok_after = int(ec.functions.balanceOf(
            Web3.to_checksum_address(addr)).call())
        eth_received = (eth_after - eth_before) + gas_used * gas_price
        tok_received = tok_after - tok_before
        return h, rcpt, max(0, eth_received), max(0, tok_received)

    return _call_with_rpc(_fn, proxy)


def get_lp_balance(pair_address: str, owner: str,
                   proxy: Optional[str] = None) -> int:
    def _fn(w3: Web3) -> int:
        pc = w3.eth.contract(address=Web3.to_checksum_address(pair_address),
                             abi=PAIR_ABI)
        return int(pc.functions.balanceOf(
            Web3.to_checksum_address(owner)).call())
    return _call_with_rpc(_fn, proxy)
