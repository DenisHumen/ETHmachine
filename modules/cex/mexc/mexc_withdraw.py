import requests
import base64
import random
import time
import hmac
import hashlib
import datetime
import sys
import os
import sqlite3
import csv
import json
import threading
from concurrent.futures import ThreadPoolExecutor
sys.__stdout__ = sys.stdout
from questionary import Choice, select
from web3 import Web3

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from modules.simple_logger import logger
from modules.proxy_manager import get_random_proxy_dict

def _get_mexc_settings():
    """Получить настройки MEXC с обработкой ошибок"""
    try:
        from config.cex_settings import MEXC_ACCOUNTS
        return MEXC_ACCOUNTS
    except ImportError:
        logger.error("Файл config/cex_settings.py не найден. Запустите main.py для создания.")
        return []
    except Exception as e:
        logger.error(f"Ошибка в настройках MEXC: {e}")
        return []

from config.modules.cfg_cex import TYPE_WITHDRAW, VALUES_TO_WITHDRAW, WAIT_FOR_BALANCE
from config.modules.cfg_base import SLEEP_BETWEEN_ACTIONS, NUM_THREADS
from config import networks as rpc
from modules.cex.exchange_selector import select_mexc_account

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
    
    logger.add(
        os.path.join(log_path, 'mexc_withdraw_errors.log'),
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        rotation="10 MB",
        retention="7 days"
    )

    logger.add(
        os.path.join(log_path, 'mexc_withdraw_full.log'),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {function} | {message}",
        rotation="50 MB",
        retention="3 days"
    )

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
        
        print(f'\r\033[K🚀 {self.desc}: |{bar}| {self.current}/{self.total} [{percentage:6.2f}%] ⏱️ {elapsed_str} ⏳ ETA: {eta_str}', end='', flush=True)
        
        if self.current >= self.total:
            print() 
    
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


def mexc_signature(query_string, secret_key):
    """Создать подпись для MEXC API согласно официальной документации"""
    try:
        sign = hmac.new(
            secret_key.encode('utf-8'), 
            query_string.encode('utf-8'), 
            hashlib.sha256
        ).hexdigest()
        return sign
    except Exception as ex:
        logger.error(f'MEXC signature error: {ex}')
        return None


def mexc_data(api_key, secret_key, request_path="/api/v3/account", body='', method="GET"):
    """Подготовить данные для запроса к MEXC API согласно официальной документации"""
    try:
        from urllib.parse import urlencode, quote
        
        server_time_response = requests.get('https://api.mexc.com/api/v3/time', timeout=10)
        server_time = server_time_response.json()['serverTime']
        req_time = server_time
        
        params = {}
        
        if '?' in request_path:
            path_parts = request_path.split('?')
            request_path = path_parts[0]
            existing_params = path_parts[1]
            for param in existing_params.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = value
        
        if method.upper() == 'POST' and body:
            if isinstance(body, str):
                body_data = json.loads(body)
            else:
                body_data = body
            params.update(body_data)
        
        params['timestamp'] = req_time
        
        if params:
            sign_params = urlencode(params, quote_via=quote)
            to_sign = "{}&timestamp={}".format(
                urlencode({k: v for k, v in params.items() if k != 'timestamp'}, quote_via=quote),
                req_time
            ) if len(params) > 1 else "timestamp={}".format(req_time)
        else:
            to_sign = "timestamp={}".format(req_time)
            sign_params = to_sign
        
        signature = mexc_signature(to_sign, secret_key)
        if not signature:
            return None, None, None, None
        
        params['signature'] = signature
        
        headers = {
            "X-MEXC-APIKEY": api_key,
            "Content-Type": "application/json"
        }
        
        return "https://api.mexc.com", request_path, headers, params
            
    except Exception as ex:
        logger.error(f'MEXC data error: {ex}')
        return None, None, None, None


