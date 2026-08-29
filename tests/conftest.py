"""Общая настройка pytest: корень проекта в sys.path, тихие предупреждения.

Тесты не трогают пользовательские данные — всё, что пишет на диск,
работает во временных каталогах через фикстуру ``tmp_project``.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Каталоги, которые не являются исходниками проекта.
SKIP_DIR_PARTS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "build", "dist", "scripts", "tests",
}


def is_project_path(path: Path) -> bool:
    """Путь относится к исходникам, а не к окружению или копии проекта.

    Скрытые каталоги отбрасываются целиком: в ``.claude/worktrees`` лежит
    полная рабочая копия проекта, и без этого правила обход находил каждый
    модуль дважды — один раз настоящий, один раз из копии.
    """
    rel = path.relative_to(PROJECT_ROOT)
    parts = rel.parts if path.is_dir() else rel.parts[:-1]
    return not any(part in SKIP_DIR_PARTS or part.startswith(".")
                   for part in parts)


def project_files(pattern: str = "*.py", root: Path | None = None):
    """Файлы проекта по маске — без окружений, кешей и рабочих копий."""
    for path in sorted((root or PROJECT_ROOT).rglob(pattern)):
        if is_project_path(path):
            yield path

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Модули не должны поднимать веб-дашборд во время тестов.
os.environ.setdefault("ETHMACHINE_DISABLE_WEB", "1")


@pytest.fixture()
def tmp_project(tmp_path, monkeypatch):
    """Временный рабочий каталог со скелетом проекта.

    Нужен тестам, которые создают файлы/БД: они не должны писать
    в реальные ``db/``, ``result/`` и ``log/``.
    """
    for sub in ("db", "data", "result", "log"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path
