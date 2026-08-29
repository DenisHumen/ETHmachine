"""Проводка «пункт меню → функция модуля».

Самая частая поломка такого CLI: модуль переименовали или функцию убрали,
а пункт меню остался. Пользователь узнаёт об этом уже нажатием — падением
с ImportError посреди работы.

Обработчики в main.py импортируют модули лениво (внутри функций), поэтому
обычный импорт main.py такие ссылки не проверяет. Здесь мы достаём все
ленивые импорты из AST и убеждаемся, что каждый действительно резолвится.
"""

from __future__ import annotations

import ast
import importlib

import pytest

from tests.conftest import PROJECT_ROOT

MAIN_PY = PROJECT_ROOT / "main.py"


def _lazy_imports() -> list[tuple[str, str]]:
    """``[(модуль, имя), ...]`` для всех ``from ... import ...`` внутри функций."""
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    module_level = {id(node) for node in tree.body}
    found: list[tuple[str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or id(node) in module_level:
            continue
        if not node.module or node.level:
            continue
        for alias in node.names:
            found.append((node.module, alias.name))
    return sorted(set(found))


LAZY_IMPORTS = _lazy_imports()


def test_found_lazy_imports():
    assert len(LAZY_IMPORTS) > 20, (
        "не нашли ленивые импорты в main.py — обработчики стали импортировать иначе"
    )


@pytest.mark.parametrize(
    ("module_name", "symbol"), LAZY_IMPORTS, ids=lambda v: str(v)
)
def test_lazy_import_resolves(module_name: str, symbol: str):
    module = importlib.import_module(module_name)
    assert hasattr(module, symbol), f"{module_name} не содержит {symbol}"


def test_lazy_import_targets_are_callable():
    """Обработчик должен импортировать функцию, а не что попало."""
    not_callable: list[str] = []
    for module_name, symbol in LAZY_IMPORTS:
        module = importlib.import_module(module_name)
        target = getattr(module, symbol, None)
        if target is None:
            continue  # ловится отдельным тестом
        if not callable(target) and not isinstance(target, (dict, list, tuple, str, int, bool)):
            not_callable.append(f"{module_name}.{symbol}")
    assert not not_callable, f"неожиданные цели импорта: {not_callable}"


def test_every_main_menu_key_is_routed():
    """У каждого раздела главного меню есть обработчик."""
    import main
    from config.menu_config import get_enabled_main_menu_items

    # Разделы, которые main_menu() обрабатывает не через таблицу _ROUTES.
    handled_inline = {"backup_menu", "info", "exit", "faucets"}
    missing = [
        item.key for item in get_enabled_main_menu_items()
        if item.key not in main._ROUTES and item.key not in handled_inline
    ]
    assert not missing, f"разделы без обработчика: {missing}"


def test_routes_point_at_existing_handlers():
    import main

    broken = [key for key, fn in main._ROUTES.items() if not callable(fn)]
    assert not broken, f"нерабочие маршруты: {broken}"


def test_main_module_has_no_import_side_effects(tmp_project):
    """Импорт main.py не должен создавать файлы.

    Раньше ``check_and_create_files()`` вызывался прямо на импорте, из-за чего
    любой импорт main.py (в том числе из тестов) создавал каталоги в текущей
    директории. Теперь подготовка окружения — явный шаг в ``main()``.
    """
    import importlib

    import main as main_module

    importlib.reload(main_module)
    created = [p.name for p in tmp_project.iterdir()
               if p.name not in {"db", "data", "result", "log"}]
    assert not created, f"импорт main.py создал файлы: {created}"


def test_bootstrap_is_idempotent(tmp_project):
    """Повторная подготовка окружения не перезаписывает существующие файлы."""
    from modules import bootstrap

    first = bootstrap.ensure_directories(tmp_project)
    bootstrap.ensure_files(tmp_project)

    marker = tmp_project / bootstrap.CEX_SETTINGS_PATH
    assert marker.exists()
    marker.write_text("USER_EDITED = True\n", encoding="utf-8")

    second_dirs = bootstrap.ensure_directories(tmp_project)
    second_files = bootstrap.ensure_files(tmp_project)

    assert first, "первый вызов должен что-то создать"
    assert not second_dirs and not second_files, "повторный вызов создал файлы заново"
    assert marker.read_text(encoding="utf-8") == "USER_EDITED = True\n", (
        "подготовка окружения затёрла пользовательский конфиг"
    )
