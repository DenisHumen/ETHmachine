from web3 import Web3

def get_wallet_balance(address, rpc_url):
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    checksum_address = web3.to_checksum_address(address)
    balance = web3.eth.get_balance(checksum_address)
    return web3.from_wei(balance, 'ether')
