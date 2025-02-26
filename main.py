import os
import sys
import platform
import json
import requests
from web3 import Web3
import time
import csv
import inquirer
from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium, Polygon, Binance_Smart_Chain, Avalanche, Fantom
from config.config import NUM_THREADS
from colorama import Fore, Style, init
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import random

# импорт функций из модулей
from modules.get_wallet_balance_avalanche import get_wallet_balance_avalanche, get_wallet_balance_avalanche_with_proxy
from modules.get_wallet_balance_bsc import get_wallet_balance_bsc, get_wallet_balance_bsc_with_proxy
from modules.get_wallet_balance_fantom import get_wallet_balance_fantom, get_wallet_balance_fantom_with_proxy
from modules.get_wallet_balance_polygon import get_wallet_balance_polygon, get_wallet_balance_polygon_with_proxy
from modules.get_wallet_balance_base import get_wallet_balance_base, get_wallet_balance_base_with_proxy
from modules.get_wallet_balance_arbitrum import get_wallet_balance_arbitrum, get_wallet_balance_arbitrum_with_proxy
from modules.get_wallet_balance_eth import get_wallet_balance_eth, get_wallet_balance_eth_with_proxy
from modules.get_wallet_balance_optimism import get_wallet_balance_optimism, get_wallet_balance_optimism_with_proxy
from modules.get_wallet_balance_sepolia import get_wallet_balance_sepolia, get_wallet_balance_sepolia_with_proxy
from modules.get_wallet_balance_soneium import get_wallet_balance_soneium, get_wallet_balance_soneium_with_proxy
from modules.get_gas_price import get_gas_price
from modules.sum_balances import sum_balances
from modules.get_transaction_count import get_transaction_count, get_transaction_count_with_proxy
from modules.check_transaction_count import check_transaction_count_fast, check_transaction_count_slow

init(autoreset=True)

