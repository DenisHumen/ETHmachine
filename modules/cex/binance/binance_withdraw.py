import os
import sys
import csv
import time
import hmac
import random
import hashlib
import sqlite3
import requests
import threading
import datetime
from concurrent.futures import ThreadPoolExecutor
sys.__stdout__ = sys.stdout
from questionary import Choice, select
from loguru import logger
from web3 import Web3

# Добавляем корневую директорию в путь для импорта конфигов
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from config.cex_settings import binance_api_key, secret_key
from config.config import TYPE_WITHDRAW, VALUES_TO_WITHDRAW, SLEEP_BETWEEN_ACTIONS, WAIT_FOR_BALANCE, NUM_THREADS
from config import rpc

# Настройка логирования
log_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'log')
os.makedirs(log_path, exist_ok=True)

# Добавляем файловый хендлер для ошибок
logger.add(
    os.path.join(log_path, 'binance_withdraw_errors.log'),
    level="ERROR",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    rotation="10 MB",
    retention="7 days"
)

# Добавляем файловый хендлер для всех логов
logger.add(
    os.path.join(log_path, 'binance_withdraw_full.log'),
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {function} | {message}",
    rotation="50 MB",
    retention="3 days"
)

# Блокировка для thread-safe операций
db_lock = threading.Lock()
csv_lock = threading.Lock()

