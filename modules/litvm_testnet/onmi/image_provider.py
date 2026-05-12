"""Загрузка и подготовка картинки для onmi.fun coin.

Требования сайта:
  • Формат: JPG / PNG / GIF (мы используем JPEG для гарантированного <1 MB).
  • Минимум: 1000 × 1000 px.
  • Аспект: 1:1.
  • Размер: max 1 MB.

Алгоритм:
  1. Берём случайный запрос из `ONMI_PINTEREST_QUERIES`.
  2. Поднимаем `PinterestClient` (guest mode) и выгребаем URL'ы.
  3. Скачиваем картинку через прокси.
  4. PIL: center-crop в квадрат, resize до 1000×1000, JPEG quality.
  5. Если файл > 1 MB — снижаем quality итеративно, в крайнем случае — размер.
"""
from __future__ import annotations

import io
import os
import random
import time
import uuid
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

from config.modules.cfg_litvm_testnet import (
    ONMI_IMAGE_FETCH_ATTEMPTS,
    ONMI_IMAGE_JPEG_QUALITY,
    ONMI_IMAGE_MAX_BYTES,
    ONMI_IMAGE_SIDE,
    ONMI_PINTEREST_QUERIES,
)
from modules.proxy_manager import parse_proxy


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CACHE_DIR = REPO_ROOT / "result" / "onmi" / "image_cache"


class ImageError(Exception):
    pass


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _session_with_proxy(proxy: Optional[str]) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    parsed = parse_proxy(proxy) if proxy else None
    if parsed:
        s.proxies = {"http": parsed, "https": parsed}
    return s


def _search_pinterest_urls(query: str, proxy: Optional[str], *,
                           limit: int = 30) -> list[str]:
    """Guest-mode поиск через PinterestClient. Возвращает список URL'ов."""
    # Импортируем здесь, чтобы тяжёлый модуль не грузился при импорте onmi.
    from modules.pinterest_downloader import PinterestClient

    client = PinterestClient(email="", password="", proxy=proxy)
    try:
        if not client.login():
            raise ImageError("pinterest login/guest failed")
        urls, _ = client.search_images(query, "")
        # перемешаем, чтобы не брать всегда первую
        random.shuffle(urls)
        return urls[:limit]
    finally:
        try:
            client.close()
        except Exception:
            pass


def _download_bytes(session: requests.Session, url: str,
                    timeout: int = 25) -> Optional[bytes]:
    urls_to_try = [url]
    if "/originals/" in url:
        urls_to_try.append(url.replace("/originals/", "/736x/"))
    for u in urls_to_try:
        try:
            r = session.get(u, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "")
            if "image" not in ct and "octet-stream" not in ct:
                continue
            data = r.content
            if len(data) < 2000:
                continue
            return data
        except Exception:
            continue
    return None


def _square_resize_to_jpeg(raw: bytes, *, side: int, quality: int,
                           max_bytes: int) -> bytes:
    """Center-crop в квадрат, resize, конвертация в JPEG.

    Если файл > `max_bytes` — снижаем quality (до 50), затем уменьшаем side
    (до side//2). Кидаем ImageError если не удалось уложиться."""
    img = Image.open(io.BytesIO(raw))
    if img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    # центральный квадрат
    s = min(w, h)
    left = (w - s) // 2
    top = (h - s) // 2
    img = img.crop((left, top, left + s, top + s))
    img = img.resize((side, side), Image.Resampling.LANCZOS)

    cur_side = side
    cur_quality = int(quality)
    for _ in range(10):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=cur_quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= max_bytes:
            return data
        # снижаем качество
        if cur_quality > 50:
            cur_quality = max(50, cur_quality - 10)
            continue
        # уменьшаем размер (но не ниже 1000)
        if cur_side > 1000:
            cur_side = max(1000, cur_side - 200)
            img = img.resize((cur_side, cur_side), Image.Resampling.LANCZOS)
            cur_quality = int(quality)
            continue
        break
    raise ImageError(
        f"image > {max_bytes} bytes даже при quality=50 / side={cur_side}"
    )


def fetch_and_prepare_image(
    *,
    proxy: Optional[str] = None,
    query: Optional[str] = None,
) -> tuple[Path, str]:
    """Возвращает (filepath, source_url). Файл — JPEG ≥ 1000×1000, ≤ 1 MB.

    Бросает ImageError если все попытки провалились.
    """
    _ensure_cache_dir()
    queries = list(ONMI_PINTEREST_QUERIES) if not query else [query]
    random.shuffle(queries)

    last_err: Optional[str] = None
    for attempt_query in queries:
        try:
            urls = _search_pinterest_urls(attempt_query, proxy, limit=20)
        except Exception as e:
            last_err = f"search '{attempt_query}': {e}"
            continue
        if not urls:
            last_err = f"search '{attempt_query}': no urls"
            continue

        session = _session_with_proxy(proxy)
        try:
            tried = 0
            for url in urls:
                if tried >= int(ONMI_IMAGE_FETCH_ATTEMPTS):
                    break
                tried += 1
                raw = _download_bytes(session, url)
                if not raw:
                    continue
                try:
                    jpeg = _square_resize_to_jpeg(
                        raw,
                        side=int(ONMI_IMAGE_SIDE),
                        quality=int(ONMI_IMAGE_JPEG_QUALITY),
                        max_bytes=int(ONMI_IMAGE_MAX_BYTES),
                    )
                except ImageError as e:
                    last_err = str(e)
                    continue
                fname = f"onmi_{int(time.time())}_{uuid.uuid4().hex[:8]}.jpg"
                fpath = CACHE_DIR / fname
                with open(fpath, "wb") as f:
                    f.write(jpeg)
                return fpath, url
        finally:
            session.close()
    raise ImageError(f"не удалось получить картинку (last: {last_err})")


def cleanup_local_image(path: Path) -> None:
    try:
        if path and Path(path).exists():
            os.remove(path)
    except Exception:
        pass
