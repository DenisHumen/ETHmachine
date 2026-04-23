"""Runner — многопоточный запуск чекера и сохранение в SQLite.

Каждый кошелёк → своя curl_cffi-сессия → свой прокси из data.csv.
При ошибке — ретраи (RETRY_COUNT) и ротация на случайный прокси из пула.
"""
from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from eth_account import Account

from config.modules.cfg_base import DELAY_BETWEEN_ACCOUNTS, NUM_THREADS
from config.modules.cfg_pharos_claim import REQUIRE_PROXY
from modules.data_manager import load_data
from modules.proxy_manager import ProxyManager
from modules.simple_logger import logger as _logger, tqdm_safe_logging
from modules.pharos_claim import database as db
from modules.pharos_claim.checker import check_wallet_with_retry

try:
    from tqdm import tqdm  # type: ignore
    _HAS_TQDM = True
except Exception:  # pragma: no cover
    tqdm = None  # type: ignore
    _HAS_TQDM = False


def _load_wallets() -> list[dict]:
    """Загрузить кошельки из data.csv: pk + address + proxy + имя."""
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
    """Потокобезопасный ротатор прокси для одного кошелька."""

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


def _run_one(
    task: dict,
    private_key: str,
    proxy_pool: list[str],
    idx: int,
    total: int,
) -> tuple[int, str]:
    """Возвращает (task_id, outcome) где outcome ∈ {'eligible','not_eligible','failed'}."""
    task_id = int(task["id"])
    address = task["address"]
    account_name = task.get("account_name")  # может быть None — колонка скроется

    bound = _logger.bind(
        account_name=account_name,
        task_index=idx,
        task_total=total,
        wallet=f"{address[:6]}...{address[-4:]}",
    )

    proxy = task.get("proxy")
    if REQUIRE_PROXY and not proxy:
        db.mark_failed(task_id, "no proxy assigned")
        bound.error("Нет прокси — кошелёк пропущен (REQUIRE_PROXY=True)")
        return task_id, "failed"

    db.mark_running(task_id)

    # Случайная стартовая задержка между аккаунтами (не «ровный» паттерн).
    time.sleep(random.uniform(*DELAY_BETWEEN_ACCOUNTS))

    rotator = _ProxyRotator(proxy, proxy_pool)

    def _on_rotate() -> Optional[str]:
        new = rotator.rotate()
        if new and new != proxy:
            db.update_proxy(task_id, new)
        return new

    result = check_wallet_with_retry(
        private_key, rotator.current, on_proxy_rotate=_on_rotate,
    )

    if result.error:
        db.mark_failed(task_id, result.error)
        bound.error(f"Ошибка: {result.error}")
        return task_id, "failed"

    db.mark_completed(
        task_id,
        eligible=result.eligible,
        amount=result.amount,
        claimed=result.claimed,
        tiers=result.tiers,
        endpoint=result.endpoint,
        raw_response=result.raw,
    )

    raw = result.raw or {}
    srv_code = raw.get("code")
    srv_msg = (raw.get("message") or "").strip()
    srv_tag = f"code={srv_code}" + (f", '{srv_msg}'" if srv_msg else "")

    if result.eligible:
        amt = result.amount or "?"
        claimed_str = "" if result.claimed is None else (
            " [claimed]" if result.claimed else " [not claimed]"
        )
        bound.success(f"ELIGIBLE · allocation={amt}{claimed_str} · server: {srv_tag}")
        return task_id, "eligible"

    bound.warning(f"NOT eligible · server: {srv_tag}")
    return task_id, "not_eligible"


