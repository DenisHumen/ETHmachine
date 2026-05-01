"""Python обёртка над node_helper/signer.js — подпись/отправка транзакций zkSync Lite.

Каждый вызов = subprocess `node signer.js <command> <json>`.
Из соображений безопасности приватник передаётся как аргумент CLI (виден в
process list только локально); альтернатива — stdin, но запуск долгий и так.

Если нужно сменить L1 RPC — выставите ZKSL_L1_RPC в env.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

HELPER_DIR = Path(__file__).resolve().parent / "node_helper"
SIGNER_JS = HELPER_DIR / "signer.js"
NODE_MODULES = HELPER_DIR / "node_modules"


class LiteSignerError(RuntimeError):
    pass


class LiteSigner:
    """Высокоуровневая обёртка над node-хелпером."""

    def __init__(self, *, node_path: str = "node", l1_rpc: Optional[str] = None,
                 timeout: int = 180) -> None:
        self.node_path = node_path
        self.l1_rpc = l1_rpc
        self.timeout = timeout
        if not SIGNER_JS.exists():
            raise LiteSignerError(f"signer.js not found: {SIGNER_JS}")
        if not NODE_MODULES.exists():
            raise LiteSignerError(
                f"node_modules не установлены. Запустите:\n"
                f"  cd \"{HELPER_DIR}\" && npm install"
            )

    # ───────── core ─────────

    def _run(self, command: str, payload: Dict[str, Any],
             timeout: Optional[int] = None) -> Dict[str, Any]:
        env = os.environ.copy()
        if self.l1_rpc:
            env["ZKSL_L1_RPC"] = self.l1_rpc
        try:
            proc = subprocess.run(
                [self.node_path, str(SIGNER_JS), command, json.dumps(payload)],
                cwd=str(HELPER_DIR),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout or self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise LiteSignerError(f"timeout ({exc.timeout}s) on {command}") from exc
        except FileNotFoundError as exc:
            raise LiteSignerError(
                f"node executable not found: {self.node_path!r}"
            ) from exc

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        # На stdout берём ПОСЛЕДНЮЮ JSON-строку (zksync.js может писать warning'и).
        last_line = stdout.split("\n")[-1].strip() if stdout else ""
        try:
            data = json.loads(last_line) if last_line else {}
        except json.JSONDecodeError as exc:
            raise LiteSignerError(
                f"bad JSON from helper ({command}): {exc} | "
                f"stdout={stdout[-300:]} stderr={stderr[-300:]}"
            ) from exc

        if proc.returncode != 0 or "error" in data:
            err = data.get("error") or stderr or f"exit {proc.returncode}"
            raise LiteSignerError(f"{command}: {err}")
        return data

    # ───────── commands ─────────

    def account_info(self, private_key: str) -> Dict[str, Any]:
        return self._run("account-info", {"privateKey": private_key}, timeout=60)

    def change_pubkey(self, private_key: str, fee_token: str = "ETH") -> Dict[str, Any]:
        return self._run(
            "change-pubkey",
            {"privateKey": private_key, "feeToken": fee_token},
            timeout=300,
        )

    def transfer(self, *, private_key: str, to: str, token: str, amount_raw: str,
                 fee_token: str = "ETH") -> Dict[str, Any]:
        return self._run(
            "transfer",
            {
                "privateKey": private_key,
                "to": to,
                "token": token,
                "amountRaw": str(amount_raw),
                "feeToken": fee_token,
            },
            timeout=180,
        )

    def withdraw(self, *, private_key: str, eth_address: str, token: str,
                 amount_raw: str, fee_token: str = "ETH",
                 fast_processing: bool = False) -> Dict[str, Any]:
        return self._run(
            "withdraw",
            {
                "privateKey": private_key,
                "ethAddress": eth_address,
                "token": token,
                "amountRaw": str(amount_raw),
                "feeToken": fee_token,
                "fastProcessing": bool(fast_processing),
            },
            timeout=180,
        )

    def tx_receipt(self, tx_hash: str) -> Dict[str, Any]:
        return self._run("tx-receipt", {"txHash": tx_hash}, timeout=60)

    def transfer_fee(self, *, to: str, token: str,
                     fee_token: Optional[str] = None) -> Dict[str, Any]:
        """Вернёт {feeRaw, feeHuman, decimals} для Transfer-tx."""
        return self._run(
            "transfer-fee",
            {"to": to, "token": token, "feeToken": fee_token or token},
            timeout=60,
        )

    def change_pubkey_fee(self, *, address: str,
                          fee_token: str = "ETH") -> Dict[str, Any]:
        return self._run(
            "change-pubkey-fee",
            {"address": address, "feeToken": fee_token},
            timeout=60,
        )

    def withdraw_fee(self, *, eth_address: str, fee_token: str,
                     fast_processing: bool = False) -> Dict[str, Any]:
        """Вернёт {feeRaw, feeHuman, decimals, txType} для Withdraw."""
        return self._run(
            "withdraw-fee",
            {"ethAddress": eth_address, "feeToken": fee_token,
             "fastProcessing": bool(fast_processing)},
            timeout=60,
        )


__all__ = ["LiteSigner", "LiteSignerError"]
