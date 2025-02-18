import os
import sys
import platform

if platform.system() == 'Windows':
    os.system('chcp 65001')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
else:
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

import json
import requests
from web3 import Web3
import time
import csv
import inquirer
from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium
from colorama import Fore, Style, init
from tqdm import tqdm

# импорт функций из модулей
from modules.get_wallet_balance_base import get_wallet_balance_base
from modules.get_wallet_balance_arbitrum import get_wallet_balance_arbitrum
from modules.get_wallet_balance_eth import get_wallet_balance_eth
from modules.get_wallet_balance_optimism import get_wallet_balance_optimism
from modules.get_wallet_balance_sepolia import get_wallet_balance_sepolia
from modules.get_wallet_balance_soneium import get_wallet_balance_soneium
from modules.get_gas_price import get_gas_price
from modules.sum_balances import sum_balances

init(autoreset=True)


def main_menu():
    while True:
        questions = [
            inquirer.List('action',
                          message="What do you want to do?",
                          choices=['💲 Check Balances', '💰 Sum Balances', '⛽ Check Gas Price', '❌ Exit'],
                         ),
        ]
        answers = inquirer.prompt(questions)
        action = answers['action']

        if action == '❌ Exit':
            break
        elif action == '💰 Sum Balances':
            sum_balances('result.csv')
        elif action == '💲 Check Balances':
            check_balances_menu()
        elif action == '⛽ Check Gas Price':
            check_gas_price_menu()

def check_balances_menu():
    while True:
        questions = [
            inquirer.List('network',
                          message="Which network do you want to check?",
                          choices=['🚀 Sepolia', '🚀 Ethereum Mainnet', '🚀 Base', '🚀 Arbitrum One', '🚀 Optimism', '🚀 Soneium', '🔙 Back'],
                         ),
        ]
        answers = inquirer.prompt(questions)
        network = answers['network']

        if network == '🔙 Back':
            return

        if network == '🚀 Sepolia':
            get_balance = lambda addr: get_wallet_balance_sepolia(addr, sepolia)
        elif network == '🚀 Ethereum Mainnet':
            get_balance = lambda addr: get_wallet_balance_eth(addr, L1)
        elif network == '🚀 Base':
            get_balance = lambda addr: get_wallet_balance_base(addr, base)
        elif network == '🚀 Arbitrum One':
            get_balance = lambda addr: get_wallet_balance_arbitrum(addr, arbitrum)
        elif network == '🚀 Optimism':
            get_balance = lambda addr: get_wallet_balance_optimism(addr, optimism)
        elif network == '🚀 Soneium':
            get_balance = lambda addr: get_wallet_balance_soneium(addr, soneium)

        with open('walletss.txt', 'r', encoding='utf-8') as file:
            wallet_addresses = file.readlines()

        with open('result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'balance', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for address in tqdm(wallet_addresses, desc="Checking balances", unit="wallet"):
                address = address.strip()
                balance = get_balance(address)
                time.sleep(1)
                writer.writerow({'address': address, 'balance': balance, 'network': network})

        print(Fore.GREEN + f"\n\n\nBalances checked and saved in result.csv for {network} network\n")

def check_gas_price_menu():
    while True:
        questions = [
            inquirer.List('network',
                          message="Which network's gas price do you want to check?",
                          choices=['🚀 Sepolia', '🚀 Ethereum Mainnet', '🚀 Base', '🚀 Arbitrum One', '🚀 Optimism', '🚀 Soneium', '🔙 Back'],
                         ),
        ]
        answers = inquirer.prompt(questions)
        network = answers['network']

        if network == '🔙 Back':
            return

        if network == '🚀 Sepolia':
            gas_price = get_gas_price(sepolia)
        elif network == '🚀 Ethereum Mainnet':
            gas_price = get_gas_price(L1)
        elif network == '🚀 Base':
            gas_price = get_gas_price(base)
        elif network == '🚀 Arbitrum One':
            gas_price = get_gas_price(arbitrum)
        elif network == '🚀 Optimism':
            gas_price = get_gas_price(optimism)
        elif network == '🚀 Soneium':
            gas_price = get_gas_price(soneium)

        if gas_price is not None:
            print(Fore.GREEN + f"\n\n\n⛽ Current gas price on {network}: {gas_price} Gwei\n")
        else:
            print(Fore.RED + f"\n\n\n❌ Failed to retrieve gas price for {network}\n")

if __name__ == "__main__":
    main_menu()