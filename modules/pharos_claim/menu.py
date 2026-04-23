"""Хендлер меню для Pharos Claim Checker — вызывается из modules/pharos/menu.py.

Подменю:
  ▶ Запустить / продолжить чекер   — доделать pending/failed, авто-добавить новые из data.csv
  💰 Клеймить eligible             — он-чейн claim() для всех eligible+not_claimed
  🔁 Переклеймить (reset claim)    — сбросить claim_* и перезапустить клеймер
  🗑 Очистить БД и начать заново
  🔙 Назад
"""
from colorama import Fore, Style
from questionary import select, confirm

from config.menu_config import SubMenu, MenuItem, build_submenu_choices
from config.modules.cfg_base import NUM_THREADS
from config.modules.cfg_pharos_claim import REGISTER_DEFAULT_TIER
from modules.pharos_claim import database as db
from modules.pharos_claim.claim_runner import run_claimer
from modules.pharos_claim.excel_export import export_run
from modules.pharos_claim.register_runner import run_registrar
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
            label="Запустить / продолжить чекер",
            description="Доделать pending/failed + добавить новые адреса",
            icon="▶",
        ),
        MenuItem(
            key="register",
            label="Регистрация tier (Confirm)",
            description="POST /airdrop_info {tier:'now'} для всех eligible",
            icon="✅",
        ),
        MenuItem(
            key="register_reset",
            label="Сброс регистрации и повтор",
            description="Обнулить register_* и зарегистрировать заново",
            icon="♻",
        ),
        MenuItem(
            key="claim",
            label="Клеймить eligible (он-чейн)",
            description="claim() на контракте для всех eligible",
            icon="💰",
        ),
        MenuItem(
            key="claim_reset",
            label="Сброс клейма и повтор",
            description="Обнулить claim_* и заклеймить заново",
            icon="🔁",
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


def _run_check(reset: bool) -> None:
    workers = _ask_workers()
    run_id = run_checker(max_workers=workers, reset=reset)
    if run_id is None:
        return
    filepath = export_run(run_id)
    if filepath:
        print(f"\n  {Fore.GREEN}Excel: {filepath}{Style.RESET_ALL}")


def _run_claim(reset: bool) -> None:
    workers = _ask_workers()
    run_id = run_claimer(max_workers=workers, reset=reset)
    if run_id is None:
        return
    filepath = export_run(run_id)
    if filepath:
        print(f"\n  {Fore.GREEN}Excel: {filepath}{Style.RESET_ALL}")


def _run_register(reset: bool, tier: str = REGISTER_DEFAULT_TIER) -> None:
    workers = _ask_workers()
    run_id = run_registrar(max_workers=workers, reset=reset, tier=tier)
    if run_id is None:
        return
    filepath = export_run(run_id)
    if filepath:
        print(f"\n  {Fore.GREEN}Excel: {filepath}{Style.RESET_ALL}")


def claim_checker_menu() -> None:
    """Подменю Claim Checker + Claimer."""
    print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════╗")
    print(f"║{Fore.WHITE}       PHAROS CLAIM (claim.pharos.xyz)            {Fore.CYAN}║")
    print(f"╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}- состояние хранится в SQLite (db/pharos_claim.db)")
    print(f"  - чекер: при повторном запуске уже готовые кошельки пропускаются")
    print(f"  - клеймер: работает по последнему run чекера{Style.RESET_ALL}\n")

    while True:
        action = select(
            "Pharos Claim — выберите действие:",
            choices=build_submenu_choices(CLAIM_MENU),
            qmark=CLAIM_MENU.qmark,
            pointer=CLAIM_MENU.pointer,
        ).ask()

        if action is None or action == "back":
            return

        if action == "run":
            _run_check(reset=False)
            return

        if action == "claim":
            _run_claim(reset=False)
            return

        if action == "claim_reset":
            ok = confirm(
                "Сбросить claim-состояние всех задач и заново попытаться?",
                default=False,
            ).ask()
            if not ok:
                continue
            _run_claim(reset=True)
            return

        if action == "register":
            _run_register(reset=False)
            return

        if action == "register_reset":
            ok = confirm(
                "Сбросить register-состояние всех задач и заново зарегистрировать?",
                default=False,
            ).ask()
            if not ok:
                continue
            _run_register(reset=True)
            return

        if action == "reset":
            ok = confirm(
                "Удалить всю историю Pharos Claim Checker и начать с нуля?",
                default=False,
            ).ask()
            if not ok:
                continue
            _run_check(reset=True)
            return
