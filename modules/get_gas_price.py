from web3 import Web3

def get_gas_price(rpc_url):
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    gas_price = web3.eth.gas_price
    return round(web3.from_wei(gas_price, 'gwei'), 2)