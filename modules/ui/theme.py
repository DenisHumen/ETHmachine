"""Единая палитра и набор символов для всего терминального UI.

Здесь и только здесь задаются цвета и глифы. Модули не должны собирать
ANSI-последовательности руками — иначе интерфейс расползается: у одного
модуля рамка из `=`, у другого из `═`, у третьего цвет заголовка другой.

Windows-консоль не всегда умеет UTF-8 (cp866/cp1251), поэтому каждый
рисующий символ имеет ASCII-замену. Выбор делается один раз при импорте
по кодировке stdout.
"""

from __future__ import annotations

import os
import sys

# ── Цвета (true-color там, где можно, иначе 16-цветный ANSI) ─────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

FG_TEXT = "\033[97m"        # основной текст — яркий белый
FG_MUTED = "\033[38;5;245m"  # пояснения, подписи
FG_ACCENT = "\033[38;5;51m"  # бирюзовый — заголовки, рамки
FG_BRAND = "\033[38;5;141m"  # фиолетовый — акценты бренда
FG_OK = "\033[38;5;84m"
FG_WARN = "\033[38;5;221m"
FG_ERR = "\033[38;5;203m"
FG_INFO = "\033[38;5;117m"

BG_OK = "\033[48;5;28m"
BG_WARN = "\033[48;5;136m"
BG_ERR = "\033[48;5;124m"
BG_INFO = "\033[48;5;24m"

# Градиент логотипа: бирюзовый → фиолетовый.
GRADIENT_START = (0, 255, 200)
GRADIENT_END = (160, 50, 255)


def _stdout_supports_unicode() -> bool:
    if os.environ.get("ETHMACHINE_ASCII_UI"):
        return False
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    if "utf" in encoding:
        return True
    # Пробуем записать пробный символ — некоторые терминалы врут про кодировку.
    try:
        "═".encode(encoding or "ascii")
    except (LookupError, UnicodeEncodeError):
        return False
    return True


UNICODE_OK = _stdout_supports_unicode()


class _Glyphs:
    """Символы рисования с ASCII-фолбэком."""

    def __init__(self, unicode_ok: bool) -> None:
        if unicode_ok:
            self.h = "─"
            self.h_bold = "━"
            self.v = "│"
            self.tl, self.tr, self.bl, self.br = "╭", "╮", "╰", "╯"
            self.t_left, self.t_right = "├", "┤"
            self.bullet = "•"
            self.arrow = "→"
            self.pointer = "❯"
            self.check = "✔"
            self.cross = "✘"
            self.dot = "·"
        else:
            self.h = "-"
            self.h_bold = "="
            self.v = "|"
            self.tl = self.tr = self.bl = self.br = "+"
            self.t_left = self.t_right = "+"
            self.bullet = "*"
            self.arrow = "->"
            self.pointer = ">"
            self.check = "v"
            self.cross = "x"
            self.dot = "."


GLYPHS = _Glyphs(UNICODE_OK)

# Ширина панелей по умолчанию. Ужимаем под узкие терминалы.
DEFAULT_WIDTH = 72
MIN_WIDTH = 40
# Выше этого рамки читаются хуже: глаз теряет строку на обратном ходе.
MAX_WIDTH = 100


def terminal_width(default: int = DEFAULT_WIDTH + 2) -> int:
    """Ширина терминала; ``default`` — когда вывод не в терминал."""
    try:
        columns = os.get_terminal_size().columns
    except OSError:
        return default
    return columns if columns > 0 else default


def panel_width(requested: int | None = None) -> int:
    """Ширина панели: не шире терминала и не шире разумного максимума.

    Верхняя граница нужна и при выводе в файл или пайп, где размер
    терминала неизвестен: иначе одна длинная строка (например абсолютный
    путь) растягивает рамку на всю ширину и ломает вёрстку.
    """
    width = requested or DEFAULT_WIDTH
    available = terminal_width() - 2
    return max(MIN_WIDTH, min(width, available, MAX_WIDTH))


def gradient(text: str,
             start: tuple[int, int, int] = GRADIENT_START,
             end: tuple[int, int, int] = GRADIENT_END) -> str:
    """Окрашивает строку посимвольным RGB-градиентом."""
    steps = max(len(text) - 1, 1)
    out: list[str] = []
    for i, char in enumerate(text):
        r = int(start[0] + (end[0] - start[0]) * i / steps)
        g = int(start[1] + (end[1] - start[1]) * i / steps)
        b = int(start[2] + (end[2] - start[2]) * i / steps)
        out.append(f"\033[38;2;{r};{g};{b}m{char}")
    out.append(RESET)
    return "".join(out)


def badge(text: str, style: str = "info") -> str:
    """Цветная «плашка» — например статус модуля в меню."""
    palette = {
        "ok": BG_OK,
        "success": BG_OK,
        "warn": BG_WARN,
        "warning": BG_WARN,
        "error": BG_ERR,
        "red": BG_ERR,
        "yellow": BG_WARN,
        "info": BG_INFO,
    }
    background = palette.get(style, BG_INFO)
    return f"{background}\033[97;1m {text} {RESET}"


__all__ = [
    "RESET", "BOLD", "DIM",
    "FG_TEXT", "FG_MUTED", "FG_ACCENT", "FG_BRAND",
    "FG_OK", "FG_WARN", "FG_ERR", "FG_INFO",
    "GLYPHS", "UNICODE_OK", "DEFAULT_WIDTH",
    "panel_width", "gradient", "badge",
]
