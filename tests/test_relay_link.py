"""Регрессии моста Relay Link.

Три вещи, которые тут закрепляются:
1. Хеш транзакции попадает в БД ДО долгого ожидания поступления средств,
   а резюме не бриджит повторно кошелёк, у которого деньги уже в пути.
2. Бюджет опроса берётся из документированных ручек, а не из задержки между действиями.
3. Адреса токенов — производная от config/token_address_erc20.py, второй копии нет.

Сеть не трогаем: RelayBridge создаётся в обход __init__ (он пишет в реальные
db/ и result/ по абсолютному пути), БД — временная.
"""

from __future__ import annotations

import sqlite3

import pytest

from config import token_address_erc20
from config.modules.general_config import (
    WHAITE_TRANSACTION_PENDING,
    WHAITE_TRANSACTION_PENDING_COUNT,
)
from modules.relay_link import relay_link as relay_module
from modules.relay_link.relay_link import RelayBridge
from modules.relay_link.settings import settings_relay_link as relay_settings

# Тестовый ключ, никогда не использовавшийся в мейннете
TEST_PRIVATE_KEY = '0x' + '11' * 32
TEST_TX_HASH = '0x' + 'ab' * 32


@pytest.fixture()
def bridge(tmp_path):
    """RelayBridge с временной БД и без сетевых зависимостей."""
    obj = RelayBridge.__new__(RelayBridge)
    obj.db_path = str(tmp_path / 'relay_progress.db')
    obj.wallet_pairs = {}
    obj.web3_connections = {}
    obj.rpc_pools = {}
    obj.chain_id_to_explorer_network = {}
    RelayBridge._init_database(obj)
    return obj


def _test_wallet_address() -> str:
    from web3 import Web3

    return Web3().eth.account.from_key(TEST_PRIVATE_KEY).address


def _insert_row(bridge, wallet: str, status: str = 'pending', tx_hash=None) -> None:
    conn = sqlite3.connect(bridge.db_path)
    conn.execute(
        "INSERT INTO relay_progress "
        "(wallet_address, private_key_hash, from_network, to_network, amount, status, tx_hash) "
        "VALUES (?, '', 'base', 'linea', 0.001, ?, ?)",
        (wallet, status, tx_hash),
    )
    conn.commit()
    conn.close()


def _row(bridge, wallet: str) -> sqlite3.Row:
    conn = sqlite3.connect(bridge.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT * FROM relay_progress WHERE wallet_address = ?', (wallet,)
    ).fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# Резюмируемость
# ---------------------------------------------------------------------------

def test_tx_sent_saves_hash_immediately(bridge):
    """Промежуточный статус кладёт хеш в БД — резюме увидит, что деньги ушли."""
    wallet = '0xAAA'
    _insert_row(bridge, wallet)

    bridge._save_transaction_result(wallet, TEST_TX_HASH, 0, 'tx_sent')

    row = _row(bridge, wallet)
    assert row['tx_hash'] == TEST_TX_HASH
    assert row['status'] == 'tx_sent'


def test_final_status_lands_after_intermediate(bridge):
    """Финальный статус пишется поверх 'tx_sent'.

    Раньше UPDATE был ограничен status='pending' и после промежуточной записи
    попадал в ноль строк — итог бриджа молча терялся.
    """
    wallet = '0xBBB'
    _insert_row(bridge, wallet)

    bridge._save_transaction_result(wallet, TEST_TX_HASH, 0, 'tx_sent')
    bridge._save_transaction_result(wallet, TEST_TX_HASH, 0.00002, 'completed')

    row = _row(bridge, wallet)
    assert row['status'] == 'completed'
    assert row['bridge_fee'] == pytest.approx(0.00002)


def test_error_does_not_erase_saved_tx_hash(bridge):
    """Ветка с ошибкой передаёт tx_hash=None и не должна затирать сохранённый хеш."""
    wallet = '0xCCC'
    _insert_row(bridge, wallet)

    bridge._save_transaction_result(wallet, TEST_TX_HASH, 0, 'tx_sent')
    bridge._save_transaction_result(wallet, None, 0, 'error', 'RPC умер')

    row = _row(bridge, wallet)
    assert row['tx_hash'] == TEST_TX_HASH
    assert row['status'] == 'error'


def test_completed_row_is_never_overwritten(bridge):
    """Завершённая запись терминальна: поздний апдейт по кошельку её не трогает."""
    wallet = '0xDDD'
    _insert_row(bridge, wallet)

    bridge._save_transaction_result(wallet, TEST_TX_HASH, 0.00001, 'completed')
    bridge._save_transaction_result(wallet, None, 0, 'failed')

    assert _row(bridge, wallet)['status'] == 'completed'


