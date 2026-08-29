"""Регрессии по config/networks.py и config/token_address_erc20.py.

Эти два файла пользователь правит руками, а модули читают их насквозь —
поэтому опечатка здесь всплывает не при импорте, а в момент вывода средств.
Тесты закрывают три реально случившихся дефекта:

* модуль обращается к ``networks.<имя>``, которого в файле нет
  (падало AttributeError на выводе с OKX/MEXC/Binance);
* explorer одной сети скопирован в другую (ссылки на транзакции вели в никуда);
* адреса токенов скопированы из чужой сети (риск отправки в никуда).

Сети наружу не дёргаем — только статический разбор исходников.
"""

from __future__ import annotations

import ast
import importlib
from collections import defaultdict
from urllib.parse import urlparse

from tests.conftest import PROJECT_ROOT

SKIP_DIR_PARTS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "build", "dist", "scripts", "tests",
}


def _iter_source_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT)
        if any(part in SKIP_DIR_PARTS for part in rel.parts):
            continue
        yield path


def _aliases_for_networks(tree: ast.AST) -> set[str]:
    """Имена, под которыми в файле доступен модуль ``config.networks``.

    Ловит обе формы: ``from config import networks as rpc``
    и ``import config.networks as rpc``.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "config" and not node.level:
            for alias in node.names:
                if alias.name == "networks":
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "config.networks" and alias.asname:
                    aliases.add(alias.asname)
    return aliases


def _collect_networks_attribute_access() -> dict[str, set[str]]:
    """``{'modules/cex/okx/okx_withdraw.py': {'L1', 'sepolia', ...}}``."""
    used: dict[str, set[str]] = {}
    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — ловится отдельным тестом
            continue
        aliases = _aliases_for_networks(tree)
        if not aliases:
            continue
        attrs = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
        }
        if attrs:
            used[str(path.relative_to(PROJECT_ROOT))] = attrs
    return used


NETWORKS_ATTR_USAGE = _collect_networks_attribute_access()


def test_found_networks_attribute_usage():
    """Страховка от «зелёного» теста при сломанном обходе исходников."""
    assert NETWORKS_ATTR_USAGE, "не нашли ни одного обращения к networks.<attr>"


def test_networks_exposes_every_attribute_modules_use():
    """Каждое ``rpc.<attr>`` должно существовать в config/networks.py.

    Словарь chain_mapping в модулях вывода собирается целиком до вызова
    ``.get()``, поэтому одно отсутствующее имя роняет вывод на ЛЮБОЙ сети,
    а не только на той, к которой это имя относится.
    """
    networks = importlib.import_module("config.networks")
    missing: dict[str, list[str]] = {}
    for file_path, attrs in sorted(NETWORKS_ATTR_USAGE.items()):
        absent = sorted(a for a in attrs if not hasattr(networks, a))
        if absent:
            missing[file_path] = absent
    assert not missing, f"config/networks.py не содержит: {missing}"


def test_explorer_hosts_are_not_shared_between_networks():
    """Ровно один и тот же хост explorer'а на две сети — копипаста tx_url.

    Проверка намеренно грубая (сравниваем netloc целиком): домены вроде
    etherscan.io и blockscout.com легитимно обслуживают по несколько сетей,
    поэтому сравнивать на уровне домена нельзя — будут ложные срабатывания
    у пользователя, который добавит свою сеть.

    Случай MONAD → Manta этот тест НЕ ловит (`pacific-explorer.manta.network`
    и `explorer.manta.network` — разные хосты), под него отдельный тест ниже.
    """
    from config.networks import NETWORKS, SOL_NETWORKS

    hosts: dict[str, list[str]] = defaultdict(list)
    for name, cfg in list(NETWORKS.items()) + list(SOL_NETWORKS.items()):
        hosts[urlparse(cfg["tx_url"]).netloc].append(name)

    shared = {host: names for host, names in hosts.items() if len(names) > 1}
    assert not shared, f"один explorer на несколько сетей: {shared}"


def test_monad_explorer_is_a_monad_explorer():
    """MONAD ссылался на explorer Manta — ссылки на транзакции вели в чужую сеть.

    RPC сети отдаёт chain_id 0x8f (143) — это Monad mainnet, поэтому и explorer
    должен быть mainnet-овый. Список взят из документации Monad; testnet-овый
    monadexplorer.com сюда не годится, он обслуживает chain_id 10143.
    """
    from config.networks import NETWORKS

    host = urlparse(NETWORKS['🚀 MONAD']['tx_url']).netloc
    assert host in {'monadscan.com', 'monadvision.com'}, (
        f"tx_url MONAD ведёт на {host!r} — это не explorer Monad mainnet"
    )


def test_token_maps_do_not_reuse_a_foreign_stablecoin_address():
    """USDC/USDT одной сети не должны повторяться в другой.

    Стейблкоины деплоятся под каждую сеть отдельно, поэтому совпадение
    адреса — копипаста (так в somnia попали адреса Base). Обёртки вроде
    WETH исключены намеренно: на OP Stack это один и тот же предеплой
    ``0x4200...0006`` сразу в нескольких сетях, и это законно.
    """
    from config import token_address_erc20 as tokens

    stable_prefixes = ("usdc", "usdt")
    seen: dict[str, list[str]] = defaultdict(list)
    for var_name, mapping in vars(tokens).items():
        if var_name.startswith("_") or not isinstance(mapping, dict):
            continue
        for symbol, address in mapping.items():
            if not symbol.lower().startswith(stable_prefixes):
                continue
            if not isinstance(address, str) or not address.startswith("0x"):
                continue
            seen[address.lower()].append(f"{var_name}.{symbol}")

    shared = {addr: where for addr, where in seen.items() if len(where) > 1}
    assert not shared, f"адрес стейблкоина повторяется в разных сетях: {shared}"
