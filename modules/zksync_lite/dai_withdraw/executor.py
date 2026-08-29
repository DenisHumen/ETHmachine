"""DAI-withdraw executor: проводит withdraw Lite → L1 для каждой pending-задачи.

Стратегия per wallet:
  1. account_info; если !isActive → ChangePubKey (fee в DAI).
  2. Узнать реальный DAI-баланс на Lite, выбрать send_raw = balance - withdraw_fee_DAI.
  3. signer.withdraw(... fast_processing=False).  Lite-tx подтверждается мгновенно.
  4. Записать lite_tx_hash. L1-финализация занимает часы — отслеживаем в фоне.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from modules.simple_logger import logger
from modules.zksync_lite.dai_withdraw import database as dai_db
from modules.zksync_lite.swap.executor import _print_banner
from modules.zksync_lite.swap.lite_signer import LiteSigner, LiteSignerError

DAI_DECIMALS = 18
SCALE = Decimal(10) ** DAI_DECIMALS


class DaiWithdrawExecutor:
    def __init__(self, *, signer: Optional[LiteSigner] = None) -> None:
        self.signer = signer or LiteSigner()
        self.failures: List[Dict[str, Any]] = []

    # ───────── public ─────────

    def run_all(self) -> Dict[str, Any]:
        tasks = dai_db.list_pending()
        logger.info(f"[dai_exec] pending задач: {len(tasks)}")
        results: Dict[str, str] = {}
        for i, task in enumerate(tasks, 1):
            wallet = task["wallet_address"]
            print(f"\n[{i}/{len(tasks)}] {wallet}")
            try:
                self._run_task(task)
                results[wallet] = "ok"
            except Exception as exc:
                logger.exception(f"[dai_exec] ошибка по кошельку {wallet}")
                dai_db.update_task(
                    task["id"],
                    status=dai_db.STATUS_FAILED,
                    error_message=str(exc)[:500],
                )
                self.failures.append({
                    "wallet": wallet, "task_id": task["id"], "error": str(exc),
                })
                results[wallet] = f"error: {exc}"
                _print_banner("DAI WITHDRAW FAILED", [
                    f"wallet:  {wallet}",
                    f"amount:  {task['amount_human_planned']} DAI",
                    f"reason:  {exc}",
                ], symbol="!")
        return {"results": results, "stats": dai_db.get_statistics(),
                "failures": self.failures}

    # ───────── per-task ─────────

    def _run_task(self, task: Dict[str, Any]) -> None:
        wallet = task["wallet_address"]
        priv = task["private_key"]
        eth_address = task["eth_address"]
        # Весь трафик модуля идёт через node-хелпер (signer.js), а он прокси не
        # поддерживает. Раньше здесь строился ProxyPool и в лог писалось
        # «прокси: primary активна» — при том, что ни один запрос через неё не
        # шёл. Молчать об этом нельзя: для мультиаккаунта это незаявленная
        # привязка всех кошельков к одному IP.
        if (task.get("proxy") or "").strip() or (task.get("reserve_proxy") or "").strip():
            logger.warning(
                f"[{wallet}] прокси из CSV НЕ применяется: zkSync Lite работает "
                f"через node-хелпер без поддержки прокси — запросы уходят с "
                f"реального IP машины")
        else:
            logger.warning(f"[{wallet}] прокси не указана — идём напрямую")

        dai_db.increment_attempts(task["id"])

        # 1) account_info
        info = self.signer.account_info(priv)
        actual = (info.get("address") or "").lower()
        if actual != wallet.lower():
            raise RuntimeError(f"private_key выводит {actual}, ожидался {wallet}")

        balances = info.get("balances") or {}
        dai_raw = int(balances.get("DAI", "0") or "0")
        if dai_raw <= 0:
            dai_db.update_task(
                task["id"], status=dai_db.STATUS_SKIPPED,
                error_message="DAI=0 на Lite",
            )
            logger.info(f"[{wallet}] DAI=0 на Lite — пропуск")
            return

        # 2) ChangePubKey (если нужно). Fee в DAI.
        if not info.get("isActive"):
            try:
                cpk_fee = self.signer.change_pubkey_fee(
                    address=wallet, fee_token="DAI",
                )
                cpk_fee_raw = int(cpk_fee["feeRaw"])
            except LiteSignerError as e:
                raise RuntimeError(f"не удалось рассчитать ChangePubKey-fee: {e}")
            if dai_raw <= cpk_fee_raw:
                dai_db.update_task(
                    task["id"], status=dai_db.STATUS_SKIPPED,
                    error_message=(f"DAI {Decimal(dai_raw)/SCALE} ≤ "
                                   f"ChangePubKey fee {cpk_fee['feeHuman']}"),
                )
                logger.info(f"[{wallet}] DAI < ChangePubKey fee — пропуск")
                return
            logger.info(f"[{wallet}] ChangePubKey требуется (fee {cpk_fee['feeHuman']} DAI)")
            try:
                cpk = self.signer.change_pubkey(priv, fee_token="DAI")
                logger.info(f"[{wallet}] ChangePubKey tx: {cpk.get('txHash')}")
            except LiteSignerError as e:
                raise RuntimeError(f"ChangePubKey не удался: {e}")
            # Перечитываем баланс — fee списан
            info = self.signer.account_info(priv)
            balances = info.get("balances") or {}
            dai_raw = int(balances.get("DAI", "0") or "0")
            if dai_raw <= 0:
                dai_db.update_task(
                    task["id"], status=dai_db.STATUS_SKIPPED,
                    error_message="после ChangePubKey DAI=0",
                )
                return

        # 3) Withdraw fee в DAI
        try:
            wf = self.signer.withdraw_fee(
                eth_address=eth_address, fee_token="DAI",
            )
            fee_raw = int(wf["feeRaw"])
        except LiteSignerError as e:
            raise RuntimeError(f"не удалось рассчитать Withdraw-fee: {e}")

        # 4) drain под ноль: send = real - fee, capped по плану
        send_raw = dai_raw - fee_raw
        if send_raw <= 0:
            dai_db.update_task(
                task["id"], status=dai_db.STATUS_SKIPPED,
                error_message=(f"DAI {Decimal(dai_raw)/SCALE} ≤ "
                               f"Withdraw fee {wf['feeHuman']}"),
            )
            logger.info(f"[{wallet}] DAI ≤ withdraw fee — пропуск")
            return
        send_human = Decimal(send_raw) / SCALE

        dai_db.update_task(
            task["id"],
            amount_raw_planned=str(send_raw),
            amount_human_planned=str(send_human),
            fee_raw=str(fee_raw),
            fee_token="DAI",
        )
        logger.info(f"[{wallet}] Withdraw: {send_human} DAI → L1 {eth_address} "
                    f"(fee={wf['feeHuman']} DAI)")

        # 5) Сам withdraw
        try:
            tx = self.signer.withdraw(
                private_key=priv, eth_address=eth_address, token="DAI",
                amount_raw=str(send_raw), fee_token="DAI", fast_processing=False,
            )
        except LiteSignerError as e:
            dai_db.update_task(
                task["id"], status=dai_db.STATUS_LITE_TX_FAILED,
                error_message=str(e)[:500],
            )
            raise RuntimeError(f"withdraw failed: {e}")
        lite_hash = tx.get("txHash")
        dai_db.update_task(
            task["id"],
            status=dai_db.STATUS_LITE_TX_SENT,
            lite_tx_hash=lite_hash,
        )
        logger.info(f"[{wallet}] Lite withdraw tx: {lite_hash}")
        logger.info(f"[{wallet}] финализация в L1 займёт несколько часов "
                    f"(до 24+ ч). Проверяйте на etherscan: {eth_address}")

        # Лог остатка для аудита
        try:
            info_after = self.signer.account_info(priv)
            left = int((info_after.get("balances") or {}).get("DAI", "0") or "0")
            if left > 0:
                logger.info(f"[{wallet}] DAI остаток на Lite: "
                            f"{Decimal(left)/SCALE} ({left} wei)")
        except Exception:
            pass


__all__ = ["DaiWithdrawExecutor"]
