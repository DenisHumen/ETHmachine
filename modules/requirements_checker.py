"""
Проверка установленных зависимостей из requirements.txt.
ВАЖНО: Использует ТОЛЬКО стандартную библиотеку Python,
чтобы работать даже на чистом Python без установленных пакетов.
"""

import sys
import os
import platform
import subprocess
import shutil
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


def _is_debian_based():
    """Проверяет, является ли система Debian/Ubuntu."""
    if platform.system() != "Linux":
        return False
    if shutil.which("apt") or shutil.which("apt-get"):
        return True
    os_release = Path("/etc/os-release")
    if os_release.exists():
        content = os_release.read_text(encoding="utf-8", errors="ignore").lower()
        return "debian" in content or "ubuntu" in content
    return False


def _get_python_dev_package():
    """Возвращает имя пакета python3.X-dev для текущей версии Python."""
    v = sys.version_info
    return f"python{v.major}.{v.minor}-dev"


def _is_apt_package_installed(pkg_name: str) -> bool:
    """Проверяет, установлен ли apt-пакет."""
    try:
        result = subprocess.run(
            ["dpkg", "-s", pkg_name],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0 and "Status: install ok installed" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_linux_build_deps() -> list[str]:
    """
    На Debian/Ubuntu проверяет наличие python3.X-dev и build-essential.
    Возвращает список недостающих apt-пакетов.
    """
    if not _is_debian_based():
        return []
    missing = []
    dev_pkg = _get_python_dev_package()
    if not _is_apt_package_installed(dev_pkg):
        missing.append(dev_pkg)
    if not _is_apt_package_installed("build-essential"):
        # Дополнительно проверяем наличие gcc
        if not shutil.which("gcc") and not shutil.which("cc"):
            missing.append("build-essential")
    return missing


def _install_apt_packages(packages: list[str]) -> bool:
    """
    Предлагает установить apt-пакеты через sudo.
    Возвращает True при успехе.
    """
    pkg_str = " ".join(packages)
    print(f"\n   {YELLOW}{BOLD}[!] Обнаружены недостающие системные пакеты:{RESET}")
    for pkg in packages:
        print(f"       {RED}-{RESET} {pkg}")

    print(f"\n   {CYAN}Некоторые Python-пакеты (ed25519-blake2b, lru-dict, ckzg и др.){RESET}")
    print(f"   {CYAN}требуют компиляции C-расширений. Для этого нужны заголовочные{RESET}")
    print(f"   {CYAN}файлы Python и C-компилятор.{RESET}")
    print()
    print(f"   {WHITE}{BOLD}Команда для установки:{RESET}")
    print(f"   {CYAN}sudo apt update && sudo apt install -y {pkg_str}{RESET}")
    print()
    print(f"   {CYAN}Установить автоматически? (потребуется пароль sudo) (y/n): {RESET}", end="")
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer not in ("y", "yes", "д", "да"):
        print(f"\n   {YELLOW}Пропуск. Установите вручную:{RESET}")
        print(f"   {CYAN}sudo apt update && sudo apt install -y {pkg_str}{RESET}\n")
        return False

    print(f"\n   {CYAN}Обновление списка пакетов...{RESET}")
    rc_update = subprocess.call(["sudo", "apt", "update"])
    if rc_update != 0:
        print(f"   {RED}apt update завершился с ошибкой.{RESET}")
        return False

    print(f"\n   {CYAN}Установка {pkg_str}...{RESET}")
    rc_install = subprocess.call(["sudo", "apt", "install", "-y"] + packages)
    if rc_install != 0:
        print(f"   {RED}apt install завершился с ошибкой (код {rc_install}).{RESET}")
        return False

    print(f"\n   {GREEN}{BOLD}Системные пакеты успешно установлены!{RESET}")
    return True


def _pip_output_has_python_h_error(output: str) -> bool:
    """Проверяет, содержит ли вывод pip ошибку отсутствия Python.h."""
    return "Python.h: No such file or directory" in output or "Python.h:" in output


def _check_and_fix_pkg_resources() -> bool:
    """
    Проверяет доступность pkg_resources (нужен для web3 и др.).
    setuptools >= 82 удаляет pkg_resources.
    Возвращает True если всё ок или исправлено.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import pkg_resources"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True  # не можем проверить — не блокируем

    print(f"\n   {YELLOW}{BOLD}[!] Обнаружена проблема: модуль pkg_resources недоступен{RESET}")
    print(f"   {CYAN}Новые версии setuptools (>= 82) удалили pkg_resources,{RESET}")
    print(f"   {CYAN}но он нужен для работы web3 и других библиотек.{RESET}")
    print()
    print(f"   {WHITE}{BOLD}Решение:{RESET} откатить setuptools до версии < 81")
    print(f"   {CYAN}pip install \"setuptools<81\"{RESET}")
    print()
    print(f"   {CYAN}Исправить автоматически? (y/n): {RESET}", end="")
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer not in ("y", "yes", "д", "да"):
        print(f"\n   {YELLOW}Пропуск. Исправьте вручную:{RESET}")
        print(f"   {CYAN}pip install \"setuptools<81\"{RESET}\n")
        return False

    print(f"\n   {CYAN}Откат setuptools...{RESET}")
    rc = subprocess.call([sys.executable, "-m", "pip", "install", "setuptools<81"])
    if rc != 0:
        print(f"   {RED}Не удалось откатить setuptools (код {rc}).{RESET}")
        print(f"   {YELLOW}Попробуйте вручную: pip install \"setuptools<81\"{RESET}")
        return False

    print(f"   {GREEN}{BOLD}setuptools откачен, pkg_resources снова доступен!{RESET}")
    return True


def _print_build_error_help(pip_output: str = ""):
    """Выводит подробную инструкцию при ошибке сборки пакетов."""
    w = 72
    is_linux = platform.system() == "Linux"
    is_debian = _is_debian_based()
    has_python_h_error = _pip_output_has_python_h_error(pip_output) if pip_output else False

    # Header
    print(f"\n   {RED}{BOLD}{'=' * w}{RESET}")
    print(f"   {RED}{BOLD}  [!] ОШИБКА СБОРКИ ПАКЕТА [!]{RESET}")
    print(f"   {RED}{BOLD}{'=' * w}{RESET}")
    print()

    # ─── Linux (Debian/Ubuntu) — Python.h + build-essential ───
    if is_debian and has_python_h_error:
        dev_pkg = _get_python_dev_package()
        print(f"   {YELLOW}Отсутствуют заголовочные файлы Python (Python.h).{RESET}")
        print(f"   {YELLOW}Для компиляции C-расширений нужен пакет {dev_pkg}.{RESET}")
        print()

        _box(f"РЕШЕНИЕ — Установить {dev_pkg} и build-essential", [
            f"{WHITE}{BOLD}Выполните команду:{RESET}",
            f"  {CYAN}sudo apt update && sudo apt install -y {dev_pkg} build-essential{RESET}",
            "",
            f"{WHITE}{BOLD}Затем повторите установку зависимостей:{RESET}",
            f"  {CYAN}pip install -r requirements.txt{RESET}",
        ], GREEN)

        # Предложить автоустановку
        missing_pkgs = _check_linux_build_deps()
        if missing_pkgs:
            _install_apt_packages(missing_pkgs)
        return

    if is_linux and has_python_h_error:
        dev_pkg = _get_python_dev_package()
        print(f"   {YELLOW}Отсутствуют заголовочные файлы Python (Python.h).{RESET}")
        print(f"   {YELLOW}Установите пакет разработки для вашего дистрибутива:{RESET}")
        print()
        _box("РЕШЕНИЕ — Установить заголовочные файлы Python", [
            f"{WHITE}{BOLD}Debian/Ubuntu:{RESET}",
            f"  {CYAN}sudo apt install -y {dev_pkg} build-essential{RESET}",
            "",
            f"{WHITE}{BOLD}Fedora/RHEL:{RESET}",
            f"  {CYAN}sudo dnf install -y python3-devel gcc{RESET}",
            "",
            f"{WHITE}{BOLD}Arch Linux:{RESET}",
            f"  {DIM}Заголовочные файлы включены в пакет python{RESET}",
            "",
            f"{WHITE}{BOLD}Затем повторите:{RESET}",
            f"  {CYAN}pip install -r requirements.txt{RESET}",
        ], GREEN)
        return

    # ─── Windows ───
    print(f"   {YELLOW}Некоторые пакеты (например ckzg) требуют C-компилятор.{RESET}")
    if not is_linux:
        print(f"   {YELLOW}На Windows он не установлен по умолчанию.{RESET}")
    print(f"   {YELLOW}Ниже варианты решения:{RESET}")

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
        f"{WHITE}{BOLD}Шаг 3:{RESET} Создай и активируй виртуальное окружение:",
        f"  {CYAN}python3 -m venv venv{RESET}",
        f"  {CYAN}source venv/bin/activate{RESET}",
        "",
        f"{WHITE}{BOLD}Шаг 4:{RESET} Установи зависимости:",
        f"  {CYAN}pip install --upgrade pip{RESET}",
        f"  {CYAN}pip install -r requirements.txt{RESET}",
        "",
        f"{WHITE}{BOLD}Шаг 5:{RESET} Запусти проект:",
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
        # Все пакеты установлены — проверяем pkg_resources
        _check_and_fix_pkg_resources()
        return True

    print(f"\n{YELLOW}{BOLD}!  Не установлены {len(missing)} из {len(reqs)} зависимостей:{RESET}")
    print(f"{CYAN}   Python {sys.version.split()[0]}  ({sys.executable}){RESET}\n")
    for _, spec in missing:
        print(f"   {RED}-{RESET} {spec}")

    # ── На Linux проверяем системные зависимости ДО установки pip ──
    linux_deps_installed = False
    if _is_debian_based():
        missing_apt = _check_linux_build_deps()
        if missing_apt:
            linux_deps_installed = _install_apt_packages(missing_apt)
            if linux_deps_installed:
                print()  # отступ перед pip

    print(f"\n{CYAN}   Установить все зависимости из requirements.txt? (y/n): {RESET}", end="")
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer not in ("y", "yes", "д", "да"):
        print(f"{YELLOW}   Пропуск. Некоторые модули могут не работать.\n{RESET}")
        return True

    print(f"\n{CYAN}   pip install -r requirements.txt ...{RESET}\n")

    # Захватываем вывод pip для анализа ошибок
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True
    )
    pip_output = proc.stdout or ""
    # Выводим вывод pip пользователю
    if pip_output:
        print(pip_output)

    if proc.returncode != 0:
        print(f"\n{RED}   pip завершился с ошибкой (код {proc.returncode}){RESET}")

        # Если на Linux ошибка Python.h и мы ещё не устанавливали dev-пакеты
        if _is_debian_based() and _pip_output_has_python_h_error(pip_output) and not linux_deps_installed:
            missing_apt = _check_linux_build_deps()
            if missing_apt:
                installed = _install_apt_packages(missing_apt)
                if installed:
                    # Повторяем pip install после установки системных пакетов
                    print(f"\n{CYAN}   Повторная установка pip install -r requirements.txt ...{RESET}\n")
                    rc_retry = subprocess.call(
                        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)]
                    )
                    if rc_retry == 0:
                        print(f"\n{GREEN}   Зависимости установлены!{RESET}")
                        _check_and_fix_pkg_resources()
                        _install_playwright_if_needed(missing)
                        return True
                    else:
                        print(f"\n{RED}   pip повторно завершился с ошибкой (код {rc_retry}).{RESET}")

        _print_build_error_help(pip_output)
        return False

    print(f"\n{GREEN}   Зависимости установлены!{RESET}")

    # ── Проверка pkg_resources после установки ──
    _check_and_fix_pkg_resources()

    # Playwright — нужна отдельная установка браузера
    _install_playwright_if_needed(missing)

    return True


def _install_playwright_if_needed(missing: list):
    """Устанавливает Chromium для Playwright если нужно."""
    if any(name == "playwright" for name, _ in missing):
        print(f"{CYAN}   Установка Chromium для Playwright...{RESET}")
        rc2 = subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
        if rc2 == 0:
            print(f"{GREEN}   Chromium установлен!{RESET}")
        else:
            print(f"{YELLOW}   Запустите вручную: python -m playwright install chromium{RESET}")
