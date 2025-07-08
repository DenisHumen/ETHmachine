import random
from web3 import Web3
from eth_account import Account
from colorama import Fore
import time
from datetime import datetime, timedelta
import csv
from config.config import TX_SEND_ATTEMPTS, WHAITE_TRANSACTION_PENDING, WHAITE_TRANSACTION_PENDING_COUNT, expected_completion_time, MIN_FROM_BALANCE, trim_the_number_of_characters_enable, trim_the_number_of_characters, loop_transfer_enable, loop_transfer_count, expected_balance_from_wallet, expected_balance_to_wallet, sleep_time_between_loops
from itertools import cycle
from colorama import Style
import json
import os
from config.explorer_url import get_explorer_url


def parse_percent_range(percent_str):
    try:
        parts = percent_str.split('-')
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        else:
            val = int(parts[0])
            return val, val
    except Exception:
        return 100, 100  

def get_network_rpc(network):
    from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium, Polygon, Binance_Smart_Chain, Avalanche, Fantom, Gravity_Alpha_Mainnet, monad_testnet, sahara_testnet, zora, somnia_testnet, mega_eth_testnet, Abstract
    mainnet_rpc_urls = {
        '🚀 Ethereum Mainnet': L1,
        '🚀 Base': base,
        '🚀 Arbitrum One': arbitrum,
        '🚀 Optimism': optimism,
        '🚀 Soneium': soneium,
        '🚀 Polygon': Polygon,
        '🚀 Binance Smart Chain': Binance_Smart_Chain,
        '🚀 Avalanche': Avalanche,
        '🚀 Fantom': Fantom,
        '🚀 Gravity Alpha Mainnet': Gravity_Alpha_Mainnet,
        '🚀 Zora': zora,
        '🚀 Abstract': Abstract,
    }
    testnet_rpc_urls = {
        '🚀 Sepolia': sepolia,
        '🚀 Monad Testnet (native token MON)': monad_testnet,
        '🚀 Sahara testnet': sahara_testnet,
        '🚀 Somnia Testnet': somnia_testnet,
        '🚀 Mega ETH': mega_eth_testnet,
    }
    if network in mainnet_rpc_urls:
        return random.choice(mainnet_rpc_urls[network])
    elif network in testnet_rpc_urls:
        return random.choice(testnet_rpc_urls[network])
    else:
        raise Exception(f"Неизвестная сеть: {network}")

def get_eth_balance(w3, address):
    try:
        return w3.eth.get_balance(address)
    except Exception as e:
        print(Fore.RED + f"Ошибка получения баланса: {e}")
        return 0

def estimate_gas_with_margin(w3, tx):
    try:
        gas = w3.eth.estimate_gas(tx)
        return int(gas * 1.2)  # +20%
    except Exception as e:
        print(Fore.YELLOW + f"Не удалось оценить газ, используем 21000: {e}")
        return int(21000 * 1.2)

def send_with_retry(w3, signed_tx, explorer_url, max_attempts=None):
    if max_attempts is None:
        max_attempts = TX_SEND_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = w3.to_hex(tx_hash)
            print(Fore.LIGHTBLUE_EX + Style.BRIGHT + f"🔗 Посмотреть транзакцию: {explorer_url}{tx_hash_hex}" + Style.RESET_ALL)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt and receipt.status == 1:
                return True, tx_hash_hex
            else:
                print(Fore.RED + f"Транзакция неуспешна (статус != 1): {tx_hash_hex}")
        except Exception as e:
            print(Fore.RED + f"Ошибка отправки/подтверждения транзакции (попытка {attempt}): {e}")
        time.sleep(WHAITE_TRANSACTION_PENDING)
    print(Fore.RED + "Не удалось выполнить транзакцию после нескольких попыток.")
    return False, None

