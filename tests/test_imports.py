"""Каждый модуль проекта должен импортироваться без ошибок.

Это самый дешёвый способ поймать битые импорты, опечатки в путях и
удалённые зависимости — то, что иначе всплывает уже у пользователя
при выборе пункта меню.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

from tests.conftest import PROJECT_ROOT

SKIP_DIR_PARTS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "build", "dist", "scripts", "tests",
}


def _iter_module_names() -> list[str]:
    names: list[str] = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT)
        if any(part in SKIP_DIR_PARTS for part in rel.parts):
            continue
        if rel.name == "main.py":
            continue  # у main.py есть побочные эффекты на импорте
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
            if not parts:
                continue
        else:
            parts[-1] = parts[-1][: -len(".py")]
        names.append(".".join(parts))
    return names


MODULE_NAMES = _iter_module_names()


def test_module_list_is_not_empty():
    assert len(MODULE_NAMES) > 100, "не нашли модули — сломан обход дерева"


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_module_imports(module_name: str):
    importlib.import_module(module_name)


def test_no_leftover_backup_files():
    """В репозитории не должно быть *.backup / *.original артефактов."""
    leftovers = [
        str(p.relative_to(PROJECT_ROOT))
        for p in PROJECT_ROOT.rglob("*")
        if p.is_file()
        and p.suffix in {".backup", ".original"}
        and not any(part in SKIP_DIR_PARTS for part in p.relative_to(PROJECT_ROOT).parts)
    ]
    assert not leftovers, f"лишние артефакты: {leftovers}"


def test_packages_have_init():
    """Каталоги-пакеты под modules/ должны иметь __init__.py.

    Namespace-пакеты работают, но ломают статический анализ и
    осложняют упаковку — держим явные __init__.py.
    """
    missing: list[str] = []
    modules_root = PROJECT_ROOT / "modules"
    for pkg_dir in sorted(modules_root.rglob("*")):
        if not pkg_dir.is_dir():
            continue
        rel = pkg_dir.relative_to(PROJECT_ROOT)
        if any(part in SKIP_DIR_PARTS for part in rel.parts):
            continue
        if not any(child.suffix == ".py" for child in pkg_dir.iterdir() if child.is_file()):
            continue
        if not (pkg_dir / "__init__.py").exists():
            missing.append(str(rel))
    assert not missing, f"нет __init__.py в: {missing}"
