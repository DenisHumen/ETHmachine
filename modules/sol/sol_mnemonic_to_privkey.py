import binascii
import csv
from itertools import cycle
from colorama import Fore, Style
import sys
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
from solders.keypair import Keypair
from bip_utils import Bip39MnemonicValidator
import base58

def mnemonic_to_private_key(mnemonic):
    """
    Convert a mnemonic phrase to a Solana private key.
    Supports 12-word mnemonics.
    """
    # Проверка валидности мнемоники
    if not Bip39MnemonicValidator().IsValid(mnemonic):
        raise ValueError("Invalid mnemonic phrase. Ensure it has 12 words and is valid.")

    # Генерация seed из мнемоники
    seed_bytes = Bip39SeedGenerator(mnemonic).Generate()

    # Получаем ключи по BIP44 для Solana
    bip44_mst_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
    bip44_acc_ctx = bip44_mst_ctx.Purpose().Coin().Account(0)
    bip44_chg_ctx = bip44_acc_ctx.Change(Bip44Changes.CHAIN_EXT)

    # Получаем приватный и публичный ключи
    priv_key = bip44_chg_ctx.PrivateKey().Raw().ToBytes()
    pub_key = bip44_chg_ctx.PublicKey().RawCompressed().ToBytes()[1:]  # Убираем байт сжатия

    if len(priv_key) != 32 or len(pub_key) != 32:
        raise ValueError("Invalid key lengths")

    # Собираем 64-байтовый ключ
    full_keypair_bytes = priv_key + pub_key

    # Создаем Keypair
    keypair = Keypair.from_bytes(full_keypair_bytes)

    # Возвращаем ключ в Base58 и публичный ключ
    return base58.b58encode(full_keypair_bytes).decode(), str(keypair.pubkey())


def sol_process_mnemonics(input_path="data/mnemonic.txt", output_path="result/result.csv"):
    # Чтение мнемоник
    with open(input_path, "r", encoding="utf-8") as f:
        mnemonics = [line.strip() for line in f if line.strip()]

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
                priv_key, pub_key = mnemonic_to_private_key(mnemonic)
                # Публичный ключ уже строка, используем напрямую
                address = pub_key
                writer.writerow([mnemonic, priv_key, address])
                results.append((mnemonic, priv_key, address))
            except Exception as e:
                print(f"\n{Fore.RED}Ошибка для мнемоники {mnemonic[:16]}...: {e}{Style.RESET_ALL}", file=sys.stderr)
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
        for i, (mnemonic, priv_key_b58, address) in enumerate(rows):
            mark = ""
            try:
                # Проверка по мнемонике
                check_priv_b58, check_pub = mnemonic_to_private_key(mnemonic)
                check_addr_mnemonic = check_pub

                # Преобразуем приватный ключ из Base58 обратно в байты
                priv_key_bytes = base58.b58decode(priv_key_b58)
                keypair = Keypair.from_bytes(priv_key_bytes)
                check_addr_priv = str(keypair.pubkey())

                # Сравниваем адреса
                if check_addr_mnemonic != address or check_addr_priv != address:
                    mark = " ⚠️⚠️⚠️"
            except Exception as e:
                mark = " ⚠️⚠️⚠️"
            verified_results.append((mnemonic, priv_key_b58, address, mark))
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

# Пример вызова:
# process_mnemonics()