"""Тесты transfer_wallets_to_wallets: деньги не уходят дважды, статистика не падает.

Сети не касаемся: Web3 подменён заглушкой, БД — во временном каталоге.
"""

from __future__ import annotations

import sqlite3

import pytest
from eth_account import Account
from hexbytes import HexBytes
from web3 import Web3
from web3.exceptions import TransactionNotFound

from modules.eth import transfer_wallets_to_wallets as m

NETWORK = "🚀 Base"
EXPLORER = "https://basescan.org/tx/"
PRIVATE_KEY = "0x" + "11" * 32
TO_ADDRESS = Account.from_key("0x" + "22" * 32).address


class _Receipt:
    """Минимальный receipt: коду нужен только status."""

    def __init__(self, status: int = 1):
        self.status = status


class _FakeEth:
    """Заглушка w3.eth со счётчиком broadcast-ов."""

    def __init__(self, receipts=None, known_txs=()):
        self.chain_id = 8453
        self.gas_price = 10**9
        self.sent = []  # сюда попадает каждый вызов send_raw_transaction
        self._receipts = dict(receipts or {})
        self._known = {h.lower() for h in known_txs}

    def get_balance(self, address):
        return Web3.to_wei(1, "ether")

    def get_transaction_count(self, address):
        return 0

    def get_block(self, _block):
        return {}  # нет baseFeePerGas → legacy-ветка, меньше движущихся частей

    def send_raw_transaction(self, raw):
        tx_hash = HexBytes(Web3.keccak(raw))
        self.sent.append(tx_hash.hex())
        return tx_hash

    def get_transaction_receipt(self, tx_hash):
        receipt = self._receipts.get(str(tx_hash).lower())
        if receipt is None:
            raise TransactionNotFound(str(tx_hash))
        return receipt

    def get_transaction(self, tx_hash):
        if str(tx_hash).lower() in self._known:
            return {"hash": tx_hash}
        raise TransactionNotFound(str(tx_hash))


class _FakeW3:
    def __init__(self, eth: _FakeEth):
        self.eth = eth

    def is_connected(self):
        return True

    def from_wei(self, value, unit):
        return Web3.from_wei(value, unit)

    def to_wei(self, value, unit):
        return Web3.to_wei(value, unit)


@pytest.fixture()
def db(tmp_project, monkeypatch):
    """Свежая БД задач во временном каталоге."""
    monkeypatch.setattr(m, "DB_DIR", tmp_project / "db")
    monkeypatch.setattr(m, "DB_FILE", tmp_project / "db" / "transfer_tasks.db")
    monkeypatch.setattr(m, "RESULT_DIR", tmp_project / "result")
    m._init_db()
    return tmp_project


def _make_task(amount: str = "0.1"):
    """Создать одну задачу в БД и вернуть её словарь."""
    m._create_tasks(
        [{"from_wallet": PRIVATE_KEY, "to_wallet": TO_ADDRESS, "amount": amount}],
        NETWORK,
        [],
    )
    return m._get_pending_tasks(NETWORK)[0]


def _install_fake_web3(monkeypatch, eth: _FakeEth):
    """Подменить сеть и ускорить опрос подтверждения."""
    monkeypatch.setattr(m, "_get_web3", lambda rpc, proxy=None: (_FakeW3(eth), None))
    monkeypatch.setattr(m, "WHAITE_TRANSACTION_PENDING_COUNT", 2)
    monkeypatch.setattr(m, "WHAITE_TRANSACTION_PENDING", 1)
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)


def _run(task):
    return m._process_single_transfer(
        task=task,
        rpc_urls=["http://rpc.local"],
        explorer_url=EXPLORER,
        symbol="ETH",
        total_tasks=1,
        task_index=1,
    )


def _task_row(task_id: int) -> dict:
    with sqlite3.connect(str(m.DB_FILE)) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM transfer_tasks WHERE id = ?", (task_id,)).fetchone())


# ── дубль отправки ────────────────────────────────────────────────────────────


def test_receipt_timeout_does_not_resend(db, monkeypatch):
    """Не дождались receipt — транзакция НЕ отправляется повторно."""
    eth = _FakeEth()  # receipt не появится никогда
    _install_fake_web3(monkeypatch, eth)
    monkeypatch.setattr(m, "RETRY_COUNT", 15)

    task = _make_task()
    assert _run(task) is False

    # Главное: ровно один broadcast, несмотря на RETRY_COUNT = 15.
    assert len(eth.sent) == 1

    row = _task_row(task["id"])
    assert row["status"] == "tx_sent"
    assert row["tx_hash"] == eth.sent[0]
    assert "Не дождались подтверждения" in row["error_message"]


