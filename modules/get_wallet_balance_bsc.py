from config.rpc import Binance_Smart_Chain
from web3 import Web3
import random

def get_wallet_balance_bsc(wallet_address, rpc_urls):
    try:
        for rpc_url in rpc_urls:
            try:
                web3 = Web3(Web3.HTTPProvider(rpc_url))
                if web3.is_connected():
                    balance = web3.eth.get_balance(wallet_address)
                    return round(web3.from_wei(balance, 'ether'), 5)
            except Exception as e:
                print(f"Error with RPC URL {rpc_url}: {e}")
        print("All Binance Smart Chain RPC URLs failed. Please add more proxies.")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_wallet_balance_bsc_with_proxy(wallet_address, rpc_urls, proxies):
    backup_proxies = proxies.copy()
    while True:
        proxy = random.choice(proxies)
        proxies_dict = {
            "http": proxy,
            "https": proxy,
        }
        try:
            return get_wallet_balance_bsc(wallet_address, rpc_urls)
        except Exception as e:
            print(f"Error with proxy {proxy}: {e}")
            proxies.remove(proxy)
            if not proxies:
                print("No working proxies left, switching to backup proxies.")
                proxies = backup_proxies.copy()
            if not proxies:
                print("No working proxies available.")
                return None
