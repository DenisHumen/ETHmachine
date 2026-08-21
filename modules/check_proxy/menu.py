"""Интерактивный чекер прокси: выбор уровня детализации и запуск.

Это не обычное меню модуля, а мастер: уровень → сколько прокси → потоки →
прогон. Поэтому здесь не ``ModuleMenu``, а прямые вызовы UI-набора.
"""

from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List

from modules.simple_logger import logger, setup_file_logging
from modules.proxy_manager import load_proxies
from modules.ui import ui
from modules.ui.menu_model import BACK_KEY, MenuItem

from config.modules.general_config import NUM_THREADS

from .database import ProxyCheckerDB
from .excel_export import export_run_to_xlsx
from .tester import run_proxy_test


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "log"

# Уровень детализации: название и что добавляется к предыдущему уровню.
_LEVELS = {
    1: ("Уровень 1 · базовый", "доступность, задержка, страна и IP"),
    2: ("Уровень 2 · стандарт", "плюс сайты и соцсети, факт блокировок"),
    3: ("Уровень 3 · расширенный",
        "плюс криптобиржи, CoinGecko, Etherscan, RPC-узлы"),
    4: ("Уровень 4 · максимум",
        "плюс скорость, джиттер и тайминги соединения"),
}

# На четвёртом уровне speed-test тяжёлый — потоков нужно заметно меньше.
_THREAD_CAP = {4: 20}
_DEFAULT_THREAD_CAP = 80


def _setup_logging(level: int) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"proxy_checker_L{level}_{ts}.log"
    setup_file_logging(str(log_file))
    logger.info(f"Логи проверки прокси: {log_file}")


def _ask_level() -> int | None:
    """Уровень детализации 1..4. ``None`` — пользователь отказался."""
    items = [
        MenuItem(str(level), title, description, icon="🔹")
        for level, (title, description) in _LEVELS.items()
    ]
    items.append(MenuItem(BACK_KEY, "Назад", icon="←"))

    choice = ui.show_items("🛰️ Проверка прокси — уровень детализации", items)
    if choice in (None, BACK_KEY):
        return None
    return int(choice)


def check_proxy_menu() -> None:
    """Точка входа: спрашивает параметры прогона и запускает проверку."""
    level = _ask_level()
    if level is None:
        return

    _setup_logging(level)

    proxies: List[str] = load_proxies()
    if not proxies:
        logger.error("Прокси не найдены — проверьте поле proxy в data.csv")
        ui.pause()
        return

    total_found = len(proxies)
    max_n = ui.ask_int("Сколько прокси проверить", minimum=1,
                       maximum=total_found, default=total_found)
    if max_n is None:
        return
    proxies = proxies[:max_n]

    cap = _THREAD_CAP.get(level, _DEFAULT_THREAD_CAP)
    threads = ui.ask_int("Потоков", minimum=1, maximum=cap,
                         default=min(NUM_THREADS, cap))
    if threads is None:
        return

    db = ProxyCheckerDB()
    run_id = db.create_run(level=level, threads=threads, proxies=proxies)

    ui.print_lines(ui.info_panel("Проверка прокси", {
        _LEVELS[level][0]: [
            f"L{step} · {_LEVELS[step][1]}" for step in range(1, level + 1)
        ],
        "Параметры": [
            f"Прокси в работе: {len(proxies)} из {total_found} найденных",
            f"Потоков: {threads}",
        ],
    }, footer=f"Прогон #{run_id} · {db.path.name}"))

    _run(db, run_id, level, proxies, threads)
    ui.pause()


