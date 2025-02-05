import re

def sum_wallet_balances(file_path):
    with open(file_path, 'r') as file:
        balances = file.readlines()
    
    total_balance = 0.0
    for balance in balances:
        match = re.search(r'(\d+\.\d+)', balance)
        if match:
            total_balance += float(match.group(1))
    
    print(f"Total balance: {total_balance}")

if __name__ == "__main__":
    file_path = 'wallet_balances.txt'
    sum_wallet_balances(file_path)