"""Preflight: verify optional dependencies before booting the dashboard.

The web dashboard relies on libraries that are not strictly required to run
the rest of ETHmachine in CLI-only mode. If any are missing, we don't crash —
we print a clear, actionable instruction list and skip starting the web.
"""
from __future__ import annotations

import importlib
import shutil
import sys
from dataclasses import dataclass, field


# (importable name, pip name, minimum version note, why we need it)
_REQUIRED: tuple[tuple[str, str, str, str], ...] = (
    ("aiohttp", "aiohttp>=3.9.0", "3.9+", "HTTP/WebSocket server"),
    ("jinja2",  "jinja2>=3.1.0",  "3.1+", "HTML-шаблоны"),
    ("loguru",  "loguru>=0.7.0",  "0.7+", "захват логов в дашборд"),
)


@dataclass
class PreflightResult:
    ok: bool
    missing: list[tuple[str, str, str, str]] = field(default_factory=list)

    def install_command(self) -> str:
        if not self.missing:
            return ""
        return "pip install " + " ".join(spec for _, spec, _, _ in self.missing)

    def render(self) -> str:
        if self.ok:
            return "[web] preflight OK"
        lines = [
            "",
            "=" * 72,
            "[web] dashboard НЕ запущен — отсутствуют зависимости:",
            "",
        ]
        for name, spec, ver, why in self.missing:
            lines.append(f"  • {name}  ({ver})  — {why}")
            lines.append(f"      pip install {spec}")
        lines += [
            "",
            "Шаги для установки:",
            "  1) Активируйте venv (если используете):",
            "         Windows:  .venv\\Scripts\\activate",
            "         Linux/Mac:  source .venv/bin/activate",
            f"  2) Выполните одной командой:",
            f"         {self.install_command()}",
            "  3) Либо обновите все зависимости из requirements.txt:",
            "         pip install -r requirements.txt",
            "  4) Перезапустите main.py — web морда поднимется автоматически.",
            "",
            "Если web не нужен — установите WEB_ENABLED=False",
            "в config/modules/cfg_web.py, и это сообщение пропадёт.",
            "=" * 72,
            "",
        ]
        return "\n".join(lines)


def check() -> PreflightResult:
    """Return PreflightResult with `ok` flag and list of missing packages."""
    missing: list[tuple[str, str, str, str]] = []
    for entry in _REQUIRED:
        modname = entry[0]
        try:
            importlib.import_module(modname)
        except Exception:
            missing.append(entry)
    return PreflightResult(ok=not missing, missing=missing)


def print_instructions(result: PreflightResult, stream=None) -> None:
    """Print render() to stderr (default) or any stream."""
    out = stream or sys.stderr
    out.write(result.render() + "\n")
    try:
        out.flush()
    except Exception:
        pass
