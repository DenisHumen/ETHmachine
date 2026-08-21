import requests
import base64
import json
import random
import time
import hmac
import datetime
import sys
import os
import sqlite3
import csv
import threading
from concurrent.futures import ThreadPoolExecutor
sys.__stdout__ = sys.stdout
from questionary import Choice, select
from web3 import Web3

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from modules.simple_logger import logger
from modules.proxy_manager import get_random_proxy_dict

def _get_okx_settings():
    """Получить настройки OKX с обработкой ошибок"""
    try:
        from config.cex_settings import OKX_EU_TYPE, OKX_ACCOUNTS
        return OKX_EU_TYPE, OKX_ACCOUNTS
    except ImportError:
        logger.error("Файл config/cex_settings.py не найден. Запустите main.py для создания.")
        return 0, []
    except Exception as e:
        logger.error(f"Ошибка в настройках OKX: {e}")
        return 0, []

from config.modules.cfg_cex import TYPE_WITHDRAW, VALUES_TO_WITHDRAW, WAIT_FOR_BALANCE
from config.modules.general_config import SLEEP_BETWEEN_ACTIONS, NUM_THREADS
from config import networks as rpc

# Импорт селектора аккаунтов
from modules.cex.exchange_selector import select_okx_account

# Настройка логирования
log_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'log')

# Флаг инициализации логгера
_logger_initialized = False

