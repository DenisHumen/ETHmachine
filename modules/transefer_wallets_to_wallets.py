import random
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from colorama import Fore
import time
from datetime import datetime
import csv
from config.config import TX_SEND_ATTEMPTS

def parse_percent_range(percent_str):
    # Преобразует строку вида "30-50" в кортеж (30, 50)
    try:
        parts = percent_str.split('-')
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        else:
            val = int(parts[0])
            return val, val
    except Exception:
        return 100, 100  # fallback

def get_network_rpc(network):
    # Импортируем rpc из config.rpc
    from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium, Polygon, Binance_Smart_Chain, Avalanche, Fantom, Gravity_Alpha_Mainnet, monad_testnet, sahara_testnet, zora, somnia_testnet, mega_eth, Abstract
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
        '🚀 Mega ETH': mega_eth,
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
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_hash_hex = w3.to_hex(tx_hash)
            print(Fore.GREEN + f"Попытка {attempt}: Транзакция отправлена: {tx_hash_hex}")
            print(Fore.CYAN + f"Ссылка: {explorer_url}{tx_hash_hex}")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt and receipt.status == 1:
                print(Fore.GREEN + f"Транзакция подтверждена и успешна: {tx_hash_hex}")
                print(Fore.CYAN + f"Explorer: {explorer_url}{tx_hash_hex}")
                return True, tx_hash_hex
            else:
                print(Fore.RED + f"Транзакция неуспешна (статус != 1): {tx_hash_hex}")
        except Exception as e:
            print(Fore.RED + f"Ошибка отправки/подтверждения транзакции (попытка {attempt}): {e}")
        time.sleep(5)
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