class BeautifulProgressBar:
    """Красивый прогресс-бар"""
    
    def __init__(self, total, desc="Progress", width=50):
        self.total = total
        self.current = 0
        self.desc = desc
        self.width = width
        self.start_time = time.time()
    
    def update(self, step=1):
        """Обновить прогресс"""
        self.current += step
        self._display()
    
    def _display(self):
        """Отобразить прогресс-бар"""
        if self.total == 0:
            return
            
        percentage = (self.current / self.total) * 100
        filled_width = int(self.width * self.current // self.total)
        bar = '█' * filled_width + '░' * (self.width - filled_width)
        
        elapsed_time = time.time() - self.start_time
        
        if self.current > 0:
            eta = (elapsed_time / self.current) * (self.total - self.current)
            eta_str = self._format_time(eta)
        else:
            eta_str = "??:??"
        
        elapsed_str = self._format_time(elapsed_time)
        
        # Очищаем строку и выводим прогресс
        print(f'\r\033[K🚀 {self.desc}: |{bar}| {self.current}/{self.total} [{percentage:6.2f}%] ⏱️ {elapsed_str} ⏳ ETA: {eta_str}', end='', flush=True)
        
        if self.current >= self.total:
            print()  # Переход на новую строку при завершении
    
    def _format_time(self, seconds):
        """Форматировать время в MM:SS"""
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"


def sleeping_with_progress(duration, desc="Sleeping"):
    """Красивое ожидание с прогресс-баром"""
    progress = BeautifulProgressBar(duration, desc, width=40)
    
    for i in range(duration):
        time.sleep(1)
        progress.update()


def sleeping(*timing):
    if len(timing) == 2: 
        x = random.randint(timing[0], timing[1])
    else: 
        x = timing[0]
    
    sleeping_with_progress(x, f"Sleep {x}s")


def create_signature(query_string, secret_key):
    """Создать подпись для Binance API"""
    return hmac.new(
        secret_key.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def binance_request(endpoint, method="GET", params=None):
    """Универсальная функция для запросов к Binance API"""
    try:
        base_url = "https://api.binance.com"
        timestamp = int(time.time() * 1000)
        
        if params is None:
            params = {}
        
        params['timestamp'] = timestamp
        
        # Создаем строку запроса
        query_string = '&'.join([f"{key}={value}" for key, value in params.items()])
        
        # Создаем подпись
        signature = create_signature(query_string, secret_key)
        params['signature'] = signature
        
        headers = {
            'X-MBX-APIKEY': binance_api_key,
            'Content-Type': 'application/json'
        }
        
        url = f"{base_url}{endpoint}"
        
        if method == "GET":
            response = requests.get(url, params=params, headers=headers, timeout=10)
        elif method == "POST":
            response = requests.post(url, params=params, headers=headers, timeout=10)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        return response.json()
        
    except Exception as ex:
        logger.error(f'Binance API request error: {ex}')
        return None


def get_token_price_in_usdt(token):
    """Получить цену токена в USDT через API Binance"""
    try:
        if token == 'USDT':
            return 1.0
        
        response = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={token}USDT", timeout=10)
        data = response.json()
        if 'price' in data:
            return float(data['price'])
        return None
    except Exception as ex:
        logger.error(f'Error getting price for {token}: {ex}')
        return None


def get_account_balances():
    """Получить все балансы аккаунта"""
    try:
        data = binance_request("/api/v3/account")
        
        balances = {}
        if data and 'balances' in data:
            for item in data['balances']:
                free_balance = float(item['free'])
                if free_balance > 0:
                    balances[item['asset']] = free_balance
        
        return balances
    except Exception as ex:
        logger.error(f'Error getting balances: {ex}')
        return {}


def pick_token_to_withdraw(balances):
    """Выбор токена для вывода"""
    if not balances:
        logger.error("No tokens with positive balance found")
        return None
    
    logger.info("Available tokens with balance:")
    for token, balance in balances.items():
        logger.info(f"{token}: {balance}")
    
    choices = []
    for token, balance in balances.items():
        choices.append(Choice(f"💰 {token:<10} | Balance: {balance:>15.6f}", token))
    choices.append(Choice("🔙 Назад", "back"))
    
    token = select(
        "Какой токен вы хотите вывести?",
        choices=choices
    ).ask()
    
    if token == "back":
        return None
    
    return token


def pick_chain(token):
    """Выбор сети для вывода"""
    try:
        # Получаем информацию о сетях для токена
        params = {'coin': token}
        data = binance_request("/sapi/v1/capital/config/getall", params=params)
        
        chains = []
        if data:
            for coin_info in data:
                if coin_info['coin'] == token:
                    for network in coin_info['networkList']:
                        if network['withdrawEnable']:
                            chains.append(network['network'])
        
        if not chains:
            logger.error(f"No withdrawal chains available for {token}")
            return None
        
        choices = []
        for chain in chains:
            choices.append(Choice(f"🔗 {chain:<15} | Сеть для вывода {token}", chain))
        choices.append(Choice("🔙 Назад", "back"))
            
        chain = select(
            f"Какую сеть предпочитаете для {token}?",
            choices=choices
        ).ask()
        
        if chain == "back":
            return None
        
        return chain
    except Exception as ex:
        logger.error(f'Error getting chains for {token}: {ex}')
        return None


def calculate_withdraw_amount(token, available_balance):
    """Рассчитать сумму для вывода"""
    if TYPE_WITHDRAW == 1:  # Выводить в USDT эквиваленте
        price_in_usdt = get_token_price_in_usdt(token)
        if price_in_usdt is None:
            logger.warning(f"Cannot get price for {token}, using native amount")
            amount_from, amount_to = VALUES_TO_WITHDRAW[0], VALUES_TO_WITHDRAW[1]
        else:
            # Конвертируем USDT суммы в нативный токен
            amount_from = VALUES_TO_WITHDRAW[0] / price_in_usdt
            amount_to = VALUES_TO_WITHDRAW[1] / price_in_usdt
            logger.info(f"Price {token}/USDT: {price_in_usdt}")
            logger.info(f"Withdraw range in {token}: {amount_from:.6f} - {amount_to:.6f}")
    else:  # Выводить в нативном токене
        amount_from, amount_to = VALUES_TO_WITHDRAW[0], VALUES_TO_WITHDRAW[1]
    
    # Проверяем достаточность баланса
    if amount_from > available_balance:
        logger.error(f"Insufficient balance. Need at least {amount_from} {token}, but have {available_balance}")
        
        confirm = select(
            f"Недостаточно баланса. Вывести весь доступный баланс ({available_balance} {token})?",
            choices=[
                Choice('❌ Нет, отменить', False),
                Choice('✅ Да, вывести всё', True),
                Choice('🔙 Назад', "back")
            ]
        ).ask()
        
        if confirm == "back":
            return "back"
        elif confirm:
            return available_balance
        else:
            return None
    
    if amount_to > available_balance:
        logger.warning(f"Max withdraw amount adjusted from {amount_to} to {available_balance}")
        amount_to = available_balance
    
    return round(random.uniform(amount_from, amount_to), 6)


def calculate_individual_withdraw_amount(token, available_balance):
    """Рассчитать индивидуальную сумму для вывода для одного кошелька"""
    if TYPE_WITHDRAW == 1:  # Выводить в USDT эквиваленте
        price_in_usdt = get_token_price_in_usdt(token)
        if price_in_usdt is None:
            logger.warning(f"Cannot get price for {token}, using native amount")
            amount_from, amount_to = VALUES_TO_WITHDRAW[0], VALUES_TO_WITHDRAW[1]
        else:
            # Конвертируем USDT суммы в нативный токен
            amount_from = VALUES_TO_WITHDRAW[0] / price_in_usdt
            amount_to = VALUES_TO_WITHDRAW[1] / price_in_usdt
    else:  # Выводить в нативном токене
        amount_from, amount_to = VALUES_TO_WITHDRAW[0], VALUES_TO_WITHDRAW[1]
    
    # Проверяем достаточность баланса
    if amount_from > available_balance:
        logger.warning(f"Insufficient balance. Need at least {amount_from} {token}, but have {available_balance}. Using all available balance.")
        return available_balance
    
    if amount_to > available_balance:
        amount_to = available_balance
    
    return round(random.uniform(amount_from, amount_to), 6)


def get_withdraw_fee(token, network):
    """Получить комиссию за вывод"""
    try:
        params = {'coin': token}
        data = binance_request("/sapi/v1/capital/config/getall", params=params)
        
        if data:
            for coin_info in data:
                if coin_info['coin'] == token:
                    for network_info in coin_info['networkList']:
                        if network_info['network'] == network:
                            return float(network_info['withdrawFee'])
        return 0
    except Exception as ex:
        logger.error(f'Error getting fee for {token}-{network}: {ex}')
        return 0


def execute_binance_withdraw(wallet: str, token: str, network: str, amount: float, retry=0):
    """Выполнить вывод средств"""
    logger.info(f'[{wallet}] Starting withdrawal of {amount} {token}')
    
    try:
        # Выполняем вывод
        params = {
            'coin': token,
            'address': wallet,
            'amount': amount,
            'network': network
        }
        
        result = binance_request("/sapi/v1/capital/withdraw/apply", method="POST", params=params)
        
        if result and 'id' in result:
            logger.success(f"Binance withdraw success => {wallet} | {amount} {token} | ID: {result['id']}")
            return amount
        else:
            error = result.get('msg', 'Unknown error') if result else 'API request failed'
            logger.error(f"Binance withdraw failed => {wallet} | error: {error}")
            if retry < 3:
                time.sleep(10)
                return execute_binance_withdraw(wallet, token, network, amount, retry + 1)
            
    except Exception as error:
        logger.error(f"Binance withdraw error => {wallet} | {error}")
        if retry < 3:
            time.sleep(10)
            return execute_binance_withdraw(wallet, token, network, amount, retry + 1)
    
    return None


def load_wallets():
    """Загрузить адреса кошельков"""
    wallets_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'walletss.txt')
    try:
        with open(wallets_path, 'r') as f:
            wallets = [line.strip() for line in f.readlines() if line.strip()]
        return wallets
    except FileNotFoundError:
        logger.error(f"File not found: {wallets_path}")
        return []
    except Exception as ex:
        logger.error(f"Error loading wallets: {ex}")
        return []


def get_chain_rpc_list(chain):
    """Получить список RPC для конкретной сети"""
    chain_mapping = {
        'ERC20': rpc.L1,
        'ETH': rpc.L1,
        'Ethereum': rpc.L1,
        'BSC': rpc.Binance_Smart_Chain,
        'BNB': rpc.Binance_Smart_Chain,
        'BEP20': rpc.Binance_Smart_Chain,
        'MATIC': rpc.Polygon,
        'Polygon': rpc.Polygon,
        'ARBITRUM': rpc.arbitrum,
        'Arbitrum': rpc.arbitrum,
        'OPTIMISM': rpc.optimism,
        'Optimism': rpc.optimism,
        'BASE': rpc.base,
        'Base': rpc.base,
        'AVAXC': rpc.Avalanche,
        'Avalanche': rpc.Avalanche,
        'FTM': rpc.Fantom,
        'Fantom': rpc.Fantom,
        'ZORA': rpc.zora,
        'Zora': rpc.zora,
        'ABSTRACT': rpc.Abstract,
        'Abstract': rpc.Abstract,
        'SONEIUM': rpc.soneium,
        'Soneium': rpc.soneium,
        # Testnets
        'SEPOLIA': rpc.sepolia,
        'Sepolia': rpc.sepolia,
    }
    
    return chain_mapping.get(chain, rpc.L1)  # По умолчанию используем Ethereum


def get_working_web3_connection(chain):
    """Получить рабочее подключение Web3 для конкретной сети"""
    rpc_list = get_chain_rpc_list(chain)
    
    for rpc_url in rpc_list:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
            if w3.is_connected():
                logger.debug(f"Connected to {chain} via {rpc_url}")
                return w3
        except Exception as ex:
            logger.debug(f"Failed to connect to {rpc_url}: {ex}")
            continue
    
    logger.error(f"Could not connect to any RPC for {chain}")
    return None


def get_token_contract_address(token, chain):
    """Получить адрес контракта токена для конкретной сети"""
    # Словарь с адресами популярных токенов для разных сетей
    token_addresses = {
        'USDT': {
            'ERC20': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'ETH': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'BSC': '0x55d398326f99059fF775485246999027B3197955',
            'BEP20': '0x55d398326f99059fF775485246999027B3197955',
            'MATIC': '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
            'ARBITRUM': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'OPTIMISM': '0x94b008aA00579c1307B0EF2c499aD98a8ce58e58',
            'BASE': '0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2',
            'AVAXC': '0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7'
        },
        'USDC': {
            'ERC20': '0xA0b86a33E6441b33F5A4dF7a54fA0Fbc9B1bF0e2',
            'ETH': '0xA0b86a33E6441b33F5A4dF7a54fA0Fbc9B1bF0e2',
            'BSC': '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d',
            'BEP20': '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d',
            'MATIC': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174',
            'ARBITRUM': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
            'OPTIMISM': '0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85',
            'BASE': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
            'AVAXC': '0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E'
        },
        'BNB': {
            'BSC': '0x0000000000000000000000000000000000000000',  # Нативный токен
            'BEP20': '0x0000000000000000000000000000000000000000'
        },
        'ETH': {
            'ERC20': '0x0000000000000000000000000000000000000000',  # Нативный токен
            'ETH': '0x0000000000000000000000000000000000000000'
        }
    }
    
    if token in token_addresses and chain in token_addresses[token]:
        return token_addresses[token][chain]
    
    return None


def check_native_balance(w3, wallet_address):
    """Проверить баланс нативного токена (ETH, BNB, MATIC и т.д.)"""
    try:
        balance_wei = w3.eth.get_balance(wallet_address)
        balance_eth = w3.from_wei(balance_wei, 'ether')
        return float(balance_eth)
    except Exception as ex:
        logger.error(f"Error checking native balance: {ex}")
        return 0


def check_token_balance(w3, wallet_address, token_address):
    """Проверить баланс ERC20 токена"""
    try:
        # ABI для функции balanceOf
        erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            }
        ]
        
        contract = w3.eth.contract(address=token_address, abi=erc20_abi)
        
        # Получаем баланс в wei
        balance_wei = contract.functions.balanceOf(wallet_address).call()
        
        # Получаем количество десятичных знаков
        decimals = contract.functions.decimals().call()
        
        # Конвертируем в человекочитаемый формат
        balance = balance_wei / (10 ** decimals)
        
        return float(balance)
        
    except Exception as ex:
        logger.error(f"Error checking token balance: {ex}")
        return 0