def _setup_logging():
    """Настройка логирования - вызывается при запуске модуля"""
    global _logger_initialized
    if _logger_initialized:
        return
    _logger_initialized = True
    
    os.makedirs(log_path, exist_ok=True)
    
    # Добавляем файловый хендлер для ошибок
    logger.add(
        os.path.join(log_path, 'okx_withdraw_errors.log'),
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        rotation="10 MB",
        retention="7 days"
    )

    # Добавляем файловый хендлер для всех логов
    logger.add(
        os.path.join(log_path, 'okx_withdraw_full.log'),
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


def okx_data(api_key, secret_key, passphras, request_path="/api/v5/account/balance", body='', meth="GET"):
    try:
        def signature(timestamp: str, method: str, request_path: str, secret_key: str, body: str = "") -> str:
            if not body:
                body = ""
            message = timestamp + method.upper() + request_path + body
            mac = hmac.new(
                bytes(secret_key, encoding="utf-8"),
                bytes(message, encoding="utf-8"),
                digestmod="sha256",
            )
            d = mac.digest()
            return base64.b64encode(d).decode("utf-8")

        dt_now = datetime.datetime.utcnow()
        ms = str(dt_now.microsecond).zfill(6)[:3]
        timestamp = f"{dt_now:%Y-%m-%dT%H:%M:%S}.{ms}Z"

        base_url = "https://www.okx.cab"
        headers = {
            "Content-Type": "application/json",
            "OK-ACCESS-KEY": api_key,
            "OK-ACCESS-SIGN": signature(timestamp, meth, request_path, secret_key, body),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": passphras,
            'x-simulated-trading': '0'
        }
        return base_url, request_path, headers
    except Exception as ex:
        logger.error(f'OKX DATA ERROR: {ex}')
        return None, None, None


def get_token_price_in_usdt(token):
    """Получить цену токена в USDT через API OKX"""
    try:
        if token == 'USDT':
            return 1.0
        
        response = requests.get(f"https://www.okx.cab/api/v5/market/ticker?instId={token}-USDT", timeout=10)
        data = response.json()
        if data['code'] == '0' and data['data']:
            return float(data['data'][0]['last'])
        return None
    except Exception as ex:
        logger.error(f'Error getting price for {token}: {ex}')
        return None


def get_account_balances(api_key, api_secret, passphrase):
    """Получить все балансы аккаунта"""
    try:
        _, _, headers = okx_data(api_key, api_secret, passphrase, 
                                request_path="/api/v5/asset/balances", meth="GET")
        
        response = requests.get("https://www.okx.cab/api/v5/asset/balances", timeout=10, headers=headers)
        data = response.json()
        
        balances = {}
        if data['code'] == '0':
            for item in data['data']:
                if float(item['availBal']) > 0:
                    balances[item['ccy']] = float(item['availBal'])
        
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


def pick_chain(token, api_key, api_secret, passphrase):
    """Выбор сети для вывода"""
    try:
        _, _, headers = okx_data(api_key, api_secret, passphrase,
                                request_path=f"/api/v5/asset/currencies?ccy={token}", meth="GET")
        response = requests.get(f"https://www.okx.cab/api/v5/asset/currencies?ccy={token}", 
                               timeout=10, headers=headers)
        
        chains = []
        if response.json()['code'] == '0':
            for lst in response.json()['data']:
                if lst['canWd']:  # Проверяем, доступен ли вывод
                    chain_name = '-'.join(lst["chain"].split('-')[1:])
                    chains.append(chain_name)
        
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


def get_withdraw_fee(token, chain, api_key, api_secret, passphrase):
    """Получить комиссию за вывод"""
    try:
        _, _, headers = okx_data(api_key, api_secret, passphrase, 
                                request_path=f"/api/v5/asset/currencies?ccy={token}", meth="GET")
        response = requests.get(f"https://www.okx.cab/api/v5/asset/currencies?ccy={token}", 
                               timeout=10, headers=headers)
        
        for lst in response.json()['data']:
            if lst['chain'] == f'{token}-{chain}':
                return float(lst['minFee'])
        return 0
    except Exception as ex:
        logger.error(f'Error getting fee for {token}-{chain}: {ex}')
        return 0


def format_okx_amount(value) -> str:
    """Сумма для OKX всегда строка: float даёт экспоненту (1e-06), которую биржа не парсит"""
    return f"{float(value):.8f}".rstrip('0').rstrip('.')


def execute_okx_withdraw(wallet: str, token: str, chain: str, amount: float,
                        api_key: str, api_secret: str, passphrase: str,
                        wallet_number: int = 0, total_wallets: int = 0, retry=0):
    """Выполнить вывод средств"""
    # Получаем настройки OKX
    OKX_EU_TYPE, _ = _get_okx_settings()
    
    wallet_prefix = f"[{wallet_number}/{total_wallets}] " if wallet_number > 0 else ""
    logger.info(f'{wallet_prefix}[{wallet}] Starting withdrawal of {amount} {token}')
    
    try:
        # Получаем комиссию
        fee = get_withdraw_fee(token, chain, api_key, api_secret, passphrase)
        
        # Переводим с торгового на основной счет если нужно
        if OKX_EU_TYPE == 0:
            try:
                _, _, headers = okx_data(api_key, api_secret, passphrase, 
                                        request_path=f"/api/v5/account/balance?ccy={token}")
                balance = requests.get(f'https://www.okx.cab/api/v5/account/balance?ccy={token}', 
                                     timeout=10, headers=headers)
                balance_data = balance.json()
                
                if balance_data['code'] == '0' and balance_data['data']:
                    trading_balance = float(balance_data["data"][0]["details"][0]["cashBal"])
                    
                    if trading_balance > 0:
                        # Подпись OKX считается по телу запроса байт в байт, поэтому сериализуем
                        # JSON один раз и одну и ту же строку отдаём и в подпись, и в POST
                        body = json.dumps({
                            "ccy": token,
                            "amt": format_okx_amount(trading_balance),
                            "from": "18",
                            "to": "6",
                            "type": "0",
                        })
                        _, _, headers = okx_data(api_key, api_secret, passphrase,
                                               request_path="/api/v5/asset/transfer", body=body, meth="POST")
                        requests.post("https://www.okx.cab/api/v5/asset/transfer", data=body,
                                    timeout=10, headers=headers)
            except Exception:
                pass
        
        # Выполняем вывод
        # Тело обязано быть валидным JSON (str(dict) даёт одинарные кавычки, биржа такое не парсит)
        body = json.dumps({
            "ccy": token,
            "amt": format_okx_amount(amount),
            "fee": format_okx_amount(fee),
            "dest": "4",
            "chain": f"{token}-{chain}",
            "toAddr": wallet,
        })

        _, _, headers = okx_data(api_key, api_secret, passphrase,
                                request_path="/api/v5/asset/withdrawal", meth="POST", body=body)
        response = requests.post("https://www.okx.cab/api/v5/asset/withdrawal",
                               data=body, timeout=10, headers=headers)
        result = response.json()
        
        if result['code'] == '0':
            logger.success(f"{wallet_prefix}OKX withdraw success => {wallet} | {amount} {token}")
            return amount
        else:
            error = result['msg']
            logger.error(f"{wallet_prefix}OKX withdraw failed => {wallet} | error: {error}")
            if retry < 3:
                time.sleep(10)
                return execute_okx_withdraw(wallet, token, chain, amount, 
                                           api_key, api_secret, passphrase,
                                           wallet_number, total_wallets, retry + 1)
            
    except Exception as error:
        logger.error(f"{wallet_prefix}OKX withdraw error => {wallet} | {error}")
        if retry < 3:
            time.sleep(10)
            return execute_okx_withdraw(wallet, token, chain, amount,
                                       api_key, api_secret, passphrase,
                                       wallet_number, total_wallets, retry + 1)
    
    return None


def load_wallets():
    """Загрузить адреса кошельков из data.csv"""
    from modules.data_manager import get_wallet_addresses
    wallets = get_wallet_addresses()
    if not wallets:
        logger.error("Нет кошельков в data/data.csv")
    return wallets


def get_chain_rpc_list(chain):
    """Получить список RPC для конкретной сети"""
    chain_mapping = {
        'ERC20': rpc.L1,
        'Ethereum': rpc.L1,
        'ETH': rpc.L1,
        'Base': rpc.base,
        'Arbitrum One': rpc.arbitrum,
        'Arbitrum': rpc.arbitrum,
        'Optimism': rpc.optimism,
        'Polygon': rpc.Polygon,
        'BSC': rpc.Binance_Smart_Chain,
        'BNB Smart Chain (BEP20)': rpc.Binance_Smart_Chain,
        'Avalanche C-Chain': rpc.Avalanche,
        'Avalanche': rpc.Avalanche,
        'Fantom': rpc.Fantom,
        'Gravity Alpha Mainnet': rpc.Gravity_Alpha_Mainnet,
        'Gravity': rpc.Gravity_Alpha_Mainnet,
        'Zora': rpc.zora,
        'Abstract': rpc.Abstract,
        'Soneium': rpc.soneium,
        # Testnets
        'Sepolia': rpc.sepolia,
        'Kite Testnet': rpc.kite_testnet,
        'MegaETH Testnet': rpc.mega_eth_testnet,
        'Pharos Testnet': rpc.pharos_testnet,
    }
    
    return chain_mapping.get(chain, rpc.L1)  # По умолчанию используем Ethereum


def get_working_web3_connection(chain):
    """Получить рабочее подключение Web3 для конкретной сети через прокси"""
    rpc_list = get_chain_rpc_list(chain)
    proxy = get_random_proxy_dict()
    
    if proxy:
        for rpc_url in rpc_list:
            try:
                session = requests.Session()
                session.proxies.update(proxy)
                
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}, session=session))
                if w3.is_connected():
                    logger.debug(f"Подключился к {chain} через {rpc_url} с прокси")
                    return w3
            except Exception as ex:
                logger.debug(f"Не удалось подключиться к {rpc_url} с прокси: {ex}")
                continue
    
    # Если прокси не сработал, пробуем без прокси
    logger.info(f"Подключение к {chain} без прокси (fallback)")
    for rpc_url in rpc_list:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
            if w3.is_connected():
                logger.debug(f"Подключился к {chain} через {rpc_url} без прокси")
                return w3
        except Exception as ex:
            logger.debug(f"Не удалось подключиться к {rpc_url} без прокси: {ex}")
            continue
    
    logger.error(f"Не удалось подключиться к RPC для {chain}")
    return None


