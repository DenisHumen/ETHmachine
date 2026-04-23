"""Runner для CLAIMER (он-чейн исполнение награды).

Берёт из последнего run_id чекера все eligible+not_claimed адреса и для каждого
вызывает claim() на контракте. Тир и сумма берутся:
  • из колонки `tiers` (claim_tier) если есть → плюс `amount` (распарсить wei),
  • иначе из самого proof-эндпоинта (он сам отдаёт amount).
"""
from __future__ import annotations

import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from eth_account import Account

from config.modules.cfg_base import DELAY_BETWEEN_ACCOUNTS, NUM_THREADS
from config.modules.cfg_pharos_claim import CLAIM_DEFAULT_TIER, REQUIRE_PROXY
from modules.data_manager import load_data
from modules.proxy_manager import ProxyManager
from modules.simple_logger import logger as _logger, tqdm_safe_logging
from modules.pharos_claim import database as db
from modules.pharos_claim.claimer import claim_wallet_with_retry, explorer_url

try:
    from tqdm import tqdm  # type: ignore
    _HAS_TQDM = True
except Exception:  # pragma: no cover
    tqdm = None  # type: ignore
    _HAS_TQDM = False


# ─────────────────── загрузка кошельков (то же, что в runner.py) ───────────────────

def _load_wallets() -> list[dict]:
    rows = load_data()
    wallets: list[dict] = []
    for i, row in enumerate(rows, 1):
        pk = (row.get("private_key") or "").strip()
        if not pk:
            continue
        if not pk.startswith("0x"):
            pk = "0x" + pk
        try:
            addr = Account.from_key(pk).address
        except Exception as e:
            _logger.error(f"Ключ #{i}: {e}")
            continue
        wallets.append({
            "private_key": pk,
            "address": addr,
            "proxy": (row.get("proxy") or "").strip() or None,
            "account_name": (row.get("name") or "").strip() or None,
        })
    return wallets


class _ProxyRotator:
    def __init__(self, initial: Optional[str], pool: list[str]) -> None:
        self._lock = threading.Lock()
        self._current = initial
        self._pool = [p for p in pool if p]
        self._used: set[str] = set()
        if initial:
            self._used.add(initial)

    @property
    def current(self) -> Optional[str]:
        return self._current

    def rotate(self) -> Optional[str]:
        with self._lock:
            if not self._pool:
                return self._current
            candidates = [p for p in self._pool if p not in self._used] or list(self._pool)
            new = random.choice(candidates)
            self._used.add(new)
            self._current = new
            return new


# ─────────────────── разбор tier из ранее сохранённого ответа чекера ──

def _extract_tier_from_task(task: dict) -> Optional[str]:
    """Достать claim_tier из колонки tiers (JSON) или raw_response."""
    tiers_raw = task.get("tiers")
    if tiers_raw:
        try:
            parsed = json.loads(tiers_raw)
            if isinstance(parsed, list) and parsed:
                first = parsed[0]
                if isinstance(first, dict):
                    t = first.get("claim_tier")
                    if isinstance(t, str) and t.strip():
                        return t.strip()
        except (json.JSONDecodeError, TypeError):
            pass

    raw = task.get("raw_response")
    if raw:
        try:
            parsed = json.loads(raw)
            data = parsed.get("data") if isinstance(parsed, dict) else None
            if isinstance(data, dict):
                t = data.get("claim_tier")
                if isinstance(t, str) and t.strip():
                    return t.strip()
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _extract_amount_wei_from_task(task: dict) -> Optional[int]:
    """Если в raw_response есть airdrop_amount (wei) — берём его, иначе None."""
    raw = task.get("raw_response")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if isinstance(data, dict):
            v = data.get("airdrop_amount")
            if v not in (None, "", 0, "0"):
                return int(str(v))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return None


# ─────────────────── один воркер ───────────────────

def _claim_one(
    task: dict,
    private_key: str,
    proxy_pool: list[str],
    idx: int,
    total: int,
) -> str:
    """Возвращает outcome ∈ {'claimed','skipped','failed'}."""
    task_id = int(task["id"])
    address = task["address"]
    account_name = task.get("account_name")

    bound = _logger.bind(
        account_name=account_name,
        task_index=idx,
        task_total=total,
        wallet=f"{address[:6]}...{address[-4:]}",
    )

    proxy = task.get("proxy")
    if REQUIRE_PROXY and not proxy:
        db.mark_claim_failed(task_id, "no proxy assigned")
        bound.error("Нет прокси — клейм пропущен (REQUIRE_PROXY=True)")
        return "failed"

    db.mark_claim_running(task_id)

    # Стартовая разница, чтобы не залп RPC.
    time.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS))

    rotator = _ProxyRotator(proxy, proxy_pool)

    def _on_rotate() -> Optional[str]:
        new = rotator.rotate()
        if new and new != proxy:
            db.update_proxy(task_id, new)
        return new

    tier = _extract_tier_from_task(task) or CLAIM_DEFAULT_TIER
    amount_wei = _extract_amount_wei_from_task(task)

    result = claim_wallet_with_retry(
        private_key,
        rotator.current,
        tier=tier,
        amount_wei=amount_wei,
        on_proxy_rotate=_on_rotate,
    )

    if result.ok:
        if result.already_claimed:
            db.mark_claim_done(
                task_id,
                tx_hash=None,
                amount=result.amount,
                tier=result.tier,
                already_claimed=True,
            )
            bound.info(f"SKIP · уже заклеймлено on-chain · tier={result.tier}")
            return "skipped"
        db.mark_claim_done(
            task_id,
            tx_hash=result.tx_hash,
            amount=result.amount,
            tier=result.tier,
            already_claimed=False,
        )
        url = explorer_url(result.tx_hash) if result.tx_hash else "?"
        bound.success(
            f"CLAIMED · amount={result.amount or '?'} · tier={result.tier} · tx={url}"
        )
        return "claimed"

    if result.not_ready:
        db.mark_claim_not_ready(
            task_id,
            result.skip_reason or "proof not ready",
            tier=result.tier,
        )
        bound.warning(
            f"NOT_READY · proof ещё не опубликован на сервере · tier={result.tier}"
        )
        return "not_ready"

    db.mark_claim_failed(task_id, result.error or "unknown", tx_hash=result.tx_hash, tier=result.tier)
    bound.error(f"FAIL · {result.error}")
    return "failed"


