"""Планировщик задач DAI-withdraw из balance-БД."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

from modules.simple_logger import logger
from modules.zksync_lite import database as balance_db
from modules.zksync_lite.dai_withdraw import database as dai_db
from modules.zksync_lite.swap.planner import load_wallet_credentials

# Минимум DAI чтобы экономически имело смысл (fee ~0.2025 DAI ⇒ берём порог 1 DAI).
MIN_DAI_HUMAN = Decimal("1.0")


def _existing_keys() -> set:
    """Кошельки, по которым уже есть незавершённая или успешная задача."""
    keys = set()
    for r in dai_db.list_all():
        if r["status"] in (dai_db.STATUS_FAILED, dai_db.STATUS_LITE_TX_FAILED):
            continue
        keys.add(r["wallet_address"].lower())
    return keys


def plan_tasks(*, reset: bool = False, dry_run: bool = False,
               min_dai: Decimal = MIN_DAI_HUMAN) -> Dict[str, Any]:
    if reset and not dry_run:
        dai_db.reset_database()
    if not dry_run:
        dai_db.init_database()

    existing = _existing_keys() if not dry_run else set()
    creds = load_wallet_credentials()
    rows = balance_db.get_all_results()

    summary = {
        "created": 0,
        "skipped_no_priv": 0,
        "skipped_no_dai": 0,
        "skipped_below_min": 0,
        "skipped_existing": 0,
        "total_wallets": len(rows),
        "preview": [],
    }

    for row in rows:
        st = (row.get("status") or "").lower()
        if st not in ("completed", "success"):
            continue
        addr = (row.get("wallet_address") or "").lower()
        if not addr:
            continue
        balances = row.get("balances") or {}
        dai_info = None
        for sym, info in balances.items():
            if sym.upper() == "DAI":
                dai_info = info
                break
        if not dai_info:
            summary["skipped_no_dai"] += 1
            continue
        try:
            amount = Decimal(str(dai_info.get("amount", "0")))
        except Exception:
            amount = Decimal("0")
        decimals = int(dai_info.get("decimals", 18))
        if amount < min_dai:
            summary["skipped_below_min"] += 1
            continue
        if addr in existing:
            summary["skipped_existing"] += 1
            continue
        cred = creds.get(addr)
        if not cred:
            summary["skipped_no_priv"] += 1
            continue

        raw = int((amount * (Decimal(10) ** decimals)).to_integral_value())
        if dry_run:
            summary["preview"].append({"wallet": addr, "amount": str(amount)})
            continue
        dai_db.create_task(
            wallet_address=addr,
            private_key=cred["private_key"],
            proxy=cred.get("proxy") or None,
            reserve_proxy=cred.get("reserve_proxy") or None,
            eth_address=addr,  # отправляем сами себе на L1
            amount_raw_planned=str(raw),
            amount_human_planned=str(amount),
            decimals=decimals,
        )
        summary["created"] += 1

    logger.info(
        f"[dai_planner] создано: {summary['created']}, "
        f"без DAI: {summary['skipped_no_dai']}, "
        f"<min: {summary['skipped_below_min']}, "
        f"уже есть: {summary['skipped_existing']}, "
        f"без приватника: {summary['skipped_no_priv']}"
    )
    return summary


__all__ = ["plan_tasks", "MIN_DAI_HUMAN"]
