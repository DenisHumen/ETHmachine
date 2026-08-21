"""Каркас меню модуля.

Почти каждый модуль повторял один и тот же блок: цикл ``while True``,
``questionary.select`` со своими qmark/pointer, ветвление ``if action == ...``,
ручная отрисовка статистики рамками из ``'=' * 60`` и ``input("Нажмите Enter…")``
в конце. Отличались только пункты — из-за чего интерфейс расползался, а
починка одной детали требовала правки двадцати файлов.

Здесь этот каркас один раз. Модуль описывает, что он умеет, а как это
выглядит — решает UI-слой.

Пример::

    from modules.ui.module_menu import MenuAction, ModuleMenu

    ModuleMenu(
        title="zkSync Era → Base USDC",
        subtitle="свап всех токенов через Rhino.fi",
        icon="💱",
        actions=[
            MenuAction("auto",   "Авто-режим",    _handle_auto,
                       "план, свап и Excel одной кнопкой", icon="🤖"),
            MenuAction("plan",   "Планирование",  _handle_plan,
                       "снять балансы и создать задачи",   icon="📋"),
            MenuAction("run",    "Запуск свапа",  _handle_run, icon="▶️"),
            MenuAction("export", "Экспорт отчёта", _handle_export, icon="📑"),
        ],
        stats=db.get_statistics,
        stats_title=str(db.DB_PATH),
        reset=db.reset_database,
        info=_info_sections,
    ).run()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from modules.ui import components, prompts, theme
from modules.ui.menu_model import BACK_KEY, MenuItem

# Ключи служебных пунктов, которые каркас добавляет сам.
STATS_KEY = "__stats__"
RESET_KEY = "__reset__"
INFO_KEY = "__info__"


@dataclass
class MenuAction:
    """Пункт меню модуля."""

    key: str
    label: str
    handler: Callable[[], Any]
    description: str = ""
    icon: str = "▶️"
    enabled: bool = True
    # Пауза после выполнения, чтобы вывод не смыло возвратом в меню.
    pause_after: bool = True
    # Подтверждение перед запуском — для необратимых действий.
    confirm: str | None = None

    def to_item(self) -> MenuItem:
        return MenuItem(key=self.key, label=self.label,
                        description=self.description, icon=self.icon,
                        enabled=self.enabled)


@dataclass
class ModuleMenu:
    """Меню одного модуля: пункты, статистика, справка, очистка БД."""

    title: str
    actions: Sequence[MenuAction]
    subtitle: str = ""
    icon: str = "▶️"
    # Функция, возвращающая {статус: количество} — панель статистики.
    stats: Callable[[], Mapping[str, Any]] | None = None
    stats_title: str = ""
    # Функция очистки БД. Всегда спрашивает подтверждение.
    reset: Callable[[], Any] | None = None
    # Справка: {"Раздел": ["строка", ...]}.
    info: Callable[[], Mapping[str, Iterable[str]]] | Mapping[str, Iterable[str]] | None = None
    # Дополнительные строки под заголовком при каждом показе меню.
    status_line: Callable[[], str] | None = None

    _handlers: dict = field(default_factory=dict, init=False, repr=False)

    # ── Сборка списка пунктов ───────────────────────────────────────────

    def _items(self) -> list[MenuItem]:
        items = [action.to_item() for action in self.actions if action.enabled]
        if self.stats is not None:
            items.append(MenuItem(key=STATS_KEY, label="Статистика",
                                  description="что уже сделано и что осталось",
                                  icon="📊"))
        if self.info is not None:
            items.append(MenuItem(key=INFO_KEY, label="Справка",
                                  description="как работает модуль", icon="📖"))
        if self.reset is not None:
            items.append(MenuItem(key=RESET_KEY, label="Очистить базу",
                                  description="сбросить весь прогресс модуля",
                                  icon="🗑️"))
        items.append(MenuItem(key=BACK_KEY, label="Назад", description="",
                              icon="←"))
        return items

    # ── Служебные экраны ────────────────────────────────────────────────

    def _show_stats(self) -> None:
        assert self.stats is not None
        try:
            data = dict(self.stats())
        except Exception as exc:
            # Таблицы ещё нет — значит модуль ни разу не запускали. Это не
            # ошибка, и пугать пользователя трассировкой SQLite незачем.
            if "no such table" in str(exc).lower():
                prompts.print_lines(components.panel(
                    self.stats_title or self.title,
                    ["Модуль ещё не запускался — данных нет.",
                     "Начните с планирования или авто-режима."],
                    color=theme.FG_MUTED))
                return
            prompts.print_lines(components.panel(
                "Не удалось прочитать статистику", [str(exc)],
                color=theme.FG_ERR))
            return
        prompts.print_lines(components.stats_panel(
            self.stats_title or self.title, data))

    def _show_info(self) -> None:
        assert self.info is not None
        sections = self.info() if callable(self.info) else self.info
        prompts.print_lines(components.info_panel(self.title, dict(sections)))

    def _do_reset(self) -> None:
        assert self.reset is not None
        if not prompts.confirm(
            "Удалить весь прогресс модуля из базы? Отменить будет нельзя",
            default=False,
        ):
            prompts.print_lines(
                f"  {theme.FG_MUTED}Отменено — база не тронута.{theme.RESET}")
            return
        self.reset()
        prompts.print_lines(
            f"  {theme.FG_OK}База очищена.{theme.RESET}")

    # ── Основной цикл ───────────────────────────────────────────────────

    def run(self) -> None:
        actions = {action.key: action for action in self.actions}

        while True:
            header = f"{self.icon} {self.title}" if self.icon else self.title
            if self.status_line is not None:
                try:
                    line = self.status_line()
                except Exception:
                    line = ""
                if line:
                    print(f"\n  {theme.FG_MUTED}{line}{theme.RESET}")

            choice = prompts.menu(
                header if not self.subtitle else f"{header} — {self.subtitle}",
                [(item.render(_label_width(self._items())), item.key)
                 for item in self._items()],
            )

            if choice in (None, BACK_KEY):
                return

            if choice == STATS_KEY:
                self._show_stats()
                prompts.pause()
                continue
            if choice == INFO_KEY:
                self._show_info()
                prompts.pause()
                continue
            if choice == RESET_KEY:
                self._do_reset()
                prompts.pause()
                continue

            action = actions.get(choice)
            if action is None:
                continue

            if action.confirm and not prompts.confirm(action.confirm, default=False):
                continue

            try:
                action.handler()
            except KeyboardInterrupt:
                prompts.print_lines(
                    f"  {theme.FG_WARN}Прервано пользователем. "
                    f"Прогресс сохранён в базе.{theme.RESET}")
            if action.pause_after:
                prompts.pause()


def _label_width(items: Sequence[MenuItem]) -> int:
    from modules.ui.menu_model import label_column_width

    return label_column_width(items)


__all__ = ["MenuAction", "ModuleMenu", "STATS_KEY", "RESET_KEY", "INFO_KEY"]
