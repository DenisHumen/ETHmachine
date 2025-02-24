from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium
import requests
import json
import random

def get_wallet_balance_sepolia(wallet_address, rpc_urls):
    try:
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
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_wallet_balance_sepolia_with_proxy(wallet_address, rpc_urls, proxies):
    backup_proxies = proxies.copy()
    while True:
        proxy = random.choice(proxies)
        proxies_dict = {
            "http": proxy,
            "https": proxy,
        }
        try:
            return get_wallet_balance_sepolia(wallet_address, rpc_urls)
        except Exception as e:
            print(f"Error with proxy {proxy}: {e}")
            proxies.remove(proxy)
            if not proxies:
                print("No working proxies left, switching to backup proxies.")
                proxies = backup_proxies.copy()
            if not proxies:
                print("No working proxies available.")
                return None