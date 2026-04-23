"""Playwright-скрейпер дашборда Base Network Analytics (Dune).

Работает БЕЗ API-ключа: открывает публичный дашборд
https://dune.com/nvthao/base-network-analytics-dashboard в патченом Chromium
(``patchright`` — обходит Cloudflare challenge), вводит адрес в строку поиска
каждой таблицы и парсит найденную строку (или «No results match»).

По умолчанию окно запускается видимым (пользователь видит, что происходит).
Чтобы уводить окно offscreen (−32000,−32000) — задайте переменную окружения
``DUNE_BASE_OFFSCREEN=1`` или передайте ``offscreen=True`` в конструктор.

Подробное логирование каждого шага (nav → ожидание таблиц → ввод адреса →
парсинг) идёт через ``modules.simple_logger.logger`` — если чекер «застрял»,
в консоли будет видно, на каком именно шаге.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from patchright.sync_api import (
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)

from modules.simple_logger import logger

DASHBOARD_URL = "https://dune.com/nvthao/base-network-analytics-dashboard"

# По заголовкам таблиц из дашборда
RANKING_HEADER = "rank_tx"
VOLUME_HEADER = "rank_native_vl"

_DEBUG_DIR = Path(__file__).resolve().parents[3] / "result" / "dune" / "debug"

# Сентинел «точно нет в лидерборде» (дашборд показал «No results match …»).
# Отличается от None (который означает «не удалось определить, можно ретрайнуть»).
# На границе публичного API (search()) конвертируется обратно в None.
_NO_RESULTS: Any = object()


def _offscreen_args() -> list[str]:
    return [
        "--window-position=-32000,-32000",
        "--window-size=1366,900",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def _visible_args() -> list[str]:
    return [
        "--window-size=1366,900",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def _env_truthy(name: str) -> bool:
    val = (os.environ.get(name) or "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _parse_proxy_for_browser(proxy_raw: Optional[str]) -> Optional[Dict[str, str]]:
    """`USER:PASS@IP:PORT` → dict для patchright ``context.proxy``."""
    if not proxy_raw:
        return None
    p = proxy_raw.strip()
    if not p:
        return None
    for pref in ("http://", "https://"):
        if p.startswith(pref):
            p = p[len(pref):]
            break
    try:
        if "@" in p:
            auth, addr = p.split("@", 1)
            user, pwd = auth.split(":", 1)
            return {"server": f"http://{addr}", "username": user, "password": pwd}
        return {"server": f"http://{p}"}
    except Exception:  # noqa: BLE001
        return None


class DuneBaseScraper:
    """Один браузер Chrome + одна вкладка.

    Для каждого прокси создаётся новый browser-context (Cloudflare-сессия
    пере-инициализируется). Если прокси не меняется между кошельками,
    контекст переиспользуется.
    """

    def __init__(
        self,
        offscreen: Optional[bool] = None,
        nav_timeout_ms: int = 60_000,
        dashboard_ready_timeout_ms: int = 45_000,
        search_debounce_sec: float = 1.2,
        search_wait_sec: float = 10.0,
        verbose: Optional[bool] = None,
    ) -> None:
        self._pw: Optional[Playwright] = None
        self._browser = None
        self._context = None
        self._page: Optional[Page] = None
        self._current_proxy: Optional[str] = None

        # По умолчанию показываем окно, чтобы пользователь видел прогресс.
        # Уводим offscreen только по явному запросу (env/конструктор).
        if offscreen is None:
            offscreen = _env_truthy("DUNE_BASE_OFFSCREEN")
        self._offscreen = offscreen
        # Подробные info-логи скрейпера выключены по умолчанию, чтобы не
        # шуметь поверх прогресс-бара. Включаются через DUNE_BASE_VERBOSE=1.
        if verbose is None:
            verbose = _env_truthy("DUNE_BASE_VERBOSE")
        self._verbose = verbose
        self._nav_timeout_ms = nav_timeout_ms
        self._dashboard_ready_timeout_ms = dashboard_ready_timeout_ms
        self._search_debounce_sec = search_debounce_sec
        self._search_wait_sec = search_wait_sec

    def _vlog(self, msg: str) -> None:
        """Информационный лог только в verbose-режиме."""
        if self._verbose:
            logger.info(msg)

    # ───────────────────────── lifecycle ─────────────────────────

    def start(self) -> None:
        t0 = time.time()
        self._pw = sync_playwright().start()
        args = _offscreen_args() if self._offscreen else _visible_args()
        try:
            self._browser = self._pw.chromium.launch(
                headless=False,
                channel="chrome",
                args=args,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[scraper] channel=chrome недоступен ({exc}) — fallback на bundled Chromium"
            )
            self._browser = self._pw.chromium.launch(headless=False, args=args)
        self._vlog(f"[scraper] Chromium запущен за {time.time() - t0:.1f}с")

    def close(self) -> None:
        for obj_name in ("_context", "_browser"):
            obj = getattr(self, obj_name, None)
            if obj is not None:
                try:
                    obj.close()
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, obj_name, None)
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None

    def __enter__(self) -> "DuneBaseScraper":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ───────────────────────── context/page ─────────────────────────

    def _ensure_context(self, proxy_raw: Optional[str]) -> None:
        """Гарантирует активный `page` с нужным прокси и загруженным дашбордом."""
        if self._context is not None and self._current_proxy == proxy_raw and self._page is not None:
            return

        if self._context is not None:
            try:
                self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None
            self._page = None

        ctx_kwargs: Dict[str, Any] = {"viewport": {"width": 1366, "height": 900}}
        proxy = _parse_proxy_for_browser(proxy_raw)
        if proxy:
            ctx_kwargs["proxy"] = proxy
            self._vlog(f"[scraper] proxy = {proxy.get('server')}")
        else:
            self._vlog("[scraper] proxy = none (direct)")

        if self._browser is None:
            raise RuntimeError("Scraper не запущен — вызовите .start() перед search()")

        self._context = self._browser.new_context(**ctx_kwargs)
        self._page = self._context.new_page()
        self._page.set_default_timeout(self._nav_timeout_ms)
        self._page.set_default_navigation_timeout(self._nav_timeout_ms)
        self._current_proxy = proxy_raw

        t0 = time.time()
        try:
            self._page.goto(
                DASHBOARD_URL, wait_until="domcontentloaded",
                timeout=self._nav_timeout_ms,
            )
        except Exception as exc:  # noqa: BLE001
            self._dump_debug("goto_failed")
            raise RuntimeError(f"Не удалось открыть дашборд: {exc}") from exc

        self._wait_past_cloudflare()
        self._wait_dashboard_ready()
        logger.success(f"[scraper] Dune дашборд готов ({time.time() - t0:.1f}с)")

    def _wait_past_cloudflare(self, timeout_sec: float = 25.0) -> None:
        """Ждём, пока страница перестанет быть Cloudflare challenge page."""
        if self._page is None:
            return
        deadline = time.time() + timeout_sec
        seen_cf = False
        while time.time() < deadline:
            try:
                title = (self._page.title() or "").lower()
            except Exception:  # noqa: BLE001
                title = ""
            if "just a moment" not in title and "attention required" not in title:
                if seen_cf:
                    self._vlog("[scraper] Cloudflare challenge пройден")
                return
            seen_cf = True
            self._vlog(f"[scraper] Ожидание Cloudflare… '{title[:60]}'")
            time.sleep(1.5)
        logger.warning("[scraper] Cloudflare challenge висит слишком долго — продолжаем")

    def _wait_dashboard_ready(self) -> None:
        """Ждёт, что таблицы дашборда отрисовались."""
        assert self._page is not None
        try:
            self._page.wait_for_selector(
                f"thead th:has-text('{RANKING_HEADER}')",
                timeout=self._dashboard_ready_timeout_ms,
            )
        except PWTimeoutError:
            self._dump_debug("no_ranking_header")
            raise RuntimeError(
                f"Не дождался заголовка '{RANKING_HEADER}' за "
                f"{self._dashboard_ready_timeout_ms / 1000:.0f}с — "
                f"дашборд мог измениться или заблокирован Cloudflare. "
                f"Скриншот: result/dune/debug/"
            )
        try:
            self._page.wait_for_selector(
                f"thead th:has-text('{VOLUME_HEADER}')",
                timeout=self._dashboard_ready_timeout_ms,
            )
        except PWTimeoutError:
            self._dump_debug("no_volume_header")
            raise RuntimeError(
                f"Не дождался заголовка '{VOLUME_HEADER}' за "
                f"{self._dashboard_ready_timeout_ms / 1000:.0f}с"
            )
        # Ждём, пока в таблицах появятся строки (не только заголовки)
        try:
            self._page.wait_for_function(
                "() => document.querySelectorAll('table tbody tr').length >= 10",
                timeout=20_000,
            )
        except PWTimeoutError:
            self._vlog("[scraper] Таблицы есть, но строк <10 — продолжаю")
        time.sleep(1.2)

    def _dump_debug(self, tag: str) -> None:
        """Сохраняет скриншот + html текущей страницы в result/dune/debug/."""
        if self._page is None:
            return
        try:
            _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            png = _DEBUG_DIR / f"{tag}_{ts}.png"
            html = _DEBUG_DIR / f"{tag}_{ts}.html"
            try:
                self._page.screenshot(path=str(png), full_page=True, timeout=5000)
            except Exception:  # noqa: BLE001
                pass
            try:
                html.write_text(self._page.content(), encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                pass
            logger.warning(f"[scraper] Debug dump сохранён: {png.name}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[scraper] Не удалось сохранить debug dump: {exc}")

    # ───────────────────────── public ─────────────────────────

    def search(
        self,
        address: str,
        proxy_raw: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, str]]]:
        """Поиск адреса в обеих таблицах. Возвращает (ranking_row, volume_row).

        None для отсутствующего результата, dict {column: value} для найденного.
        """
        self._ensure_context(proxy_raw)
        short = address[:8] + "…" + address[-4:]

        def _label(res: Any) -> str:
            if res is _NO_RESULTS:
                return "NOT IN LEADERBOARD"
            if res:
                return "FOUND"
            return "not found"

        try:
            self._vlog(f"[scraper] {short}: поиск '{RANKING_HEADER}'")
            ranking = self._query_table(RANKING_HEADER, address)
            self._vlog(f"[scraper] {short}: ranking → {_label(ranking)}")
            self._vlog(f"[scraper] {short}: поиск '{VOLUME_HEADER}'")
            volume = self._query_table(VOLUME_HEADER, address)
            self._vlog(f"[scraper] {short}: volume → {_label(volume)}")
        finally:
            # Сбрасываем поля поиска, чтобы следующий запрос стартовал с чистого виджета
            self._clear_all_searches()

        # Нормализуем сентинел в None для внешнего API
        if ranking is _NO_RESULTS:
            ranking = None
        if volume is _NO_RESULTS:
            volume = None
        return ranking, volume

    def _clear_all_searches(self) -> None:
        """Чистит оба поля Search. Если виджет в состоянии "No results",
        после очистки он возвращается к отрисовке всех строк."""
        if self._page is None:
            return
        try:
            boxes = self._page.locator("input[placeholder='Search...']").all()
        except Exception:  # noqa: BLE001
            return
        for box in boxes:
            try:
                box.click(timeout=3000)
                box.press("Control+A")
                box.press("Delete")
                box.fill("")
            except Exception:  # noqa: BLE001
                continue

    # ───────────────────────── internals ─────────────────────────

    def _query_table(self, header_text: str, address: str) -> Any:
        """Возвращает:
        • dict — адрес найден в таблице;
        • `_NO_RESULTS` — дашборд показал «No results match …» (точно не в лидерборде);
        • None — не удалось определить (ретраиться не имеет смысла уже сверху).
        """
        for attempt in range(2):
            result = self._query_table_once(header_text, address)
            if result is _NO_RESULTS:
                return _NO_RESULTS
            if result is not None:
                return result
            # Последняя проверка через всю страницу: если где-то мелькнуло
            # "No results match your search for "<address>"" — точно не в лидерборде.
            if self._has_no_results(header_text, address):
                return _NO_RESULTS
            # Лёгкий reset между попытками
            time.sleep(0.8)
        return None

    def _has_no_results(self, header_text: str, address: Optional[str] = None) -> bool:
        """True, если виджет (или страница) содержит «No results match …».

        Если передан `address`, дополнительно ищем фразу по всей странице —
        так ловим случаи, когда локатор виджета перестал работать после
        ре-рендера, но текст «No results match your search for "0x…"» уже виден.
        """
        if self._page is None:
            return False
        # 1) Проверяем конкретный виджет
        try:
            widget = self._page.locator(
                f"xpath=//thead//th[contains(normalize-space(.), '{header_text}')]"
                f"/ancestor::*[.//input[@placeholder='Search...']][1]"
            ).first
            txt = widget.inner_text(timeout=2000)
            if "No results match" in txt:
                return True
        except Exception:  # noqa: BLE001
            pass
        # 2) Фоллбэк — ищем «No results match your search for "<address>"» во всей странице
        if address:
            try:
                needle = f'No results match your search for "{address}"'
                body_txt = self._page.locator("body").inner_text(timeout=3000)
                if needle in body_txt or needle.lower() in body_txt.lower():
                    return True
                # допустим случай, когда Dune экранирует кавычки иначе
                if "No results match" in body_txt and address.lower() in body_txt.lower():
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _query_table_once(self, header_text: str, address: str) -> Any:
        """Одна итерация поиска адреса в конкретной таблице.

        Возвращает:
          • dict — найдена строка (значения колонок);
          • `_NO_RESULTS` — дашборд показал «No results match …» (точно нет);
          • None — непонятное состояние, вызывающий код решает, ретраить или нет.
        """
        assert self._page is not None
        page = self._page
        addr_l = address.lower()

        widget = page.locator(
            f"xpath=//thead//th[contains(normalize-space(.), '{header_text}')]"
            f"/ancestor::*[.//input[@placeholder='Search...']][1]"
        ).first

        box = widget.locator("input[placeholder='Search...']").first
        try:
            box.wait_for(state="visible", timeout=10_000)
        except PWTimeoutError:
            # Перед reload — проверим, не «No results match» ли уже на странице
            # (такое бывает после предыдущего поиска, если виджет схлопнулся).
            if self._has_no_results(header_text, address):
                self._vlog(
                    f"[scraper] '{header_text}': already 'No results' для {address[:10]}…"
                )
                return _NO_RESULTS
            # Виджет в плохом состоянии — мягко перезагружаем страницу
            logger.warning(
                f"[scraper] Search-поле для '{header_text}' не появилось — reload"
            )
            page.reload(wait_until="domcontentloaded", timeout=self._nav_timeout_ms)
            self._wait_dashboard_ready()
            box = widget.locator("input[placeholder='Search...']").first
            try:
                box.wait_for(state="visible", timeout=15_000)
            except PWTimeoutError:
                if self._has_no_results(header_text, address):
                    return _NO_RESULTS
                raise

        box.scroll_into_view_if_needed()
        box.click()
        # Полный сброс значения
        try:
            box.press("Control+A")
            box.press("Delete")
        except Exception:  # noqa: BLE001
            pass
        box.fill("")
        box.type(address, delay=20)

        # Ждём, пока таблица обновится: либо «No results match», либо появится строка с адресом
        deadline = time.time() + self._search_wait_sec
        found = False
        while time.time() < deadline:
            time.sleep(0.25)
            try:
                txt = widget.inner_text(timeout=2000)
            except PWTimeoutError:
                continue
            except Exception:  # noqa: BLE001
                continue
            if "No results match" in txt:
                return _NO_RESULTS
            if addr_l[:10] in txt.lower():
                found = True
                break

        if not found:
            # Последний шанс: подождать debounce и перепроверить
            time.sleep(self._search_debounce_sec)
            txt = ""
            try:
                txt = widget.inner_text(timeout=2000)
            except Exception:  # noqa: BLE001
                pass
            if "No results match" in txt:
                return _NO_RESULTS
            # Страничный фоллбэк на случай, если виджет-локатор сломался
            if self._has_no_results(header_text, address):
                return _NO_RESULTS
            if addr_l[:10] not in (txt or "").lower():
                return None

        tbl = widget.locator("table").first
        headers = [h.strip() for h in tbl.locator("thead th").all_inner_texts()]

        rows = tbl.locator("tbody tr").all()
        for r in rows:
            cells = [c.strip() for c in r.locator("td").all_inner_texts()]
            if any(addr_l in (c or "").lower() for c in cells):
                if len(cells) < len(headers):
                    cells = cells + [""] * (len(headers) - len(cells))
                elif len(cells) > len(headers):
                    cells = cells[: len(headers)]
                return dict(zip(headers, cells))
        return None
