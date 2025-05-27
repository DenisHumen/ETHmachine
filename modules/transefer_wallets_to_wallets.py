import random
from decimal import Decimal
from web3 import Web3
from eth_account import Account
from colorama import Fore
import time
from datetime import datetime
import csv
from config.config import TX_SEND_ATTEMPTS
from itertools import cycle
from colorama import Style
import json
import os

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
            #print(Fore.GREEN + f"Попытка {attempt}: Транзакция отправлена: {tx_hash_hex}")
            print(Fore.LIGHTBLUE_EX + Style.BRIGHT + f"🔗 Посмотреть транзакцию: {explorer_url}{tx_hash_hex}" + Style.RESET_ALL)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt and receipt.status == 1:
                #print(Fore.GREEN + f"Транзакция подтверждена и успешна: {tx_hash_hex}")
                #print(Fore.CYAN + f"Explorer: {explorer_url}{tx_hash_hex}")
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

def get_proxy_list():
    proxies = []
    try:
        with open("data/proxy.csv", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.lower().startswith("proxy"):
                    continue
                if not line.startswith("http://"):
                    line = "http://" + line
                proxies.append(line)
    except Exception as e:
        print(Fore.YELLOW + f"Не удалось загрузить прокси: {e}")
    if not proxies:
        print(Fore.RED + "ВНИМАНИЕ: В файле data/proxy.csv не найдено ни одного прокси!")
        input(Fore.YELLOW + "Добавьте прокси в файл data/proxy.csv и нажмите Enter для продолжения, либо Ctrl+C для выхода...")
    return proxies

def get_web3_with_proxy(rpc_url, proxy_url):
    from web3 import HTTPProvider
    import requests
    from web3.middleware import geth_poa_middleware

    # Для web3==5.31.4: используем environment переменные для прокси (гарантированно работает)
    import os
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url

    provider = HTTPProvider(rpc_url)
    w3 = Web3(provider)
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    # Проверка: пробуем сделать запрос и вывести IP (опционально)
    try:
        # Проверяем, что web3 работает (например, получаем chain_id)
        _ = w3.eth.chain_id
    except Exception as e:
        print(Fore.RED + f"ВНИМАНИЕ: Прокси не применился к web3 или RPC недоступен через этот прокси: {e}")
    return w3

def get_explorer_url(network):
    # Возвращает explorer url для выбранной сети
    explorers = {
        '🚀 Ethereum Mainnet': "https://etherscan.io/tx/",
        '🚀 Base': "https://basescan.org/tx/",
        '🚀 Arbitrum One': "https://arbiscan.io/tx/",
        '🚀 Optimism': "https://optimistic.etherscan.io/tx/",
        '🚀 Soneium': "https://soneium.blockscout.com/tx/",
        '🚀 Polygon': "https://polygonscan.com/tx/",
        '🚀 Binance Smart Chain': "https://bscscan.com/tx/",
        '🚀 Avalanche': "https://subnets.avax.network/p-chain/tx/",
        '🚀 Fantom': "https://explorer.fantom.network/transactions/",
        '🚀 Gravity Alpha Mainnet': "https://explorer.gravity.xyz/tx/",
        '🚀 Zora': "https://explorer.zora.energy/tx/",
        '🚀 Abstract': "https://explorer.testnet.abs.xyz/tx/",
        '🚀 Sepolia': "https://sepolia.etherscan.io/tx/",
        '🚀 Monad Testnet (native token MON)': "https://testnet.monvision.io/tx/",
        '🚀 Sahara testnet': "https://testnet-explorer.saharalabs.ai/tx/",
        '🚀 Somnia Testnet': None,
        '🚀 Mega ETH': "https://www.oklink.com/ru/megaeth-testnet/tx/",
    }
    return explorers.get(network, "https://www.megaexplorer.xyz/tx/")

def countdown_timer(seconds, message_prefix="Пауза"):
    for remaining in range(seconds, 0, -1):
        print(
            f"\r{Fore.YELLOW}{message_prefix} {remaining} сек до следующей транзакции для равномерного распределения...{Style.RESET_ALL} ",
            end="",
            flush=True,
        )
        time.sleep(1)
    print("\r" + " " * 80 + "\r", end="")  # Очистить строку

def transefer_wallets_to_wallets(from_priv, intermediary_priv, to_priv, network, amount, proxy=None, delay_between=0, tx_counter=0, total_tx=1):
    dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Получаем RPC для выбранной сети
    rpc_url = get_network_rpc(network)
    proxies = get_proxy_list()
    use_proxy = None
    if proxy:
        use_proxy = proxy
    elif proxies:
        use_proxy = random.choice(proxies)

    print(Fore.MAGENTA + "\n" + "="*60)
    print(Fore.YELLOW + f"[{dt_str}] Запуск цепочки перевода:")
    print(Fore.CYAN + f"  FROM:        {from_priv[:10]}... ")
    print(Fore.CYAN + f"  INTERMEDIARY:{intermediary_priv[:10]}... ")
    print(Fore.CYAN + f"  TO:          {to_priv[:10]}... ")
    print(Fore.CYAN + f"  Сеть:        {network}")
    print(Fore.CYAN + f"  Процент:     {amount}%")
    if use_proxy:
        print(Fore.CYAN + f"  Используется прокси: {use_proxy}")
    else:
        print(Fore.RED + "  Нет доступных прокси! Работа невозможна.")
        input(Fore.YELLOW + "Добавьте прокси в файл data/proxy.csv и нажмите Enter для продолжения, либо Ctrl+C для выхода...")
        return
    print(Fore.MAGENTA + "-"*60)

    # --- Web3 только через прокси ---
    w3 = get_web3_with_proxy(rpc_url, use_proxy)

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

    explorer_url = get_explorer_url(network)
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

    # Пауза между транзакциями (если это не последняя транзакция)
    if delay_between > 0 and tx_counter < total_tx - 1:
        countdown_timer(int(delay_between))
    tx_counter += 1

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

    # Пауза между транзакциями (если это не последняя транзакция)
    if delay_between > 0 and tx_counter < total_tx - 1:
        countdown_timer(int(delay_between))

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
        "explorer_link_1": f"{explorer_url}{tx_hash_hex}" if tx_hash_hex and explorer_url else "",
        "explorer_link_2": f"{explorer_url}{tx_hash2_hex}" if tx_hash2_hex and explorer_url else "",
    })

    print(Fore.GREEN + f"\n[{dt_str}] ✅ Операция завершена успешно.")
    print(Fore.YELLOW + f"  Отправлено: {amount_sent_eth} ETH ({amount_sent_wei} wei)")
    print(Fore.YELLOW + f"  TX1: {tx_hash_hex} | {explorer_url}{tx_hash_hex if tx_hash_hex and explorer_url else ''}")
    print(Fore.YELLOW + f"  TX2: {tx_hash2_hex} | {explorer_url}{tx_hash2_hex if tx_hash2_hex and explorer_url else ''}")
    print(Fore.MAGENTA + "="*60)

