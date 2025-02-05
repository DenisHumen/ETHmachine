import json
import requests

rpc_url = "https://sepolia.infura.io/v3/3fed4f332ce94dd19bed579f074f8aab"

def get_wallet_balance(wallet_address):
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [wallet_address, "latest"],
        "id": 1
    }
    response = requests.post(rpc_url, headers=headers, data=json.dumps(payload))
    result = response.json().get("result")
    if result:
        balance = int(result, 16) / 10**18  
        return balance
    else:
        return None

with open('walletss.txt', 'r') as file:
    wallets = file.readlines()

with open('wallet_balances.txt', 'w') as file:
    for wallet in wallets:
        wallet = wallet.strip()
        balance = get_wallet_balance(wallet)
        if balance is not None:
            file.write(f"{balance}\n")
        else:
            file.write("Error\n")

print("Баланс кошельков проверен и записан в wallet_balances.txt")