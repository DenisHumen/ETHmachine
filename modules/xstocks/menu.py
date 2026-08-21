"""Меню modules.xstocks — xStocks DeFi Points."""
from __future__ import annotations

import asyncio
from pathlib import Path

from eth_account import Account

from config.modules.cfg_xstocks import GM_COOLDOWN_HOURS
from config.modules.general_config import DELAY_BETWEEN_ACCOUNTS, NUM_THREADS
from modules.data_manager import load_data
from modules.ui import theme, ui
from modules.ui.module_menu import MenuAction, ModuleMenu
from modules.xstocks import database as db
from modules.xstocks import xstocks_logger as logger
from modules.xstocks.excel_export import export_results
from modules.xstocks.worker import (
    run_connect_sol, run_full_auto, run_gm_loop, run_gm_once, run_registration,
    run_stats,
)


# ── Подготовка данных ────────────────────────────────────────────────────

def load_wallets() -> list[dict]:
    """Кошельки из data.csv: приватный ключ, прокси, Solana, реф-код."""
    rows = load_data()
    if not rows:
        return []

    wallets = []
    for i, row in enumerate(rows):
        pk = row.get('private_key', '').strip()
        if not pk:
            continue
        if not pk.startswith("0x"):
            pk = "0x" + pk
        try:
            account = Account.from_key(pk)
            wallets.append({
                "private_key": pk,
                "address": account.address,
                "account_name": row.get('name', '').strip() or None,
                "proxy": row.get('proxy', '').strip() or None,
                "reserve_proxy": row.get('reserve_proxy', '').strip() or None,
                "sol_private_key": row.get('sol_private_key', '').strip() or None,
                "sol_address": row.get('sol_address', '').strip() or None,
                "referral_code": row.get('referral_code', '').strip() or None,
            })
        except Exception as e:
            logger.log(f"Ошибка ключа #{i + 1}: {e}", "error")
    return wallets


def _ensure_db() -> bool:
    """Синхронизирует базу с data.csv. False — работать не с чем."""
    wallets = load_wallets()
    if not wallets:
        logger.log("Нет данных в data.csv! Добавьте приватные ключи", "error")
        return False

    total = db.ensure_wallets(wallets)
    logger.log(f"База синхронизирована: {total} кошельков", "info")
    return True


def _ask_workers() -> int | None:
    """Сколько кошельков обрабатывать одновременно. None — отказ."""
    return ui.ask_int("Параллельных кошельков", minimum=1, default=NUM_THREADS)


# ── Действия ─────────────────────────────────────────────────────────────

def _handle_full_auto() -> None:
    if not _ensure_db():
        return
    ui.print_lines(ui.panel("Авто-режим", [
        "Порядок работы: регистрация → подключение Solana → GM по кругу.",
        f"Кулдаун GM: {GM_COOLDOWN_HOURS} ч.",
        f"Задержка между аккаунтами: "
        f"{DELAY_BETWEEN_ACCOUNTS[0]}–{DELAY_BETWEEN_ACCOUNTS[1]} с.",
        "Остановка — Ctrl+C, прогресс останется в базе.",
    ]))
    workers = _ask_workers()
    if workers is None:
        return
    try:
        asyncio.run(run_full_auto(workers))
    except KeyboardInterrupt:
        logger.log("Авто-режим остановлен (Ctrl+C). Прогресс сохранён в базе.",
                   "warning")


def _handle_register() -> None:
    if not _ensure_db():
        return
    workers = _ask_workers()
    if workers is None:
        return
    try:
        results = asyncio.run(run_registration(workers))
    except Exception as exc:
        logger.log(f"Регистрация прервана ошибкой: {exc}", "error")
        return
    if results:
        export_results()


def _handle_connect_sol() -> None:
    if not _ensure_db():
        return
    workers = _ask_workers()
    if workers is None:
        return
    asyncio.run(run_connect_sol(workers))


def _handle_gm_once() -> None:
    if not _ensure_db():
        return
    workers = _ask_workers()
    if workers is None:
        return
    asyncio.run(run_gm_once(workers))


def _handle_gm_loop() -> None:
    if not _ensure_db():
        return
    ui.print_lines(ui.panel("GM по кругу", [
        f"Отметка повторяется примерно раз в {GM_COOLDOWN_HOURS} ч "
        f"для каждого кошелька.",
        "Точное время следующей отметки берётся из ответа сайта.",
        "Остановка — Ctrl+C, прогресс останется в базе.",
    ]))
    workers = _ask_workers()
    if workers is None:
        return
    try:
        asyncio.run(run_gm_loop(workers))
    except KeyboardInterrupt:
        logger.log("GM-цикл остановлен (Ctrl+C). Прогресс сохранён в базе.",
                   "warning")


