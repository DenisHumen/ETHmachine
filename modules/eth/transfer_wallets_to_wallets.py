import random
from web3 import Web3
from eth_account import Account
from colorama import Fore
import time
from datetime import datetime, timedelta
import csv
import sys
from pathlib import Path
from itertools import cycle
from colorama import Style
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger

# Настройка путей для импорта
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import TX_SEND_ATTEMPTS, WHAITE_TRANSACTION_PENDING, WHAITE_TRANSACTION_PENDING_COUNT, expected_completion_time, MIN_FROM_BALANCE, trim_the_number_of_characters_enable, trim_the_number_of_characters, loop_transfer_enable, loop_transfer_count, expected_balance_from_wallet, expected_balance_to_wallet, sleep_time_between_loops, USE_INTERMEDIARY, TYPE_VALUE_TO_WALLET, TELEGRAM_LOG_LEVEL_transfer, MULTI_THREADING, NUM_THREADS
from config.explorer_url import get_explorer_url
from modules.notifications import send_telegram_notification, send_telegram_file

# Глобальная статистика
TRANSFER_STATS = {
    "start_time": None,
    "end_time": None,
    "total_transactions_attempted": 0,
    "total_transactions_success": 0,
    "total_transactions_failed": 0,
    "total_amount_transferred_wei": 0,
    "total_amount_transferred_eth": 0,
    "wallets_processed": 0,
    "wallets_failed": 0,
    "cycles_completed": 0,
    "errors": [],
    "successful_txs": [],
    "network": "",
    "use_intermediary": False,
    "loop_mode": False
}

def init_stats(network, use_intermediary=False, loop_mode=False):
    """Инициализация статистики"""
    global TRANSFER_STATS
    TRANSFER_STATS["start_time"] = datetime.now()
    TRANSFER_STATS["network"] = network
    TRANSFER_STATS["use_intermediary"] = use_intermediary
    TRANSFER_STATS["loop_mode"] = loop_mode
    
    # Отправляем уведомление о начале работы только если уровень >= 1
    if TELEGRAM_LOG_LEVEL_transfer >= 1:
        send_telegram_notification(
            notif_type="info",
            title="🚀 Запуск модуля переводов",
            message=f"Начинаем обработку переводов кошельков",
            network=network,
            mode="Через посредника" if use_intermediary else "Напрямую",
            loop_mode="Включен" if loop_mode else "Отключен",
            main_title="ETHmachine Transfer"
        )

def update_stats(success=True, amount_wei=0, tx_hash=None, error_msg=None):
    """Обновление статистики"""
    global TRANSFER_STATS
    TRANSFER_STATS["total_transactions_attempted"] += 1
    
    if success:
        TRANSFER_STATS["total_transactions_success"] += 1
        if amount_wei > 0:
            TRANSFER_STATS["total_amount_transferred_wei"] += amount_wei
            TRANSFER_STATS["total_amount_transferred_eth"] += Web3().from_wei(amount_wei, 'ether')
        if tx_hash:
            TRANSFER_STATS["successful_txs"].append(tx_hash)
    else:
        TRANSFER_STATS["total_transactions_failed"] += 1
        if error_msg:
            TRANSFER_STATS["errors"].append(error_msg)

def finalize_stats():
    """Завершение статистики и отправка в телеграм"""
    global TRANSFER_STATS
    TRANSFER_STATS["end_time"] = datetime.now()
    
    # Рассчитываем время работы
    if TRANSFER_STATS["start_time"]:
        duration = TRANSFER_STATS["end_time"] - TRANSFER_STATS["start_time"]
        duration_str = str(duration).split('.')[0]  # Убираем микросекунды
    else:
        duration_str = "Неизвестно"
    
    # Рассчитываем процент успешных транзакций
    success_rate = 0
    if TRANSFER_STATS["total_transactions_attempted"] > 0:
        success_rate = (TRANSFER_STATS["total_transactions_success"] / TRANSFER_STATS["total_transactions_attempted"]) * 100
    
    # Отправляем статистику только если уровень >= 1
    if TELEGRAM_LOG_LEVEL_transfer >= 1:
        # Формируем статистику
        stats_message = f"""
📊 <b>СТАТИСТИКА ПЕРЕВОДОВ</b>

⏱️ <b>Время работы:</b> {duration_str}
🌐 <b>Сеть:</b> {TRANSFER_STATS['network']}
🔄 <b>Режим:</b> {'Через посредника' if TRANSFER_STATS['use_intermediary'] else 'Напрямую'}
🔁 <b>Цикличность:</b> {'Включена' if TRANSFER_STATS['loop_mode'] else 'Отключена'}

📈 <b>ТРАНЗАКЦИИ:</b>
• Всего попыток: {TRANSFER_STATS['total_transactions_attempted']}
• Успешных: {TRANSFER_STATS['total_transactions_success']}
• Неудачных: {TRANSFER_STATS['total_transactions_failed']}
• Процент успеха: {success_rate:.1f}%

👛 <b>КОШЕЛЬКИ:</b>
• Обработано: {TRANSFER_STATS['wallets_processed']}
• С ошибками: {TRANSFER_STATS['wallets_failed']}

💰 <b>ПЕРЕВЕДЕНО:</b>
• Общая сумма: {TRANSFER_STATS['total_amount_transferred_eth']:.6f} ETH
• В wei: {TRANSFER_STATS['total_amount_transferred_wei']}

🔁 <b>ЦИКЛЫ:</b> {TRANSFER_STATS['cycles_completed']}

🚨 <b>Ошибки:</b> {len(TRANSFER_STATS['errors'])}
✅ <b>Успешные tx:</b> {len(TRANSFER_STATS['successful_txs'])}
        """
        
        # Отправляем статистику
        send_telegram_notification(
            notif_type="success",
            title="📊 Завершение работы модуля",
            message=stats_message,
            main_title="ETHmachine Transfer Completed"
        )

        # Если есть transfer_result.csv, отправляем его как файл
        result_file = "result/transfer_result.csv"
        if os.path.exists(result_file):
            send_telegram_file(
                file_path=result_file,
                caption="📄 Результаты переводов",
                main_title="ETHmachine Results"
            )

def parse_percent_range(percent_str):
    """
    Парсит строку с диапазоном для amount.
    Поддерживает:
    - "10-20%" или "10-20" - процент от баланса
    - "10-20ETH" - фиксированная сумма в ETH
    - "10%" или "10" - фиксированный процент
    - "10ETH" - фиксированная сумма в ETH
    """
    try:
        percent_str = percent_str.strip()
        
        # Проверяем, есть ли в строке "ETH" - значит фиксированная сумма
        if percent_str.upper().endswith('ETH'):
            # Убираем "ETH" и парсим как фиксированную сумму
            amount_str = percent_str[:-3].strip()
            if '-' in amount_str:
                parts = amount_str.split('-')
                if len(parts) == 2:
                    return float(parts[0]), float(parts[1]), 'ETH'
                else:
                    val = float(parts[0])
                    return val, val, 'ETH'
            else:
                val = float(amount_str)
                return val, val, 'ETH'
        else:
            # Процентное значение (убираем % если есть)
            if percent_str.endswith('%'):
                percent_str = percent_str[:-1].strip()
            
            if '-' in percent_str:
                parts = percent_str.split('-')
                if len(parts) == 2:
                    return int(parts[0]), int(parts[1]), 'PERCENT'
                else:
                    val = int(parts[0])
                    return val, val, 'PERCENT'
            else:
                val = int(percent_str)
                return val, val, 'PERCENT'
    except Exception:
        return 100, 100, 'PERCENT'  # По умолчанию 100%

def apply_trim_to_amount(amount_eth):
    """
    Применяет обрезку к сумме в ETH согласно настройкам trim_the_number_of_characters
    """
    if trim_the_number_of_characters_enable and trim_the_number_of_characters:
        # Выбираем случайное количество символов для обрезки
        trim_digits = random.choice(trim_the_number_of_characters)
        # Обрезаем до указанного количества знаков после запятой
        return round(amount_eth, trim_digits)
    return amount_eth

