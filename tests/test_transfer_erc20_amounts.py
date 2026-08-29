"""Регрессии модуля переводов ERC-20 (modules/eth/transfer_erc20_tokens).

Ловим два дефекта, которые стоили пользователю денег и доверия к отчётам:
  1. любой неразобранный ``transfer_amount`` молча превращался в «100% баланса»,
     то есть опечатка в одной ячейке data/data.csv выметала кошелёк подчистую;
  2. откатившаяся (reverted) и «повисшая» транзакция всё равно попадали в
     result/token_transfer_result.csv и в счётчик успешных переводов.

Сеть не используется: web3, БД и запись CSV подменяются заглушками.
"""

from __future__ import annotations

import pytest

from modules.eth import transfer_erc20_tokens as tx_mod


# ── Разбор transfer_amount ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("10-20%", (10.0, 20.0, "PERCENT")),
        ("90%", (90.0, 90.0, "PERCENT")),
        (" 50 - 80 % ", (50.0, 80.0, "PERCENT")),
        ("1-3token", (1.0, 3.0, "FIXED")),
        ("5token", (5.0, 5.0, "FIXED")),
        ("5TOKEN", (5.0, 5.0, "FIXED")),
        ("0.25token", (0.25, 0.25, "FIXED")),
    ],
)
def test_parse_amount_range_suffixed_forms(raw, expected):
    """Формы с явным суффиксом читаются ровно так, как описано в cfg_transfer_erc20."""
    assert tx_mod.parse_amount_range(raw) == expected


@pytest.mark.parametrize("raw, expected", [("10-20", (10.0, 20.0)), ("90", (90.0, 90.0))])
def test_parse_amount_range_bare_value_is_token_count(raw, expected):
    """Без суффикса это КОЛИЧЕСТВО токенов — так написано в шапке конфига.

    Раньше здесь возвращался PERCENT, из-за чего '90' означало «90% баланса».
    """
    lo, hi, kind = tx_mod.parse_amount_range(raw)
    assert (lo, hi) == expected
    assert kind == "FIXED", "голое число обязано трактоваться как количество, а не процент"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        "0,5",          # десятичная запятая (частая раскладка RU/UA)
        "0.5 USDT",     # лишняя единица измерения
        "5 eth",
        "abc",
        "10-20-30",     # не диапазон
        "%",            # суффикс без числа
        "token",
        "-5",           # отрицательное
        "nan%",
        "inf",
    ],
)
def test_parse_amount_range_rejects_garbage(raw):
    """Любой мусор — это ValueError, а НЕ «отправить весь баланс».

    Именно молчаливый fallback (100, 100, 'PERCENT') делал опечатку в CSV
    равносильной сливу кошелька.
    """
    with pytest.raises(ValueError):
        tx_mod.parse_amount_range(raw)


def test_parse_amount_range_never_invents_full_sweep():
    """Ни одна некорректная строка не должна давать 100% баланса."""
    for raw in ("0,5", "5 eth", "мусор", "1e-5"):
        with pytest.raises(ValueError):
            tx_mod.parse_amount_range(raw)


def test_validation_catches_bad_amount_before_run():
    """Плохой transfer_amount ловится валидацией до первого RPC-подключения."""
    good_key = "0x" + "11" * 32
    good_addr = "0x" + "22" * 20
    rows = [
        {"from_wallet": good_key, "to_wallet": good_addr, "amount": "10-20%"},
        {"from_wallet": good_key, "to_wallet": good_addr, "amount": "0,5"},
    ]

    errors = tx_mod.validate_token_transfer_data(rows)

    assert any("Строка 2" in e and "0,5" in e for e in errors), errors
    assert not any("Строка 1" in e for e in errors), errors


# ── Учёт результата транзакции ────────────────────────────────────────────────

FROM_KEY = "0x" + "11" * 32
TO_ADDRESS = "0x" + "22" * 20