def append_result_csv(row):
    filename = "result/result.csv"
    header = [
        "datetime", "from_wallet", "from_address", "intermediary_wallet", "intermediary_address",
        "to_wallet", "to_address", "amount_sent_wei", "amount_sent_eth", "tx_hash_1", "tx_hash_2",
        "explorer_link_1", "explorer_link_2"
    ]
    try:
        need_header = False
        try:
            with open(filename, "r", encoding="utf-8") as f:
                if not f.readline():
                    need_header = True
        except FileNotFoundError:
            need_header = True
        with open(filename, "a", encoding="utf-8", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            if need_header:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        print(Fore.RED + f"Ошибка записи в result/result.csv: {e}")

def get_proxy_list():
    proxies = []
    try:
        with open("data/proxy.csv", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.lower().startswith("proxy"):
                    continue
                if line.startswith("http://"):
                    line = line[7:]
                proxies.append(line)
    except Exception as e:
        print(Fore.YELLOW + f"Не удалось загрузить прокси: {e}")
    if not proxies:
        print(Fore.RED + "ВНИМАНИЕ: В файле data/proxy.csv не найдено ни одного прокси!")
        input(Fore.YELLOW + "Добавьте прокси в файл data/proxy.csv и нажмите Enter для продолжения, либо Ctrl+C для выхода...")
    return proxies

def get_web3_with_proxy(rpc_url, proxy_url):
    import requests
    from web3 import HTTPProvider
    
    session = None
    try:
        session = requests.Session()
        
        if proxy_url:
            if '@' in proxy_url:
                auth_part, address_part = proxy_url.split('@')
                login, password = auth_part.split(':')
                ip, port = address_part.split(':')
                proxy_dict = {
                    'http': f"http://{login}:{password}@{ip}:{port}",
                    'https': f"http://{login}:{password}@{ip}:{port}"
                }
            else:
                proxy_dict = {
                    'http': f"http://{proxy_url}",
                    'https': f"http://{proxy_url}"
                }
            
            session.proxies.update(proxy_dict)
        
        provider = HTTPProvider(rpc_url, session=session)
        w3 = Web3(provider)
        
        _ = w3.eth.chain_id
        return w3, session
        
    except Exception as e:
        print(Fore.RED + f"ВНИМАНИЕ: Ошибка подключения через прокси или RPC недоступен: {e}")
        if session:
            session.close()
        # Возвращаем обычное соединение без прокси шоб хоть как-то работало
        provider = HTTPProvider(rpc_url)
        w3 = Web3(provider)
        return w3, None

def countdown_timer(seconds, message_prefix="Пауза"):
    for remaining in range(seconds, 0, -1):
        print(
            f"{Fore.YELLOW}{message_prefix} {remaining} сек до следующей транзакции...{Style.RESET_ALL} ",
            end="\r",
            flush=True,
        )
        time.sleep(1)
    print("\r" + " " * 80 + "\r", end="")  

def countdown_timer_with_expected_time(total_tx, completed_txs):
    remaining_tx = total_tx - completed_txs
    if remaining_tx > 0:
        delay = expected_completion_time / total_tx
        for remaining in range(int(delay), 0, -1):
            print(
                f"\r{Fore.YELLOW}Ожидание {remaining} сек до следующей транзакции...{Style.RESET_ALL} ",
                end="",
                flush=True,
            )
            time.sleep(1)
        print("\r" + " " * 60 + "\r", end="")  

def get_eth_balance_safe(w3, address, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    for attempt in range(max_attempts):
        try:
            balance = w3.eth.get_balance(address)
            if balance >= 0:  
                return balance
        except Exception as e:
            print(Fore.YELLOW + f"[{address}] Ошибка получения баланса (попытка {attempt+1}/{max_attempts}): {e}")
            time.sleep(sleep_sec)
    print(Fore.RED + f"[{address}] Не удалось получить баланс после {max_attempts} попыток.")
    return 0

def get_nonce_safe(w3, address, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    for attempt in range(max_attempts):
        try:
            return w3.eth.get_transaction_count(address)
        except Exception as e:
            print(Fore.YELLOW + f"[{address}] Ошибка получения nonce (попытка {attempt+1}/{max_attempts}): {e}")
            time.sleep(sleep_sec)
    print(Fore.RED + f"[{address}] Не удалось получить nonce после {max_attempts} попыток.")
    return None

def estimate_gas_with_margin_safe(w3, tx, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    for attempt in range(max_attempts):
        try:
            gas = w3.eth.estimate_gas(tx)
            return int(gas * 1.2)  # +20%
        except KeyboardInterrupt:
            print(Fore.RED + "\nОперация прервана пользователем (Ctrl+C). Завершение работы.")
            raise
        except Exception as e:
            print(Fore.YELLOW + f"Не удалось оценить газ (попытка {attempt+1}/{max_attempts}), используем 21000: {e}")
            time.sleep(sleep_sec)
    return int(21000 * 1.2)

def transefer_wallets_to_wallets(from_priv, intermediary_priv, to_priv, network, amount, proxy=None, delay_between=0, tx_counter=0, total_tx=1):
    session = None
    try:
        start_time = time.time()
        dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        rpc_url = get_network_rpc(network)
        proxies = get_proxy_list()
        use_proxy = None
        if proxy:
            use_proxy = proxy
        elif proxies:
            use_proxy = random.choice(proxies)

        try:
            from_acc = Account.from_key(from_priv)
            intermediary_acc = Account.from_key(intermediary_priv)
            to_acc = Account.from_key(to_priv)
        except Exception as e:
            print(Fore.RED + f"Ошибка создания аккаунта: {e}")
            return

        if use_proxy:
            if '@' in use_proxy:
                proxy_parts = use_proxy.split("@")
                proxy_hidden = f"xxxx:xxx@{proxy_parts[-1].rsplit('.', 1)[0]}.x:{proxy_parts[-1].split(':')[-1]}"
            else:
                proxy_hidden = f"{use_proxy.rsplit('.', 1)[0]}.x:{use_proxy.split(':')[-1]}"
        else:
            proxy_hidden = "Нет доступных прокси"

        print(Fore.MAGENTA + "\n" + "="*61)
        print(Fore.YELLOW + f"[{dt_str}] Запуск цепочки перевода:")
        print(Fore.CYAN + f"  FROM:         priv - {from_priv[:10]}... | wallet - {from_acc.address[:10]}...")
        print(Fore.CYAN + f"  INTERMEDIARY: priv - {intermediary_priv[:10]}... | wallet - {intermediary_acc.address[:10]}...")
        print(Fore.CYAN + f"  TO:           priv - {to_priv[:10]}... | wallet - {to_acc.address[:10]}...")
        print(Fore.CYAN + f"  Сеть:         {network}")
        print(Fore.CYAN + f"  Процент:      {amount}%")
        print(Fore.CYAN + f"  Используется прокси: {proxy_hidden}")
        print(Fore.MAGENTA + "-"*61)
        
        w3, session = get_web3_with_proxy(rpc_url, use_proxy)

        explorer_url = get_explorer_url(network)

        for attempt in range(TX_SEND_ATTEMPTS):
            balance = get_eth_balance_safe(w3, from_acc.address)
            if balance > 0:
                break
            print(Fore.YELLOW + f"Попытка {attempt+1}/{TX_SEND_ATTEMPTS}: Баланс {from_acc.address} = 0, ждем 3 сек...")
            time.sleep(3)
        else:
            print(Fore.RED + f"Баланс {from_acc.address} = 0 после {TX_SEND_ATTEMPTS} попыток, пропуск")
            return

        percent_from, percent_to = parse_percent_range(amount)
        percent = random.randint(percent_from, percent_to)

        try:
            gas_price = w3.eth.gas_price
        except Exception as e:
            print(Fore.YELLOW + f"Ошибка получения цены газа: {e}")
            gas_price = int(w3.to_wei('30', 'gwei'))  

        nonce_from = get_nonce_safe(w3, from_acc.address)
        if nonce_from is None:
            print(Fore.RED + f"Не удалось получить nonce для {from_acc.address}, пропуск")
            return

        def get_send_amount(balance, percent, w3, from_addr, to_addr, gas_price, chain_id, priv_key):
            value = int(balance * percent / 100)
            tx = {
                'type': 0x2,
                'from': Web3.to_checksum_address(from_addr),
                'to': Web3.to_checksum_address(to_addr),
                'value': value,
                'gas': 1000000,
                'nonce': nonce_from,
                'chainId': chain_id,
                'maxFeePerGas': int(gas_price * 1.2),
                'maxPriorityFeePerGas': 0
            }

            estimated_gas = w3.eth.estimate_gas(tx)
            gas = int(estimated_gas * 1.2)
            fee = gas * int(gas_price * 1.2)
            
            min_balance_random = random.uniform(MIN_FROM_BALANCE[0], MIN_FROM_BALANCE[1])
            if trim_the_number_of_characters_enable:

                min_balance_random = round(min_balance_random, random.choice(trim_the_number_of_characters))
            min_balance_wei = w3.to_wei(min_balance_random, 'ether')

            if value + fee > balance - min_balance_wei:
                original_value = value
                value = balance - fee - min_balance_wei
                if value < 0:
                    value = 0
                print(Fore.YELLOW + f"⚠️ Перерасчет отправляемой суммы: должно было отправиться {w3.from_wei(original_value, 'ether')} ETH, "
                                    f"но будет отправлено {w3.from_wei(value, 'ether')} ETH из-за MIN_FROM_BALANCE ({min_balance_random} ETH).")
            return value, gas

        send_amount, gas = get_send_amount(balance, percent, w3, from_acc.address, intermediary_acc.address, gas_price, w3.eth.chain_id, from_priv)

        if send_amount == 0:
            print(Fore.YELLOW + f"Транзакция from -> intermediary пропущена, так как value = 0.")
            return

        tx = {
            'type': 0x2,
            'from': Web3.to_checksum_address(from_acc.address),
            'to': Web3.to_checksum_address(intermediary_acc.address),
            'value': send_amount,
            'gas': gas,
            'nonce': nonce_from,
            'chainId': w3.eth.chain_id,
            'maxFeePerGas': int(gas_price * 1.2),
            'maxPriorityFeePerGas': 0
        }

        tx_hash = None
        for attempt in range(TX_SEND_ATTEMPTS):
            try:
                signed_tx = w3.eth.account.sign_transaction(tx, from_priv)
                print(Fore.BLUE + f"[{dt_str}] Отправка from -> intermediary...")
                tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                print(Fore.YELLOW + f"✅ Успешно отправлено from -> intermediary. Tx hash: {w3.to_hex(tx_hash)}")
                break
            except Exception as e:
                print(Fore.RED + f"❌ Ошибка отправки from -> intermediary (попытка {attempt+1}): {e}")
                tx['nonce'] += 1
                time.sleep(3)
        else:
            print(Fore.RED + "❌ Не удалось отправить транзакцию from -> intermediary после нескольких попыток.")

        print(Fore.BLUE + "Ожидание подтверждения транзакции from -> intermediary...")
        time.sleep(WHAITE_TRANSACTION_PENDING)  
        for attempt in range(WHAITE_TRANSACTION_PENDING_COUNT):
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                if receipt and receipt.status == 1:
                    print(Fore.GREEN + f"✅ Транзакция подтверждена. Tx hash: {w3.to_hex(tx_hash)}")
                    break
                elif receipt and receipt.status == 0:
                    print(Fore.RED + f"❌ Транзакция неуспешна. Tx hash: {w3.to_hex(tx_hash)}")
                    break
            except Exception as e:
                print(Fore.YELLOW + f"⏳ Транзакция в ожидании (попытка {attempt+1}/{WHAITE_TRANSACTION_PENDING_COUNT}): {e}")
            time.sleep(WHAITE_TRANSACTION_PENDING)
        else:
            print(Fore.RED + f"❌ Транзакция from -> intermediary остается в состоянии pending после {WHAITE_TRANSACTION_PENDING_COUNT} попыток.")

        interm_balance = get_eth_balance_safe(w3, intermediary_acc.address)
        if interm_balance <= 0:
            print(Fore.RED + f"Баланс {intermediary_acc.address} = {interm_balance}, пропуск транзакции intermediary -> to.")
            return

        nonce_intermediary = get_nonce_safe(w3, intermediary_acc.address)
        if nonce_intermediary is None:
            print(Fore.RED + f"Не удалось получить nonce для {intermediary_acc.address}, пропуск")
            return

        def get_send_amount2(balance, w3, from_addr, to_addr, gas_price, chain_id, priv_key):
            value = balance
            tx = {
                'type': 0x2,
                'from': Web3.to_checksum_address(from_addr),
                'to': Web3.to_checksum_address(to_addr),
                'value': value,
                'gas': 1000000,
                'nonce': nonce_intermediary,
                'chainId': chain_id,
                'maxFeePerGas': int(gas_price * 1.2),
                'maxPriorityFeePerGas': 0
            }
            estimated_gas = w3.eth.estimate_gas(tx)
            gas = int(estimated_gas * 1.2)
            fee = gas * int(gas_price * 1.2)
            if value > balance - fee:
                value = balance - fee
            if value < 0:
                value = 0
            return value, gas

        send_amount2, gas2 = get_send_amount2(interm_balance, w3, intermediary_acc.address, to_acc.address, gas_price, w3.eth.chain_id, intermediary_priv)

        if send_amount2 == 0:
            print(Fore.YELLOW + f"Транзакция intermediary -> to пропущена, так как value = 0.")
            return

        tx2 = {
            'type': 0x2,
            'from': Web3.to_checksum_address(intermediary_acc.address),
            'to': Web3.to_checksum_address(to_acc.address),
            'value': send_amount2,
            'gas': gas2,
            'nonce': nonce_intermediary,
            'chainId': w3.eth.chain_id,
            'maxFeePerGas': int(gas_price * 1.2),
            'maxPriorityFeePerGas': 0
        }

        tx_hash2 = None
        for attempt in range(TX_SEND_ATTEMPTS):
            try:
                signed_tx2 = w3.eth.account.sign_transaction(tx2, intermediary_priv)
                print(Fore.BLUE + f"[{dt_str}] Отправка intermediary -> to...")
                tx_hash2 = w3.eth.send_raw_transaction(signed_tx2.rawTransaction)
                print(Fore.YELLOW + f"✅ Успешно отправлено intermediary -> to. Tx hash: {w3.to_hex(tx_hash2)}")
                break
            except Exception as e:
                print(Fore.RED + f"❌ Ошибка отправки intermediary -> to (попытка {attempt+1}): {e}")
                tx2['nonce'] += 1
                time.sleep(3)
        else:
            print(Fore.RED + "❌ Не удалось отправить транзакцию intermediary -> to после нескольких попытов.")

        print(Fore.BLUE + "Ожидание подтверждения транзакции intermediary -> to...")
        time.sleep(WHAITE_TRANSACTION_PENDING)  
        for attempt in range(WHAITE_TRANSACTION_PENDING_COUNT):
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash2)
                if receipt and receipt.status == 1:
                    print(Fore.GREEN + f"✅ Транзакция подтверждена. Tx hash: {w3.to_hex(tx_hash2)}")
                    break
                elif receipt and receipt.status == 0:
                    print(Fore.RED + f"❌ Транзакция неуспешна. Tx hash: {w3.to_hex(tx_hash2)}")
                    break
            except Exception as e:
                print(Fore.YELLOW + f"⏳ Транзакция в ожидании (попытка {attempt+1}/{WHAITE_TRANSACTION_PENDING_COUNT}): {e}")
            time.sleep(WHAITE_TRANSACTION_PENDING)
        else:
            print(Fore.RED + f"❌ Транзакция intermediary -> to остается в состоянии pending после {WHAITE_TRANSACTION_PENDING_COUNT} попыток.")

        append_result_csv({
            "datetime": dt_str,
            "from_wallet": from_priv,
            "from_address": from_acc.address,
            "intermediary_wallet": intermediary_priv,
            "intermediary_address": intermediary_acc.address,
            "to_wallet": to_priv,
            "to_address": to_acc.address,
            "amount_sent_wei": send_amount,
            "amount_sent_eth": w3.from_wei(send_amount, 'ether'),
            "tx_hash_1": w3.to_hex(tx_hash),
            "tx_hash_2": w3.to_hex(tx_hash2),
            "explorer_link_1": f"{explorer_url}{w3.to_hex(tx_hash)}",
            "explorer_link_2": f"{explorer_url}{w3.to_hex(tx_hash2)}",
        })

        to_wallet_balance = get_eth_balance_safe(w3, to_acc.address)
        to_wallet_balance_eth = w3.from_wei(to_wallet_balance, 'ether')

        print(Fore.GREEN + "\n" + "=" * 60)
        print(Fore.CYAN + f"{explorer_url}{w3.to_hex(tx_hash)}")
        print(Fore.CYAN + f"{explorer_url}{w3.to_hex(tx_hash2)}")
        print(Fore.YELLOW + f"\nfrom_wallet ({from_acc.address}) - {w3.from_wei(send_amount, 'ether')} ETH")
        print(Fore.YELLOW + f"intermediary ({intermediary_acc.address}) - {w3.from_wei(send_amount2, 'ether')} ETH")
        print(Fore.YELLOW + f"Баланс to_wallet ({to_acc.address}) по завершению - {to_wallet_balance_eth} ETH")
        print(Fore.GREEN + "=" * 60 + "\n")

    except Exception as e:
        print(Fore.RED + f"Error: {e}")
        print(Fore.YELLOW + "Переход к следующей паре кошельков...")
    finally:
        if session:
            session.close()


def save_failed_wallet(row):
    progress_file = "db/transfer_progress.json"
    try:
        if os.path.exists(progress_file):
            with open(progress_file, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
        else:
            progress_data = {"failed_wallets": []}
        progress_data["failed_wallets"].append(row)
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, indent=2)
    except Exception as e:
        print(Fore.RED + f"Ошибка сохранения зафейленной строки: {e}")

def load_failed_wallets():
    progress_file = "db/transfer_progress.json"
    try:
        if os.path.exists(progress_file):
            with open(progress_file, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
                return progress_data.get("failed_wallets", [])
        return []
    except Exception as e:
        print(Fore.RED + f"Ошибка загрузки зафейленных строк: {e}")
        return []

def remove_failed_wallet(row):
    progress_file = "db/transfer_progress.json"
    try:
        if os.path.exists(progress_file):
            with open(progress_file, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
            progress_data["failed_wallets"] = [
                r for r in progress_data.get("failed_wallets", []) if r != row
            ]
            with open(progress_file, "w", encoding="utf-8") as f:
                json.dump(progress_data, f, indent=2)

        transfer_file = "data/transfer_token.csv"
        if os.path.exists(transfer_file):
            with open(transfer_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            with open(transfer_file, "w", encoding="utf-8") as f:
                for line in lines:
                    if not all(str(row[key]) in line for key in row):
                        f.write(line)
    except Exception as e:
        print(Fore.RED + f"Ошибка удаления строки: {e}")

def get_available_intermediary_wallets():
    """
    Получает доступные посреднические кошельки из data/one_time_intermediary.csv
    """
    try:
        intermediary_file = "data/one_time_intermediary.csv"
        available_wallets = []
        
        if not os.path.exists(intermediary_file):
            print(Fore.RED + f"Файл {intermediary_file} не найден!")
            return []
        
        with open(intermediary_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Берем только кошельки без статуса или с пустым статусом
                if not row.get('status', '').strip():
                    available_wallets.append({
                        'mnemonic': row['mnemonic'],
                        'wallet_address': row['wallet_address'],
                        'private_key': row['private_key'],
                        'status': row.get('status', '')
                    })
        
        print(Fore.CYAN + f"Найдено {len(available_wallets)} доступных посреднических кошельков")
        return available_wallets
        
    except Exception as e:
        print(Fore.RED + f"Ошибка чтения файла посредников: {e}")
        return []

def mark_intermediary_as_used(used_private_key):
    """
    Отмечает посреднический кошелек как использованный
    """
    try:
        intermediary_file = "data/one_time_intermediary.csv"
        if not os.path.exists(intermediary_file):
            return False
        
        # Читаем все данные
        rows = []
        with open(intermediary_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                if row['private_key'] == used_private_key:
                    row['status'] = 'used'
                rows.append(row)
        
        # Записываем обратно
        with open(intermediary_file, "w", encoding="utf-8", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        print(Fore.YELLOW + f"Посреднический кошелек отмечен как использованный: {used_private_key[:10]}...")
        return True
        
    except Exception as e:
        print(Fore.RED + f"Ошибка обновления статуса посреднического кошелька: {e}")
        return False

def check_wallet_balances_for_loop(transfer_data, network, proxies):
    """
    Проверяет балансы кошельков для принятия решения о продолжении цикла
    """
    print(Fore.CYAN + "🔍 Проверка балансов кошельков...")
    
    # Генерируем случайные пороговые значения
    min_from_balance = random.uniform(expected_balance_from_wallet[0], expected_balance_from_wallet[1])
    max_to_balance = random.uniform(expected_balance_to_wallet[0], expected_balance_to_wallet[1])
    
    print(Fore.CYAN + f"Проверка балансов: минимальный from_wallet = {min_from_balance:.6f} ETH, максимальный to_wallet = {max_to_balance:.6f} ETH")
    
    valid_wallets = []
    
    for row in transfer_data:
        session = None
        w3 = None
        try:
            # Создаем новую сессию для каждого кошелька
            rpc_url = get_network_rpc(network)
            proxy = random.choice(proxies) if proxies else None
            w3, session = get_web3_with_proxy(rpc_url, proxy)
            
            from_acc = Account.from_key(row['from_wallet'])
            to_acc = Account.from_key(row['to_wallet'])
            
            from_balance = get_eth_balance_safe(w3, from_acc.address)
            to_balance = get_eth_balance_safe(w3, to_acc.address)
            
            from_balance_eth = w3.from_wei(from_balance, 'ether')
            to_balance_eth = w3.from_wei(to_balance, 'ether')
            
            # Проверяем условия
            if from_balance_eth >= min_from_balance and to_balance_eth <= max_to_balance:
                valid_wallets.append(row)
                print(Fore.GREEN + f"✅  {from_acc.address[:10]}... -> {to_acc.address[:10]}... (from: {from_balance_eth:.6f}, to: {to_balance_eth:.6f})")
            else:
                print(Fore.YELLOW + f"⏭️  {from_acc.address[:10]}... -> {to_acc.address[:10]}... (from: {from_balance_eth:.6f}, to: {to_balance_eth:.6f}) - не подходит")
                
        except Exception as e:
            print(Fore.RED + f"Ошибка проверки баланса кошелька: {e}")
            continue
        finally:
            # Закрываем сессию для каждого коша после использования 
            if session:
                try:
                    session.close()
                except Exception as e:
                    print(Fore.YELLOW + f"Ошибка закрытия сессии для кошелька: {e}")
    
    return valid_wallets

def process_wallets_transfer_normal(transfer_data, proxies, network, delay_between, total_tx, progress_file=None, start_idx=0, completed_txs=0):
    """
    Обычная обработка переводов без зацикливания (оригинальная логика)
    """
    spinner_cycle = cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    bar_length = 80 
    total_wallets = len(transfer_data)

    def log_error(msg):
        print(Fore.RED + msg + Style.RESET_ALL)

    if progress_file and os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
                start_idx = progress_data.get("last_idx", 0)
                completed_txs = progress_data.get("completed_txs", 0)
                print(Fore.YELLOW + f"Восстановление с кошелька #{start_idx}, завершено транзакций: {completed_txs}...")
        except Exception as e:
            print(Fore.RED + f"Ошибка загрузки прогресса: {e}")
            start_idx = 0
            completed_txs = 0

    failed_wallets = load_failed_wallets()
    if failed_wallets:
        print(Fore.YELLOW + f"Обработка зафейленных кошельков ({len(failed_wallets)} строк)...")
        for failed_row in failed_wallets:
            proxy = random.choice(proxies) if proxies else None
            try:
                transefer_wallets_to_wallets(
                    failed_row['from_wallet'],
                    failed_row['intermediary'],
                    failed_row['to_wallet'],
                    network,
                    failed_row['amount'],
                    proxy,
                    delay_between,
                    completed_txs,
                    total_tx
                )
                remove_failed_wallet(failed_row) 
                completed_txs += 2
            except Exception as e:
                print(Fore.RED + f"Ошибка обработки зафейленного кошелька: {e}")

    for idx in range(start_idx, total_wallets):
        row = transfer_data[idx]
        proxy = random.choice(proxies) if proxies else None
        tx_counter = idx * 2

        if progress_file:
            try:
                with open(progress_file, "w", encoding="utf-8") as f:
                    json.dump({"last_idx": idx, "completed_txs": completed_txs}, f, indent=2)
            except Exception as e:
                print(Fore.RED + f"Ошибка записи прогресса: {e}")

        try:
            transefer_wallets_to_wallets(
                row['from_wallet'],
                row['intermediary'],
                row['to_wallet'],
                network,
                row['amount'],
                proxy,
                delay_between,
                tx_counter + completed_txs,
                total_tx
            )
            completed_txs += 2
        except Exception as e:
            print(Fore.RED + f"Ошибка обработки кошелька: {e}")
            save_failed_wallet(row)  

        progress = int((completed_txs / total_tx) * bar_length)
        bar = "█" * progress + "░" * (bar_length - progress)
        spinner_frame = next(spinner_cycle)

        remaining_tx = total_tx - completed_txs
        remaining_wallets = total_wallets - idx - 1
        estimated_time = remaining_tx * delay_between + remaining_wallets * 13 
        completion_time = datetime.now() + timedelta(seconds=estimated_time)
        completion_time_str = completion_time.strftime("%d.%m.%Y в %H:%M")  

        print(
            f"\r[{bar}] {completed_txs}/{total_tx} транзакций | Осталось пар: {remaining_wallets} | {spinner_frame} {Fore.CYAN}Последний:| Завершение: {completion_time_str}{Style.RESET_ALL}",
            end="",
            flush=True,
        )
        print() 

        if delay_between > 0 and idx < total_wallets - 1:
            countdown_timer(int(delay_between))
    print()  
    if progress_file and os.path.exists(progress_file):
        os.remove(progress_file)

def process_wallets_transfer(transfer_data, proxies, network, delay_between, total_tx, progress_file=None, start_idx=0, completed_txs=0):
    """
    Обработка переводов с поддержкой зацикливания
    """
    if not loop_transfer_enable:
        # Обычный режим работы без зацикливания
        return process_wallets_transfer_normal(transfer_data, proxies, network, delay_between, total_tx, progress_file, start_idx, completed_txs)
    
    # Режим с зацикливанием
    print(Fore.MAGENTA + f"🔄 Включен режим зацикливания. Максимум циклов: {loop_transfer_count}")
    
    cycle = 0
    while cycle < loop_transfer_count:
        cycle += 1
        print(Fore.MAGENTA + f"\n{'='*60}")
        print(Fore.YELLOW + f"🔄 ЦИКЛ {cycle}/{loop_transfer_count}")
        print(Fore.MAGENTA + f"{'='*60}")
        
        # Проверяем доступность посреднических кошельков
        available_intermediaries = get_available_intermediary_wallets()
        if not available_intermediaries:
            print(Fore.RED + "❌ Нет доступных кошельков для роли посредника!")
            print(Fore.YELLOW + "Остановка выполнения переводов.")
            break
        
        # Проверяем балансы кошельков
        print(Fore.CYAN + "🔍 Проверка балансов кошельков...")
        valid_wallets = check_wallet_balances_for_loop(transfer_data, network, proxies)
        
        if not valid_wallets:
            local_sleep_time_between_loops = random.randint(sleep_time_between_loops[0], sleep_time_between_loops[1])
            completion_time = datetime.now() + timedelta(seconds=local_sleep_time_between_loops)
            completion_time_str = completion_time.strftime("%d.%m.%Y в %H:%M:%S")
            current_time_str = datetime.now().strftime("%d.%m.%Y в %H:%M:%S")
            print(Fore.YELLOW + f"⏭️ Цикл {cycle}: Нет кошельков, подходящих под условия.")
            print(Fore.YELLOW + f"⏰ Текущее время: {current_time_str}")
            print(Fore.YELLOW + f"🔄 Следующий запуск: {completion_time_str} (через {local_sleep_time_between_loops} секунд)")
            time.sleep(local_sleep_time_between_loops)
            continue
        
        print(Fore.GREEN + f"✅ Найдено {len(valid_wallets)} подходящих пар кошельков")
        
        # Проверяем, хватает ли посредников
        if len(available_intermediaries) < len(valid_wallets):
            print(Fore.YELLOW + f"⚠️ Доступно только {len(available_intermediaries)} посредников для {len(valid_wallets)} пар")
            valid_wallets = valid_wallets[:len(available_intermediaries)]
        
        # Обрабатываем ВСЕ найденные кошельки сразу
        current_total_tx = len(valid_wallets) * 2
        process_wallets_transfer_with_one_time_intermediaries(valid_wallets, available_intermediaries, proxies, network, delay_between, current_total_tx)
        
        print(Fore.GREEN + f"✅ Цикл {cycle} завершен. Обработано {len(valid_wallets)} пар кошельков")
        
        # Пауза между циклами (кроме последнего)
        if cycle < loop_transfer_count:
            local_sleep_time_between_loops = random.randint(sleep_time_between_loops[0], sleep_time_between_loops[1])
            print(Fore.CYAN + f"⏸️ Пауза между циклами {local_sleep_time_between_loops} секунд...")
            countdown_timer(local_sleep_time_between_loops, "Пауза между циклами")

    if cycle >= loop_transfer_count: 
        print(Fore.GREEN + f"🎉 Все {loop_transfer_count} циклов завершены!")
    else:
        print(Fore.RED + f"❌ Завершены не все циклы, выполнено - {cycle} из {loop_transfer_count} циклов.")

def process_wallets_transfer_with_one_time_intermediaries(valid_wallets, available_intermediaries, proxies, network, delay_between, total_tx):
    """
    Обработка переводов с использованием одноразовых посредников
    """
    if not valid_wallets:
        return
        
    print(Fore.MAGENTA + f"\n🚀 Начинаем обработку {len(valid_wallets)} подходящих пар кошельков")
    
    spinner_cycle = cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    bar_length = 80
    completed_txs = 0
    
    for idx, row in enumerate(valid_wallets):
        if idx >= len(available_intermediaries):
            print(Fore.RED + f"❌ Недостаточно посредников для обработки всех кошельков")
            break
        
        # Берем случайного посредника из доступных
        intermediary = random.choice(available_intermediaries)
        available_intermediaries.remove(intermediary)  # Убираем из списка доступных
        
        proxy = random.choice(proxies) if proxies else None
        tx_counter = idx * 2
        
        print(Fore.CYAN + f"\n📋 Обработка пары {idx + 1}/{len(valid_wallets)}")
        
        try:
            # Используем одноразового посредника вместо того, что в файле transfer_data
            transefer_wallets_to_wallets(
                row['from_wallet'],
                intermediary['private_key'],  # Используем посредника из one_time_intermediary.csv
                row['to_wallet'],
                network,
                row['amount'],
                proxy,
                delay_between,
                tx_counter + completed_txs,
                total_tx
            )
            
            # Отмечаем посредника как использованного
            mark_intermediary_as_used(intermediary['private_key'])
            
            completed_txs += 2
            
        except Exception as e:
            print(Fore.RED + f"Ошибка обработки кошелька: {e}")
            # Даже при ошибке отмечаем посредника как использованного
            mark_intermediary_as_used(intermediary['private_key'])
        
        # Обновляем прогресс
        progress = int((completed_txs / total_tx) * bar_length)
        bar = "█" * progress + "░" * (bar_length - progress)
        spinner_frame = next(spinner_cycle)
        
        remaining_tx = total_tx - completed_txs
        remaining_wallets = len(valid_wallets) - idx - 1
        estimated_time = remaining_tx * delay_between + remaining_wallets * 13
        completion_time = datetime.now() + timedelta(seconds=estimated_time)
        completion_time_str = completion_time.strftime("%d.%m.%Y в %H:%M")
        
        print(
            f"\r[{bar}] {completed_txs}/{total_tx} транзакций | Осталось пар: {remaining_wallets} | {spinner_frame} {Fore.CYAN}Посредник: {intermediary['wallet_address'][:10]}...| Завершение: {completion_time_str}{Style.RESET_ALL}",
            end="",
            flush=True,
        )
        print()
        
        # Задержка между парами кошельков (кроме последней)
        if delay_between > 0 and idx < len(valid_wallets) - 1:
            countdown_timer(int(delay_between), "Задержка до следующей пары")
    
    print(Fore.GREEN + f"\n✅ Завершена обработка всех {len(valid_wallets)} подходящих пар в текущем цикле")