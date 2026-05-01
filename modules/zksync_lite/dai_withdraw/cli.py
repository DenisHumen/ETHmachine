"""CLI: dai_withdraw меню (план / запуск / статистика).

Запуск из main.py через Меню или вручную:
    python -m modules.zksync_lite.dai_withdraw.cli
"""
from __future__ import annotations

import sys
from typing import Optional

try:
    import questionary  # type: ignore
except Exception:
    questionary = None

from modules.simple_logger import logger
from modules.zksync_lite.dai_withdraw import database as dai_db
from modules.zksync_lite.dai_withdraw.executor import DaiWithdrawExecutor
from modules.zksync_lite.dai_withdraw.planner import plan_tasks, MIN_DAI_HUMAN


def _menu() -> Optional[str]:
    if questionary is None:
        print("установите questionary: pip install questionary")
        return None
    return questionary.select(
        "💧 DAI withdraw Lite → L1 — выберите действие:",
        choices=[
            "📋 Планирование (создать задачи из balance-БД)",
            "▶️  Запуск pending задач",
            "🤖 Авто-режим (план + запуск)",
            "📊 Статистика",
            "🔄 Сброс БД (reset)",
            "↩  Назад",
        ],
    ).ask()


def cmd_plan(reset: bool = False, dry_run: bool = False) -> None:
    print(f"Планирование (min_dai={MIN_DAI_HUMAN}) reset={reset} dry_run={dry_run}…")
    s = plan_tasks(reset=reset, dry_run=dry_run)
    for k, v in s.items():
        if k != "preview":
            print(f"  {k}: {v}")
    if dry_run and s.get("preview"):
        print("\nПервые 20 кошельков:")
        for p in s["preview"][:20]:
            print(f"  {p['wallet']}  {p['amount']} DAI")


def cmd_run() -> None:
    dai_db.init_database()
    executor = DaiWithdrawExecutor()
    res = executor.run_all()
    print("\n=== итог ===")
    print(f"  результаты: {len(res['results'])}")
    print(f"  фейлы: {len(res['failures'])}")
    print(f"  статусы: {res['stats']}")


def cmd_stats() -> None:
    dai_db.init_database()
    print("\nDAI withdraw stats:")
    for k, v in dai_db.get_statistics().items():
        print(f"  {k}: {v}")


def cmd_reset() -> None:
    if questionary is None:
        ans = input("Точно сбросить БД? (y/N): ").strip().lower() == "y"
    else:
        ans = questionary.confirm("Точно сбросить БД?").ask()
    if ans:
        dai_db.reset_database()
        print("Сброшено.")


def main() -> None:
    while True:
        ch = _menu()
        if not ch or ch.startswith("↩"):
            return
        if ch.startswith("📋"):
            cmd_plan(reset=False, dry_run=False)
        elif ch.startswith("▶"):
            cmd_run()
        elif ch.startswith("🤖"):
            cmd_plan(reset=False, dry_run=False)
            cmd_run()
        elif ch.startswith("📊"):
            cmd_stats()
        elif ch.startswith("🔄"):
            cmd_reset()
        try:
            input("\nНажмите Enter для продолжения…")
        except (EOFError, KeyboardInterrupt):
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(0)
