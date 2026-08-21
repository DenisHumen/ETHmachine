"""Executor: Rhino.fi swap-all для одного кошелька (zkSync Era → Base USDC).

В отличие от Layerswap (deposit_address pattern), Rhino.fi требует on-chain
вызов `depositWithId(token, amount, commitmentId)` на bridge-контракте, где
commitmentId = uint256.fromHex(quoteId). Поэтому пайплайн:
   approve → depositWithId → polling /bridge/history.
"""
from __future__ import annotations

import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from eth_account import Account
from web3 import Web3

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from modules.simple_logger import logger, log_wallet_task
from modules.eth.swap_all_zksync_era_to_base import database as db
from modules.eth.swap_all_zksync_era_to_base.rhinofi import (
    RhinoFiClient, RhinoFiError, SUPPORTED_PAIRS,
    TERMINAL_OK, TERMINAL_FAIL,
)

from config.modules.general_config import (
    NUM_THREADS as _CFG_NUM_THREADS,
    SLEEP_BETWEEN_ACTIONS as _CFG_SLEEP_BETWEEN_ACTIONS,
    DELAY_BETWEEN_ACCOUNTS as _CFG_DELAY_BETWEEN_ACCOUNTS,
    TX_SEND_ATTEMPTS as _CFG_TX_SEND_ATTEMPTS,
    RETRY_COUNT as _CFG_RETRY_COUNT,
)
try:
    from config.modules import cfg_swap_all_zksync_era_to_base as _cfg
except Exception:
    _cfg = None

NUM_THREADS = max(1, int(_CFG_NUM_THREADS))
SLEEP_BETWEEN_ACTIONS = list(_CFG_SLEEP_BETWEEN_ACTIONS)
DELAY_BETWEEN_ACCOUNTS = list(_CFG_DELAY_BETWEEN_ACCOUNTS)
TX_SEND_ATTEMPTS = max(1, int(_CFG_TX_SEND_ATTEMPTS))
RETRY_COUNT = max(1, int(_CFG_RETRY_COUNT))
ARRIVAL_TIMEOUT_SEC = int(getattr(_cfg, "ARRIVAL_TIMEOUT_SEC", 25 * 60))
RHINOFI_POLL_INTERVAL = int(getattr(_cfg, "RHINOFI_POLL_INTERVAL", 15))
TX_RECEIPT_TIMEOUT_SEC = int(getattr(_cfg, "TX_RECEIPT_TIMEOUT_SEC", 600))
RHINOFI_API_KEY = (getattr(_cfg, "RHINOFI_API_KEY", "") or "").strip() or None
RHINOFI_BASE_URL = getattr(_cfg, "RHINOFI_BASE_URL", "https://api.rhino.fi")

ZKSYNC_RPCS = [
    "https://mainnet.era.zksync.io",
    "https://zksync.drpc.org",
    "https://1rpc.io/zksync2-era",
]
BASE_RPCS = [
    "https://mainnet.base.org",
    "https://base-rpc.publicnode.com",
    "https://base.llamarpc.com",
]

RHINOFI_BRIDGE_CONTRACT = "0x1fa66e2b38d0cc496ec51f81c3e05e6a6708986f"
USDC_BASE_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

ERC20_ABI = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "allowance", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"},
                {"name": "value", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
]

BRIDGE_ABI = [
    {"name": "depositWithId", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "token", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "commitmentId", "type": "uint256"}],
     "outputs": []},
    {"name": "depositNativeWithId", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "commitmentId", "type": "uint256"}],
     "outputs": []},
]


def _sleep_action() -> None:
    lo, hi = (SLEEP_BETWEEN_ACTIONS + [SLEEP_BETWEEN_ACTIONS[0]])[:2]
    time.sleep(random.uniform(float(lo), float(hi)))


def _retry(fn, *, attempts: int, label: str, should_retry=None):
    last: Optional[Exception] = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if should_retry is not None and not should_retry(exc):
                raise
            logger.warning(f"{label}: попытка {i}/{attempts} → {exc}")
            if i < attempts:
                time.sleep(random.uniform(1.0, 2.5))
    raise last  # type: ignore[misc]


_INSUFFICIENT_GAS_MARKERS = (
    "insufficient funds for gas",
    "insufficient balance for transfer",
    "insufficient for gas",
    "native balance",
)