def run_checker(max_workers: Optional[int] = None, *, reset: bool = False) -> Optional[int]:
    """Запустить чекер по кошелькам из data.csv.

    Поведение:
      • reset=True → очистить БД и создать новый run.
      • Иначе — переиспользовать последний run:
          - возобновляются задачи со статусом running/failed;
          - новые адреса из data.csv добавляются как pending;
          - если pending нет и новых адресов нет — сообщаем, что всё готово.

    Возвращает run_id или None.
    """
    if reset:
        db.reset_all()
        _logger.warning("БД Pharos Claim Checker очищена — старт с нуля.")

    wallets = _load_wallets()
    if not wallets:
        _logger.error("Нет кошельков в data.csv. Добавьте private_key/proxy.")
        return None

    proxy_pool = ProxyManager.load_proxies()
    if REQUIRE_PROXY and not any(w.get("proxy") for w in wallets) and not proxy_pool:
        _logger.error(
            "REQUIRE_PROXY=True, но ни у одного кошелька нет прокси и пул пуст."
        )
        return None

    workers = max(1, int(max_workers or NUM_THREADS))

    # ── Resume / append ────────────────────────────────────────────────
    last_run_id = db.get_last_run_id()
    if last_run_id is None:
        run_id = db.create_run(total=len(wallets))
        db.create_tasks(run_id, wallets)
        _logger.info(f"Новый run_id={run_id}, кошельков: {len(wallets)}")
    else:
        run_id = last_run_id
        db.reopen_run(run_id)
        requeued = db.requeue_stale(run_id, include_failed=True)
        added = db.append_tasks(run_id, wallets)
        if requeued:
            _logger.info(f"Возобновлено задач (running/failed → pending): {requeued}")
        if added:
            _logger.info(f"Добавлено новых кошельков в run_id={run_id}: {added}")

    pending = db.get_pending_tasks(run_id)
    total = len(pending)
    if total == 0:
        _logger.success(
            f"Все кошельки уже обработаны (run_id={run_id}). "
            "Добавьте новые в data.csv или очистите БД для повторного запуска."
        )
        db.finish_run(run_id)
        return run_id

    # Быстрый словарь address → private_key (в БД ключи не храним).
    pk_by_address = {w["address"].lower(): w["private_key"] for w in wallets}

    _logger.info(
        f"Pharos Claim Checker: к обработке {total}, потоков: {workers}, run_id={run_id}"
    )

    # ── Прогресс-бары (pip-style): Progress (checked/remaining) + Eligible
    bar_fmt_top = (
        "{desc:<12} {percentage:3.0f}%|{bar:30}| "
        "{n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
    )
    bar_fmt_bot = (
        "{desc:<12} {percentage:3.0f}%|{bar:30}| "
        "{n_fmt}/{total_fmt} {postfix}"
    )

    counters = {"eligible": 0, "not_eligible": 0, "failed": 0}

    with tqdm_safe_logging():
        if _HAS_TQDM:
            bar_done = tqdm(
                total=total, desc="Progress", unit="w",
                position=0, leave=True, dynamic_ncols=True,
                colour="cyan", bar_format=bar_fmt_top,
            )
            bar_elig = tqdm(
                total=total, desc="Eligible", unit="w",
                position=1, leave=True, dynamic_ncols=True,
                colour="green", bar_format=bar_fmt_bot,
            )
            bar_elig.set_postfix_str("not_eligible=0, failed=0")
        else:
            bar_done = bar_elig = None

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for i, task in enumerate(pending, 1):
                pk = pk_by_address.get(str(task["address"]).lower())
                if not pk:
                    db.mark_failed(
                        int(task["id"]),
                        "private_key отсутствует в data.csv для этого адреса",
                    )
                    counters["failed"] += 1
                    if bar_done is not None:
                        bar_done.update(1)
                        bar_elig.set_postfix_str(
                            f"not_eligible={counters['not_eligible']}, "
                            f"failed={counters['failed']}"
                        )
                    continue
                futures.append(
                    executor.submit(_run_one, task, pk, proxy_pool, i, total)
                )
            try:
                for fut in as_completed(futures):
                    try:
                        _tid, outcome = fut.result()
                    except Exception as e:
                        _logger.error(f"Неожиданная ошибка в воркере: {e}")
                        outcome = "failed"
                    counters[outcome] = counters.get(outcome, 0) + 1
                    if bar_done is not None:
                        bar_done.update(1)
                        if outcome == "eligible":
                            bar_elig.update(1)
                        bar_elig.set_postfix_str(
                            f"not_eligible={counters['not_eligible']}, "
                            f"failed={counters['failed']}"
                        )
            except KeyboardInterrupt:
                _logger.warning("Остановка по Ctrl+C, жду завершения запущенных задач…")
                for fut in futures:
                    fut.cancel()

        if bar_done is not None:
            bar_elig.close()
            bar_done.close()

    stats = db.finish_run(run_id)
    _logger.success(
        f"Готово: eligible={stats['eligible']}, not_eligible={stats['not_eligible']}, "
        f"failed={stats['failed']} | run_id={run_id}"
    )
    return run_id
