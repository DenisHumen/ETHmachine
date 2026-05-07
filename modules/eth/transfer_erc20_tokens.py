"""
💎 МОДУЛЬ ПЕРЕВОДОВ ТОКЕНОВ ERC-20
===================================

Универсальный модуль для отправки токенов ERC-20 между кошельками в различных блокчейн сетях.

Основные возможности:
- Отправка токенов напрямую или через посредника
- Многопоточная обработка
- Циклическая обработка с условиями
- Поддержка процентных и фиксированных сумм
- Интеграция с Telegram
- Детальная статистика

Автор: ETHmachine Team
Версия: 1.0
"""

import sys
import os
import csv
import time
import random
import requests
from web3 import Web3
from eth_account import Account
from colorama import Fore, Style
from datetime import datetime
from pathlib import Path
from itertools import cycle
from concurrent.futures import ThreadPoolExecutor, as_completed
from modules.simple_logger import logger

# Настройка путей для импорта
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.modules.cfg_base import TX_SEND_ATTEMPTS, WHAITE_TRANSACTION_PENDING, WHAITE_TRANSACTION_PENDING_COUNT
from config.modules.cfg_transfer_erc20 import (
    expected_completion_time_token, MIN_FROM_BALANCE_TOKEN, trim_the_number_of_characters_enable_token,
    trim_the_number_of_characters_token, loop_transfer_enable_token, loop_transfer_count_token,
    expected_balance_from_wallet_token, expected_balance_to_wallet_token, sleep_time_between_loops_token,
    USE_INTERMEDIARY_TOKEN, TYPE_VALUE_TO_WALLET_TOKEN, TELEGRAM_LOG_LEVEL_transfer_token,
    MULTI_THREADING_TOKEN, NUM_THREADS_TOKEN, GAS_PRICE_MULTIPLIER_TOKEN, GAS_LIMIT_MULTIPLIER_TOKEN
)
from config.networks import get_explorer_url, get_network_display_name
from config.token_address_erc20 import *
from modules.notifications import send_telegram_notification, send_telegram_file

# ERC-20 ABI для взаимодействия с токенами
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]

# Глобальная статистика
TOKEN_TRANSFER_STATS = {
    "start_time": None,
    "end_time": None,
    "total_transactions_attempted": 0,
    "total_transactions_success": 0,
    "total_transactions_failed": 0,
    "total_amount_transferred": 0,
    "wallets_processed": 0,
    "wallets_failed": 0,
    "cycles_completed": 0,
    "errors": [],
    "successful_txs": [],
    "network": "",
    "token_symbol": "",
    "use_intermediary": False,
    "loop_mode": False
}

def init_token_stats(network, token_symbol, use_intermediary=False, loop_mode=False):
    """Инициализация статистики для переводов токенов"""
    global TOKEN_TRANSFER_STATS
    TOKEN_TRANSFER_STATS["start_time"] = datetime.now()
    TOKEN_TRANSFER_STATS["network"] = network
    TOKEN_TRANSFER_STATS["token_symbol"] = token_symbol
    TOKEN_TRANSFER_STATS["use_intermediary"] = use_intermediary
    TOKEN_TRANSFER_STATS["loop_mode"] = loop_mode
    
    # Отправляем уведомление о начале работы
    if TELEGRAM_LOG_LEVEL_transfer_token >= 1:
        send_telegram_notification(
            notif_type="info",
            title="🚀 Запуск модуля переводов токенов",
            message=f"Начинаем обработку переводов токенов {token_symbol.upper()}",
            network=network,
            token=token_symbol.upper(),
            mode="Через посредника" if use_intermediary else "Напрямую",
            loop_mode="Включен" if loop_mode else "Отключен",
            main_title="ETHmachine Token Transfer"
        )

def update_token_stats(success=True, amount=0, tx_hash=None, error_msg=None):
    """Обновление статистики переводов токенов"""
    global TOKEN_TRANSFER_STATS
    TOKEN_TRANSFER_STATS["total_transactions_attempted"] += 1
    
    if success:
        TOKEN_TRANSFER_STATS["total_transactions_success"] += 1
        if amount > 0:
            TOKEN_TRANSFER_STATS["total_amount_transferred"] += amount
        if tx_hash:
            TOKEN_TRANSFER_STATS["successful_txs"].append(tx_hash)
    else:
        TOKEN_TRANSFER_STATS["total_transactions_failed"] += 1
        if error_msg:
            TOKEN_TRANSFER_STATS["errors"].append(error_msg)

def finalize_token_stats():
    """Завершение статистики и отправка в телеграм"""
    global TOKEN_TRANSFER_STATS
    TOKEN_TRANSFER_STATS["end_time"] = datetime.now()
    
    # Рассчитываем время работы
    if TOKEN_TRANSFER_STATS["start_time"]:
        duration = TOKEN_TRANSFER_STATS["end_time"] - TOKEN_TRANSFER_STATS["start_time"]
        duration_str = str(duration).split('.')[0]
    else:
        duration_str = "Неизвестно"
    
    # Рассчитываем процент успешных транзакций
    success_rate = 0
    if TOKEN_TRANSFER_STATS["total_transactions_attempted"] > 0:
        success_rate = (TOKEN_TRANSFER_STATS["total_transactions_success"] / TOKEN_TRANSFER_STATS["total_transactions_attempted"]) * 100
    
    # Отправляем статистику
    if TELEGRAM_LOG_LEVEL_transfer_token >= 1:
        stats_message = f"""
📊 <b>СТАТИСТИКА ПЕРЕВОДОВ ТОКЕНОВ</b>

⏱️ <b>Время работы:</b> {duration_str}
🌐 <b>Сеть:</b> {TOKEN_TRANSFER_STATS['network']}
💎 <b>Токен:</b> {TOKEN_TRANSFER_STATS['token_symbol'].upper()}
🔄 <b>Режим:</b> {'Через посредника' if TOKEN_TRANSFER_STATS['use_intermediary'] else 'Напрямую'}
🔁 <b>Цикличность:</b> {'Включена' if TOKEN_TRANSFER_STATS['loop_mode'] else 'Отключена'}

📈 <b>ТРАНЗАКЦИИ:</b>
• Всего попыток: {TOKEN_TRANSFER_STATS['total_transactions_attempted']}
• Успешных: {TOKEN_TRANSFER_STATS['total_transactions_success']}
• Неудачных: {TOKEN_TRANSFER_STATS['total_transactions_failed']}
• Процент успеха: {success_rate:.1f}%

👛 <b>КОШЕЛЬКИ:</b>
• Обработано: {TOKEN_TRANSFER_STATS['wallets_processed']}
• С ошибками: {TOKEN_TRANSFER_STATS['wallets_failed']}

💰 <b>ПЕРЕВЕДЕНО:</b>
• Общее количество: {TOKEN_TRANSFER_STATS['total_amount_transferred']:.6f} {TOKEN_TRANSFER_STATS['token_symbol'].upper()}

🔁 <b>ЦИКЛЫ:</b> {TOKEN_TRANSFER_STATS['cycles_completed']}

🚨 <b>Ошибки:</b> {len(TOKEN_TRANSFER_STATS['errors'])}
✅ <b>Успешные tx:</b> {len(TOKEN_TRANSFER_STATS['successful_txs'])}
        """
        
        send_telegram_notification(
            notif_type="success",
            title="📊 Завершение работы модуля токенов",
            message=stats_message,
            main_title="ETHmachine Token Transfer Completed"
        )

        # Отправляем файл результатов если есть
        result_file = "result/token_transfer_result.csv"
        if os.path.exists(result_file):
            send_telegram_file(
                file_path=result_file,
                caption="📄 Результаты переводов токенов",
                main_title="ETHmachine Token Results"
            )

