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


DIM = "\033[2m"
WHITE = "\033[97m"
MAGENTA = "\033[95m"
BG_RED = "\033[41m"
BG_CYAN = "\033[46m"
BG_YELLOW = "\033[43m"
BG_BLACK = "\033[40m"


def _box(title: str, lines: list[str], color: str = CYAN, width: int = 72):
    """Рисует красивый бокс с заголовком (ASCII-safe для cp1251)."""
    print(f"\n   {color}{BOLD}+{'-' * (width - 2)}+{RESET}")
    pad = width - 4 - len(title)
    print(f"   {color}{BOLD}| {title}{' ' * max(pad, 0)} |{RESET}")
    print(f"   {color}+{'-' * (width - 2)}+{RESET}")
    for line in lines:
        visible = len(line.replace(BOLD, "").replace(RESET, "").replace(RED, "")
                        .replace(GREEN, "").replace(YELLOW, "").replace(CYAN, "")
                        .replace(WHITE, "").replace(DIM, "").replace(MAGENTA, ""))
        pad = width - 4 - visible
        print(f"   {color}|{RESET} {line}{' ' * max(pad, 0)} {color}|{RESET}")
    print(f"   {color}{BOLD}+{'-' * (width - 2)}+{RESET}\n")


def _print_build_error_help():
    """Выводит подробную инструкцию при ошибке сборки пакетов."""
    w = 72

    # Header
    print(f"\n   {RED}{BOLD}{'=' * w}{RESET}")
    print(f"   {RED}{BOLD}  [!] ОШИБКА СБОРКИ ПАКЕТА [!]{RESET}")
    print(f"   {RED}{BOLD}{'=' * w}{RESET}")
    print()
    print(f"   {YELLOW}Некоторые пакеты (например ckzg) требуют C-компилятор.{RESET}")
    print(f"   {YELLOW}На Windows он не установлен по умолчанию.{RESET}")
    print(f"   {YELLOW}Ниже два варианта решения:{RESET}")

    # Вариант 1
    _box("ВАРИАНТ 1 — Установить C++ Build Tools (Windows)", [
        f"{WHITE}{BOLD}Шаг 1:{RESET} Скачай Visual Studio Build Tools:",
        f"  {CYAN}https://visualstudio.microsoft.com/visual-cpp-build-tools/{RESET}",
        "",
        f"{WHITE}{BOLD}Шаг 2:{RESET} В установщике выбери:",
        f"  {GREEN}[v] Desktop development with C++{RESET}",
        f"  {DIM}(Разработка классических приложений на C++){RESET}",
        "",
        f"{WHITE}{BOLD}Шаг 3:{RESET} Нажми 'Установить' и дождись завершения",
        "",
        f"{WHITE}{BOLD}Шаг 4:{RESET} {YELLOW}Перезапусти терминал{RESET} (обязательно!)",
        "",
        f"{WHITE}{BOLD}Шаг 5:{RESET} Повтори установку:",
        f"  {CYAN}pip install -r requirements.txt{RESET}",
    ], CYAN)

    # Вариант 2
    _box("ВАРИАНТ 2 — Запуск через WSL (рекомендуется)", [
        f"{WHITE}{BOLD}Шаг 1:{RESET} Установи WSL (PowerShell от администратора):",
        f"  {CYAN}wsl --install{RESET}",
        f"  {DIM}Перезагрузи компьютер после установки{RESET}",
        "",
        f"{WHITE}{BOLD}Шаг 2:{RESET} Открой Ubuntu и установи зависимости:",
        f"  {CYAN}sudo apt update && sudo apt install -y \\{RESET}",
        f"  {CYAN}  python3 python3-pip python3-venv git build-essential{RESET}",
        "",
        f"{WHITE}{BOLD}Шаг 3:{RESET} Перейди в папку проекта:",
        f"  {CYAN}cd /mnt/c/Users/denishumen/Desktop/code/GitHub/ETHmachine{RESET}",
        "",
        f"{WHITE}{BOLD}Шаг 4:{RESET} Создай и активируй виртуальное окружение:",
        f"  {CYAN}python3 -m venv venv{RESET}",
        f"  {CYAN}source venv/bin/activate{RESET}",
        "",
        f"{WHITE}{BOLD}Шаг 5:{RESET} Установи зависимости:",
        f"  {CYAN}pip install --upgrade pip{RESET}",
        f"  {CYAN}pip install -r requirements.txt{RESET}",
        "",
        f"{WHITE}{BOLD}Шаг 6:{RESET} Запусти проект:",
        f"  {CYAN}python main.py{RESET}",
    ], GREEN)

    print(f"   {DIM}В WSL пакеты с C-расширениями собираются без проблем{RESET}")
    print(f"   {DIM}благодаря build-essential (gcc/g++).{RESET}")
    print(f"   {RED}{BOLD}{'=' * w}{RESET}\n")


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
        _print_build_error_help()
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
