"""LiteForge bridge — on-chain клиент (Arbitrum Orbit, custom gas-token zkLTC).

Маршруты:
  L1 (Sepolia) → L2: approve + ERC20Inbox.depositERC20
  L2 → L1: ArbSys.withdrawEth (на L1 финализация через Outbox.executeTransaction;
           делается автоматически модулем при следующих запусках, когда
           ассерция rollup'а будет подтверждена)
"""
from __future__ import annotations

import time
from typing import Optional

from eth_utils import keccak
from web3 import Web3
from web3.exceptions import TransactionNotFound

from config.modules.cfg_litvm_testnet import (
    LITVM_BRIDGE_L1_BRIDGE,
    LITVM_BRIDGE_L1_INBOX,
    LITVM_BRIDGE_L1_TOKEN_ZKLTC,
    LITVM_BRIDGE_L2_ARBSYS,
    LITVM_BRIDGE_L2_NODE_INTERFACE,
    LITVM_BRIDGE_LITEFORGE_CHAIN_ID,
    LITVM_BRIDGE_RECEIPT_TIMEOUT_SEC,
    LITVM_BRIDGE_RPC_TIMEOUT,
    LITVM_BRIDGE_SEPOLIA_CHAIN_ID,
    LITVM_BRIDGE_SEPOLIA_RPCS,
    LITVM_RPCS,
)
from modules.proxy_manager import get_proxy_dict


# ---------------------------------------------------------------------------
# ABI fragments
# ---------------------------------------------------------------------------

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
    {"name": "allowance", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint8"}]},
]

# Arbitrum Orbit ERC20Inbox: depositERC20(uint256) returns (uint256 sequenceNumber)
ERC20_INBOX_ABI = [
    {"name": "depositERC20", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "", "type": "uint256"}]},
]

# ArbSys precompile (L2 0x...0064): withdrawEth(address) payable returns (uint256)
ARBSYS_ABI = [
    {"name": "withdrawEth", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "destination", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    # event L2ToL1Tx(address caller, address indexed destination,
    #                uint256 indexed hash, uint256 indexed position,
    #                uint256 arbBlockNum, uint256 ethBlockNum,
    #                uint256 timestamp, uint256 callvalue, bytes data)
    {"name": "L2ToL1Tx", "type": "event", "anonymous": False,
     "inputs": [
         {"name": "caller", "type": "address", "indexed": False},
         {"name": "destination", "type": "address", "indexed": True},
         {"name": "hash", "type": "uint256", "indexed": True},
         {"name": "position", "type": "uint256", "indexed": True},
         {"name": "arbBlockNum", "type": "uint256", "indexed": False},
         {"name": "ethBlockNum", "type": "uint256", "indexed": False},
         {"name": "timestamp", "type": "uint256", "indexed": False},
         {"name": "callvalue", "type": "uint256", "indexed": False},
         {"name": "data", "type": "bytes", "indexed": False},
     ]},
]

# Bridge (L1): activeOutbox + allowedOutboxList(uint256)
L1_BRIDGE_ABI = [
    {"name": "activeOutbox", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "address"}]},
    {"name": "allowedOutboxList", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "uint256"}], "outputs": [{"type": "address"}]},
]

# Outbox (L1): executeTransaction + roots view
L1_OUTBOX_ABI = [
    {"name": "executeTransaction", "type": "function", "stateMutability": "nonpayable",
     "inputs": [
         {"name": "proof", "type": "bytes32[]"},
         {"name": "index", "type": "uint256"},
         {"name": "l2Sender", "type": "address"},
         {"name": "to", "type": "address"},
         {"name": "l2Block", "type": "uint256"},
         {"name": "l1Block", "type": "uint256"},
         {"name": "l2Timestamp", "type": "uint256"},
         {"name": "value", "type": "uint256"},
         {"name": "data", "type": "bytes"},
     ], "outputs": []},
    {"name": "roots", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "bytes32"}],
     "outputs": [{"type": "bytes32"}]},
]

# NodeInterface (L2 0x...00c8): constructOutboxProof(size, leaf)
#  returns (bytes32 send, bytes32 root, bytes32[] proof)
L2_NODE_INTERFACE_ABI = [
    {"name": "constructOutboxProof", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "size", "type": "uint64"},
                {"name": "leaf", "type": "uint64"}],
     "outputs": [{"name": "send", "type": "bytes32"},
                 {"name": "root", "type": "bytes32"},
                 {"name": "proof", "type": "bytes32[]"}]},
]


