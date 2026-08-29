"""Модель пунктов меню и их отрисовка.

Данные меню живут в ``config/menu_config.py`` — там пользователь включает
и выключает разделы. Здесь только структуры и рендеринг, чтобы конфиг
оставался декларативным списком, а внешний вид менялся в одном месте.

Ширина колонки с названием считается по самому длинному пункту конкретного
меню, а не берётся из константы: раньше длинный пункт («Swap All Polygon
zkEVM → Base USDC») вылезал за фиксированные 35 ячеек и ломал выравнивание
всего списка.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence

from modules.ui import theme
from modules.ui.text import fit, visual_width

_G = theme.GLYPHS

BACK_KEY = "back"

# Минимальная и максимальная ширина колонки названий.
_MIN_LABEL_WIDTH = 18
_MAX_LABEL_WIDTH = 42


def _current_os() -> str:
    """``windows`` / ``macos`` / ``linux`` — нормализованное имя ОС."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


@dataclass
class MenuItem:
    """Пункт меню.

    ``key``          — значение, которое вернёт меню при выборе.
    ``is_wip``       — помечает незаконченный функционал жёлтой плашкой.
    ``badge``        — произвольная плашка (например «ПАУЗА»).
    ``requires_os``  — пункт показывается только на указанной ОС.
    """

    key: str
    label: str
    description: str = ""
    icon: str = _G.bullet
    enabled: bool = True
    handler: Optional[Callable[..., Any]] = None
    requires_os: Optional[str] = None
    is_wip: bool = False
    badge: Optional[str] = None
    badge_style: str = "red"

    # ── Отрисовка ────────────────────────────────────────────────────────

    def label_cell(self) -> str:
        return f"{self.icon} {self.label}" if self.icon else self.label

    def is_available(self) -> bool:
        """False, если пункт требует другую ОС."""
        return not self.requires_os or self.requires_os == _current_os()

    def badges(self) -> str:
        parts: list[str] = []
        if self.badge:
            parts.append(theme.badge(self.badge, self.badge_style))
        if self.is_wip:
            parts.append(theme.badge("СКОРО", "warn"))
        if not self.is_available():
            parts.append(theme.badge(f"ТОЛЬКО {self.requires_os.upper()}", "warn"))
        return " ".join(parts)

    def render(self, label_width: int) -> str:
        """Строка пункта: иконка, название, разделитель, описание."""
        label = f"{theme.FG_TEXT}{fit(self.label_cell(), label_width)}{theme.RESET}"
        badges = self.badges()
        tail_parts = [p for p in (badges, self.description) if p]
        if not tail_parts:
            return label
        tail = " ".join(tail_parts)
        separator = f"{theme.DIM}{_G.v}{theme.RESET}"
        return f"{label} {separator} {theme.FG_MUTED}{tail}{theme.RESET}"

    # Историческое имя — часть публичного API config/menu_config.py.
    def get_choice_text(self, label_width: int | None = None) -> str:
        return self.render(label_width or _MIN_LABEL_WIDTH)


@dataclass
class SubMenu:
    """Группа пунктов с собственным заголовком."""

    key: str
    label: str
    description: str = ""
    icon: str = _G.bullet
    enabled: bool = True
    items: List[MenuItem] = field(default_factory=list)
    qmark: str = ""
    pointer: str = ""

    def get_enabled_items(self) -> List[MenuItem]:
        return [item for item in self.items if item.enabled]

    def label_cell(self) -> str:
        return f"{self.icon} {self.label}" if self.icon else self.label

    def get_choice_text(self, label_width: int | None = None) -> str:
        item = MenuItem(
            key=self.key, label=self.label, description=self.description,
            icon=self.icon,
        )
        return item.render(label_width or _MIN_LABEL_WIDTH)


def label_column_width(items: Sequence[MenuItem]) -> int:
    """Общая ширина колонки названий для набора пунктов."""
    if not items:
        return _MIN_LABEL_WIDTH
    widest = max(visual_width(item.label_cell()) for item in items)
    return max(_MIN_LABEL_WIDTH, min(widest, _MAX_LABEL_WIDTH))


def render_items(items: Sequence[MenuItem]) -> list[tuple[str, str]]:
    """``[(отрисованная строка, key), ...]`` — готовый вход для ``ui.menu``."""
    enabled = [item for item in items if item.enabled]
    width = label_column_width(enabled)
    return [(item.render(width), item.key) for item in enabled]


def show(title: str, items: Sequence[MenuItem], **kwargs) -> Any:
    """Показывает список пунктов и возвращает key выбранного."""
    from modules.ui.prompts import menu

    return menu(title, render_items(items), **kwargs)


__all__ = [
    "MenuItem", "SubMenu", "BACK_KEY",
    "label_column_width", "render_items", "show",
]
