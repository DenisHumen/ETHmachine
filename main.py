import time
import csv
from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium, Polygon, Binance_Smart_Chain, Avalanche, Fantom, Gravity_Alpha_Mainnet, monad_testnet, sahara_testnet, zora
from config.config import NUM_THREADS
from colorama import Fore, init
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
from questionary import Choice, select

# импорт функций из модулей
from modules.get_wallet_balance import get_wallet_balance
from modules.get_wallet_balance_fast import get_wallet_balance_fast
from modules.get_gas_price import get_gas_price
from modules.sum_balances import sum_balances
from modules.get_transaction_count import get_transaction_count

init(autoreset=True)

mainnet_rpc_urls = {
    '🚀 Ethereum Mainnet': L1,
    '🚀 Base': base,
    '🚀 Arbitrum One': arbitrum,
    '🚀 Optimism': optimism,
    '🚀 Soneium': soneium,
    '🚀 Polygon': Polygon,
    '🚀 Binance Smart Chain': Binance_Smart_Chain,
    '🚀 Avalanche': Avalanche,
    '🚀 Fantom': Fantom,
    '🚀 Gravity Alpha Mainnet': Gravity_Alpha_Mainnet,
    '🚀 Zora': zora
}

testnet_rpc_urls = {
    '🚀 Sepolia': sepolia,
    '🚀 Monad Testnet (native token MON)': monad_testnet,
    '🚀 Sahara testnet': sahara_testnet
}

def main_menu():
    try:
        while True:
            action = select(
                "What do you want to do?",
                choices=[
                    Choice('💲 Check Balances', 'check_balances'),
                    Choice('💰 Sum Balances', 'sum_balances'),
                    Choice('⛽ Check Gas Price', 'check_gas_price'),
                    Choice('🔢 Check Transaction Count', 'check_transaction_count'),
                    Choice('❌ Exit', 'exit')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()

            if action == 'exit':
                break

            if action == 'sum_balances':
                print(Fore.GREEN + "Summing balances from result/result.csv...")
                try:
                    with open('result/result.csv', 'r', encoding='utf-8') as csvfile:
                        reader = csv.reader(csvfile)
                        data = list(reader)
                        if len(data) <= 1:
                            print(Fore.RED + "Error: result/result.csv is empty. Please run balance check first.")
                        else:
                            sum_balances('result/result.csv')
                except FileNotFoundError:
                    print(Fore.RED + "Error: result/result.csv not found. Please run balance check first.")
                except Exception as e:
                    print(Fore.RED + f"Error: {e}")
                continue

            network_type = select(
                "Select network type:",
                choices=[
                    Choice('🌐 Mainnet', 'mainnet'),
                    Choice('🔧 Testnet', 'testnet'),
                    Choice('🔙 Back', 'back')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()

            if network_type == 'back':
                continue

            network_choices = list(mainnet_rpc_urls.keys()) if network_type == 'mainnet' else list(testnet_rpc_urls.keys())
            network = select(
                "Which network do you want to check?",
                choices=[Choice(n, n) for n in network_choices] + [Choice('🔙 Back', 'back')],
                qmark='🛠️',
                pointer='👉'
            ).ask()

            if network == 'back':
                continue

            if action == 'check_balances':
                check_balances_menu(network, network_type)
            elif action == 'check_gas_price':
                check_gas_price_menu(network, network_type)
            elif action == 'check_transaction_count':
                check_transaction_count_menu(network, network_type)
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_balances_menu(network, network_type):
    try:
        mode = select(
            "Select mode:",
            choices=[
                Choice('🚀 Fast (requires proxies)', 'fast'),
                Choice('🐢 Slow (no proxies)', 'slow')
            ],
            qmark='🛠️',
            pointer='👉'
        ).ask()

        with open('walletss.txt', 'r', encoding='utf-8') as file:
            wallet_addresses = file.readlines()

        rpc_urls = mainnet_rpc_urls if network_type == 'mainnet' else testnet_rpc_urls

        if mode == 'fast':
            check_balances_fast(wallet_addresses, network, random.choice(rpc_urls[network]))
        else:
            check_balances_slow(wallet_addresses, network, random.choice(rpc_urls[network]))
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_balances_fast(wallet_addresses, network, rpc_url):
    try:
        with open('proxy.csv', 'r', encoding='utf-8') as file:
            proxies = file.readlines()[1:]

        if len(proxies) == 0:
            print(Fore.RED + "ERROR: No proxies found in proxy.csv")
            return
        elif len(proxies) < len(wallet_addresses):
            print(Fore.YELLOW + "WARNING: Так как прокси меньше кошельков, будут браться рандомно.")
        else:
            print(Fore.GREEN + "INFO: Прокси больше или равны количеству кошельков, будет использоваться 1к1.")

        results = {addr.strip(): 'N/A' for addr in wallet_addresses}

        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            future_to_address = {executor.submit(get_wallet_balance_fast, addr.strip(), rpc_url, proxies.copy()): addr for addr in wallet_addresses}
            for future in tqdm(as_completed(future_to_address), total=len(wallet_addresses), desc="Checking balances", unit="wallet"):
                address = future_to_address[future]
                try:
                    balance = future.result()
                    results[address.strip()] = balance if balance is not None else 'N/A'
                except Exception as e:
                    print(Fore.RED + f"Error checking balance for {address.strip()}: {e}")

        with open('result/result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'balance', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for address in wallet_addresses:
                writer.writerow({'address': address.strip(), 'balance': results[address.strip()], 'network': network})

        print(Fore.GREEN + f"\n\n\nBalances checked and saved in result/result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_balances_slow(wallet_addresses, network, rpc_url):
    try:
        results = {addr.strip(): 'N/A' for addr in wallet_addresses}

        with open('result/result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'balance', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for address in tqdm(wallet_addresses, desc="Checking balances", unit="wallet"):
                address = address.strip()
                balance = get_wallet_balance(address, rpc_url)
                time.sleep(1)
                results[address] = balance

            for address in wallet_addresses:
                writer.writerow({'address': address.strip(), 'balance': results[address.strip()], 'network': network})

        print(Fore.GREEN + f"\n\n\nBalances checked and saved in result/result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_gas_price_menu(network, network_type):
    try:
        rpc_urls = mainnet_rpc_urls if network_type == 'mainnet' else testnet_rpc_urls
        gas_price = get_gas_price(random.choice(rpc_urls[network]))
        if gas_price is not None:
            print(Fore.GREEN + f"\n\n\n⛽ Current gas price on {network}: {gas_price} Gwei\n")
        else:
            print(Fore.RED + f"\n\n\n❌ Failed to retrieve gas price for {network}.\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_transaction_count_menu(network, network_type):
    try:
        with open('walletss.txt', 'r', encoding='utf-8') as file:
            wallet_addresses = file.readlines()

        with open('result/transaction_count_result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'transaction_count', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            rpc_urls = mainnet_rpc_urls if network_type == 'mainnet' else testnet_rpc_urls

            for address in tqdm(wallet_addresses, desc="Checking transaction counts", unit="wallet"):
                address = address.strip()
                count = get_transaction_count(address, random.choice(rpc_urls[network]))
                time.sleep(1)
                writer.writerow({'address': address, 'transaction_count': count, 'network': network})

        print(Fore.GREEN + f"\n\n\nTransaction counts checked and saved in result/transaction_count_result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

if __name__ == "__main__":
    main_menu()