def check_wallet_balance(wallet_address, token, network, expected_amount, timeout_hours=1):
    """Проверить баланс кошелька и ждать поступления средств"""
    if not WAIT_FOR_BALANCE:
        return True
    
    logger.info(f"Ожидание поступления {expected_amount} {token} на кошелек {wallet_address}")
    
    # Получаем подключение к Web3
    w3 = get_working_web3_connection(network)
    if not w3:
        logger.warning(f"Cannot connect to {network} network, skipping balance check")
        return True
    
    # Получаем начальный баланс
    token_contract_address = get_token_contract_address(token, network)
    
    if token_contract_address == '0x0000000000000000000000000000000000000000' or token_contract_address is None:
        # Нативный токен
        initial_balance = check_native_balance(w3, wallet_address)
        logger.info(f"Initial native balance: {initial_balance} {token}")
    else:
        # ERC20 токен
        initial_balance = check_token_balance(w3, wallet_address, token_contract_address)
        logger.info(f"Initial {token} balance: {initial_balance}")
    
    timeout_seconds = timeout_hours * 3600  # 1 час в секундах
    start_time = time.time()
    check_interval = 30  # Проверяем каждые 30 секунд
    
    while time.time() - start_time < timeout_seconds:
        try:
            time.sleep(check_interval)
            
            # Проверяем текущий баланс
            if token_contract_address == '0x0000000000000000000000000000000000000000' or token_contract_address is None:
                current_balance = check_native_balance(w3, wallet_address)
            else:
                current_balance = check_token_balance(w3, wallet_address, token_contract_address)
            
            # Проверяем, увеличился ли баланс
            balance_increase = current_balance - initial_balance
            
            logger.debug(f"Current balance: {current_balance}, increase: {balance_increase}")
            
            # Если баланс увеличился на ожидаемую сумму (с небольшой погрешностью)
            if balance_increase >= expected_amount * 0.95:
                logger.success(f"✅ Balance received! {balance_increase} {token} on {wallet_address}")
                return True
                
        except Exception as ex:
            logger.error(f"Error checking balance: {ex}")
    
    # Если время истекло - показываем красный баннер
    show_balance_timeout_error(wallet_address, expected_amount, token)
    return False