# ---------------------------------------------------------------------------
# RPC helpers (round-robin)
# ---------------------------------------------------------------------------

class _ChainCfg:
    __slots__ = ("name", "chain_id", "rpcs")

    def __init__(self, name: str, chain_id: int, rpcs: list[str]) -> None:
        self.name = name
        self.chain_id = chain_id
        self.rpcs = list(rpcs)


L1 = _ChainCfg("Sepolia", LITVM_BRIDGE_SEPOLIA_CHAIN_ID,
               LITVM_BRIDGE_SEPOLIA_RPCS)
L2 = _ChainCfg("LiteForge", LITVM_BRIDGE_LITEFORGE_CHAIN_ID,
               LITVM_RPCS)


def get_w3(chain: _ChainCfg, proxy: Optional[str] = None,
           rpc_index: int = 0) -> Web3:
    """Создаёт Web3 на N-м RPC из списка (round-robin делает caller)."""
    proxy_dict = get_proxy_dict(proxy)
    request_kwargs: dict = {"timeout": LITVM_BRIDGE_RPC_TIMEOUT}
    if proxy_dict:
        request_kwargs["proxies"] = proxy_dict
    rpc = chain.rpcs[rpc_index % len(chain.rpcs)]
    return Web3(Web3.HTTPProvider(rpc, request_kwargs=request_kwargs))


def call_with_rpc_fallback(chain: _ChainCfg, fn, proxy: Optional[str] = None):
    """Запустить `fn(w3)` перебирая RPC из chain.rpcs до успеха."""
    last_err: Optional[Exception] = None
    for i in range(len(chain.rpcs)):
        try:
            w3 = get_w3(chain, proxy, rpc_index=i)
            return fn(w3)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise BridgeError(f"all {chain.name} RPCs failed: {last_err}")


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

class BridgeError(Exception):
    pass


class InsufficientBalance(BridgeError):
    pass


class ApprovalFailed(BridgeError):
    pass


class DepositFailed(BridgeError):
    pass


# ---------------------------------------------------------------------------
# tx helpers
# ---------------------------------------------------------------------------

def _build_fees_l1(w3: Web3) -> dict:
    """Sepolia — EIP-1559. Используем maxFeePerGas из RPC c небольшим запасом."""
    try:
        base = w3.eth.get_block("latest").get("baseFeePerGas") or 0
        prio = w3.to_wei("1.5", "gwei")
        max_fee = int(base) * 2 + int(prio)
        return {"maxFeePerGas": int(max_fee),
                "maxPriorityFeePerGas": int(prio)}
    except Exception:
        # Fallback на legacy
        gp = int(w3.eth.gas_price * 1.2)
        return {"gasPrice": gp}


def _build_fees_l2(w3: Web3) -> dict:
    """LiteForge (Arbitrum Nitro) — обычно поддерживает EIP-1559, но
    некоторые Orbit-чейны капризные на priority. Используем legacy gasPrice
    из RPC с +20% запасом."""
    gp = int(w3.eth.gas_price * 1.2)
    return {"gasPrice": gp}


def _sign_and_send(w3: Web3, tx: dict, pk: str) -> str:
    signed = w3.eth.account.sign_transaction(tx, pk)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction")
    h = w3.eth.send_raw_transaction(raw)
    return h.hex() if hasattr(h, "hex") else str(h)


