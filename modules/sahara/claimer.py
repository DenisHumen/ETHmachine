"""Sahara Knowledge Drop claimer + (optional) auto-withdraw на CEX-адрес.

Поток для одного кошелька (`run_one`):
  1. SIWE sign_in
  2. /sahara/info — проверка eligibility / уже-claimed статуса
  3. /sahara/prepare_claim → calldata
  4. on-chain claimEarndrop / multiClaimEarndrop на BSC (value = claim_fee BNB)
  5. ждём receipt + ждём зачисления SAHARA на balanceOf кошелька
  6. /sahara/record_claim (best-effort)
  7. если AUTO_WITHDRAW_TO_CEX и evm_cex_address заполнен →
     ERC-20 transfer всех SAHARA на CEX-адрес + ждём зачисления
     на CEX-адрес через balanceOf.

Все параметры (потоки, задержки, ретраи) — из general_config.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound

from config.networks import NETWORKS
from config.modules.general_config import (
    SLEEP_BETWEEN_ACTIONS,
    TX_SEND_ATTEMPTS,
    RETRY_COUNT,
    WHAITE_TRANSACTION_PENDING,
    WHAITE_TRANSACTION_PENDING_COUNT,
)
from config.modules.cfg_sahara import (
    AUTO_WITHDRAW_TO_CEX,
    CHAIN_KEY,
    CHAIN_ID,
    SAHARA_TOKEN_ADDRESS,
    MIN_BNB_FOR_GAS,
    CLAIM_BALANCE_WAIT_TIMEOUT,
    CLAIM_BALANCE_POLL_INTERVAL,
    WITHDRAW_BALANCE_WAIT_TIMEOUT,
    WITHDRAW_BALANCE_POLL_INTERVAL,
)
from modules.proxy_manager import parse_proxy
from modules.simple_logger import log_wallet_task

from modules.sahara.earndrop_api import EarndropClient, EarndropError


# --- ABI ----------------------------------------------------------------------
# Только то, что реально используется: claimEarndrop, multiClaimEarndrop, balanceOf, transfer.

CLAIM_PARAM_TUPLE = {
    "components": [
        {"internalType": "uint256", "name": "stageIndex", "type": "uint256"},
        {"internalType": "uint256", "name": "leafIndex", "type": "uint256"},
        {"internalType": "address", "name": "account", "type": "address"},
        {"internalType": "uint256", "name": "amount", "type": "uint256"},
        {"internalType": "bytes32[]", "name": "merkleProof", "type": "bytes32[]"},
    ],
    "internalType": "struct VestingEarndrop.ClaimParam",
    "name": "param",
    "type": "tuple",
}

CLAIM_PARAMS_ARRAY = {
    **CLAIM_PARAM_TUPLE,
    "name": "params",
    "type": "tuple[]",
}

EARNDROP_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "earndropId", "type": "uint256"},
            CLAIM_PARAM_TUPLE,
            {"internalType": "bytes", "name": "signature", "type": "bytes"},
        ],
        "name": "claimEarndrop",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "earndropId", "type": "uint256"},
            CLAIM_PARAMS_ARRAY,
            {"internalType": "bytes", "name": "signature", "type": "bytes"},
        ],
        "name": "multiClaimEarndrop",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
]

ERC20_MIN_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# --- result struct ------------------------------------------------------------

@dataclass
class WalletResult:
    name: str
    address: str
    eligible: Optional[int] = None         # raw amount (wei, 18 decimals)
    already_claimed: Optional[int] = None
    claim_tx: Optional[str] = None
    claim_amount: Optional[int] = None     # сколько списал контракт за эту сессию (raw)
    withdraw_tx: Optional[str] = None
    withdraw_amount: Optional[int] = None  # сколько ушло на CEX (raw)
    cex_balance_after: Optional[int] = None
    status: str = "pending"                # pending | not_eligible | already_claimed | claimed | claimed+withdrawn | failed
    errors: List[str] = field(default_factory=list)


# --- web3 helpers -------------------------------------------------------------

def _get_rpc_urls() -> List[str]:
    cfg = NETWORKS.get(CHAIN_KEY, {})
    urls = cfg.get('rpc_urls') or []
    if not urls:
        raise RuntimeError(f"No RPC URLs configured for {CHAIN_KEY}")
    return list(urls)


def _w3_for(rpc_url: str, proxy: Optional[str] = None) -> Web3:
    request_kwargs: Dict[str, Any] = {"timeout": 30}
    if proxy:
        # Web3.HTTPProvider использует requests под капотом — proxies прокидываются.
        request_kwargs["proxies"] = {"http": proxy, "https": proxy}
    return Web3(Web3.HTTPProvider(rpc_url, request_kwargs=request_kwargs))


def _with_rpc_fallback(callable_with_w3, proxy: Optional[str] = None,
                       attempts: Optional[int] = None) -> Any:
    """Выполнить callable(w3) с перебором RPC при ошибках."""
    rpc_urls = _get_rpc_urls()
    random.shuffle(rpc_urls)
    n = attempts or max(RETRY_COUNT, len(rpc_urls))
    last_exc: Optional[Exception] = None
    for i in range(n):
        url = rpc_urls[i % len(rpc_urls)]
        try:
            w3 = _w3_for(url, proxy=proxy)
            return callable_with_w3(w3)
        except Exception as e:  # web3/requests/timeouts → next RPC
            last_exc = e
            time.sleep(min(2.0, 0.3 * (i + 1)))
    raise RuntimeError(f"All RPCs failed after {n} attempts: {last_exc}")


def _send_signed(w3: Web3, tx: dict, private_key: str) -> str:
    signed = w3.eth.account.sign_transaction(tx, private_key)
    raw = getattr(signed, "rawTransaction", None) or signed.raw_transaction  # type: ignore[attr-defined]
    return w3.eth.send_raw_transaction(raw).hex()


def _wait_receipt(w3: Web3, tx_hash: str,
                  timeout: int = WHAITE_TRANSACTION_PENDING * WHAITE_TRANSACTION_PENDING_COUNT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = w3.eth.get_transaction_receipt(tx_hash)
            if r is not None:
                return dict(r)
        except TransactionNotFound:
            pass
        except Exception:
            pass
        time.sleep(WHAITE_TRANSACTION_PENDING)
    raise TimeoutError(f"tx {tx_hash} not mined in {timeout}s")


def _balance_of(token_address: str, owner: str, proxy: Optional[str] = None) -> int:
    def _call(w3: Web3) -> int:
        token = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_MIN_ABI,
        )
        return int(token.functions.balanceOf(Web3.to_checksum_address(owner)).call())
    return _with_rpc_fallback(_call, proxy=proxy)


def _wait_balance_growth(token_address: str, owner: str, baseline: int,
                         *, timeout: int, poll: int,
                         proxy: Optional[str] = None) -> int:
    """Ждём, пока balanceOf(owner) > baseline. Возвращает новый баланс."""
    deadline = time.time() + timeout
    last = baseline
    while time.time() < deadline:
        try:
            cur = _balance_of(token_address, owner, proxy=proxy)
            last = cur
            if cur > baseline:
                return cur
        except Exception:
            pass
        time.sleep(poll)
    return last  # timeout → возвращаем последнее увиденное (вызывающий решит, что делать)


# --- claim --------------------------------------------------------------------

def _build_claim_tx(w3: Web3, *, prep: dict, sender: str) -> dict:
    contract_address = Web3.to_checksum_address(prep["contract_address"])
    earndrop_id = int(prep["earndrop_id"])
    claim_fee = int(prep["claim_fee"])
    signature_hex = prep["signature"]
    if isinstance(signature_hex, str) and signature_hex.startswith("0x"):
        signature_bytes = bytes.fromhex(signature_hex[2:])
    else:
        signature_bytes = bytes.fromhex(signature_hex)

    raw_params = prep["params"]
    params = []
    for p in raw_params:
        proof = p["merkle_proof"] or []
        proof_bytes = [bytes.fromhex(x[2:] if x.startswith("0x") else x) for x in proof]
        params.append((
            int(p["stage_index"]),
            int(p["leaf_index"]),
            Web3.to_checksum_address(p["account"]),
            int(p["amount"]),
            proof_bytes,
        ))

    contract = w3.eth.contract(address=contract_address, abi=EARNDROP_ABI)
    if len(params) == 1:
        fn = contract.functions.claimEarndrop(earndrop_id, params[0], signature_bytes)
    else:
        fn = contract.functions.multiClaimEarndrop(earndrop_id, params, signature_bytes)

    sender_cs = Web3.to_checksum_address(sender)
    nonce = w3.eth.get_transaction_count(sender_cs)
    # BSC: используем фактический gas_price ноды (сейчас ~0.05 gwei).
    # Бамп не нужен — claim не time-critical.
    gas_price = max(int(w3.eth.gas_price), 1)

    tx = fn.build_transaction({
        "from": sender_cs,
        "value": claim_fee,
        "nonce": nonce,
        "chainId": CHAIN_ID,
        "gasPrice": int(gas_price),
    })
    # Защита: накинем 20% на estimate
    try:
        est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(est * 1.2)
    except Exception:
        tx["gas"] = 600_000

    total_cost = claim_fee + tx["gas"] * int(gas_price)
    bal = w3.eth.get_balance(sender_cs)
    if bal < total_cost:
        raise RuntimeError(
            f"insufficient BNB: have {bal}, need >= {total_cost} "
            f"(claim_fee={claim_fee}, gas={tx['gas']}*{gas_price})"
        )

    return tx


def _do_onchain_claim(prep: dict, *, sender: str, private_key: str,
                      proxy: Optional[str]) -> str:
    """Отправляет claim-tx с RPC-fallback. Возвращает tx hash."""
    last_exc: Optional[Exception] = None
    for attempt in range(max(TX_SEND_ATTEMPTS, 1)):
        try:
            def _send(w3: Web3) -> str:
                tx = _build_claim_tx(w3, prep=prep, sender=sender)
                tx_hash = _send_signed(w3, tx, private_key)
                _wait_receipt(w3, tx_hash)
                return tx_hash
            return _with_rpc_fallback(_send, proxy=proxy)
        except Exception as e:
            last_exc = e
            time.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
    raise RuntimeError(f"on-chain claim failed: {last_exc}")


# --- withdraw -----------------------------------------------------------------

def _do_token_transfer(*, sender: str, private_key: str, to_address: str,
                       amount_raw: int, proxy: Optional[str]) -> str:
    """Простой ERC-20 transfer всей суммы. Возвращает tx hash."""
    def _send(w3: Web3) -> str:
        token = w3.eth.contract(
            address=Web3.to_checksum_address(SAHARA_TOKEN_ADDRESS),
            abi=ERC20_MIN_ABI,
        )
        sender_cs = Web3.to_checksum_address(sender)
        gas_price = max(int(w3.eth.gas_price), 1)
        nonce = w3.eth.get_transaction_count(sender_cs)
        tx = token.functions.transfer(
            Web3.to_checksum_address(to_address),
            int(amount_raw),
        ).build_transaction({
            "from": sender_cs,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "gasPrice": int(gas_price),
        })
        try:
            est = w3.eth.estimate_gas(tx)
            tx["gas"] = int(est * 1.2)
        except Exception:
            tx["gas"] = 120_000

        # Проверяем BNB на газ (без хардкодного флора — кошелёк одноразовый).
        # +10% буфер на колебания gas_price между estimate и send.
        need = int(tx["gas"] * int(gas_price) * 1.1)
        bnb = w3.eth.get_balance(sender_cs)
        if bnb < need:
            raise RuntimeError(
                f"insufficient BNB for token transfer: have {bnb}, need >= {need} "
                f"(gas={tx['gas']} * {gas_price} wei + 10%)"
            )

        tx_hash = _send_signed(w3, tx, private_key)
        _wait_receipt(w3, tx_hash)
        return tx_hash
    return _with_rpc_fallback(_send, proxy=proxy)


# --- main orchestrator --------------------------------------------------------

def run_one(record: Dict[str, Any], *, index: int, total: int,
            auto_withdraw_override: Optional[bool] = None) -> WalletResult:
    """Полный flow для одного кошелька.

    record: dict из modules.data_manager.load_data() (с полями
            name, private_key, proxy, reserve_proxy, evm_cex_address ...).
    auto_withdraw_override: если задан — переопределяет AUTO_WITHDRAW_TO_CEX.
    """
    name = (record.get('name') or '').strip()
    pk_raw = (record.get('private_key') or '').strip()
    if not pk_raw:
        return WalletResult(name=name, address='', status='failed',
                            errors=['empty private_key'])
    pk = pk_raw if pk_raw.startswith('0x') else f'0x{pk_raw}'

    try:
        addr = Account.from_key(pk).address
    except Exception as e:
        return WalletResult(name=name, address='', status='failed',
                            errors=[f'invalid private_key: {e}'])

    short = f"{addr[:6]}…{addr[-4:]}"
    proxy = parse_proxy(record.get('proxy')) or parse_proxy(record.get('reserve_proxy'))
    cex_address = (record.get('evm_cex_address') or '').strip()

    auto_withdraw = AUTO_WITHDRAW_TO_CEX if auto_withdraw_override is None else bool(auto_withdraw_override)

    res = WalletResult(name=name, address=addr)

    def _log(msg: str, level: str = 'info'):
        log_wallet_task(short, index, total, msg, level, account_name=name or '')

    # 1. sign_in -------------------------------------------------------------
    try:
        client = EarndropClient(private_key=pk, proxy=proxy)
        _log("🔑 SIWE sign-in…", 'info')
        client.sign_in()
    except EarndropError as e:
        msg = f"sign_in failed: {e}"
        res.status = 'failed'
        res.errors.append(msg)
        _log(f"❌ {msg}", 'error')
        return res

    # 2. info ----------------------------------------------------------------
    try:
        info = client.get_info()
    except EarndropError as e:
        res.status = 'failed'
        res.errors.append(f"info: {e}")
        _log(f"❌ info: {e}", 'error')
        return res

    eligible_raw = int(info.get('eligible_amount') or 0)
    claimed_raw = int(info.get('claimed_amount') or 0)
    total_raw = int(info.get('total_amount') or 0)
    res.eligible = eligible_raw
    res.already_claimed = claimed_raw

    if total_raw == 0 and eligible_raw == 0:
        res.status = 'not_eligible'
        _log("⏭ нет аллокации (not eligible)", 'warning')
    elif eligible_raw == 0 and claimed_raw > 0:
        res.status = 'already_claimed'
        _log(f"✅ уже заклеймлено: {claimed_raw / 1e18:.4f} SAHARA", 'success')
    elif eligible_raw == 0:
        # есть total, но нечего клеймить прямо сейчас (заблокировано/не разблокировано)
        res.status = 'not_eligible'
        stages_status = [s.get('status') for s in (info.get('stages') or [])]
        _log(f"⏭ нет available для claim сейчас (stages={stages_status})", 'warning')
    else:
        # 3. prepare_claim --------------------------------------------------
        try:
            _log(f"📋 prepare_claim (eligible={eligible_raw / 1e18:.4f} SAHARA)…", 'info')
            prep = client.prepare_claim()
        except EarndropError as e:
            res.status = 'failed'
            res.errors.append(f"prepare_claim: {e}")
            _log(f"❌ prepare_claim: {e}", 'error')
            return res

        time.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

        # 4. on-chain claim --------------------------------------------------
        try:
            baseline = _balance_of(SAHARA_TOKEN_ADDRESS, addr, proxy=proxy)
        except Exception:
            baseline = 0
        try:
            _log("📤 on-chain claimEarndrop…", 'info')
            tx_hash = _do_onchain_claim(prep, sender=addr, private_key=pk, proxy=proxy)
        except Exception as e:
            res.status = 'failed'
            res.errors.append(f"on-chain claim: {e}")
            _log(f"❌ on-chain claim: {e}", 'error')
            return res

        res.claim_tx = tx_hash
        _log(f"🧾 claim tx: 0x{tx_hash.lstrip('0x')}", 'info')

        # 5. ждём зачисление --------------------------------------------------
        new_balance = _wait_balance_growth(
            SAHARA_TOKEN_ADDRESS, addr, baseline,
            timeout=CLAIM_BALANCE_WAIT_TIMEOUT,
            poll=CLAIM_BALANCE_POLL_INTERVAL,
            proxy=proxy,
        )
        if new_balance <= baseline:
            res.status = 'failed'
            res.errors.append("balance did not grow after claim")
            _log("❌ balance не пришёл после claim", 'error')
            return res

        delta = new_balance - baseline
        res.claim_amount = delta
        res.status = 'claimed'
        _log(f"✅ зачислено {delta / 1e18:.4f} SAHARA на кошелёк", 'success')

        # 6. record_claim (best-effort) --------------------------------------
        try:
            client.record_claim(tx_hash=tx_hash, address=addr, amount=str(delta))
        except EarndropError as e:
            _log(f"⚠ record_claim: {e}", 'warning')

    # 7. withdraw ------------------------------------------------------------
    if not auto_withdraw:
        return res

    if res.status in ('not_eligible',) and res.already_claimed == 0:
        return res

    if not cex_address:
        _log("⏭ evm_cex_address пуст — авто-вывод пропущен", 'warning')
        return res
    try:
        Web3.to_checksum_address(cex_address)
    except Exception:
        _log(f"⚠ некорректный evm_cex_address={cex_address}", 'warning')
        return res

    try:
        wallet_bal = _balance_of(SAHARA_TOKEN_ADDRESS, addr, proxy=proxy)
    except Exception as e:
        res.errors.append(f"balanceOf before withdraw: {e}")
        _log(f"❌ balanceOf: {e}", 'error')
        return res

    if wallet_bal == 0:
        _log("⏭ на кошельке 0 SAHARA — выводить нечего", 'warning')
        return res

    try:
        cex_baseline = _balance_of(SAHARA_TOKEN_ADDRESS, cex_address, proxy=proxy)
    except Exception:
        cex_baseline = 0

    time.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))

    try:
        _log(f"💸 withdraw → {cex_address[:6]}…{cex_address[-4:]} "
             f"({wallet_bal / 1e18:.4f} SAHARA)", 'info')
        tx_hash = _do_token_transfer(
            sender=addr, private_key=pk,
            to_address=cex_address, amount_raw=wallet_bal,
            proxy=proxy,
        )
    except Exception as e:
        res.errors.append(f"withdraw transfer: {e}")
        _log(f"❌ withdraw: {e}", 'error')
        return res

    res.withdraw_tx = tx_hash
    res.withdraw_amount = wallet_bal
    _log(f"🧾 withdraw tx: 0x{tx_hash.lstrip('0x')}", 'info')

    new_cex = _wait_balance_growth(
        SAHARA_TOKEN_ADDRESS, cex_address, cex_baseline,
        timeout=WITHDRAW_BALANCE_WAIT_TIMEOUT,
        poll=WITHDRAW_BALANCE_POLL_INTERVAL,
        proxy=proxy,
    )
    res.cex_balance_after = new_cex
    if new_cex > cex_baseline:
        res.status = 'claimed+withdrawn'
        _log(f"✅ CEX получил +{(new_cex - cex_baseline) / 1e18:.4f} SAHARA "
             f"(итог: {new_cex / 1e18:.4f})", 'success')
    else:
        res.errors.append("cex balance did not grow within timeout")
        _log("⚠ CEX balance не подтвердился в таймаут (tx могла ещё не индексироваться)", 'warning')

    return res
