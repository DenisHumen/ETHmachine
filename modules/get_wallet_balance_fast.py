from web3 import Web3
import random

def get_wallet_balance_fast(address, rpc_url, proxies):
    while proxies:
        proxy = random.choice(proxies)
        proxies_dict = {
            "http": proxy,
            "https": proxy,
        }
        try:
            web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'proxies': proxies_dict}))
            checksum_address = web3.to_checksum_address(address)
            balance = web3.eth.get_balance(checksum_address)
            return web3.from_wei(balance, 'ether')
        except Exception as e:
            print(f"Error with proxy {proxy}: {e}")
            proxies.remove(proxy)
    
    print("No working proxies left")
    return None