def process_wallets_transfer(transfer_data, proxies, network, delay_between, total_tx, progress_file=None, start_idx=0, completed_txs=0):
    """
    transfer_data: список словарей с ключами from_wallet, intermediary, to_wallet, amount
    proxies: список прокси (или None)
    network: выбранная сеть
    delay_between: пауза между транзакциями (сек)
    total_tx: общее количество транзакций (from->intermediary + intermediary->to)
    progress_file: путь к файлу прогресса
    start_idx: с какого индекса начинать
    completed_txs: сколько транзакций уже завершено
    """
    spinner_cycle = cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    bar_length = 40
    total_wallets = len(transfer_data)

    def log_error(msg):
        print(Fore.RED + msg + Style.RESET_ALL)

    for idx in range(start_idx, total_wallets):
        row = transfer_data[idx]
        proxy = None
        if proxies:
            if len(proxies) == total_wallets:
                proxy = proxies[idx]
            else:
                proxy = random.choice(proxies)
        tx_counter = idx * 2
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
        progress = int((completed_txs / total_tx) * bar_length)
        bar = "█" * progress + "░" * (bar_length - progress)
        spinner_frame = next(spinner_cycle)
        print(
            f"\r[{bar}] {completed_txs}/{total_tx} | {spinner_frame} | {Fore.CYAN}Последний: {row['from_wallet'][:8]}...{Style.RESET_ALL}",
            end="",
            flush=True,
        )
        # Сохраняем прогресс после каждой цепочки
        if progress_file:
            try:
                with open(progress_file, "w", encoding="utf-8") as pf:
                    json.dump({"last_idx": idx + 1, "completed_txs": completed_txs}, pf)
            except Exception as e:
                log_error(f"Ошибка сохранения прогресса: {e}")
        # Добавлено: задержка между цепочками (кроме последней)
        if delay_between > 0 and idx < total_wallets - 1:
            countdown_timer(int(delay_between))
    print()  # Перевод строки после прогресса
    # Удаляем прогресс-файл после завершения
    if progress_file and os.path.exists(progress_file):
        os.remove(progress_file)