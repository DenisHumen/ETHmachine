"""Подготовка рабочего окружения при запуске.

Создаёт каталоги и файлы, без которых модули падают на первом же запуске:
``data/``, ``db/``, ``result/``, ``log/``, шаблоны конфигов с ключами бирж
и Pinterest.

Все операции идемпотентны: существующие файлы никогда не перезаписываются,
поэтому обновление проекта не затирает пользовательские настройки.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Каталоги, которые должны существовать до старта любого модуля.
REQUIRED_DIRECTORIES = (
    "result",
    "data",
    "data/twitter",
    "db",
    "backups",
    "log",
)

# Пути, которые создаются с содержимым по умолчанию.
# Ключ — путь относительно корня, значение — имя шаблона ниже.
_CSV_HEADERS = {
    "result/result.csv": "address,balance,network\n",
    "data/twitter/twitters.csv": "nickname,auth_token,ct0,proxy\n",
    "data/twitter/twitter_task.csv": "link,type,value\n",
}

CEX_SETTINGS_PATH = "config/cex_settings.py"
PINTEREST_CONFIG_PATH = "config/modules/cfg_pinterest.py"


def _cex_settings_template() -> str:
    return '''"""Ключи API бирж.

Файл не попадает в git (см. .gitignore) — храните ключи только локально.
Для каждой биржи можно завести несколько аккаунтов: добавьте ещё один
словарь в список и поставьте enabled=True.
"""

# OKX — https://www.okx.com/ru/account/my-api
# Поставьте 1, если депозиты приходят на Торговый аккаунт вместо Финансового.
OKX_EU_TYPE = 0

OKX_ACCOUNTS = [
    {
        'name': 'OKX Main',
        'api_key': '',
        'api_secret': '',
        'passphrase': '',
        'type': OKX_EU_TYPE,
        'enabled': False,
    },
]

# Binance — https://www.binance.com/en/my/settings/api-management
BINANCE_ACCOUNTS = [
    {
        'name': 'Binance Main',
        'api_key': '',
        'api_secret': '',
        'enabled': False,
    },
]

# Bitget — https://www.bitget.com/ru/support/articles/360033773814
BITGET_ACCOUNTS = [
    {
        'name': 'Bitget Main',
        'api_key': '',
        'api_secret': '',
        'passphrase': '',
        'enabled': False,
    },
]

# MEXC — https://www.mexc.com/ru-RU/user/openapi
MEXC_ACCOUNTS = [
    {
        'name': 'MEXC Main',
        'api_key': '',
        'api_secret': '',
        'enabled': False,
    },
]
'''


def _pinterest_config_template() -> str:
    return '''"""Настройки загрузчика картинок с Pinterest.

Файл не попадает в git — в нём учётные данные аккаунта.
"""

PINTEREST_EMAIL = ''              # Email аккаунта Pinterest
PINTEREST_PASSWORD = ''           # Пароль аккаунта Pinterest

# Максимум картинок за одну сессию.
PINTEREST_MAX_IMAGES = 500

# Пауза между скачиваниями [мин, макс] в секундах.
PINTEREST_DOWNLOAD_DELAY = [0.2, 0.6]

# Качество: 'originals' (максимальное), '736x' (среднее), '564x' (сжатое).
PINTEREST_IMAGE_QUALITY = 'originals'

# Свои поисковые запросы. Пустой список — используется встроенный набор тем.
# Например ['meme', 'cats'] — для каждого поиска берётся случайный запрос
# из списка (один поиск отдаёт примерно 20 картинок).
PINTEREST_SEARCH_QUERIES = []
'''


_FILE_TEMPLATES = {
    CEX_SETTINGS_PATH: _cex_settings_template,
    PINTEREST_CONFIG_PATH: _pinterest_config_template,
}


def ensure_directories(root: Path | None = None) -> list[str]:
    """Создаёт рабочие каталоги. Возвращает список созданных."""
    base = root or PROJECT_ROOT
    created: list[str] = []
    for name in REQUIRED_DIRECTORIES:
        path = base / name
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(name)
    return created


def ensure_files(root: Path | None = None) -> list[str]:
    """Создаёт файлы с содержимым по умолчанию. Существующие не трогает."""
    base = root or PROJECT_ROOT
    created: list[str] = []

    for name, header in _CSV_HEADERS.items():
        path = base / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header, encoding="utf-8")
        created.append(name)

    for name, template in _FILE_TEMPLATES.items():
        path = base / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template(), encoding="utf-8")
        created.append(name)

    return created


def prepare_workspace(root: Path | None = None, *, announce: bool = True) -> list[str]:
    """Полная подготовка окружения. Возвращает список созданных путей."""
    created = ensure_directories(root)
    created += ensure_files(root)

    # Файл данных с полным набором колонок создаёт сам data_manager —
    # он же владеет схемой и умеет мигрировать старые файлы.
    from modules.data_manager import _ensure_data_file

    _ensure_data_file()

    if announce and created:
        _announce(created)
    return created


def _announce(created: Iterable[str]) -> None:
    from modules.ui import theme

    for name in created:
        print(f"  {theme.FG_OK}+{theme.RESET} {theme.FG_MUTED}создано{theme.RESET} {name}")


__all__ = [
    "PROJECT_ROOT", "REQUIRED_DIRECTORIES",
    "CEX_SETTINGS_PATH", "PINTEREST_CONFIG_PATH",
    "ensure_directories", "ensure_files", "prepare_workspace",
]
