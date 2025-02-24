import time
import random
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from colorama import Fore
import csv
from config.config import NUM_THREADS
from modules.get_transaction_count import get_transaction_count

def get_transaction_count_with_proxy(wallet_address, rpc_urls, proxies):
    backup_proxies = proxies.copy()
    while True:
        proxy = random.choice(proxies)
        proxies_dict = {
            "http": proxy,
            "https": proxy,
        }
        try:
            return get_transaction_count(wallet_address, rpc_urls)
        except Exception as e:
            print(f"Error with proxy {proxy}: {e}")
            proxies.remove(proxy)
            if not proxies:
                print("No working proxies left, switching to backup proxies.")
                proxies = backup_proxies.copy()
            if not proxies:
                print("No working proxies available.")
                return None

def check_transaction_count_fast(wallet_addresses, get_count_with_proxy, network, proxies):
    try:
        with open('result/transaction_count_result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'transaction_count', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
                future_to_address = {executor.submit(get_count_with_proxy, addr.strip(), proxies): addr for addr in wallet_addresses}
                for future in tqdm(as_completed(future_to_address), total=len(wallet_addresses), desc="Checking transaction counts", unit="wallet"):
                    address = future_to_address[future]
                    try:
                        count = future.result()
                        writer.writerow({'address': address.strip(), 'transaction_count': count, 'network': network})
                    except Exception as e:
                        print(Fore.RED + f"Error checking transaction count for {address.strip()}: {e}")
                        writer.writerow({'address': address.strip(), 'transaction_count': 'N/A', 'network': network})

        print(Fore.GREEN + f"\n\n\nTransaction counts checked and saved in result/transaction_count_result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")

def check_transaction_count_slow(wallet_addresses, get_count, network):
    try:
        with open('result/transaction_count_result.csv', 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['address', 'transaction_count', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for address in tqdm(wallet_addresses, desc="Checking transaction counts", unit="wallet"):
                address = address.strip()
                count = get_count(address)
                time.sleep(1)
                writer.writerow({'address': address, 'transaction_count': count, 'network': network})

        print(Fore.GREEN + f"\n\n\nTransaction counts checked and saved in result/transaction_count_result.csv for {network} network\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")