def get_network_rpc(network):
    from config.rpc import L1, base, sepolia, arbitrum, optimism, soneium, Polygon, Binance_Smart_Chain, Avalanche, Fantom, Gravity_Alpha_Mainnet, monad_testnet, zora, somnia, mega_eth_testnet, Abstract, pharos_testnet, kite_testnet
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
        '🚀 Gravity Alpha Mainnet (сеть Gravity )': Gravity_Alpha_Mainnet,
        '🚀 Zora': zora,
        '🚀 Abstract': Abstract,
        '🚀 Somnia': somnia,
    }
    testnet_rpc_urls = {
        '🚀 Sepolia': sepolia,
        '🚀 Mega ETH': mega_eth_testnet,
        '🚀 Pharos Testnet': pharos_testnet,
        '🚀 Kite Testnet': kite_testnet,
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
        logger.error(f"Ошибка получения баланса: {e}")
        return 0

def estimate_gas_with_margin(w3, tx):
    try:
        gas = w3.eth.estimate_gas(tx)
        return int(gas * 1.2)  # +20%
    except Exception as e:
        logger.warning(f"Не удалось оценить газ, используем 21000: {e}")
        return int(21000 * 1.2)

def send_with_retry(w3, signed_tx, explorer_url, max_attempts=None):
    if max_attempts is None:
        max_attempts = TX_SEND_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = w3.to_hex(tx_hash)
            logger.info(f"🔗 Посмотреть транзакцию: {explorer_url}{tx_hash_hex}")
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt and receipt.status == 1:
                return True, tx_hash_hex
            else:
                logger.error(f"Транзакция неуспешна (статус != 1): {tx_hash_hex}")
        except Exception as e:
            logger.error(f"Ошибка отправки/подтверждения транзакции (попытка {attempt}): {e}")
        time.sleep(WHAITE_TRANSACTION_PENDING)
    logger.error("Не удалось выполнить транзакцию после нескольких попыток.")
    return False, None

def append_result_csv(row):
    filename = "result/transfer_result.csv"
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
        logger.error(f"Ошибка записи в result/transfer_result.csv: {e}")

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
        logger.warning(f"Не удалось загрузить прокси: {e}")
    if not proxies:
        logger.error("ВНИМАНИЕ: В файле data/proxy.csv не найдено ни одного прокси!")
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
        logger.error(f"ВНИМАНИЕ: Ошибка подключения через прокси или RPC недоступен: {e}")
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
            logger.warning(f"[{address}] Ошибка получения баланса (попытка {attempt+1}/{max_attempts}): {e}")
            time.sleep(sleep_sec)
    logger.error(f"[{address}] Не удалось получить баланс после {max_attempts} попыток.")
    return 0

def get_nonce_safe(w3, address, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    for attempt in range(max_attempts):
        try:
            return w3.eth.get_transaction_count(address)
        except Exception as e:
            logger.warning(f"[{address}] Ошибка получения nonce (попытка {attempt+1}/{max_attempts}): {e}")
            time.sleep(sleep_sec)
    logger.error(f"[{address}] Не удалось получить nonce после {max_attempts} попыток.")
    return None

def estimate_gas_with_margin_safe(w3, tx, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    for attempt in range(max_attempts):
        try:
            gas = w3.eth.estimate_gas(tx)
            return int(gas * 1.2)  # +20%
        except KeyboardInterrupt:
            logger.error("\nОперация прервана пользователем (Ctrl+C). Завершение работы.")
            raise
        except Exception as e:
            logger.warning(f"Не удалось оценить газ (попытка {attempt+1}/{max_attempts}), используем 21000: {e}")
            time.sleep(sleep_sec)
    return int(21000 * 1.2)

def validate_wallet_format(wallet_value, expected_type, row_index):
    """
    Проверяет формат кошелька в зависимости от ожидаемого типа
    expected_type: 0 - приватный ключ, 1 - адрес кошелька
    """
    if not wallet_value or not isinstance(wallet_value, str):
        return False, f"Пустое значение кошелька"
    
    wallet_value = wallet_value.strip()
    
    if expected_type == 0:  # Ожидаем приватный ключ
        # Приватный ключ должен быть 64 символа в hex (без 0x) или 66 с 0x
        if wallet_value.startswith('0x'):
            if len(wallet_value) == 66:
                try:
                    int(wallet_value, 16)
                    return True, "OK"
                except ValueError:
                    return False, f"Неверный формат приватного ключа (не hex)"
            else:
                return False, f"Неверная длина приватного ключа с 0x (ожидается 66 символов, получено {len(wallet_value)})"
        else:
            if len(wallet_value) == 64:
                try:
                    int(wallet_value, 16)
                    return True, "OK"
                except ValueError:
                    return False, f"Неверный формат приватного ключа (не hex)"
            else:
                return False, f"Неверная длина приватного ключа (ожидается 64 символа, получено {len(wallet_value)})"
    
    elif expected_type == 1:  # Ожидаем адрес кошелька
        # Адрес должен начинаться с 0x и быть длиной 42 символа
        if wallet_value.startswith('0x') and len(wallet_value) == 42:
            try:
                int(wallet_value, 16)
                return True, "OK"
            except ValueError:
                return False, f"Неверный формат адреса кошелька (не hex)"
        else:
            return False, f"Неверный формат адреса кошелька (должен начинаться с 0x и быть длиной 42 символа, получено {len(wallet_value)})"
    
    return False, f"Неизвестный тип кошелька: {expected_type}"

def validate_transfer_data(transfer_data):
    """
    Проверяет данные переводов на корректность форматов кошельков
    """
    errors = []
    
    for idx, row in enumerate(transfer_data, start=1):
        # Проверяем from_wallet (всегда должен быть приватный ключ)
        is_valid, error_msg = validate_wallet_format(row.get('from_wallet', ''), 0, idx)
        if not is_valid:
            errors.append(f"Строка {idx}, поле 'from_wallet': {error_msg}")
        
        # Проверяем intermediary (если используется, всегда должен быть приватный ключ)
        if USE_INTERMEDIARY:
            intermediary = row.get('intermediary', '').strip()
            if intermediary:  # Если не пустой
                is_valid, error_msg = validate_wallet_format(intermediary, 0, idx)
                if not is_valid:
                    errors.append(f"Строка {idx}, поле 'intermediary': {error_msg}")
        
        # Проверяем to_wallet в зависимости от TYPE_VALUE_TO_WALLET
        is_valid, error_msg = validate_wallet_format(row.get('to_wallet', ''), TYPE_VALUE_TO_WALLET, idx)
        if not is_valid:
            wallet_type_name = "приватный ключ" if TYPE_VALUE_TO_WALLET == 0 else "адрес кошелька"
            errors.append(f"Строка {idx}, поле 'to_wallet' (ожидается {wallet_type_name}): {error_msg}")
    return errors

def get_to_wallet_address(to_wallet_value):
    """
    Получает адрес кошелька получателя в зависимости от TYPE_VALUE_TO_WALLET
    """
    if TYPE_VALUE_TO_WALLET == 0:
        # to_wallet - это приватный ключ, нужно получить адрес
        try:
            to_acc = Account.from_key(to_wallet_value)
            return to_acc.address, to_wallet_value
        except Exception as e:
            raise Exception(f"Ошибка создания аккаунта из приватного ключа: {e}")
    elif TYPE_VALUE_TO_WALLET == 1:
        # to_wallet - это уже адрес, но нужно преобразовать в checksum формат
        try:
            checksum_address = Web3.to_checksum_address(to_wallet_value)
            return checksum_address, None
        except Exception as e:
            raise Exception(f"Ошибка преобразования адреса в checksum формат: {e}")
    else:
        raise Exception(f"Неизвестный тип TYPE_VALUE_TO_WALLET: {TYPE_VALUE_TO_WALLET}")

def transefer_wallets_to_wallets(from_priv, intermediary_priv, to_wallet_value, network, amount, proxy=None, delay_between=0, tx_counter=0, total_tx=1):
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
            
            # Обработка to_wallet в зависимости от TYPE_VALUE_TO_WALLET
            to_address, to_priv = get_to_wallet_address(to_wallet_value)
            
            # Обработка intermediary в зависимости от USE_INTERMEDIARY
            if USE_INTERMEDIARY and intermediary_priv and intermediary_priv.strip():
                intermediary_acc = Account.from_key(intermediary_priv)
                use_intermediary = True
            else:
                intermediary_acc = None
                use_intermediary = False
                
        except Exception as e:
            error_msg = f"Ошибка создания аккаунта: {e}"
            # В многопоточном режиме не выводим детальные сообщения
            if not MULTI_THREADING:
                logger.error(error_msg)
            update_stats(success=False, error_msg=error_msg)
            if TELEGRAM_LOG_LEVEL_transfer == 2:
                send_telegram_notification(
                    notif_type="error",
                    title="❌ Ошибка создания аккаунта",
                    message=str(e),
                    wallet_address=from_priv[:10] + "...",
                    main_title="ETHmachine Transfer Error"
                )
            return

        if use_proxy:
            if '@' in use_proxy:
                proxy_parts = use_proxy.split("@")
                proxy_hidden = f"xxxx:xxx@{proxy_parts[-1].rsplit('.', 1)[0]}.x:{proxy_parts[-1].split(':')[-1]}"
            else:
                proxy_hidden = f"{use_proxy.rsplit('.', 1)[0]}.x:{use_proxy.split(':')[-1]}"
        else:
            proxy_hidden = "Нет доступных прокси"

        # В многопоточном режиме не выводим детальную информацию о запуске
        if not MULTI_THREADING:
            logger.info("="*61)
            logger.info(f"[{dt_str}] Запуск {'цепочки' if use_intermediary else 'прямого'} перевода:")
            logger.info(f"  FROM:         priv - {from_priv[:10]}... | wallet - {from_acc.address[:10]}...")
            if use_intermediary:
                logger.info(f"  INTERMEDIARY: priv - {intermediary_priv[:10]}... | wallet - {intermediary_acc.address[:10]}...")
            logger.info(f"  TO:           {'priv - ' + to_priv[:10] + '... | ' if to_priv else ''}wallet - {to_address[:10]}...")
            logger.info(f"  Сеть:         {network}")
            logger.info(f"  Используется прокси: {proxy_hidden}")
            logger.info(f"  Режим:        {'Через посредника' if use_intermediary else 'Напрямую'}")
            logger.info("-"*61)
        
        w3, session = get_web3_with_proxy(rpc_url, use_proxy)
        explorer_url = get_explorer_url(network)

        # Проверяем баланс отправителя
        for attempt in range(TX_SEND_ATTEMPTS):
            balance = get_eth_balance_safe(w3, from_acc.address)
            if balance > 0:
                break
            if not MULTI_THREADING:
                logger.warning(f"Попытка {attempt+1}/{TX_SEND_ATTEMPTS}: Баланс {from_acc.address} = 0, ждем 3 сек...")
            time.sleep(3)
        else:
            error_msg = f"Баланс {from_acc.address} = 0 после {TX_SEND_ATTEMPTS} попыток, пропуск"
            if not MULTI_THREADING:
                logger.error(error_msg)
            update_stats(success=False, error_msg=f"Нулевой баланс кошелька {from_acc.address}")
            if TELEGRAM_LOG_LEVEL_transfer == 2:
                send_telegram_notification(
                    notif_type="warning",
                    title="⚠️ Нулевой баланс",
                    message="Кошелек имеет нулевой баланс",
                    wallet_address=from_acc.address,
                    balance="0 ETH",
                    main_title="ETHmachine Transfer Warning"
                )
            return

        # Обработка amount с поддержкой ETH и процентов
        amount_from, amount_to, amount_type = parse_percent_range(amount)
        
        # Получаем цену газа заранее
        try:
            gas_price = w3.eth.gas_price
            # Устанавливаем минимальный priority fee для совместимости с L2 сетями
            min_priority_fee = max(1, int(gas_price * 0.01))  # 1% от gas_price или минимум 1 wei
        except Exception as e:
            if not MULTI_THREADING:
                logger.warning(f"Ошибка получения цены газа: {e}")
            gas_price = int(w3.to_wei('30', 'gwei'))
            min_priority_fee = int(w3.to_wei('1', 'gwei'))
        
        if amount_type == 'ETH':
            # Фиксированная сумма в ETH - генерируем случайное значение в диапазоне
            amount_eth = random.uniform(amount_from, amount_to)
            
            # Применяем обрезку если включена
            amount_eth = apply_trim_to_amount(amount_eth)
            
            amount_wei = w3.to_wei(amount_eth, 'ether')
            
            # Проверяем, что у нас достаточно средств
            if amount_wei > balance:
                if not MULTI_THREADING:
                    logger.warning(f"⚠️ Недостаточно средств: запрошено {amount_eth:.6f} ETH, доступно {w3.from_wei(balance, 'ether'):.6f} ETH")
                # Используем весь доступный баланс минус комиссия и MIN_FROM_BALANCE
                estimated_gas = 21000 * 1.2  # Примерная оценка
                fee = int(estimated_gas * gas_price * 1.2)
                
                min_balance_random = random.uniform(MIN_FROM_BALANCE[0], MIN_FROM_BALANCE[1])
                if trim_the_number_of_characters_enable:
                    min_balance_random = round(min_balance_random, random.choice(trim_the_number_of_characters))
                min_balance_wei = w3.to_wei(min_balance_random, 'ether')
                
                amount_wei = balance - fee - min_balance_wei
                if amount_wei <= 0:
                    if not MULTI_THREADING:
                        logger.warning(f"Транзакция пропущена, недостаточно средств после учета комиссии и MIN_FROM_BALANCE.")
                    return
                amount_eth = w3.from_wei(amount_wei, 'ether')
                # Применяем обрезку к пересчитанной сумме
                amount_eth = apply_trim_to_amount(amount_eth)
                amount_wei = w3.to_wei(amount_eth, 'ether')
                if not MULTI_THREADING:
                    logger.warning(f"Будет отправлено {amount_eth:.6f} ETH (максимум доступно)")
            
            # Правильный вывод диапазона только в однопоточном режиме
            if not MULTI_THREADING:
                if amount_from == amount_to:
                    logger.info(f"  Сумма:        {amount_eth:.6f} ETH (фиксированная)")
                else:
                    logger.info(f"  Сумма:        {amount_eth:.6f} ETH (из диапазона {amount_from:.6f}-{amount_to:.6f} ETH)")
        else:
            # Процентное значение
            percent = random.randint(int(amount_from), int(amount_to))
            if not MULTI_THREADING:
                if amount_from == amount_to:
                    logger.info(f"  Процент:      {percent}% от баланса")
                else:
                    logger.info(f"  Процент:      {percent}% (из диапазона {int(amount_from)}-{int(amount_to)}%) от баланса")

        if use_intermediary:
            # Старая логика с посредником
            nonce_from = get_nonce_safe(w3, from_acc.address)
            if nonce_from is None:
                logger.error(f"Не удалось получить nonce для {from_acc.address}, пропуск")
                return

            def get_send_amount(balance, amount_from, amount_to, amount_type, w3, from_addr, to_addr, gas_price, chain_id, priv_key):
                if amount_type == 'ETH':
                    # Фиксированная сумма в ETH
                    amount_eth = random.uniform(amount_from, amount_to)
                    # Применяем обрезку
                    amount_eth = apply_trim_to_amount(amount_eth)
                    value = w3.to_wei(amount_eth, 'ether')
                else:
                    # Процент от баланса
                    percent = random.randint(int(amount_from), int(amount_to))
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
                    'maxPriorityFeePerGas': min_priority_fee
                }

                estimated_gas = w3.eth.estimate_gas(tx)
                gas = int(estimated_gas * 1.2)
                fee = gas * int(gas_price * 1.2)
                
                # Применяем MIN_FROM_BALANCE только для процентных переводов
                if amount_type == 'PERCENT':
                    min_balance_random = random.uniform(MIN_FROM_BALANCE[0], MIN_FROM_BALANCE[1])
                    if trim_the_number_of_characters_enable:
                        min_balance_random = round(min_balance_random, random.choice(trim_the_number_of_characters))
                    min_balance_wei = w3.to_wei(min_balance_random, 'ether')

                    if value + fee > balance - min_balance_wei:
                        original_value = value
                        value = balance - fee - min_balance_wei
                        if value < 0:
                            value = 0
                        logger.warning(f"⚠️ Перерасчет отправляемой суммы: должно было отправиться {w3.from_wei(original_value, 'ether')} ETH, "
                                        f"но будет отправлено {w3.from_wei(value, 'ether')} ETH из-за MIN_FROM_BALANCE ({min_balance_random} ETH).")
                else:
                    # Для фиксированных сумм просто проверяем достаточность средств
                    if value + fee > balance:
                        logger.warning(f"⚠️ Недостаточно средств для отправки {w3.from_wei(value, 'ether')} ETH + комиссия {w3.from_wei(fee, 'ether')} ETH")
                        value = balance - fee
                        if value < 0:
                            value = 0
                
                return value, gas

            send_amount, gas = get_send_amount(balance, amount_from, amount_to, amount_type, w3, from_acc.address, intermediary_acc.address, gas_price, w3.eth.chain_id, from_priv)

            if send_amount == 0:
                logger.warning(f"Транзакция from -> intermediary пропущена, так как value = 0.")
                return

            # Первая транзакция: from -> intermediary
            tx = {
                'type': 0x2,
                'from': Web3.to_checksum_address(from_acc.address),
                'to': Web3.to_checksum_address(intermediary_acc.address),
                'value': send_amount,
                'gas': gas,
                'nonce': nonce_from,
                'chainId': w3.eth.chain_id,
                'maxFeePerGas': int(gas_price * 1.2),
                'maxPriorityFeePerGas': min_priority_fee
            }

            tx_hash = None
            for attempt in range(TX_SEND_ATTEMPTS):
                try:
                    signed_tx = w3.eth.account.sign_transaction(tx, from_priv)
                    logger.info(f"[{dt_str}] Отправка from -> intermediary...")
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                    logger.success(f"✅ Успешно отправлено from -> intermediary. Tx hash: {w3.to_hex(tx_hash)}")
                    
                    # Уведомление об успешной отправке первой транзакции только если уровень = 2
                    if TELEGRAM_LOG_LEVEL_transfer == 2:
                        send_telegram_notification(
                            notif_type="tx",
                            title="📤 Транзакция отправлена (1/2)",
                            message="from → intermediary",
                            wallet_address=from_acc.address[:10] + "...",
                            tx_hash=w3.to_hex(tx_hash)[:10] + "...",
                            explorer_url=explorer_url,
                            amount=f"{w3.from_wei(send_amount, 'ether'):.6f} ETH",
                            main_title="ETHmachine Transfer"
                        )
                    break
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки from -> intermediary (попытка {attempt+1}): {e}")
                    if attempt == TX_SEND_ATTEMPTS - 1:  # Последняя попытка
                        update_stats(success=False, error_msg=f"Ошибка отправки from->intermediary: {e}")
                        # Отправляем уведомление об ошибке только если уровень = 2
                        if TELEGRAM_LOG_LEVEL_transfer == 2:
                            send_telegram_notification(
                                notif_type="error",
                                title="❌ Ошибка транзакции (1/2)",
                                message=f"from → intermediary: {e}",
                                wallet_address=from_acc.address,
                                main_title="ETHmachine Transfer Error"
                            )
                    tx['nonce'] += 1
                    time.sleep(3)
            else:
                logger.error("❌ Не удалось отправить транзакцию from -> intermediary после нескольких попыток.")
                return

            logger.info("Ожидание подтверждения транзакции from -> intermediary...")
            time.sleep(WHAITE_TRANSACTION_PENDING)  
            for attempt in range(WHAITE_TRANSACTION_PENDING_COUNT):
                try:
                    receipt = w3.eth.get_transaction_receipt(tx_hash)
                    if receipt and receipt.status == 1:
                        logger.success(f"✅ Транзакция подтверждена. Tx hash: {w3.to_hex(tx_hash)}")
                        break
                    elif receipt and receipt.status == 0:
                        logger.error(f"❌ Транзакция неуспешна. Tx hash: {w3.to_hex(tx_hash)}")
                        break
                except Exception as e:
                    if not MULTI_THREADING:
                        logger.warning(f"⏳ Транзакция в ожидании (попытка {attempt+1}/{WHAITE_TRANSACTION_PENDING_COUNT}): {e}")
                time.sleep(WHAITE_TRANSACTION_PENDING)
            else:
                logger.error(f"❌ Транзакция from -> intermediary остается в состоянии pending после {WHAITE_TRANSACTION_PENDING_COUNT} попыток.")

            interm_balance = get_eth_balance_safe(w3, intermediary_acc.address)
            if interm_balance <= 0:
                logger.error(f"Баланс {intermediary_acc.address} = {interm_balance}, пропуск транзакции intermediary -> to.")
                return

            nonce_intermediary = get_nonce_safe(w3, intermediary_acc.address)
            if nonce_intermediary is None:
                logger.error(f"Не удалось получить nonce для {intermediary_acc.address}, пропуск")
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
                    'maxPriorityFeePerGas': min_priority_fee
                }
                estimated_gas = w3.eth.estimate_gas(tx)
                gas = int(estimated_gas * 1.2)
                fee = gas * int(gas_price * 1.2)
                if value > balance - fee:
                    value = balance - fee
                if value < 0:
                    value = 0
                return value, gas

            send_amount2, gas2 = get_send_amount2(interm_balance, w3, intermediary_acc.address, to_address, gas_price, w3.eth.chain_id, intermediary_priv)

            if send_amount2 == 0:
                logger.warning(f"Транзакция intermediary -> to пропущена, так как value = 0.")
                return

            tx2 = {
                'type': 0x2,
                'from': Web3.to_checksum_address(intermediary_acc.address),
                'to': Web3.to_checksum_address(to_address),
                'value': send_amount2,
                'gas': gas2,
                'nonce': nonce_intermediary,
                'chainId': w3.eth.chain_id,
                'maxFeePerGas': int(gas_price * 1.2),
                'maxPriorityFeePerGas': min_priority_fee
            }

            tx_hash2 = None
            for attempt in range(TX_SEND_ATTEMPTS):
                try:
                    signed_tx2 = w3.eth.account.sign_transaction(tx2, intermediary_priv)
                    logger.info(f"[{dt_str}] Отправка intermediary -> to...")
                    tx_hash2 = w3.eth.send_raw_transaction(signed_tx2.rawTransaction)
                    logger.success(f"✅ Успешно отправлено intermediary -> to. Tx hash: {w3.to_hex(tx_hash2)}")
                    
                    # Уведомление об успешной отправке второй транзакции только если уровень = 2
                    if TELEGRAM_LOG_LEVEL_transfer == 2:
                        send_telegram_notification(
                            notif_type="tx",
                            title="📤 Транзакция отправлена (2/2)",
                            message="intermediary → to",
                            wallet_address=to_address[:10] + "...",
                            tx_hash=w3.to_hex(tx_hash2)[:10] + "...",
                            explorer_url=explorer_url,
                            amount=f"{w3.from_wei(send_amount2, 'ether'):.6f} ETH",
                            main_title="ETHmachine Transfer"
                        )
                    break
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки intermediary -> to (попытка {attempt+1}): {e}")
                    if attempt == TX_SEND_ATTEMPTS - 1:  # Последняя попытка
                        update_stats(success=False, error_msg=f"Ошибка отправки intermediary->to: {e}")
                        # Отправляем уведомление об ошибке только если уровень = 2
                        if TELEGRAM_LOG_LEVEL_transfer == 2:
                            send_telegram_notification(
                                notif_type="error",
                                title="❌ Ошибка транзакции (2/2)",
                                message=f"intermediary → to: {e}",
                                wallet_address=to_address,
                                main_title="ETHmachine Transfer Error"
                            )
                    tx2['nonce'] += 1
                    time.sleep(3)
            else:
                logger.error("❌ Не удалось отправить транзакцию intermediary -> to после нескольких попытов.")
                return

            append_result_csv({
                "datetime": dt_str,
                "from_wallet": from_priv,
                "from_address": from_acc.address,
                "intermediary_wallet": intermediary_priv,
                "intermediary_address": intermediary_acc.address,
                "to_wallet": to_wallet_value,
                "to_address": to_address,
                "amount_sent_wei": send_amount,
                "amount_sent_eth": w3.from_wei(send_amount, 'ether'),
                "tx_hash_1": w3.to_hex(tx_hash),
                "tx_hash_2": w3.to_hex(tx_hash2),
                "explorer_link_1": f"{explorer_url}{w3.to_hex(tx_hash)}",
                "explorer_link_2": f"{explorer_url}{w3.to_hex(tx_hash2)}",
            })

            # Обновляем статистику для успешных транзакций
            update_stats(success=True, amount_wei=send_amount, tx_hash=w3.to_hex(tx_hash))
            update_stats(success=True, amount_wei=send_amount2, tx_hash=w3.to_hex(tx_hash2))
            
            # Итоговое уведомление о завершении цепочки только если уровень >= 1
            if TELEGRAM_LOG_LEVEL_transfer >= 1:
                to_wallet_balance = get_eth_balance_safe(w3, to_address)
                to_wallet_balance_eth = w3.from_wei(to_wallet_balance, 'ether')
                
                send_telegram_notification(
                    notif_type="success",
                    title="✅ Цепочка переводов завершена",
                    message=f"from → intermediary → to",
                    wallet_address=f"{from_acc.address[:10]}...→{to_address[:10]}...",
                    balance=f"{to_wallet_balance_eth:.6f} ETH",
                    tx1=w3.to_hex(tx_hash)[:10] + "...",
                    tx2=w3.to_hex(tx_hash2)[:10] + "...",
                    total_amount=f"{w3.from_wei(send_amount, 'ether'):.6f} ETH",
                    main_title="ETHmachine Transfer Success"
                )

        else:
            # Новая логика: прямой перевод from -> to
            if not MULTI_THREADING:
                logger.info(f"[{dt_str}] Прямой перевод from -> to...")
            
            nonce_from = get_nonce_safe(w3, from_acc.address)
            if nonce_from is None:
                logger.error(f"Не удалось получить nonce для {from_acc.address}, пропуск")
                return

            # Рассчитываем сумму для прямого перевода в зависимости от типа
            if amount_type == 'ETH':
                # Фиксированная сумма в ETH
                amount_eth = random.uniform(amount_from, amount_to)
                # Применяем обрезку
                amount_eth = apply_trim_to_amount(amount_eth)
                value = w3.to_wei(amount_eth, 'ether')
            else:
                # Процент от баланса
                percent = random.randint(int(amount_from), int(amount_to))
                value = int(balance * percent / 100)
            
            tx = {
                'type': 0x2,
                'from': Web3.to_checksum_address(from_acc.address),
                'to': Web3.to_checksum_address(to_address),
                'value': value,
                'gas': 1000000,
                'nonce': nonce_from,
                'chainId': w3.eth.chain_id,
                'maxFeePerGas': int(gas_price * 1.2),
                'maxPriorityFeePerGas': min_priority_fee
            }

            estimated_gas = w3.eth.estimate_gas(tx)
            gas = int(estimated_gas * 1.2)
            fee = gas * int(gas_price * 1.2)
            
            # Применяем MIN_FROM_BALANCE только для процентных переводов
            if amount_type == 'PERCENT':
                min_balance_random = random.uniform(MIN_FROM_BALANCE[0], MIN_FROM_BALANCE[1])
                if trim_the_number_of_characters_enable:
                    min_balance_random = round(min_balance_random, random.choice(trim_the_number_of_characters))
                min_balance_wei = w3.to_wei(min_balance_random, 'ether')

                if value + fee > balance - min_balance_wei:
                    original_value = value
                    value = balance - fee - min_balance_wei
                    if value < 0:
                        value = 0
                    logger.warning(f"⚠️ Перерасчет отправляемой суммы: должно было отправиться {w3.from_wei(original_value, 'ether')} ETH, "
                                    f"но будет отправлено {w3.from_wei(value, 'ether')} ETH из-за MIN_FROM_BALANCE ({min_balance_random} ETH).")
            else:
                # Для фиксированных сумм просто проверяем достаточность средств
                if value + fee > balance:
                    logger.warning(f"⚠️ Недостаточно средств для отправки {w3.from_wei(value, 'ether')} ETH + комиссия {w3.from_wei(fee, 'ether')} ETH")
                    value = balance - fee
                    if value < 0:
                        value = 0

            if value == 0:
                logger.warning(f"Транзакция пропущена, так как value = 0.")
                return

            tx['value'] = value
            tx['gas'] = gas

            tx_hash = None
            for attempt in range(TX_SEND_ATTEMPTS):
                try:
                    signed_tx = w3.eth.account.sign_transaction(tx, from_priv)
                    if not MULTI_THREADING:
                        logger.info(f"[{dt_str}] Отправка from -> to...")
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                    if not MULTI_THREADING:
                        logger.success(f"✅ Успешно отправлено from -> to. Tx hash: {w3.to_hex(tx_hash)}")

                    break
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки from -> to (попытка {attempt+1}): {e}")
                    if attempt == TX_SEND_ATTEMPTS - 1:  # Последняя попытка
                        update_stats(success=False, error_msg=f"Ошибка прямого перевода: {e}")
                        # Отправляем уведомление об ошибке только если уровень = 2
                        if TELEGRAM_LOG_LEVEL_transfer == 2:
                            send_telegram_notification(
                                notif_type="error",
                                title="❌ Ошибка прямой транзакции",
                                message=f"from → to: {e}",
                                wallet_address=from_acc.address,
                                main_title="ETHmachine Transfer Error"
                            )
                    tx['nonce'] += 1
                    time.sleep(3)
            else:
                logger.error("❌ Не удалось отправить транзакцию from -> to после нескольких попыток.")
                return

            # Ждем подтверждения
            if not MULTI_THREADING:
                logger.info("Ожидание подтверждения транзакции from -> to...")
            time.sleep(WHAITE_TRANSACTION_PENDING)
            for attempt in range(WHAITE_TRANSACTION_PENDING_COUNT):
                try:
                    receipt = w3.eth.get_transaction_receipt(tx_hash)
                    if receipt and receipt.status == 1:
                        logger.success(f"✅ Транзакция подтверждена. Tx hash: {explorer_url}{w3.to_hex(tx_hash)}")
                        break
                    elif receipt and receipt.status == 0:
                        logger.error(f"❌ Транзакция неуспешна. Tx hash: {explorer_url}{w3.to_hex(tx_hash)}")
                        break
                except Exception as e:
                    if not MULTI_THREADING:
                        logger.warning(f"⏳ Транзакция в ожидании (попытка {attempt+1}/{WHAITE_TRANSACTION_PENDING_COUNT}): {e}")
                time.sleep(WHAITE_TRANSACTION_PENDING)
            else:
                logger.error(f"❌ Транзакция from -> to остается в состоянии pending после {WHAITE_TRANSACTION_PENDING_COUNT} попыток.")

            # Записываем результат для прямого перевода
            append_result_csv({
                "datetime": dt_str,
                "from_wallet": from_priv,
                "from_address": from_acc.address,
                "intermediary_wallet": "",
                "intermediary_address": "",
                "to_wallet": to_wallet_value,
                "to_address": to_address,
                "amount_sent_wei": value,
                "amount_sent_eth": w3.from_wei(value, 'ether'),
                "tx_hash_1": w3.to_hex(tx_hash),
                "tx_hash_2": "",
                "explorer_link_1": f"{explorer_url}{w3.to_hex(tx_hash)}",
                "explorer_link_2": "",
            })

            # Обновляем статистику для успешной транзакции
            update_stats(success=True, amount_wei=value, tx_hash=w3.to_hex(tx_hash))
            
            # Итоговое уведомление о завершении прямого перевода только если уровень >= 1
            if TELEGRAM_LOG_LEVEL_transfer >= 1:
                to_wallet_balance = get_eth_balance_safe(w3, to_address)
                to_wallet_balance_eth = w3.from_wei(to_wallet_balance, 'ether')
                
                send_telegram_notification(
                    notif_type="success",
                    title="✅ Прямой перевод завершен",
                    message=f"from → to",
                    wallet_address=f"{from_acc.address[:10]}...→{to_address[:10]}...",
                    balance=f"{to_wallet_balance_eth:.6f} ETH",
                    tx_hash=w3.to_hex(tx_hash)[:10] + "...",
                    amount=f"{w3.from_wei(value, 'ether'):.6f} ETH",
                    main_title="ETHmachine Transfer Success"
                )

            # Получаем баланс для финального вывода
            to_wallet_balance = get_eth_balance_safe(w3, to_address)
            to_wallet_balance_eth = w3.from_wei(to_wallet_balance, 'ether')
            if not MULTI_THREADING:
                logger.success("=" * 60)
                logger.success(f"{explorer_url}{w3.to_hex(tx_hash)}")
                logger.success(f"from_wallet ({from_acc.address}) - {w3.from_wei(value, 'ether')} ETH")
                logger.success(f"Баланс to_wallet ({to_address}) по завершению - {to_wallet_balance_eth} ETH")
                logger.success("=" * 60 + "\n")
    except Exception as e:
        logger.error(f"Ошибка в процессе перевода: {e}")
        update_stats(success=False, error_msg=str(e))
        # Отправляем уведомление об общей ошибке только если уровень = 2
        if TELEGRAM_LOG_LEVEL_transfer == 2:
            send_telegram_notification(
                notif_type="error",
                title="❌ Ошибка в процессе перевода",
                message=str(e),
                wallet_address=from_priv[:10] + "...",
                main_title="ETHmachine Transfer Error"
            )


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
        logger.error(f"Ошибка сохранения зафейленной строки: {e}")

def load_failed_wallets():
    progress_file = "db/transfer_progress.json"
    try:
        if os.path.exists(progress_file):
            with open(progress_file, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
                return progress_data.get("failed_wallets", [])
        return []
    except Exception as e:
        logger.error(f"Ошибка загрузки зафейленных строк: {e}")
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
        logger.error(f"Ошибка удаления строки: {e}")

def get_available_intermediary_wallets():
    """
    Получает доступные посреднические кошельки из data/one_time_intermediary.csv
    """
    try:
        intermediary_file = "data/one_time_intermediary.csv"
        available_wallets = []
        
        if not os.path.exists(intermediary_file):
            logger.error(f"Файл {intermediary_file} не найден!")
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
        
        logger.info(f"Найдено {len(available_wallets)} доступных посреднических кошельков")
        return available_wallets
        
    except Exception as e:
        logger.error(f"Ошибка чтения файла посредников: {e}")
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
        
        logger.warning(f"Посреднический кошелек отмечен как использованный: {used_private_key[:10]}...")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка обновления статуса посреднического кошелька: {e}")
        return False

def check_wallet_balances_for_loop(transfer_data, network, proxies):
    """
    Проверяет балансы кошельков для принятия решения о продолжении цикла
    """
    logger.info("🔍 Проверка балансов кошельков...")
    
    # Генерируем случайные пороговые значения
    min_from_balance = random.uniform(expected_balance_from_wallet[0], expected_balance_from_wallet[1])
    max_to_balance = random.uniform(expected_balance_to_wallet[0], expected_balance_to_wallet[1])
    
    logger.info(f"Проверка балансов: минимальный from_wallet = {min_from_balance:.6f} ETH, максимальный to_wallet = {max_to_balance:.6f} ETH")
    
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
            
            # Правильно обрабатываем to_wallet в зависимости от TYPE_VALUE_TO_WALLET
            if TYPE_VALUE_TO_WALLET == 0:
                # to_wallet - это приватный ключ
                to_acc = Account.from_key(row['to_wallet'])
                to_address = to_acc.address
            else:
                # to_wallet - это адрес, преобразуем в checksum формат
                to_address = Web3.to_checksum_address(row['to_wallet'])
            
            from_balance = get_eth_balance_safe(w3, from_acc.address)
            to_balance = get_eth_balance_safe(w3, to_address)
            
            from_balance_eth = w3.from_wei(from_balance, 'ether')
            to_balance_eth = w3.from_wei(to_balance, 'ether')
            
            # Проверяем условия
            if from_balance_eth >= min_from_balance and to_balance_eth <= max_to_balance:
                valid_wallets.append(row)
                logger.success(f"✅  {from_acc.address[:10]}... -> {to_address[:10]}... (from: {from_balance_eth:.6f}, to: {to_balance_eth:.6f})")
            else:
                logger.warning(f"⏭️  {from_acc.address[:10]}... -> {to_address[:10]}... (from: {from_balance_eth:.6f}, to: {to_balance_eth:.6f}) - не подходит")
                
        except Exception as e:
            logger.error(f"Ошибка проверки баланса кошелька: {e}")
            continue
        finally:
            # Закрываем сессию для каждого коша после использования 
            if session:
                try:
                    session.close()
                except Exception as e:
                    logger.warning(f"Ошибка закрытия сессии для кошелька: {e}")
    
    return valid_wallets

def process_wallets_transfer_normal(transfer_data, proxies, network, delay_between, total_tx, progress_file=None, start_idx=0, completed_txs=0):
    """
    Обычная обработка переводов без зацикливания (оригинальная логика)
    """
    # Инициализируем статистику
    init_stats(network, USE_INTERMEDIARY, False)
    
    # Валидация данных перед началом обработки
    validation_errors = validate_transfer_data(transfer_data)
    if validation_errors:
        logger.error("❌ Ошибки валидации данных:")
        for error in validation_errors:
            logger.error(f"  {error}")
        logger.error("\nИсправьте ошибки в файле data/transfer_token.csv и запустите снова.")
        return

    logger.success("✅ Валидация данных прошла успешно")
    
    # Проверяем, включена ли многопоточность
    if MULTI_THREADING:
        return process_wallets_transfer_multithreaded(transfer_data, proxies, network, delay_between, total_tx, progress_file, start_idx, completed_txs)
    
    # Оригинальная логика для однопоточного режима
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
                logger.warning(f"Восстановление с кошелька #{start_idx}, завершено транзакций: {completed_txs}...")
        except Exception as e:
            logger.error(f"Ошибка загрузки прогресса: {e}")
            start_idx = 0
            completed_txs = 0

    failed_wallets = load_failed_wallets()
    if failed_wallets:
        logger.warning(f"Обработка зафейленных кошельков ({len(failed_wallets)} строк)...")
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
                logger.error(f"Ошибка обработки зафейленного кошелька: {e}")

    for idx in range(start_idx, total_wallets):
        row = transfer_data[idx]
        proxy = random.choice(proxies) if proxies else None
        tx_counter = idx * 2

        if progress_file:
            try:
                with open(progress_file, "w", encoding="utf-8") as f:
                    json.dump({"last_idx": idx, "completed_txs": completed_txs}, f, indent=2)
            except Exception as e:
                logger.error(f"Ошибка записи прогресса: {e}")

        try:
            TRANSFER_STATS["wallets_processed"] += 1
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
            logger.error(f"Ошибка обработки кошелька: {e}")
            TRANSFER_STATS["wallets_failed"] += 1
            save_failed_wallet(row)  

        progress = int((completed_txs / total_tx) * bar_length)
        bar = "█" * progress + "░" * (bar_length - progress)
        spinner_frame = next(spinner_cycle)

        remaining_tx = total_tx - completed_txs
        remaining_wallets = total_wallets - idx - 1
        estimated_time = remaining_tx * delay_between + remaining_wallets * 13 
        completion_time = datetime.now() + timedelta(seconds=estimated_time)
        completion_time_str = completion_time.strftime("%d.%m.%Y в %H:%M")  

        if USE_INTERMEDIARY:
            print(
                f"\r[{bar}] {completed_txs}/{total_tx} транзакций | Осталось пар: {remaining_wallets} | {spinner_frame} {Fore.CYAN}Последний:| Завершение: {completion_time_str}{Style.RESET_ALL}",
                end="",
                flush=True,
            )
            print() 
        else:
            print(
                f"\r[{bar}] {completed_txs}/{total_tx/2} транзакций | Осталось кошельков: {remaining_wallets} | {spinner_frame} {Fore.CYAN}Последний:| Завершение: {completion_time_str}{Style.RESET_ALL}",
                end="",
                flush=True,
            )

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
    
    # Инициализируем статистику для циклического режима
    init_stats(network, USE_INTERMEDIARY, True)
    
    # Валидация данных перед началом обработки
    validation_errors = validate_transfer_data(transfer_data)
    if validation_errors:
        logger.error("❌ Ошибки валидации данных:")
        for error in validation_errors:
            logger.error(f"  {error}")
        logger.error("\nИсправьте ошибки в файле data/transfer_token.csv и запустите снова.")
        return

    logger.success("✅ Валидация данных прошла успешно")
    
    logger.info(f"🔄 Включен режим зацикливания. Максимум циклов: {loop_transfer_count}")
    
    cycle = 0
    while cycle < loop_transfer_count:
        cycle += 1
        TRANSFER_STATS["cycles_completed"] = cycle
        
        logger.info("="*60)
        logger.info(f"🔄 ЦИКЛ {cycle}/{loop_transfer_count}")
        logger.info("="*60)
        
        # Уведомление о начале нового цикла
        send_telegram_notification(
            notif_type="info",
            title=f"🔄 Начало цикла {cycle}/{loop_transfer_count}",
            message="Проверяем балансы и ищем подходящие кошельки",
            cycle=f"{cycle}/{loop_transfer_count}",
            main_title="ETHmachine Transfer Cycle"
        )
        
        # Проверяем доступность посреднических кошельков
        available_intermediaries = get_available_intermediary_wallets()
        if not available_intermediaries:
            logger.error("❌ Нет доступных кошельков для роли посредника!")
            logger.warning("Остановка выполнения переводов.")
            break
        
        # Проверяем балансы кошельков
        logger.info("🔍 Проверка балансов кошельков...")
        valid_wallets = check_wallet_balances_for_loop(transfer_data, network, proxies)
        
        if not valid_wallets:
            local_sleep_time_between_loops = random.randint(sleep_time_between_loops[0], sleep_time_between_loops[1])
            completion_time = datetime.now() + timedelta(seconds=local_sleep_time_between_loops)
            completion_time_str = completion_time.strftime("%d.%m.%Y в %H:%M:%S")
            current_time_str = datetime.now().strftime("%d.%m.%Y в %H:%M:%S")
            logger.warning(f"⏭️ Цикл {cycle}: Нет кошельков, подходящих под условия.")
            logger.warning(f"⏰ Текущее время: {current_time_str}")
            logger.warning(f"🔄 Следующий запуск: {completion_time_str} (через {local_sleep_time_between_loops} секунд)")
            
            # Уведомление о пропуске цикла только если уровень = 2
            if TELEGRAM_LOG_LEVEL_transfer == 2:
                send_telegram_notification(
                    notif_type="warning",
                    title=f"⏭️ Цикл {cycle} пропущен",
                    message="Нет кошельков, подходящих под условия",
                    next_check=completion_time_str,
                    cycle=f"{cycle}/{loop_transfer_count}",
                    main_title="ETHmachine Transfer Cycle"
                )
            time.sleep(local_sleep_time_between_loops)
            continue
        
        logger.success(f"✅ Найдено {len(valid_wallets)} подходящих пар кошельков")
        
        # Уведнение о найденных кошельках только если уровень = 2
        if TELEGRAM_LOG_LEVEL_transfer == 2:
            send_telegram_notification(
                notif_type="success",
                title=f"✅ Цикл {cycle}: найдены кошельки",
                message=f"Обрабатываем {len(valid_wallets)} подходящих пар",
                wallets_found=len(valid_wallets),
                intermediaries_available=len(available_intermediaries),
                cycle=f"{cycle}/{loop_transfer_count}",
                main_title="ETHmachine Transfer Cycle"
            )
        
        # Проверяем, хватает ли посредников
        if len(available_intermediaries) < len(valid_wallets):
            logger.warning(f"⚠️ Доступно только {len(available_intermediaries)} посредников для {len(valid_wallets)} пар")
            valid_wallets = valid_wallets[:len(available_intermediaries)]
        
        # Обрабатываем ВСЕ найденные кошельки сразу
        current_total_tx = len(valid_wallets) * 2
        process_wallets_transfer_with_one_time_intermediaries(valid_wallets, available_intermediaries, proxies, network, delay_between, current_total_tx)
        
        logger.success(f"✅ Цикл {cycle} завершен. Обработано {len(valid_wallets)} пар кошельков")
        
        # Уведомление о завершении цикла только если уровень = 2
        if TELEGRAM_LOG_LEVEL_transfer == 2:
            send_telegram_notification(
                notif_type="success",
                title=f"✅ Цикл {cycle} завершен",
                message=f"Обработано {len(valid_wallets)} пар кошельков",
                cycle=f"{cycle}/{loop_transfer_count}",
                processed_wallets=len(valid_wallets),
                main_title="ETHmachine Transfer Cycle"
            )
        
        # Пауза между циклами (кроме последнего)
        if cycle < loop_transfer_count:
            local_sleep_time_between_loops = random.randint(sleep_time_between_loops[0], sleep_time_between_loops[1])
            logger.info(f"⏸️ Пауза между циклами {local_sleep_time_between_loops} секунд...")
            countdown_timer(local_sleep_time_between_loops, "Пауза между циклами")

    if cycle >= loop_transfer_count: 
        logger.success(f"🎉 Все {loop_transfer_count} циклов завершены!")
    else:
        logger.error(f"❌ Завершены не все циклы, выполнено - {cycle} из {loop_transfer_count} циклов.")
    
    # Завершаем статистику
    finalize_stats()

def process_wallets_transfer_with_one_time_intermediaries(valid_wallets, available_intermediaries, proxies, network, delay_between, total_tx):
    """
    Обработка переводов с использованием одноразовых посредников
    """
    if not valid_wallets:
        return
        
    logger.info(f"\n🚀 Начинаем обработку {len(valid_wallets)} подходящих пар кошельков")
    
    spinner_cycle = cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    bar_length = 80
    completed_txs = 0
    
    for idx, row in enumerate(valid_wallets):
        if idx >= len(available_intermediaries):
            logger.error(f"❌ Недостаточно посредников для обработки всех кошельков")
            break
        
        # Берем случайного посредника из доступных
        intermediary = random.choice(available_intermediaries)
        available_intermediaries.remove(intermediary)  # Убираем из списка доступных
        
        proxy = random.choice(proxies) if proxies else None
        tx_counter = idx * 2
        
        logger.info(f"\n📋 Обработка пары {idx + 1}/{len(valid_wallets)}")
        
        try:
            TRANSFER_STATS["wallets_processed"] += 1
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
            logger.error(f"Ошибка обработки кошелька: {e}")
            TRANSFER_STATS["wallets_failed"] += 1
            # Даже при ошибке отмечаем посредника как использованного
            mark_intermediary_as_used(intermediary['private_key'])
        
        # Обновляем прогресс
        progress = int((completed_txs / total_tx) * bar_length)
        bar = "█" * progress + "░" * (bar_length - progress)
        spinner_frame = next(spinner_cycle)
        
        remaining_tx = total_tx - completed_txs
        remaining_wallets = len(valid_wallets) - idx -  1
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
    
    logger.success(f"\n✅ Завершена обработка всех {len(valid_wallets)} подходящих пар в текущем цикле")
def process_single_wallet_transfer(args):
    """
    Обрабатывает один кошелек для многопоточного режима
    """
    row, proxy, network, delay_between, tx_counter, total_tx = args
    
    try:
        TRANSFER_STATS["wallets_processed"] += 1
        
        # Выполняем перевод
        result = transefer_wallets_to_wallets(
            row['from_wallet'],
            row['intermediary'],
            row['to_wallet'],
            network,
            row['amount'],
            proxy,
            delay_between,
            tx_counter,
            total_tx
        )
        
        return {"success": True, "row": row, "result": result}
        
    except Exception as e:
        TRANSFER_STATS["wallets_failed"] += 1
        return {"success": False, "row": row, "error": str(e)}

def process_wallets_transfer_multithreaded(transfer_data, proxies, network, delay_between, total_tx, progress_file=None, start_idx=0, completed_txs=0):
    """
    Многопоточная обработка переводов
    """
    logger.info(f"🧵 Многопоточный режим включен. Потоков: {NUM_THREADS}")
    logger.warning("📊 В процессе работы выводятся только результаты транзакций")
    logger.info("="*80)
    
    # Используем переданные параметры прогресса
    if start_idx > 0:
        logger.success(f"▶️ Продолжаем с кошелька #{start_idx}, завершено транзакций: {completed_txs}")
        # Обрезаем список кошельков до непроцессированных
        transfer_data = transfer_data[start_idx:]
    
    # Обработка зафейленных кошельков
    failed_wallets = load_failed_wallets()
    if failed_wallets:
        logger.warning(f"\n📋 Обработка зафейленных кошельков ({len(failed_wallets)} строк)...")
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
                logger.success(f"✅ Зафейленный кошелек успешно обработан")
            except Exception as e:
                logger.error(f"❌ Ошибка обработки зафейленного кошелька: {e}")
    
    # Подготавливаем аргументы для каждого кошелька
    tasks = []
    for idx, row in enumerate(transfer_data):
        proxy = random.choice(proxies) if proxies else None
        tx_counter = (start_idx + idx) * 2  # Учитываем начальный индекс
        tasks.append((row, proxy, network, delay_between, tx_counter, total_tx, start_idx + idx))
    
    successful_transfers = 0
    failed_transfers = 0
    completed_tasks = 0
    total_tasks = len(tasks)
    
    # Инициализируем прогресс бар
    bar_length = 50
    spinner_cycle = cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    
    def update_progress_bar():
        progress = int((completed_tasks / total_tasks) * bar_length)
        bar = "█" * progress + "░" * (bar_length - progress)
        percentage = (completed_tasks / total_tasks) * 100
        spinner_frame = next(spinner_cycle)

        print(f"\r{spinner_frame} [{bar}] {completed_tasks}/{total_tasks} ({percentage:.1f}%) | ✅{successful_transfers} ❌{failed_transfers}", end="", flush=True)
        print('\n')

    def save_progress(current_idx):
        """Сохраняет текущий прогресс"""
        if progress_file:
            try:
                os.makedirs(os.path.dirname(progress_file), exist_ok=True)
                with open(progress_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "last_idx": current_idx,
                        "completed_txs": completed_txs + (completed_tasks * 2)
                    }, f, indent=2)
            except Exception as e:
                logger.error(f"\nОшибка сохранения прогресса: {e}")
    
    # Выполняем многопоточную обработку
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_task = {executor.submit(process_single_wallet_transfer_with_progress, task): task for task in tasks}
        
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            row = task[0]
            wallet_idx = task[6]  # Индекс кошелька
            completed_tasks += 1
            
            # Сохраняем прогресс каждые 5 кошельков
            if completed_tasks % 5 == 0:
                save_progress(wallet_idx + 1)
            
            try:
                result = future.result()
                
                if result["success"]:
                    successful_transfers += 1
                    # Краткий вывод успешной транзакции
                    from_acc = Account.from_key(row['from_wallet'])
                    to_address, _ = get_to_wallet_address(row['to_wallet'])
                    
                    # Обновляем прогресс бар
                    update_progress_bar()
                    if not MULTI_THREADING:
                        logger.success(f"\n✅ Успешно отправлено from -> to (#{wallet_idx + 1})")
                        logger.info(f"   - from: {from_acc.address}")
                        logger.info(f"   - to: {to_address}")
                        logger.info(f"   - amount: {row['amount']}")
                        if 'tx_hash' in str(result.get('result', '')):
                            logger.info(f"   - Tx: {result.get('result', 'N/A')}")
                else:
                    failed_transfers += 1
                    # Краткий вывод неудачной транзакции
                    if not MULTI_THREADING:
                        from_acc = Account.from_key(row['from_wallet'])
                        to_address, _ = get_to_wallet_address(row['to_wallet'])

                    # Обновляем прогресс бар
                    update_progress_bar()
                    logger.error(f"\n❌ Ошибка перевода from -> to (#{wallet_idx + 1})")
                    logger.info(f"   - from: {from_acc.address}")
                    logger.info(f"   - to: {to_address}")
                    logger.error(f"   - error: {result['error']}")
                    
                    # Сохраняем неудачную попытку
                    save_failed_wallet(result["row"])
                    
            except Exception as e:
                failed_transfers += 1
                from_acc = Account.from_key(row['from_wallet'])
                to_address, _ = get_to_wallet_address(row['to_wallet'])
                
                # Обновляем прогресс бар
                update_progress_bar()
                logger.error(f"\n❌ Исключение при обработке кошелька (#{wallet_idx + 1})")
                logger.info(f"   - from: {from_acc.address}")
                logger.info(f"   - to: {to_address}")
                logger.error(f"   - exception: {str(e)}")
                
                save_failed_wallet(row)
    
    # Финальное обновление прогресс бара
    update_progress_bar()
    
    # Удаляем файл прогресса после завершения
    if progress_file and os.path.exists(progress_file):
        os.remove(progress_file)
    
    # Выводим итоговую статистику
    logger.info("\n\n" + "="*80)
    logger.warning("📊 ИТОГОВАЯ СТАТИСТИКА МНОГОПОТОЧНОГО РЕЖИМА:")
    logger.success(f"✅ Успешных переводов: {successful_transfers}")
    logger.error(f"❌ Неудачных переводов: {failed_transfers}")
    if (successful_transfers + failed_transfers) > 0:
        logger.info(f"📈 Общий процент успеха: {(successful_transfers/(successful_transfers+failed_transfers)*100):.1f}%")
    logger.info("="*80)

def process_single_wallet_transfer_with_progress(args):
    """
    Обрабатывает один кошелек для многопоточного режима с поддержкой прогресса
    """
    row, proxy, network, delay_between, tx_counter, total_tx, wallet_idx = args
    
    try:
        TRANSFER_STATS["wallets_processed"] += 1
        
        # Выполняем перевод
        result = transefer_wallets_to_wallets(
            row['from_wallet'],
            row['intermediary'],
            row['to_wallet'],
            network,
            row['amount'],
            proxy,
            delay_between,
            tx_counter,
            total_tx
        )
        
        return {"success": True, "row": row, "result": result, "wallet_idx": wallet_idx}
        
    except Exception as e:
        TRANSFER_STATS["wallets_failed"] += 1
        return {"success": False, "row": row, "error": str(e), "wallet_idx": wallet_idx}

