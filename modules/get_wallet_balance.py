from web3 import Web3

def get_wallet_balance(address, rpc_url, proxy=None):
    try:
        provider = Web3.HTTPProvider(rpc_url, request_kwargs={"proxies": {"http": proxy, "https": proxy}} if proxy else {})
        web3 = Web3(provider)
        checksum_address = web3.to_checksum_address(address)
        balance = web3.eth.get_balance(checksum_address)
        return web3.from_wei(balance, 'ether')
    except Exception as e:
        return f"Error: {e}"
