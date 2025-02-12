import json
import requests
from web3 import Web3
import time
import csv
import inquirer
from config.rpc import L1, base, sepolia

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

def sum_balances(file_path):
    total_balance = 0.0
    with open(file_path, 'r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            total_balance += float(row['balance'])
    print(f"\n\n\n⭐ Total balance: {total_balance}")

def main_menu():
    while True:
        questions = [
            inquirer.List('action',
                          message="What do you want to do?",
                          choices=['💲 Check Balances', '💰 Sum Balances', '❌ Exit'],
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

def check_balances_menu():
    while True:
        questions = [
            inquirer.List('network',
                          message="Which network do you want to check?",
                          choices=['🚀 Sepolia', '🚀 Ethereum Mainnet', '🚀 Base', '🔙 Back'],
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

        with open('walletss.txt', 'r') as file:
            wallet_addresses = file.readlines()

        with open('result.csv', 'w', newline='') as csvfile:
            fieldnames = ['address', 'balance', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for address in wallet_addresses:
                address = address.strip()
                balance = get_balance(address)
                time.sleep(1)
                writer.writerow({'address': address, 'balance': balance, 'network': network})

        print(f"Balances checked and saved in result.csv for {network} network")

if __name__ == "__main__":
    main_menu()
