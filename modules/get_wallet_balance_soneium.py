from web3 import Web3
import random

def get_wallet_balance_soneium(wallet_address, rpc_urls):
    try:
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
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_wallet_balance_soneium_with_proxy(wallet_address, rpc_urls, proxies):
    backup_proxies = proxies.copy()
    max_proxy_switches = 5
    max_rpc_switches = 10
    rpc_index = 0
    proxy_switch_count = 0
    rpc_switch_count = 0

    while rpc_switch_count < max_rpc_switches:
        proxy = random.choice(proxies)
        proxies_dict = {
            "http": proxy,
            "https": proxy,
        }
        try:
            balance = get_wallet_balance_soneium(wallet_address, [rpc_urls[rpc_index]])
            if balance is not None:
                return balance
        except Exception as e:
            print(f"Error with proxy {proxy}: {e}")
            proxies.remove(proxy)
            proxy_switch_count += 1
            if proxy_switch_count >= max_proxy_switches:
                proxy_switch_count = 0
                rpc_index += 1
                rpc_switch_count += 1
                if rpc_index >= len(rpc_urls):
                    rpc_index = 0
            if not proxies:
                print("No working proxies left, switching to backup proxies.")
                proxies = backup_proxies.copy()
            if not proxies:
                print("No working proxies available.")
                return None
    print("All RPC URLs and proxies failed. Marking as error.")
    return None