# ─────────────────── публичный запуск ───────────────────

def run_claimer(
    max_workers: Optional[int] = None,
    *,
    reset: bool = False,
    run_id: Optional[int] = None,
) -> Optional[int]:
    """Запустить клеймер по всем eligible+not_claimed кошелькам последнего run.

    reset=True — сбросить claim_* колонки во ВСЕХ задачах run, чтобы
    перепопытаться (включая ранее claimed/failed). По умолчанию пропускаем
    уже claimed/skipped.
    """
    if run_id is None:
        run_id = db.get_last_run_id()
    if run_id is None:
        _logger.error(
            "Сначала запустите Claim Checker — нет ни одного run_id в БД."
        )
        return None

    if reset:
        n = db.reset_claim_state(run_id)
        _logger.warning(f"Сброшено claim-состояние у {n} задач (run_id={run_id}).")

    candidates = db.get_claim_candidates(run_id, include_failed=True)
    total = len(candidates)
    if total == 0:
        _logger.success(
            f"Нет кандидатов на клейм (run_id={run_id}): все eligible-кошельки "
            "уже обработаны или клеймить нечего."
        )
        return run_id

    wallets = _load_wallets()
    pk_by_address = {w["address"].lower(): w["private_key"] for w in wallets}
    proxy_pool = ProxyManager.load_proxies()

    workers = max(1, int(max_workers or NUM_THREADS))

    _logger.info(
        f"Pharos Claimer: к клейму {total} кошельков, потоков: {workers}, run_id={run_id}"
    )

    bar_fmt_top = (
        "{desc:<12} {percentage:3.0f}%|{bar:30}| "
        "{n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
    )
    bar_fmt_bot = (
        "{desc:<12} {percentage:3.0f}%|{bar:30}| "
        "{n_fmt}/{total_fmt} {postfix}"
    )

    counters = {"claimed": 0, "skipped": 0, "failed": 0, "not_ready": 0}

    with tqdm_safe_logging():
        if _HAS_TQDM:
            bar_done = tqdm(
                total=total, desc="Progress", unit="w",
                position=0, leave=True, dynamic_ncols=True,
                colour="cyan", bar_format=bar_fmt_top,
            )
            bar_ok = tqdm(
                total=total, desc="Claimed", unit="w",
                position=1, leave=True, dynamic_ncols=True,
                colour="green", bar_format=bar_fmt_bot,
            )
            bar_ok.set_postfix_str("skipped=0, not_ready=0, failed=0")
        else:
            bar_done = bar_ok = None

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for i, task in enumerate(candidates, 1):
                pk = pk_by_address.get(str(task["address"]).lower())
                if not pk:
                    db.mark_claim_failed(
                        int(task["id"]),
                        "private_key отсутствует в data.csv для этого адреса",
                    )
                    counters["failed"] += 1
                    if bar_done is not None:
                        bar_done.update(1)
                        bar_ok.set_postfix_str(
                            f"skipped={counters['skipped']}, not_ready={counters['not_ready']}, failed={counters['failed']}"
                        )
                    continue
                futures.append(
                    executor.submit(_claim_one, task, pk, proxy_pool, i, total)
                )

            try:
                for fut in as_completed(futures):
                    try:
                        outcome = fut.result()
                    except Exception as e:
                        _logger.error(f"Неожиданная ошибка в воркере клейма: {e}")
                        outcome = "failed"
                    counters[outcome] = counters.get(outcome, 0) + 1
                    if bar_done is not None:
                        bar_done.update(1)
                        if outcome == "claimed":
                            bar_ok.update(1)
                        bar_ok.set_postfix_str(
                            f"skipped={counters['skipped']}, not_ready={counters['not_ready']}, failed={counters['failed']}"
                        )
            except KeyboardInterrupt:
                _logger.warning("Остановка по Ctrl+C, жду завершения запущенных задач…")
                for fut in futures:
                    fut.cancel()

        if bar_done is not None:
            bar_ok.close()
            bar_done.close()

    _logger.success(
        f"Готово: claimed={counters['claimed']}, skipped={counters['skipped']}, "
        f"not_ready={counters['not_ready']}, failed={counters['failed']} | run_id={run_id}"
    )
    return run_id
