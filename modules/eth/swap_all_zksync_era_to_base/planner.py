"""Этап планирования: для каждого кошелька — снять баланс с OKLink на zkSync Era,
классифицировать токены (USDC/USDT поддерживаются → USDC на Base), записать
задачи в БД. Native ETH не свапаем — он нужен на газ.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from eth_account import Account
from rich.console import Console

from modules.data_manager import load_data
from modules.eth.oklink_balance_checker import (
    fetch_oklink_tokens, _make_proxy_dict,
)
from modules.eth.swap_all_zksync_era_to_base.rhinofi import SUPPORTED_PAIRS
from modules.eth.swap_all_zksync_era_to_base import database as db

console = Console()

NETWORK_NAME = "🚀 zkSync Era"
OKLINK_CHAIN = "zksync"
ETH_BALANCE_DB = project_root / "db" / "eth_balance_tasks.db"

# Контракты на zkSync Era (значения из Rhino.fi configs, проверены 2026-05-08).
USDC_ZKSYNC_CONTRACT = "0x3355df6d4c9c3035724fd0e3914de96a5a83aaf4"  # USDC.e
USDT_ZKSYNC_CONTRACT = "0x493257fd37edb34451f62edf8d2a0c418852ba4c"
# Дополнительный «native» USDC от Circle на zkSync (если у кошелька он есть —
# не свапается этим модулем, помечается no_route).
USDC_NATIVE_ZKSYNC = "0x1d17cbcf0d6d143135ae902365d2e5e2a16538d4"
USDC_DECIMALS = 6
USDT_DECIMALS = 6
ETH_DECIMALS = 18

_SUPPORTED_CONTRACTS: Dict[str, str] = {
    USDC_ZKSYNC_CONTRACT: "USDC",
    USDT_ZKSYNC_CONTRACT: "USDT",
}


def _load_cached_tokens(wallet: str) -> Optional[List[Dict[str, Any]]]:
    if not ETH_BALANCE_DB.exists():
        return None
    try:
        con = sqlite3.connect(str(ETH_BALANCE_DB))
        con.row_factory = sqlite3.Row
        row = con.execute(
            """SELECT balance FROM eth_balance_tasks
               WHERE LOWER(wallet_address) = ?
                 AND network = ?
                 AND task_type = 'oklink_tokens'
                 AND status = 'completed'
               ORDER BY updated_at DESC LIMIT 1""",
            (wallet.lower(), NETWORK_NAME),
        ).fetchone()
        con.close()
        if not row:
            return None
        raw = row["balance"]
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _build_records() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for r in load_data():
        pk = (r.get("private_key") or "").strip()
        if not pk:
            continue
        pk_hex = pk if pk.startswith("0x") else f"0x{pk}"
        try:
            addr = Account.from_key(pk_hex).address
        except Exception:
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "wallet": addr,
            "private_key": pk_hex,
            "proxy": (r.get("proxy") or "").strip() or None,
            "reserve_proxy": (r.get("reserve_proxy") or "").strip() or None,
            "name": (r.get("name") or "").strip(),
        })
    return out


def _classify_tokens(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Только USDC.e и USDT по их контрактам — supported. Всё прочее skipped."""
    out = []
    for t in tokens or []:
        sym = (t.get("symbol") or "").upper()
        contract = (t.get("contract") or "").lower()
        is_risk = bool(t.get("is_risk"))
        if is_risk:
            out.append({**t, "supported": False, "reason": "risk_flagged"})
            continue
        if not contract and sym == "ETH":
            out.append({**t, "supported": False, "reason": "native_kept_for_gas"})
            continue
        if contract in _SUPPORTED_CONTRACTS:
            canonical = _SUPPORTED_CONTRACTS[contract]
            out.append({**t, "symbol": canonical,
                        "supported": canonical in SUPPORTED_PAIRS,
                        "reason": "ok"})
            continue
        out.append({**t, "supported": False, "reason": "no_route"})
    return out


def _decimals_for(token_symbol: str, contract: str) -> int:
    if not contract and token_symbol == "ETH":
        return ETH_DECIMALS
    if contract in (USDC_ZKSYNC_CONTRACT, USDT_ZKSYNC_CONTRACT,
                    USDC_NATIVE_ZKSYNC):
        return 6
    return 18


def plan_one_wallet(rec: Dict[str, Any], *, refresh: bool = True) -> Dict[str, Any]:
    db.init_database()
    wallet = rec["wallet"]
    proxy = rec.get("proxy")
    reserve = rec.get("reserve_proxy")
    proxy_dict = _make_proxy_dict(proxy)

    if refresh:
        res = fetch_oklink_tokens(wallet, OKLINK_CHAIN, proxy_dict)
        if not res["ok"] and reserve:
            res = fetch_oklink_tokens(wallet, OKLINK_CHAIN,
                                       _make_proxy_dict(reserve))
        if not res["ok"]:
            cached = _load_cached_tokens(wallet)
            if cached is not None:
                total_usd = sum(float(t.get("usd") or 0) for t in cached)
                res = {"ok": True, "tokens": cached,
                       "total_usd": total_usd,
                       "error": f"oklink_failed→cache ({res.get('error')})"}
    else:
        cached = _load_cached_tokens(wallet) or []
        total_usd = sum(float(t.get("usd") or 0) for t in cached)
        res = {"ok": True, "tokens": cached,
               "total_usd": total_usd, "error": None}

    annotated = _classify_tokens(res.get("tokens") or [])
    supported_count = 0
    for tok in annotated:
        sym = (tok.get("symbol") or "").upper()
        contract = (tok.get("contract") or "").lower()
        decimals = _decimals_for(sym, contract)
        human_val = Decimal(str(tok.get("value") or "0"))
        raw = int((human_val * (Decimal(10) ** decimals)).to_integral_value())
        extra = {
            "name": tok.get("name") or "",
            "price": tok.get("price") or 0.0,
            "reason": tok.get("reason"),
            "is_risk": bool(tok.get("is_risk")),
        }
        db.upsert_task(
            wallet_address=wallet,
            account_name=rec.get("name") or "",
            private_key=rec["private_key"],
            proxy=proxy, reserve_proxy=reserve,
            token=sym or "UNKNOWN",
            contract=contract,
            decimals=decimals,
            raw_balance=str(raw),
            human_balance=str(human_val),
            usd_value=str(tok.get("usd") or "0"),
            supported=bool(tok.get("supported")),
            extra=extra,
        )
        if tok.get("supported"):
            supported_count += 1

    return {
        "ok": res["ok"],
        "error": res.get("error"),
        "total_usd": res.get("total_usd") or 0.0,
        "tokens_total": len(annotated),
        "supported_count": supported_count,
        "name": rec.get("name") or "",
    }


__all__ = [
    "plan_one_wallet", "_build_records",
    "NETWORK_NAME", "OKLINK_CHAIN",
    "USDC_ZKSYNC_CONTRACT", "USDT_ZKSYNC_CONTRACT",
]
