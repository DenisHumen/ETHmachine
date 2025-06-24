import random
# from decimal import Decimal  # Not used
from web3 import Web3
from eth_account import Account
from colorama import Fore
import time
from datetime import datetime, timedelta
import csv
from config.config import TX_SEND_ATTEMPTS, WHAITE_TRANSACTION_PENDING, WHAITE_TRANSACTION_PENDING_COUNT, expected_completion_time, MIN_FROM_BALANCE
# from config.config import MIN_FROM_BALANCE  # Not used
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
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
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
    # import requests  # Not used
    #from web3.middleware import geth_poa_middleware

    # Для web3==5.31.4: используем environment переменные для прокси (гарантированно работает)
    import os
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url

    provider = HTTPProvider(rpc_url)
    w3 = Web3(provider)
    #w3.middleware_onion.inject(geth_poa_middleware, layer=0)
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
        '🚀 Somnia Testnet': "https://shannon-explorer.somnia.network/tx/",
        '🚀 Mega ETH': "https://www.oklink.com/ru/megaeth-testnet/tx/",
        '🚀 Pharos': "https://testnet.pharosscan.xyz/tx/",
    }
    return explorers.get(network, "https://www.megaexplorer.xyz/tx/")

def countdown_timer(seconds, message_prefix="Пауза"):
    for remaining in range(seconds, 0, -1):
        print(
            f"\r{Fore.YELLOW}{message_prefix} {remaining} сек до следующей транзакции...{Style.RESET_ALL} ",
            end="",
            flush=True,
        )
        time.sleep(1)
    print("\r" + " " * 80 + "\r", end="")  # Очистить строку

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
        print("\r" + " " * 60 + "\r", end="")  # Очистить строку

def get_eth_balance_safe(w3, address, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    for attempt in range(max_attempts):
        try:
            balance = w3.eth.get_balance(address)
            if balance >= 0:  # Убедимся, что баланс корректно получен (>= 0)
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
    try:
        start_time = time.time()
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

        # Получаем explorer url
        explorer_url = get_explorer_url(network)

        # Получаем аккаунты
        try:
            from_acc = Account.from_key(from_priv)
            intermediary_acc = Account.from_key(intermediary_priv)
            to_acc = Account.from_key(to_priv)
        except Exception as e:
            print(Fore.RED + f"Ошибка создания аккаунта: {e}")
            return

        # Получаем баланс отправителя (safe)
        for attempt in range(TX_SEND_ATTEMPTS):
            balance = get_eth_balance_safe(w3, from_acc.address)
            if balance > 0:
                break
            print(Fore.YELLOW + f"Попытка {attempt+1}/{TX_SEND_ATTEMPTS}: Баланс {from_acc.address} = 0, ждем 3 сек...")
            time.sleep(3)
        else:
            print(Fore.RED + f"Баланс {from_acc.address} = 0 после {TX_SEND_ATTEMPTS} попыток, пропуск")
            return

        # Получаем процент для отправки
        percent_from, percent_to = parse_percent_range(amount)
        percent = random.randint(percent_from, percent_to)

        # Получаем текущую цену газа
        try:
            gas_price = w3.eth.gas_price
        except Exception as e:
            print(Fore.YELLOW + f"Ошибка получения цены газа: {e}")
            gas_price = int(w3.to_wei('30', 'gwei'))  # fallback

        # Получаем nonce для отправителя
        nonce_from = get_nonce_safe(w3, from_acc.address)
        if nonce_from is None:
            print(Fore.RED + f"Не удалось получить nonce для {from_acc.address}, пропуск")
            return

        # Считаем сумму для отправки (percent% от баланса минус комиссия)
        # Сначала считаем максимально возможную сумму с учетом комиссии и MIN_FROM_BALANCE
        def get_send_amount(balance, percent, w3, from_addr, to_addr, gas_price, chain_id, priv_key):
            # Вычисляем сумму для отправки с учетом процента, комиссии и MIN_FROM_BALANCE
            value = int(balance * percent / 100)
            # Формируем tx для оценки газа
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
            # Проверяем, хватает ли баланса с учетом MIN_FROM_BALANCE
            min_balance_wei = w3.to_wei(MIN_FROM_BALANCE, 'ether')
            if value + fee > balance - min_balance_wei:
                value = balance - fee - min_balance_wei
            if value < 0:
                value = 0
            return value, gas

        send_amount, gas = get_send_amount(balance, percent, w3, from_acc.address, intermediary_acc.address, gas_price, w3.eth.chain_id, from_priv)

        # Формируем транзакцию from -> intermediary (с учетом новой схемы)
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

        # Отправка транзакции from -> intermediary
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

        # Ожидание подтверждения транзакции from -> intermediary
        print(Fore.BLUE + "Ожидание подтверждения транзакции from -> intermediary...")
        time.sleep(WHAITE_TRANSACTION_PENDING)  # Пауза перед первой проверкой
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

        # Проверка баланса intermediary
        interm_balance = get_eth_balance_safe(w3, intermediary_acc.address)
        if interm_balance <= 0:
            print(Fore.RED + f"Баланс {intermediary_acc.address} = {interm_balance}, пропуск транзакции intermediary -> to.")
            return

        # Получаем nonce для intermediary
        nonce_intermediary = get_nonce_safe(w3, intermediary_acc.address)
        if nonce_intermediary is None:
            print(Fore.RED + f"Не удалось получить nonce для {intermediary_acc.address}, пропуск")
            return

        # Формируем транзакцию intermediary -> to (100% баланса минус комиссия)
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

        # Ожидание подтверждения транзакции intermediary -> to
        print(Fore.BLUE + "Ожидание подтверждения транзакции intermediary -> to...")
        time.sleep(WHAITE_TRANSACTION_PENDING)  # Пауза перед первой проверкой
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

        # Запись результата
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

        elapsed_time = time.time() - start_time
        print(Fore.GREEN + "\n" + "=" * 60)
        print(Fore.CYAN + f"{explorer_url}{w3.to_hex(tx_hash)}")
        print(Fore.CYAN + f"{explorer_url}{w3.to_hex(tx_hash2)}")
        print(Fore.GREEN + "=" * 60 + "\n")

    except Exception as e:
        print(Fore.RED + f"Error: {e}")
        print(Fore.YELLOW + "Переход к следующей паре кошельков...")

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
    bar_length = 80  # Увеличена ширина прогресс-бара
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

        # Рассчитываем примерное время завершения
        remaining_tx = total_tx - completed_txs
        remaining_wallets = total_wallets - idx - 1
        estimated_time = remaining_tx * delay_between
        completion_time = datetime.now() + timedelta(seconds=estimated_time)
        completion_time_str = completion_time.strftime("%H:%M:%S")

        # Вывод прогресс-бара
        print(
            f"\r[{bar}] {completed_txs}/{total_tx} транзакций | Осталось пар: {remaining_wallets} | {spinner_frame} | {Fore.CYAN}Последний: {row['from_wallet'][:8]}... | Завершение: {completion_time_str}{Style.RESET_ALL}",
            end="",
            flush=True,
        )

        # Ожидание между транзакциями
        if delay_between > 0 and idx < total_wallets - 1:
            countdown_timer(int(delay_between))
    print()  # Перевод строки после прогресса
    # Удаляем прогресс-файл после завершения
    if progress_file and os.path.exists(progress_file):
        os.remove(progress_file)