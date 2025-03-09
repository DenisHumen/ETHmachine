from web3 import Web3

def get_transaction_count(address, rpc_url):
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    checksum_address = web3.to_checksum_address(address)
    return web3.eth.get_transaction_count(checksum_address)