def test_unconfirmed_task_is_polled_not_resent(db, monkeypatch):
    """Задача в статусе tx_sent до-опрашивается по своему хэшу, без отправки."""
    eth = _FakeEth()
    _install_fake_web3(monkeypatch, eth)

    task = _make_task()
    assert _run(task) is False
    tx_hash = eth.sent[0]

    # Второй запуск: транзакция к этому моменту попала в блок.
    eth2 = _FakeEth(receipts={tx_hash.lower(): _Receipt(status=1)})
    _install_fake_web3(monkeypatch, eth2)

    resumed = m._get_pending_tasks(NETWORK)[0]
    assert resumed["status"] == "tx_sent"
    assert _run(resumed) is True

    assert eth2.sent == []  # ни одной новой отправки
    row = _task_row(task["id"])
    assert row["status"] == "completed"
    assert row["tx_hash"] == tx_hash


def test_unconfirmed_task_stays_in_queue(db, monkeypatch):
    """tx_sent остаётся в очереди — иначе подтверждение потеряется навсегда."""
    eth = _FakeEth()
    _install_fake_web3(monkeypatch, eth)

    task = _make_task()
    _run(task)

    pending = m._get_pending_tasks(NETWORK)
    assert [t["id"] for t in pending] == [task["id"]]
    assert m._get_stats_summary(NETWORK)["unconfirmed"] == 1


def test_lost_send_response_is_not_resent(db, monkeypatch):
    """Ответ RPC потерян, но транзакция в мемпуле — считаем её отправленной."""

    class _LosingEth(_FakeEth):
        def send_raw_transaction(self, raw):
            # Узел принял транзакцию, а ответ до нас не дошёл.
            self.sent.append(HexBytes(Web3.keccak(raw)).hex())
            raise TimeoutError("read timed out")

        def get_transaction(self, tx_hash):
            return {"hash": tx_hash}  # сеть транзакцию уже видит

    eth = _LosingEth()
    _install_fake_web3(monkeypatch, eth)
    monkeypatch.setattr(m, "RETRY_COUNT", 5)

    task = _make_task()
    assert _run(task) is False
    assert len(eth.sent) == 1  # повторной отправки не было

    row = _task_row(task["id"])
    # Хэш взят из локально подписанной транзакции и совпал с реально ушедшим.
    assert row["status"] == "tx_sent"
    assert row["tx_hash"] == eth.sent[0]


def test_send_failure_before_broadcast_still_retries(db, monkeypatch):
    """Транзакция в сеть не ушла — обычный retry должен работать как раньше."""

    class _DeadEth(_FakeEth):
        def send_raw_transaction(self, raw):
            raise ConnectionError("rpc down")

    eth = _DeadEth()  # get_transaction всегда бросает TransactionNotFound
    _install_fake_web3(monkeypatch, eth)
    monkeypatch.setattr(m, "RETRY_COUNT", 3)

    task = _make_task()
    assert _run(task) is False
    assert _task_row(task["id"])["status"] == "failed"


def test_reverted_tx_is_failed_not_completed(db, monkeypatch):
    """Откат транзакции — статус failed: средства не двигались, повтор безопасен."""
    sent_hashes = []

    class _RevertEth(_FakeEth):
        def send_raw_transaction(self, raw):
            tx_hash = super().send_raw_transaction(raw)
            sent_hashes.append(tx_hash)
            self._receipts[tx_hash.hex().lower()] = _Receipt(status=0)
            return tx_hash

    eth = _RevertEth()
    _install_fake_web3(monkeypatch, eth)

    task = _make_task()
    assert _run(task) is False
    assert len(eth.sent) == 1

    row = _task_row(task["id"])
    assert row["status"] == "failed"
    assert "reverted" in row["error_message"]


# ── переполнение SUM() ────────────────────────────────────────────────────────


def test_stats_summary_survives_wei_over_int64(db):
    """Сумма wei больше 2^63 не должна ронять статистику (SQLite integer overflow)."""
    one_token = 10**18
    rows = 20  # 2e19 wei — заметно больше 2^63 ≈ 9.22e18
    with sqlite3.connect(str(m.DB_FILE)) as conn:
        for _ in range(rows):
            conn.execute(
                """INSERT INTO transfer_tasks
                   (from_private_key, from_address, to_wallet, to_address,
                    amount_raw, amount_wei, network, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'completed')""",
                ("k", "0xfrom", TO_ADDRESS, TO_ADDRESS, "1.0", str(one_token), NETWORK),
            )
        conn.commit()

    stats = m._get_stats_summary(NETWORK)

    assert stats["total_wei"] > 2**63
    assert stats["total_wei"] == rows * one_token
    assert stats["total_eth"] == pytest.approx(float(rows))


def test_stats_summary_ignores_broken_amount(db):
    """Мусор в amount_wei не должен ронять весь подсчёт."""
    with sqlite3.connect(str(m.DB_FILE)) as conn:
        for amount in ("1000000000000000000", None, "", "не число"):
            conn.execute(
                """INSERT INTO transfer_tasks
                   (from_private_key, from_address, to_wallet, to_address,
                    amount_raw, amount_wei, network, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'completed')""",
                ("k", "0xfrom", TO_ADDRESS, TO_ADDRESS, "1.0", amount, NETWORK),
            )
        conn.commit()

    assert m._get_stats_summary(NETWORK)["total_wei"] == 10**18
