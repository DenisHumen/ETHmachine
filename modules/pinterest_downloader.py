"""
Pinterest Random Image Downloader
Скачивает рандомные картинки из Pinterest через авторизованную сессию
или через гостевой доступ с правильной эмуляцией браузера.
"""
import os
import re
import json
import time
import uuid
import zipfile
import random
import requests
from typing import Optional, List, Tuple

from rich.progress import (
    Progress, BarColumn, TextColumn, DownloadColumn,
    TransferSpeedColumn, TimeRemainingColumn, SpinnerColumn,
)
from rich.console import Console

from modules.simple_logger import log_simple, log_task
from modules.proxy_manager import ProxyManager, parse_proxy
from config.modules.cfg_pinterest import (
    PINTEREST_EMAIL, PINTEREST_PASSWORD,
    PINTEREST_MAX_IMAGES, PINTEREST_DOWNLOAD_DELAY, PINTEREST_IMAGE_QUALITY,
)

console = Console()

SEARCH_QUERIES = [
    "aesthetic wallpaper", "nature photography", "abstract art",
    "digital art", "landscape", "minimal design", "neon lights",
    "space galaxy", "ocean waves", "mountain view", "sunset sky",
    "flowers macro", "urban photography", "street art", "cyberpunk",
    "anime art", "retro vintage", "watercolor painting", "forest",
    "animals wildlife", "architecture modern", "car photography",
    "food photography", "travel world", "portrait photography",
    "geometric patterns", "fantasy art", "dark aesthetic",
    "pastel colors", "graffiti art", "underwater photography",
]

RESULT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "result", "pinterest",
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_QUALITY_MAP = {"originals": "originals", "736x": "736x", "564x": "564x"}