class _FakeEth:
    """Минимальный web3.eth: нативный перевод без обращения к сети."""

    chain_id = 1

    def __init__(self, receipt_status):
        self._receipt_status = receipt_status

        class _Account:
            @staticmethod
            def sign_transaction(tx, key):
                return type("Signed", (), {"rawTransaction": b"\x01\x02"})()

        self.account = _Account()

    def get_balance(self, address):
        return 10 * 10 ** 18

    def send_raw_transaction(self, raw):
        return b"\xab" * 32

    def get_transaction_receipt(self, tx_hash):
        return type("Receipt", (), {"status": self._receipt_status})()


class _FakeW3:
    def __init__(self, receipt_status):
        self.eth = _FakeEth(receipt_status)

    @staticmethod
    def to_hex(value):
        return "0x" + value.hex()

    @staticmethod
    def from_wei(value, unit):
        return value / 10 ** 18


def _run_native_transfer(monkeypatch, receipt_status):
    """Гоняет transfer_erc20_tokens по нативному пути с фейковым web3.

    Возвращает (список строк result-CSV, список вызовов update_token_stats).
    """
    w3 = _FakeW3(receipt_status)
    csv_rows = []
    stats_calls = []

    monkeypatch.setattr(tx_mod, "get_proxy_list", lambda: [])
    monkeypatch.setattr(
        tx_mod, "connect_with_failover", lambda *a, **k: (w3, None, "rpc://fake", None)
    )
    monkeypatch.setattr(tx_mod, "_create_token_task", lambda *a, **k: 1)
    monkeypatch.setattr(tx_mod, "_update_token_task", lambda *a, **k: None)
    monkeypatch.setattr(tx_mod, "get_explorer_url", lambda net: "https://scan/tx/")
    monkeypatch.setattr(tx_mod, "get_network_symbol", lambda net: "ETH")
    monkeypatch.setattr(
        tx_mod, "_get_native_balance_with_reconnect",
        lambda _w3, session, *a, **k: (5 * 10 ** 18, _w3, session),
    )
    monkeypatch.setattr(
        tx_mod, "_verify_zero_native_balance",
        lambda balance, _w3, session, *a, **k: (balance, _w3, session),
    )
    monkeypatch.setattr(tx_mod, "_compute_gas_fees", lambda _w3: (10 ** 9, 10 ** 9, True))
    monkeypatch.setattr(tx_mod, "get_nonce_safe", lambda *a, **k: 0)
    monkeypatch.setattr(tx_mod, "append_token_result_csv", lambda row: csv_rows.append(row))
    monkeypatch.setattr(
        tx_mod, "update_token_stats",
        lambda **kwargs: stats_calls.append(kwargs),
    )
    # Ожидание подтверждения не должно тормозить тест.
    monkeypatch.setattr(tx_mod.time, "sleep", lambda *_: None)

    tx_mod.transfer_erc20_tokens(
        from_priv=FROM_KEY,
        to_wallet_value=TO_ADDRESS,
        network="ethereum",
        token_address="native",
        token_symbol="ETH",
        amount="1token",
    )
    return csv_rows, stats_calls


def test_reverted_tx_is_not_counted_as_success(monkeypatch):
    """receipt.status == 0 — токены не двигались, значит это провал.

    Раньше такая транзакция попадала в result-CSV и увеличивала счётчик
    успешных, из-за чего отчёт расходился и с ончейном, и с БД.
    """
    csv_rows, stats_calls = _run_native_transfer(monkeypatch, receipt_status=0)

    assert csv_rows == [], "откатившаяся транзакция не должна попадать в result-CSV"
    assert stats_calls, "статистика обязана быть обновлена хотя бы один раз"
    assert all(call.get("success") is False for call in stats_calls), stats_calls


def test_confirmed_tx_is_still_counted_as_success(monkeypatch):
    """receipt.status == 1 — обычный успешный перевод продолжает учитываться."""
    csv_rows, stats_calls = _run_native_transfer(monkeypatch, receipt_status=1)

    assert len(csv_rows) == 1, "подтверждённый перевод обязан попасть в result-CSV"
    assert csv_rows[0]["token_symbol"] == "ETH"
    assert any(call.get("success") is True for call in stats_calls), stats_calls
