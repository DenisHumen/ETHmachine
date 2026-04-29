"""Quick smoke test for the auto progress-bar in modules.simple_logger.

Сценарии:
  1. Несколько потоков вызывают log_wallet_task -> авто-бар появляется,
     обновляется, закрывается на завершении и не ломает форматирование логов.
  2. При активном внешнем tqdm-баре наш авто-бар НЕ создаётся (бэккомпат
     с dune/pharos_claim).
  3. log_simple / log_task без index/total ничего не ломают.
"""
from __future__ import annotations

import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Гарантируем, что в качестве рабочей директории – корень репо.
import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.simple_logger import (  # noqa: E402
    log_wallet_task,
    log_task,
    log_simple,
    tqdm_safe_logging,
    reset_progress,
    logger,
)


def _scenario_auto_bar():
    print("\n===== Scenario 1: auto progress-bar over threads =====")
    total = 8

    def work(idx: int):
        wallet = f"0x{idx:040x}"[:10]
        log_wallet_task(wallet, idx, total, "starting…", "info")
        time.sleep(random.uniform(0.2, 0.6))
        log_wallet_task(wallet, idx, total, "step 1 ok", "info")
        time.sleep(random.uniform(0.1, 0.4))
        if idx == 3:
            log_wallet_task(wallet, idx, total, "boom", "error")
            return
        log_wallet_task(wallet, idx, total, "done", "success")

    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(work, range(1, total + 1)))

    # На всякий случай — на случай если total не достигли (не должно случиться).
    reset_progress()


def _scenario_external_tqdm():
    print("\n===== Scenario 2: external tqdm should suppress auto-bar =====")
    try:
        from tqdm import tqdm
    except Exception:
        print("tqdm not installed — skipping")
        return

    total = 4
    bar_format = "EXT {desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt}"
    with tqdm_safe_logging(), tqdm(total=total, desc="external", bar_format=bar_format) as ext_bar:
        for i in range(1, total + 1):
            wallet = f"0x{i:040x}"[:10]
            log_wallet_task(wallet, i, total, f"external-step {i}", "info")
            time.sleep(0.15)
            log_wallet_task(wallet, i, total, "ok", "success")
            ext_bar.update(1)


def _scenario_plain_logs():
    print("\n===== Scenario 3: plain logs without index/total =====")
    log_simple("hello world", "info")
    log_simple("warning here", "warning")
    log_task(1, 1, "single-step task", "success")


if __name__ == "__main__":
    _scenario_auto_bar()
    _scenario_external_tqdm()
    _scenario_plain_logs()
    print("\nAll scenarios finished.")