def _run(db: ProxyCheckerDB, run_id: int, level: int,
         proxies: List[str], threads: int) -> None:
    """Прогон по всем прокси: результаты пишутся в базу по мере готовности."""
    start_ts = time.time()
    completed = working = partial = broken = 0

    try:
        with ThreadPoolExecutor(max_workers=threads) as executor:
            future_map = {}
            for idx, p in enumerate(proxies, start=1):
                task_id = db.get_task_id(run_id, idx)
                db.mark_task_running(task_id)
                fut = executor.submit(_run_one, p, level)
                future_map[fut] = (idx, p, task_id)

            for fut in as_completed(future_map):
                idx, proxy, task_id = future_map[fut]
                try:
                    summary = fut.result()
                except Exception as e:
                    logger.error(f"❌ #{idx} {proxy[:30]} — исключение: {e}")
                    summary = {
                        "overall": "BROKEN",
                        "score": 0.0,
                        "service_results": [],
                        "details": {"exception": traceback.format_exc()[:2000]},
                        "error": f"{type(e).__name__}: {e!s}"[:240],
                        "failed_stage": "task_exception",
                    }

                db.save_task_result(task_id, run_id, summary)
                db.save_service_results(task_id, run_id, proxy, summary.get("service_results", []))
                db.increment_completed(run_id)
                completed += 1

                ov = summary.get("overall")
                if ov == "WORKING":
                    working += 1
                elif ov == "PARTIAL":
                    partial += 1
                else:
                    broken += 1

                _log_progress(idx, len(proxies), completed, summary)

    except KeyboardInterrupt:
        logger.warning("⏹️ Прервано пользователем — фиксируем частичные результаты")
        db.finalize_run(run_id, working, partial, broken, status="interrupted")
        _show_summary(level, start_ts, completed, working, partial, broken,
                      title_suffix="прервано")
        try:
            xlsx = export_run_to_xlsx(db, run_id)
            logger.info(f"📊 Частичный отчёт: {xlsx}")
        except Exception as e:
            logger.error(f"Ошибка экспорта: {e}")
        return

    _show_summary(level, start_ts, completed, working, partial, broken)

    try:
        xlsx = export_run_to_xlsx(db, run_id)
        db.finalize_run(run_id, working, partial, broken, excel_path=str(xlsx))
        logger.success(f"📊 Excel-отчёт: {xlsx}")
    except Exception as e:
        logger.error(f"❌ Ошибка экспорта Excel: {e}")
        db.finalize_run(run_id, working, partial, broken, status="export_failed")


# ──────────────────────────────────────────────────────────────────────────────

def _show_summary(level: int, start_ts: float, completed: int,
                  working: int, partial: int, broken: int,
                  title_suffix: str = "") -> None:
    # Прогон может уложиться в доли секунды — защищаемся от деления на ноль.
    duration = max(round(time.time() - start_ts, 2), 0.01)
    title = f"Итог проверки · L{level}"
    if title_suffix:
        title = f"{title} ({title_suffix})"
    ui.print_lines(ui.stats_panel(
        title,
        {"рабочие": working, "частично": partial, "нерабочие": broken,
         "total": completed},
        footer=f"{duration} с · {completed / duration:.2f} прокси/с",
    ))


def _run_one(proxy: str, level: int) -> dict:
    """Обёртка для submit() — ловит исключения тестера."""
    try:
        return run_proxy_test(proxy, level)
    except Exception as e:
        return {
            "overall": "BROKEN",
            "score": 0.0,
            "service_results": [],
            "details": {"trace": traceback.format_exc()[:2000]},
            "error": f"{type(e).__name__}: {e!s}"[:240],
            "failed_stage": "tester_exception",
        }


def _log_progress(idx: int, total: int, completed: int, summary: dict) -> None:
    pct = completed / total * 100
    ov = summary.get("overall", "?")
    score = summary.get("score", 0)
    country = summary.get("country") or "??"
    lat = summary.get("avg_latency")
    extra = f" | {country}, {lat}ms" if lat else f" | {country}"
    icon = {"WORKING": "✅", "PARTIAL": "⚠️", "BROKEN": "❌"}.get(ov, "•")
    logger.info(f"{icon} [{completed}/{total} {pct:5.1f}%] #{idx} {ov} {score:.0f}%{extra}")


__all__ = ["check_proxy_menu"]


if __name__ == "__main__":
    check_proxy_menu()
