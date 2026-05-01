"""Планировщик задач свопа: читает balance-БД, формирует записи swap_tasks.

Порядок исполнения по требованию пользователя — стейблы первыми, ETH последним:
  1. DAI   — Layerswap не поддерживает как source, задача сразу помечается skipped.
  2. USDT  → ZKSYNCERA_MAINNET/USDT  (Layerswap)
  3. USDC  → ZKSYNCERA_MAINNET/USDC.e (Layerswap; роут USDC→USDT недоступен
           в режиме use_deposit_address)
  4. ETH   → ZKSYNCERA_MAINNET/ETH    (Layerswap)
"""
from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.simple_logger import logger
from modules.zksync_lite import database as balance_db
from modules.zksync_lite.swap import swap_database as swap_db
from modules.zksync_lite.swap.layerswap_client import (
    LayerswapClient, LayerswapError, SUPPORTED_PAIRS,
)

DATA_CSV = Path(__file__).resolve().parents[3] / "data" / "data.csv"

# Минимальные «экономические» пороги (~$0.15). Если Layerswap min выше — берётся он.
THRESHOLDS_HUMAN: Dict[str, Decimal] = {
    "ETH": Decimal("0.00005"),    # ~$0.15
    "USDT": Decimal("0.15"),
    "USDC": Decimal("0.15"),
    "DAI": Decimal("0.15"),
}

# Резерв ETH на каждую Lite-tx (transfer/withdraw/changePubKey).
# На практике комиссии ~0.00001—0.00003 ETH; берём верхнюю границу.
ETH_GAS_RESERVE = Decimal("0.00003")

# Маршруты: всё идёт через Layerswap, DAI не поддерживается.
ROUTES: Dict[str, str] = {
    "ETH": "layerswap",
    "USDT": "layerswap",
    "USDC": "layerswap",
    "DAI": "unsupported",
}

# Меньше priority ⇒ раньше исполняем.
# Порядок по требованию: DAI → USDT → USDC → ETH (последним).
PRIORITIES: Dict[str, int] = {
    "DAI": 10,
    "USDT": 20,
    "USDC": 30,
    "ETH": 99,
}


# ────────── Layerswap limits (динамика) ──────────

# Кеш лимитов на время одного планирования.
_LIMITS_CACHE: Dict[str, Optional[Dict[str, Decimal]]] = {}


def _get_layerswap_limits(token: str) -> Optional[Dict[str, Decimal]]:
    """Возвращает {min_amount, max_amount, min_usd, max_usd} либо None при ошибке."""
    tok = token.upper()
    if tok in _LIMITS_CACHE:
        return _LIMITS_CACHE[tok]
    if tok not in SUPPORTED_PAIRS:
        _LIMITS_CACHE[tok] = None
        return None
    try:
        cli = LayerswapClient()
        lim = cli.limits(tok)
        _LIMITS_CACHE[tok] = lim
        logger.info(f"[planner] {tok} limits: min={lim['min_amount']} "
                    f"(${lim['min_usd']}), max={lim['max_amount']} (${lim['max_usd']})")
        return lim
    except (LayerswapError, Exception) as exc:
        logger.warning(f"[planner] limits {tok} недоступны ({exc}) — "
                       f"fallback на статический порог")
        _LIMITS_CACHE[tok] = None
        return None


def _effective_min(token: str) -> Decimal:
    """Финальный минимум: max(пользовательский порог, Layerswap min)."""
    static = THRESHOLDS_HUMAN[token]
    lim = _get_layerswap_limits(token)
    if not lim or lim["min_amount"] <= 0:
        return static
    return max(static, lim["min_amount"])


def _effective_max(token: str) -> Optional[Decimal]:
    """Layerswap max или None, если лимиты недоступны (тогда не кэпим)."""
    lim = _get_layerswap_limits(token)
    if not lim or lim["max_amount"] <= 0:
        return None
    return lim["max_amount"]



def load_wallet_credentials(csv_path: Path = DATA_CSV) -> Dict[str, Dict[str, str]]:
    """Читает data.csv → {wallet_address_lower: {'private_key':..., 'proxy':...}}.

    Если адрес не указан в CSV, его выводим из приватника.
    """
    from eth_account import Account

    out: Dict[str, Dict[str, str]] = {}
    if not csv_path.exists():
        return out
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pk = (row.get("private_key") or "").strip()
            if not pk:
                continue
            if not pk.startswith("0x"):
                pk = "0x" + pk
            address = (row.get("wallet_address") or "").strip().lower()
            if not address:
                try:
                    address = Account.from_key(pk).address.lower()
                except Exception:
                    continue
            proxy = (row.get("proxy") or "").strip() or None
            reserve = (row.get("reserve_proxy") or "").strip() or None
            out[address] = {
                "private_key": pk,
                "proxy": proxy or "",
                "reserve_proxy": reserve or "",
            }
    return out


