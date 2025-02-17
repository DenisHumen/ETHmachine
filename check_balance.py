import os
import sys
import platform

# Установить кодировку консоли на UTF-8 для Windows
if platform.system() == 'Windows':
    os.system('chcp 65001')

# Установить кодировку stdout на UTF-8
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

init(autoreset=True)

def get_wallet_balance_sepolia(wallet_address, rpc_urls):
    for rpc_url in rpc_urls:
        try:
            headers = {"Content-Type": "application/json"}
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_getBalance",
                "params": [wallet_address, "latest"],
                "id": 1
            }
            response = requests.post(rpc_url, headers=headers, data=json.dumps(payload))
            result = response.json().get("result")
            if result:
                balance = int(result, 16) / 10**18  
                return balance
        except Exception as e:
            print(f"Error with RPC URL {rpc_url}: {e}")
    print("All Sepolia RPC URLs failed. Please add more proxies.")
    return None

def get_wallet_balance_eth(wallet_address, rpc_urls):
    for rpc_url in rpc_urls:
        try:
            web3 = Web3(Web3.HTTPProvider(rpc_url))
            if web3.is_connected():
                balance = web3.eth.get_balance(wallet_address)
                return round(web3.from_wei(balance, 'ether'), 5)
        except Exception as e:
            print(f"Error with RPC URL {rpc_url}: {e}")
    print("All Ethereum Mainnet RPC URLs failed. Please add more proxies.")
    return None

def get_wallet_balance_base(wallet_address, rpc_urls):
    for rpc_url in rpc_urls:
        try:
            web3 = Web3(Web3.HTTPProvider(rpc_url))
            if web3.is_connected():
                balance = web3.eth.get_balance(wallet_address)
                return round(web3.from_wei(balance, 'ether'), 5)
        except Exception as e:
            print(f"Error with RPC URL {rpc_url}: {e}")
    print("All Base RPC URLs failed. Please add more proxies.")
    return None

def get_wallet_balance_arbitrum(wallet_address, rpc_urls):
    for rpc_url in rpc_urls:
        try:
            web3 = Web3(Web3.HTTPProvider(rpc_url))
            if web3.is_connected():
                balance = web3.eth.get_balance(wallet_address)
                return round(web3.from_wei(balance, 'ether'), 5)
        except Exception as e:
            print(f"Error with RPC URL {rpc_url}: {e}")
    print("All Arbitrum One RPC URLs failed. Please add more proxies.")
    return None

def get_wallet_balance_optimism(wallet_address, rpc_urls):
    for rpc_url in rpc_urls:
        try:
            web3 = Web3(Web3.HTTPProvider(rpc_url))
            if web3.is_connected():
                balance = web3.eth.get_balance(wallet_address)
                return round(web3.from_wei(balance, 'ether'), 5)
        except Exception as e:
            print(f"Error with RPC URL {rpc_url}: {e}")
    print("All Optimism RPC URLs failed. Please add more proxies.")
    return None

def get_wallet_balance_soneium(wallet_address, rpc_urls):
    for rpc_url in rpc_urls:
        try:
            web3 = Web3(Web3.HTTPProvider(rpc_url))
            if web3.is_connected():
                balance = web3.eth.get_balance(wallet_address)
                return round(web3.from_wei(balance, 'ether'), 5)
        except Exception as e:
            print(f"Error with RPC URL {rpc_url}: {e}")
    print("All Soneium RPC URLs failed. Please add more proxies.")
    return None

def get_gas_price(rpc_urls):
    for rpc_url in rpc_urls:
        try:
            web3 = Web3(Web3.HTTPProvider(rpc_url))
            if web3.is_connected():
                gas_price = web3.eth.gas_price
                return round(web3.from_wei(gas_price, 'gwei'), 2)
        except Exception as e:
            print(f"Error with RPC URL {rpc_url}: {e}")
    print("All RPC URLs failed. Please add more proxies.")
    return None

def sum_balances(file_path):
    total_balance = 0.0
    with open(file_path, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            total_balance += float(row['balance'])
    print(Fore.GREEN + f"\n\n\n⭐ Total balance: {total_balance:.8f}\n")

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