def show_balance_timeout_error(wallet_address, amount, token):
    """Показать красный баннер об ошибке с балансом"""
    error_message = f"""
    ╔══════════════════════════════════════════════════════════════════════════════════════╗
    ║                                    ⚠️  ОШИБКА  ⚠️                                   ║
    ╠══════════════════════════════════════════════════════════════════════════════════════╣
    ║                                                                                      ║
    ║  🚨 ПОПОЛНЕНИЕ ОСТАНОВЛЕНО 🚨                                                       ║
    ║                                                                                      ║
    ║  Кошелек: {wallet_address[:10]}...{wallet_address[-10:]}                             ║
    ║  Сумма:   {amount} {token}                                                           ║
    ║                                                                                      ║
    ║  Баланс не поступил в течение 1 часа!                                                ║
    ║  Проверьте:                                                                          ║
    ║  • Статус транзакции на бирже                                                        ║
    ║  • Правильность адреса кошелька                                                      ║
    ║  • Состояние сети {token}                                                            ║
    ║                                                                                      ║
    ║  Пополнение других кошельков ОСТАНОВЛЕНО для безопасности                            ║
    ║                                                                                      ║
    ╚══════════════════════════════════════════════════════════════════════════════════════╝
    """
    
    logger.error(error_message)
    