def _handle_collect_stats() -> None:
    if not _ensure_db():
        return
    workers = _ask_workers()
    if workers is None:
        return
    results = asyncio.run(run_stats(workers))
    if results:
        ui.print_lines(_accounts_panel(results))


def _handle_export() -> None:
    export_results()


# ── Панели ───────────────────────────────────────────────────────────────

# Колонки таблицы аккаунтов: адрес, множитель, рефералы, очки.
_COLUMNS = ((12, "адрес"), (8, "xBoost"), (11, "рефералов"), (8, "очков"))


def _accounts_panel(results: list[dict]) -> str:
    """Собранная с сайта статистика по каждому аккаунту."""
    widths = [width for width, _ in _COLUMNS]
    head = "  ".join(
        ui.fit(title, width, "left" if i == 0 else "right")
        for i, (width, title) in enumerate(_COLUMNS)
    )
    lines = [f"{theme.FG_MUTED}{head}{theme.RESET}"]

    for row in results:
        stats = row.get("stats") or {}
        xboost = stats.get("xboost_multiplier") or stats.get("xboost") or "?"
        points = stats.get("total_points") or stats.get("today_points", 0)
        lines.append(
            f"{ui.fit(ui.shorten_address(row.get('address', '?')), widths[0])}  "
            f"{theme.FG_OK}{ui.fit(f'x{xboost}', widths[1], 'right')}"
            f"{theme.RESET}  "
            f"{theme.FG_WARN}"
            f"{ui.fit(str(stats.get('referrals_count', 0)), widths[2], 'right')}"
            f"{theme.RESET}  "
            f"{theme.FG_INFO}{ui.fit(str(points), widths[3], 'right')}"
            f"{theme.RESET}"
        )
    return ui.panel("Статистика аккаунтов", lines)


def _stats() -> dict:
    """Состояние базы в порядке жизненного цикла кошелька."""
    raw = db.get_db_stats()
    next_gm = db.get_next_gm_time()
    return {
        "зарегистрировано": raw.get("evm_registered", 0),
        "подключено Solana": raw.get("sol_connected", 0),
        "отметок GM": raw.get("total_gm", 0),
        "реферальных кодов": raw.get("referral_codes", 0),
        "ближайший GM": next_gm[:16] if next_gm else "—",
        "total": raw.get("total_wallets", 0),
    }


def _info() -> dict:
    return {
        "Как это работает": [
            "Кошельки берутся из data/data.csv по полю private_key и перед "
            "каждым запуском синхронизируются с базой.",
            "Регистрация подписывает сообщение EVM-ключом и привязывает "
            "реферальный код: сначала из data.csv, иначе случайный из уже "
            "собранных — с балансировкой по числу использований.",
            "Solana подключается отдельным шагом и только тем кошелькам, у "
            "которых заполнен sol_private_key.",
            f"Say GM повторяется по кулдауну сайта, примерно раз в "
            f"{GM_COOLDOWN_HOURS} ч; точное время следующей отметки приходит "
            f"в ответе и хранится в базе.",
            "Авто-режим ведёт цикл сам: регистрирует новых, подключает Solana "
            "и отмечается, пока его не прервут Ctrl+C.",
        ],
        "Где что лежит": [
            f"База: db/{Path(db.DB_FILE).name}",
            "Кошельки и статусы: таблица wallets",
            "Реферальные коды: таблица referral_codes",
            "История отметок: таблица gm_history",
            "Отчёт: result/xstocks/xstocks_<время>.xlsx",
        ],
    }


def xstocks_menu() -> None:
    ModuleMenu(
        title="xStocks DeFi Points",
        subtitle="регистрация, Solana и ежедневный GM",
        icon="📈",
        actions=[
            MenuAction("full_auto", "Авто-режим", _handle_full_auto,
                       "регистрация, Solana и GM по кругу", icon="🤖"),
            MenuAction("register", "Регистрация", _handle_register,
                       "завести EVM-кошельки на сайте", icon="✅"),
            MenuAction("connect_sol", "Подключение Solana", _handle_connect_sol,
                       "привязать Solana-кошельки к аккаунтам", icon="☀️"),
            MenuAction("gm_once", "Отметка GM", _handle_gm_once,
                       "отметить всех, у кого прошёл кулдаун", icon="🌅"),
            MenuAction("gm_loop", "Отметка GM по кругу", _handle_gm_loop,
                       "повторять отметку по кулдауну сайта", icon="🔄"),
            MenuAction("collect", "Сбор статистики", _handle_collect_stats,
                       "обновить xBoost, рефералов и очки с сайта", icon="🔎"),
            MenuAction("export", "Экспорт отчёта", _handle_export,
                       "Excel по данным из базы", icon="📑"),
        ],
        stats=_stats,
        stats_title=f"Прогресс · {Path(db.DB_FILE).name}",
        info=_info,
    ).run()


__all__ = ["xstocks_menu", "load_wallets"]
