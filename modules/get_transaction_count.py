from web3 import Web3

def get_transaction_count(address, rpc_url):
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    return web3.eth.get_transaction_count(address)