def get_network_rpc(network):
    """Получение RPC URL для сети"""
    from config.networks import get_network_rpc_urls
    import random
    
    rpc_urls = get_network_rpc_urls(network)
    if not rpc_urls:
        raise Exception(f"Неизвестная сеть: {network}")
    return random.choice(rpc_urls)

def get_proxy_list():
    """Получение списка прокси"""
    from modules.data_manager import get_proxies
    proxies = get_proxies()

    if not proxies:
        logger.error("ВНИМАНИЕ: В файле data/data.csv не найдено ни одного прокси!")
        input(Fore.YELLOW + "Добавьте прокси в файл data/data.csv и нажмите Enter для продолжения, либо Ctrl+C для выхода...")

    return proxies

def get_web3_with_proxy(rpc_url, proxy_url):
    """Создание Web3 подключения с прокси"""
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
        
        # Проверяем соединение
        _ = w3.eth.chain_id
        return w3, session
        
    except Exception as e:
        logger.error(f"ВНИМАНИЕ: Ошибка подключения через прокси или RPC недоступен: {e}")
        # Возвращаем обычное соединение без прокси
        provider = HTTPProvider(rpc_url)
        w3 = Web3(provider)
        return w3, None

def get_token_balance(w3, token_address, wallet_address):
    """Получение баланса токена"""
    try:
        contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        balance = contract.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()
        return balance
    except Exception as e:
        logger.error(f"Ошибка получения баланса токена: {e}")
        return 0

def get_token_decimals(w3, token_address):
    """Получение количества десятичных знаков токена"""
    try:
        contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        decimals = contract.functions.decimals().call()
        return decimals
    except Exception as e:
        logger.warning(f"Не удалось получить decimals токена, используем 18 по умолчанию: {e}")
        return 18

def get_token_symbol(w3, token_address):
    """Получение символа токена"""
    try:
        contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        symbol = contract.functions.symbol().call()
        return symbol
    except Exception as e:
        logger.warning(f"Не удалось получить символ токена: {e}")
        return "TOKEN"

def parse_amount_range(amount_str):
    """
    Парсит строку с диапазоном для amount токенов.
    Поддерживает:
    - "10-20%" - процент от баланса токена
    - "10-20token" - фиксированное количество токенов
    - "10%" - фиксированный процент
    - "10token" - фиксированное количество
    """
    try:
        amount_str = amount_str.strip()
        
        # Проверяем, есть ли в строке "%"
        if amount_str.endswith('%'):
            # Процентное значение
            percent_str = amount_str[:-1].strip()
            if '-' in percent_str:
                parts = percent_str.split('-')
                if len(parts) == 2:
                    return float(parts[0]), float(parts[1]), 'PERCENT'
                else:
                    val = float(parts[0])
                    return val, val, 'PERCENT'
            else:
                val = float(percent_str)
                return val, val, 'PERCENT'
        elif amount_str.lower().endswith('token'):
            # Фиксированное количество токенов
            token_str = amount_str[:-5].strip()  # Убираем 'token'
            if '-' in token_str:
                parts = token_str.split('-')
                if len(parts) == 2:
                    return float(parts[0]), float(parts[1]), 'FIXED'
                else:
                    val = float(parts[0])
                    return val, val, 'FIXED'
            else:
                val = float(token_str)
                return val, val, 'FIXED'
        else:
            # Если нет суффикса, считаем процентами по умолчанию
            if '-' in amount_str:
                parts = amount_str.split('-')
                if len(parts) == 2:
                    return float(parts[0]), float(parts[1]), 'PERCENT'
                else:
                    val = float(parts[0])
                    return val, val, 'PERCENT'
            else:
                val = float(amount_str)
                return val, val, 'PERCENT'
    except Exception:
        return 100, 100, 'PERCENT'  # По умолчанию 100%

def apply_trim_to_amount(amount):
    """Применяет обрезку к количеству токенов"""
    if trim_the_number_of_characters_enable_token and trim_the_number_of_characters_token:
        trim_digits = random.choice(trim_the_number_of_characters_token)
        return round(amount, trim_digits)
    return amount

