from web3 import Web3
import random

def get_transaction_count(wallet_address, rpc_urls):
    try:
        for rpc_url in rpc_urls:
            try:
                web3 = Web3(Web3.HTTPProvider(rpc_url))
                if web3.is_connected():
                    count = web3.eth.get_transaction_count(wallet_address)
                    return count
            except Exception as e:
                print(f"Error with RPC URL {rpc_url}: {e}")
        print("All RPC URLs failed. Please add more proxies.")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

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
