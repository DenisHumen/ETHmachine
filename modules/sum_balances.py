import csv
from colorama import Fore

def sum_balances(file_path):
    try:
        total_balance = 0.0
        with open(file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                total_balance += float(row['balance'])
        print(Fore.GREEN + f"\n\n\n⭐ Total balance: {total_balance:.8f}\n")
    except Exception as e:
        print(Fore.RED + f"Error: {e}")