def create_progress_db():
    """Создать базу данных для отслеживания прогресса"""
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'db')
    os.makedirs(db_path, exist_ok=True)
    
    db_file = os.path.join(db_path, 'binance_withdraw_progress.db')
    
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS withdraw_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                token TEXT NOT NULL,
                network TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        ''')
        conn.commit()
    
    return db_file


def save_progress(db_file, wallet_address, token, network, amount, status, error_message=None):
    """Сохранить прогресс в базу данных"""
    with db_lock:
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            
            # Проверяем, существует ли уже запись
            cursor.execute('''
                SELECT id FROM withdraw_progress 
                WHERE wallet_address = ? AND token = ? AND network = ?
            ''', (wallet_address, token, network))
            
            existing = cursor.fetchone()
            
            if existing:
                # Обновляем существующую запись
                cursor.execute('''
                    UPDATE withdraw_progress 
                    SET amount = ?, status = ?, error_message = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (amount, status, error_message, existing[0]))
            else:
                # Создаем новую запись
                cursor.execute('''
                    INSERT INTO withdraw_progress 
                    (wallet_address, token, network, amount, status, error_message)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (wallet_address, token, network, amount, status, error_message))
            
            conn.commit()


def get_pending_wallets(db_file):
    """Получить список кошельков, которые еще не обработаны"""
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wallet_address FROM withdraw_progress 
            WHERE status = 'pending'
        ''')
        return [row[0] for row in cursor.fetchall()]


