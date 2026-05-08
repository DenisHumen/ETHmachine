"""Executor: исполняет задачи дрейнера по одному кошельку."""
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
from modules.eth.drainer_polygonzk_to_base import database as db
from modules.eth.drainer_polygonzk_to_base.layerswap import (
    LayerswapClient, LayerswapError, SUPPORTED_PAIRS,
)

from config.modules.cfg_base import (
    NUM_THREADS as _CFG_NUM_THREADS,
    SLEEP_BETWEEN_ACTIONS as _CFG_SLEEP_BETWEEN_ACTIONS,
    DELAY_BETWEEN_ACCOUNTS as _CFG_DELAY_BETWEEN_ACCOUNTS,
    TX_SEND_ATTEMPTS as _CFG_TX_SEND_ATTEMPTS,
    RETRY_COUNT as _CFG_RETRY_COUNT,
)
try:
    from config.modules import cfg_drainer_polygonzk_to_base as _cfg
except Exception:
    _cfg = None
NUM_THREADS = max(1, int(_CFG_NUM_THREADS))
SLEEP_BETWEEN_ACTIONS = list(_CFG_SLEEP_BETWEEN_ACTIONS)
DELAY_BETWEEN_ACCOUNTS = list(_CFG_DELAY_BETWEEN_ACCOUNTS)
TX_SEND_ATTEMPTS = max(1, int(_CFG_TX_SEND_ATTEMPTS))
RETRY_COUNT = max(1, int(_CFG_RETRY_COUNT))
NATIVE_GAS_RESERVE_ETH = float(getattr(_cfg, "NATIVE_GAS_RESERVE_ETH", 0.0002))
ARRIVAL_TIMEOUT_SEC = int(getattr(_cfg, "ARRIVAL_TIMEOUT_SEC", 25 * 60))
LAYERSWAP_POLL_INTERVAL = int(getattr(_cfg, "LAYERSWAP_POLL_INTERVAL", 15))
TX_RECEIPT_TIMEOUT_SEC = int(getattr(_cfg, "TX_RECEIPT_TIMEOUT_SEC", 600))
LAYERSWAP_API_KEY = (getattr(_cfg, "LAYERSWAP_API_KEY", "") or "").strip() or None

POLYGONZK_RPCS = [
    "https://zkevm-rpc.com",
    "https://polygon-zkevm.drpc.org",
]
BASE_RPCS = [
    "https://mainnet.base.org",
    "https://base-rpc.publicnode.com",
    "https://base.llamarpc.com",
]
USDC_BASE_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_BASE_DECIMALS = 6

# ABI fragments
ERC20_ABI = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "transfer", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
]

ARRIVAL_TIMEOUT_SEC = ARRIVAL_TIMEOUT_SEC
LAYERSWAP_POLL_INTERVAL = LAYERSWAP_POLL_INTERVAL


def _sleep_action() -> None:
    lo, hi = (SLEEP_BETWEEN_ACTIONS + [SLEEP_BETWEEN_ACTIONS[0]])[:2]
    time.sleep(random.uniform(float(lo), float(hi)))


def _retry(fn, *, attempts: int, label: str):
    last: Optional[Exception] = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last = exc
            logger.warning(f"{label}: попытка {i}/{attempts} → {exc}")
            if i < attempts:
                time.sleep(random.uniform(1.0, 2.5))
    raise last  # type: ignore[misc]



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
    """Try RPCs in priority order; validate with a real eth_chainId call."""
    last_exc = None
    for rpc in rpcs:
        try:
            w3 = Web3(Web3.HTTPProvider(
                rpc, request_kwargs={"proxies": proxies, "timeout": 30}
                if proxies else {"timeout": 30}))
            # is_connected may swallow 404; force a real call.
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
    """Polygon zkEVM accepts только legacy-транзакции (type 0)."""
    gas_price = int(w3.eth.gas_price)
    return {"gasPrice": max(gas_price, w3.to_wei(1, "gwei"))}


