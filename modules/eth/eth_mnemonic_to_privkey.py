import binascii
import csv
from itertools import cycle
import sys
from pathlib import Path
from .eth_wallet_generator import (
    mnemonic_to_private_key,
    PublicKey,
    ETH_DERIVATION_PATH,
)

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from modules.simple_logger import logger

def process_mnemonics(input_path=None, output_path="result/result.csv"):
    # Чтение мнемоник из data.csv
    from modules.data_manager import get_mnemonics
    mnemonics = get_mnemonics()

    spinner_cycle = cycle(["|", "/", "-", "\\"])
    bar_length = 30
    total = len(mnemonics)
    results = []

    # Преобразование мнемоник в приватники и адреса
    with open(output_path, "w", newline='', encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["mnemonic", "priv_key", "address"])
        for i, mnemonic in enumerate(mnemonics):
            try:
                priv_key = mnemonic_to_private_key(mnemonic, f"{ETH_DERIVATION_PATH}/0")
                priv_hex = binascii.hexlify(priv_key).decode("utf-8")
                address = PublicKey(priv_key).address()
                writer.writerow([mnemonic, priv_hex, address])
                results.append((mnemonic, priv_hex, address))
            except Exception as e:
                logger.error(f"Ошибка для мнемоники {mnemonic[:16]}...: {e}")
            # Прогресс-бар
            progress = int(((i + 1) / total) * bar_length)
            bar = "█" * progress + "░" * (bar_length - progress)
            spinner_frame = next(spinner_cycle)
            print(
                f"\r[GEN] [{bar}] {i+1}/{total} | {spinner_frame} Mnemonics to keys...",
                end="",
                flush=True,
            )
    print()

    # Верификация результата
    spinner_cycle_check = cycle(["|", "/", "-", "\\"])
    bar_length_check = 30
    checked = 0
    verified_results = []
    with open(output_path, "r", encoding="utf-8") as file:
        reader = csv.reader(file)
        next(reader)  # skip header
        rows = list(reader)
        total_rows = len(rows)
        for i, (mnemonic, priv_hex, address) in enumerate(rows):
            mark = ""
            try:
                # Проверка по мнемонике
                check_priv = mnemonic_to_private_key(mnemonic, f"{ETH_DERIVATION_PATH}/0")
                check_addr_mnemonic = PublicKey(check_priv).address()
                # Проверка по приватнику
                check_addr_priv = PublicKey(binascii.unhexlify(priv_hex)).address()
                if check_addr_mnemonic != address or check_addr_priv != address:
                    mark = " ⚠️⚠️⚠️"
                    logger.warning(f"Несоответствие для мнемоники {mnemonic[:16]}...")
            except Exception as e:
                mark = " ⚠️⚠️⚠️"
                logger.error(f"Ошибка верификации для мнемоники {mnemonic[:16]}...: {e}")
            verified_results.append((mnemonic, priv_hex, address, mark))
            checked += 1
            progress = int((checked / total_rows) * bar_length_check)
            bar = "█" * progress + "░" * (bar_length_check - progress)
            spinner_frame = next(spinner_cycle_check)
            print(
                f"\r[CHK] [{bar}] {checked}/{total_rows} | {spinner_frame} Verifying...",
                end="",
                flush=True,
            )
    print()

    # Перезапись файла с отметками
    with open(output_path, "w", newline='', encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["mnemonic", "priv_key", "address", "check"])
        for row in verified_results:
            writer.writerow(row)

    logger.success(f"Обработано {total} мнемоник, результат сохранен в {output_path}")

# Пример вызова:
# process_mnemonics()
