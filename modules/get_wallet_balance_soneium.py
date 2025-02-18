from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium
import requests
import json
from web3 import Web3

def get_wallet_balance_soneium(wallet_address, rpc_urls):
    for rpc_url in rpc_urls:
        try:
            web3 = Web3(Web3.HTTPProvider(rpc_url))
            if web3.is_connected():
                balance = web3.eth.get_balance(wallet_address)
                return round(web3.from_wei(balance, 'ether'), 5)
        except Exception as e:
            print(f"Error with RPC URL {rpc_url}: {e}")
    print("All Soneium RPC URLs failed. Please add more proxies.")
    return None