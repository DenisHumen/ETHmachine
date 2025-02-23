from config.rpc import Fantom
from web3 import Web3

def get_wallet_balance_fantom(wallet_address, rpc_urls):
    try:
        for rpc_url in rpc_urls:
            try:
                web3 = Web3(Web3.HTTPProvider(rpc_url))
                if web3.is_connected():
                    balance = web3.eth.get_balance(wallet_address)
                    return round(web3.from_wei(balance, 'ether'), 5)
            except Exception as e:
                print(f"Error with RPC URL {rpc_url}: {e}")
        print("All Fantom RPC URLs failed. Please add more proxies.")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None
