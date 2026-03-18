import csv
from itertools import cycle
from colorama import Fore, Style
import sys
from web3 import Web3

def process_private_keys(input_path=None, output_path="result/result.csv"):
    # Чтение приватных ключей из data.csv
    from modules.data_manager import get_private_keys
    private_keys = get_private_keys()

    spinner_cycle = cycle(["|", "/", "-", "\\"])
    bar_length = 30
    total = len(private_keys)
    results = []

    # Преобразование приватных ключей в адреса
    with open(output_path, "w", newline='', encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["priv_key", "address"])
        for i, priv_key in enumerate(private_keys):
            try:
                # Добавляем 0x если его нет
                if not priv_key.startswith('0x'):
                    priv_key = '0x' + priv_key
                
                # Получаем адрес через web3
                account = Web3().eth.account.from_key(priv_key)
                address = account.address
                
                writer.writerow([priv_key, address])
                results.append((priv_key, address))
            except Exception as e:
                print(f"\n{Fore.RED}Ошибка для приватного ключа {priv_key[:16]}...: {e}{Style.RESET_ALL}", file=sys.stderr)
            
            # Прогресс-бар
            progress = int(((i + 1) / total) * bar_length)
            bar = "█" * progress + "░" * (bar_length - progress)
            spinner_frame = next(spinner_cycle)
            print(
                f"\r[GEN] [{bar}] {i+1}/{total} | {spinner_frame} Private keys to addresses...",
                end="",
                flush=True,
            )
    print()

    # Верификация результата
    spinner_cycle_check = cycle(["|", "/", "-", "\\"])
    bar_length_check = 30
    checked = 0
    verified_results = []
    
    with open(output_path, "r", encoding="utf-8") as file:
        reader = csv.reader(file)
        next(reader)  # skip header
        rows = list(reader)
        total_rows = len(rows)
        
        for i, (priv_key, address) in enumerate(rows):
            mark = ""
            try:
                # Проверка по приватному ключу
                check_account = Web3().eth.account.from_key(priv_key)
                check_address = check_account.address
                
                if check_address != address:
                    mark = " ⚠️⚠️⚠️"
            except Exception as e:
                mark = " ⚠️⚠️⚠️"
                
            verified_results.append((priv_key, address, mark))
            checked += 1
            
            progress = int((checked / total_rows) * bar_length_check)
            bar = "█" * progress + "░" * (bar_length_check - progress)
            spinner_frame = next(spinner_cycle_check)
            print(
                f"\r[CHK] [{bar}] {checked}/{total_rows} | {spinner_frame} Verifying...",
                end="",
                flush=True,
            )
    print()

    # Перезапись файла с отметками
    with open(output_path, "w", newline='', encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["priv_key", "address", "check"])
        for row in verified_results:
            writer.writerow(row)

# Пример вызова:
# process_private_keys()
