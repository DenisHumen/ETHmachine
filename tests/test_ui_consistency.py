"""Интерфейс собирается только из ``modules/ui``.

AGENTS.md §13.5: меню и запросы к пользователю идут через UI-набор.
Прямые вызовы ``questionary`` со своими ``qmark``/``pointer`` — это ровно
то, из-за чего интерфейс раньше выглядел собранным из разных программ,
а починка одной детали требовала правки двух десятков файлов.

Проверяем это тестом, а не глазами на ревью: правило легко нарушить
случайно, скопировав меню из старого модуля.
"""

from __future__ import annotations

import ast

import pytest

from tests.conftest import PROJECT_ROOT

SKIP_DIR_PARTS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "build", "dist", "scripts", "tests",
}

# Единственное место, которому questionary положен: сам UI-набор его и
# оборачивает — ради этого он и существует.
UI_PACKAGE = ("modules", "ui")


def _source_files() -> list:
    files = []
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT)
        if any(part in SKIP_DIR_PARTS for part in rel.parts):
            continue
        if rel.parts[:2] == UI_PACKAGE:
            continue
        files.append(path)
    return files


SOURCE_FILES = _source_files()


def _questionary_imports(path) -> list[str]:
    """Строки файла, где импортируется questionary."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "questionary" for alias in node.names):
                hits.append(f"строка {node.lineno}: import questionary")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root == "questionary":
                names = ", ".join(alias.name for alias in node.names)
                hits.append(f"строка {node.lineno}: from questionary import {names}")
    return hits


def test_source_files_found():
    assert len(SOURCE_FILES) > 100, "не нашли исходники — сломан обход дерева"


@pytest.mark.parametrize(
    "path", SOURCE_FILES, ids=lambda p: str(p.relative_to(PROJECT_ROOT))
)
def test_no_direct_questionary(path):
    """Вне modules/ui questionary не импортируется."""
    hits = _questionary_imports(path)
    assert not hits, (
        f"{path.relative_to(PROJECT_ROOT)} зовёт questionary напрямую "
        f"({'; '.join(hits)}). Меню и запросы — через modules/ui: "
        f"ui.menu / ui.choose / ui.confirm / ui.confirm_or_back / "
        f"ui.ask_int / ui.ask_text, каркас меню — ModuleMenu."
    )