def _select_tokens_for_wallet(balances: Dict[str, Any]) -> List[Tuple[str, Decimal, int, str]]:
    """Возвращает список (token, amount_human, decimals, route), отсортированный по priority.

    Логика «вычистить под чистую»:
      • Минимум:  max(пользовательский порог, Layerswap min) — иначе пропускаем.
      • Максимум: cap по Layerswap max (если задан).
      • Суммой к отправке считаем весь баланс (для ETH — за вычетом газового резерва),
        затем при необходимости обрезаем cap'ом.
    """
    selected = []
    eth_amount = Decimal("0")
    eth_decimals = 18
    eth_present = False
    for sym, info in balances.items():
        sym_u = sym.upper()
        if sym_u not in THRESHOLDS_HUMAN:
            continue
        try:
            amount = Decimal(str(info.get("amount", "0")))
        except Exception:
            continue
        decimals = int(info.get("decimals", 18))
        if sym_u == "ETH":
            eth_amount = amount
            eth_decimals = decimals
            eth_present = True
            continue
        # стейблы: фильтр по effective_min, cap по effective_max
        emin = _effective_min(sym_u)
        if amount < emin:
            continue
        emax = _effective_max(sym_u)
        send = amount if (emax is None or amount <= emax) else emax
        selected.append((sym_u, send, decimals, ROUTES[sym_u]))

    # Сортируем не-ETH по приоритету
    selected.sort(key=lambda x: PRIORITIES.get(x[0], 50))

    # ETH добавляем последним. Резерв = 2*ETH_GAS_RESERVE (ChangePubKey + ETH-swap fee).
    # Стейблы платят комиссию в самом стейбле, ETH ими не расходуется.
    if eth_present:
        reserve = ETH_GAS_RESERVE * Decimal("2")
        eth_for_swap = eth_amount - reserve
        emin_eth = _effective_min("ETH")
        if eth_for_swap >= emin_eth:
            emax_eth = _effective_max("ETH")
            if emax_eth is not None and eth_for_swap > emax_eth:
                eth_for_swap = emax_eth
            selected.append(("ETH", eth_for_swap, eth_decimals, ROUTES["ETH"]))
    return selected


def _existing_task_keys() -> set:
    """Набор (wallet_lower, token) для всех не финальных/успешных задач —
    чтобы plan_tasks() был идемпотентен."""
    keys = set()
    for r in swap_db.list_all_tasks():
        if r["status"] == swap_db.STATUS_FAILED:
            continue
        keys.add((r["wallet_address"].lower(), r["source_token"].upper()))
    return keys


def plan_tasks(*, reset: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Главная функция: читает balance-DB, создаёт записи swap_tasks.

    Идемпотентен: если задача (wallet, token) уже есть и не failed — пропускаем.
    """
    if reset and not dry_run:
        swap_db.reset_database()
    if not dry_run:
        swap_db.init_database()

    existing = _existing_task_keys() if not dry_run else set()
    creds = load_wallet_credentials()
    rows = balance_db.get_all_results()

    summary = {
        "created": 0,
        "skipped_no_priv": 0,
        "skipped_no_balance": 0,
        "wallets_with_tasks": 0,
        "total_wallets": len(rows),
        "by_token": {"ETH": 0, "USDT": 0, "USDC": 0, "DAI": 0},
        "by_route": {"layerswap": 0, "unsupported": 0},
        "preview": [],
    }

    for row in rows:
        # balance-checker записывает status='completed' для успешных
        st = (row.get("status") or "").lower()
        if st not in ("completed", "success"):
            continue
        addr = (row.get("wallet_address") or "").lower()
        balances = row.get("balances") or {}
        if not balances:
            continue
        tokens = _select_tokens_for_wallet(balances)
        if not tokens:
            summary["skipped_no_balance"] += 1
            continue
        cred = creds.get(addr)
        if not cred:
            summary["skipped_no_priv"] += 1
            continue

        summary["wallets_with_tasks"] += 1
        for token, amount_human, decimals, route in tokens:
            if (addr, token) in existing:
                continue
            raw = int((amount_human * (Decimal(10) ** decimals)).to_integral_value())
            summary["by_token"][token] += 1
            summary["by_route"][route] += 1
            if dry_run:
                summary["preview"].append({
                    "wallet": addr, "token": token,
                    "amount": str(amount_human), "route": route,
                })
                continue
            swap_db.create_task(
                wallet_address=addr,
                private_key=cred["private_key"],
                proxy=cred.get("proxy") or None,
                route=route,
                source_token=token,
                target_token=SUPPORTED_PAIRS.get(token, token),
                amount_raw_planned=str(raw),
                amount_human_planned=str(amount_human),
                decimals=decimals,
                priority=PRIORITIES.get(token, 50),
                extra={"reserve_proxy": cred.get("reserve_proxy") or ""},
            )
            summary["created"] += 1
    return summary


__all__ = ["plan_tasks", "load_wallet_credentials", "THRESHOLDS_HUMAN", "ROUTES"]
