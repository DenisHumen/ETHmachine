from mnemonic import Mnemonic
import binascii
import hashlib
import hmac
import struct
from ecdsa.curves import SECP256k1
from eth_utils import to_checksum_address, keccak as eth_utils_keccak
import csv
from datetime import datetime
from itertools import cycle
from pathlib import Path
import sys

from modules.simple_logger import logger

# result/result.csv — общая свалка: чекеры балансов и конвертеры открывают её
# с mode='w' и затирают всё, что там лежало. Поэтому свежие мнемоники и
# приватники дублируем в отдельный файл запуска, который больше никто не трогает.
RESULT_CSV = Path('result') / 'result.csv'
WALLETS_DIR = Path('result') / 'wallets'

BIP39_PBKDF2_ROUNDS = 2048
BIP39_SALT_MODIFIER = "mnemonic"
BIP32_PRIVDEV = 0x80000000
BIP32_CURVE = SECP256k1
BIP32_SEED_MODIFIER = b'Bitcoin seed'
ETH_DERIVATION_PATH = "m/44'/60'/0'/0"

class PublicKey:
    def __init__(self, private_key):
        self.point = int.from_bytes(private_key, byteorder='big') * BIP32_CURVE.generator

    def __bytes__(self):
        xstr = self.point.x().to_bytes(32, byteorder='big')
        parity = self.point.y() & 1
        return (2 + parity).to_bytes(1, byteorder='big') + xstr

    def address(self):
        x = self.point.x()
        y = self.point.y()
        s = x.to_bytes(32, 'big') + y.to_bytes(32, 'big')
        return to_checksum_address(eth_utils_keccak(s)[12:])

def mnemonic_to_bip39seed(mnemonic, passphrase):
    mnemonic = bytes(mnemonic, 'utf8')
    salt = bytes(BIP39_SALT_MODIFIER + passphrase, 'utf8')
    return hashlib.pbkdf2_hmac('sha512', mnemonic, salt, BIP39_PBKDF2_ROUNDS)

def bip39seed_to_bip32masternode(seed):
    k = seed
    h = hmac.new(BIP32_SEED_MODIFIER, seed, hashlib.sha512).digest()
    key, chain_code = h[:32], h[32:]
    return key, chain_code

def derive_bip32childkey(parent_key, parent_chain_code, i):
    assert len(parent_key) == 32
    assert len(parent_chain_code) == 32
    k = parent_chain_code
    if (i & BIP32_PRIVDEV) != 0:
        key = b'\x00' + parent_key
    else:
        key = bytes(PublicKey(parent_key))
    d = key + struct.pack('>L', i)
    while True:
        h = hmac.new(k, d, hashlib.sha512).digest()
        key, chain_code = h[:32], h[32:]
        a = int.from_bytes(key, byteorder='big')
        b = int.from_bytes(parent_key, byteorder='big')
        key = (a + b) % BIP32_CURVE.order
        if a < BIP32_CURVE.order and key != 0:
            key = key.to_bytes(32, byteorder='big')
            break
        d = b'\x01' + h[32:] + struct.pack('>L', i)
    return key, chain_code

def parse_derivation_path(str_derivation_path):
    path = []
    if str_derivation_path[0:2] != 'm/':
        raise ValueError("Can't recognize derivation path. It should look like \"m/44'/60/0'/0\".")
    for i in str_derivation_path.lstrip('m/').split('/'):
        if "'" in i:
            path.append(BIP32_PRIVDEV + int(i[:-1]))
        else:
            path.append(int(i))
    return path

def mnemonic_to_private_key(mnemonic, str_derivation_path, passphrase=""):
    derivation_path = parse_derivation_path(str_derivation_path)
    bip39seed = mnemonic_to_bip39seed(mnemonic, passphrase)
    master_private_key, master_chain_code = bip39seed_to_bip32masternode(bip39seed)
    private_key, chain_code = master_private_key, master_chain_code
    for i in derivation_path:
        private_key, chain_code = derive_bip32childkey(private_key, chain_code, i)
    return private_key

def new_wallets_file(prefix, wallets_dir=WALLETS_DIR):
    """
    Уникальный путь под ключи одного запуска генератора.

    Штамп времени в имени: потерянную мнемонику восстановить нечем,
    поэтому новый запуск не имеет права затирать результат предыдущего.
    ``wallets_dir`` нужен вызывающим, которые работают не из корня проекта
    (Rust-обёртка запускает бинарник с другим cwd и передаёт абсолютный путь).
    """
    wallets_dir = Path(wallets_dir)
    wallets_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = wallets_dir / f"{prefix}_{stamp}.csv"
    attempt = 1
    while path.exists():
        attempt += 1
        path = wallets_dir / f"{prefix}_{stamp}_{attempt}.csv"
    return path

def eth_generate_wallets(num_wallets):
    """
    Generate Ethereum wallets and save them to a CSV file with a progress bar.
    Then verify that mnemonic/private key import gives the same address.

    Возвращает путь к файлу запуска с ключами (result/wallets/...).
    """
    mnemo = Mnemonic("english")
    spinner_cycle = cycle(["|", "/", "-", "\\"])  # Spinner animation
    bar_length = 30  # Length of the progress bar

    wallets_path = new_wallets_file('eth_wallets')

    # Clear the file and write the header
    for path in (RESULT_CSV, wallets_path):
        with open(path, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["mnemonic", "wallet_address", "private_key"])  # Add header

    # Stage 1: Generation
    completed_wallets = 0
    wallets = []
    with open(RESULT_CSV, mode='a', newline='', encoding='utf-8') as shared_file, \
         open(wallets_path, mode='a', newline='', encoding='utf-8') as wallets_file:
        writers = [csv.writer(shared_file), csv.writer(wallets_file)]
        for i in range(num_wallets):
            try:
                mnemonic = mnemo.generate()
                private_key = mnemonic_to_private_key(mnemonic, str_derivation_path=f'{ETH_DERIVATION_PATH}/0')
                public_key = PublicKey(private_key)
                address = public_key.address()
                priv_hex = binascii.hexlify(bytes(private_key)).decode("utf-8")
                for writer in writers:
                    writer.writerow([mnemonic, address, priv_hex])
                wallets.append((mnemonic, address, priv_hex))

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
    for i, (mnemonic, orig_address, priv_hex) in enumerate(wallets):
        # Проверка по мнемонике
        check_priv = mnemonic_to_private_key(mnemonic, str_derivation_path=f'{ETH_DERIVATION_PATH}/0')
        check_addr_mnemonic = PublicKey(check_priv).address()
        # Проверка по приватнику
        check_addr_priv = PublicKey(binascii.unhexlify(priv_hex)).address()
        # Сравнение
        mark = ""
        if check_addr_mnemonic != orig_address or check_addr_priv != orig_address:
            mark = " ⚠️⚠️⚠️"
        results.append((mnemonic, orig_address, priv_hex, mark))

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
        with open(path, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["mnemonic", "wallet_address", "private_key", "check"])
            for row in results:
                writer.writerow(row)

    logger.success(f"Ключи сохранены в {wallets_path} (копия в {RESULT_CSV})")
    return wallets_path

#generate_wallets(10000)  # Example usage