def get_token_contract_address(token, chain):
    """Получить адрес контракта токена для конкретной сети"""
    # Словарь с адресами популярных токенов для разных сетей
    token_addresses = {
        'USDT': {
            'ERC20': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'Ethereum': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'BSC': '0x55d398326f99059fF775485246999027B3197955',
            'Polygon': '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
            'Arbitrum': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'Optimism': '0x94b008aA00579c1307B0EF2c499aD98a8ce58e58',
            'Base': '0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2',
            'Avalanche': '0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7',
            'zkSync Era': '0x493257fD37EDB34451f62EDf8D2a0C418852bA4C'
        },
        'USDC': {
            'ERC20': '0xA0b86a33E6441b33F5A4dF7a54fA0Fbc9B1bF0e2',
            'Ethereum': '0xA0b86a33E6441b33F5A4dF7a54fA0Fbc9B1bF0e2',
            'BSC': '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d',
            'Polygon': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174',
            'Arbitrum': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
            'Optimism': '0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85',
            'Base': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
            'Avalanche': '0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E',
            'zkSync Era': '0x3355df6D4c9C3035724Fd0e3914dE96A5a83aaf4'
        },
        'G': {
            'Gravity Alpha Mainnet': '0x0000000000000000000000000000000000000000',  # Нативный токен
            'Gravity': '0x0000000000000000000000000000000000000000'
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


def check_wallet_balance(wallet_address, token, chain, expected_amount, wallet_number: int = 0, total_wallets: int = 0, timeout_hours=1):
    """Проверить баланс кошелька и ждать поступления средств"""
    if not WAIT_FOR_BALANCE:
        return True
    
    wallet_prefix = f"[{wallet_number}/{total_wallets}] " if wallet_number > 0 else ""
    logger.info(f"{wallet_prefix}Ожидание поступления {expected_amount} {token} на кошелек {wallet_address}")
    
    # Получаем подключение к Web3
    w3 = get_working_web3_connection(chain)
    if not w3:
        logger.warning(f"{wallet_prefix}Cannot connect to {chain} network, skipping balance check")
        return True
    
    # Получаем начальный баланс
    token_contract_address = get_token_contract_address(token, chain)
    
    if token_contract_address == '0x0000000000000000000000000000000000000000' or token_contract_address is None:
        # Нативный токен
        initial_balance = check_native_balance(w3, wallet_address)
        logger.info(f"{wallet_prefix}Initial native balance: {initial_balance} {token}")
    else:
        # ERC20 токен
        initial_balance = check_token_balance(w3, wallet_address, token_contract_address)
        logger.info(f"{wallet_prefix}Initial {token} balance: {initial_balance}")
    
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
            
            logger.debug(f"{wallet_prefix}Current balance: {current_balance}, increase: {balance_increase}")
            
            # Если баланс увеличился на ожидаемую сумму (с небольшой погрешностью)
            if balance_increase >= expected_amount * 0.95:  # 95% от ожидаемой суммы
                logger.success(f"{wallet_prefix}Баланс поступил на кошелек {wallet_address}: +{balance_increase} {token}")
                return True
                
        except Exception as ex:
            logger.error(f"{wallet_prefix}Ошибка при проверке баланса {wallet_address}: {ex}")
            time.sleep(30)
    
    # Если время истекло - показываем красный баннер
    show_balance_timeout_error(wallet_address, expected_amount, token, wallet_number, total_wallets)
    return False


def show_balance_timeout_error(wallet_address, amount, token, wallet_number: int = 0, total_wallets: int = 0):
    """Показать красный баннер об ошибке с балансом"""
    wallet_prefix = f"[{wallet_number}/{total_wallets}] " if wallet_number > 0 else ""
    error_message = f"""
    ╔══════════════════════════════════════════════════════════════════════════════════════╗
    ║                                    ⚠️  ОШИБКА  ⚠️                                   ║
    ╠══════════════════════════════════════════════════════════════════════════════════════╣
    ║                                                                                      ║
    ║  🚨 ПОПОЛНЕНИЕ ОСТАНОВЛЕНО 🚨                                                       ║
    ║                                                                                      ║
    ║  {wallet_prefix}Кошелек: {wallet_address[:10]}...{wallet_address[-10:]}             ║
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
    
    db_file = os.path.join(db_path, 'okx_withdraw_progress.db')
    
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS withdraw_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                token TEXT NOT NULL,
                chain TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        ''')
        conn.commit()
    
    return db_file


def save_progress(db_file, wallet_address, token, chain, amount, status, error_message=None):
    """Сохранить прогресс в базу данных"""
    with db_lock:
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            
            if status == 'pending':
                cursor.execute('''
                    INSERT INTO withdraw_progress (wallet_address, token, chain, amount, status)
                    VALUES (?, ?, ?, ?, ?)
                ''', (wallet_address, token, chain, amount, status))
            else:
                cursor.execute('''
                    UPDATE withdraw_progress 
                    SET status = ?, error_message = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE wallet_address = ? AND token = ? AND chain = ? AND status = 'pending'
                ''', (status, error_message, wallet_address, token, chain))
            
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


def save_result_to_csv(wallet_address, token, chain, amount, status, error_message=None):
    """Сохранить результат в CSV файл"""
    result_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'result')
    os.makedirs(result_path, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = os.path.join(result_path, f'okx_withdraw_results_{timestamp[:8]}.csv')
    
    with csv_lock:
        file_exists = os.path.isfile(csv_file)
        
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            if not file_exists:
                writer.writerow(['timestamp', 'wallet_address', 'token', 'chain', 'amount', 'status', 'error_message'])
            
            writer.writerow([
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                wallet_address,
                token,
                chain,
                amount,
                status,
                error_message or ''
            ])


def process_single_wallet(wallet_data):
    """Обработать один кошелек"""
    wallet, token, chain, db_file, progress_bar, wallet_number, total_wallets, api_key, api_secret, passphrase = wallet_data
    
    try:
        wallet_prefix = f"[{wallet_number}/{total_wallets}] "
        logger.info(f'{wallet_prefix}[Thread] Processing wallet: {wallet}')
        
        # Получаем текущий баланс для расчета суммы
        current_balances = get_account_balances(api_key, api_secret, passphrase)
        if not current_balances or token not in current_balances:
            logger.error(f"{wallet_prefix}No balance found for {token}")
            save_progress(db_file, wallet, token, chain, 0, 'error', 'No balance available')
            save_result_to_csv(wallet, token, chain, 0, 'error', 'No balance available')
            progress_bar.update()
            return False
        
        # Рассчитываем индивидуальную сумму для этого кошелька
        individual_amount = calculate_individual_withdraw_amount(token, current_balances[token])
        
        # Обновляем запись в БД с реальной суммой
        save_progress(db_file, wallet, token, chain, individual_amount, 'processing')
        
        result = execute_okx_withdraw(wallet, token, chain, individual_amount, 
                                     api_key, api_secret, passphrase,
                                     wallet_number, total_wallets)
        
        if result:
            status = 'success'
            error_message = None
            
            # Проверяем поступление баланса если включено ожидание
            if WAIT_FOR_BALANCE:
                balance_received = check_wallet_balance(wallet, token, chain, individual_amount, wallet_number, total_wallets)
                if not balance_received:
                    status = 'balance_timeout'
                    error_message = 'Balance not received within timeout'
        else:
            status = 'failed'
            error_message = 'Withdrawal failed'
        
        # Сохраняем прогресс
        save_progress(db_file, wallet, token, chain, individual_amount, status, error_message)
        
        # Сохраняем результат в CSV
        save_result_to_csv(wallet, token, chain, individual_amount, status, error_message)
        
        # Обновляем прогресс-бар после завершения обработки кошелька
        progress_bar.update()
        
        return status == 'success'
        
    except Exception as ex:
        wallet_prefix = f"[{wallet_number}/{total_wallets}] " if wallet_number > 0 else ""
        logger.error(f'{wallet_prefix}Error processing wallet {wallet}: {ex}')
        save_progress(db_file, wallet, token, chain, 0, 'error', str(ex))
        save_result_to_csv(wallet, token, chain, 0, 'error', str(ex))
        progress_bar.update()
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
            pending_count = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM withdraw_progress WHERE status = "success"')
            success_count = cursor.fetchone()[0]
            
            logger.info(f"Найден существующий прогресс:")
            logger.info(f"Всего записей: {total_records}")
            logger.info(f"Ожидают обработки: {pending_count}")
            logger.info(f"Успешно завершено: {success_count}")
            
            if pending_count > 0:
                action = select(
                    "Что делать с существующим прогрессом?",
                    choices=[
                        Choice('🔄 Продолжить с того места где остановились', 'continue'),
                        Choice('🗑️ Очистить и начать заново', 'clear'),
                        Choice('❌ Отменить', 'cancel')
                    ]
                ).ask()
                
                if action == 'clear':
                    clear_progress_db(db_file)
                    return db_file, 'new'
                elif action == 'continue':
                    return db_file, 'continue'
                else:
                    return None, 'cancel'
            else:
                clear_progress_db(db_file)
                return db_file, 'new'
    
    return db_file, 'new'


def okx_withdraw():
    """Основная функция"""
    _setup_logging()
    logger.info("=== OKX Withdrawal Module ===")
    
    # Выбираем аккаунт OKX
    exchange_name, account = select_okx_account()
    if not account:
        logger.error("❌ Не выбран аккаунт OKX")
        return
    
    # Получаем данные аккаунта
    api_key = account['api_key']
    api_secret = account['api_secret'] 
    passphrase = account['passphrase']
    
    logger.info(f"🏢 Используется аккаунт: {account['name']}")
    
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
        balances = get_account_balances(api_key, api_secret, passphrase)
        if not balances:
            logger.error("No tokens with positive balance")
            return
        
        # Выбираем токен
        token = pick_token_to_withdraw(balances)
        if not token:
            return
        
        # Выбираем сеть
        chain = pick_chain(token, api_key, api_secret, passphrase)
        if not chain:
            continue
        
        # Рассчитываем примерную сумму для отображения (будет пересчитана для каждого кошелька)
        available_balance = balances[token]
        sample_withdraw_amount = calculate_withdraw_amount(token, available_balance)
        if sample_withdraw_amount is None:
            continue
        elif sample_withdraw_amount == "back":
            continue
        
        # Подтверждение (показываем примерный диапазон)
        if TYPE_WITHDRAW == 1:
            price_in_usdt = get_token_price_in_usdt(token)
            if price_in_usdt:
                usdt_from = VALUES_TO_WITHDRAW[0]
                usdt_to = VALUES_TO_WITHDRAW[1]
                confirm = select(
                    f"Вывести {usdt_from}-{usdt_to} USDT (≈{usdt_from/price_in_usdt:.6f}-{usdt_to/price_in_usdt:.6f} {token}) через сеть {chain} на {len(wallets)} кошельков?",
                    choices=[
                        Choice('❌ Нет, отменить операцию', False),
                        Choice('✅ Да, начать вывод средств', True),
                        Choice('🔙 Назад', "back")
                    ]
                ).ask()
            else:
                confirm = select(
                    f"Вывести {VALUES_TO_WITHDRAW[0]}-{VALUES_TO_WITHDRAW[1]} {token} через сеть {chain} на {len(wallets)} кошельков?",
                    choices=[
                        Choice('❌ Нет, отменить операцию', False),
                        Choice('✅ Да, начать вывод средств', True),
                        Choice('🔙 Назад', "back")
                    ]
                ).ask()
        else:
            confirm = select(
                f"Вывести {VALUES_TO_WITHDRAW[0]}-{VALUES_TO_WITHDRAW[1]} {token} через сеть {chain} на {len(wallets)} кошельков?",
                choices=[
                    Choice('❌ Нет, отменить операцию', False),
                    Choice('✅ Да, начать вывод средств', True),
                    Choice('🔙 Назад', "back")
                ]
            ).ask()
        
        if confirm == "back":
            continue
        elif not confirm:
            logger.warning("Withdrawal cancelled")
            return
        
        # Создаем записи в БД для новых кошельков (с временной суммой 0)
        if progress_action == 'new':
            for wallet in wallets:
                save_progress(db_file, wallet, token, chain, 0, 'pending')
        
        # Создаем прогресс-бар для отслеживания обработки кошельков
        progress_bar = BeautifulProgressBar(len(wallets), "Processing wallets", width=60)
        
        # Подготавливаем данные для потоков (добавляем прогресс-бар и номера кошельков)
        wallet_data_list = []
        for i, wallet in enumerate(wallets, 1):
            wallet_data_list.append((wallet, token, chain, db_file, progress_bar, i, len(wallets), api_key, api_secret, passphrase))
        
        # Выполняем выводы с использованием ThreadPoolExecutor
        logger.info(f"Starting withdrawals with {NUM_THREADS} threads...")
        successful = 0
        failed = 0
        
        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            # Создаем задержки между запусками потоков
            futures = []
            for i, wallet_data in enumerate(wallet_data_list):
                if i > 0:
                    time.sleep(random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1]))
                
                future = executor.submit(process_single_wallet, wallet_data)
                futures.append(future)
            
            # Ждем завершения всех потоков
            for future in futures:
                try:
                    result = future.result()
                    if result:
                        successful += 1
                    else:
                        failed += 1
                except Exception as ex:
                    logger.error(f"Thread execution error: {ex}")
                    failed += 1
        
        logger.info("=== Summary ===")
        logger.info(f"Successful withdrawals: {successful}")
        logger.info(f"Failed withdrawals: {failed}")
        logger.info(f"Total processed: {successful + failed}")
        
        # Проверяем, все ли кошельки обработаны успешно
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM withdraw_progress WHERE status = "pending"')
            remaining_pending = cursor.fetchone()[0]
            
            if remaining_pending == 0:
                logger.info("All wallets processed successfully. Cleaning up database...")
                clear_progress_db(db_file)
        
        break



if __name__ == '__main__':
    okx_withdraw()