def get_token_price_in_usdt(token):
    """Получить цену токена в USDT через API MEXC"""
    try:
        if token == 'USDT':
            return 1.0
        
        response = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={token}USDT", timeout=10)
        data = response.json()
        if 'price' in data:
            return float(data['price'])
        return None
    except Exception as ex:
        logger.error(f'Error getting price for {token}: {ex}')
        return None


def get_account_balances(mexc_api_key, mexc_api_secret):
    """Получить все балансы аккаунта"""
    try:
        base_url, request_path, headers, params = mexc_data(mexc_api_key, mexc_api_secret,
                                                           request_path="/api/v3/account", method="GET")
        
        if not headers:
            logger.error("Failed to create MEXC headers")
            return {}
        
        proxy = get_random_proxy_dict()
        
        response = requests.get(f"{base_url}{request_path}", params=params, timeout=10, headers=headers, proxies=proxy)
        data = response.json()
        
        balances = {}
        if 'balances' in data:
            for item in data['balances']:
                available = float(item['free'])
                if available > 0:
                    balances[item['asset']] = available
        
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


def pick_chain(token, mexc_api_key, mexc_api_secret):
    """Выбор сети для вывода"""
    try:
        base_url, request_path, headers, params = mexc_data(mexc_api_key, mexc_api_secret,
                                                           request_path="/api/v3/capital/config/getall", method="GET")
        
        if not headers:
            logger.error("Failed to create MEXC headers")
            return None
            
        proxy = get_random_proxy_dict()
        
        response = requests.get(base_url + request_path, headers=headers, params=params, proxies=proxy, timeout=10)
        
        chains = []
        chain_info_list = []  
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                for coin_data in data:
                    if coin_data['coin'] == token:
                        for network_info in coin_data['networkList']:
                            if network_info['withdrawEnable']:  
                                chain_name = network_info.get('netWork', network_info.get('network', 'Unknown'))
                                withdraw_fee = network_info['withdrawFee']
                                min_withdraw = network_info['withdrawMin']
                                
                                chains.append(chain_name)
                                chain_info_list.append({
                                    'chain': chain_name,
                                    'withdrawFee': withdraw_fee,
                                    'minWithdrawAmount': min_withdraw
                                })
                        break
            else:
                logger.warning(f"Unexpected response format for token {token}")
        else:
            logger.error(f"API request failed: {response.status_code}, {response.text}")
        
        if not chains:
            logger.error(f"No withdrawal chains available for {token}")
            return None
        
        choices = []
        for chain_info in chain_info_list:
            chain = chain_info['chain']
            fee = chain_info['withdrawFee']
            min_amount = chain_info['minWithdrawAmount']
            
            warning = ""
            if "Optimism" in chain:
                warning = " ⚠️ (возможны проблемы)"
            
            choice_text = f"🔗 {chain:<15} | Fee: {fee} {token} | Min: {min_amount} {token}{warning}"
            choices.append(Choice(choice_text, chain))
        
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
    if TYPE_WITHDRAW == 1:  
        price_in_usdt = get_token_price_in_usdt(token)
        if price_in_usdt is None:
            logger.warning(f"Cannot get price for {token}, using native amount")
            amount_from, amount_to = VALUES_TO_WITHDRAW[0], VALUES_TO_WITHDRAW[1]
        else:
            amount_from = VALUES_TO_WITHDRAW[0] / price_in_usdt
            amount_to = VALUES_TO_WITHDRAW[1] / price_in_usdt
            logger.info(f"Price {token}/USDT: {price_in_usdt}")
            logger.info(f"Withdraw range in {token}: {amount_from:.6f} - {amount_to:.6f}")
    else:  
        amount_from, amount_to = VALUES_TO_WITHDRAW[0], VALUES_TO_WITHDRAW[1]
    
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
    if TYPE_WITHDRAW == 1:  
        price_in_usdt = get_token_price_in_usdt(token)
        if price_in_usdt is None:
            logger.warning(f"Cannot get price for {token}, using native amount")
            amount_from, amount_to = VALUES_TO_WITHDRAW[0], VALUES_TO_WITHDRAW[1]
        else:
            amount_from = VALUES_TO_WITHDRAW[0] / price_in_usdt
            amount_to = VALUES_TO_WITHDRAW[1] / price_in_usdt
    else:  
        amount_from, amount_to = VALUES_TO_WITHDRAW[0], VALUES_TO_WITHDRAW[1]
    
    if amount_from > available_balance:
        logger.warning(f"Insufficient balance. Need at least {amount_from} {token}, but have {available_balance}. Using all available balance.")
        return available_balance
    
    if amount_to > available_balance:
        amount_to = available_balance
    
    return round(random.uniform(amount_from, amount_to), 6)


