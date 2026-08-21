"""Измерение и выравнивание текста в терминале.

``str.ljust`` считает кодпоинты, а терминал рисует ячейки: эмодзи занимает
две, variation selector — ноль. Без честного подсчёта колонки меню
«съезжают» ровно настолько, сколько эмодзи в строке.
"""

from __future__ import annotations

import re
import unicodedata

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# Variation selector-16 переключает символ в «эмодзи»-начертание, и терминал
# рисует его в две ячейки, хотя сам по себе символ узкий (🛠 vs 🛠️).
_VS16 = "️"
_VS15 = "︎"
_ZWJ = "‍"

# Кодпоинты нулевой ширины: селекторы начертания, ZWJ, нулевой пробел.
_ZERO_WIDTH = {_VS16, _VS15, _ZWJ, "​", "︎"}


def strip_ansi(text: str) -> str:
    """Убирает ANSI-последовательности — для подсчёта видимой длины."""
    return _ANSI_RE.sub("", text)


def char_width(char: str, *, emoji_presentation: bool = False) -> int:
    """Ширина одного символа в ячейках терминала.

    ``emoji_presentation`` — за символом стоит U+FE0F, значит терминал
    нарисует его как эмодзи (две ячейки), даже если по таблице Unicode
    он «нейтральный».
    """
    if char in _ZERO_WIDTH or unicodedata.combining(char):
        return 0
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return 2
    if emoji_presentation and unicodedata.category(char) in ("So", "Sk", "Sm"):
        return 2
    # Ambiguous (box drawing, стрелки, средняя точка) современные терминалы
    # рисуют в одну ячейку — считаем так же.
    return 1


def _iter_cells(text: str):
    """``(символ, ширина)`` с учётом следующего за символом VS-16."""
    chars = strip_ansi(text)
    for index, char in enumerate(chars):
        nxt = chars[index + 1] if index + 1 < len(chars) else ""
        yield char, char_width(char, emoji_presentation=(nxt == _VS16))


def visual_width(text: str) -> int:
    """Ширина строки в ячейках терминала."""
    return sum(width for _, width in _iter_cells(text))


def pad(text: str, width: int, align: str = "left", fill: str = " ") -> str:
    """Дополняет строку до нужной видимой ширины."""
    gap = max(0, width - visual_width(text))
    if align == "right":
        return fill * gap + text
    if align == "center":
        left = gap // 2
        return fill * left + text + fill * (gap - left)
    return text + fill * gap


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """Обрезает строку по видимой ширине, сохраняя ANSI-последовательности."""
    if visual_width(text) <= width:
        return text
    if width <= 0:
        return ""
    # На совсем узкой колонке многоточие само не помещается — режем без него.
    if width <= visual_width(ellipsis):
        ellipsis = ""
    limit = width - visual_width(ellipsis)
    out: list[str] = []
    current = 0
    index = 0
    has_ansi = "\033" in text
    while index < len(text):
        match = _ANSI_RE.match(text, index) if has_ansi else None
        if match:
            out.append(match.group(0))
            index = match.end()
            continue
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        cell = char_width(char, emoji_presentation=(nxt == _VS16))
        if current + cell > limit:
            break
        out.append(char)
        current += cell
        index += 1
    tail = theme_reset() if has_ansi else ""
    return "".join(out) + ellipsis + tail


def theme_reset() -> str:
    """ANSI-сброс. Вынесен сюда, чтобы ``text`` не зависел от ``theme``."""
    return "\033[0m"


def fit(text: str, width: int, align: str = "left") -> str:
    """Обрезает или дополняет строку ровно до ``width`` ячеек."""
    return pad(truncate(text, width), width, align)


def wrap(text: str, width: int) -> list[str]:
    """Простой перенос по словам с учётом видимой ширины."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if visual_width(current) + 1 + visual_width(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def shorten_address(address: str, head: int = 6, tail: int = 4) -> str:
    """``0x1234…abcd`` — компактный вид адреса для логов и таблиц."""
    if not address or len(address) <= head + tail + 1:
        return address
    return f"{address[:head]}…{address[-tail:]}"


__all__ = [
    "strip_ansi", "visual_width", "pad", "truncate", "fit", "wrap",
    "shorten_address",
]
