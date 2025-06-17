import csv
import re
import sys
from itertools import cycle
from colorama import Fore
from bip_utils import (
    Bip39MnemonicGenerator,
    Bip39SeedGenerator,
    Bip44,
    Bip44Coins,
    Bip44Changes
)
from solders.keypair import Keypair
import base58
from config.config import (
    NICE_ADDRESS_WORDS, REPEATED_CHAR_COUNT, NICE_ADDRESS_WORDS_enable,
    REPEATED_CHAR_COUNT_enable, display_the_address_search_process
)

def mnemonic_to_private_key(mnemonic):
    """
    Convert a mnemonic phrase to a Solana private key.
    """
    # ...existing code from sol_wallet_generator.py...
    seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
    bip44_mst_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
    bip44_acc_ctx = bip44_mst_ctx.Purpose().Coin().Account(0)
    bip44_chg_ctx = bip44_acc_ctx.Change(Bip44Changes.CHAIN_EXT)
    priv_key = bip44_chg_ctx.PrivateKey().Raw().ToBytes()
    pub_key = bip44_chg_ctx.PublicKey().RawCompressed().ToBytes()[1:]
    full_keypair_bytes = priv_key + pub_key
    keypair = Keypair.from_bytes(full_keypair_bytes)
    return base58.b58encode(full_keypair_bytes).decode(), str(keypair.pubkey())

def is_nice_address(address):
    """
    Проверяет, является ли адрес "красивым".
    Критерии:
    - Адрес содержит слово из массива `NICE_ADDRESS_WORDS`.
    - Адрес содержит 7 или более одинаковых символов подряд.
    """
    address = address.lower()

    if display_the_address_search_process:
        print(Fore.YELLOW + f"Checking address: {address}")

    # Проверка на наличие слов из NICE_ADDRESS_WORDS
    if NICE_ADDRESS_WORDS_enable and any(word in address for word in NICE_ADDRESS_WORDS):
        return True

    # Проверка на повторяющиеся символы
    if REPEATED_CHAR_COUNT_enable and re.search(r'(.)\1{' + str(REPEATED_CHAR_COUNT - 1) + r',}', address):
        return True

    return False

def sol_generate_nice_wallets(num_wallets):
    """
    Генерирует только "красивые" Solana-кошельки и сохраняет их в CSV-файл.
    """
    spinner_cycle = cycle(["|", "/", "-", "\\"])  # Spinner animation
    bar_length = 30  # Length of the progress bar

    # Clear the file and write the header
    with open('result/result.csv', mode='w', newline='', encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["mnemonic", "wallet_address", "private_key"])  # Add header

    completed_wallets = 0
    with open('result/result.csv', mode='a', newline='', encoding="utf-8") as file:
        writer = csv.writer(file)
        while completed_wallets < num_wallets:
            try:
                # Генерация мнемоники
                mnemonic = Bip39MnemonicGenerator().FromWordsNumber(12)
                priv_key, pub_key = mnemonic_to_private_key(mnemonic)

                if is_nice_address(pub_key):
                    writer.writerow([mnemonic, pub_key, priv_key])
                    completed_wallets += 1

                    # Update progress bar
                    progress = int((completed_wallets / num_wallets) * bar_length)
                    bar = "█" * progress + "░" * (bar_length - progress)
                    spinner_frame = next(spinner_cycle)
                    print(
                        f"\r[GEN] [{bar}] {completed_wallets}/{num_wallets} | {spinner_frame} Generating nice wallets...",
                        end="",
                        flush=True,
                    )
            except Exception as e:
                print(f"\n❌ Error generating wallet: {str(e)}", file=sys.stderr)
    print()  # Move to the next line after the progress bar is complete
