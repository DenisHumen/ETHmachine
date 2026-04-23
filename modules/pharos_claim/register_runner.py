"""Runner для REGISTRAR (регистрация tier Instant Airdrop до даты клейма).

Берёт из последнего run_id чекера все eligible адреса и для каждого
вызывает updateTier(tier) на API (кнопка Confirm на claim.pharos.xyz).
"""
from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from eth_account import Account

from config.modules.cfg_base import DELAY_BETWEEN_ACCOUNTS, NUM_THREADS
from config.modules.cfg_pharos_claim import REGISTER_DEFAULT_TIER, REQUIRE_PROXY
from modules.data_manager import load_data
from modules.proxy_manager import ProxyManager
from modules.simple_logger import logger as _logger, tqdm_safe_logging
from modules.pharos_claim import database as db
from modules.pharos_claim.registrar import register_wallet_with_retry

try:
    from tqdm import tqdm  # type: ignore
    _HAS_TQDM = True
except Exception:  # pragma: no cover
    tqdm = None  # type: ignore
    _HAS_TQDM = False


# ─────────────────── загрузка кошельков (то же, что в claim_runner.py) ───────────────────

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


# ─────────────────── один воркер ───────────────────

def _register_one(
    task: dict,
    private_key: str,
    proxy_pool: list[str],
    idx: int,
    total: int,
    tier: str,
) -> str:
    """Возвращает outcome ∈ {'registered','already','not_eligible','failed'}."""
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
        db.mark_register_failed(task_id, "no proxy assigned", tier=tier)
        bound.error("Нет прокси — регистрация пропущена (REQUIRE_PROXY=True)")
        return "failed"

    db.mark_register_running(task_id)

    # Стартовая разница, чтобы не залп API.
    time.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS))

    rotator = _ProxyRotator(proxy, proxy_pool)

    def _on_rotate() -> Optional[str]:
        new = rotator.rotate()
        if new and new != proxy:
            db.update_proxy(task_id, new)
        return new

    result = register_wallet_with_retry(
        private_key,
        rotator.current,
        tier=tier,
        on_proxy_rotate=_on_rotate,
    )

    if result.ok:
        db.mark_register_done(
            task_id,
            tier=result.saved_tier or result.tier,
            already_registered=result.already_registered,
        )
        if result.already_registered:
            bound.info(f"ALREADY · tier={result.saved_tier or result.tier}")
            return "already"
        bound.success(f"REGISTERED · tier={result.saved_tier or result.tier}")
        return "registered"

    if result.not_eligible:
        db.mark_register_failed(
            task_id,
            result.error or "not eligible",
            tier=result.tier,
            not_eligible=True,
        )
        bound.warning(f"NOT_ELIGIBLE · {result.error}")
        return "not_eligible"

    db.mark_register_failed(task_id, result.error or "unknown", tier=result.tier)
    bound.error(f"FAIL · {result.error}")
    return "failed"


# ─────────────────── публичный запуск ───────────────────

def run_registrar(
    max_workers: Optional[int] = None,
    *,
    reset: bool = False,
    run_id: Optional[int] = None,
    tier: str = REGISTER_DEFAULT_TIER,
) -> Optional[int]:
    """Запустить регистратор tier по всем eligible кошелькам последнего run.

    reset=True — сбросить register_* колонки во ВСЕХ задачах run, чтобы
    повторить регистрацию (включая ранее registered/failed).
    """
    if run_id is None:
        run_id = db.get_last_run_id()
    if run_id is None:
        _logger.error(
            "Сначала запустите Claim Checker — нет ни одного run_id в БД."
        )
        return None

    if reset:
        n = db.reset_register_state(run_id)
        _logger.warning(f"Сброшено register-состояние у {n} задач (run_id={run_id}).")

    candidates = db.get_register_candidates(run_id, include_failed=True)
    total = len(candidates)
    if total == 0:
        _logger.success(
            f"Нет кандидатов на регистрацию tier (run_id={run_id}): все eligible "
            "уже зарегистрированы или их нет."
        )
        return run_id

    wallets = _load_wallets()
    pk_by_address = {w["address"].lower(): w["private_key"] for w in wallets}
    proxy_pool = ProxyManager.load_proxies()

    workers = max(1, int(max_workers or NUM_THREADS))

    _logger.info(
        f"Pharos Registrar: к регистрации {total} кошельков, tier={tier!r}, "
        f"потоков: {workers}, run_id={run_id}"
    )

    bar_fmt_top = (
        "{desc:<12} {percentage:3.0f}%|{bar:30}| "
        "{n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
    )
    bar_fmt_bot = (
        "{desc:<12} {percentage:3.0f}%|{bar:30}| "
        "{n_fmt}/{total_fmt} {postfix}"
    )

    counters = {"registered": 0, "already": 0, "not_eligible": 0, "failed": 0}

    with tqdm_safe_logging():
        if _HAS_TQDM:
            bar_done = tqdm(
                total=total, desc="Progress", unit="w",
                position=0, leave=True, dynamic_ncols=True,
                colour="cyan", bar_format=bar_fmt_top,
            )
            bar_ok = tqdm(
                total=total, desc="Registered", unit="w",
                position=1, leave=True, dynamic_ncols=True,
                colour="green", bar_format=bar_fmt_bot,
            )
            bar_ok.set_postfix_str("already=0, not_eligible=0, failed=0")
        else:
            bar_done = bar_ok = None

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for i, task in enumerate(candidates, 1):
                pk = pk_by_address.get(str(task["address"]).lower())
                if not pk:
                    db.mark_register_failed(
                        int(task["id"]),
                        "private_key отсутствует в data.csv для этого адреса",
                        tier=tier,
                    )
                    counters["failed"] += 1
                    if bar_done is not None:
                        bar_done.update(1)
                        bar_ok.set_postfix_str(
                            f"already={counters['already']}, "
                            f"not_eligible={counters['not_eligible']}, "
                            f"failed={counters['failed']}"
                        )
                    continue
                futures.append(
                    executor.submit(
                        _register_one, task, pk, proxy_pool, i, total, tier,
                    )
                )

            try:
                for fut in as_completed(futures):
                    try:
                        outcome = fut.result()
                    except Exception as e:
                        _logger.error(f"Неожиданная ошибка в воркере регистратора: {e}")
                        outcome = "failed"
                    counters[outcome] = counters.get(outcome, 0) + 1
                    if bar_done is not None:
                        bar_done.update(1)
                        if outcome == "registered":
                            bar_ok.update(1)
                        bar_ok.set_postfix_str(
                            f"already={counters['already']}, "
                            f"not_eligible={counters['not_eligible']}, "
                            f"failed={counters['failed']}"
                        )
            except KeyboardInterrupt:
                _logger.warning("Остановка по Ctrl+C, жду завершения запущенных задач…")
                for fut in futures:
                    fut.cancel()

        if bar_done is not None:
            bar_ok.close()
            bar_done.close()

    _logger.success(
        f"Готово: registered={counters['registered']}, already={counters['already']}, "
        f"not_eligible={counters['not_eligible']}, failed={counters['failed']} | "
        f"run_id={run_id}"
    )
    return run_id