class PinterestClient:
    """Клиент Pinterest: авторизация email/password + гостевой fallback."""

    BASE = "https://www.pinterest.com"

    def __init__(self, email: str = "", password: str = "", proxy: Optional[str] = None):
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        if proxy:
            parsed = parse_proxy(proxy)
            if parsed:
                self.session.proxies = {"http": parsed, "https": parsed}

        self._app_version = ""
        self._csrf = ""
        self._logged_in = False

    def _init_session(self) -> bool:
        """Получить cookies, CSRF и app_version с главной страницы."""
        try:
            resp = self.session.get(f"{self.BASE}/", timeout=15)
            resp.raise_for_status()

            match = re.search(r'"appVersion":"([^"]+)"', resp.text)
            self._app_version = match.group(1) if match else ""
            self._csrf = self.session.cookies.get("csrftoken", "")

            if not self._csrf:
                log_simple("Не удалось получить CSRF токен", status="error", account_name="Pinterest")
                return False
            return True
        except Exception as e:
            log_simple(f"Ошибка инициализации сессии: {e}", status="error", account_name="Pinterest")
            return False

    def _setup_api_headers(self, source_url: str = "/", handler: str = "www/index.js"):
        """Настроить заголовки для API запросов."""
        self.session.headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": self._csrf,
            "X-APP-VERSION": self._app_version,
            "X-Pinterest-AppState": "active",
            "X-Pinterest-Source-Url": source_url,
            "X-Pinterest-PWS-Handler": handler,
            "Referer": f"{self.BASE}{source_url}",
            "Origin": self.BASE,
        })

    def login(self) -> bool:
        """Авторизация на Pinterest через email/password."""
        if not self._init_session():
            return False

        if not self.email or not self.password:
            log_simple("Логин/пароль не указаны, работаем в гостевом режиме", status="warning", account_name="Pinterest")
            return self._init_guest_mode()

        try:
            # Посетить страницу логина
            self.session.get(f"{self.BASE}/login/", timeout=15)
            self._csrf = self.session.cookies.get("csrftoken", self._csrf)

            self._setup_api_headers("/login/", "www/login.js")
            self.session.headers["Content-Type"] = "application/x-www-form-urlencoded"

            login_data = {
                "source_url": "/login/",
                "data": json.dumps({
                    "options": {
                        "username_or_email": self.email,
                        "password": self.password,
                    },
                    "context": {},
                }),
            }

            resp = self.session.post(
                f"{self.BASE}/resource/UserSessionResource/create/",
                data=login_data,
                timeout=15,
            )

            # Убрать Content-Type чтобы не мешал GET запросам
            self.session.headers.pop("Content-Type", None)

            if resp.status_code == 200:
                data = resp.json()
                error = data.get("resource_response", {}).get("error")
                if error:
                    msg = error.get("message", str(error))
                    # Аккаунт через Google — fallback на гостевой режим
                    if "Google" in msg or "connected" in msg:
                        log_simple(
                            f"Аккаунт привязан к Google. Работаем в гостевом режиме",
                            status="warning", account_name="Pinterest",
                        )
                        return self._init_guest_mode()
                    log_simple(f"Ошибка авторизации: {msg}", status="error", account_name="Pinterest")
                    return False

                self._csrf = self.session.cookies.get("csrftoken", self._csrf)
                self._logged_in = True
                log_simple("Авторизация успешна!", status="success", account_name="Pinterest")
                return True
            else:
                log_simple(f"Ошибка авторизации: HTTP {resp.status_code}", status="error", account_name="Pinterest")
                # Fallback
                return self._init_guest_mode()

        except Exception as e:
            log_simple(f"Ошибка при авторизации: {e}", status="error", account_name="Pinterest")
            return self._init_guest_mode()

    def _init_guest_mode(self) -> bool:
        """Инициализация гостевого режима — работает без логина."""
        try:
            if not self._csrf:
                if not self._init_session():
                    return False
            log_simple("Гостевой режим активирован", status="info", account_name="Pinterest")
            return True
        except Exception:
            return False

    def _visit_search_page(self, query: str):
        """Посетить HTML страницу поиска для получения правильных cookies."""
        try:
            # Временно вернуть HTML Accept
            old_accept = self.session.headers.get("Accept", "")
            self.session.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            self.session.headers.pop("X-Requested-With", None)

            self.session.get(
                f"{self.BASE}/search/pins/?q={requests.utils.quote(query)}",
                timeout=15,
            )
            self._csrf = self.session.cookies.get("csrftoken", self._csrf)

            self.session.headers["Accept"] = old_accept
        except Exception:
            pass

    def search_images(self, query: str, bookmark: str = "") -> Tuple[List[str], str]:
        """Поиск картинок через Pinterest API."""
        image_urls: list[str] = []
        new_bookmark = ""
        quality = _QUALITY_MAP.get(PINTEREST_IMAGE_QUALITY, "originals")

        source_url = f"/search/pins/?q={requests.utils.quote(query)}"

        # Посещаем HTML страницу поиска перед API запросом (нужно для cookies)
        if not bookmark:
            self._visit_search_page(query)

        self._setup_api_headers(source_url, "www/search/[scope].js")

        options = {
            "query": query,
            "scope": "pins",
            "bookmarks": [bookmark] if bookmark else [],
            "field_set_key": "unauth_react",
        }

        params = {
            "source_url": source_url,
            "data": json.dumps({"options": options, "context": {}}),
            "_": str(int(time.time() * 1000)),
        }

        try:
            resp = self.session.get(
                f"{self.BASE}/resource/BaseSearchResource/get/",
                params=params,
                timeout=15,
            )
            if resp.status_code != 200:
                return image_urls, new_bookmark

            data = resp.json()
            resource = data.get("resource_response", {})
            results = resource.get("data", {}).get("results", [])
            new_bookmark = resource.get("bookmark", "")

            for pin in results:
                if not isinstance(pin, dict):
                    continue

                images = pin.get("images", {})
                url = ""

                # Приоритет: orig > 736x > 564x > 474x
                for size_key in ["orig", "736x", "564x", "474x"]:
                    size_data = images.get(size_key, {})
                    url = size_data.get("url", "")
                    if url:
                        break

                if url and url.startswith("http"):
                    # Конвертируем в нужное качество
                    if quality == "originals":
                        for sz in ["736x", "564x", "474x"]:
                            if f"/{sz}/" in url:
                                url = url.replace(f"/{sz}/", "/originals/")
                                break
                    elif f"/{quality}/" not in url:
                        url = re.sub(r"/(originals|736x|564x|474x)/", f"/{quality}/", url)

                    image_urls.append(url)

        except Exception as e:
            log_simple(f"Ошибка поиска '{query}': {e}", status="warning", account_name="Pinterest")

        return image_urls, new_bookmark

    def close(self):
        self.session.close()