def _is_insufficient_gas_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _INSUFFICIENT_GAS_MARKERS)


def _format_proxies(proxy: Optional[str]) -> Optional[Dict[str, str]]:
    if not proxy:
        return None
    p = proxy.strip()
    if not p:
        return None
    if "://" not in p:
        p = "http://" + p
    return {"http": p, "https": p}


def _connect_web3(rpcs: List[str], proxies: Optional[Dict[str, str]]) -> Web3:
    last_exc = None
    for rpc in rpcs:
        try:
            kw = {"timeout": 30}
            if proxies:
                kw["proxies"] = proxies
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs=kw))
            _ = w3.eth.chain_id
            return w3
        except Exception as e:
            last_exc = e
    raise RuntimeError(f"failed to connect to any RPC: {last_exc}")


def _get_token_balance(w3: Web3, wallet: str, contract: str,
                       is_native: bool) -> int:
    addr = Web3.to_checksum_address(wallet)
    if is_native:
        return int(w3.eth.get_balance(addr))
    c = w3.eth.contract(address=Web3.to_checksum_address(contract),
                         abi=ERC20_ABI)
    return int(c.functions.balanceOf(addr).call())


def _build_legacy_fees(w3: Web3) -> Dict[str, int]:
    """zkSync Era — type-2 не везде поддерживается; legacy gasPrice проще."""
    rpc_price = int(w3.eth.gas_price)
    floor = w3.to_wei("0.025", "gwei")  # zkSync обычно ~0.025 gwei
    gas_price = max(rpc_price, floor) * 12 // 10
    return {"gasPrice": gas_price}


def _commitment_id(quote_id: str) -> int:
    """quoteId — 24-hex-char ObjectId, преобразуется в uint256 как BigInt('0x'+id)."""
    return int(quote_id, 16)


def _send_approve(*, w3: Web3, account, contract: str, spender: str,
                   amount: int) -> Optional[Dict[str, Any]]:
    """Approve бридж-контракту, если allowance < amount. Возвращает None если
    апрув не нужен."""
    addr = account.address
    c = w3.eth.contract(address=Web3.to_checksum_address(contract),
                         abi=ERC20_ABI)
    spender_cs = Web3.to_checksum_address(spender)
    cur = int(c.functions.allowance(addr, spender_cs).call())
    if cur >= amount:
        return None
    fees = _build_legacy_fees(w3)
    gas_price = int(fees["gasPrice"])
    nonce = w3.eth.get_transaction_count(addr)
    # Часть токенов (USDT-стиль) требует сначала zero approve, но USDC.e и
    # USDT на zkSync такого ограничения не имеют — отправляем сразу.
    tx = c.functions.approve(spender_cs, int(amount)).build_transaction({
        "from": addr, "nonce": nonce, "chainId": w3.eth.chain_id,
        "gasPrice": gas_price,
    })
    try:
        gas_est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(gas_est * 1.3)
    except Exception:
        tx["gas"] = 80_000
    signed = w3.eth.account.sign_transaction(tx, account.key)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction")
    h = w3.eth.send_raw_transaction(raw)
    return {"tx_hash": h.hex()}


def _send_deposit_with_id(*, w3: Web3, account, token_contract: str,
                           amount_raw: int, commitment_id: int,
                           bridge_contract: str = RHINOFI_BRIDGE_CONTRACT
                           ) -> Dict[str, Any]:
    addr = account.address
    bridge = w3.eth.contract(
        address=Web3.to_checksum_address(bridge_contract), abi=BRIDGE_ABI,
    )
    fees = _build_legacy_fees(w3)
    gas_price = int(fees["gasPrice"])
    nonce = w3.eth.get_transaction_count(addr)
    tx = bridge.functions.depositWithId(
        Web3.to_checksum_address(token_contract),
        int(amount_raw),
        int(commitment_id),
    ).build_transaction({
        "from": addr, "nonce": nonce, "chainId": w3.eth.chain_id,
        "gasPrice": gas_price,
    })
    try:
        gas_est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(gas_est * 1.3)
    except Exception:
        tx["gas"] = 250_000
    eth_bal = w3.eth.get_balance(addr)
    gas_cost = int(tx["gas"]) * gas_price
    if eth_bal < gas_cost:
        raise RuntimeError(
            f"native balance {eth_bal} insufficient for gas {gas_cost}")
    signed = w3.eth.account.sign_transaction(tx, account.key)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction")
    h = w3.eth.send_raw_transaction(raw)
    return {"tx_hash": h.hex(), "value": int(amount_raw)}


