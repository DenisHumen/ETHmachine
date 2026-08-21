"""UI-набор: измерение ширины, выравнивание, рамки.

Если ширина символа посчитана неверно, «поедут» все меню и рамки сразу,
поэтому базовые метрики закреплены тестами.
"""

from __future__ import annotations

import pytest

from modules.ui import MenuItem, components, render_items, text, theme


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", 0),
        ("abc", 3),
        ("привет", 6),
        ("─", 1),          # box drawing — одна ячейка
        ("│", 1),
        ("→", 1),
        ("←", 1),
        ("❯", 1),
        ("·", 1),
        ("🌟", 2),         # эмодзи — две
        ("⚡", 2),
        ("🛠️", 2),         # узкий символ + VS-16 → эмодзи-начертание
        ("☀️", 2),
        ("▶️", 2),
        ("💲 BALANCES", 11),
        ("🔙 Назад", 8),
    ],
)
def test_visual_width(value: str, expected: int):
    assert text.visual_width(value) == expected


def test_visual_width_ignores_ansi():
    plain = "готово"
    colored = f"{theme.FG_OK}{plain}{theme.RESET}"
    assert text.visual_width(colored) == text.visual_width(plain)


@pytest.mark.parametrize("width", [1, 5, 12, 40])
def test_fit_produces_exact_width(width: int):
    for sample in ("abc", "🌟 длинная строка с эмодзи", "─" * 60, ""):
        assert text.visual_width(text.fit(sample, width)) == width


def test_fit_keeps_ansi_and_exact_width():
    colored = f"{theme.FG_ACCENT}очень длинный цветной заголовок{theme.RESET}"
    result = text.fit(colored, 12)
    assert text.visual_width(result) == 12
    assert "\033" in result


def test_truncate_adds_ellipsis():
    assert text.truncate("abcdefgh", 5) == "abcd…"
    assert text.truncate("abc", 5) == "abc"


def test_wrap_respects_width():
    lines = text.wrap("один два три четыре пять шесть", 12)
    assert all(text.visual_width(line) <= 12 for line in lines)
    assert " ".join(lines) == "один два три четыре пять шесть"


def test_shorten_address():
    assert text.shorten_address("0x1234567890abcdef1234567890abcdef12345678") == "0x1234…5678"
    assert text.shorten_address("0x12") == "0x12"


def _visible(block: str) -> list[str]:
    return [text.strip_ansi(line) for line in block.splitlines()]


def test_panel_lines_have_equal_width():
    block = components.panel(
        "Заголовок",
        ["короткая", "существенно более длинная строка с эмодзи 🌟"],
        footer="подпись",
    )
    widths = {text.visual_width(line) for line in _visible(block)}
    assert len(widths) == 1, f"строки рамки разной ширины: {sorted(widths)}"


def test_stats_panel_lines_have_equal_width():
    block = components.stats_panel(
        "db/example.db",
        {"pending": 12, "arrived": 140, "failed": 2, "total": 154},
    )
    widths = {text.visual_width(line) for line in _visible(block)}
    assert len(widths) == 1, f"строки панели разной ширины: {sorted(widths)}"


def test_stats_panel_handles_empty_database():
    block = components.stats_panel("db/example.db", {"total": 0})
    assert "база пуста" in text.strip_ansi(block)


def test_info_panel_lines_have_equal_width():
    block = components.info_panel(
        "Модуль",
        {"Раздел": ["строка один", "строка два подлиннее"], "Ещё": ["хвост"]},
    )
    widths = {text.visual_width(line) for line in _visible(block)}
    assert len(widths) == 1


def test_menu_items_share_label_column():
    items = [
        MenuItem("a", "Коротко", "описание", "🤖"),
        MenuItem("b", "Существенно более длинное название пункта", "описание", "💱"),
        MenuItem("c", "Средней длины", "", "📊"),
    ]
    rendered = [label for label, _ in render_items(items)]
    columns = {
        text.visual_width(text.strip_ansi(line).split("│")[0])
        for line in rendered
        if "│" in text.strip_ansi(line)
    }
    assert len(columns) == 1, f"колонка названий разъехалась: {columns}"


def test_menu_item_without_description_has_no_dangling_separator():
    item = MenuItem("back", "Назад", "", "←")
    rendered = text.strip_ansi(item.render(20))
    assert not rendered.rstrip().endswith("│")
    assert rendered.strip() == "← Назад"


def test_wip_item_gets_a_badge():
    item = MenuItem("x", "Функция", "", "🔧", is_wip=True)
    assert "СКОРО" in text.strip_ansi(item.render(20))


def test_render_items_skips_disabled():
    items = [
        MenuItem("a", "Видимый"),
        MenuItem("b", "Скрытый", enabled=False),
    ]
    assert [key for _, key in render_items(items)] == ["a"]


def test_ascii_fallback_glyphs_are_ascii():
    from modules.ui.theme import _Glyphs

    ascii_glyphs = _Glyphs(unicode_ok=False)
    for name in ("h", "v", "tl", "br", "bullet", "arrow", "pointer"):
        value = getattr(ascii_glyphs, name)
        assert value.isascii(), f"{name} не ASCII: {value!r}"
