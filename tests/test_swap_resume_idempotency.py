"""Регрессии возобновления мостовых задач (swap_all_* и zkSync Lite swap).

Ловим сценарий, в котором пользователь терял деньги из отчёта:
задача пережила Ctrl-C уже ПОСЛЕ отправки перевода в мост, следующий запуск
видел нулевой on-chain баланс и помечал задачу терминальным ``skipped`` —
средства в пути становились невидимыми, а на пополненном кошельке уходил
второй перевод.

Плюс проверяем, что планировщик zkSync Lite уважает выбранный профиль данных,
и что БД модуля открываются в WAL (иначе веб-дашборд не может открыть их
read-only во время работы модуля).

Сеть и реальные БД не используются: RPC/HTTP-функции подменены заглушками,
файлы пишутся во временный каталог.
"""

from __future__ import annotations

import sqlite3

import pytest


def _boom(*args, **kwargs):
    """Заглушка для вызовов, которых при возобновлении быть не должно."""
    raise AssertionError("повторный сетевой вызов при возобновлении задачи")


class _Recorder:
    """Собирает вызовы db.update_task, чтобы проверить итоговый статус."""

    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.attempts: list[int] = []

    def update_task(self, task_id, **fields):
        self.updates.append(fields)

    def increment_attempts(self, task_id):
        self.attempts.append(task_id)

    def statuses(self) -> list[str]:
        return [u["status"] for u in self.updates if "status" in u]


# ────────── swap_all zkSync Era → Base (Rhino.fi) ──────────

def test_zksync_era_resume_does_not_skip_inflight_deposit(monkeypatch):
    """Депозит уже отправлен → ждём прибытия, а не помечаем skipped."""
    from modules.eth.swap_all_zksync_era_to_base import database as db, executor as ex

    rec = _Recorder()
    monkeypatch.setattr(db, "update_task", rec.update_task)
    monkeypatch.setattr(db, "increment_attempts", rec.increment_attempts)
    monkeypatch.setattr(ex, "log_wallet_task", lambda *a, **k: None)
    # Ни баланс, ни quote при возобновлении запрашивать нельзя.
    monkeypatch.setattr(ex, "_get_token_balance", _boom)
    monkeypatch.setattr(ex, "_send_deposit_with_id", _boom)

    inst = ex.SwapAllExecutor.__new__(ex.SwapAllExecutor)
    awaited: list[tuple] = []
    monkeypatch.setattr(inst, "_await_arrival",
                        lambda *a, **k: awaited.append(a))

    task = {
        "id": 7, "token": "USDC", "wallet_address": "0xabc",
        "contract": "0xcontract", "decimals": 6,
        "swap_id": "quote123", "src_tx_hash": "0xdeadbeefcafebabe",
    }
    inst._run_task(task, None, None, None, None, {})

    assert awaited, "ожидание прибытия по существующему quoteId не запущено"
    assert awaited[0][1] == "quote123"
    assert db.STATUS_SKIPPED not in rec.statuses(), \
        "задача с отправленным депозитом помечена терминальным skipped"