def _estimate_native_gas_units(w3: Web3, from_addr: str,
                                to_addr: Optional[str] = None) -> int:
    """Оценить gas units для native-transfer.

    EOA→EOA = 21000. Если deposit_addr — контракт (Layerswap иногда так),
    estimate_gas вернёт фактическое значение. Если узнать заранее
    нельзя — берём 21000 + 5000 запас.
    """
    target = Web3.to_checksum_address(to_addr or from_addr)
    try:
        return int(w3.eth.estimate_gas({
            "from": Web3.to_checksum_address(from_addr),
            "to": target,
            "value": 0,
        }))
    except Exception:
        return 21_000


def _native_gas_reserve(w3: Web3, *, est_gas: Optional[int] = None) -> int:
    """Точный резерв native-ETH для одной transfer-tx (drain-to-zero).

    Формула: reserve = gas_price × est_gas × 1.4
       1.3 = markup, который применяет _send_native_drain к gas_limit
       1.05 ≈ safety на флуктуации gas_price между планом и отправкой
    Используем тот же `gas_price`, что и `_build_legacy_fees`, чтобы
    резерв точно совпадал с реальной стоимостью tx — leftover после
    дрейна обычно <0.00001 ETH (≪ цента).
    """
    gas_price = int(_build_legacy_fees(w3)["gasPrice"])
    units = int(est_gas or 21_000)
    return int(gas_price * units * 14 // 10)


def _send_native_drain(*, w3: Web3, account, deposit_addr: str,
                        amount_planned_raw: int) -> Dict[str, Any]:
    """Отправить ровно `amount_planned_raw` wei на deposit_addr (для ETH)."""
    addr = account.address
    fees = _build_legacy_fees(w3)
    gas_price = int(fees["gasPrice"])
    nonce = w3.eth.get_transaction_count(addr)
    tx = {
        "to": Web3.to_checksum_address(deposit_addr),
        "from": addr, "value": int(amount_planned_raw),
        "nonce": nonce, "chainId": w3.eth.chain_id,
        "gasPrice": gas_price,
    }
    gas_est = w3.eth.estimate_gas(tx)
    tx["gas"] = int(gas_est * 1.3)
    # Проверка что хватает на gas + value; иначе урезаем value
    bal = w3.eth.get_balance(addr)
    cost = tx["gas"] * gas_price + int(amount_planned_raw)
    if bal < cost:
        gas_buffer = int(tx["gas"] * gas_price * 1.1)
        if bal <= gas_buffer:
            raise RuntimeError(
                f"native balance {bal} below gas buffer {gas_buffer}")
        tx["value"] = bal - gas_buffer
    signed = w3.eth.account.sign_transaction(tx, account.key)
    raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction")
    h = w3.eth.send_raw_transaction(raw)
    return {"tx_hash": h.hex(), "value": int(tx["value"])}


def _send_erc20(*, w3: Web3, account, contract: str, deposit_addr: str,
                 amount_raw: int) -> Dict[str, Any]:
    addr = account.address
    c = w3.eth.contract(address=Web3.to_checksum_address(contract),
                         abi=ERC20_ABI)
    fees = _build_legacy_fees(w3)
    gas_price = int(fees["gasPrice"])
    nonce = w3.eth.get_transaction_count(addr)
    tx = c.functions.transfer(
        Web3.to_checksum_address(deposit_addr), int(amount_raw)
    ).build_transaction({
        "from": addr, "nonce": nonce, "chainId": w3.eth.chain_id,
        "gasPrice": gas_price,
    })
    try:
        gas_est = w3.eth.estimate_gas(tx)
        tx["gas"] = int(gas_est * 1.3)
    except Exception:
        tx["gas"] = 120_000
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


class DrainerExecutor:
    def __init__(self, *, layerswap: Optional[LayerswapClient] = None,
                 num_threads: Optional[int] = None) -> None:
        self.layerswap = layerswap or LayerswapClient(api_key=LAYERSWAP_API_KEY)
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
                                 thread_name_prefix="drainer") as ex:
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
            w3_src = _retry(lambda: _connect_web3(POLYGONZK_RPCS, proxies),
                            attempts=RETRY_COUNT, label="connect zkEVM[proxy]")
        except Exception:
            w3_src = _connect_web3(POLYGONZK_RPCS, None)
        try:
            w3_dst = _retry(lambda: _connect_web3(BASE_RPCS, proxies),
                            attempts=RETRY_COUNT, label="connect Base[proxy]")
        except Exception:
            w3_dst = _connect_web3(BASE_RPCS, None)
        # Сортируем: сначала USDC (главная цель), потом ETH (как gas-source).
        tasks_sorted = sorted(tasks, key=lambda t: (0 if t["token"] == "USDC" else 1))
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
        is_native = (token == "ETH" and not contract)

        if token not in SUPPORTED_PAIRS:
            db.update_task(task["id"], status=db.STATUS_SKIPPED,
                            error_message="layerswap route not supported")
            return

        db.increment_attempts(task["id"])

        # 1. Свежий on-chain баланс (OKLink-данные могли устареть)
        real_raw = _retry(
            lambda: _get_token_balance(w3_src, wallet,
                                        contract or "0x0", is_native),
            attempts=RETRY_COUNT, label=f"balance {token}")
        if real_raw <= 0:
            db.update_task(task["id"], status=db.STATUS_SKIPPED,
                            raw_balance="0", human_balance="0",
                            error_message="zero on-chain balance")
            return

        # 2. Лимиты Layerswap
        try:
            lim = _retry(lambda: self.layerswap.limits(token, proxies=proxies),
                         attempts=RETRY_COUNT, label="layerswap.limits")
        except LayerswapError as e:
            db.update_task(task["id"], status=db.STATUS_FAILED,
                            error_message=f"limits failed: {e}"[:300])
            return
        min_raw = int((lim["min_amount"] * scale).to_integral_value())
        max_raw = int((lim["max_amount"] * scale).to_integral_value())

        # 3. Расчёт суммы (для native — точная оценка газа из RPC, чтобы
        # выгрести максимум-под-ноль; для ERC-20 — весь баланс)
        if is_native:
            est_units = _estimate_native_gas_units(w3_src, account.address)
            gas_reserve = _native_gas_reserve(w3_src, est_gas=est_units)
            send_raw = real_raw - gas_reserve
        else:
            send_raw = real_raw

        if send_raw <= 0:
            db.update_task(task["id"], status=db.STATUS_SKIPPED,
                            error_message="balance below gas reserve")
            return
        if max_raw and send_raw > max_raw:
            send_raw = max_raw
        if min_raw and send_raw < min_raw:
            human_min = lim["min_amount"]
            db.update_task(
                task["id"], status=db.STATUS_SKIPPED,
                raw_balance=str(real_raw),
                human_balance=str(Decimal(real_raw) / scale),
                error_message=f"amount {Decimal(send_raw)/scale} < layerswap min {human_min}",
            )
            return

        send_human = Decimal(send_raw) / scale

        # 4. Baseline баланс на Base (USDC.contract or native ETH)
        try:
            if token == "USDC":
                dst_before = _get_token_balance(
                    w3_dst, wallet, USDC_BASE_CONTRACT, False)
            else:
                dst_before = _get_token_balance(w3_dst, wallet, "0x0", True)
        except Exception:
            dst_before = None
        db.update_task(task["id"],
                        dst_balance_before=(str(dst_before) if dst_before is not None else None))

        # 5. Создание свапа
        try:
            swap = _retry(
                lambda: self.layerswap.create_swap(
                    source_token=token, amount=send_human,
                    destination_address=wallet, proxies=proxies),
                attempts=RETRY_COUNT, label="layerswap.create_swap")
        except LayerswapError as e:
            db.update_task(task["id"], status=db.STATUS_FAILED,
                            error_message=f"create_swap: {e}"[:400])
            return
        swap_id = swap.get("swap_id")
        deposit = swap.get("deposit_address")
        if not swap_id or not deposit:
            db.update_task(task["id"], status=db.STATUS_FAILED,
                            error_message=f"missing swap_id/deposit: {swap}")
            return
        # Если Layerswap округлил deposit_amount — используем его.
        deposit_amount = swap.get("deposit_amount")
        if deposit_amount:
            try:
                planned = Decimal(str(deposit_amount))
                send_raw = int((planned * scale).to_integral_value())
                send_human = planned
            except Exception:
                pass

        db.update_task(task["id"], status=db.STATUS_SWAP_CREATED,
                        swap_id=swap_id, deposit_address=deposit,
                        sent_amount_raw=str(send_raw),
                        sent_amount_human=str(send_human))
        self._wlog(wallet, ctx,
                   f"💱 {token} swap {swap_id[:10]}… amount={send_human}",
                   "info")

        # 6. Отправка on-chain транзакции (TX_SEND_ATTEMPTS)
        try:
            if is_native:
                tx_info = _retry(
                    lambda: _send_native_drain(
                        w3=w3_src, account=account, deposit_addr=deposit,
                        amount_planned_raw=send_raw),
                    attempts=TX_SEND_ATTEMPTS, label="send native")
            else:
                tx_info = _retry(
                    lambda: _send_erc20(
                        w3=w3_src, account=account, contract=contract,
                        deposit_addr=deposit, amount_raw=send_raw),
                    attempts=TX_SEND_ATTEMPTS, label="send erc20")
        except Exception as e:
            db.update_task(task["id"], status=db.STATUS_FAILED,
                            error_message=f"tx send failed: {e}"[:400])
            return
        tx_hash = tx_info["tx_hash"]
        db.update_task(task["id"], status=db.STATUS_TX_SENT,
                        src_tx_hash=tx_hash,
                        sent_amount_raw=str(tx_info["value"]),
                        sent_amount_human=str(Decimal(tx_info["value"]) / scale))
        self._wlog(wallet, ctx, f"📤 {token} src tx {tx_hash[:14]}…", "info")

        # 7. Ждём confirmation
        try:
            rc = _wait_receipt(w3_src, tx_hash, timeout=TX_RECEIPT_TIMEOUT_SEC)
            if rc["status"] != 1:
                db.update_task(task["id"], status=db.STATUS_FAILED,
                                error_message=f"src tx reverted (block={rc['block']})")
                return
        except Exception as e:
            self._wlog(wallet, ctx, f"receipt wait err: {e}", "warning")

        # 8. Polling Layerswap до COMPLETED
        db.update_task(task["id"], status=db.STATUS_AWAITING)
        deadline = time.monotonic() + ARRIVAL_TIMEOUT_SEC
        last_status: Optional[str] = None
        dst_tx: Optional[str] = None
        while time.monotonic() < deadline:
            try:
                cur = self.layerswap.get_swap(swap_id, proxies=proxies)
            except (LayerswapError, requests.RequestException) as e:
                self._wlog(wallet, ctx, f"poll err: {e}", "warning")
                time.sleep(LAYERSWAP_POLL_INTERVAL)
                continue
            status = (cur.get("status") or "").lower()
            if status != last_status and status:
                self._wlog(wallet, ctx, f"swap status: {status}", "info")
                last_status = status
            if status in ("failed", "cancelled", "expired"):
                fr = cur.get("fail_reason") or ""
                db.update_task(
                    task["id"], status=db.STATUS_FAILED,
                    error_message=f"layerswap terminal: {status} ({fr})"[:400],
                    dst_tx_hash=cur.get("destination_tx"),
                )
                return
            if status == "completed":
                dst_tx = cur.get("destination_tx")
                received = cur.get("destination_amount")
                # Проверим Base баланс
                try:
                    if token == "USDC":
                        dst_after = _get_token_balance(
                            w3_dst, wallet, USDC_BASE_CONTRACT, False)
                    else:
                        dst_after = _get_token_balance(
                            w3_dst, wallet, "0x0", True)
                except Exception:
                    dst_after = None
                db.update_task(
                    task["id"], status=db.STATUS_ARRIVED,
                    dst_tx_hash=dst_tx,
                    received_amount=str(received) if received is not None else None,
                    dst_balance_after=(str(dst_after)
                                       if dst_after is not None else None),
                )
                self._wlog(wallet, ctx,
                           f"✅ {token} arrived on Base (received={received})",
                           "success")
                return
            time.sleep(LAYERSWAP_POLL_INTERVAL)
        db.update_task(task["id"], status=db.STATUS_FAILED,
                        error_message=f"timeout waiting for arrival "
                                      f"(last={last_status})")


__all__ = ["DrainerExecutor", "POLYGONZK_RPCS", "BASE_RPCS",
           "USDC_BASE_CONTRACT"]
