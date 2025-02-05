from web3 import Web3
import time

def get_eth_balance(wallet_address, web3):
    balance = web3.eth.get_balance(wallet_address)
    return round(web3.from_wei(balance, 'ether'), 5)

def main():
    infura_url = 'https://base.llamarpc.com'
    web3 = Web3(Web3.HTTPProvider(infura_url))

    if not web3.is_connected():
        print("Failed to connect to the Ethereum network")
        return

    with open('walletss.txt', 'r') as file:
        wallet_addresses = file.readlines()

    with open('wallet_balances.txt', 'w') as output_file:
        for address in wallet_addresses:
            address = address.strip()
            balance = get_eth_balance(address, web3)
            time.sleep(1)
            output_file.write(f"{address} --- {balance} ETH\n")

if __name__ == "__main__":
    main()