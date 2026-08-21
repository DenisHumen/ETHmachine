"""Ввод пользователя: меню, подтверждения, числа, пауза.

Один вход для всех интерактивных запросов. Раньше каждый модуль звал
``questionary.select`` со своими ``qmark``/``pointer`` и своим текстом
«Нажмите Enter», из-за чего интерфейс выглядел собранным из разных
программ. Плюс здесь централизованно обрабатывается Ctrl+C: ``ask()``
возвращает ``None``, и модулю не нужно про это помнить.
"""

from __future__ import annotations

from typing import Any, Sequence

from modules.ui import theme
from modules.ui.text import visual_width

_G = theme.GLYPHS

# Единый стиль вопроса во всех меню проекта.
QMARK = _G.bullet
POINTER = _G.pointer

_BACK = "back"


def _formatted(text: str):
    """ANSI-строка → FormattedText, который понимает questionary.

    ``Choice`` приводит неизвестные типы через ``str()``, поэтому обычный
    ``ANSI(...)`` печатается как литерал ``ANSI('...')``. Разворачиваем
    сразу в список кортежей — его ``Choice`` принимает как готовый
    FormattedText.
    """
    if "\033" not in text:
        return text
    try:
        from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    except ImportError:  # pragma: no cover — prompt_toolkit идёт с questionary
        return text
    return to_formatted_text(ANSI(text))


def _questionary_style():
    from questionary import Style

    return Style([
        ("qmark", "fg:#00d7ff bold"),
        ("question", "bold"),
        ("pointer", "fg:#00d7ff bold"),
        ("highlighted", "fg:#00d7ff bold"),
        ("selected", "fg:#5fd75f"),
        ("answer", "fg:#af5fff bold"),
        ("instruction", "fg:#8a8a8a"),
    ])


def menu(title: str, options: Sequence[tuple[str, Any]], *,
         qmark: str = QMARK, pointer: str = POINTER,
         default: Any = None) -> Any:
    """Показывает меню и возвращает значение выбранного пункта.

    ``options`` — последовательность пар ``(отображаемый текст, значение)``.
    При Ctrl+C возвращает ``None``.
    """
    from questionary import Choice, select

    choices = [Choice(_formatted(label), value) for label, value in options]
    kwargs: dict[str, Any] = {
        "choices": choices,
        "qmark": qmark,
        "pointer": pointer,
        "style": _questionary_style(),
        "instruction": " ",
    }
    if default is not None:
        for choice in choices:
            if choice.value == default:
                kwargs["default"] = choice
                break
    try:
        return select(title, **kwargs).ask()
    except KeyboardInterrupt:
        return None


def choose(title: str, options: Sequence[tuple[str, Any]], *,
           back_label: str | None = "Назад", **kwargs) -> Any:
    """``menu()`` с автоматически добавленным пунктом «Назад»."""
    items = list(options)
    if back_label is not None:
        items.append((f"{_G.arrow} {back_label}", _BACK))
    return menu(title, items, **kwargs)


def confirm(question: str, *, default: bool = True) -> bool:
    """Да/нет. Ctrl+C трактуется как «нет»."""
    from questionary import confirm as _confirm

    try:
        answer = _confirm(
            question, default=default, qmark=QMARK, style=_questionary_style()
        ).ask()
    except KeyboardInterrupt:
        return False
    return bool(answer)


def ask_int(question: str, *, minimum: int | None = None,
            maximum: int | None = None, default: int | None = None) -> int | None:
    """Целое число с валидацией. ``None`` — пользователь отказался."""
    from questionary import text as _text

    def _validate(value: str) -> bool | str:
        value = value.strip()
        if not value and default is not None:
            return True
        try:
            number = int(value)
        except ValueError:
            return "Нужно целое число"
        if minimum is not None and number < minimum:
            return f"Минимум — {minimum}"
        if maximum is not None and number > maximum:
            return f"Максимум — {maximum}"
        return True

    hint = ""
    if minimum is not None and maximum is not None:
        hint = f" [{minimum}–{maximum}]"
    elif minimum is not None:
        hint = f" [от {minimum}]"
    try:
        answer = _text(
            f"{question}{hint}:",
            default=str(default) if default is not None else "",
            validate=_validate,
            qmark=QMARK,
            style=_questionary_style(),
        ).ask()
    except KeyboardInterrupt:
        return None
    if answer is None:
        return None
    answer = answer.strip()
    if not answer:
        return default
    return int(answer)


def ask_text(question: str, *, default: str = "",
             allow_empty: bool = True) -> str | None:
    from questionary import text as _text

    def _validate(value: str) -> bool | str:
        if not allow_empty and not value.strip():
            return "Пустое значение не подходит"
        return True

    try:
        answer = _text(
            f"{question}:", default=default, validate=_validate,
            qmark=QMARK, style=_questionary_style(),
        ).ask()
    except KeyboardInterrupt:
        return None
    return answer


def pause(message: str = "Enter — продолжить") -> None:
    """Пауза перед возвратом в меню. Ctrl+C не роняет программу."""
    try:
        input(f"\n{theme.FG_MUTED}{_G.arrow} {message}{theme.RESET} ")
    except (KeyboardInterrupt, EOFError):
        print()


def print_lines(*blocks: str) -> None:
    """Печатает блоки UI с отступами — чтобы не плодить ``print()`` в модулях."""
    print()
    for block in blocks:
        print(block)
    print()


__all__ = [
    "menu", "choose", "confirm", "ask_int", "ask_text", "pause",
    "print_lines", "QMARK", "POINTER",
]
