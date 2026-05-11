"""Интерактивное меню чекера прокси: выбор уровня детализации и запуск."""

from __future__ import annotations

import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List

from modules.simple_logger import logger, setup_file_logging
from modules.proxy_manager import load_proxies

from config.modules.general_config import NUM_THREADS

from .database import ProxyCheckerDB
from .excel_export import export_run_to_xlsx
from .tester import run_proxy_test


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "log"


_LEVEL_DESCRIPTIONS = {
    1: "Базовая проверка: alive, latency, страна/IP",
    2: "Стандарт: + популярные сайты и соцсети, факт блокировок",
    3: "Расширенная: + криптобиржи (Binance/OKX/Bybit/...), CoinGecko, Etherscan, EVM/Solana RPC",
    4: "Максимум: + speed-test, jitter и стадийные тайминги (DNS/TCP/TLS/TTFB)",
}


def _setup_logging(level: int) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"proxy_checker_L{level}_{ts}.log"
    setup_file_logging(str(log_file))
    logger.info(f"Логи проверки прокси: {log_file}")


def _ask_level() -> int:
    """Запросить уровень детализации 1..4."""
    try:
        from questionary import Choice, select
        choices = [
            Choice(f"  🔹 Уровень {lvl} — {desc}", lvl)
            for lvl, desc in _LEVEL_DESCRIPTIONS.items()
        ]
        choices.append(Choice("  🔙 Назад", "back"))
        ans = select(
            "\n╔══════════════════════════════════════════════════════════════╗\n"
            "║         🛠️  Проверка прокси / Уровень детализации             ║\n"
            "╚══════════════════════════════════════════════════════════════╝",
            choices=choices, qmark="🛠️", pointer="👉",
        ).ask()
        return ans if isinstance(ans, int) else "back"
    except Exception:
        # plain input fallback
        for lvl, desc in _LEVEL_DESCRIPTIONS.items():
            print(f"  {lvl}) {desc}")
        try:
            v = int(input("Выберите уровень (1-4): ").strip())
            return v if 1 <= v <= 4 else "back"
        except Exception:
            return "back"


def _ask_max_proxies(total: int) -> int:
    try:
        s = input(f"Сколько прокси проверить из {total}? Enter = все: ").strip()
        if not s:
            return total
        n = int(s)
        return max(1, min(n, total))
    except Exception:
        return total


def _ask_threads(default: int, level: int) -> int:
    # Под L4 не стоит давать слишком много потоков — speed-test тяжёлый
    cap = 20 if level >= 4 else 80
    suggested = min(default, cap)
    try:
        s = input(f"Потоков [{suggested}, max {cap}]: ").strip()
        if not s:
            return suggested
        n = int(s)
        return max(1, min(n, cap))
    except Exception:
        return suggested


def check_proxy_menu() -> None:
    """Точка входа. Показывает меню уровня детализации и запускает проверку."""
    level = _ask_level()
    if level == "back" or level is None:
        return
    if not isinstance(level, int) or not (1 <= level <= 4):
        logger.error("Некорректный уровень детализации")
        return

    _setup_logging(level)
    logger.info("=" * 70)
    logger.info(f"🚀 Запуск чекера прокси | Уровень: L{level}")
    logger.info(f"📋 Профиль: {_LEVEL_DESCRIPTIONS[level]}")
    logger.info("=" * 70)

    proxies: List[str] = load_proxies()
    if not proxies:
        logger.error("❌ Прокси не найдены — проверьте поле 'proxy' в data.csv")
        return
    logger.info(f"📂 Загружено {len(proxies)} прокси")

    max_n = _ask_max_proxies(len(proxies))
    if max_n < len(proxies):
        proxies = proxies[:max_n]
        logger.info(f"🔧 Ограничение: проверим первые {max_n}")

    threads = _ask_threads(NUM_THREADS, level)
    logger.info(f"🧵 Потоков: {threads}")

    db = ProxyCheckerDB()
    run_id = db.create_run(level=level, threads=threads, proxies=proxies)
    logger.info(f"🗄️  Run #{run_id} создан в БД ({db.path})")

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
        logger.warning("⏹️  Прервано пользователем — фиксируем частичные результаты")
        db.finalize_run(run_id, working, partial, broken, status="interrupted")
        try:
            xlsx = export_run_to_xlsx(db, run_id)
            logger.info(f"📊 Частичный отчёт: {xlsx}")
        except Exception as e:
            logger.error(f"Ошибка экспорта: {e}")
        return

    duration = round(time.time() - start_ts, 2)
    logger.info("=" * 70)
    logger.success(f"✅ Готово за {duration} c | {completed/duration:.2f} прокси/c")
    logger.info(f"   WORKING:  {working}")
    logger.info(f"   PARTIAL:  {partial}")
    logger.info(f"   BROKEN:   {broken}")
    logger.info("=" * 70)

    try:
        xlsx = export_run_to_xlsx(db, run_id)
        db.finalize_run(run_id, working, partial, broken, excel_path=str(xlsx))
        logger.success(f"📊 Excel-отчёт: {xlsx}")
    except Exception as e:
        logger.error(f"❌ Ошибка экспорта Excel: {e}")
        db.finalize_run(run_id, working, partial, broken, status="export_failed")


# ──────────────────────────────────────────────────────────────────────────────

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


if __name__ == "__main__":
    check_proxy_menu()