def test_wallet_with_sent_tx_is_not_bridged_again(bridge):
    """Кошелёк с уже отправленной транзакцией пропускается без нового бриджа.

    Флаг, а не raise: `_process_wallet` глушит любые Exception и всё равно
    вернул бы False, так что исключение регрессию не поймало бы.
    """
    wallet = _test_wallet_address()
    _insert_row(bridge, wallet, status='tx_sent', tx_hash=TEST_TX_HASH)

    calls = []
    bridge._check_balances = lambda *args, **kwargs: (calls.append(1), {})[1]

    assert bridge._process_wallet(TEST_PRIVATE_KEY, 0) is False
    assert not calls, 'обработка дошла до бриджа — деньги ушли бы второй раз'
    assert _row(bridge, wallet)['status'] == 'tx_sent'


def test_bridge_saves_hash_before_arrival_poll():
    """Запись хеша обязана стоять ДО опроса поступления средств.

    В этом весь смысл резюмируемости (AGENTS.md §14.3): опрос длится минуты,
    и прерывание внутри него не должно оставлять запись без tx_hash.
    """
    import inspect

    for method in (RelayBridge._execute_bridge, RelayBridge._execute_solana_bridge):
        src = inspect.getsource(method)
        assert "'tx_sent'" in src, method.__name__
        assert src.index("'tx_sent'") < src.index('_check_balance_changes'), method.__name__


def test_reverted_wallet_may_be_retried(bridge):
    """Откаченная сетью транзакция средств не тратит — повтор разрешён."""
    wallet = _test_wallet_address()
    _insert_row(bridge, wallet, status='reverted', tx_hash=TEST_TX_HASH)

    calls = []

    def _record(*args, **kwargs):
        calls.append(args)
        return {}

    bridge._check_balances = _record

    bridge._process_wallet(TEST_PRIVATE_KEY, 0)
    assert calls, 'после reverted обработка кошелька должна продолжиться'


# ---------------------------------------------------------------------------
# Опрос поступления средств
# ---------------------------------------------------------------------------

def test_arrival_poll_plan_uses_documented_knobs():
    """Интервал — ручка модуля, бюджет — WHAITE_* из general_config (AGENTS.md §9.4)."""
    interval, attempts = RelayBridge._arrival_poll_plan()

    assert interval == relay_settings.BALANCE_CHECK_INTERVAL
    budget = WHAITE_TRANSACTION_PENDING * WHAITE_TRANSACTION_PENDING_COUNT
    assert attempts == max(1, budget // interval)
    # Защита от возврата к SLEEP_BETWEEN_ACTIONS: тогда получалось ~225 проверок
    assert attempts <= 60


def test_native_balance_uses_first_working_source(bridge, monkeypatch):
    """Баланс берём у первой живой ноды, а не max() по всем RPC."""

    class _FakeEth:
        @staticmethod
        def get_balance(_address):
            return 10 ** 18  # 1.0 в wei

    class _FakeWeb3:
        eth = _FakeEth()

        @staticmethod
        def from_wei(value, _unit):
            return value / 10 ** 18

    def _no_new_providers(*args, **kwargs):
        raise AssertionError('лишнее подключение: кешированной ноды уже достаточно')

    bridge.web3_connections[8453] = _FakeWeb3()
    bridge.rpc_pools[8453] = ['http://never-used']
    monkeypatch.setattr(relay_module, 'Web3', _no_new_providers)

    assert bridge._get_native_balance(8453, '0xAAA') == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Адреса токенов
# ---------------------------------------------------------------------------

def test_token_addresses_come_from_config():
    """Адреса — производная от config/token_address_erc20.py, без второй копии."""
    assert relay_settings.TOKEN_ADDRESSES[1]['USDC'] == token_address_erc20.ethereum_mainnet['usdc']
    assert relay_settings.TOKEN_ADDRESSES[8453]['USDC'] == token_address_erc20.base['usdc']
    assert relay_settings.TOKEN_ADDRESSES[8453]['USDT'] == token_address_erc20.base['usdt']


def test_phantom_usdc_address_is_gone():
    """0xA0b86a33...Ca51 стоял как «USDC» сразу в трёх сетях и не существует ни в одной."""
    phantom = '0xa0b86a33e6441446ff2eae9f6c6b0dfec9e8ca51'
    for chain_id, tokens in relay_settings.TOKEN_ADDRESSES.items():
        for symbol, address in tokens.items():
            assert address.lower() != phantom, f'{chain_id}/{symbol}'


def test_every_network_exposes_its_native_token():
    """Котировка берёт адрес нативной монеты по символу — он обязан быть у каждой сети."""
    for chain_id, settings in relay_settings.NETWORK_SETTINGS.items():
        tokens = relay_settings.TOKEN_ADDRESSES[chain_id]
        assert settings['native_symbol'] in tokens