def test_zksync_era_resume_without_quote_id_is_not_resent(monkeypatch):
    """Есть tx, но нет quoteId — повторно не отправляем, зовём на ручную проверку."""
    from modules.eth.swap_all_zksync_era_to_base import database as db, executor as ex

    rec = _Recorder()
    monkeypatch.setattr(db, "update_task", rec.update_task)
    monkeypatch.setattr(db, "increment_attempts", rec.increment_attempts)
    monkeypatch.setattr(ex, "log_wallet_task", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_get_token_balance", _boom)
    monkeypatch.setattr(ex, "_send_deposit_with_id", _boom)

    inst = ex.SwapAllExecutor.__new__(ex.SwapAllExecutor)
    monkeypatch.setattr(inst, "_await_arrival", _boom)

    task = {
        "id": 8, "token": "USDT", "wallet_address": "0xabc",
        "contract": "0xcontract", "decimals": 6,
        "swap_id": "", "src_tx_hash": "0xfeed",
    }
    inst._run_task(task, None, None, None, None, {})

    assert rec.statuses() == [db.STATUS_FAILED]


# ────────── swap_all Polygon zkEVM → Base (Layerswap) ──────────

def test_polygon_zkevm_resume_does_not_skip_inflight_transfer(monkeypatch):
    """Перевод на deposit_address уже сделан → возобновляем ожидание."""
    from modules.eth.swap_all_polygon_zkevm_to_base import database as db, executor as ex

    rec = _Recorder()
    monkeypatch.setattr(db, "update_task", rec.update_task)
    monkeypatch.setattr(db, "increment_attempts", rec.increment_attempts)
    monkeypatch.setattr(ex, "log_wallet_task", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_get_token_balance", _boom)
    monkeypatch.setattr(ex, "_send_erc20", _boom)
    monkeypatch.setattr(ex, "_send_native_drain", _boom)

    inst = ex.SwapAllExecutor.__new__(ex.SwapAllExecutor)
    awaited: list[tuple] = []
    monkeypatch.setattr(inst, "_await_arrival",
                        lambda *a, **k: awaited.append(a))

    task = {
        "id": 3, "token": "ETH", "wallet_address": "0xabc",
        "contract": "", "decimals": 18,
        "swap_id": "swap-42", "src_tx_hash": "0x0123456789abcdef",
    }
    inst._run_task(task, None, None, None, None, {})

    assert awaited, "ожидание прибытия по существующему swap_id не запущено"
    assert awaited[0][1] == "swap-42"
    assert db.STATUS_SKIPPED not in rec.statuses()


def test_polygon_zkevm_await_arrival_exists():
    """Хелпер обязан существовать: на него ссылается ветка возобновления."""
    from modules.eth.swap_all_polygon_zkevm_to_base import executor as ex

    assert callable(getattr(ex.SwapAllExecutor, "_await_arrival", None))


# ────────── zkSync Lite → Era (Layerswap) ──────────

def test_zksync_lite_resume_does_not_skip_inflight_lite_tx(monkeypatch):
    """Lite-перевод уже отправлен → ждём прибытия, баланс не перечитываем."""
    from modules.zksync_lite.swap import executor as ex, swap_database as swap_db

    rec = _Recorder()
    monkeypatch.setattr(swap_db, "update_task", rec.update_task)
    monkeypatch.setattr(swap_db, "increment_attempts", rec.increment_attempts)

    inst = ex.SwapExecutor.__new__(ex.SwapExecutor)
    # account_info при возобновлении дёргать нельзя — деньги уже ушли.
    inst.signer = type("S", (), {"account_info": staticmethod(_boom)})()
    awaited: list[tuple] = []
    monkeypatch.setattr(inst, "_await_arrival",
                        lambda *a, **k: awaited.append(a))

    pool = ex.ProxyPool(None, None)
    task = {
        "id": 11, "route": "layerswap", "source_token": "USDT",
        "target_token": "USDT", "wallet_address": "0xabc", "decimals": 6,
        "layerswap_swap_id": "ls-77", "lite_tx_hash": "sync-tx-hash",
    }
    inst._run_layerswap_task(task, pool, "0x" + "11" * 32, "0xabc", "USDT",
                             "1000000", 1)

    assert awaited, "ожидание прибытия по существующему swap_id не запущено"
    assert awaited[0][3] == "ls-77"
    assert swap_db.STATUS_SKIPPED not in rec.statuses(), \
        "задача с отправленным Lite-переводом помечена skipped"


def test_zksync_lite_resume_without_swap_id_raises(monkeypatch):
    """Lite-tx без swap_id — фатальная ситуация, но без второго перевода."""
    from modules.zksync_lite.swap import executor as ex, swap_database as swap_db

    rec = _Recorder()
    monkeypatch.setattr(swap_db, "update_task", rec.update_task)
    monkeypatch.setattr(swap_db, "increment_attempts", rec.increment_attempts)

    inst = ex.SwapExecutor.__new__(ex.SwapExecutor)
    inst.signer = type("S", (), {"account_info": staticmethod(_boom)})()
    monkeypatch.setattr(inst, "_await_arrival", _boom)

    task = {
        "id": 12, "route": "layerswap", "source_token": "USDT",
        "target_token": "USDT", "wallet_address": "0xabc", "decimals": 6,
        "layerswap_swap_id": "", "lite_tx_hash": "sync-tx-hash",
    }
    with pytest.raises(RuntimeError):
        inst._run_layerswap_task(task, ex.ProxyPool(None, None),
                                 "0x" + "11" * 32, "0xabc", "USDT", "1000000", 1)


# ────────── планировщик уважает выбранный профиль данных ──────────

def test_zksync_lite_planner_reads_selected_data_profile(tmp_path, monkeypatch):
    """load_wallet_credentials обязан идти через data_manager, а не в data/data.csv."""
    from modules import data_manager
    from modules.zksync_lite.swap import planner

    profile = tmp_path / "data_second.csv"
    profile.write_text(
        "private_key,wallet_address,proxy,reserve_proxy\n"
        "0x" + "11" * 32 + ",0xAAA111,1.2.3.4:8080,5.6.7.8:9090\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(data_manager, "_selected_data_file", profile)
    monkeypatch.setattr(data_manager, "_loaded_rows", [])
    monkeypatch.setattr(data_manager, "_loaded_file", None)

    creds = planner.load_wallet_credentials()

    assert "0xaaa111" in creds, "профиль пользователя проигнорирован"
    assert creds["0xaaa111"]["private_key"] == "0x" + "11" * 32
    assert creds["0xaaa111"]["proxy"] == "1.2.3.4:8080"
    assert creds["0xaaa111"]["reserve_proxy"] == "5.6.7.8:9090"


def test_zksync_lite_planner_derives_address_from_private_key(tmp_path, monkeypatch):
    """Пустой wallet_address — адрес выводим из приватника (старое поведение)."""
    from eth_account import Account

    from modules import data_manager
    from modules.zksync_lite.swap import planner

    priv = "0x" + "22" * 32
    profile = tmp_path / "data_derive.csv"
    profile.write_text(
        "private_key,wallet_address\n" + priv + ",\n", encoding="utf-8")
    monkeypatch.setattr(data_manager, "_selected_data_file", profile)
    monkeypatch.setattr(data_manager, "_loaded_rows", [])
    monkeypatch.setattr(data_manager, "_loaded_file", None)

    creds = planner.load_wallet_credentials()

    assert Account.from_key(priv).address.lower() in creds


# ────────── WAL ──────────

def _journal_mode(db_path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    finally:
        conn.close()


def test_zksync_lite_balance_db_uses_wal(tmp_path, monkeypatch):
    """Дашборд открывает файл read-only — rollback-journal этого не позволяет."""
    from modules.zksync_lite import database as bal_db

    monkeypatch.setattr(bal_db, "DB_DIR", tmp_path / "db")
    monkeypatch.setattr(bal_db, "DB_FILE", tmp_path / "db" / "zksync_lite_balance.db")
    bal_db.init_database()

    assert _journal_mode(bal_db.DB_FILE) == "wal"


def test_dai_withdraw_db_uses_wal(tmp_path, monkeypatch):
    """Тот же контракт для БД DAI-withdraw."""
    from modules.zksync_lite.dai_withdraw import database as dai_db

    monkeypatch.setattr(dai_db, "DB_FILE", tmp_path / "db" / "dai_withdraw.db")
    dai_db.init_database()

    assert _journal_mode(dai_db.DB_FILE) == "wal"
