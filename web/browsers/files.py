"""Files browser — listing + safe download for data/, result/, db/."""
from __future__ import annotations

import pathlib
from typing import Any

from web.core.paths import DATA_DIR, DB_DIR, RESULT_DIR, ROOT, safe_under


ROOTS: dict[str, pathlib.Path] = {
    "data": DATA_DIR,
    "result": RESULT_DIR,
    "db": DB_DIR,
}


def _resolve(root_key: str, rel_path: str) -> pathlib.Path:
    if root_key not in ROOTS:
        raise ValueError(f"unknown root: {root_key}")
    root = ROOTS[root_key]
    rel = (root / (rel_path or "")).resolve()
    if not safe_under(root, rel):
        raise PermissionError("path traversal blocked")
    return rel


def list_dir(root_key: str, rel_path: str = "") -> dict[str, Any]:
    target = _resolve(root_key, rel_path)
    if not target.exists():
        # the root itself may not exist yet — return an empty listing rather than 404
        return {"root": root_key, "path": rel_path, "entries": []}
    if target.is_file():
        raise IsADirectoryError("not a directory")
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            stat = p.stat()
        except OSError:
            continue
        entries.append({
            "name": p.name,
            "is_dir": p.is_dir(),
            "size": stat.st_size if p.is_file() else 0,
            "rel": p.relative_to(ROOTS[root_key]).as_posix(),
        })
    return {"root": root_key, "path": rel_path, "entries": entries}


def file_for_download(root_key: str, rel_path: str) -> pathlib.Path:
    target = _resolve(root_key, rel_path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(rel_path)
    return target
