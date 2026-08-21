"""Готовые блоки интерфейса: рамки, заголовки, панели статистики.

Раньше каждый модуль рисовал свою рамку: где-то `'=' * 60`, где-то
жёстко зашитые `╔═══╗` фиксированной ширины, которые ломались, как только
менялся текст внутри. Здесь ширина всегда считается по содержимому.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from modules.ui import theme
from modules.ui.text import fit, visual_width, wrap

_G = theme.GLYPHS

# Ниже этой ширины панель выглядит обрезком, а не блоком интерфейса.
_MIN_PANEL_WIDTH = 46


def rule(width: int | None = None, *, bold: bool = False,
         color: str = theme.FG_ACCENT) -> str:
    """Горизонтальная линия-разделитель."""
    char = _G.h_bold if bold else _G.h
    return f"{color}{char * theme.panel_width(width)}{theme.RESET}"


def header(title: str, subtitle: str | None = None,
           *, width: int | None = None, color: str = theme.FG_ACCENT) -> str:
    """Заголовок секции: линия, название, необязательное пояснение, линия."""
    inner = theme.panel_width(width)
    lines = [
        f"{color}{_G.h * inner}{theme.RESET}",
        f"{color}{theme.BOLD}{title}{theme.RESET}",
    ]
    if subtitle:
        lines.append(f"{theme.FG_MUTED}{subtitle}{theme.RESET}")
    lines.append(f"{color}{_G.h * inner}{theme.RESET}")
    return "\n".join(lines)


def panel(title: str, lines: Sequence[str], *, width: int | None = None,
          color: str = theme.FG_ACCENT, footer: str | None = None) -> str:
    """Рамка с заголовком. Ширина подбирается по самой длинной строке."""
    content = list(lines)
    natural = max(
        [visual_width(title)] + [visual_width(line) for line in content]
        + ([visual_width(footer)] if footer else [])
    )
    # Панель уже минимума выглядит случайной, шире терминала — рвётся.
    inner = theme.panel_width(width or max(natural + 4, _MIN_PANEL_WIDTH)) - 2
    inner = max(inner, visual_width(title) + 2)

    out = [f"{color}{_G.tl}{_G.h * inner}{_G.tr}{theme.RESET}"]
    out.append(
        f"{color}{_G.v}{theme.RESET} {theme.BOLD}{fit(title, inner - 2)}"
        f"{theme.RESET} {color}{_G.v}{theme.RESET}"
    )
    out.append(f"{color}{_G.t_left}{_G.h * inner}{_G.t_right}{theme.RESET}")
    for line in content:
        out.append(
            f"{color}{_G.v}{theme.RESET} {fit(line, inner - 2)} "
            f"{color}{_G.v}{theme.RESET}"
        )
    if footer:
        out.append(f"{color}{_G.t_left}{_G.h * inner}{_G.t_right}{theme.RESET}")
        out.append(
            f"{color}{_G.v}{theme.RESET} {theme.FG_MUTED}{fit(footer, inner - 2)}"
            f"{theme.RESET} {color}{_G.v}{theme.RESET}"
        )
    out.append(f"{color}{_G.bl}{_G.h * inner}{_G.br}{theme.RESET}")
    return "\n".join(out)


def key_values(mapping: Mapping[str, Any], *, indent: str = "  ",
               key_width: int | None = None,
               key_color: str = theme.FG_MUTED,
               value_color: str = theme.FG_TEXT) -> list[str]:
    """Выровненные пары «ключ — значение»."""
    if not mapping:
        return []
    width = key_width or max(visual_width(str(k)) for k in mapping)
    return [
        f"{indent}{key_color}{fit(str(key), width)}{theme.RESET}  "
        f"{value_color}{value}{theme.RESET}"
        for key, value in mapping.items()
    ]


# Порядок и оформление канонических статусов задач (см. AGENTS.md §5.2).
_STATUS_COLORS = {
    "pending": theme.FG_MUTED,
    "planned": theme.FG_MUTED,
    "skipped": theme.FG_MUTED,
    "in_progress": theme.FG_INFO,
    "swap_created": theme.FG_INFO,
    "tx_sent": theme.FG_INFO,
    "awaiting_arrival": theme.FG_INFO,
    "arrived": theme.FG_OK,
    "done": theme.FG_OK,
    "success": theme.FG_OK,
    "failed": theme.FG_ERR,
    "error": theme.FG_ERR,
}


def stats_panel(title: str, stats: Mapping[str, Any], *,
                total_key: str = "total", footer: str | None = None,
                width: int | None = None) -> str:
    """Панель статистики БД — единый вид во всех модулях."""
    body = {k: v for k, v in stats.items() if k != total_key}
    if not body and not stats.get(total_key):
        lines = [f"{theme.FG_MUTED}база пуста{theme.RESET}"]
        return panel(title, lines, width=width, footer=footer)

    key_width = max((visual_width(str(k)) for k in body), default=8)
    key_width = max(key_width, visual_width(total_key))
    lines = [
        f"{_STATUS_COLORS.get(key, theme.FG_TEXT)}{fit(str(key), key_width)}"
        f"{theme.RESET}  {theme.BOLD}{value}{theme.RESET}"
        for key, value in body.items()
    ]
    if total_key in stats:
        lines.append(f"{theme.FG_MUTED}{_G.h * (key_width + 6)}{theme.RESET}")
        lines.append(
            f"{theme.BOLD}{fit(total_key, key_width)}{theme.RESET}  "
            f"{theme.BOLD}{stats[total_key]}{theme.RESET}"
        )
    return panel(title, lines, width=width, footer=footer)


def info_panel(title: str, sections: Mapping[str, Iterable[str]], *,
               width: int | None = None, footer: str | None = None) -> str:
    """Справка модуля: заголовок и именованные блоки строк."""
    lines: list[str] = []
    for index, (section, items) in enumerate(sections.items()):
        if index:
            lines.append("")
        if section:
            lines.append(f"{theme.FG_ACCENT}{section}{theme.RESET}")
        for item in items:
            for wrapped in wrap(item, theme.panel_width(width) - 8):
                lines.append(f"  {wrapped}")
    return panel(title, lines, width=width, footer=footer)


def bullet_list(items: Iterable[str], *, indent: str = "  ",
                color: str = theme.FG_TEXT) -> list[str]:
    return [
        f"{indent}{theme.FG_ACCENT}{_G.bullet}{theme.RESET} {color}{item}{theme.RESET}"
        for item in items
    ]


__all__ = [
    "rule", "header", "panel", "key_values", "stats_panel", "info_panel",
    "bullet_list",
]
