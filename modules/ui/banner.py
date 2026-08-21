"""Приветственный и прощальный экраны.

Логотип берётся из ``assets/ASCI_logo.txt`` и красится градиентом.
Если файла нет или терминал не тянет Unicode — показывается компактный
текстовый вариант, программа при этом не падает.
"""

from __future__ import annotations

import time
from pathlib import Path

from modules.ui import theme
from modules.ui.text import pad, visual_width

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGO_PATH = PROJECT_ROOT / "assets" / "ASCI_logo.txt"
VERSION_PATH = PROJECT_ROOT / "db" / "version"

AUTHOR = "@DenisHumen"
LINKS = (
    ("Telegram", "https://t.me/DenisHumen"),
    ("GitHub", "https://github.com/DenisHumen"),
    ("Донат ERC-20", "0xa24fbbd57720ec580395aedba3ad37f6a6067727"),
)

_G = theme.GLYPHS


def read_version() -> str:
    """Локальная версия из ``db/version``; пустая строка, если файла нет."""
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _logo_lines() -> list[str]:
    try:
        raw = LOGO_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ["ETHmachine"]
    lines = [line.rstrip() for line in raw]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines or ["ETHmachine"]


def render_logo() -> str:
    """Логотип с градиентом бирюзовый → фиолетовый."""
    if not theme.UNICODE_OK:
        return f"{theme.FG_ACCENT}{theme.BOLD}ETHmachine{theme.RESET}"
    lines = _logo_lines()
    return "\n".join(theme.gradient(line) for line in lines)


def _logo_width() -> int:
    return max((visual_width(line) for line in _logo_lines()), default=32)


def render_welcome(*, data_profile: str | None = None,
                   web_url: str | None = None) -> str:
    """Полный приветственный экран."""
    width = _logo_width() if theme.UNICODE_OK else 32
    blocks = [render_logo()]

    version = read_version()
    signature = f"by {AUTHOR}" + (f"  {_G.dot}  {version}" if version else "")
    blocks.append(f"{theme.FG_MUTED}{pad(signature, width, 'right')}{theme.RESET}")
    blocks.append("")

    label_width = max(visual_width(name) for name, _ in LINKS)
    for name, url in LINKS:
        blocks.append(
            f"  {theme.FG_ACCENT}{pad(name, label_width)}{theme.RESET}  "
            f"{theme.FG_BRAND}{url}{theme.RESET}"
        )

    status: list[str] = []
    if data_profile:
        status.append(f"данные: {data_profile}")
    if web_url:
        status.append(f"веб-панель: {web_url}")
    if status:
        blocks.append("")
        blocks.append(
            f"  {theme.FG_MUTED}{f'  {_G.dot}  '.join(status)}{theme.RESET}"
        )

    return "\n".join(blocks)


def print_welcome(**kwargs) -> None:
    print()
    print(render_welcome(**kwargs))
    print()


def print_farewell(*, animate: bool = True) -> None:
    """Прощание. Анимация отключается для не-интерактивных запусков."""
    frames = ["", "🚀", "🚀✨", "🚀✨💸"]
    if animate and theme.UNICODE_OK:
        for frame in frames:
            print(f"\r  {frame}", end="", flush=True)
            time.sleep(0.08)
        print("\r" + " " * 12 + "\r", end="")

    print()
    print(f"  {theme.FG_OK}{theme.BOLD}Спасибо, что пользуетесь ETHmachine{theme.RESET}")
    print(f"  {theme.FG_MUTED}Вопросы и предложения {_G.arrow} "
          f"{theme.FG_BRAND}https://t.me/DenisHumen{theme.RESET}")
    print()


__all__ = [
    "read_version", "render_logo", "render_welcome",
    "print_welcome", "print_farewell", "AUTHOR", "LINKS",
]
