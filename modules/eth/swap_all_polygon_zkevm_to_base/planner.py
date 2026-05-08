"""Этап планирования: для каждого кошелька — снять баланс с OKLink,
классифицировать токены (свапаемые/нет), записать задачи в БД.

Поддерживаемые маршруты Layerswap (POLYGONZK_MAINNET → BASE_MAINNET):
  USDC → USDC, ETH → ETH (на 2026-05-07).
Всё остальное — статус skipped (с пометкой "no swap route").
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
from modules.eth.swap_all_polygon_zkevm_to_base.layerswap import SUPPORTED_PAIRS
from modules.eth.swap_all_polygon_zkevm_to_base import database as db

console = Console()

NETWORK_NAME = "🚀 Polygon zkEVM"
OKLINK_CHAIN = "polygon_zkevm"
ETH_BALANCE_DB = project_root / "db" / "eth_balance_tasks.db"

# ETH native is symbol-only (no contract). USDC on Polygon zkEVM:
USDC_POLYGONZK_CONTRACT = "0xa8ce8aee21bc2a48a5ef670afcc9274c7bbbc035"
ETH_DECIMALS = 18
USDC_DECIMALS = 6


def _load_cached_tokens(wallet: str) -> Optional[List[Dict[str, Any]]]:
    """Read previously fetched OKLink tokens from eth_balance_tasks.db."""
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
    """Read data.csv and produce per-wallet records (with private key)."""
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
    """Annotate each token with `supported`/`reason`/`token_symbol_canonical`.

    OKLink returns `value` already as a human float (decimals applied) and
    a `contract` field. For native ETH the contract is empty.
    """
    out = []
    for t in tokens or []:
        sym = (t.get("symbol") or "").upper()
        contract = (t.get("contract") or "").lower()
        is_risk = bool(t.get("is_risk"))
        # Skip risk-flagged tokens (scam airdrops)
        if is_risk:
            out.append({**t, "supported": False, "reason": "risk_flagged"})
            continue
        # Native ETH (no contract)
        if sym == "ETH" and not contract:
            out.append({**t, "supported": "ETH" in SUPPORTED_PAIRS,
                        "reason": ("ok" if "ETH" in SUPPORTED_PAIRS
                                   else "no_route")})
            continue
        # USDC by contract on Polygon zkEVM
        if contract == USDC_POLYGONZK_CONTRACT and sym == "USDC":
            out.append({**t, "supported": True, "reason": "ok"})
            continue
        out.append({**t, "supported": False,
                    "reason": "no_route" if sym in ("USDT", "DAI") else "unknown_token"})
    return out


def _decimals_for(token_symbol: str, contract: str) -> int:
    if token_symbol == "ETH" and not contract:
        return ETH_DECIMALS
    if contract == USDC_POLYGONZK_CONTRACT:
        return USDC_DECIMALS
    # Reasonable fallback; we don't actually swap "unknown" tokens, so the
    # value is only used for display.
    return 18


def plan_one_wallet(rec: Dict[str, Any], *, refresh: bool = True) -> Dict[str, Any]:
    """План для одного кошелька: тянем балансы, классифицируем, пишем задачи в БД.

    Возвращает {ok, error, total_usd, tokens_total, supported_count, name}.
    """
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


def fetch_balances_and_plan(records: List[Dict[str, Any]],
                            *, refresh: bool = True,
                            on_progress=None) -> Dict[str, Any]:
    """For each wallet: pull OKLink token list, write tasks to swap-all DB.

    Returns dict {wallet -> {ok, tokens, total_usd, supported_count, ...}}.
    """
    db.init_database()
    summary: Dict[str, Any] = {}
    fallback_proxies = [r["proxy"] for r in records if r.get("proxy")]

    for idx, rec in enumerate(records, 1):
        wallet = rec["wallet"]
        proxy = rec.get("proxy")
        reserve = rec.get("reserve_proxy")
        proxy_dict = _make_proxy_dict(proxy)

        if refresh:
            res = fetch_oklink_tokens(wallet, OKLINK_CHAIN, proxy_dict)
            if not res["ok"] and fallback_proxies:
                for p in [p for p in fallback_proxies if p != proxy][:2]:
                    time.sleep(0.5)
                    res = fetch_oklink_tokens(wallet, OKLINK_CHAIN,
                                              _make_proxy_dict(p))
                    if res["ok"]:
                        break
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

        summary[wallet] = {
            "ok": res["ok"],
            "error": res.get("error"),
            "total_usd": res.get("total_usd") or 0.0,
            "tokens_total": len(annotated),
            "supported_count": supported_count,
            "name": rec.get("name") or "",
        }
        if on_progress:
            try:
                on_progress(idx, len(records), wallet, summary[wallet])
            except Exception:
                pass

    return summary


__all__ = [
    "fetch_balances_and_plan", "_build_records",
    "NETWORK_NAME", "OKLINK_CHAIN",
    "USDC_POLYGONZK_CONTRACT",
]