def get_withdraw_fee(token, chain, mexc_api_key, mexc_api_secret):
    """Получить комиссию за вывод"""
    try:
        base_url, request_path, headers, params = mexc_data(mexc_api_key, mexc_api_secret,
                                                           request_path="/api/v3/capital/config/getall", method="GET")
        
        if not headers:
            logger.error("Failed to create MEXC headers")
            return 0
            
        proxy = get_random_proxy_dict()
        
        response = requests.get(base_url + request_path, headers=headers, params=params, proxies=proxy, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                for coin_data in data:
                    if coin_data['coin'] == token:
                        for network_info in coin_data['networkList']:
                            network_name = network_info.get('netWork', network_info.get('network', ''))
                            if network_name == chain:
                                return float(network_info['withdrawFee'])
        
        logger.warning(f"Could not get withdraw fee for {token}-{chain}")
        return 0
    except Exception as ex:
        logger.error(f'Error getting fee for {token}-{chain}: {ex}')
        return 0


def execute_mexc_withdraw(wallet: str, token: str, chain: str, amount: float, 
                         mexc_api_key, mexc_api_secret, 
                         wallet_number: int = 0, total_wallets: int = 0, retry=0):
    """Выполнить вывод средств"""
    wallet_prefix = f"[{wallet_number}/{total_wallets}] " if wallet_number > 0 else ""
    logger.info(f'{wallet_prefix}[{wallet}] Starting withdrawal of {amount} {token}')
    
    try:
        fee = get_withdraw_fee(token, chain)
        
        body_data = {
            "coin": token,
            "address": wallet,
            "netWork": chain, 
            "amount": str(amount)
        }
        
        base_url, request_path, headers, params = mexc_data(mexc_api_key, mexc_api_secret,
                                                           request_path="/api/v3/capital/withdraw", 
                                                           method="POST", body=json.dumps(body_data))
        
        if not headers:
            logger.error(f"{wallet_prefix}Failed to create MEXC headers")
            return None
        
        logger.debug(f"{wallet_prefix}Request URL: {base_url}{request_path}")
        logger.debug(f"{wallet_prefix}Request headers: {headers}")
        logger.debug(f"{wallet_prefix}Request params: {params}")
        
        proxy = get_random_proxy_dict()
        
        response = requests.post(f"{base_url}{request_path}", 
                                params=params, timeout=10, headers=headers, proxies=proxy)
        
        try:
            result = response.json()
        except:
            logger.error(f"{wallet_prefix}Failed to parse response as JSON: {response.text}")
            return None
        
        if response.status_code == 200 and 'id' in result:
            logger.success(f"{wallet_prefix}MEXC withdraw success => {wallet} | {amount} {token} | ID: {result['id']}")
            return amount
        else:
            error = result.get('msg', f'HTTP {response.status_code}: {response.text}')
            error_code = result.get('code', 'Unknown')
            
            if error_code == 10232:
                logger.error(f"{wallet_prefix}MEXC withdraw failed => {wallet} | Error 10232: 'Coin is not exist' - возможно сеть {chain} недоступна для {token} или требуется дополнительная верификация")
            elif error_code == 700002:
                logger.error(f"{wallet_prefix}MEXC withdraw failed => {wallet} | Error 700002: 'Signature invalid' - проблема с подписью запроса")
            elif error_code == 152056:
                logger.error(f"{wallet_prefix}MEXC withdraw failed => {wallet} | Error 152056: 'Contract address cannot be empty' - возможно нужен memo/tag")
            else:
                logger.error(f"{wallet_prefix}MEXC withdraw failed => {wallet} | error: {error}")
                
            if retry < 3 and error_code != 10232:  
                time.sleep(10)
                return execute_mexc_withdraw(wallet, token, chain, amount, 
                                            mexc_api_key, mexc_api_secret, 
                                            wallet_number, total_wallets, retry + 1)
            
    except Exception as error:
        logger.error(f"{wallet_prefix}MEXC withdraw error => {wallet} | {error}")
        if retry < 3:
            time.sleep(10)
            return execute_mexc_withdraw(wallet, token, chain, amount, 
                                        mexc_api_key, mexc_api_secret, 
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
        'BASE': rpc.base,
        'ArbitrumOne': rpc.arbitrum,
        'Arbitrum One': rpc.arbitrum,
        'Arbitrum': rpc.arbitrum,
        'ARB': rpc.arbitrum, 
        'Optimism': rpc.optimism,
        'OP': rpc.optimism, 
        'Polygon': rpc.Polygon,
        'BSC': rpc.Binance_Smart_Chain,
        'BNB Smart Chain (BEP20)': rpc.Binance_Smart_Chain,
        'BEP20(BSC)': rpc.Binance_Smart_Chain,
        'Avalanche C-Chain': rpc.Avalanche,
        'AVAXC-Chain': rpc.Avalanche,
        'Avalanche': rpc.Avalanche,
        'Fantom': rpc.Fantom,
        'Gravity Alpha Mainnet': rpc.Gravity_Alpha_Mainnet,
        'Gravity': rpc.Gravity_Alpha_Mainnet,
        'Zora': rpc.zora,
        'Abstract': rpc.Abstract,
        'Soneium': rpc.soneium,
        'Somnia': rpc.somnia,
        'Sepolia': rpc.sepolia,
        'Kite Testnet': rpc.kite_testnet,
        'MegaETH Testnet': rpc.mega_eth_testnet,
        'Pharos Testnet': rpc.pharos_testnet,
        'TRC20': rpc.L1,  
        'SOL': rpc.L1,    
    }
    
    return chain_mapping.get(chain, rpc.L1)  


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
    token_addresses = {
        'USDT': {
            'ERC20': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'Ethereum': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'BSC': '0x55d398326f99059fF775485246999027B3197955',
            'BEP20(BSC)': '0x55d398326f99059fF775485246999027B3197955',
            'Polygon': '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
            'Arbitrum': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'ArbitrumOne': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'Optimism': '0x94b008aA00579c1307B0EF2c499aD98a8ce58e58',
            'Base': '0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2',
            'BASE': '0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2',
            'Avalanche': '0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7',
            'TRC20': '0x0000000000000000000000000000000000000000'  
        },
        'USDC': {
            'ERC20': '0xA0b86a33E6441b33F5A4dF7a54fA0Fbc9B1bF0e2',
            'Ethereum': '0xA0b86a33E6441b33F5A4dF7a54fA0Fbc9B1bF0e2',
            'BSC': '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d',
            'BEP20(BSC)': '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d',
            'Polygon': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174',
            'Arbitrum': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
            'ArbitrumOne': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
            'Optimism': '0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85',
            'Base': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
            'BASE': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
            'Avalanche': '0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E'
        },
        'ETH': {
            'Ethereum': '0x0000000000000000000000000000000000000000',
            'ERC20': '0x0000000000000000000000000000000000000000',
            'ETH': '0x0000000000000000000000000000000000000000',
            'Arbitrum': '0x0000000000000000000000000000000000000000',
            'ArbitrumOne': '0x0000000000000000000000000000000000000000',
            'Optimism': '0x0000000000000000000000000000000000000000',
            'Base': '0x0000000000000000000000000000000000000000',
            'BASE': '0x0000000000000000000000000000000000000000',
            'Polygon': '0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619',  
            'BSC': '0x2170Ed0880ac9A755fd29B2688956BD959F933F8',     
            'BEP20(BSC)': '0x2170Ed0880ac9A755fd29B2688956BD959F933F8'
        },
        'BTC': {
            'BTC': '0x0000000000000000000000000000000000000000',
            'Bitcoin': '0x0000000000000000000000000000000000000000'
        },
        'BNB': {
            'BSC': '0x0000000000000000000000000000000000000000',
            'BEP20(BSC)': '0x0000000000000000000000000000000000000000'
        },
        'MATIC': {
            'Polygon': '0x0000000000000000000000000000000000000000'
        },
        'AVAX': {
            'Avalanche': '0x0000000000000000000000000000000000000000',
            'AVAXC-Chain': '0x0000000000000000000000000000000000000000'
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
        
        balance_wei = contract.functions.balanceOf(wallet_address).call()
        
        decimals = contract.functions.decimals().call()
        
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
    
    w3 = get_working_web3_connection(chain)
    if not w3:
        logger.warning(f"{wallet_prefix}Cannot connect to {chain} network, skipping balance check")
        return True
    
    token_contract_address = get_token_contract_address(token, chain)
    logger.debug(f"{wallet_prefix}Token: {token}, Chain: {chain}, Contract: {token_contract_address}")
    
    if token_contract_address == '0x0000000000000000000000000000000000000000' or token_contract_address is None:
        initial_balance = check_native_balance(w3, wallet_address)
        logger.info(f"{wallet_prefix}Checking native token balance for {token} on {chain}: {initial_balance}")
    else:
        initial_balance = check_token_balance(w3, wallet_address, token_contract_address)
        logger.info(f"{wallet_prefix}Checking ERC20 token balance for {token} on {chain}: {initial_balance}")
    
    if initial_balance is None:
        logger.error(f"{wallet_prefix}Failed to get initial balance, skipping balance check")
        return True
    
    if initial_balance >= expected_amount * 0.95:
        logger.success(f"{wallet_prefix}Баланс уже поступил на кошелек {wallet_address}: {initial_balance} {token} (ожидалось {expected_amount})")
        return True
    
    timeout_seconds = timeout_hours * 3600  
    start_time = time.time()
    check_interval = 30  
    
    while time.time() - start_time < timeout_seconds:
        try:
            time.sleep(check_interval)
            
            if token_contract_address == '0x0000000000000000000000000000000000000000' or token_contract_address is None:
                current_balance = check_native_balance(w3, wallet_address)
            else:
                current_balance = check_token_balance(w3, wallet_address, token_contract_address)
            
            if current_balance is None:
                logger.warning(f"{wallet_prefix}Failed to get current balance, retrying...")
                continue
            
            balance_increase = current_balance - initial_balance
            
            if balance_increase >= expected_amount * 0.95: 
                logger.success(f"{wallet_prefix}Баланс поступил на кошелек {wallet_address}: +{balance_increase} {token}")
                return True
            elif balance_increase > 0:
                pass
                
        except Exception as ex:
            logger.error(f"{wallet_prefix}Ошибка при проверке баланса {wallet_address}: {ex}")
            time.sleep(30)
    
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
    
    db_file = os.path.join(db_path, 'mexc_withdraw_progress.db')
    
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
    csv_file = os.path.join(result_path, f'mexc_withdraw_results_{timestamp[:8]}.csv')
    
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
    wallet, token, chain, db_file, progress_bar, wallet_number, total_wallets, mexc_api_key, mexc_api_secret = wallet_data
    
    try:
        wallet_prefix = f"[{wallet_number}/{total_wallets}] "
        
        current_balances = get_account_balances(mexc_api_key, mexc_api_secret)
        if not current_balances or token not in current_balances:
            logger.error(f"{wallet_prefix}No balance found for {token}")
            save_progress(db_file, wallet, token, chain, 0, 'error', 'No balance available')
            save_result_to_csv(wallet, token, chain, 0, 'error', 'No balance available')
            progress_bar.update()
            return False
        
        individual_amount = calculate_individual_withdraw_amount(token, current_balances[token])
        
        save_progress(db_file, wallet, token, chain, individual_amount, 'processing')
        
        result = execute_mexc_withdraw(wallet, token, chain, individual_amount, 
                                      mexc_api_key, mexc_api_secret, 
                                      wallet_number, total_wallets)
        
        if result:
            status = 'success'
            error_message = None
            
            if WAIT_FOR_BALANCE:
                balance_received = check_wallet_balance(wallet, token, chain, individual_amount, wallet_number, total_wallets)
                if not balance_received:
                    status = 'balance_timeout'
                    error_message = 'Balance not received within timeout'
        else:
            status = 'failed'
            error_message = 'Withdrawal failed'
        
        save_progress(db_file, wallet, token, chain, individual_amount, status, error_message)
        
        save_result_to_csv(wallet, token, chain, individual_amount, status, error_message)
        
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


def mexc_withdraw():
    """Основная функция"""
    _setup_logging()
    logger.info("=== MEXC Withdrawal Module ===")
    
    # Выбор аккаунта MEXC
    exchange_name, selected_account = select_mexc_account()
    if not selected_account:
        logger.error("❌ Не выбран аккаунт MEXC")
        return
    
    # Обновляем переменные API ключей
    mexc_api_key = selected_account['api_key']
    mexc_api_secret = selected_account['api_secret']
    
    logger.info(f"Используется аккаунт MEXC: {selected_account['name']}")
    
    db_file, progress_action = check_existing_progress()
    if progress_action == 'cancel':
        logger.info("Операция отменена")
        return
    
    all_wallets = load_wallets()
    if not all_wallets:
        logger.error("No wallets found")
        return
    
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
        balances = get_account_balances(mexc_api_key, mexc_api_secret)
        if not balances:
            logger.error("No tokens with positive balance")
            return
        
        token = pick_token_to_withdraw(balances)
        if not token:
            return
        
        chain = pick_chain(token, mexc_api_key, mexc_api_secret)
        if not chain:
            continue
        
        available_balance = balances[token]
        sample_withdraw_amount = calculate_withdraw_amount(token, available_balance)
        if sample_withdraw_amount is None:
            continue
        elif sample_withdraw_amount == "back":
            continue
        
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
        
        if progress_action == 'new':
            for wallet in wallets:
                save_progress(db_file, wallet, token, chain, 0, 'pending')
        
        progress_bar = BeautifulProgressBar(len(wallets), "Processing wallets", width=60)
        
        wallet_data_list = []
        for i, wallet in enumerate(wallets, 1):
            wallet_data_list.append((wallet, token, chain, db_file, progress_bar, i, len(wallets), mexc_api_key, mexc_api_secret))
        
        logger.info(f"Starting withdrawals with {NUM_THREADS} threads...")
        successful = 0
        failed = 0
        
        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            futures = []
            for i, wallet_data in enumerate(wallet_data_list):
                if i > 0:
                    time.sleep(random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1]))
                
                future = executor.submit(process_single_wallet, wallet_data)
                futures.append(future)
            
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
        
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM withdraw_progress WHERE status = "pending"')
            remaining_pending = cursor.fetchone()[0]
            
            if remaining_pending == 0:
                logger.info("All wallets processed successfully. Cleaning up database...")
                clear_progress_db(db_file)
        
        break



if __name__ == '__main__':
    mexc_withdraw()