def clear_progress_db(db_file):
    """Очистить базу данных прогресса"""
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM withdraw_progress')
        conn.commit()


def save_result_to_csv(wallet_address, token, network, amount, status, error_message=None):
    """Сохранить результат в CSV файл"""
    result_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'result')
    os.makedirs(result_path, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = os.path.join(result_path, f'binance_withdraw_results_{timestamp[:8]}.csv')
    
    with csv_lock:
        file_exists = os.path.isfile(csv_file)
        
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Записываем заголовок, если файл новый
            if not file_exists:
                writer.writerow(['Timestamp', 'Wallet', 'Token', 'Network', 'Amount', 'Status', 'Error'])
            
            # Записываем данные
            writer.writerow([
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                wallet_address,
                token,
                network,
                amount,
                status,
                error_message or ''
            ])


def process_single_wallet(wallet_data):
    """Обработать один кошелек"""
    wallet, token, network, db_file = wallet_data
    
    try:
        logger.info(f'[Thread] Processing wallet: {wallet}')
        
        # Получаем текущий баланс для расчета суммы
        current_balances = get_account_balances()
        if not current_balances or token not in current_balances:
            error_message = f"Token {token} not found in account or insufficient balance"
            save_progress(db_file, wallet, token, network, 0, 'error', error_message)
            save_result_to_csv(wallet, token, network, 0, 'error', error_message)
            return False
        
        # Рассчитываем индивидуальную сумму для этого кошелька
        individual_amount = calculate_individual_withdraw_amount(token, current_balances[token])
        
        # Обновляем запись в БД с реальной суммой
        save_progress(db_file, wallet, token, network, individual_amount, 'processing')
        
        result = execute_binance_withdraw(wallet, token, network, individual_amount)
        
        if result:
            status = 'success'
            error_message = None
            
            # Проверяем баланс кошелька после вывода (если включено)
            if not check_wallet_balance(wallet, token, network, individual_amount):
                status = 'warning'
                error_message = 'Withdraw success but balance not received within timeout'
        else:
            status = 'error'
            error_message = 'Withdraw failed'
        
        # Сохраняем прогресс
        save_progress(db_file, wallet, token, network, individual_amount, status, error_message)
        
        # Сохраняем результат в CSV
        save_result_to_csv(wallet, token, network, individual_amount, status, error_message)
        
        # Добавляем задержку между операциями
        sleeping(*SLEEP_BETWEEN_ACTIONS)
        
        return status == 'success'
        
    except Exception as ex:
        logger.error(f'Error processing wallet {wallet}: {ex}')
        save_progress(db_file, wallet, token, network, 0, 'error', str(ex))
        save_result_to_csv(wallet, token, network, 0, 'error', str(ex))
        return False


def check_existing_progress():
    """Проверить существующий прогресс и предложить варианты"""
    db_file = create_progress_db()
    
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM withdraw_progress')
        total_records = cursor.fetchone()[0]
        
        if total_records > 0:
            cursor.execute('SELECT COUNT(*) FROM withdraw_progress WHERE status = "pending"')
            pending_records = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM withdraw_progress WHERE status = "success"')
            success_records = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM withdraw_progress WHERE status = "error"')
            error_records = cursor.fetchone()[0]
            
            logger.info(f"Found existing progress: {total_records} total, {pending_records} pending, {success_records} success, {error_records} errors")
            
            if pending_records > 0:
                action = select(
                    "Найден незавершенный процесс вывода. Что делать?",
                    choices=[
                        Choice('🔄 Продолжить с того места, где остановились', 'continue'),
                        Choice('🔥 Начать заново (очистить прогресс)', 'new'),
                        Choice('❌ Отменить', 'cancel')
                    ]
                ).ask()
                
                if action == 'new':
                    clear_progress_db(db_file)
                    return db_file, 'new'
                
                return db_file, action
    
    return db_file, 'new'


def binance_withdraw():
    """Основная функция"""
    logger.info("=== Binance Withdrawal Module ===")
    
    # Проверяем настройки API
    if not binance_api_key or not secret_key:
        logger.error("Binance API credentials not configured. Please check config/cex_settings.py")
        return
    
    # Проверяем существующий прогресс
    db_file, progress_action = check_existing_progress()
    if progress_action == 'cancel':
        logger.info("Операция отменена")
        return
    
    # Загружаем кошельки
    all_wallets = load_wallets()
    if not all_wallets:
        logger.error("No wallets found")
        return
    
    # Если продолжаем, фильтруем уже обработанные кошельки
    if progress_action == 'continue':
        pending_wallets = get_pending_wallets(db_file)
        wallets = [w for w in all_wallets if w in pending_wallets]
        logger.info(f"Continuing with {len(wallets)} remaining wallets")
    else:
        wallets = all_wallets
        logger.info(f"Starting fresh with {len(wallets)} wallets")
    
    if not wallets:
        logger.info("No wallets to process")
        return
    
    while True:
        # Получаем балансы
        balances = get_account_balances()
        if not balances:
            logger.error("Cannot get account balances or no positive balances found")
            return
        
        # Выбираем токен
        token = pick_token_to_withdraw(balances)
        if not token:
            logger.info("Операция отменена пользователем")
            return
        
        # Выбираем сеть
        network = pick_chain(token)
        if not network:
            logger.info("Операция отменена пользователем")
            return
        
        # Рассчитываем примерную сумму для отображения (будет пересчитана для каждого кошелька)
        available_balance = balances[token]
        sample_withdraw_amount = calculate_withdraw_amount(token, available_balance)
        if sample_withdraw_amount is None:
            logger.info("Операция отменена пользователем")
            return
        elif sample_withdraw_amount == "back":
            logger.info("Операция отменена пользователем")
            return
        
        # Подтверждение (показываем примерный диапазон)
        if TYPE_WITHDRAW == 1:
            amount_info = f"${VALUES_TO_WITHDRAW[0]}-{VALUES_TO_WITHDRAW[1]} USDT эквивалент"
        else:
            amount_info = f"{VALUES_TO_WITHDRAW[0]}-{VALUES_TO_WITHDRAW[1]} {token}"
        
        confirm = select(
            f"Вывести {amount_info} на {len(wallets)} кошельков через сеть {network}?",
            choices=[
                Choice('✅ Да, начать вывод', True),
                Choice('❌ Нет, отменить', False),
                Choice('🔙 Назад', "back")
            ]
        ).ask()
        
        if confirm == "back":
            logger.info("Операция отменена пользователем")
            return
        elif not confirm:
            logger.info("Операция отменена")
            return
        
        # Создаем записи в БД для новых кошельков (с временной суммой 0)
        if progress_action == 'new':
            for wallet in wallets:
                save_progress(db_file, wallet, token, network, 0, 'pending')
        
        # Подготавливаем данные для потоков (без фиксированной суммы)
        wallet_data_list = []
        for wallet in wallets:
            wallet_data_list.append((wallet, token, network, db_file))
        
        # Выполняем выводы с использованием ThreadPoolExecutor
        logger.info(f"Starting withdrawals with {NUM_THREADS} threads...")
        successful = 0
        failed = 0
        
        # Создаем прогресс-бар для отслеживания обработки кошельков
        progress_bar = BeautifulProgressBar(len(wallet_data_list), "Processing wallets", width=60)
        
        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            future_to_wallet = {executor.submit(process_single_wallet, wallet_data): wallet_data[0] 
                              for wallet_data in wallet_data_list}
            
            for future in future_to_wallet:
                wallet = future_to_wallet[future]
                try:
                    result = future.result()
                    if result:
                        successful += 1
                    else:
                        failed += 1
                except Exception as ex:
                    logger.error(f'Exception for wallet {wallet}: {ex}')
                    failed += 1
                finally:
                    progress_bar.update()
        
        logger.info("=== Summary ===")
        logger.info(f"Successful withdrawals: {successful}")
        logger.info(f"Failed withdrawals: {failed}")
        logger.info(f"Total processed: {successful + failed}")
        
        # Проверяем, все ли кошельки обработаны успешно
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM withdraw_progress WHERE status = "pending"')
            remaining = cursor.fetchone()[0]
            
            if remaining == 0:
                logger.success("All wallets processed!")
            else:
                logger.warning(f"{remaining} wallets still pending")
        
        break


if __name__ == '__main__':
    binance_withdraw()
