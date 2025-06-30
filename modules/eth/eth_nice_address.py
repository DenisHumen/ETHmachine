from mnemonic import Mnemonic
import binascii
import hashlib
import hmac
import struct
from ecdsa.curves import SECP256k1
from eth_utils import to_checksum_address, keccak as eth_utils_keccak
import csv
from itertools import cycle
from config.config import (
    NICE_ADDRESS_WORDS_ETH, REPEATED_CHAR_COUNT, NICE_ADDRESS_WORDS_enable,
    REPEATED_CHAR_COUNT_enable, display_the_address_search_process
)
import re
import sys
from colorama import Fore 
from eth_account import Account  
import random
import time

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

def is_nice_address(address, attempt=None):
    address = address.lower().replace('0x', '')

    if display_the_address_search_process:
        attempt_info = f" (Attempt: {attempt})" if attempt is not None else ""
        print(Fore.YELLOW + f"Checking address: {address}{attempt_info}")

    match_word = NICE_ADDRESS_WORDS_enable and any(word in address for word in NICE_ADDRESS_WORDS_ETH)

    match_repeated = REPEATED_CHAR_COUNT_enable and re.search(rf'([a-f0-9])\1{{{REPEATED_CHAR_COUNT - 1}}}', address)

    return match_word or match_repeated

def eth_generate_nice_wallets(num_wallets):
    mnemo = Mnemonic("english")
    spinner_cycle = cycle(["|", "/", "-", "\\"])  
    bar_length = 30  


    with open('result/result.csv', mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["mnemonic", "wallet_address", "private_key"]) 

    completed_wallets = 0
    attempt = 0
    with open('result/result.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        while completed_wallets < num_wallets:
            attempt += 1
            try:
                mnemonic = mnemo.generate()
                private_key = mnemonic_to_private_key(mnemonic, str_derivation_path=f'{ETH_DERIVATION_PATH}/0')
                public_key = PublicKey(private_key)
                address = public_key.address()
                priv_hex = binascii.hexlify(bytes(private_key)).decode("utf-8")

                if is_nice_address(address, attempt=attempt):
                    writer.writerow([mnemonic, address, priv_hex]) 
                    completed_wallets += 1

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
    print() 

def find_nice_addresses(search_word=None):
    words_to_search = [search_word] if search_word else NICE_ADDRESS_WORDS_ETH

    print(Fore.GREEN + "Начинаем поиск адресов...")

    attempts = 0
    found_addresses = []

    while True:
        attempts += 1
        account = Account.create(random.randint(0, 2**256 - 1))
        address = account.address.lower()

        match_word = NICE_ADDRESS_WORDS_enable and any(word in address for word in words_to_search)
        match_repeated = REPEATED_CHAR_COUNT_enable and re.search(rf'([a-f0-9])\1{{{REPEATED_CHAR_COUNT - 1}}}', address)

        if match_word or match_repeated:
            found_addresses.append({
                "address": account.address,
                "private_key": account.key.hex()
            })
            print(Fore.CYAN + f"Найден адрес: {account.address} | Приватный ключ: {account.key.hex()}")

