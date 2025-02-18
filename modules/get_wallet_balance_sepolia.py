from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium
import requests
import json

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