"""Config editor — list/read/write config/*.py with diff + restart flag."""
from __future__ import annotations

import difflib
import pathlib
from typing import Any

from config.modules.cfg_web import WEB_RESTART_REQUIRED_PATHS
from web.core.paths import CONFIG_DIR, ROOT, safe_under


_RESTART_REQUIRED = {p.replace("\\", "/") for p in WEB_RESTART_REQUIRED_PATHS}


def list_config_files() -> list[dict[str, Any]]:
    out = []
    if not CONFIG_DIR.exists():
        return out
    for p in sorted(CONFIG_DIR.rglob("*.py")):
        if p.name == "__init__.py":
            continue
        rel = p.relative_to(ROOT).as_posix()
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({
            "rel": rel,
            "name": p.name,
            "size": size,
            "restart_required": rel in _RESTART_REQUIRED,
        })
    return out


def _validate_rel(rel: str) -> pathlib.Path:
    rel = (rel or "").strip().replace("\\", "/")
    if not rel.startswith("config/"):
        raise PermissionError("only config/* allowed")
    if not rel.endswith(".py") or rel.endswith("__init__.py"):
        raise PermissionError("only *.py allowed (not __init__.py)")
    target = (ROOT / rel).resolve()
    if not safe_under(CONFIG_DIR, target):
        raise PermissionError("path traversal blocked")
    return target


def read_config(rel: str) -> str:
    target = _validate_rel(rel)
    if not target.exists():
        raise FileNotFoundError(rel)
    return target.read_text(encoding="utf-8")


def write_config(rel: str, new_content: str) -> dict[str, Any]:
    """Write new content. Returns {'diff', 'restart_required', 'old_size', 'new_size'}."""
    target = _validate_rel(rel)
    if not target.exists():
        raise FileNotFoundError(rel)
    old = target.read_text(encoding="utf-8")
    if old == new_content:
        return {"diff": "", "restart_required": False, "old_size": len(old),
                "new_size": len(new_content), "changed": False}
    diff = "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
        n=3,
    ))
    target.write_text(new_content, encoding="utf-8")
    rel_norm = rel.replace("\\", "/")
    return {
        "diff": diff,
        "restart_required": rel_norm in _RESTART_REQUIRED,
        "old_size": len(old),
        "new_size": len(new_content),
        "changed": True,
    }