def _wait_receipt(w3: Web3, tx_hash: str, timeout: int = 600) -> Dict[str, Any]:
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
    return {"status": int(receipt.status), "block": int(receipt.blockNumber)}


class SwapAllExecutor:
    def __init__(self, *, rhinofi: Optional[RhinoFiClient] = None,
                 num_threads: Optional[int] = None) -> None:
        self.rhinofi = rhinofi or RhinoFiClient(api_key=RHINOFI_API_KEY,
                                                 base_url=RHINOFI_BASE_URL)
        self.num_threads = max(1, int(num_threads or NUM_THREADS))
        self._stagger_lock = threading.Lock()

    def _stagger(self) -> None:
        lo, hi = (DELAY_BETWEEN_ACCOUNTS + [DELAY_BETWEEN_ACCOUNTS[0]])[:2]
        with self._stagger_lock:
            time.sleep(random.uniform(float(lo), float(hi)))

    def run_all(self, wallets: Optional[List[str]] = None,
                on_progress=None) -> Dict[str, Any]:
        wallets = wallets or db.list_wallets_with_pending()
        total = len(wallets)
        logger.info(f"кошельков с pending: {total}; threads={self.num_threads}")
        results: Dict[str, str] = {}
        if total == 0:
            return {"results": results, "stats": db.get_statistics()}

        if self.num_threads <= 1:
            for i, wallet in enumerate(wallets, 1):
                try:
                    self.run_wallet(wallet, task_index=i, task_total=total)
                    results[wallet] = "ok"
                except Exception as exc:
                    log_wallet_task(wallet, i, total,
                                    f"unhandled error: {exc}", "error")
                    results[wallet] = f"error: {exc}"
                if on_progress:
                    try:
                        on_progress(i, total, wallet, results[wallet])
                    except Exception:
                        pass
            return {"results": results, "stats": db.get_statistics()}

        def _worker(idx: int, w: str) -> tuple[str, str]:
            self._stagger()
            try:
                self.run_wallet(w, task_index=idx, task_total=total)
                return w, "ok"
            except Exception as exc:
                log_wallet_task(w, idx, total,
                                f"unhandled error: {exc}", "error")
                return w, f"error: {exc}"

        done = 0
        with ThreadPoolExecutor(max_workers=self.num_threads,
                                 thread_name_prefix="swap_all_zk") as ex:
            futs = {ex.submit(_worker, i, w): w
                    for i, w in enumerate(wallets, 1)}
            for fut in as_completed(futs):
                wallet, status = fut.result()
                results[wallet] = status
                done += 1
                if on_progress:
                    try:
                        on_progress(done, total, wallet, status)
                    except Exception:
                        pass
        return {"results": results, "stats": db.get_statistics()}

    def run_wallet(self, wallet_address: str, *,
                    task_index: Optional[int] = None,
                    task_total: Optional[int] = None) -> None:
        tasks = db.list_pending_for_wallet(wallet_address)
        if not tasks:
            return
        priv = tasks[0]["private_key"]
        proxy = tasks[0].get("proxy")
        reserve_proxy = tasks[0].get("reserve_proxy")
        account_name = tasks[0].get("account_name") or ""
        proxies = _format_proxies(proxy) or _format_proxies(reserve_proxy)
        account = Account.from_key(priv)
        if account.address.lower() != wallet_address.lower():
            raise RuntimeError(
                f"private_key выдаёт {account.address}, ожидался {wallet_address}")
        try:
            w3_src = _retry(lambda: _connect_web3(ZKSYNC_RPCS, proxies),
                            attempts=RETRY_COUNT, label="connect zkSync[proxy]")
        except Exception:
            w3_src = _connect_web3(ZKSYNC_RPCS, None)
        try:
            w3_dst = _retry(lambda: _connect_web3(BASE_RPCS, proxies),
                            attempts=RETRY_COUNT, label="connect Base[proxy]")
        except Exception:
            w3_dst = _connect_web3(BASE_RPCS, None)
        # USDC сначала, потом USDT (USDC обычно крупнее).
        tasks_sorted = sorted(tasks,
                               key=lambda t: (0 if t["token"] == "USDC" else 1))
        ctx = {"index": task_index, "total": task_total, "name": account_name}
        for idx, task in enumerate(tasks_sorted):
            if idx > 0:
                _sleep_action()
            try:
                self._run_task(task, account, w3_src, w3_dst, proxies, ctx)
            except Exception as exc:
                self._wlog(wallet_address, ctx,
                           f"task {task['token']} failed: {exc}", "error")
                db.update_task(task["id"], status=db.STATUS_FAILED,
                                error_message=str(exc)[:500])

    @staticmethod
    def _wlog(wallet: str, ctx: Dict[str, Any], message: str,
              status: str = "info") -> None:
        idx = ctx.get("index")
        tot = ctx.get("total")
        name = ctx.get("name") or ""
        if idx is not None and tot is not None:
            log_wallet_task(wallet, idx, tot, message, status,
                            account_name=name)
        else:
            log_wallet_task(wallet, 1, 1, message, status, account_name=name)

    def _run_task(self, task: Dict[str, Any], account, w3_src: Web3,
                   w3_dst: Web3, proxies: Optional[Dict[str, str]],
                   ctx: Dict[str, Any]) -> None:
        token = task["token"]
        wallet = task["wallet_address"]
        contract = task["contract"]
        decimals = int(task["decimals"])
        scale = Decimal(10) ** decimals

        # Идемпотентность (AGENTS §14.3). Задача переживает Ctrl-C и таймаут
        # ожидания: `list_pending_for_wallet` вернёт её и в статусе tx_sent,
        # и в awaiting_arrival, и в failed. Если депозит уже улетел в мост —
        # деньги в пути, а on-chain баланс уже нулевой. Без этой проверки ветка
        # «zero on-chain balance» ниже затирала бы задачу терминальным skipped
        # (перевод становился невидимым), а пополненный кошелёк получал бы
        # второй depositWithId. Поэтому: есть tx — только дожидаемся прибытия.
        prior_tx = (task.get("src_tx_hash") or "").strip()
        prior_quote = (task.get("swap_id") or "").strip()
        if prior_tx:
            db.increment_attempts(task["id"])
            if not prior_quote:
                db.update_task(
                    task["id"], status=db.STATUS_FAILED,
                    error_message=("депозит отправлен, но quoteId не сохранён — "
                                   "проверьте перевод вручную")[:400])
                self._wlog(wallet, ctx,
                           f"⚠️  {token}: есть депозит {prior_tx[:14]}… без quoteId — "
                           f"повторно не отправляем, проверьте вручную", "error")
                return
            self._wlog(wallet, ctx,
                       f"↩️  {token}: депозит {prior_tx[:14]}… уже отправлен, "
                       f"возобновляем ожидание прибытия", "info")
            self._await_arrival(task, prior_quote, wallet, token,
                                 w3_dst, proxies, ctx)
            return

        if token not in SUPPORTED_PAIRS or not contract:
            db.update_task(task["id"], status=db.STATUS_SKIPPED,
                            error_message="rhino.fi route not supported")
            return

        db.increment_attempts(task["id"])

        # 1. Свежий on-chain баланс
        real_raw = _retry(
            lambda: _get_token_balance(w3_src, wallet, contract, False),
            attempts=RETRY_COUNT, label=f"balance {token}")
        if real_raw <= 0:
            db.update_task(task["id"], status=db.STATUS_SKIPPED,
                            raw_balance="0", human_balance="0",
                            error_message="zero on-chain balance")
            return

        send_raw = real_raw
        send_human = Decimal(send_raw) / scale

        # 2.0 Pre-check: достаточно ли native ETH на zkSync для approve+deposit.
        try:
            native_balance = int(
                w3_src.eth.get_balance(Web3.to_checksum_address(wallet)))
            gas_price_check = int(_build_legacy_fees(w3_src)["gasPrice"])
            # approve (~80k) + depositWithId (~470k оценки на zkSync) с запасом.
            required_native = 600_000 * gas_price_check
            if native_balance < required_native:
                db.update_task(
                    task["id"], status=db.STATUS_SKIPPED,
                    error_message=(f"insufficient native ETH for gas "
                                   f"(have={native_balance}, "
                                   f"need≈{required_native})")[:400],
                )
                self._wlog(
                    wallet, ctx,
                    f"⏭  {token} skipped: мало ETH на газ "
                    f"(have={native_balance} < need≈{required_native})",
                    "warning",
                )
                return
        except Exception:
            pass

        # 2.1 Baseline USDC на Base
        try:
            dst_before = _get_token_balance(w3_dst, wallet,
                                             USDC_BASE_CONTRACT, False)
        except Exception:
            dst_before = None
        db.update_task(task["id"],
                        dst_balance_before=(str(dst_before)
                                              if dst_before is not None else None))

        # 3. Quote + commit (создаёт у Rhino.fi commitmentId).
        try:
            swap = _retry(
                lambda: self.rhinofi.create_swap(
                    source_token=token, amount=send_human,
                    destination_address=wallet, depositor=wallet,
                    proxies=proxies),
                attempts=RETRY_COUNT, label="rhinofi.quote+commit",
                should_retry=lambda e: "NegativeReceiveAmount" not in str(e))
        except RhinoFiError as e:
            if "NegativeReceiveAmount" in str(e):
                db.update_task(
                    task["id"], status=db.STATUS_SKIPPED,
                    error_message=f"amount too small for rhino.fi: {e}"[:400],
                )
                self._wlog(
                    wallet, ctx,
                    f"⏭  {token} skipped: сумма меньше комиссии Rhino.fi "
                    f"({send_human})",
                    "warning",
                )
                return
            db.update_task(task["id"], status=db.STATUS_FAILED,
                            error_message=f"quote/commit: {e}"[:400])
            return
        quote_id = swap.get("swap_id")
        if not quote_id:
            db.update_task(task["id"], status=db.STATUS_FAILED,
                            error_message=f"missing quoteId: {swap}")
            return
        # Если Rhino округлил — доверяем payAmount.
        pay_amount = swap.get("pay_amount")
        if pay_amount:
            try:
                send_human = Decimal(str(pay_amount))
                send_raw = int((send_human * scale).to_integral_value())
            except Exception:
                pass

        db.update_task(task["id"], status=db.STATUS_SWAP_CREATED,
                        swap_id=quote_id,
                        deposit_address=RHINOFI_BRIDGE_CONTRACT,
                        sent_amount_raw=str(send_raw),
                        sent_amount_human=str(send_human))
        self._wlog(wallet, ctx,
                   f"💱 {token} quote {quote_id[:10]}… amount={send_human} "
                   f"→ Base ({swap.get('receive_amount')} USDC)", "info")

        # 4. Approve бридж-контракту (если нужно)
        try:
            ap = _retry(
                lambda: _send_approve(
                    w3=w3_src, account=account, contract=contract,
                    spender=RHINOFI_BRIDGE_CONTRACT, amount=send_raw),
                attempts=TX_SEND_ATTEMPTS, label="approve",
                should_retry=lambda e: not _is_insufficient_gas_error(e))
            if ap is not None:
                self._wlog(wallet, ctx,
                            f"🔓 approve tx {ap['tx_hash'][:14]}…", "info")
                rc = _wait_receipt(w3_src, ap["tx_hash"],
                                    timeout=TX_RECEIPT_TIMEOUT_SEC)
                if rc["status"] != 1:
                    raise RuntimeError(
                        f"approve reverted (block={rc['block']})")
        except Exception as e:
            if _is_insufficient_gas_error(e):
                db.update_task(
                    task["id"], status=db.STATUS_SKIPPED,
                    error_message=f"approve: insufficient gas: {e}"[:400],
                )
                self._wlog(wallet, ctx,
                           f"⏭  {token} skipped: мало ETH на approve",
                           "warning")
                return
            db.update_task(task["id"], status=db.STATUS_FAILED,
                            error_message=f"approve failed: {e}"[:400])
            return

        # 5. depositWithId
        try:
            commitment = _commitment_id(quote_id)
            tx_info = _retry(
                lambda: _send_deposit_with_id(
                    w3=w3_src, account=account, token_contract=contract,
                    amount_raw=send_raw, commitment_id=commitment),
                attempts=TX_SEND_ATTEMPTS, label="depositWithId",
                should_retry=lambda e: not _is_insufficient_gas_error(e))
        except Exception as e:
            if _is_insufficient_gas_error(e):
                db.update_task(
                    task["id"], status=db.STATUS_SKIPPED,
                    error_message=f"deposit: insufficient gas: {e}"[:400],
                )
                self._wlog(wallet, ctx,
                           f"⏭  {token} skipped: мало ETH на deposit",
                           "warning")
                return
            db.update_task(task["id"], status=db.STATUS_FAILED,
                            error_message=f"deposit tx failed: {e}"[:400])
            return
        tx_hash = tx_info["tx_hash"]
        db.update_task(task["id"], status=db.STATUS_TX_SENT,
                        src_tx_hash=tx_hash,
                        sent_amount_raw=str(tx_info["value"]),
                        sent_amount_human=str(Decimal(tx_info["value"]) / scale))
        self._wlog(wallet, ctx, f"📤 {token} deposit tx {tx_hash[:14]}…",
                   "info")

        # 6. Confirmation
        try:
            rc = _wait_receipt(w3_src, tx_hash, timeout=TX_RECEIPT_TIMEOUT_SEC)
            if rc["status"] != 1:
                db.update_task(task["id"], status=db.STATUS_FAILED,
                                error_message=f"deposit tx reverted (block={rc['block']})")
                return
        except Exception as e:
            self._wlog(wallet, ctx, f"receipt wait err: {e}", "warning")

        # 7. Polling Rhino.fi history
        self._await_arrival(task, quote_id, wallet, token, w3_dst, proxies, ctx)

    def _await_arrival(self, task: Dict[str, Any], quote_id: str, wallet: str,
                        token: str, w3_dst: Web3,
                        proxies: Optional[Dict[str, str]],
                        ctx: Dict[str, Any]) -> None:
        """Ожидание прибытия USDC на Base по уже созданному quoteId.

        Отдельный метод, чтобы повторный запуск мог дождаться ранее
        отправленного депозита, а не создавать новый (см. проверку
        идемпотентности в `_run_task`).
        """
        db.update_task(task["id"], status=db.STATUS_AWAITING)
        deadline = time.monotonic() + ARRIVAL_TIMEOUT_SEC
        last_status: Optional[str] = None
        while time.monotonic() < deadline:
            try:
                cur = self.rhinofi.get_swap(quote_id, proxies=proxies)
            except (RhinoFiError, requests.RequestException) as e:
                self._wlog(wallet, ctx, f"poll err: {e}", "warning")
                time.sleep(RHINOFI_POLL_INTERVAL)
                continue
            status = (cur.get("status") or "").upper()
            if status != last_status and status:
                self._wlog(wallet, ctx, f"swap status: {status}", "info")
                last_status = status
            if status in TERMINAL_FAIL:
                fr = cur.get("fail_reason") or ""
                db.update_task(
                    task["id"], status=db.STATUS_FAILED,
                    error_message=f"rhinofi terminal: {status} ({fr})"[:400],
                    dst_tx_hash=cur.get("destination_tx"),
                )
                return
            if status in TERMINAL_OK:
                dst_tx = cur.get("destination_tx")
                received = cur.get("destination_amount")
                try:
                    dst_after = _get_token_balance(
                        w3_dst, wallet, USDC_BASE_CONTRACT, False)
                except Exception:
                    dst_after = None
                db.update_task(
                    task["id"], status=db.STATUS_ARRIVED,
                    dst_tx_hash=dst_tx,
                    received_amount=(str(received)
                                       if received is not None else None),
                    dst_balance_after=(str(dst_after)
                                        if dst_after is not None else None),
                )
                self._wlog(wallet, ctx,
                           f"✅ {token} arrived on Base (received={received})",
                           "success")
                return
            time.sleep(RHINOFI_POLL_INTERVAL)
        db.update_task(task["id"], status=db.STATUS_FAILED,
                        error_message=f"timeout waiting for arrival "
                                      f"(last={last_status})")


__all__ = ["SwapAllExecutor", "ZKSYNC_RPCS", "BASE_RPCS",
           "USDC_BASE_CONTRACT", "RHINOFI_BRIDGE_CONTRACT"]
