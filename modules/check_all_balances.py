import csv
import time
import random
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from config.rpc import *
from config.config import NUM_THREADS
from modules.get_wallet_balance import get_wallet_balance
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# Configure logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S')

def load_proxies(proxy_file='data/proxy.csv'):
    try:
        with open(proxy_file, 'r', encoding='utf-8') as file:
            proxies = [line.strip() for line in file.readlines() if line.strip()]
        return proxies
    except FileNotFoundError:
        print(Fore.RED + "Error: data/proxy.csv not found. Please add proxies.")
        return []

def format_proxy(proxy):
    if not proxy.startswith('http://'):
        return 'http://' + proxy
    return proxy

def fetch_balance_with_proxy(wallet, rpc_url, proxies, max_retries=5):
    retries = 0
    while retries < max_retries and proxies:
        proxy = random.choice(proxies)
        try:
            return get_wallet_balance(wallet, rpc_url, proxy=format_proxy(proxy))
        except Exception as e:
            if '429' in str(e) or 'RemoteDisconnected' in str(e) or 'Connection aborted' in str(e):
                proxies.remove(proxy)  # Remove the problematic proxy and retry
                retries += 1
                time.sleep(2 ** retries)  # Exponential backoff
            else:
                return f"Error: {e}"
    return "Error: No valid proxies available after retries"

def update_progress_bar(current, total, description="Progress"):
    progress = int((current / total) * 40)  # 40-character wide progress bar
    bar = f"[{Fore.GREEN}{'█' * progress}{Fore.RED}{'░' * (40 - progress)}{Style.RESET_ALL}]"
    percentage = (current / total) * 100
    sys.stdout.write(f"\r{Fore.CYAN}⏳ [{description}] {bar} {current}/{total} ({percentage:.1f}%)")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")  # Move to the next line when complete

def check_all_balances(wallet_addresses):
    # Dynamically fetch all networks from config.rpc
    networks = {key: value for key, value in globals().items() if isinstance(value, list)}
    proxies = load_proxies()

    if not proxies:
        print(Fore.RED + "Error: No proxies available. Please add proxies to data/proxy.csv.")
        return

    results = {wallet.strip(): {network: 'N/A' for network in networks.keys()} for wallet in wallet_addresses}
    error_log = []

    for network, rpc_urls in networks.items():
        logging.info(Fore.YELLOW + f"Starting balance check for network: {network}")
        total_wallets = len(wallet_addresses)
        completed_wallets = 0

        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            future_to_wallet = {
                executor.submit(fetch_balance_with_proxy, wallet.strip(), rpc_urls[0], proxies.copy()): wallet.strip()
                for wallet in wallet_addresses
            }
            for future in as_completed(future_to_wallet):
                wallet = future_to_wallet[future]
                try:
                    results[wallet][network] = future.result()
                except Exception as e:
                    error_message = f"Error checking {wallet} on {network}: {e}"
                    error_log.append(error_message)
                    results[wallet][network] = f"Error: {e}"
                completed_wallets += 1
                update_progress_bar(completed_wallets, total_wallets, description=f"Accounts completed for {network}")

    # Save results to result/result.csv
    with open('result/result.csv', 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['wallet_address'] + list(networks.keys())
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for wallet, balances in results.items():
            row = {'wallet_address': wallet}
            row.update(balances)
            writer.writerow(row)

    # Save error log to result/error_log.txt
    if error_log:
        with open('result/error_log.txt', 'w', encoding='utf-8') as error_file:
            error_file.write("\n".join(error_log))

    logging.info(Fore.GREEN + "Balances across all networks have been saved to result/result.csv.")
    if error_log:
        logging.info(Fore.RED + "Errors encountered during execution. Check result/error_log.txt for details.")
