"""Phase-1: загрузка кошельков из data/data.csv, декод kava1 → 0x,
заполнение справочника kava_wallets и заглушек pending-задач.

Не выполняет on-chain действия — это легковесная подготовка.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from eth_account import Account

from modules.data_manager import load_data
from modules.eth.transfer_kava_to_cex import database as db
from modules.eth.transfer_kava_to_cex.kava_address import kava_bech32_to_evm


def build_records() -> List[Dict[str, Any]]:
    """Прочитать CSV, провалидировать PK и kava1-адрес. Вернуть unified-структуру.

    Каждая запись:
      {csv_index, wallet, private_key, proxy, reserve_proxy, name,
       cex_bech32, cex_evm, amount_spec, skip_reason}
    `skip_reason` = None если запись валидна, иначе текст ошибки.
    """
    out: List[Dict[str, Any]] = []
    seen_pk: set[str] = set()
    rows = load_data()
    for idx, r in enumerate(rows, 1):
        pk = (r.get("private_key") or "").strip()
        if not pk:
            continue
        pk_hex = pk if pk.startswith("0x") else f"0x{pk}"
        try:
            addr = Account.from_key(pk_hex).address
        except Exception as exc:
            out.append({
                "csv_index": idx, "wallet": None, "private_key": pk_hex,
                "proxy": None, "reserve_proxy": None,
                "name": r.get("name") or "",
                "cex_bech32": "", "cex_evm": "", "amount_spec": "",
                "skip_reason": f"bad private_key: {exc}",
            })
            continue
        if addr.lower() in seen_pk:
            continue
        seen_pk.add(addr.lower())

        cex_b = (r.get("evm_cex_address") or "").strip()
        if not cex_b:
            out.append({
                "csv_index": idx, "wallet": addr, "private_key": pk_hex,
                "proxy": (r.get("proxy") or "").strip() or None,
                "reserve_proxy": (r.get("reserve_proxy") or "").strip() or None,
                "name": r.get("name") or "",
                "cex_bech32": "", "cex_evm": "",
                "amount_spec": (r.get("transfer_amount") or "").strip(),
                "skip_reason": "empty evm_cex_address",
            })
            continue
        if not cex_b.startswith("kava1"):
            out.append({
                "csv_index": idx, "wallet": addr, "private_key": pk_hex,
                "proxy": (r.get("proxy") or "").strip() or None,
                "reserve_proxy": (r.get("reserve_proxy") or "").strip() or None,
                "name": r.get("name") or "",
                "cex_bech32": cex_b, "cex_evm": "",
                "amount_spec": (r.get("transfer_amount") or "").strip(),
                "skip_reason": f"not a kava1 address: {cex_b!r}",
            })
            continue
        try:
            cex_evm = kava_bech32_to_evm(cex_b)
        except Exception as exc:
            out.append({
                "csv_index": idx, "wallet": addr, "private_key": pk_hex,
                "proxy": (r.get("proxy") or "").strip() or None,
                "reserve_proxy": (r.get("reserve_proxy") or "").strip() or None,
                "name": r.get("name") or "",
                "cex_bech32": cex_b, "cex_evm": "",
                "amount_spec": (r.get("transfer_amount") or "").strip(),
                "skip_reason": f"bech32 decode failed: {exc}",
            })
            continue

        out.append({
            "csv_index": idx,
            "wallet": addr,
            "private_key": pk_hex,
            "proxy": (r.get("proxy") or "").strip() or None,
            "reserve_proxy": (r.get("reserve_proxy") or "").strip() or None,
            "name": (r.get("name") or "").strip(),
            "cex_bech32": cex_b,
            "cex_evm": cex_evm,
            "amount_spec": (r.get("transfer_amount") or "").strip() or "100-100%",
            "skip_reason": None,
        })
    return out


def plan_all() -> Dict[str, int]:
    """Заполнить kava_wallets для всех валидных записей. Возвращает счётчики."""
    db.init_database()
    records = build_records()
    counters = {"valid": 0, "skipped": 0, "total": len(records)}
    for rec in records:
        if rec["skip_reason"] or not rec["wallet"]:
            counters["skipped"] += 1
            continue
        wid = db.upsert_wallet(
            wallet_address=rec["wallet"],
            account_name=rec["name"],
            private_key=rec["private_key"],
            proxy=rec["proxy"],
            reserve_proxy=rec["reserve_proxy"],
            cex_address_bech32=rec["cex_bech32"],
            cex_address_evm=rec["cex_evm"],
            transfer_amount_spec=rec["amount_spec"],
            csv_index=rec["csv_index"],
        )
        # создаём pending-task если ещё нет
        db.get_or_create_task(wid)
        counters["valid"] += 1
    return counters


__all__ = ["build_records", "plan_all"]
