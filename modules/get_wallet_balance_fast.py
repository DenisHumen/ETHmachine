from web3 import Web3
import random

def get_wallet_balance_fast(address, rpc_url, proxies):
    while True:
        proxy = random.choice(proxies)
        proxies_dict = {
            "http": proxy,
            "https": proxy,
        }
        try:
            web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'proxies': proxies_dict}))
            balance = web3.eth.get_balance(address)
            return web3.fromWei(balance, 'ether')
        except Exception as e:
            print(f"Error with proxy {proxy}: {e}")
            proxies.remove(proxy)
            if not proxies:
                print("No working proxies left")
                return None
