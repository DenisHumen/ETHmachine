import csv
from datetime import datetime
from itertools import cycle
from pathlib import Path
import sys
from bip_utils import Bip39MnemonicGenerator, Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
from solders.keypair import Keypair
import base58

from modules.simple_logger import logger

# result/result.csv — общая свалка: чекеры балансов и конвертеры открывают её
# с mode='w' и затирают всё, что там лежало. Поэтому свежие мнемоники и
# приватники дублируем в отдельный файл запуска, который больше никто не трогает.
RESULT_CSV = Path('result') / 'result.csv'
WALLETS_DIR = Path('result') / 'wallets'

def new_wallets_file(prefix):
    """
    Уникальный путь под ключи одного запуска генератора.

    Штамп времени в имени: потерянную мнемонику восстановить нечем,
    поэтому новый запуск не имеет права затирать результат предыдущего.
    """
    WALLETS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = WALLETS_DIR / f"{prefix}_{stamp}.csv"
    attempt = 1
    while path.exists():
        attempt += 1
        path = WALLETS_DIR / f"{prefix}_{stamp}_{attempt}.csv"
    return path

def mnemonic_to_private_key(mnemonic):
    """
    Convert a mnemonic phrase to a Solana private key.
    """
    # Генерация seed из мнемоники
    seed_bytes = Bip39SeedGenerator(mnemonic).Generate()

    # Получаем ключи по BIP44 для Solana
    bip44_mst_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
    bip44_acc_ctx = bip44_mst_ctx.Purpose().Coin().Account(0)
    bip44_chg_ctx = bip44_acc_ctx.Change(Bip44Changes.CHAIN_EXT)

    # Получаем приватный и публичный ключи
    priv_key = bip44_chg_ctx.PrivateKey().Raw().ToBytes()
    pub_key = bip44_chg_ctx.PublicKey().RawCompressed().ToBytes()[1:]  # Убираем байт сжатия

    # Собираем 64-байтовый ключ
    full_keypair_bytes = priv_key + pub_key

    # Создаем Keypair
    keypair = Keypair.from_bytes(full_keypair_bytes)

    # Возвращаем ключ в Base58 и публичный ключ
    return base58.b58encode(full_keypair_bytes).decode(), str(keypair.pubkey())

def sol_generate_wallets(num_wallets):
    """
    Generate Solana wallets and save them to a CSV file with a progress bar.
    Then verify that mnemonic/private key import gives the same address.

    Возвращает путь к файлу запуска с ключами (result/wallets/...).
    """
    spinner_cycle = cycle(["|", "/", "-", "\\"])  # Spinner animation
    bar_length = 30  # Length of the progress bar

    wallets_path = new_wallets_file('sol_wallets')

    # Clear the file and write the header
    for path in (RESULT_CSV, wallets_path):
        with open(path, mode='w', newline='', encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["mnemonic", "wallet_address", "private_key"])  # Add header

    # Stage 1: Generation
    completed_wallets = 0
    wallets = []
    with open(RESULT_CSV, mode='a', newline='', encoding="utf-8") as shared_file, \
         open(wallets_path, mode='a', newline='', encoding="utf-8") as wallets_file:
        writers = [csv.writer(shared_file), csv.writer(wallets_file)]
        for i in range(num_wallets):
            try:
                # Генерация мнемоники
                mnemonic = Bip39MnemonicGenerator().FromWordsNumber(12)
                priv_key, pub_key = mnemonic_to_private_key(mnemonic)
                address = pub_key
                # Порядок колонок строго по заголовку mnemonic,wallet_address,private_key:
                # раньше адрес и приватник шли местами наоборот, и до финальной
                # перезаписи файл читался неверно (а при обрыве — оставался таким).
                for writer in writers:
                    writer.writerow([mnemonic, address, priv_key])
                wallets.append((mnemonic, address, priv_key))

                # Update progress bar
                completed_wallets += 1
                progress = int((completed_wallets / num_wallets) * bar_length)
                bar = "█" * progress + "░" * (bar_length - progress)
                spinner_frame = next(spinner_cycle)
                print(
                    f"\r[GEN] [{bar}] {completed_wallets}/{num_wallets} | {spinner_frame} Generating wallets...",
                    end="",
                    flush=True,
                )
            except Exception as e:
                print(f"\n❌ Error generating wallet {i + 1}: {str(e)}", file=sys.stderr)
    print()  # Move to the next line after the progress bar is complete

    # Stage 2: Verification
    completed_checks = 0
    spinner_cycle_check = cycle(["|", "/", "-", "\\"])
    bar_length_check = 30
    results = []
    for i, (mnemonic, orig_address, priv_key) in enumerate(wallets):
        # Проверка по мнемонике
        check_priv, check_addr_mnemonic = mnemonic_to_private_key(mnemonic)
        # Проверка по приватнику
        priv_key_bytes = base58.b58decode(priv_key)
        keypair = Keypair.from_bytes(priv_key_bytes)
        check_addr_priv = str(keypair.pubkey())
        # Сравнение
        mark = ""
        if check_addr_mnemonic != orig_address or check_addr_priv != orig_address:
            mark = " ⚠️⚠️⚠️"
        results.append((mnemonic, orig_address, priv_key, mark))

        # Update verification progress bar
        completed_checks += 1
        progress = int((completed_checks / num_wallets) * bar_length_check)
        bar = "█" * progress + "░" * (bar_length_check - progress)
        spinner_frame = next(spinner_cycle_check)
        print(
            f"\r[CHK] [{bar}] {completed_checks}/{num_wallets} | {spinner_frame} Verifying wallets...",
            end="",
            flush=True,
        )
    print()  # Move to the next line after the progress bar is complete

    # Перезаписываем файлы с отметками
    for path in (RESULT_CSV, wallets_path):
        with open(path, mode='w', newline='', encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["mnemonic", "wallet_address", "private_key", "check"])  # Исправлено: порядок заголовков
            for row in results:
                writer.writerow(row)

    logger.success(f"Ключи сохранены в {wallets_path} (копия в {RESULT_CSV})")
    return wallets_path

# Пример вызова:
# sol_generate_wallets(100)
