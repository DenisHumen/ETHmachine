"""Сгенерированные ключи не должны теряться.

result/result.csv — общая свалка: чекеры балансов, сборщики и конвертеры
открывают её с mode='w'. Раньше туда же писали генераторы, и мнемоники
пропадали от одного запуска проверки баланса. Теперь каждый запуск
генератора кладёт ключи ещё и в собственный файл result/wallets/*.csv —
эти тесты стерегут именно это, сети не трогают.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest


def _read_csv(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def _only(pattern: str) -> Path:
    """Единственный файл запуска, подходящий под маску."""
    found = sorted(Path("result/wallets").glob(pattern))
    assert len(found) == 1, f"ожидали один файл по маске {pattern}, нашли {found}"
    return found[0]


def test_eth_generator_pishet_otdelnyy_fayl(tmp_project):
    """ETH-генератор возвращает путь к своему файлу и дублирует ключи в result.csv."""
    from modules.eth.eth_wallet_generator import eth_generate_wallets

    wallets_path = eth_generate_wallets(1)

    assert wallets_path.parent == Path("result/wallets")
    rows = _read_csv(wallets_path)
    assert rows[0] == ["mnemonic", "wallet_address", "private_key", "check"]
    assert len(rows) == 2
    assert rows[1][1].startswith("0x")

    # Совместимость: старый путь остаётся на месте с тем же содержимым.
    assert _read_csv(Path("result/result.csv")) == rows


def test_sol_generaciya_ne_zatiraet_eth_klyuchi(tmp_project):
    """Генерация SOL после ETH не уничтожает ETH-мнемоники (был баг с mode='w')."""
    from modules.eth.eth_wallet_generator import eth_generate_wallets
    from modules.sol.sol_wallet_generator import sol_generate_wallets

    eth_path = eth_generate_wallets(1)
    eth_rows = _read_csv(eth_path)

    sol_path = sol_generate_wallets(1)

    assert sol_path != eth_path
    # ETH-файл пережил запуск SOL-генератора без изменений.
    assert _read_csv(eth_path) == eth_rows
    # А общий result.csv действительно перезаписан — там уже SOL.
    assert _read_csv(Path("result/result.csv")) == _read_csv(sol_path)


def test_nice_generatory_pishut_otdelnye_fayly(tmp_project, monkeypatch):
    """Красивые адреса ищутся часами — их ключи тоже уходят в файл запуска."""
    from modules.eth.eth_nice_address.python import eth_nice_address as eth_nice
    from modules.sol import sol_nice_address as sol_nice

    # Критерий «красоты» зависит от конфига пользователя — тесту важен только путь.
    monkeypatch.setattr(eth_nice, "is_nice_address", lambda address, attempt=None: True)
    monkeypatch.setattr(sol_nice, "is_nice_address", lambda address, attempt=None: True)

    eth_path = eth_nice.eth_generate_nice_wallets(1)
    eth_rows = _read_csv(eth_path)
    assert eth_path == _only("eth_nice_wallets_*.csv")
    assert eth_rows[0] == ["mnemonic", "wallet_address", "private_key"]
    assert len(eth_rows) == 2

    sol_path = sol_nice.sol_generate_nice_wallets(1)
    assert sol_path == _only("sol_nice_wallets_*.csv")
    assert len(_read_csv(sol_path)) == 2

    # Ключи ETH на месте, хотя result.csv уже перезаписан солановскими.
    assert _read_csv(eth_path) == eth_rows


def test_sol_promezhutochnyy_fayl_v_poryadke_zagolovka(tmp_project, monkeypatch):
    """Обрыв на середине оставляет читаемый файл: адрес в колонке адреса.

    До исправления в промежуточные строки писали (mnemonic, private_key,
    address) под заголовком mnemonic,wallet_address,private_key.
    """
    from modules.sol import sol_wallet_generator as gen

    real_derive = gen.mnemonic_to_private_key
    calls = {"n": 0}

    def stop_after_first(mnemonic):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt  # имитируем Ctrl+C после первого кошелька
        return real_derive(mnemonic)

    monkeypatch.setattr(gen, "mnemonic_to_private_key", stop_after_first)

    with pytest.raises(KeyboardInterrupt):
        gen.sol_generate_wallets(2)

    rows = _read_csv(_only("sol_wallets_*.csv"))
    assert rows[0] == ["mnemonic", "wallet_address", "private_key"]
    assert len(rows) == 2

    mnemonic, address, priv_key = rows[1]
    _, expected_address = real_derive(mnemonic)
    assert address == expected_address
