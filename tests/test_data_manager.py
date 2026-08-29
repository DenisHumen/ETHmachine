"""Тесты кэша и перемешивания в ``modules.data_manager``.

Два инварианта, которые здесь закреплены, стоят пользователю денег:

1. Колонки одной строки data.csv должны оставаться склеенными. Если
   ``get_private_keys()`` и ``get_proxies()`` перемешиваются независимо,
   кошелёк N уходит в сеть через прокси кошелька M — это связывание аккаунтов
   и бан у провайдеров с привязкой IP.
2. Кэш обязан замечать правку data.csv. Процесс живёт в бесконечном цикле
   главного меню, и «дописал строку → запустил модуль ещё раз» — обычный
   сценарий, а не экзотика.

Сеть и пользовательские data/ здесь не трогаются: всё во временном каталоге.
"""

from __future__ import annotations

import csv

import pytest

import modules.data_manager as dm


HEADERS = dm.HEADERS


def _write_csv(path, count, start=1):
    """Пишет CSV, где каждая колонка строки помечена её номером.

    Номер зашит в private_key/proxy/wallet_address, поэтому по результату
    видно, склеены ли колонки одной строки.
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for i in range(start, start + count):
            row = {h: "" for h in HEADERS}
            row["name"] = f"acc{i:02d}"
            row["private_key"] = f"pk{i:02d}"
            row["proxy"] = f"proxy{i:02d}"
            row["wallet_address"] = f"wallet{i:02d}"
            writer.writerow(row)


@pytest.fixture()
def data_file(tmp_path, monkeypatch):
    """Чистый data_manager, привязанный к временному каталогу."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "data.csv"

    monkeypatch.setattr(dm, "DATA_DIR", data_dir)
    monkeypatch.setattr(dm, "DEFAULT_DATA_FILE", path)
    monkeypatch.setattr(dm, "_selected_data_file", path)
    # Миграция сканирует DATA_DIR целиком — тестам она не нужна.
    monkeypatch.setattr(dm, "_migrated_once", True)
    # Сбрасываем кэш процесса, иначе тесты потянут данные друг друга.
    monkeypatch.setattr(dm, "_loaded_rows", [])
    monkeypatch.setattr(dm, "_loaded_file", None)
    monkeypatch.setattr(dm, "_loaded_stamp", None)
    monkeypatch.setattr(dm, "_shuffled_rows", None)
    return path


def _index_of(values, prefix):
    """['pk03', 'pk01'] + 'pk' -> ['03', '01'] — номера строк в порядке выдачи."""
    return [v[len(prefix):] for v in values]


def test_shuffle_keeps_row_columns_aligned(data_file, monkeypatch):
    """При перемешивании private_key/proxy/wallet_address идут из одной строки."""
    _write_csv(data_file, 8)
    monkeypatch.setattr(dm, "_SHUFLE_ACCOUNTS", True)

    keys = _index_of(dm.get_private_keys(), "pk")
    proxies = _index_of(dm.get_proxies(), "proxy")
    wallets = _index_of(dm.get_wallet_addresses(), "wallet")

    assert keys == proxies == wallets, (
        f"колонки разъехались: keys={keys} proxies={proxies} wallets={wallets}"
    )
    assert sorted(keys) == [f"{i:02d}" for i in range(1, 9)]


def test_shuffle_order_is_stable_within_cache(data_file, monkeypatch):
    """Порядок перемешивания считается один раз на кэш, а не на каждый вызов."""
    _write_csv(data_file, 8)
    monkeypatch.setattr(dm, "_SHUFLE_ACCOUNTS", True)

    first = dm.get_private_keys()
    second = dm.get_private_keys()
    third = [r["private_key"] for r in dm.load_data()]

    assert first == second == third


def test_shuffle_actually_reorders(data_file, monkeypatch):
    """Перемешивание не выродилось в «вернуть файловый порядок»."""
    _write_csv(data_file, 30)
    monkeypatch.setattr(dm, "_SHUFLE_ACCOUNTS", True)

    file_order = [f"pk{i:02d}" for i in range(1, 31)]
    assert dm.get_private_keys() != file_order


def test_no_shuffle_returns_file_order(data_file, monkeypatch):
    """SHUFLE_ACCOUNTS=False — строки строго в порядке файла."""
    _write_csv(data_file, 5)
    monkeypatch.setattr(dm, "_SHUFLE_ACCOUNTS", False)

    assert dm.get_private_keys() == [f"pk{i:02d}" for i in range(1, 6)]


def test_caller_cannot_reorder_the_cache(data_file, monkeypatch):
    """Вызывающий код перемешивает свою копию, а не кэш менеджера."""
    _write_csv(data_file, 8)
    monkeypatch.setattr(dm, "_SHUFLE_ACCOUNTS", True)

    rows = dm.load_data()
    expected = [r["private_key"] for r in rows]
    rows.reverse()

    assert [r["private_key"] for r in dm.load_data()] == expected


def test_cache_reloads_after_file_edited(data_file, monkeypatch):
    """Дописанные в data.csv строки видны без перезапуска процесса."""
    monkeypatch.setattr(dm, "_SHUFLE_ACCOUNTS", False)
    _write_csv(data_file, 2)
    assert len(dm.load_data()) == 2

    # Тот же путь, другое содержимое — кэш обязан протухнуть по mtime/размеру.
    _write_csv(data_file, 5)
    # mtime на Windows может совпасть с точностью до тика, поэтому подстрахуемся
    # ощутимым сдвигом времени модификации файла.
    import os
    st = data_file.stat()
    os.utime(data_file, (st.st_atime, st.st_mtime + 10))

    rows = dm.load_data()
    assert len(rows) == 5
    assert rows[-1]["private_key"] == "pk05"


def test_shuffled_order_recomputed_after_reload(data_file, monkeypatch):
    """После перезагрузки данных перемешанный порядок пересобирается под новый размер."""
    monkeypatch.setattr(dm, "_SHUFLE_ACCOUNTS", True)
    _write_csv(data_file, 4)
    assert len(dm.get_private_keys()) == 4

    _write_csv(data_file, 9)
    rows = dm.reload_data()
    assert len(rows) == 9

    keys = _index_of(dm.get_private_keys(), "pk")
    proxies = _index_of(dm.get_proxies(), "proxy")
    assert keys == proxies
    assert sorted(keys) == [f"{i:02d}" for i in range(1, 10)]
