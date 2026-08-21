"""Документация не должна расходиться с кодом.

README и docs/ — первое, что видит пользователь. Ссылка на несуществующий
файл или упоминание удалённого модуля обходятся дороже, чем кажется:
человек ищет то, чего нет, и решает, что сломан инструмент.
"""

from __future__ import annotations

import re

import pytest

from tests.conftest import PROJECT_ROOT

README = PROJECT_ROOT / "README.md"
DOCS_DIR = PROJECT_ROOT / "docs"

# Markdown-ссылки вида [текст](путь) — без внешних URL и якорей.
_LINK_RE = re.compile(r"\[[^\]]*\]\((?!https?://|#)([^)#\s]+)")
# Пути к файлам проекта, упомянутые в тексте (config/x.py, modules/y.py).
_PATH_RE = re.compile(r"`((?:config|modules|web|tests|data|db|assets)/[\w./-]+\.\w+)`")


def _markdown_files() -> list:
    files = [README]
    files += sorted(DOCS_DIR.rglob("*.md"))
    return [f for f in files if f.exists()]


def test_readme_exists_and_is_substantial():
    assert README.exists()
    assert len(README.read_text(encoding="utf-8")) > 2000


@pytest.mark.parametrize(
    "doc", _markdown_files(), ids=lambda p: str(p.relative_to(PROJECT_ROOT))
)
def test_relative_links_resolve(doc):
    """Каждая относительная ссылка ведёт на существующий файл."""
    broken: list[str] = []
    for target in _LINK_RE.findall(doc.read_text(encoding="utf-8")):
        resolved = (doc.parent / target).resolve()
        if not resolved.exists():
            broken.append(target)
    assert not broken, f"битые ссылки в {doc.name}: {broken}"


def test_readme_does_not_reference_missing_project_files():
    """README не должен ссылаться на файлы, которых нет в проекте."""
    text = README.read_text(encoding="utf-8")
    missing = sorted({
        path for path in _PATH_RE.findall(text)
        if not (PROJECT_ROOT / path).exists()
    })
    # Эти пути создаются при первом запуске и в чистом клоне отсутствуют.
    generated = {
        "config/cex_settings.py",
        "config/modules/cfg_pinterest.py",
        "data/data.csv",
    }
    missing = [m for m in missing if m not in generated]
    assert not missing, f"README ссылается на несуществующие файлы: {missing}"


def test_readme_network_counts_match_config():
    """Числа сетей в README должны совпадать с config/networks.py."""
    from config.networks import NETWORKS

    mainnet = sum(1 for cfg in NETWORKS.values() if cfg.get("type") == "mainnet")
    testnet = sum(1 for cfg in NETWORKS.values() if cfg.get("type") == "testnet")
    text = README.read_text(encoding="utf-8")

    assert f"Mainnet ({mainnet})" in text, (
        f"README должен указывать Mainnet ({mainnet})"
    )
    assert f"Testnet ({testnet})" in text, (
        f"README должен указывать Testnet ({testnet})"
    )


def test_readme_documents_every_module_in_the_menu():
    """Каждый модуль, доступный из меню, должен быть упомянут в README.

    Это тот случай, когда каталог возможностей устаревает первым: модуль
    добавили, README забыли.
    """
    import config.menu_config as mc

    text = README.read_text(encoding="utf-8").lower()
    catalogued = [
        mc.BALANCES_SUBMENU, mc.TRANSACTIONS_SUBMENU, mc.PROJECTS_SUBMENU,
        mc.CEX_SUBMENU, mc.TOOLS_SUBMENU,
    ]
    missing: list[str] = []
    for submenu in catalogued:
        for item in submenu.get_enabled_items():
            if item.key == mc.BACK_KEY:
                continue
            if item.label.lower() not in text:
                missing.append(f"{submenu.key}.{item.label}")
    assert not missing, f"README не описывает модули: {missing}"


def test_no_references_to_removed_config_files():
    """config/config.py и config/rpc.py удалены — упоминаний быть не должно."""
    offenders: list[str] = []
    for doc in _markdown_files():
        text = doc.read_text(encoding="utf-8")
        for ghost in ("config/config.py", "config/rpc.py"):
            if ghost in text:
                offenders.append(f"{doc.relative_to(PROJECT_ROOT)} -> {ghost}")
    assert not offenders, f"ссылки на удалённые конфиги: {offenders}"
