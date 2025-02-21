from web3 import Web3

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