def _wait_receipt(w3: Web3, tx_hash: str,
                  timeout: int = LITVM_BRIDGE_RECEIPT_TIMEOUT_SEC) -> dict:
    """Polling receipt с устойчивостью к TransactionNotFound на пуле RPC."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            rc = w3.eth.get_transaction_receipt(tx_hash)
            if rc is not None:
                return {"status": int(rc.status), "block": int(rc.blockNumber),
                        "gas_used": int(rc.gasUsed)}
        except TransactionNotFound:
            pass
        except Exception:
            pass
        time.sleep(5)
    raise BridgeError(f"receipt timeout {timeout}s for tx {tx_hash}")


# ---------------------------------------------------------------------------
# balance / allowance
# ---------------------------------------------------------------------------

def l1_zkltc_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    addr = Web3.to_checksum_address(address)

    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(LITVM_BRIDGE_L1_TOKEN_ZKLTC),
            abi=ERC20_ABI,
        )
        return int(c.functions.balanceOf(addr).call())

    return call_with_rpc_fallback(L1, _fn, proxy)


def l1_native_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    addr = Web3.to_checksum_address(address)
    return call_with_rpc_fallback(L1, lambda w3: int(w3.eth.get_balance(addr)), proxy)


def l2_native_balance_wei(address: str, proxy: Optional[str] = None) -> int:
    addr = Web3.to_checksum_address(address)
    return call_with_rpc_fallback(L2, lambda w3: int(w3.eth.get_balance(addr)), proxy)


def l1_zkltc_allowance(owner: str, proxy: Optional[str] = None) -> int:
    addr = Web3.to_checksum_address(owner)
    spender = Web3.to_checksum_address(LITVM_BRIDGE_L1_INBOX)

    def _fn(w3: Web3) -> int:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(LITVM_BRIDGE_L1_TOKEN_ZKLTC),
            abi=ERC20_ABI,
        )
        return int(c.functions.allowance(addr, spender).call())

    return call_with_rpc_fallback(L1, _fn, proxy)


# ---------------------------------------------------------------------------
# L1 → L2: approve + depositERC20
# ---------------------------------------------------------------------------

def send_l1_approve(*, account, amount_wei: int,
                    proxy: Optional[str] = None) -> tuple[str, dict]:
    """Если allowance уже достаточен — возвращает ('', None)."""
    cur = l1_zkltc_allowance(account.address, proxy)
    if cur >= amount_wei:
        return "", {"skipped": True, "allowance": cur}

    def _fn(w3: Web3) -> tuple[str, dict]:
        c = w3.eth.contract(
            address=Web3.to_checksum_address(LITVM_BRIDGE_L1_TOKEN_ZKLTC),
            abi=ERC20_ABI,
        )
        # Apprve "approve(spender, MAX)" чтобы не дёргать каждый раз;
        # это безопасно — допускаем потерю весь balance только если
        # private_key утёк. На уровне модуля приемлемо.
        max_uint = (1 << 256) - 1
        fees = _build_fees_l1(w3)
        nonce = w3.eth.get_transaction_count(account.address)
        tx = c.functions.approve(
            Web3.to_checksum_address(LITVM_BRIDGE_L1_INBOX), int(max_uint),
        ).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "chainId": L1.chain_id,
            **fees,
        })
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.3)
        except Exception:
            tx["gas"] = 70_000
        h = _sign_and_send(w3, tx, account.key)
        rc = _wait_receipt(w3, h)
        if rc["status"] != 1:
            raise ApprovalFailed(f"approve reverted (tx={h})")
        return h, rc

    return call_with_rpc_fallback(L1, _fn, proxy)


def send_l1_deposit(*, account, amount_wei: int,
                    proxy: Optional[str] = None) -> tuple[str, dict]:
    """ERC20Inbox.depositERC20(amount). Возвращает (tx_hash, receipt-dict)."""
    def _fn(w3: Web3) -> tuple[str, dict]:
        inbox = w3.eth.contract(
            address=Web3.to_checksum_address(LITVM_BRIDGE_L1_INBOX),
            abi=ERC20_INBOX_ABI,
        )
        fees = _build_fees_l1(w3)
        nonce = w3.eth.get_transaction_count(account.address)
        tx = inbox.functions.depositERC20(int(amount_wei)).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "chainId": L1.chain_id,
            **fees,
        })
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.4)
        except Exception:
            tx["gas"] = 200_000
        # sanity: native (ETH) hold
        native = int(w3.eth.get_balance(account.address))
        gas_price = int(fees.get("maxFeePerGas") or fees.get("gasPrice") or 0)
        gas_cost = int(tx["gas"]) * gas_price
        if native < gas_cost:
            raise InsufficientBalance(
                f"Sepolia ETH balance {native/1e18:.6f} insufficient for "
                f"deposit gas {gas_cost/1e18:.6f}"
            )
        h = _sign_and_send(w3, tx, account.key)
        rc = _wait_receipt(w3, h)
        if rc["status"] != 1:
            raise DepositFailed(f"depositERC20 reverted (tx={h})")
        return h, rc

    return call_with_rpc_fallback(L1, _fn, proxy)


# ---------------------------------------------------------------------------
# L2 → L1: ArbSys.withdrawEth
# ---------------------------------------------------------------------------

def send_l2_withdraw(*, account, amount_wei: int, destination: str,
                     proxy: Optional[str] = None) -> tuple[str, dict]:
    """ArbSys.withdrawEth{value: amount}(destination). L1-финализация делается
    отдельной фазой автоматически (try_finalize_l2_withdraw)."""
    def _fn(w3: Web3) -> tuple[str, dict]:
        arbsys = w3.eth.contract(
            address=Web3.to_checksum_address(LITVM_BRIDGE_L2_ARBSYS),
            abi=ARBSYS_ABI,
        )
        fees = _build_fees_l2(w3)
        nonce = w3.eth.get_transaction_count(account.address)
        tx = arbsys.functions.withdrawEth(
            Web3.to_checksum_address(destination),
        ).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "chainId": L2.chain_id,
            "value": int(amount_wei),
            **fees,
        })
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.4)
        except Exception:
            tx["gas"] = 500_000
        native = int(w3.eth.get_balance(account.address))
        gas_price = int(fees.get("gasPrice") or 0)
        gas_cost = int(tx["gas"]) * gas_price
        if native < int(amount_wei) + gas_cost:
            raise InsufficientBalance(
                f"L2 zkLTC balance {native/1e18:.6f} insufficient for "
                f"withdraw {int(amount_wei)/1e18:.6f} + gas {gas_cost/1e18:.6f}"
            )
        h = _sign_and_send(w3, tx, account.key)
        rc = _wait_receipt(w3, h)
        if rc["status"] != 1:
            raise BridgeError(f"withdrawEth reverted (tx={h})")
        return h, rc

    return call_with_rpc_fallback(L2, _fn, proxy)


# ---------------------------------------------------------------------------
# L2 → L1: автоматическая финализация (Outbox.executeTransaction)
# ---------------------------------------------------------------------------

# event L2ToL1Tx(address,address,uint256,uint256,uint256,uint256,uint256,uint256,bytes)
_L2_TO_L1_TX_TOPIC = (
    "0x" + keccak(text=(
        "L2ToL1Tx(address,address,uint256,uint256,uint256,uint256,"
        "uint256,uint256,bytes)"
    )).hex()
)


class FinalizeNotReady(BridgeError):
    """Outbox ещё не готов исполнить вывод (challenge window открыт, либо
    ассерция rollup'а не подтверждена). Не ошибка — повтор при сл. запуске."""


def get_l1_active_outbox(proxy: Optional[str] = None) -> Optional[str]:
    """Возвращает адрес активного Outbox на L1 или None если ещё не задан."""
    def _fn(w3: Web3) -> Optional[str]:
        bridge = w3.eth.contract(
            address=Web3.to_checksum_address(LITVM_BRIDGE_L1_BRIDGE),
            abi=L1_BRIDGE_ABI,
        )
        try:
            addr = bridge.functions.activeOutbox().call()
        except Exception:
            addr = None
        if addr and int(addr, 16) != 0:
            return Web3.to_checksum_address(addr)
        # fallback: первый из списка
        try:
            addr2 = bridge.functions.allowedOutboxList(0).call()
            if (addr2 and int(addr2, 16) != 0
                    and Web3.to_checksum_address(addr2)
                    != Web3.to_checksum_address(LITVM_BRIDGE_L1_INBOX)):
                return Web3.to_checksum_address(addr2)
        except Exception:
            return None
        return None

    return call_with_rpc_fallback(L1, _fn, proxy)


def fetch_l2_to_l1_event(l2_tx_hash: str, proxy: Optional[str] = None) -> dict:
    """Достаёт параметры события L2ToL1Tx из чека L2-tx."""
    def _fn(w3: Web3) -> dict:
        rc = w3.eth.get_transaction_receipt(l2_tx_hash)
        arbsys = Web3.to_checksum_address(LITVM_BRIDGE_L2_ARBSYS)
        for log in rc["logs"]:
            if (Web3.to_checksum_address(log["address"]) != arbsys
                    or len(log["topics"]) < 4):
                continue
            t0 = log["topics"][0].hex() if hasattr(log["topics"][0], "hex") else log["topics"][0]
            if str(t0).lower() != _L2_TO_L1_TX_TOPIC.lower():
                continue
            arbsys_contract = w3.eth.contract(address=arbsys, abi=ARBSYS_ABI)
            ev = arbsys_contract.events.L2ToL1Tx().process_log(log)
            a = ev["args"]
            return {
                "caller": a["caller"],
                "destination": a["destination"],
                "hash": int(a["hash"]),
                "position": int(a["position"]),
                "arbBlockNum": int(a["arbBlockNum"]),
                "ethBlockNum": int(a["ethBlockNum"]),
                "timestamp": int(a["timestamp"]),
                "callvalue": int(a["callvalue"]),
                "data": bytes(a["data"]),
            }
        raise BridgeError(f"L2ToL1Tx event не найден в receipt {l2_tx_hash}")

    return call_with_rpc_fallback(L2, _fn, proxy)


def _construct_outbox_proof(position: int,
                            proxy: Optional[str] = None) -> tuple[bytes, bytes, list[bytes]]:
    """Вызывает NodeInterface.constructOutboxProof. Возвращает (send, root, proof).
    Бросает FinalizeNotReady если proof ещё нельзя построить."""
    def _fn(w3: Web3):
        node = w3.eth.contract(
            address=Web3.to_checksum_address(LITVM_BRIDGE_L2_NODE_INTERFACE),
            abi=L2_NODE_INTERFACE_ABI,
        )
        # size = position + 1 (минимальный валидный размер) — node сам найдёт
        # ближайший подтверждённый assertion. Если ещё не готов — revert.
        try:
            send, root, proof = node.functions.constructOutboxProof(
                int(position) + 1, int(position)
            ).call()
        except Exception as e:
            raise FinalizeNotReady(
                f"constructOutboxProof: ассерция rollup'а ещё не подтверждена ({e})"
            ) from None
        return bytes(send), bytes(root), [bytes(p) for p in proof]

    return call_with_rpc_fallback(L2, _fn, proxy)


def try_finalize_l2_withdraw(*, account, l2_tx_hash: str,
                             proxy: Optional[str] = None) -> dict:
    """Авто-финализация L2→L1 на Sepolia. Возвращает dict с полями:
        {ready: bool, l1_tx_hash: Optional[str], reason: Optional[str]}.
    Если outbox ещё не готов — ready=False, ошибки нет (повтор позже).
    Если исполнили — ready=True + l1_tx_hash.
    Бросает BridgeError только на необратимых сбоях (события нет, баланс L1 пуст)."""
    outbox = get_l1_active_outbox(proxy)
    if not outbox:
        return {"ready": False, "l1_tx_hash": None,
                "reason": "L1 Outbox ещё не активирован оператором rollup'а"}

    event = fetch_l2_to_l1_event(l2_tx_hash, proxy)
    try:
        send, root, proof = _construct_outbox_proof(event["position"], proxy)
    except FinalizeNotReady as e:
        return {"ready": False, "l1_tx_hash": None, "reason": str(e)}

    def _fn(w3: Web3) -> str:
        outbox_c = w3.eth.contract(
            address=Web3.to_checksum_address(outbox),
            abi=L1_OUTBOX_ABI,
        )
        # Проверяем что root уже зарегистрирован в outbox
        try:
            ts_or_block = outbox_c.functions.roots(root).call()
            if isinstance(ts_or_block, (bytes, bytearray)) and int.from_bytes(ts_or_block, "big") == 0:
                raise FinalizeNotReady("root ещё не зарегистрирован в Outbox")
        except FinalizeNotReady:
            raise
        except Exception:
            # roots() может иметь другую сигнатуру на этом outbox — пропускаем check,
            # пусть executeTransaction сам ревёртнется
            pass
        # Проверка газа
        eth = w3.eth.get_balance(account.address)
        if eth < int(0.001 * 1e18):
            raise InsufficientBalance(
                f"Sepolia ETH {eth/1e18:.6f} не хватит на executeTransaction"
            )
        fees = _build_fees_l1(w3)
        nonce = w3.eth.get_transaction_count(account.address)
        tx = outbox_c.functions.executeTransaction(
            proof,
            int(event["position"]),
            Web3.to_checksum_address(event["caller"]),
            Web3.to_checksum_address(event["destination"]),
            int(event["arbBlockNum"]),
            int(event["ethBlockNum"]),
            int(event["timestamp"]),
            int(event["callvalue"]),
            event["data"],
        ).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "chainId": L1.chain_id,
            **fees,
        })
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.4)
        except Exception as e:
            # Если estimate ревёртит — почти наверняка не готов
            raise FinalizeNotReady(f"estimate_gas revert: {e}") from None
        h = _sign_and_send(w3, tx, account.key)
        rc = _wait_receipt(w3, h)
        if rc["status"] != 1:
            raise BridgeError(f"executeTransaction reverted (tx={h})")
        return h

    try:
        h = call_with_rpc_fallback(L1, _fn, proxy)
        return {"ready": True, "l1_tx_hash": h, "reason": None}
    except FinalizeNotReady as e:
        return {"ready": False, "l1_tx_hash": None, "reason": str(e)}
