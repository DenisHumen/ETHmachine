"""Защита обратной совместимости.

Пользователь обновляется через ``git pull`` и продолжает работать: его
``data/data.csv``, настройки в ``config/`` и базы в ``db/`` остаются
рабочими. Всё, что здесь перечислено, — публичный контракт. Меняете —
ломаете чужие установки, поэтому список зафиксирован тестами.

Если вы осознанно добавляете новую базу, таблицу или колонку — допишите её
в соответствующий набор. Если тест упал на переименовании существующей —
это не тест «мешает», это предупреждение, что обновление сломает людей.
"""

from __future__ import annotations

import ast
import re

import pytest

from tests.conftest import PROJECT_ROOT

SKIP_DIR_PARTS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "build", "dist", "scripts", "tests",
}

# ── Колонки data/data.csv ────────────────────────────────────────────────

EXPECTED_DATA_COLUMNS = [
    "name", "private_key", "proxy", "reserve_proxy",
    "wallet_address", "mnemonic", "sol_address", "sol_private_key",
    "discord_token", "email", "email_password", "email_imap",
    "referral_code", "evm_cex_address", "sol_cex_address",
    "transfer_amount",
]

# ── Файлы баз под db/ ────────────────────────────────────────────────────

EXPECTED_DB_FILES = {
    "binance_withdraw_progress.db",
    "bitget_withdraw_progress.db",
    "dai_withdraw.db",
    "debank_checker.db",
    "dune_base_checker.db",
    "eth_balance_tasks.db",
    "fhenix_alchemy_base_sepolia.db",
    "fhenix_ghost_faucet.db",
    "litvm.db",
    "mexc_withdraw_progress.db",
    "neura_stats_progress.db",
    "okx_withdraw_progress.db",
    "proxy_checker.db",
    "relay_progress.db",
    "safepal_x1_checker.db",
    "swap_all_polygon_zkevm_to_base.db",
    "swap_all_zksync_era_to_base.db",
    "transfer_kava_to_cex.db",
    "transfer_tasks.db",
    "twitter_tasks_progress.db",
    "web_admin.db",
    "xstocks.db",
    "zksync_lite_balance.db",
    "zksync_lite_swap.db",
}

# ── Таблицы ──────────────────────────────────────────────────────────────

EXPECTED_TABLES = {
    "actions_log", "audit_log", "ayni_wrap_tasks", "bridge_tx_tasks",
    "bridge_wallet_tasks", "check_tasks", "config_changes", "dai_tasks",
    "debank_balances", "debank_protocol_tasks", "debank_protocols",
    "debank_tasks", "eth_balance_tasks", "faucet_wallet_tasks", "gm_history",
    "kava_transfer_tasks", "kava_wallets", "midas_bets", "midas_checkins",
    "midas_faucet_claims", "midas_wallets", "minter_deployments",
    "minter_wallet_tasks", "onmi_coin_tasks", "onmi_known_tokens",
    "onmi_lp_history", "onmi_lp_positions", "onmi_swap_history",
    "onmi_swap_known_pairs", "onmi_trade_history", "operations",
    "price_history", "processing_progress", "referral_codes", "relay_progress",
    "request_history", "results", "runs", "service_results", "sessions",
    "swap_all_tasks", "swap_tasks", "tasks", "token_transfer_tasks",
    "transactions", "transfer_statistics", "transfer_tasks", "users",
    "vcrcs_cookies", "wallet_stats_json", "wallet_tasks", "wallets",
    "withdraw_progress", "zksync_lite_tasks", "zns_registrations",
}

# Имя файла базы встречается и как "x.db", и как "db/x.db".
_DB_RE = re.compile(r"""['"](?:[\w./\\-]*[/\\])?([a-z_0-9]+\.db)['"]""")
_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+([a-zA-Z_0-9]+)", re.IGNORECASE)


def _source_files():
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT)
        if any(part in SKIP_DIR_PARTS for part in rel.parts):
            continue
        yield path


def _all_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in _source_files())


SOURCE = _all_source()


def test_data_csv_columns_unchanged():
    from modules.data_manager import HEADERS

    assert HEADERS == EXPECTED_DATA_COLUMNS, (
        "изменился набор или порядок колонок data/data.csv — "
        "у существующих пользователей файл перестанет читаться"
    )


def test_no_new_or_renamed_database_files():
    found = set(_DB_RE.findall(SOURCE))
    unexpected = sorted(found - EXPECTED_DB_FILES)
    assert not unexpected, (
        f"появились новые пути баз: {unexpected}. Если это осознанно — "
        f"добавьте их в EXPECTED_DB_FILES"
    )


def test_existing_database_files_still_referenced():
    found = set(_DB_RE.findall(SOURCE))
    missing = sorted(EXPECTED_DB_FILES - found)
    assert not missing, (
        f"базы больше не используются: {missing}. Переименование пути означает, "
        f"что прогресс существующих пользователей потеряется"
    )


def test_no_renamed_tables():
    found = {name.lower() for name in _TABLE_RE.findall(SOURCE)}
    unexpected = sorted(found - EXPECTED_TABLES)
    missing = sorted(EXPECTED_TABLES - found)
    assert not unexpected, f"новые таблицы: {unexpected} — допишите в EXPECTED_TABLES"
    assert not missing, (
        f"таблицы исчезли: {missing} — существующие базы станут нечитаемыми"
    )


def test_public_entry_points_exist():
    """Функции, которые вызывает main.py, должны существовать под теми же именами."""
    import importlib

    entry_points = {
        "modules.backup": "backup_menu",
        "modules.check_proxy": "check_proxy_menu",
        "modules.data_manager": "select_data_file",
        "modules.dune": "dune_menu",
        "modules.eth.safepal_x1_checker": "safepal_x1_checker_menu",
        "modules.eth.swap_all_polygon_zkevm_to_base": "run_swap_all_polygon_zkevm_to_base",
        "modules.eth.swap_all_zksync_era_to_base": "run_swap_all_zksync_era_to_base",
        "modules.eth.transfer_kava_to_cex": "run_transfer_kava_to_cex",
        "modules.fhenix.menu": "fhenix_menu",
        "modules.info": "info",
        "modules.litvm_testnet": "litvm_testnet_menu",
        "modules.sahara": "run_sahara",
        "modules.xstocks.menu": "xstocks_menu",
        "modules.zksync_lite": "zksync_lite_menu",
    }
    missing = []
    for module_name, symbol in entry_points.items():
        module = importlib.import_module(module_name)
        if not hasattr(module, symbol):
            missing.append(f"{module_name}.{symbol}")
    assert not missing, f"пропали публичные точки входа: {missing}"


def test_generated_config_templates_match_importers():
    """Шаблон cex_settings.py должен содержать всё, что импортирует код."""
    from modules import bootstrap

    template = bootstrap._cex_settings_template()
    wanted: set[str] = set()
    for path in _source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "config.cex_settings":
                wanted.update(alias.name for alias in node.names if alias.name != "*")
    missing = sorted(name for name in wanted if name not in template)
    assert not missing, (
        f"шаблон config/cex_settings.py не содержит {missing} — "
        f"у нового пользователя модуль упадёт при первом запуске"
    )
