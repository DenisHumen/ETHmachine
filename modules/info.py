"""Экран «Info» — справка по программе.

Состав меню здесь не дублируется. Он читается из ``config/menu_config.py``,
то есть из того же места, откуда меню и строится. Так было не всегда:
раньше в этом файле лежал отдельный словарь путей вида
``"⚡ ETH >> 📋 Last Transaction"``, и он разошёлся с кодом — рекламировал
удалённые модули и объявлял «в разработке» то, что работает. Теперь
расхождение невозможно по построению: пункт исчез из конфига — исчез и
отсюда, вместе со своей иконкой, подписью и плашкой «СКОРО».

Руками поддерживаются ровно две вещи: ссылки на видеогайды
(``GUIDES_BY_KEY``, ключи — ``MenuItem.key``) и список рабочих каталогов
(``PATHS``). И то и другое меняется на порядок реже состава меню.

Точка входа — ``info()``. ``render_info()`` собирает тот же текст, но
ничего не спрашивает: удобно проверять вёрстку и печатать целиком.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from config.menu_config import (
    BACK_KEY, MenuItem, SubMenu, all_submenus, get_enabled_main_menu_items,
)
from modules.ui import ui
from modules.ui.banner import AUTHOR, LINKS

# Ширина панелей. ``ui.panel`` сам ужмёт её под узкий терминал.
_WIDTH = 78
# Колонка названий: длиннее — и описание перестаёт помещаться на 80 колонках.
_MAX_LABEL_WIDTH = 34
_INDENT = "  "


# =============================================================================
# РУЧНАЯ ЧАСТЬ — то, чего в menu_config нет
# =============================================================================

# Ключ — ``MenuItem.key`` пункта меню. Ключи стабильны: по ним main.py
# выбирает модуль, поэтому их не переименовывают из косметических
# соображений. Если пункт всё же исчезнет, гайд просто не отрисуется —
# ссылки на несуществующий пункт пользователь не увидит.
GUIDES_BY_KEY: Dict[str, str] = {
    "check_age_discord": "https://youtu.be/7lRYBa0Educ",
    "withdraw_from_okx": "https://youtu.be/iVE2fJgTACQ",
    "transfer_wallets_to_wallets_call": "https://youtu.be/zZV_FoEUPiw",
    "neura_stat": "https://youtu.be/SsuiGb8Rz0Q",
}

# Каталоги и файлы, которые пользователю нужно знать в лицо.
# Каталоги создаёт ``modules/bootstrap.py`` при первом запуске.
PATHS: Dict[str, List[str]] = {
    "Данные": [
        "data/data.csv — аккаунты: ключи, адреса, прокси, почты",
        "data/data_<профиль>.csv — второй и последующие наборы аккаунтов",
        "data/twitter/ — twitters.csv и twitter_task.csv",
    ],
    "Настройки": [
        "config/modules/general_config.py — потоки, ретраи, капча",
        "config/modules/cfg_*.py — по одному файлу на модуль",
        "config/cex_settings.py — ключи API бирж, вне git",
        "config/networks.py — RPC-эндпоинты и параметры сетей",
        "config/token_address_erc20.py — адреса токенов по сетям",
        "config/menu_config.py — состав меню, из него собран этот экран",
    ],
    "Результаты": [
        "result/ — CSV и Excel-отчёты, у каждого модуля свой подкаталог",
        "db/ — SQLite с прогрессом долгих операций",
        "log/ — логи модулей",
        "backups/ — архивы бэкапов",
    ],
}

# Подменю обычно называется ключом пункта, который его открывает
# (см. ``ask(...)`` в main.py). Исключения — балансы EVM и Solana:
# пункты называются ``ETH``/``SOL``, а подменю — ``eth_balances``/
# ``sol_balances``. Если связь потеряется, подменю не пропадёт: оно
# отрисуется отдельным разделом в конце.
_SUBMENU_ALIASES = {
    "ETH": "eth_balances",
    "SOL": "sol_balances",
}


# =============================================================================
# СБОРКА ДЕРЕВА ИЗ menu_config
# =============================================================================

@dataclass(frozen=True)
class Section:
    """Раздел справки: заголовок и плоское дерево пунктов с глубиной."""

    key: str
    icon: str
    label: str
    description: str
    rows: Tuple[Tuple[int, MenuItem], ...]
    footer: Optional[str] = None

    def title(self) -> str:
        head = f"{self.icon} {self.label}" if self.icon else self.label
        if not self.description:
            return head
        return f"{head}  {ui.glyphs.dot}  {self.description}"


def _submenu_index() -> Dict[str, SubMenu]:
    return {submenu.key: submenu for submenu in all_submenus()}


def _child_of(item: MenuItem, index: Dict[str, SubMenu]) -> Optional[SubMenu]:
    return index.get(_SUBMENU_ALIASES.get(item.key, item.key))


def _walk(items: Sequence[MenuItem], index: Dict[str, SubMenu],
          expanded: set, depth: int = 0) -> List[Tuple[int, MenuItem]]:
    """``[(глубина, пункт)]`` — пункты подменю вместе с вложенными.

    ``expanded`` общий на всю сборку: одно подменю раскрывается один раз,
    даже если на него ведут два пункта, и цикл в конфиге не зациклит обход.
    """
    rows: List[Tuple[int, MenuItem]] = []
    for item in items:
        if item.key == BACK_KEY or not item.enabled:
            continue
        rows.append((depth, item))
        child = _child_of(item, index)
        if child is not None and child.key not in expanded:
            expanded.add(child.key)
            rows.extend(_walk(child.items, index, expanded, depth + 1))
    return rows


def build_sections() -> List[Section]:
    """Разделы справки в порядке главного меню.

    Подменю, до которого не дотянулся обход (например выбор реализации
    генератора «красивых» адресов — он спрашивается по ходу, а не из
    меню), добавляется в конец отдельным разделом. Так ни один пункт
    конфига не теряется молча.
    """
    index = _submenu_index()
    expanded: set = set()
    sections: List[Section] = []

    for item in get_enabled_main_menu_items():
        submenu = _child_of(item, index)
        if submenu is None or submenu.key in expanded:
            continue
        expanded.add(submenu.key)
        rows = _walk(submenu.items, index, expanded)
        if rows:
            sections.append(Section(
                key=item.key, icon=item.icon, label=item.label,
                description=item.description, rows=tuple(rows),
            ))

    for submenu in all_submenus():
        if submenu.key in expanded:
            continue
        expanded.add(submenu.key)
        rows = _walk(submenu.items, index, expanded)
        if rows:
            sections.append(Section(
                key=submenu.key, icon=submenu.icon, label=submenu.label,
                description=submenu.description, rows=tuple(rows),
                footer="спрашивается по ходу работы, не из главного меню",
            ))

    return sections


# =============================================================================
# ОТРИСОВКА
# =============================================================================

def _content_width() -> int:
    """Сколько ячеек остаётся под текст внутри ``ui.panel`` заданной ширины."""
    return ui.theme.panel_width(_WIDTH) - 4


def _row_lines(depth: int, item: MenuItem, label_width: int) -> List[str]:
    """Пункт в том же виде, в каком он выглядит в самом меню.

    Если описание не помещается рядом с названием, оно переносится строкой
    ниже. В меню многоточие терпимо — там пункт всё равно выбирают по
    названию; в справке оно съедает ровно то, ради чего сюда пришли
    («Параметры в config/modules/cfg_passw…»).
    """
    prefix = _INDENT * depth
    line = prefix + item.render(max(label_width - len(prefix), 10))
    if ui.visual_width(line) <= _content_width():
        return [line]

    badges = item.badges()
    head = f"{prefix}{ui.theme.FG_TEXT}{item.label_cell()}{ui.theme.RESET}"
    lines = [f"{head} {badges}" if badges else head]
    wrap_width = max(_content_width() - len(prefix) - len(_INDENT), 20)
    lines += [
        f"{prefix}{_INDENT}{ui.theme.FG_MUTED}{chunk}{ui.theme.RESET}"
        for chunk in ui.wrap(item.description, wrap_width)
    ]
    return lines


def _rows_lines(rows: Sequence[Tuple[int, MenuItem]]) -> List[str]:
    if not rows:
        return [f"{ui.theme.FG_MUTED}пунктов нет{ui.theme.RESET}"]

    label_width = min(_MAX_LABEL_WIDTH, max(
        ui.visual_width(item.label_cell()) + len(_INDENT) * depth
        for depth, item in rows
    ))

    lines: List[str] = []
    for depth, item in rows:
        lines += _row_lines(depth, item, label_width)
        url = GUIDES_BY_KEY.get(item.key)
        if url:
            lines.append(
                f"{_INDENT * (depth + 1)}{ui.theme.FG_BRAND}"
                f"{ui.glyphs.arrow} {url}{ui.theme.RESET}"
            )
    return lines


def render_overview() -> str:
    """Главное меню целиком — то, что видно сразу после запуска."""
    rows = [(0, item) for item in get_enabled_main_menu_items()]
    return ui.panel("Главное меню", _rows_lines(rows), width=_WIDTH)


def render_section(section: Section) -> str:
    return ui.panel(section.title(), _rows_lines(section.rows),
                    width=_WIDTH, footer=section.footer)


def render_paths() -> str:
    """Где лежат данные, настройки и результаты."""
    return ui.info_panel("Где что лежит", PATHS, width=_WIDTH,
                         footer="каталоги создаются при первом запуске")


def known_guides() -> Dict[str, str]:
    """``{подпись пункта: ссылка}`` — только для пунктов, которые есть в меню.

    Ключ убрали из конфига — гайд молча исчезает. Ссылки на пункт, которого
    больше нет, пользователь не увидит.
    """
    labels = {
        item.key: item.label_cell()
        for submenu in all_submenus()
        for item in submenu.items
    }
    return {
        labels[key]: url
        for key, url in GUIDES_BY_KEY.items()
        if key in labels
    }


def render_guides() -> str:
    """Видеогайды. Подписи берутся из меню, а не пишутся вторым текстом."""
    guides = known_guides()
    if not guides:
        lines = [f"{ui.theme.FG_MUTED}видеогайдов пока нет{ui.theme.RESET}"]
    else:
        lines = ui.key_values(guides, key_color=ui.theme.FG_TEXT,
                              value_color=ui.theme.FG_BRAND)
    return ui.panel("Видеогайды", lines, width=_WIDTH)


def render_links() -> str:
    return ui.panel(
        f"Автор {ui.glyphs.dot} {AUTHOR}",
        ui.key_values(dict(LINKS), value_color=ui.theme.FG_BRAND),
        width=_WIDTH,
    )


def render_info() -> str:
    """Вся справка одним текстом. Ничего не спрашивает и ничего не печатает."""
    blocks = [
        ui.header(
            "Справка ETHmachine",
            "разделы читаются из config/menu_config.py",
            width=_WIDTH,
        ),
        render_overview(),
    ]
    blocks += [render_section(section) for section in build_sections()]
    blocks.append(ui.rule(_WIDTH))
    blocks += [render_paths(), render_guides(), render_links()]
    return "\n\n".join(blocks)


# =============================================================================
# ИНТЕРАКТИВНЫЙ ЭКРАН
# =============================================================================

_OVERVIEW = "__overview__"
_PATHS = "__paths__"
_GUIDES = "__guides__"
_LINKS = "__links__"


def _menu_items(sections: Sequence[Section]) -> List[MenuItem]:
    """Пункты справки — обычные ``MenuItem``, чтобы вёрстка совпала с меню."""
    items = [MenuItem(key=_OVERVIEW, label="Главное меню", icon="🧭",
                      description="Все разделы одним списком")]
    items += [
        MenuItem(key=section.key, label=section.label, icon=section.icon,
                 description=section.description)
        for section in sections
    ]
    items += [
        MenuItem(key=_PATHS, label="Где что лежит", icon="📁",
                 description="Данные, настройки, отчёты, логи"),
        MenuItem(key=_GUIDES, label="Видеогайды", icon="🎬",
                 description=f"Разборы модулей: {len(known_guides())} шт."),
        MenuItem(key=_LINKS, label="Автор", icon="👤",
                 description="Telegram, GitHub, донат"),
        MenuItem(key=BACK_KEY, label="Назад", icon=ui.glyphs.arrow),
    ]
    return items


def info() -> None:
    """Экран справки. Вызывается из main.py по пункту главного меню «Info»."""
    sections = build_sections()
    by_key = {section.key: section for section in sections}

    while True:
        choice = ui.show_items("Справка", _menu_items(sections))
        if choice in (None, BACK_KEY):
            return

        if choice == _OVERVIEW:
            block = render_overview()
        elif choice == _PATHS:
            block = render_paths()
        elif choice == _GUIDES:
            block = render_guides()
        elif choice == _LINKS:
            block = render_links()
        elif choice in by_key:
            block = render_section(by_key[choice])
        else:
            continue

        ui.print_lines(block)
        ui.pause()


__all__ = [
    "info", "render_info", "render_overview", "render_section",
    "render_paths", "render_guides", "render_links",
    "build_sections", "known_guides", "Section", "GUIDES_BY_KEY", "PATHS",
]
