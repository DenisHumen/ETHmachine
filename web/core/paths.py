"""Path helpers + project-relative roots for the web dashboard."""
from __future__ import annotations

import pathlib

# Project root = parent of web/ ; this file lives at web/core/paths.py.
ROOT = pathlib.Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"
RESULT_DIR = ROOT / "result"
DB_DIR = ROOT / "db"
CONFIG_DIR = ROOT / "config"
WEB_DIR = ROOT / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


def safe_under(root: pathlib.Path, target: pathlib.Path) -> bool:
    """True если target лежит внутри root после resolve()."""
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False
