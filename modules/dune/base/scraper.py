"""Playwright-скрейпер дашборда Base Network Analytics (Dune).

Работает БЕЗ API-ключа: открывает публичный дашборд
https://dune.com/nvthao/base-network-analytics-dashboard в патченом Chromium
(``patchright`` — обходит Cloudflare challenge), вводит адрес в строку поиска
каждой таблицы и парсит найденную строку (или «No results match»).

Окно запускается *offscreen* (позиция −32000,−32000) — визуально незаметно
для пользователя, но браузер остаётся "видимым" для Cloudflare, что нужно
для успешного прохождения JS-проверки.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from patchright.sync_api import (
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)

DASHBOARD_URL = "https://dune.com/nvthao/base-network-analytics-dashboard"

# По заголовкам таблиц из дашборда
RANKING_HEADER = "rank_tx"
VOLUME_HEADER = "rank_native_vl"

_BROWSER_ARGS = [
    "--window-position=-32000,-32000",
    "--window-size=1366,900",
    "--no-first-run",
    "--no-default-browser-check",
]


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
    """Один offscreen-браузер Chrome + одна вкладка.

    Для каждого прокси создаётся новый browser-context (Cloudflare-сессия
    пере-инициализируется). Если прокси не меняется между кошельками,
    контекст переиспользуется.
    """

    def __init__(
        self,
        headless_offscreen: bool = True,
        nav_timeout_ms: int = 90_000,
        search_debounce_sec: float = 1.2,
        search_wait_sec: float = 10.0,
    ) -> None:
        self._pw: Optional[Playwright] = None
        self._browser = None
        self._context = None
        self._page: Optional[Page] = None
        self._current_proxy: Optional[str] = None

        self._headless_offscreen = headless_offscreen
        self._nav_timeout_ms = nav_timeout_ms
        self._search_debounce_sec = search_debounce_sec
        self._search_wait_sec = search_wait_sec

    # ───────────────────────── lifecycle ─────────────────────────

    def start(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=False,
            channel="chrome",
            args=_BROWSER_ARGS if self._headless_offscreen else [],
        )

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

        if self._browser is None:
            raise RuntimeError("Scraper не запущен — вызовите .start() перед search()")

        self._context = self._browser.new_context(**ctx_kwargs)
        self._page = self._context.new_page()
        self._current_proxy = proxy_raw

        self._page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=self._nav_timeout_ms)

        # Ждём, пока Cloudflare отпустит и таблицы отрендерятся
        self._page.wait_for_selector(
            f"thead th:has-text('{RANKING_HEADER}')", timeout=self._nav_timeout_ms
        )
        self._page.wait_for_selector(
            f"thead th:has-text('{VOLUME_HEADER}')", timeout=self._nav_timeout_ms
        )
        # Ждём, пока в каждой таблице появятся реальные строки (не только заголовки)
        try:
            self._page.wait_for_function(
                "() => document.querySelectorAll('table tbody tr').length >= 10",
                timeout=30_000,
            )
        except PWTimeoutError:
            pass
        time.sleep(1.5)

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
        try:
            ranking = self._query_table(RANKING_HEADER, address)
            volume = self._query_table(VOLUME_HEADER, address)
        finally:
            # Сбрасываем поля поиска, чтобы следующий запрос стартовал с чистого виджета
            self._clear_all_searches()
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

    def _query_table(self, header_text: str, address: str) -> Optional[Dict[str, str]]:
        for attempt in range(2):
            result = self._query_table_once(header_text, address)
            if result is not None:
                return result
            # Если None — проверим, действительно ли "No results", иначе повторим
            if self._page is not None and self._has_no_results(header_text):
                return None
            # Лёгкий reset между попытками
            time.sleep(0.8)
        return None

    def _has_no_results(self, header_text: str) -> bool:
        assert self._page is not None
        try:
            widget = self._page.locator(
                f"xpath=//thead//th[contains(normalize-space(.), '{header_text}')]"
                f"/ancestor::*[.//input[@placeholder='Search...']][1]"
            ).first
            return "No results match" in widget.inner_text(timeout=2000)
        except Exception:  # noqa: BLE001
            return False

    def _query_table_once(self, header_text: str, address: str) -> Optional[Dict[str, str]]:
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
            # Виджет в плохом состоянии — мягко перезагружаем страницу
            page.reload(wait_until="domcontentloaded", timeout=self._nav_timeout_ms)
            page.wait_for_selector(
                f"thead th:has-text('{RANKING_HEADER}')", timeout=self._nav_timeout_ms
            )
            page.wait_for_selector(
                f"thead th:has-text('{VOLUME_HEADER}')", timeout=self._nav_timeout_ms
            )
            time.sleep(1.0)
            box = widget.locator("input[placeholder='Search...']").first
            box.wait_for(state="visible", timeout=15_000)

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
                return None
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
                return None
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
