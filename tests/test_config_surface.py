"""Конфигурация — публичный контракт с пользователем.

Пользователь правит файлы в ``config/`` руками. Если модуль импортирует
константу, которой там нет, программа падает при выборе пункта меню —
уже после того, как пользователь потратил время на настройку.
Эти тесты ловят такой рассинхрон статически.
"""

from __future__ import annotations

import ast
import importlib

import pytest

from tests.conftest import PROJECT_ROOT

CONFIG_DIR = PROJECT_ROOT / "config"
SKIP_DIR_PARTS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "build", "dist", "scripts", "tests",
}

# Генерируется автоматически при первом запуске main.py и лежит в .gitignore,
# поэтому в чистом клоне его нет.
GENERATED_CONFIG_MODULES = {
    "config.modules.cfg_pinterest",
    "config.cex_settings",
}


def _iter_source_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT)
        if any(part in SKIP_DIR_PARTS for part in rel.parts):
            continue
        yield path


def _collect_config_imports() -> dict[str, set[str]]:
    """``{'config.modules.cfg_x': {'CONST_A', 'CONST_B'}}`` по всему репозиторию."""
    wanted: dict[str, set[str]] = {}
    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — ловится отдельным тестом
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level:
                continue
            if not node.module or not node.module.startswith("config"):
                continue
            wanted.setdefault(node.module, set()).update(
                alias.name for alias in node.names if alias.name != "*"
            )
    return wanted


CONFIG_IMPORTS = _collect_config_imports()


def test_found_config_imports():
    assert CONFIG_IMPORTS, "не нашли ни одного импорта из config/ — сломан обход"


@pytest.mark.parametrize("module_name", sorted(CONFIG_IMPORTS))
def test_config_module_exposes_imported_names(module_name: str):
    if module_name in GENERATED_CONFIG_MODULES:
        pytest.skip(f"{module_name} генерируется при первом запуске")
    module = importlib.import_module(module_name)
    missing: list[str] = []
    for name in sorted(CONFIG_IMPORTS[module_name]):
        if hasattr(module, name):
            continue
        # `from config import networks` — импорт подмодуля, а не атрибута.
        try:
            importlib.import_module(f"{module_name}.{name}")
        except ImportError:
            missing.append(name)
    assert not missing, f"{module_name} не содержит: {missing}"


def test_networks_entries_are_well_formed():
    from config.networks import NETWORKS

    problems: list[str] = []
    for name, cfg in NETWORKS.items():
        if not isinstance(cfg, dict):
            problems.append(f"{name}: не словарь")
            continue
        rpcs = cfg.get("rpc_urls") or []
        if not rpcs:
            problems.append(f"{name}: пустой rpc_urls")
        if not all(isinstance(u, str) and u.startswith("http") for u in rpcs):
            problems.append(f"{name}: rpc_url без схемы http(s)")
        if not cfg.get("symbol"):
            problems.append(f"{name}: нет symbol")
        if cfg.get("type") not in {"mainnet", "testnet"}:
            problems.append(f"{name}: неизвестный type={cfg.get('type')!r}")
        chain_id = cfg.get("chain_id")
        if chain_id is not None and not isinstance(chain_id, int):
            problems.append(f"{name}: chain_id не int")
    assert not problems, problems


def test_no_duplicate_rpc_urls_within_a_network():
    from config.networks import NETWORKS

    problems: list[str] = []
    for name, cfg in NETWORKS.items():
        urls = list(cfg.get("rpc_urls") or [])
        duplicates = sorted({u for u in urls if urls.count(u) > 1})
        if duplicates:
            problems.append(f"{name}: {duplicates}")
    assert not problems, f"повторяющиеся RPC внутри сети: {problems}"


def test_network_names_are_unique_case_insensitively():
    from config.networks import NETWORKS

    lowered = [n.lower() for n in NETWORKS]
    duplicates = sorted({n for n in lowered if lowered.count(n) > 1})
    assert not duplicates, f"сети дублируются с точностью до регистра: {duplicates}"