def transefer_wallets_to_wallets(from_priv, intermediary_priv, to_priv, network, amount):
    dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(Fore.MAGENTA + "\n" + "="*60)
    print(Fore.YELLOW + f"[{dt_str}] Запуск цепочки перевода:")
    print(Fore.CYAN + f"  FROM:        {from_priv[:10]}... ")
    print(Fore.CYAN + f"  INTERMEDIARY:{intermediary_priv[:10]}... ")
    print(Fore.CYAN + f"  TO:          {to_priv[:10]}... ")
    print(Fore.CYAN + f"  Сеть:        {network}")
    print(Fore.CYAN + f"  Процент:     {amount}%")
    print(Fore.MAGENTA + "-"*60)

    # Получаем RPC для выбранной сети
    rpc_url = get_network_rpc(network)
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    # Получаем аккаунты
    try:
        from_acc = Account.from_key(from_priv)
        intermediary_acc = Account.from_key(intermediary_priv)
        to_acc = Account.from_key(to_priv)
    except Exception as e:
        print(Fore.RED + f"Ошибка создания аккаунта: {e}")
        return

    # Получаем баланс отправителя
    balance = get_eth_balance(w3, from_acc.address)
    if balance == 0:
        print(Fore.RED + f"Баланс {from_acc.address} = 0, пропуск")
        return

    # Получаем процент для отправки
    percent_from, percent_to = parse_percent_range(amount)
    percent = random.randint(percent_from, percent_to)

    # Получаем текущую цену газа
    try:
        gas_price = w3.eth.gas_price
        gas_price = int(gas_price * 1.2)  # +20% для ускорения
    except Exception as e:
        print(Fore.YELLOW + f"Ошибка получения цены газа: {e}")
        gas_price = int(w3.to_wei('30', 'gwei'))  # fallback

    # Оцениваем газ для простой отправки
    tx = {
        'from': from_acc.address,
        'to': intermediary_acc.address,
        'value': 0,  # позже подставим
        'gas': 21000,
        'gasPrice': gas_price,
        'nonce': w3.eth.get_transaction_count(from_acc.address),
        'chainId': w3.eth.chain_id
    }
    gas_limit = estimate_gas_with_margin(w3, tx)
    total_gas_fee = gas_limit * gas_price

    # Считаем сумму для отправки
    send_amount = int((balance - total_gas_fee) * percent / 100)
    if send_amount <= 0:
        print(Fore.RED + f"Недостаточно баланса для покрытия комиссии. Баланс: {w3.from_wei(balance, 'ether')}, комиссия: {w3.from_wei(total_gas_fee, 'ether')}")
        return

    explorer_url = "https://www.megaexplorer.xyz/tx/"
    tx_hash_hex = None
    tx_hash2_hex = None
    amount_sent_wei = 0
    amount_sent_eth = 0

    # Формируем и отправляем транзакцию from -> intermediary
    tx['value'] = send_amount
    tx['gas'] = gas_limit
    try:
        signed_tx = w3.eth.account.sign_transaction(tx, from_priv)
        print(Fore.BLUE + f"[{dt_str}] Отправка from -> intermediary...")
        success, tx_hash_hex = send_with_retry(w3, signed_tx, explorer_url)
        if not success:
            print(Fore.RED + "❌ Не удалось выполнить первую транзакцию. Пропуск.")
            print(Fore.MAGENTA + "="*60)
            return
        else:
            print(Fore.GREEN + f"✅ Успешно отправлено from -> intermediary.")
    except Exception as e:
        print(Fore.RED + f"Ошибка отправки from -> intermediary: {e}")
        print(Fore.MAGENTA + "="*60)
        return

    # Теперь отправляем с intermediary -> to
    interm_balance = 0
    for _ in range(20):
        interm_balance = get_eth_balance(w3, intermediary_acc.address)
        if interm_balance > 0:
            break
        time.sleep(3)
    else:
        print(Fore.RED + f"Баланс intermediary не пополнен, пропуск. Текущий баланс: {w3.from_wei(interm_balance, 'ether')}")
        print(Fore.MAGENTA + "="*60)
        return

    nonce = w3.eth.get_transaction_count(intermediary_acc.address)
    min_value_wei = w3.to_wei('0.000001', 'ether')
    value_to_send = interm_balance

    while value_to_send > min_value_wei:
        try:
            tx2_gas_limit = w3.eth.estimate_gas({
                'from': intermediary_acc.address,
                'to': to_acc.address,
                'value': value_to_send,
                'gasPrice': gas_price,
                'nonce': nonce,
                'chainId': w3.eth.chain_id
            })
            tx2_total_gas_fee = tx2_gas_limit * gas_price
            if value_to_send + tx2_total_gas_fee <= interm_balance:
                break
            else:
                value_to_send = interm_balance - tx2_total_gas_fee
        except Exception:
            value_to_send -= w3.to_wei('0.000001', 'ether')
    else:
        print(Fore.RED + f"Недостаточно баланса intermediary для покрытия комиссии. Баланс: {w3.from_wei(interm_balance, 'ether')}")
        print(Fore.MAGENTA + "="*60)
        return

    if value_to_send < min_value_wei:
        print(Fore.RED + f"Слишком маленькая сумма для отправки: {w3.from_wei(value_to_send, 'ether')} ETH")
        print(Fore.MAGENTA + "="*60)
        return

    try:
        tx2_gas_limit = w3.eth.estimate_gas({
            'from': intermediary_acc.address,
            'to': to_acc.address,
            'value': value_to_send,
            'gasPrice': gas_price,
            'nonce': nonce,
            'chainId': w3.eth.chain_id
        })
    except Exception as e:
        print(Fore.RED + f"Не удалось оценить газ для второй транзакции: {e}")
        print(Fore.MAGENTA + "="*60)
        return

    tx2 = {
        'from': intermediary_acc.address,
        'to': to_acc.address,
        'value': value_to_send,
        'gas': tx2_gas_limit,
        'gasPrice': gas_price,
        'nonce': nonce,
        'chainId': w3.eth.chain_id
    }
    try:
        signed_tx2 = w3.eth.account.sign_transaction(tx2, intermediary_priv)
        print(Fore.BLUE + f"[{dt_str}] Отправка intermediary -> to...")
        success2, tx_hash2_hex = send_with_retry(w3, signed_tx2, explorer_url)
        if not success2:
            print(Fore.RED + "❌ Не удалось выполнить вторую транзакцию.")
            print(Fore.MAGENTA + "="*60)
            return
        else:
            print(Fore.GREEN + f"✅ Успешно отправлено intermediary -> to.")
            amount_sent_wei = value_to_send
            amount_sent_eth = w3.from_wei(value_to_send, 'ether')
    except Exception as e:
        print(Fore.RED + f"Ошибка отправки intermediary -> to: {e}")
        print(Fore.MAGENTA + "="*60)
        return

    # Запись результата
    append_result_csv({
        "datetime": dt_str,
        "from_wallet": from_priv,
        "from_address": from_acc.address,
        "intermediary_wallet": intermediary_priv,
        "intermediary_address": intermediary_acc.address,
        "to_wallet": to_priv,
        "to_address": to_acc.address,
        "amount_sent_wei": amount_sent_wei,
        "amount_sent_eth": amount_sent_eth,
        "tx_hash_1": tx_hash_hex,
        "tx_hash_2": tx_hash2_hex,
        "explorer_link_1": f"{explorer_url}{tx_hash_hex}" if tx_hash_hex else "",
        "explorer_link_2": f"{explorer_url}{tx_hash2_hex}" if tx_hash2_hex else "",
    })

    print(Fore.GREEN + f"\n[{dt_str}] ✅ Операция завершена успешно.")
    print(Fore.YELLOW + f"  Отправлено: {amount_sent_eth} ETH ({amount_sent_wei} wei)")
    print(Fore.YELLOW + f"  TX1: {tx_hash_hex} | {explorer_url}{tx_hash_hex}")
    print(Fore.YELLOW + f"  TX2: {tx_hash2_hex} | {explorer_url}{tx_hash2_hex}")
    print(Fore.MAGENTA + "="*60)