def main_menu():
    try:
        while True:
            questions = [
                inquirer.List('action',
                              message="What do you want to do?",
                              choices=['💲 Check Balances', '💰 Sum Balances', '⛽ Check Gas Price', '🔢 Check Transaction Count', '', '❌ Exit'],
                             ),
            ]
            answers = inquirer.prompt(questions)
            action = answers['action']

            if action == '❌ Exit':
                break
            elif action == '💰 Sum Balances':
                sum_balances('result/result.csv')
            elif action == '💲 Check Balances':
                check_balances_menu()
            elif action == '⛽ Check Gas Price':
                check_gas_price_menu()
            elif action == '🔢 Check Transaction Count':
                check_transaction_count_menu()
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_balances_menu():
    try:
        questions = [
            inquirer.List('mode',
                          message="Select mode:",
                          choices=['🚀 Fast (requires proxies)', '🐢 Slow (no proxies)', '', '🔙 Back'],
                         ),
        ]
        answers = inquirer.prompt(questions)
        mode = answers['mode']

        if mode == '🔙 Back':
            return

        questions = [
            inquirer.List('network',
                          message="Which network do you want to check?",
                          choices=['🚀 Sepolia', '🚀 Ethereum Mainnet', '🚀 Base', '🚀 Arbitrum One', '🚀 Optimism', '🚀 Soneium', '🚀 Polygon', '🚀 Binance Smart Chain', '🚀 Avalanche', '🚀 Fantom', '', '🔙 Back'],
                         ),
        ]
        answers = inquirer.prompt(questions)
        network = answers['network']

        if network == '🔙 Back':
            return

        with open('walletss.txt', 'r', encoding='utf-8') as file:
            wallet_addresses = file.readlines()

        if mode == '🚀 Fast (requires proxies)':
            with open('proxy.csv', 'r', encoding='utf-8') as file:
                proxies = file.readlines()[1:]
            if len(proxies) < 1:
                print(Fore.RED + "❌ Error: Number of proxies is less than 1. Fast mode cannot be executed.")
                return
            elif len(proxies) < 10 and len(proxies) != len(wallet_addresses):
                print(Fore.YELLOW + "⚠️ Warning: Number of proxies is less than 10. The operation may be unstable.")

            if network == '🚀 Sepolia':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_sepolia_with_proxy(addr, rpc_urls, proxies)
            elif network == '🚀 Ethereum Mainnet':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_eth_with_proxy(addr, rpc_urls, proxies)
            elif network == '🚀 Base':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_base_with_proxy(addr, rpc_urls, proxies)
            elif network == '🚀 Arbitrum One':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_arbitrum_with_proxy(addr, rpc_urls, proxies)
            elif network == '🚀 Optimism':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_optimism_with_proxy(addr, rpc_urls, proxies)
            elif network == '🚀 Soneium':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_soneium_with_proxy(addr, rpc_urls, proxies)
            elif network == '🚀 Polygon':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_polygon_with_proxy(addr, rpc_urls, proxies)
            elif network == '🚀 Binance Smart Chain':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_bsc_with_proxy(addr, rpc_urls, proxies)
            elif network == '🚀 Avalanche':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_avalanche_with_proxy(addr, rpc_urls, proxies)
            elif network == '🚀 Fantom':
                get_balance = lambda addr, rpc_urls: get_wallet_balance_fantom_with_proxy(addr, rpc_urls, proxies)
            check_balances_fast(wallet_addresses, get_balance, network, sepolia)
        else:
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
            elif network == '🚀 Polygon':
                get_balance = lambda addr: get_wallet_balance_polygon(addr, Polygon)
            elif network == '🚀 Binance Smart Chain':
                get_balance = lambda addr: get_wallet_balance_bsc(addr, Binance_Smart_Chain)
            elif network == '🚀 Avalanche':
                get_balance = lambda addr: get_wallet_balance_avalanche(addr, Avalanche)
            elif network == '🚀 Fantom':
                get_balance = lambda addr: get_wallet_balance_fantom(addr, Fantom)
            check_balances_slow(wallet_addresses, get_balance, network)
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_balances_fast(wallet_addresses, get_balance, network, rpc_urls):
    try:
        with open('proxy.csv', 'r', encoding='utf-8') as file:
            proxies = file.readlines()[1:]

        if len(proxies) < len(wallet_addresses):
            print(Fore.YELLOW + "WARNING: Так как прокси меньше кошельков, будут браться рандомно.")
        else:
            print(Fore.GREEN + "INFO: Прокси больше или равны количеству кошельков, будет использоваться 1к1.")

        with open('result/result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'balance', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
                future_to_address = {executor.submit(get_balance_with_proxy, addr.strip(), proxies, get_balance, wallet_addresses, rpc_urls): addr for addr in wallet_addresses}
                for future in tqdm(as_completed(future_to_address), total=len(wallet_addresses), desc="Checking balances", unit="wallet"):
                    address = future_to_address[future]
                    try:
                        balance = future.result()
                        if balance is not None:
                            writer.writerow({'address': address.strip(), 'balance': balance, 'network': network})
                        else:
                            writer.writerow({'address': address.strip(), 'balance': 'N/A', 'network': network})
                    except Exception as e:
                        print(Fore.RED + f"Error checking balance for {address.strip()}: {e}")
                        writer.writerow({'address': address.strip(), 'balance': 'N/A', 'network': network})

        print(Fore.GREEN + f"\n\n\nBalances checked and saved in result/result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def get_balance_with_proxy(address, proxies, get_balance, wallet_addresses, rpc_urls):
    backup_proxies = proxies.copy()
    max_proxy_switches = 5
    max_rpc_switches = 10
    rpc_index = 0
    proxy_switch_count = 0
    rpc_switch_count = 0

    while rpc_switch_count < max_rpc_switches:
        if address in wallet_addresses:
            proxy = random.choice(proxies) if len(proxies) < len(wallet_addresses) else proxies[wallet_addresses.index(address) % len(proxies)]
        else:
            proxy = random.choice(proxies)
        proxies_dict = {
            "http": proxy,
            "https": proxy,
        }
        try:
            balance = get_balance(address, [rpc_urls[rpc_index]])
            if balance is not None:
                return balance
        except Exception as e:
            print(Fore.RED + f"Error with proxy {proxy}: {e}")
            proxies.remove(proxy)
            proxy_switch_count += 1
            if proxy_switch_count >= max_proxy_switches:
                proxy_switch_count = 0
                rpc_index += 1
                rpc_switch_count += 1
                if rpc_index >= len(rpc_urls):
                    rpc_index = 0
                proxies = backup_proxies.copy()
            if not proxies:
                print(Fore.YELLOW + "No working proxies left, switching to backup proxies.")
                proxies = backup_proxies.copy()
            if not proxies:
                print(Fore.RED + "No working proxies available.")
                return None
    print(Fore.RED + "All RPC URLs and proxies failed. Marking as error.")
    return None

def check_balances_slow(wallet_addresses, get_balance, network):
    try:
        with open('result/result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'balance', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for address in tqdm(wallet_addresses, desc="Checking balances", unit="wallet"):
                address = address.strip()
                balance = get_balance(address)
                time.sleep(1)
                writer.writerow({'address': address, 'balance': balance, 'network': network})

        print(Fore.GREEN + f"\n\n\nBalances checked and saved in result/result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_gas_price_menu():
    try:
        while True:
            questions = [
                inquirer.List('network',
                              message="Which network's gas price do you want to check?",
                              choices=['🚀 Sepolia', '🚀 Ethereum Mainnet', '🚀 Base', '🚀 Arbitrum One', '🚀 Optimism', '🚀 Soneium', '🚀 Polygon', '🚀 Binance Smart Chain', '🚀 Avalanche', '🚀 Fantom', '', '🔙 Back'],
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
            elif network == '🚀 Polygon':
                gas_price = get_gas_price(Polygon)
            elif network == '🚀 Binance Smart Chain':
                gas_price = get_gas_price(Binance_Smart_Chain)
            elif network == '🚀 Avalanche':
                gas_price = get_gas_price(Avalanche)
            elif network == '🚀 Fantom':
                gas_price = get_gas_price(Fantom)

            if gas_price is not None:
                print(Fore.GREEN + f"\n\n\n⛽ Current gas price on {network}: {gas_price} Gwei\n")
            else:
                print(Fore.RED + f"\n\n\n❌ Failed to retrieve gas price for {network}\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_transaction_count_menu():
    try:
        while True:
            questions = [
                inquirer.List('network',
                              message="Which network's transaction count do you want to check?",
                              choices=['🚀 Sepolia', '🚀 Ethereum Mainnet', '🚀 Base', '🚀 Arbitrum One', '🚀 Optimism', '🚀 Soneium', '🚀 Polygon', '🚀 Binance Smart Chain', '🚀 Avalanche', '🚀 Fantom', '', '🔙 Back'],
                             ),
            ]
            answers = inquirer.prompt(questions)
            network = answers['network']

            if network == '🔙 Back':
                return

            questions = [
                inquirer.List('mode',
                              message="Select mode:",
                              choices=['🚀 Fast (requires proxies)', '🐢 Slow (no proxies)', '', '🔙 Back'],
                             ),
            ]
            answers = inquirer.prompt(questions)
            mode = answers['mode']

            if mode == '🔙 Back':
                return

            if network == '🚀 Sepolia':
                get_count = lambda addr: get_transaction_count(addr, sepolia)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, sepolia, proxies)
            elif network == '🚀 Ethereum Mainnet':
                get_count = lambda addr: get_transaction_count(addr, L1)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, L1, proxies)
            elif network == '🚀 Base':
                get_count = lambda addr: get_transaction_count(addr, base)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, base, proxies)
            elif network == '🚀 Arbitrum One':
                get_count = lambda addr: get_transaction_count(addr, arbitrum)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, arbitrum, proxies)
            elif network == '🚀 Optimism':
                get_count = lambda addr: get_transaction_count(addr, optimism)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, optimism, proxies)
            elif network == '🚀 Soneium':
                get_count = lambda addr: get_transaction_count(addr, soneium)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, soneium, proxies)
            elif network == '🚀 Polygon':
                get_count = lambda addr: get_transaction_count(addr, Polygon)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, Polygon, proxies)
            elif network == '🚀 Binance Smart Chain':
                get_count = lambda addr: get_transaction_count(addr, Binance_Smart_Chain)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, Binance_Smart_Chain, proxies)
            elif network == '🚀 Avalanche':
                get_count = lambda addr: get_transaction_count(addr, Avalanche)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, Avalanche, proxies)
            elif network == '🚀 Fantom':
                get_count = lambda addr: get_transaction_count(addr, Fantom)
                get_count_with_proxy = lambda addr, proxies: get_transaction_count_with_proxy(addr, Fantom, proxies)

            with open('walletss.txt', 'r', encoding='utf-8') as file:
                wallet_addresses = file.readlines()

            if mode == '🚀 Fast (requires proxies)':
                with open('proxy.csv', 'r', encoding='utf-8') as file:
                    proxies = file.readlines()[1:]
                if len(proxies) < 1:
                    print(Fore.RED + "❌ Error: Number of proxies is less than 1. Fast mode cannot be executed.")
                    return
                elif len(proxies) < 10 and len(proxies) != len(wallet_addresses):
                    print(Fore.YELLOW + "⚠️ Warning: Number of proxies is less than 10. The operation may be unstable.")
                check_transaction_count_fast(wallet_addresses, get_count_with_proxy, network, proxies)
            else:
                check_transaction_count_slow(wallet_addresses, get_count, network)
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

if __name__ == "__main__":
    main_menu()