def get_nonce_safe(w3, address, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    """Безопасное получение nonce"""
    for attempt in range(max_attempts):
        try:
            return w3.eth.get_transaction_count(address)
        except Exception as e:
            logger.warning(f"[{address}] Ошибка получения nonce (попытка {attempt+1}/{max_attempts}): {e}")
            time.sleep(sleep_sec)
    logger.error(f"[{address}] Не удалось получить nonce после {max_attempts} попыток.")
    return None

def estimate_gas_safe(w3, tx, max_attempts=TX_SEND_ATTEMPTS, sleep_sec=2):
    """Безопасная оценка газа"""
    for attempt in range(max_attempts):
        try:
            gas = w3.eth.estimate_gas(tx)
            return int(gas * GAS_LIMIT_MULTIPLIER_TOKEN)
        except KeyboardInterrupt:
            logger.error("\nОперация прервана пользователем (Ctrl+C). Завершение работы.")
            raise
        except Exception as e:
            logger.warning(f"Не удалось оценить газ (попытка {attempt+1}/{max_attempts}): {e}")
            time.sleep(sleep_sec)
    return int(100000 * GAS_LIMIT_MULTIPLIER_TOKEN)  # Используем стандартный лимит газа для токенов

def validate_wallet_format(wallet_value, expected_type, row_index):
    """Проверяет формат кошелька"""
    if not wallet_value or not isinstance(wallet_value, str):
        return False, f"Пустое значение кошелька"
    
    wallet_value = wallet_value.strip()
    
    if expected_type == 0:  # Приватный ключ
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
    
    elif expected_type == 1:  # Адрес кошелька
        if wallet_value.startswith('0x') and len(wallet_value) == 42:
            try:
                int(wallet_value, 16)
                return True, "OK"
            except ValueError:
                return False, f"Неверный формат адреса кошелька (не hex)"
        else:
            return False, f"Неверный формат адреса кошелька (должен начинаться с 0x и быть длиной 42 символа, получено {len(wallet_value)})"
    
    return False, f"Неизвестный тип кошелька: {expected_type}"

def validate_token_transfer_data(transfer_data):
    """Проверяет данные переводов токенов на корректность"""
    errors = []
    
    for idx, row in enumerate(transfer_data, start=1):
        # Проверяем from_wallet (всегда должен быть приватный ключ)
        is_valid, error_msg = validate_wallet_format(row.get('from_wallet', ''), 0, idx)
        if not is_valid:
            errors.append(f"Строка {idx}, поле 'from_wallet': {error_msg}")
        
        # Проверяем intermediary (если используется)
        if USE_INTERMEDIARY_TOKEN:
            intermediary = row.get('intermediary', '').strip()
            if intermediary:
                is_valid, error_msg = validate_wallet_format(intermediary, 0, idx)
                if not is_valid:
                    errors.append(f"Строка {idx}, поле 'intermediary': {error_msg}")
        
        # Проверяем to_wallet
        is_valid, error_msg = validate_wallet_format(row.get('to_wallet', ''), TYPE_VALUE_TO_WALLET_TOKEN, idx)
        if not is_valid:
            wallet_type_name = "приватный ключ" if TYPE_VALUE_TO_WALLET_TOKEN == 0 else "адрес кошелька"
            errors.append(f"Строка {idx}, поле 'to_wallet' (ожидается {wallet_type_name}): {error_msg}")
        
        # Проверяем наличие поля amount
        if not row.get('amount', '').strip():
            errors.append(f"Строка {idx}, поле 'amount': отсутствует количество для перевода")
    
    return errors

def get_to_wallet_address(to_wallet_value):
    """Получает адрес кошелька получателя"""
    if TYPE_VALUE_TO_WALLET_TOKEN == 0:
        # to_wallet - это приватный ключ
        try:
            to_acc = Account.from_key(to_wallet_value)
            return to_acc.address, to_wallet_value
        except Exception as e:
            raise Exception(f"Ошибка создания аккаунта из приватного ключа: {e}")
    elif TYPE_VALUE_TO_WALLET_TOKEN == 1:
        # to_wallet - это уже адрес
        try:
            checksum_address = Web3.to_checksum_address(to_wallet_value)
            return checksum_address, None
        except Exception as e:
            raise Exception(f"Ошибка преобразования адреса в checksum формат: {e}")
    else:
        raise Exception(f"Неизвестный тип TYPE_VALUE_TO_WALLET_TOKEN: {TYPE_VALUE_TO_WALLET_TOKEN}")

def append_token_result_csv(row):
    """Записывает результат в CSV файл"""
    filename = "result/token_transfer_result.csv"
    header = [
        "datetime", "from_wallet", "from_address", "intermediary_wallet", "intermediary_address",
        "to_wallet", "to_address", "token_symbol", "token_address", "amount_sent", "tx_hash_1", "tx_hash_2",
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
        logger.error(f"Ошибка записи в result/token_transfer_result.csv: {e}")

def countdown_timer(seconds, message_prefix="Пауза"):
    """Отсчет времени до следующей транзакции"""
    for remaining in range(seconds, 0, -1):
        print(
            f"{Fore.YELLOW}{message_prefix} {remaining} сек до следующей транзакции...{Style.RESET_ALL} ",
            end="\r",
            flush=True,
        )
        time.sleep(1)
    print("\r" + " " * 80 + "\r", end="")

def transfer_erc20_tokens(from_priv, intermediary_priv, to_wallet_value, network, token_address, token_symbol, amount, proxy=None, delay_between=0):
    """Основная функция для перевода токенов ERC-20"""
    session = None
    try:
        start_time = time.time()
        dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        rpc_url = get_network_rpc(network)
        proxies = get_proxy_list()
        use_proxy = proxy if proxy else (random.choice(proxies) if proxies else None)

        # Создаем аккаунты
        try:
            from_acc = Account.from_key(from_priv)
            to_address, to_priv = get_to_wallet_address(to_wallet_value)
            
            if USE_INTERMEDIARY_TOKEN and intermediary_priv and intermediary_priv.strip():
                intermediary_acc = Account.from_key(intermediary_priv)
                use_intermediary = True
            else:
                intermediary_acc = None
                use_intermediary = False
                
        except Exception as e:
            error_msg = f"Ошибка создания аккаунта: {e}"
            if not MULTI_THREADING_TOKEN:
                logger.error(error_msg)
            update_token_stats(success=False, error_msg=error_msg)
            if TELEGRAM_LOG_LEVEL_transfer_token == 2:
                send_telegram_notification(
                    notif_type="error",
                    title="❌ Ошибка создания аккаунта",
                    message=str(e),
                    wallet_address=from_priv[:10] + "...",
                    main_title="ETHmachine Token Transfer Error"
                )
            return

        # Подключаемся к сети
        w3, session = get_web3_with_proxy(rpc_url, use_proxy)
        explorer_url = get_explorer_url(network)

        # Получаем информацию о токене
        token_decimals = get_token_decimals(w3, token_address)
        token_symbol_actual = get_token_symbol(w3, token_address) if not token_symbol else token_symbol

        if not MULTI_THREADING_TOKEN:
            logger.info("="*61)
            logger.info(f"[{dt_str}] Запуск {'цепочки' if use_intermediary else 'прямого'} перевода токенов:")
            logger.info(f"  FROM:         priv - {from_priv[:10]}... | wallet - {from_acc.address[:10]}...")
            if use_intermediary:
                logger.info(f"  INTERMEDIARY: priv - {intermediary_priv[:10]}... | wallet - {intermediary_acc.address[:10]}...")
            logger.info(f"  TO:           {'priv - ' + to_priv[:10] + '... | ' if to_priv else ''}wallet - {to_address[:10]}...")
            logger.info(f"  Сеть:         {network}")
            logger.info(f"  Токен:        {token_symbol_actual} ({token_address[:10]}...)")
            logger.info(f"  Decimals:     {token_decimals}")
            logger.info(f"  Режим:        {'Через посредника' if use_intermediary else 'Напрямую'}")
            logger.info("-"*61)

        # Проверяем баланс токена отправителя
        token_balance = get_token_balance(w3, token_address, from_acc.address)
        if token_balance == 0:
            error_msg = f"Баланс токена {token_symbol_actual} равен 0 на кошельке {from_acc.address}"
            if not MULTI_THREADING_TOKEN:
                logger.error(error_msg)
            update_token_stats(success=False, error_msg=error_msg)
            return

        # Проверяем баланс нативного токена для газа
        eth_balance = w3.eth.get_balance(from_acc.address)
        min_gas_balance = w3.to_wei(random.uniform(MIN_FROM_BALANCE_TOKEN[0], MIN_FROM_BALANCE_TOKEN[1]), 'ether')
        if eth_balance < min_gas_balance:
            error_msg = f"Недостаточно нативного токена для газа: {w3.from_wei(eth_balance, 'ether'):.6f} ETH < {w3.from_wei(min_gas_balance, 'ether'):.6f} ETH"
            if not MULTI_THREADING_TOKEN:
                logger.error(error_msg)
            update_token_stats(success=False, error_msg=error_msg)
            return

        # Рассчитываем количество токенов для отправки
        amount_from, amount_to, amount_type = parse_amount_range(amount)
        
        if amount_type == 'PERCENT':
            # Процент от баланса токена
            percent = random.uniform(amount_from, amount_to)
            send_amount_raw = int(token_balance * percent / 100)
            if not MULTI_THREADING_TOKEN:
                logger.info(f"  Процент:      {percent:.2f}% от баланса токена")
        else:
            # Фиксированное количество
            amount_tokens = random.uniform(amount_from, amount_to)
            # Применяем обрезку
            amount_tokens = apply_trim_to_amount(amount_tokens)
            send_amount_raw = int(amount_tokens * (10 ** token_decimals))
            if not MULTI_THREADING_TOKEN:
                logger.info(f"  Количество:   {amount_tokens:.6f} {token_symbol_actual}")

        if send_amount_raw > token_balance:
            send_amount_raw = token_balance
            if not MULTI_THREADING_TOKEN:
                logger.warning(f"⚠️ Запрошенное количество больше баланса, будет отправлен весь баланс")

        send_amount_formatted = send_amount_raw / (10 ** token_decimals)

        # Получаем цену газа
        try:
            gas_price = w3.eth.gas_price
            max_fee = int(gas_price * GAS_PRICE_MULTIPLIER_TOKEN)
            max_priority_fee = max(1, int(gas_price * 0.01))
        except Exception as e:
            if not MULTI_THREADING_TOKEN:
                logger.warning(f"Ошибка получения цены газа: {e}")
            gas_price = int(w3.to_wei('30', 'gwei'))
            max_fee = int(gas_price * GAS_PRICE_MULTIPLIER_TOKEN)
            max_priority_fee = int(w3.to_wei('1', 'gwei'))

        if use_intermediary:
            # Логика с посредником для токенов
            logger.info("🔄 Начинаем перевод через посредника для токенов...")
            
            # Первая транзакция: from -> intermediary
            nonce_from = get_nonce_safe(w3, from_acc.address)
            if nonce_from is None:
                logger.error(f"Не удалось получить nonce для {from_acc.address}")
                return

            # Создаем контракт токена
            token_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
            
            # Создаем транзакцию для transfer от from к intermediary
            tx1_data = token_contract.functions.transfer(
                Web3.to_checksum_address(intermediary_acc.address),
                send_amount_raw
            ).build_transaction({
                'type': 0x2,
                'from': Web3.to_checksum_address(from_acc.address),
                'nonce': nonce_from,
                'chainId': w3.eth.chain_id,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': max_priority_fee,
                'gas': 1000000
            })

            # Оцениваем газ для первой транзакции
            gas_limit1 = estimate_gas_safe(w3, tx1_data)
            tx1_data['gas'] = gas_limit1

            # Отправляем первую транзакцию
            tx_hash1 = None
            for attempt in range(TX_SEND_ATTEMPTS):
                try:
                    signed_tx1 = w3.eth.account.sign_transaction(tx1_data, from_priv)
                    if not MULTI_THREADING_TOKEN:
                        logger.info(f"[{dt_str}] Отправка токенов {token_symbol_actual} from -> intermediary...")
                    
                    tx_hash1 = w3.eth.send_raw_transaction(signed_tx1.rawTransaction)
                    tx_hash1_hex = w3.to_hex(tx_hash1)
                    
                    if not MULTI_THREADING_TOKEN:
                        logger.success(f"✅ Успешно отправлено {send_amount_formatted:.6f} {token_symbol_actual} на посредника. Tx hash: {tx_hash1_hex}")

                    # Уведомление о первой транзакции
                    if TELEGRAM_LOG_LEVEL_transfer_token == 2:
                        send_telegram_notification(
                            notif_type="tx",
                            title="📤 Транзакция токенов отправлена (1/2)",
                            message="from → intermediary",
                            wallet_address=from_acc.address[:10] + "...",
                            tx_hash=tx_hash1_hex[:10] + "...",
                            explorer_url=explorer_url,
                            token=token_symbol_actual,
                            amount=f"{send_amount_formatted:.6f} {token_symbol_actual}",
                            main_title="ETHmachine Token Transfer"
                        )
                    break
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки токенов from -> intermediary (попытка {attempt+1}): {e}")
                    if attempt == TX_SEND_ATTEMPTS - 1:
                        update_token_stats(success=False, error_msg=f"Ошибка отправки токенов from->intermediary: {e}")
                        if TELEGRAM_LOG_LEVEL_transfer_token == 2:
                            send_telegram_notification(
                                notif_type="error",
                                title="❌ Ошибка транзакции токенов (1/2)",
                                message=f"from → intermediary: {e}",
                                wallet_address=from_acc.address,
                                main_title="ETHmachine Token Transfer Error"
                            )
                    tx1_data['nonce'] += 1
                    time.sleep(3)
            else:
                logger.error("❌ Не удалось отправить токены from -> intermediary после нескольких попыток.")
                return

            # Ждем подтверждения первой транзакции
            if not MULTI_THREADING_TOKEN:
                logger.info("⏳ Ожидание подтверждения первой транзакции...")
            
            time.sleep(WHAITE_TRANSACTION_PENDING)
            for attempt in range(WHAITE_TRANSACTION_PENDING_COUNT):
                try:
                    receipt1 = w3.eth.get_transaction_receipt(tx_hash1)
                    if receipt1 and receipt1.status == 1:
                        logger.success(f"✅ Первая транзакция подтверждена. Tx hash: {tx_hash1_hex}")
                        break
                    elif receipt1 and receipt1.status == 0:
                        logger.error(f"❌ Первая транзакция неуспешна. Tx hash: {tx_hash1_hex}")
                        return
                except Exception as e:
                    if not MULTI_THREADING_TOKEN:
                        logger.warning(f"⏳ Первая транзакция в ожидании (попытка {attempt+1}/{WHAITE_TRANSACTION_PENDING_COUNT}): {e}")
                time.sleep(WHAITE_TRANSACTION_PENDING)
            else:
                logger.error(f"❌ Первая транзакция остается в состоянии pending после {WHAITE_TRANSACTION_PENDING_COUNT} попыток.")

            # Проверяем баланс посредника
            intermediary_token_balance = get_token_balance(w3, token_address, intermediary_acc.address)
            if intermediary_token_balance <= 0:
                logger.error(f"Баланс токенов {token_symbol_actual} на посреднике равен 0, пропуск второй транзакции.")
                return

            # Вторая транзакция: intermediary -> to
            nonce_intermediary = get_nonce_safe(w3, intermediary_acc.address)
            if nonce_intermediary is None:
                logger.error(f"Не удалось получить nonce для посредника {intermediary_acc.address}")
                return

            # Отправляем весь баланс токенов с посредника
            tx2_data = token_contract.functions.transfer(
                Web3.to_checksum_address(to_address),
                intermediary_token_balance
            ).build_transaction({
                'type': 0x2,
                'from': Web3.to_checksum_address(intermediary_acc.address),
                'nonce': nonce_intermediary,
                'chainId': w3.eth.chain_id,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': max_priority_fee,
                'gas': 1000000
            })

            # Оцениваем газ для второй транзакции
            gas_limit2 = estimate_gas_safe(w3, tx2_data)
            tx2_data['gas'] = gas_limit2

            # Отправляем вторую транзакцию
            tx_hash2 = None
            intermediary_amount_formatted = intermediary_token_balance / (10 ** token_decimals)
            
            for attempt in range(TX_SEND_ATTEMPTS):
                try:
                    signed_tx2 = w3.eth.account.sign_transaction(tx2_data, intermediary_priv)
                    if not MULTI_THREADING_TOKEN:
                        logger.info(f"[{dt_str}] Отправка токенов {token_symbol_actual} intermediary -> to...")
                    
                    tx_hash2 = w3.eth.send_raw_transaction(signed_tx2.rawTransaction)
                    tx_hash2_hex = w3.to_hex(tx_hash2)
                    
                    if not MULTI_THREADING_TOKEN:
                        logger.success(f"✅ Успешно отправлено {intermediary_amount_formatted:.6f} {token_symbol_actual} на получателя. Tx hash: {tx_hash2_hex}")

                    # Уведомление о второй транзакции
                    if TELEGRAM_LOG_LEVEL_transfer_token == 2:
                        send_telegram_notification(
                            notif_type="tx",
                            title="📤 Транзакция токенов отправлена (2/2)",
                            message="intermediary → to",
                            wallet_address=to_address[:10] + "...",
                            tx_hash=tx_hash2_hex[:10] + "...",
                            explorer_url=explorer_url,
                            token=token_symbol_actual,
                            amount=f"{intermediary_amount_formatted:.6f} {token_symbol_actual}",
                            main_title="ETHmachine Token Transfer"
                        )
                    break
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки токенов intermediary -> to (попытка {attempt+1}): {e}")
                    if attempt == TX_SEND_ATTEMPTS - 1:
                        update_token_stats(success=False, error_msg=f"Ошибка отправки токенов intermediary->to: {e}")
                        if TELEGRAM_LOG_LEVEL_transfer_token == 2:
                            send_telegram_notification(
                                notif_type="error",
                                title="❌ Ошибка транзакции токенов (2/2)",
                                message=f"intermediary → to: {e}",
                                wallet_address=to_address,
                                main_title="ETHmachine Token Transfer Error"
                            )
                    tx2_data['nonce'] += 1
                    time.sleep(3)
            else:
                logger.error("❌ Не удалось отправить токены intermediary -> to после нескольких попыток.")
                return

            # Записываем результат для цепочки транзакций
            append_token_result_csv({
                "datetime": dt_str,
                "from_wallet": from_priv,
                "from_address": from_acc.address,
                "intermediary_wallet": intermediary_priv,
                "intermediary_address": intermediary_acc.address,
                "to_wallet": to_wallet_value,
                "to_address": to_address,
                "token_symbol": token_symbol_actual,
                "token_address": token_address,
                "amount_sent": send_amount_formatted,
                "tx_hash_1": tx_hash1_hex,
                "tx_hash_2": tx_hash2_hex,
                "explorer_link_1": f"{explorer_url}{tx_hash1_hex}",
                "explorer_link_2": f"{explorer_url}{tx_hash2_hex}",
            })

            # Обновляем статистику для двух транзакций
            update_token_stats(success=True, amount=send_amount_formatted, tx_hash=tx_hash1_hex)
            update_token_stats(success=True, amount=intermediary_amount_formatted, tx_hash=tx_hash2_hex)
            
            # Итоговое уведомление о завершении цепочки
            if TELEGRAM_LOG_LEVEL_transfer_token >= 1:
                to_token_balance = get_token_balance(w3, token_address, to_address)
                to_token_balance_formatted = to_token_balance / (10 ** token_decimals)
                
                send_telegram_notification(
                    notif_type="success",
                    title="✅ Цепочка переводов токенов завершена",
                    message=f"from → intermediary → to",
                    wallet_address=f"{from_acc.address[:10]}...→{to_address[:10]}...",
                    token=token_symbol_actual,
                    balance=f"{to_token_balance_formatted:.6f} {token_symbol_actual}",
                    tx1=tx_hash1_hex[:10] + "...",
                    tx2=tx_hash2_hex[:10] + "...",
                    total_amount=f"{send_amount_formatted:.6f} {token_symbol_actual}",
                    main_title="ETHmachine Token Transfer Success"
                )

            # Финальный вывод для цепочки
            if not MULTI_THREADING_TOKEN:
                logger.success("=" * 60)
                logger.success(f"TX1: {explorer_url}{tx_hash1_hex}")
                logger.success(f"TX2: {explorer_url}{tx_hash2_hex}")
                logger.success(f"from_wallet ({from_acc.address}) - {send_amount_formatted:.6f} {token_symbol_actual}")
                logger.success(f"Баланс to_wallet ({to_address}) по завершению - {to_token_balance_formatted:.6f} {token_symbol_actual}")
                logger.success("=" * 60 + "\n")

        else:
            # Прямой перевод токенов
            nonce = get_nonce_safe(w3, from_acc.address)
            if nonce is None:
                logger.error(f"Не удалось получить nonce для {from_acc.address}")
                return

            # Создаем контракт токена
            token_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
            
            # Создаем транзакцию для transfer
            tx_data = token_contract.functions.transfer(
                Web3.to_checksum_address(to_address),
                send_amount_raw
            ).build_transaction({
                'type': 0x2,
                'from': Web3.to_checksum_address(from_acc.address),
                'nonce': nonce,
                'chainId': w3.eth.chain_id,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': max_priority_fee,
                'gas': 1000000  # Временно, будет пересчитано
            })

            # Оцениваем газ
            gas_limit = estimate_gas_safe(w3, tx_data)
            tx_data['gas'] = gas_limit

            # Отправляем транзакцию
            tx_hash = None
            for attempt in range(TX_SEND_ATTEMPTS):
                try:
                    signed_tx = w3.eth.account.sign_transaction(tx_data, from_priv)
                    if not MULTI_THREADING_TOKEN:
                        logger.info(f"[{dt_str}] Отправка токенов {token_symbol_actual}...")
                    
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                    tx_hash_hex = w3.to_hex(tx_hash)
                    
                    if not MULTI_THREADING_TOKEN:
                        logger.success(f"✅ Успешно отправлено {send_amount_formatted:.6f} {token_symbol_actual}. Tx hash: {tx_hash_hex}")

                    break
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки токенов (попытка {attempt+1}): {e}")
                    if attempt == TX_SEND_ATTEMPTS - 1:
                        update_token_stats(success=False, error_msg=f"Ошибка отправки токенов: {e}")
                        if TELEGRAM_LOG_LEVEL_transfer_token == 2:
                            send_telegram_notification(
                                notif_type="error",
                                title="❌ Ошибка отправки токенов",
                                message=f"{token_symbol_actual}: {e}",
                                wallet_address=from_acc.address,
                                main_title="ETHmachine Token Transfer Error"
                            )
                    tx_data['nonce'] += 1
                    time.sleep(3)
            else:
                logger.error("❌ Не удалось отправить токены после нескольких попыток.")
                return

            # Ждем подтверждения
            if not MULTI_THREADING_TOKEN:
                logger.info("Ожидание подтверждения транзакции...")
            
            time.sleep(WHAITE_TRANSACTION_PENDING)
            for attempt in range(WHAITE_TRANSACTION_PENDING_COUNT):
                try:
                    receipt = w3.eth.get_transaction_receipt(tx_hash)
                    if receipt and receipt.status == 1:
                        logger.success(f"✅ Транзакция подтверждена. Tx hash: {explorer_url}{tx_hash_hex}")
                        break
                    elif receipt and receipt.status == 0:
                        logger.error(f"❌ Транзакция неуспешна. Tx hash: {explorer_url}{tx_hash_hex}")
                        break
                except Exception as e:
                    if not MULTI_THREADING_TOKEN:
                        logger.warning(f"⏳ Транзакция в ожидании (попытка {attempt+1}/{WHAITE_TRANSACTION_PENDING_COUNT}): {e}")
                time.sleep(WHAITE_TRANSACTION_PENDING)
            else:
                logger.error(f"❌ Транзакция остается в состоянии pending после {WHAITE_TRANSACTION_PENDING_COUNT} попыток.")

            # Записываем результат
            append_token_result_csv({
                "datetime": dt_str,
                "from_wallet": from_priv,
                "from_address": from_acc.address,
                "intermediary_wallet": "",
                "intermediary_address": "",
                "to_wallet": to_wallet_value,
                "to_address": to_address,
                "token_symbol": token_symbol_actual,
                "token_address": token_address,
                "amount_sent": send_amount_formatted,
                "tx_hash_1": tx_hash_hex,
                "tx_hash_2": "",
                "explorer_link_1": f"{explorer_url}{tx_hash_hex}",
                "explorer_link_2": "",
            })

            # Обновляем статистику
            update_token_stats(success=True, amount=send_amount_formatted, tx_hash=tx_hash_hex)
            
            # Отправляем уведомление о завершении
            if TELEGRAM_LOG_LEVEL_transfer_token >= 1:
                to_token_balance = get_token_balance(w3, token_address, to_address)
                to_token_balance_formatted = to_token_balance / (10 ** token_decimals)
                
                send_telegram_notification(
                    notif_type="success",
                    title="✅ Перевод токенов завершен",
                    message=f"from → to",
                    wallet_address=f"{from_acc.address[:10]}...→{to_address[:10]}...",
                    token=token_symbol_actual,
                    balance=f"{to_token_balance_formatted:.6f} {token_symbol_actual}",
                    tx_hash=tx_hash_hex[:10] + "...",
                    amount=f"{send_amount_formatted:.6f} {token_symbol_actual}",
                    main_title="ETHmachine Token Transfer Success"
                )

            # Финальный вывод
            if not MULTI_THREADING_TOKEN:
                logger.success("=" * 60)
                logger.success(f"{explorer_url}{tx_hash_hex}")
                logger.success(f"from_wallet ({from_acc.address}) - {send_amount_formatted:.6f} {token_symbol_actual}")
                logger.success(f"Баланс to_wallet ({to_address}) по завершению - {to_token_balance_formatted:.6f} {token_symbol_actual}")
                logger.success("=" * 60 + "\n")

    except Exception as e:
        logger.error(f"Ошибка в процессе перевода токенов: {e}")
        update_token_stats(success=False, error_msg=str(e))
        if TELEGRAM_LOG_LEVEL_transfer_token == 2:
            send_telegram_notification(
                notif_type="error",
                title="❌ Ошибка в процессе перевода токенов",
                message=str(e),
                wallet_address=from_priv[:10] + "...",
                main_title="ETHmachine Token Transfer Error"
            )
    finally:
        if session:
            session.close()

def check_token_balances_for_loop(transfer_data, network, token_address, token_symbol, proxies):
    """Проверяет балансы токенов для принятия решения о продолжении цикла"""
    logger.info(f"🔍 Проверка балансов токенов {token_symbol.upper()}...")
    
    # Генерируем случайные пороговые значения
    min_from_balance = random.uniform(expected_balance_from_wallet_token[0], expected_balance_from_wallet_token[1])
    max_to_balance = random.uniform(expected_balance_to_wallet_token[0], expected_balance_to_wallet_token[1])
    
    logger.info(f"Проверка балансов: минимальный from_wallet = {min_from_balance:.6f} {token_symbol.upper()}, максимальный to_wallet = {max_to_balance:.6f} {token_symbol.upper()}")
    
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
            to_address, _ = get_to_wallet_address(row['to_wallet'])
            
            # Получаем информацию о токене
            token_decimals = get_token_decimals(w3, token_address)
            
            # Получаем балансы токенов
            from_token_balance_raw = get_token_balance(w3, token_address, from_acc.address)
            to_token_balance_raw = get_token_balance(w3, token_address, to_address)
            
            from_token_balance = from_token_balance_raw / (10 ** token_decimals)
            to_token_balance = to_token_balance_raw / (10 ** token_decimals)
            
            # Проверяем условия
            if from_token_balance >= min_from_balance and to_token_balance <= max_to_balance:
                valid_wallets.append(row)
                logger.info(f"✅ {from_acc.address[:10]}... - баланс {from_token_balance:.6f} {token_symbol.upper()} (подходит)")
            else:
                logger.warning(f"❌ {from_acc.address[:10]}... - from: {from_token_balance:.6f}, to: {to_token_balance:.6f} {token_symbol.upper()} (не подходит)")
                
        except Exception as e:
            logger.error(f"❌ Ошибка проверки баланса для {row.get('from_wallet', 'UNKNOWN')[:10]}...: {e}")
        finally:
            if session:
                session.close()
    
    return valid_wallets

def process_token_transfers_loop(transfer_data, proxies, network, delay_between, token_address, token_symbol):
    """Циклическая обработка переводов токенов"""
    if not transfer_data:
        logger.error("Нет данных для циклической обработки")
        return
    
    # Инициализируем статистику
    init_token_stats(network, token_symbol, USE_INTERMEDIARY_TOKEN, True)
    
    logger.info(f"🔄 Запуск циклической обработки переводов токенов {token_symbol.upper()}")
    logger.info(f"Количество циклов: {loop_transfer_count_token}")
    logger.info(f"Задержка между циклами: {sleep_time_between_loops_token[0]}-{sleep_time_between_loops_token[1]} сек")
    
    for cycle in range(loop_transfer_count_token):
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🔄 ЦИКЛ {cycle + 1}/{loop_transfer_count_token}")
            logger.info(f"{'='*60}")
            
            # Проверяем балансы и фильтруем подходящие кошельки
            valid_wallets = check_token_balances_for_loop(transfer_data, network, token_address, token_symbol, proxies)
            
            if not valid_wallets:
                logger.warning(f"❌ Цикл {cycle + 1}: Нет подходящих кошельков для отправки токенов")
                TOKEN_TRANSFER_STATS["cycles_completed"] += 1
                if cycle < loop_transfer_count_token - 1:
                    sleep_time = random.randint(sleep_time_between_loops_token[0], sleep_time_between_loops_token[1])
                    logger.info(f"⏳ Ожидание {sleep_time} сек до следующего цикла...")
                    time.sleep(sleep_time)
                continue
            
            logger.info(f"✅ Найдено {len(valid_wallets)} подходящих кошельков для цикла {cycle + 1}")
            
            # Обрабатываем валидные кошельки
            successful_in_cycle = 0
            for idx, row in enumerate(valid_wallets):
                try:
                    logger.info(f"\n[Цикл {cycle + 1}] [{idx+1}/{len(valid_wallets)}] Обработка кошелька {row['from_wallet'][:10]}...")
                    
                    transfer_erc20_tokens(
                        from_priv=row['from_wallet'],
                        intermediary_priv=row.get('intermediary', ''),
                        to_wallet_value=row['to_wallet'],
                        network=network,
                        token_address=token_address,
                        token_symbol=token_symbol,
                        amount=row['amount'],
                        proxy=None,
                        delay_between=delay_between
                    )
                    
                    successful_in_cycle += 1
                    TOKEN_TRANSFER_STATS["wallets_processed"] += 1
                    
                    # Задержка между транзакциями в цикле
                    if delay_between > 0 and idx < len(valid_wallets) - 1:
                        countdown_timer(delay_between, f"Пауза в цикле {cycle + 1}")
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки кошелька в цикле {cycle + 1}: {e}")
                    TOKEN_TRANSFER_STATS["wallets_failed"] += 1
            
            TOKEN_TRANSFER_STATS["cycles_completed"] += 1
            logger.info(f"✅ Цикл {cycle + 1} завершен. Успешно обработано: {successful_in_cycle}/{len(valid_wallets)} кошельков")
            
            # Отправляем уведомление о завершении цикла
            if TELEGRAM_LOG_LEVEL_transfer_token >= 1:
                send_telegram_notification(
                    notif_type="info",
                    title=f"🔄 Цикл {cycle + 1} завершен",
                    message=f"Обработано {successful_in_cycle}/{len(valid_wallets)} кошельков",
                    token=token_symbol.upper(),
                    cycle=f"{cycle + 1}/{loop_transfer_count_token}",
                    main_title="ETHmachine Token Transfer Cycle"
                )
            
            # Задержка между циклами
            if cycle < loop_transfer_count_token - 1:
                sleep_time = random.randint(sleep_time_between_loops_token[0], sleep_time_between_loops_token[1])
                logger.info(f"⏳ Ожидание {sleep_time} сек до следующего цикла...")
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.warning(f"\n⚠️ Прерывание пользователем на цикле {cycle + 1}")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле {cycle + 1}: {e}")
            TOKEN_TRANSFER_STATS["cycles_completed"] += 1
    
    logger.info(f"\n🏁 Циклическая обработка завершена. Выполнено циклов: {TOKEN_TRANSFER_STATS['cycles_completed']}")
    
    # Завершаем статистику
    finalize_token_stats()

def process_token_transfers_normal(transfer_data, proxies, network, delay_between, token_address, token_symbol):
    """Обычная обработка переводов токенов без зацикливания"""
    # Проверяем, включена ли циклическая обработка
    if loop_transfer_enable_token:
        return process_token_transfers_loop(transfer_data, proxies, network, delay_between, token_address, token_symbol)
    
    # Инициализируем статистику
    init_token_stats(network, token_symbol, USE_INTERMEDIARY_TOKEN, False)
    
    # Валидация данных
    validation_errors = validate_token_transfer_data(transfer_data)
    if validation_errors:
        logger.error("❌ Ошибки валидации данных:")
        for error in validation_errors:
            logger.error(f"  {error}")
        logger.error("\nИсправьте ошибки в файле data/transfer_token.csv и запустите снова.")
        return

    logger.success("✅ Валидация данных прошла успешно")
    
    # Обработка в зависимости от режима многопоточности
    if MULTI_THREADING_TOKEN:
        return process_token_transfers_multithreaded(transfer_data, proxies, network, delay_between, token_address, token_symbol)
    
    # Однопоточная обработка
    total_wallets = len(transfer_data)
    for idx, row in enumerate(transfer_data):
        try:
            logger.info(f"\n[{idx+1}/{total_wallets}] Обработка кошелька {row['from_wallet'][:10]}...")
            
            transfer_erc20_tokens(
                from_priv=row['from_wallet'],
                intermediary_priv=row.get('intermediary', ''),
                to_wallet_value=row['to_wallet'],
                network=network,
                token_address=token_address,
                token_symbol=token_symbol,
                amount=row['amount'],
                proxy=None,
                delay_between=delay_between
            )
            
            TOKEN_TRANSFER_STATS["wallets_processed"] += 1
            
            # Задержка между транзакциями
            if delay_between > 0 and idx < total_wallets - 1:
                countdown_timer(delay_between, "Пауза между транзакциями")
            
        except Exception as e:
            logger.error(f"Ошибка обработки кошелька {row.get('from_wallet', 'UNKNOWN')[:10]}...: {e}")
            TOKEN_TRANSFER_STATS["wallets_failed"] += 1
    
    # Завершаем статистику
    finalize_token_stats()

def process_token_transfers_multithreaded(transfer_data, proxies, network, delay_between, token_address, token_symbol):
    """Многопоточная обработка переводов токенов"""
    logger.info(f"🚀 Запуск многопоточной обработки с {NUM_THREADS_TOKEN} потоками")
    
    def process_single_transfer(row_with_index):
        idx, row = row_with_index
        try:
            transfer_erc20_tokens(
                from_priv=row['from_wallet'],
                intermediary_priv=row.get('intermediary', ''),
                to_wallet_value=row['to_wallet'],
                network=network,
                token_address=token_address,
                token_symbol=token_symbol,
                amount=row['amount'],
                proxy=None,
                delay_between=0
            )
            TOKEN_TRANSFER_STATS["wallets_processed"] += 1
            return f"✅ Успех: {row['from_wallet'][:10]}..."
        except Exception as e:
            TOKEN_TRANSFER_STATS["wallets_failed"] += 1
            return f"❌ Ошибка: {row['from_wallet'][:10]}... - {e}"
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS_TOKEN) as executor:
        # Добавляем задержки между запуском потоков
        tasks = []
        for idx, row in enumerate(transfer_data):
            time.sleep(delay_between)  # Задержка между запуском потоков
            future = executor.submit(process_single_transfer, (idx, row))
            tasks.append(future)
        
        # Ожидаем завершения всех задач
        for future in as_completed(tasks):
            result = future.result()
            logger.info(result)

def choose_token_for_network(network):
    """Выбор токена для конкретной сети через choice"""
    from questionary import select, Choice
    
    network_mapping = {
        '🚀 Base': base,
        '🚀 Pharos Testnet': pharos_testnet,
    }
    
    network_tokens = network_mapping.get(network)
    if not network_tokens:
        print(f"{Fore.RED}Сеть {network} не поддерживается для переводов токенов{Style.RESET_ALL}")
        return None, None
    
    print(f"\n{Fore.CYAN}Выберите токен для сети {network}:{Style.RESET_ALL}")
    
    # Создаем список выборов для questionary
    choices = []
    tokens_list = list(network_tokens.items())
    
    for symbol, address in tokens_list:
        # Упрощаем отображение символа
        display_symbol = symbol.split(' ')[0].split('(')[0]
        choices.append(Choice(f"{display_symbol} - {symbol}", (display_symbol.lower(), address)))
    
    choices.append(Choice('🔙 Назад', None))
    
    try:
        selected = select(
            "Выберите токен:",
            choices=choices,
            qmark='💎',
            pointer='👉'
        ).ask()
        
        if selected is None:
            return None, None
            
        token_symbol, token_address = selected
        print(f"{Fore.GREEN}Выбран токен: {token_symbol.upper()} ({token_address[:10]}...){Style.RESET_ALL}")
        return token_symbol, token_address
        
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Операция отменена пользователем{Style.RESET_ALL}")
        return None, None

def run_transfer_erc20_tokens():
    """Главная функция запуска модуля переводов ERC-20 токенов"""
    try:
        from questionary import Choice, select
        from colorama import Fore
        import csv
        from modules.eth.transfer_wallets_to_wallets import get_proxy_list
        from config.modules.cfg_transfer_erc20 import USE_INTERMEDIARY_TOKEN, expected_completion_time_token
        
        print(Fore.GREEN + f"\n\n💎 МОДУЛЬ ПЕРЕВОДОВ ТОКЕНОВ ERC-20")
        print(Fore.GREEN + f"Формат данных для data/transfer_token.csv: from_wallet,to_wallet,intermediary,amount")
        print(Fore.YELLOW + f"Пример amount: 10-20token (токены), 50-80% (проценты), 5token (фиксированно), 90% (фиксированный процент)\n")
        print(Fore.YELLOW + "Токен выбирается из меню при запуске для выбранной сети!")
        
        # Выбор типа сети
        network_type = select(
            "Select network type:",
            choices=[
                Choice('🌐 Mainnet', 'mainnet'),
                Choice('🔧 Testnet', 'testnet'),
                Choice('🔙 Back', 'back')
            ],
            qmark='🛠️',
            pointer='👉'
        ).ask()
        
        if network_type == 'back':
            return
        
        # Ограничиваем выбор сетей только теми, которые поддерживают токены
        supported_networks = ['🚀 Base', '🚀 Pharos Testnet']
        if network_type == 'mainnet':
            available_networks = [n for n in supported_networks if 'Testnet' not in n]
        else:
            available_networks = [n for n in supported_networks if 'Testnet' in n]
        
        if not available_networks:
            print(Fore.RED + f"Нет поддерживаемых сетей для типа {network_type}")
            return
        
        # Выбор сети
        network = select(
            "Which network do you want to use for token transfer?",
            choices=[Choice(get_network_display_name(n), n) for n in available_networks] + [Choice('🔙 Back', 'back')],
            qmark='🛠️',
            pointer='👉'
        ).ask()
        
        if network == 'back':
            return
        
        # Выбор токена для выбранной сети
        token_result = choose_token_for_network(network)
        if not token_result or token_result[0] is None:
            return
        
        selected_token_symbol, selected_token_address = token_result
        
        # Чтение данных из CSV
        transfer_data = []
        try:
            with open('data/transfer_token.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Берем все строки, поскольку токен уже выбран
                    if USE_INTERMEDIARY_TOKEN:
                        if row['from_wallet'] and row['to_wallet'] and row['intermediary'] and row['amount']:
                            transfer_data.append(row)
                    else:
                        if row['from_wallet'] and row['to_wallet'] and row['amount']:
                            if 'intermediary' not in row:
                                row['intermediary'] = ''
                            transfer_data.append(row)
        except Exception as e:
            print(Fore.RED + f"Ошибка чтения data/transfer_token.csv: {e}")
            return
        
        if not transfer_data:
            print(Fore.RED + f"Нет данных для отправки в data/transfer_token.csv.")
            return
        
        print(Fore.GREEN + f"Найдено {len(transfer_data)} записей для обработки с токеном {selected_token_symbol.upper()}")
        
        # Получаем прокси и вычисляем задержки
        proxies = get_proxy_list()
        delay_between = expected_completion_time_token / len(transfer_data) if len(transfer_data) > 1 else 0
        
        # Запускаем обработку
        process_token_transfers_normal(transfer_data, proxies, network, delay_between, selected_token_address, selected_token_symbol)
        
    except Exception as e:
        print(Fore.RED + f"Ошибка в модуле переводов токенов ERC-20: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Главная функция модуля"""
    run_transfer_erc20_tokens()

if __name__ == "__main__":
    main()
