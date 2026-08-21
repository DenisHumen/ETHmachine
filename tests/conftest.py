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
