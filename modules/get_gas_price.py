from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium
import requests
import json
from web3 import Web3

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