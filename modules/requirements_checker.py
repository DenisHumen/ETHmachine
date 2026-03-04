"""
Проверка установленных зависимостей из requirements.txt.
ВАЖНО: Использует ТОЛЬКО стандартную библиотеку Python,
чтобы работать даже на чистом Python без установленных пакетов.
"""

import sys
import subprocess
from pathlib import Path
from importlib.metadata import version as get_version, PackageNotFoundError

REQUIREMENTS_FILE = Path(__file__).parent.parent / "requirements.txt"

# pip-имя → metadata-имя (где отличаются)
NAME_MAP = {
    "python-okx": "python-okx",
    "bip-utils": "bip_utils",
    "fake-useragent": "fake_useragent",
    "aiohttp-socks": "aiohttp_socks",
    "eth-account": "eth_account",
    "eth-utils": "eth_utils",
    "curl-cffi": "curl_cffi",
    "tls-client": "tls_client",
}

# ANSI (без colorama)
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _installed(name: str):
    """Версия пакета или None."""
    try:
        return get_version(name)
    except PackageNotFoundError:
        mapped = NAME_MAP.get(name)
        if mapped and mapped != name:
            try:
                return get_version(mapped)
            except PackageNotFoundError:
                pass
    return None


def _parse():
    """requirements.txt → [(pip_name, full_line), ...]"""
    if not REQUIREMENTS_FILE.exists():
        return []
    result = []
    with open(REQUIREMENTS_FILE, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for sep in (">=", "==", "<=", "!=", "~="):
                if sep in line:
                    name = line.split(sep, 1)[0].strip()
                    result.append((name, line))
                    break
            else:
                result.append((line, line))
    return result


def check_requirements() -> bool:
    """Проверить зависимости. Возвращает True если можно продолжать."""
    reqs = _parse()
    if not reqs:
        return True

    missing = [(n, s) for n, s in reqs if _installed(n) is None]
    if not missing:
        return True

    print(f"\n{YELLOW}{BOLD}!  Не установлены {len(missing)} из {len(reqs)} зависимостей:{RESET}")
    print(f"{CYAN}   Python {sys.version.split()[0]}  ({sys.executable}){RESET}\n")
    for _, spec in missing:
        print(f"   {RED}-{RESET} {spec}")

    print(f"\n{CYAN}   Установить все зависимости из requirements.txt? (y/n): {RESET}", end="")
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer not in ("y", "yes", "д", "да"):
        print(f"{YELLOW}   Пропуск. Некоторые модули могут не работать.\n{RESET}")
        return True

    print(f"\n{CYAN}   pip install -r requirements.txt ...{RESET}\n")
    rc = subprocess.call([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])
    if rc != 0:
        print(f"\n{RED}   pip завершился с ошибкой (код {rc}){RESET}")
        return False

    print(f"\n{GREEN}   Зависимости установлены!{RESET}")

    # Playwright — нужна отдельная установка браузера
    if any(name == "playwright" for name, _ in missing):
        print(f"{CYAN}   Установка Chromium для Playwright...{RESET}")
        rc2 = subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
        if rc2 == 0:
            print(f"{GREEN}   Chromium установлен!{RESET}")
        else:
            print(f"{YELLOW}   Запустите вручную: python -m playwright install chromium{RESET}")

    return True
