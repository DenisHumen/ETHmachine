"""Хендлер меню для Pharos Claim Checker — вызывается из modules/pharos/menu.py.

Подменю:
  ▶ Запустить / продолжить   — доделать pending/failed, авто-добавить новые адреса из data.csv
  🗑 Очистить БД и начать заново
  🔙 Назад
"""
from colorama import Fore, Style
from questionary import select, confirm

from config.menu_config import SubMenu, MenuItem, build_submenu_choices
from config.modules.cfg_base import NUM_THREADS
from modules.pharos_claim import database as db
from modules.pharos_claim.excel_export import export_run
from modules.pharos_claim.runner import run_checker


CLAIM_MENU = SubMenu(
    key="pharos_claim",
    label="Claim Checker",
    description="Проверка результатов claim.pharos.xyz",
    icon="🏆",
    qmark="🏆",
    pointer="👉",
    items=[
        MenuItem(
            key="run",
            label="Запустить / продолжить",
            description="Доделать pending/failed и добавить новые адреса из data.csv",
            icon="▶",
        ),
        MenuItem(
            key="reset",
            label="Очистить БД и начать заново",
            description="Удалить все запуски и задачи, начать с нуля",
            icon="🗑",
        ),
        MenuItem(key="back", label="Назад", description="", icon="🔙"),
    ],
)


def _ask_workers() -> int:
    try:
        raw = input(
            f"  {Fore.WHITE}Количество потоков [{NUM_THREADS}]: {Style.RESET_ALL}"
        ).strip()
        return int(raw) if raw else NUM_THREADS
    except ValueError:
        return NUM_THREADS


def _run(reset: bool) -> None:
    workers = _ask_workers()
    run_id = run_checker(max_workers=workers, reset=reset)
    if run_id is None:
        return
    filepath = export_run(run_id)
    if filepath:
        print(f"\n  {Fore.GREEN}Excel: {filepath}{Style.RESET_ALL}")


def claim_checker_menu() -> None:
    """Подменю Claim Checker."""
    print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════╗")
    print(f"║{Fore.WHITE}       PHAROS CLAIM CHECKER (claim.pharos.xyz)    {Fore.CYAN}║")
    print(f"╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}- состояние хранится в SQLite (db/pharos_claim.db)")
    print(f"  - при повторном запуске уже готовые кошельки пропускаются")
    print(f"  - новые адреса из data.csv автоматически добавляются{Style.RESET_ALL}\n")

    while True:
        action = select(
            "Claim Checker — выберите действие:",
            choices=build_submenu_choices(CLAIM_MENU),
            qmark=CLAIM_MENU.qmark,
            pointer=CLAIM_MENU.pointer,
        ).ask()

        if action is None or action == "back":
            return

        if action == "run":
            _run(reset=False)
            return

        if action == "reset":
            ok = confirm(
                "Удалить всю историю Pharos Claim Checker и начать с нуля?",
                default=False,
            ).ask()
            if not ok:
                continue
            _run(reset=True)
            return