def _collect_image_urls(client: PinterestClient, count: int) -> List[str]:
    """Собрать URL картинок через поиск по нескольким запросам."""
    all_urls: list[str] = []
    seen: set[str] = set()

    num_queries = min(len(SEARCH_QUERIES), max(3, count // 10 + 3))
    queries = random.sample(SEARCH_QUERIES, num_queries)

    with console.status("[bold cyan]Поиск картинок на Pinterest...[/]", spinner="dots"):
        for query in queries:
            if len(all_urls) >= count * 2:
                break

            bookmark = ""
            query_count = 0
            for _page in range(5):
                urls, bookmark = client.search_images(query, bookmark)
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        all_urls.append(u)
                        query_count += 1

                if not bookmark or len(all_urls) >= count * 2:
                    break
                time.sleep(random.uniform(0.5, 1.2))

            if query_count > 0:
                log_simple(
                    f"'{query}': +{query_count} картинок (всего: {len(all_urls)})",
                    status="success", account_name="Pinterest",
                )

    random.shuffle(all_urls)
    return all_urls[:count * 3]


def _download_image(session: requests.Session, url: str, filepath: str) -> bool:
    """Скачать картинку. Fallback на 736x если originals недоступен."""
    urls_to_try = [url]
    if "/originals/" in url:
        urls_to_try.append(url.replace("/originals/", "/736x/"))

    for try_url in urls_to_try:
        try:
            resp = session.get(try_url, timeout=25, allow_redirects=True)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            if "image" not in content_type and "octet-stream" not in content_type:
                continue

            data = resp.content
            if len(data) < 2000:
                continue

            with open(filepath, "wb") as f:
                f.write(data)
            return True
        except Exception:
            continue

    if os.path.exists(filepath):
        os.remove(filepath)
    return False


def _get_extension(url: str) -> str:
    path = url.split("?")[0]
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        if path.lower().endswith(ext):
            return ext
    return ".jpg"


def download_pinterest_images(count: int) -> List[str]:
    """Основная функция: авторизация + поиск + скачивание."""
    os.makedirs(RESULT_DIR, exist_ok=True)

    # Авторизация
    proxies = ProxyManager.get_all()
    proxy = proxies[0] if proxies else None

    client = PinterestClient(PINTEREST_EMAIL, PINTEREST_PASSWORD, proxy)
    if not client.login():
        log_simple("Не удалось подключиться к Pinterest.", status="error", account_name="Pinterest")
        return []

    log_simple(f"Начинаем поиск {count} картинок...", status="info", account_name="Pinterest")

    # Сбор URL
    image_urls = _collect_image_urls(client, count)

    if not image_urls:
        log_simple("Не удалось найти картинки.", status="error", account_name="Pinterest")
        client.close()
        return []

    log_simple(
        f"Найдено {len(image_urls)} URL, скачиваем {count}...",
        status="success", account_name="Pinterest",
    )

    # Скачивание с прогресс-баром
    proxy_index = 0
    downloaded: list[str] = []
    failed = 0
    url_index = 0
    delay_min, delay_max = PINTEREST_DOWNLOAD_DELAY

    progress = Progress(
        SpinnerColumn(style="bold magenta"),
        TextColumn("[bold cyan]{task.description}[/]"),
        BarColumn(bar_width=40, style="magenta", complete_style="bold green", finished_style="bold green"),
        TextColumn("[bold white]{task.completed}/{task.total}[/]"),
        TextColumn("[dim]│[/]"),
        DownloadColumn(),
        TextColumn("[dim]│[/]"),
        TransferSpeedColumn(),
        TextColumn("[dim]│[/]"),
        TimeRemainingColumn(),
        console=console,
    )

    with progress:
        main_task = progress.add_task("📌 Скачивание", total=count)

        while len(downloaded) < count and url_index < len(image_urls):
            url = image_urls[url_index]
            url_index += 1

            # Чередуем прокси для скачивания
            dl_proxy = proxies[proxy_index % len(proxies)] if proxies else None
            proxy_index += 1

            dl_session = requests.Session()
            dl_session.headers["User-Agent"] = random.choice(USER_AGENTS)
            if dl_proxy:
                parsed = parse_proxy(dl_proxy)
                if parsed:
                    dl_session.proxies = {"http": parsed, "https": parsed}

            ext = _get_extension(url)
            filename = f"pinterest_{uuid.uuid4().hex[:10]}{ext}"
            filepath = os.path.join(RESULT_DIR, filename)

            if _download_image(dl_session, url, filepath):
                downloaded.append(filepath)
                progress.update(main_task, advance=1)
                log_task(
                    len(downloaded), count,
                    f"Скачано: {filename}",
                    status="success",
                    account_name="Pinterest",
                )
            else:
                failed += 1

            dl_session.close()
            time.sleep(random.uniform(delay_min, delay_max))

    client.close()

    log_simple(
        f"Готово! Скачано {len(downloaded)}/{count} картинок. Ошибок: {failed}",
        status="success" if downloaded else "error",
        account_name="Pinterest",
    )
    if downloaded:
        log_simple(f"Сохранено в: {RESULT_DIR}", status="info", account_name="Pinterest")

    return downloaded


def create_zip_archive(files: List[str]) -> Optional[str]:
    """Создать ZIP архив из скачанных файлов."""
    if not files:
        return None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(RESULT_DIR, f"pinterest_{timestamp}.zip")

    with Progress(
        SpinnerColumn(style="bold magenta"),
        TextColumn("[bold cyan]Создание ZIP архива...[/]"),
        BarColumn(bar_width=40, style="magenta", complete_style="bold green", finished_style="bold green"),
        TextColumn("[bold white]{task.completed}/{task.total}[/]"),
        console=console,
    ) as progress:
        task = progress.add_task("📦 Архивация", total=len(files))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in files:
                if os.path.exists(fpath):
                    zf.write(fpath, os.path.basename(fpath))
                    progress.update(task, advance=1)

    log_simple(f"ZIP архив создан: {zip_path}", status="success", account_name="Pinterest")
    return zip_path


def pinterest_downloader_menu():
    """Меню Pinterest Downloader — вызывается из main.py."""
    from questionary import text, confirm

    console.print("\n[bold magenta]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]")
    console.print("[bold cyan]  📌 Pinterest Random Image Downloader[/]")
    console.print("[bold magenta]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]\n")

    count_str = text(
        "Сколько картинок скачать?",
        default="10",
        qmark="📌",
    ).ask()

    if count_str is None:
        return

    try:
        count = int(count_str)
        if count <= 0:
            raise ValueError
    except ValueError:
        log_simple("Некорректное число.", status="error", account_name="Pinterest")
        return

    if count > PINTEREST_MAX_IMAGES:
        console.print(f"[bold yellow]⚠️  Максимум {PINTEREST_MAX_IMAGES} картинок за раз.[/]")
        count = PINTEREST_MAX_IMAGES

    downloaded = download_pinterest_images(count)

    if downloaded:
        should_zip = confirm(
            "Собрать скачанные картинки в ZIP архив?",
            default=True,
            qmark="📦",
        ).ask()

        if should_zip:
            create_zip_archive(downloaded)

    console.print(f"\n[bold green]✅ Завершено![/] Файлы в: [underline]{RESULT_DIR}[/]\n")
