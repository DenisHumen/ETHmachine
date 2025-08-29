import os
import sys
import csv
import json
import time
import random
import sqlite3
import platform
import requests
from typing import Dict, List, Optional, Tuple
from web3 import Web3
from loguru import logger
from questionary import Choice, select

# Добавляем путь к корневой директории проекта
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
sys.path.append(project_root)

# Импорты из проекта
from config.config import SUM_TO_RELAY, NETWORKS_TO_RELAY, GAS, MAIN_PROXY
from config.rpc import *
from config.explorer_url import get_explorer_url
from modules.relay_link.settings.settings_relay_link import *

# Настройка логирования
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
    colorize=True
)

# Функции для цветного логирования
def log_info(message: str):
    """Информационное сообщение - синий цвет"""
    logger.opt(colors=True).info(f"<blue>{message}</blue>")

def log_success(message: str):
    """Успешное сообщение - зеленый цвет"""
    logger.opt(colors=True).success(f"<green>{message}</green>")

def log_warning(message: str):
    """Предупреждение - желтый цвет"""
    logger.opt(colors=True).warning(f"<yellow>{message}</yellow>")

def log_error(message: str):
    """Ошибка - красный цвет"""
    logger.opt(colors=True).error(f"<red>{message}</red>")

def log_transaction(message: str):
    """Транзакционные сообщения - фиолетовый цвет"""
    logger.opt(colors=True).info(f"<magenta>{message}</magenta>")

def log_balance(message: str):
    """Балансовые сообщения - голубой цвет"""
    logger.opt(colors=True).info(f"<cyan>{message}</cyan>")

def log_progress(message: str):
    """Прогресс выполнения - белый цвет с выделением"""
    logger.opt(colors=True).info(f"<bold><white>{message}</white></bold>")

class RelayBridge:
    def __init__(self):
        self.base_url = "https://api.relay.link"
        self.current_private_key = None
        self.current_wallet_address = None
        self.current_proxy = None
        self.db_path = os.path.join(project_root, 'db', 'relay_progress.db')
        self.result_path = os.path.join(project_root, 'result', 'relay_link.csv')
        
        # Инициализация базы данных
        self._init_database()
        
        # Загрузка данных
        self.private_keys = self._load_private_keys()
        self.proxies = self._load_proxies()
        
        # Настройка RPC для сетей
        self.rpc_pools = {
            1: L1,  # Ethereum
            10: optimism,  # Optimism
            137: Polygon,  # Polygon
            8453: base,  # Base
            42161: arbitrum  # Arbitrum
        }
        
        # Маппинг chain_id на названия сетей в explorer_url.py
        self.chain_id_to_explorer_network = {
            1: '🚀 Ethereum Mainnet',
            10: '🚀 Optimism',
            137: '🚀 Polygon',
            8453: '🚀 Base',
            42161: '🚀 Arbitrum One'
        }
        
        # Кеш для Web3 подключений
        self.web3_connections = {}
        
        # Инициализация CSV файла с заголовками
        self._init_csv_file()
    
    def _init_database(self):
        """Инициализация базы данных для отслеживания прогресса"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS relay_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                private_key_hash TEXT NOT NULL,
                from_network TEXT NOT NULL,
                to_network TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                tx_hash TEXT,
                gas_used REAL,
                gas_cost REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                error_message TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def _init_csv_file(self):
        """Инициализация CSV файла с заголовками"""
        os.makedirs(os.path.dirname(self.result_path), exist_ok=True)
        
        # Всегда создаем новый файл или перезаписываем существующий
        with open(self.result_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            headers = [
                'Wallet Address',
                'From Network', 
                'To Network', 
                'Amount Sent',
                'Transaction Hash', 
                'Gas Cost (ETH)', 
                'Status', 
                'Timestamp',
                'Amount Received',
                'Bridge Fee'
            ]
            writer.writerow(headers)
        
        log_info(f"📝 Инициализирован файл результатов: {self.result_path}")
    
    def _load_private_keys(self) -> List[str]:
        """Загрузка приватных ключей из файла"""
        keys_path = os.path.join(project_root, 'data', 'private_keys.txt')
        if not os.path.exists(keys_path):
            log_error(f"❌ Файл с приватными ключами не найден: {keys_path}")
            return []
        
        with open(keys_path, 'r', encoding='utf-8') as f:
            keys = [line.strip() for line in f if line.strip()]
        
        log_info(f"📂 Загружено {len(keys)} приватных ключей")
        return keys
    
    def _load_proxies(self) -> List[str]:
        """Загрузка прокси из файла"""
        proxy_path = os.path.join(project_root, 'data', 'proxy.csv')
        if not os.path.exists(proxy_path):
            log_warning(f"⚠️ Файл с прокси не найден: {proxy_path}")
            return []
        
        proxies = []
        with open(proxy_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if row and len(row) > 0:
                    proxies.append(row[0].strip())
        
        log_info(f"🌐 Загружено {len(proxies)} прокси")
        return proxies
    
    def _get_random_proxy_for_api(self) -> Optional[str]:
        """Получение случайного прокси для API запросов"""
        # Сначала пробуем использовать случайный прокси из списка
        if self.proxies:
            return random.choice(self.proxies)
        
        # Если список пуст, используем MAIN_PROXY
        if MAIN_PROXY:
            return MAIN_PROXY
        
        # Если нет ни того, ни другого, возвращаем None
        return None
    
    def _get_proxy_for_wallet(self, wallet_index: int) -> Optional[str]:
        """Получение прокси для кошелька"""
        if not self.proxies:
            return None
        
        if len(self.proxies) >= len(self.private_keys):
            # 1к1 соответствие
            return self.proxies[wallet_index % len(self.proxies)]
        else:
            # Случайный выбор
            return random.choice(self.proxies)
    
    def _get_web3_connection(self, chain_id: int) -> Optional[Web3]:
        """Получение Web3 подключения с ротацией RPC"""
        if chain_id not in self.rpc_pools:
            log_error(f"❌ Нет RPC для сети {chain_id}")
            return None
        
        cache_key = chain_id
        if cache_key in self.web3_connections:
            web3 = self.web3_connections[cache_key]
            if web3.is_connected():
                return web3
        
        # Перебираем RPC пока не найдем рабочий
        rpc_list = self.rpc_pools[chain_id]
        for rpc_url in rpc_list:
            try:
                web3 = Web3(Web3.HTTPProvider(rpc_url))
                if web3.is_connected():
                    self.web3_connections[cache_key] = web3
                    logger.debug(f"🔗 Подключено к {NETWORK_SETTINGS[chain_id]['name']}: {rpc_url}")
                    return web3
            except Exception as e:
                logger.debug(f"⚠️ RPC {rpc_url} недоступен: {e}")
                continue
        
        log_error(f"❌ Все RPC для сети {chain_id} недоступны")
        return None
    
    def _get_native_balance(self, chain_id: int, wallet_address: str) -> float:
        """Получение баланса нативного токена"""
        web3 = self._get_web3_connection(chain_id)
        if not web3:
            return 0.0
        
        try:
            balance_wei = web3.eth.get_balance(wallet_address)
            balance = web3.from_wei(balance_wei, 'ether')
            return float(balance)
        except Exception as e:
            log_error(f"❌ Ошибка получения баланса {NETWORK_SETTINGS[chain_id]['name']}: {e}")
            return 0.0
    
    def _get_transaction_explorer_link(self, chain_id: int, tx_hash: str) -> str:
        """Получение ссылки на транзакцию в explorer"""
        explorer_network = self.chain_id_to_explorer_network.get(chain_id)
        if explorer_network:
            explorer_url = get_explorer_url(explorer_network)
            if explorer_url and not explorer_url.startswith("ошибка"):
                return f"{explorer_url}{tx_hash}"
        
        # Fallback для неизвестных сетей
        network_name = NETWORK_SETTINGS.get(chain_id, {}).get('name', 'Unknown')
        return f"Транзакция {tx_hash} в сети {network_name}"
    
    def _check_balances(self, wallet_address: str) -> Dict[str, Dict]:
        """Проверка балансов во всех сетях"""
        balances = {}
        
        log_info(f"🔍 Проверка балансов для кошелька: {wallet_address}")
        
        for network_name in NETWORKS_TO_RELAY:
            if network_name not in NETWORK_MAPPING:
                log_error(f"❌ Сеть {network_name} не найдена в NETWORK_MAPPING!")
                log_info(f"📋 Доступные сети: {list(NETWORK_MAPPING.keys())}")
                continue
            
            chain_id = NETWORK_MAPPING[network_name]
            balance = self._get_native_balance(chain_id, wallet_address)
            
            if balance > 0:
                balances[network_name] = {
                    'chain_id': chain_id,
                    'balance': balance,
                    'symbol': NETWORK_SETTINGS[chain_id]['native_symbol']
                }
                log_success(f"✅ Найден баланс в {network_name}: {balance:.6f} {NETWORK_SETTINGS[chain_id]['native_symbol']}")
            else:
                log_info(f"ℹ️ Нулевой баланс в {network_name}")
        
        log_info(f"📊 Итого найдено сетей с балансом: {len(balances)}")
        return balances
    
    def _get_quote(self, from_chain_id: int, to_chain_id: int, amount_wei: int, wallet_address: str) -> Optional[Dict]:
        """Получение котировки для бриджа"""
        url = f"{self.base_url}/quote"
        
        # Получаем адреса нативных токенов
        from_token = TOKEN_ADDRESSES[from_chain_id][NETWORK_SETTINGS[from_chain_id]['native_symbol']]
        to_token = TOKEN_ADDRESSES[to_chain_id][NETWORK_SETTINGS[to_chain_id]['native_symbol']]
        
        payload = {
            "user": wallet_address,
            "originChainId": from_chain_id,
            "destinationChainId": to_chain_id,
            "originCurrency": from_token,
            "destinationCurrency": to_token,
            "amount": str(amount_wei),
            "tradeType": "EXACT_INPUT",
            "recipient": wallet_address,
            "slippageBps": "0",
            "useExternalLiquidity": False
        }
        
        headers = {"Content-Type": "application/json"}
        
        try:
            # Используем случайный прокси для API запроса
            api_proxy = self._get_random_proxy_for_api()
            proxies = None
            if api_proxy:
                proxies = {
                    'http': f'http://{api_proxy}',
                    'https': f'http://{api_proxy}'
                }
            
            response = requests.post(url, json=payload, headers=headers, proxies=proxies, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log_error(f"❌ Ошибка получения котировки: {e}")
            return None
    
    def _execute_bridge(self, quote_data: Dict, wallet_address: str, private_key: str) -> bool:
        """Выполнение бридж транзакции"""
        try:
            steps = quote_data.get('steps', [])
            if not steps:
                log_error("❌ Нет шагов в котировке")
                return False
            
            # Находим шаг с транзакцией
            tx_step = None
            for step in steps:
                if step.get('kind') == 'transaction':
                    tx_step = step
                    break
            
            if not tx_step:
                log_error("❌ Не найден шаг с транзакцией")
                return False
            
            items = tx_step.get('items', [])
            if not items:
                log_error("❌ Нет элементов транзакции")
                return False
            
            tx_data = items[0].get('data', {})
            if not tx_data:
                log_error("❌ Нет данных транзакции")
                return False
            
            # Подключение к сети
            chain_id = tx_data.get('chainId', 1)
            web3 = self._get_web3_connection(chain_id)
            if not web3:
                return False
            
            # Подготовка транзакции
            account = web3.eth.account.from_key(private_key)
            
            value_amount = tx_data.get('value', '0')
            if isinstance(value_amount, str):
                value_amount = int(value_amount) if value_amount != '0' else 0
            elif value_amount is None:
                value_amount = 0
            
            # Создание и оценка транзакции для получения лимита газа
            transaction_for_estimate = {
                'from': wallet_address,
                'to': Web3.to_checksum_address(tx_data['to']),
                'data': tx_data.get('data', '0x'),
                'value': value_amount,
                'nonce': web3.eth.get_transaction_count(wallet_address),
                'chainId': chain_id  # Добавляем chainId для EIP-155
            }
            
            try:
                estimated_gas = web3.eth.estimate_gas(transaction_for_estimate)
                gas_limit = int(estimated_gas * 1.2)
            except Exception as e:
                log_warning(f"⚠️ Не удалось оценить газ: {e}")
                gas_limit = tx_data.get('gas', 200000)
                if isinstance(gas_limit, str):
                    gas_limit = int(gas_limit)
                gas_limit = int(gas_limit * 1.1)
            
            # Ожидание приемлемой цены газа с учетом лимита
            log_info("🔍 Проверка стоимости газа...")
            
            # Проверяем поддержку EIP-1559 (Type 2 transactions)
            try:
                latest_block = web3.eth.get_block('latest')
                supports_eip1559 = hasattr(latest_block, 'baseFeePerGas') and latest_block.baseFeePerGas is not None
            except:
                supports_eip1559 = False
            
            # Финальная транзакция
            if supports_eip1559:
                # EIP-1559 транзакция (Type 2)
                log_info("🔄 Используем EIP-1559 транзакцию")
                
                # Получаем базовую комиссию
                latest_block = web3.eth.get_block('latest')
                base_fee = latest_block.baseFeePerGas
                
                # Устанавливаем разумные значения для Optimism
                max_priority_fee_per_gas = web3.to_wei('0.001', 'gwei')  # 0.001 gwei tip для L2
                max_fee_per_gas = base_fee + max_priority_fee_per_gas
                
                final_transaction = {
                    'to': Web3.to_checksum_address(tx_data['to']),
                    'data': tx_data.get('data', '0x'),
                    'value': value_amount,
                    'gas': gas_limit,
                    'maxFeePerGas': max_fee_per_gas,
                    'maxPriorityFeePerGas': max_priority_fee_per_gas,
                    'nonce': web3.eth.get_transaction_count(wallet_address),
                    'chainId': chain_id,
                    'type': 2  # EIP-1559 transaction type
                }
            else:
                # Legacy транзакция (Type 0)
                log_info("🔄 Используем legacy транзакцию")
                gas_price = self._wait_for_acceptable_gas_price(web3, gas_limit, chain_id)
                
                final_transaction = {
                    'to': Web3.to_checksum_address(tx_data['to']),
                    'data': tx_data.get('data', '0x'),
                    'value': value_amount,
                    'gas': gas_limit,
                    'gasPrice': gas_price,
                    'nonce': web3.eth.get_transaction_count(wallet_address),
                    'chainId': chain_id  # Добавляем chainId для EIP-155 (replay protection)
                }
            
            # Подпись и отправка
            signed_tx = web3.eth.account.sign_transaction(final_transaction, private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Получаем ссылку на explorer
            explorer_link = self._get_transaction_explorer_link(chain_id, tx_hash.hex())
            log_transaction(f"📤 Транзакция отправлена: {explorer_link}")
            
            # Ожидание подтверждения
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=TRANSACTION_TIMEOUT)
            
            if receipt.status == 1:
                actual_gas_used = receipt.gasUsed
                
                # Получаем эффективную цену газа из receipt
                if hasattr(receipt, 'effectiveGasPrice'):
                    effective_gas_price = receipt.effectiveGasPrice
                else:
                    # Fallback для старых версий или если effectiveGasPrice недоступен
                    if supports_eip1559:
                        effective_gas_price = max_fee_per_gas
                    else:
                        effective_gas_price = gas_price
                
                actual_cost = actual_gas_used * effective_gas_price
                actual_cost_eth = web3.from_wei(actual_cost, 'ether')
                
                log_success(f"✅ Транзакция подтверждена. Газ: {actual_gas_used}, Стоимость: {actual_cost_eth:.8f} ETH")
                
                # Сохранение результата в БД
                self._save_transaction_result(
                    wallet_address, tx_hash.hex(), actual_gas_used, float(actual_cost_eth), 'completed'
                )
                return True
            else:
                explorer_link = self._get_transaction_explorer_link(chain_id, tx_hash.hex())
                log_error(f"❌ Транзакция провалилась: {explorer_link}")
                self._save_transaction_result(wallet_address, tx_hash.hex(), 0, 0, 'failed')
                return False
                
        except Exception as e:
            log_error(f"❌ Ошибка выполнения транзакции: {e}")
            self._save_transaction_result(wallet_address, None, 0, 0, 'error', str(e))
            return False
    
    def _save_transaction_result(self, wallet_address: str, tx_hash: str, gas_used: int, gas_cost: float, status: str, error_msg: str = None):
        """Сохранение результата транзакции в БД"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE relay_progress 
            SET tx_hash = ?, gas_used = ?, gas_cost = ?, status = ?, completed_at = CURRENT_TIMESTAMP, error_message = ?
            WHERE wallet_address = ? AND status = 'pending'
        ''', (tx_hash, gas_used, gas_cost, status, error_msg, wallet_address))
        
        conn.commit()
        conn.close()
    
    def _save_to_csv(self, wallet_address: str, from_network: str, to_network: str, 
                     amount: float, tx_hash: str, gas_cost: float, status: str, quote_data: Dict = None):
        """Сохранение результата в CSV файл"""
        os.makedirs(os.path.dirname(self.result_path), exist_ok=True)
        
        with open(self.result_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Рассчитываем реальную полученную сумму и комиссию из котировки
            if quote_data and 'details' in quote_data and 'currencyOut' in quote_data['details']:
                # Используем реальные данные из котировки
                amount_out_wei = int(quote_data['details']['currencyOut']['amount'])
                amount_out_eth = Web3.from_wei(amount_out_wei, 'ether')
                bridge_fee = amount - float(amount_out_eth)
                
                log_info(f"💰 Реальные данные: отправлено {amount:.8f} ETH, получено {amount_out_eth:.8f} ETH")
            else:
                # Fallback к примерной комиссии если нет данных котировки
                estimated_received = amount * 0.995  # Примерно 0.5% комиссия
                bridge_fee = amount - estimated_received
                amount_out_eth = estimated_received
                
                log_warning("⚠️ Используем примерную комиссию, так как нет данных котировки")
            
            writer.writerow([
                wallet_address, 
                from_network.capitalize(), 
                to_network.capitalize(), 
                f"{amount:.8f}",
                tx_hash or 'N/A', 
                f"{gas_cost:.8f}" if gas_cost > 0 else 'N/A',
                status.upper(), 
                time.strftime('%Y-%m-%d %H:%M:%S'),
                f"{amount_out_eth:.8f}",
                f"{bridge_fee:.8f}"
            ])
            
            log_info(f"💾 Результат сохранен в CSV: {wallet_address[:10]}...{wallet_address[-6:]}")
    
    def _check_quote_fees(self, quote_data: Dict, amount_eth: float, from_chain_id: int, to_chain_id: int, amount_wei: int, wallet_address: str) -> Dict:
        """Проверка комиссий в котировке перед выполнением с ожиданием снижения комиссии"""
        max_fee_usd = 0.20  # Лимит комиссии в USD
        
        while True:
            if not quote_data or 'details' not in quote_data:
                log_warning("⚠️ Нет детальной информации о комиссиях в котировке")
                return quote_data  # Возвращаем текущую котировку если нет данных
            
            details = quote_data['details']
            
            # Получаем фактическую выходную сумму
            if 'currencyOut' in details:
                amount_out_wei = int(details['currencyOut']['amount'])
                amount_out_eth = float(Web3.from_wei(amount_out_wei, 'ether'))
                
                actual_fee = amount_eth - amount_out_eth
                actual_fee_percentage = (actual_fee / amount_eth) * 100
                
                # Конвертируем в USD для проверки лимита
                eth_price = 4300  # Примерная цена ETH
                fee_usd = actual_fee * eth_price
                
                log_info(f"💰 Анализ комиссий котировки:")
                log_info(f"   📤 Отправка: {amount_eth:.8f} ETH")
                log_info(f"   📥 Получение: {amount_out_eth:.8f} ETH")
                log_info(f"   💸 Комиссия: {actual_fee:.8f} ETH ({actual_fee_percentage:.2f}%)")
                log_info(f"   💵 В USD: ${fee_usd:.4f}")
                
                # Проверяем лимит комиссии
                if fee_usd > max_fee_usd:
                    log_warning(f"⚠️ Комиссия слишком высокая: ${fee_usd:.4f} > ${max_fee_usd}")
                    log_warning(f"   💡 Ожидание снижения комиссии... Повторная проверка через {GAS['WHITE_TIMEOUT']} сек")
                    
                    # Ждем перед следующей проверкой
                    time.sleep(GAS['WHITE_TIMEOUT'])
                    
                    # Получаем новую котировку
                    log_info("🔄 Получение новой котировки...")
                    new_quote = self._get_quote(from_chain_id, to_chain_id, amount_wei, wallet_address)
                    if new_quote:
                        quote_data = new_quote
                        continue  # Проверяем новую котировку
                    else:
                        log_warning("⚠️ Не удалось получить новую котировку, используем текущую")
                        return quote_data
                else:
                    log_success(f"✅ Комиссия в пределах лимита: ${fee_usd:.4f} ≤ ${max_fee_usd}")
                    return quote_data
            else:
                log_warning("⚠️ Нет информации о выходной сумме в котировке")
                return quote_data

    def _wait_for_balance_increase(self, wallet_address: str, to_chain_id: int, expected_amount: float) -> bool:
        """Ожидание увеличения баланса в целевой сети"""
        initial_balance = self._get_native_balance(to_chain_id, wallet_address)
        start_time = time.time()
        
        log_balance(f"⏳ Ожидание поступления {expected_amount:.6f} {NETWORK_SETTINGS[to_chain_id]['native_symbol']} в {NETWORK_SETTINGS[to_chain_id]['name']}")
        
        while time.time() - start_time < BALANCE_CHECK_TIMEOUT:
            time.sleep(BALANCE_CHECK_INTERVAL)
            current_balance = self._get_native_balance(to_chain_id, wallet_address)
            
            if current_balance > initial_balance + (expected_amount * 0.8):  # Учитываем возможные комиссии
                log_success(f"💰 Баланс увеличился! Получено ~{current_balance - initial_balance:.6f} {NETWORK_SETTINGS[to_chain_id]['native_symbol']}")
                return True
        
        log_warning("⏰ Время ожидания истекло, баланс не увеличился")
        return False
    
    def _process_wallet(self, private_key: str, wallet_index: int) -> bool:
        """Обработка одного кошелька"""
        try:
            # Получение адреса кошелька
            account = Web3().eth.account.from_key(private_key)
            wallet_address = account.address
            
            # Настройка текущего контекста
            self.current_private_key = private_key
            self.current_wallet_address = wallet_address
            self.current_proxy = self._get_proxy_for_wallet(wallet_index)
            
            log_progress(f"🔄 Кошелек {wallet_index + 1}: {wallet_address}")
            
            # Проверка балансов
            balances = self._check_balances(wallet_address)
            if not balances:
                log_warning("⚠️ Нет балансов для бриджа")
                return False
            
            # Определение направления бриджа
            if len(NETWORKS_TO_RELAY) != 2:
                log_error("❌ Должно быть указано ровно 2 сети в NETWORKS_TO_RELAY")
                return False
            
            from_network = NETWORKS_TO_RELAY[0]
            to_network = NETWORKS_TO_RELAY[1]
            
            if from_network not in balances:
                log_warning(f"⚠️ Нет баланса в сети {from_network}")
                return False
            
            from_chain_id = NETWORK_MAPPING[from_network]
            to_chain_id = NETWORK_MAPPING[to_network]
            
            # Генерация случайной суммы
            min_amount, max_amount = SUM_TO_RELAY
            amount = random.uniform(min_amount, max_amount)
            
            # Проверка достаточности баланса
            available_balance = balances[from_network]['balance']
            if amount > available_balance:
                log_warning(f"⚠️ Недостаточно средств. Доступно: {available_balance:.6f}, требуется: {amount:.6f}")
                return False
            
            # Сохранение записи в БД
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO relay_progress (wallet_address, private_key_hash, from_network, to_network, amount, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            ''', (wallet_address, hash(private_key), from_network, to_network, amount))
            conn.commit()
            conn.close()
            
            # Получение котировки
            amount_wei = Web3.to_wei(amount, 'ether')
            quote = self._get_quote(from_chain_id, to_chain_id, amount_wei, wallet_address)
            
            if not quote:
                log_error("❌ Не удалось получить котировку")
                return False
            
            # Проверка комиссий в котировке с ожиданием снижения
            quote = self._check_quote_fees(quote, amount, from_chain_id, to_chain_id, amount_wei, wallet_address)
            
            # Выполнение бриджа
            log_transaction(f"🚀 Отправка {amount:.6f} {NETWORK_SETTINGS[from_chain_id]['native_symbol']} из {from_network} в {to_network}")
            
            bridge_success = self._execute_bridge(quote, wallet_address, private_key)
            if not bridge_success:
                log_error("❌ Ошибка выполнения бриджа")
                return False
            
            # Ожидание поступления средств
            balance_received = self._wait_for_balance_increase(wallet_address, to_chain_id, amount)
            
            status = 'completed' if balance_received else 'completed_no_confirmation'
            
            # Сохранение в CSV
            last_tx_hash = None
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT tx_hash, gas_cost FROM relay_progress WHERE wallet_address = ? ORDER BY id DESC LIMIT 1', (wallet_address,))
            result = cursor.fetchone()
            if result:
                last_tx_hash, gas_cost = result
            conn.close()
            
            self._save_to_csv(wallet_address, from_network, to_network, amount, last_tx_hash, gas_cost or 0, status, quote)
            
            log_success(f"✅ Кошелек {wallet_index + 1} обработан успешно")
            return True
            
        except Exception as e:
            log_error(f"❌ Ошибка обработки кошелька {wallet_index + 1}: {e}")
            return False
    
    def _check_resume_option(self) -> bool:
        """Проверка возможности продолжения работы"""
        if not os.path.exists(self.db_path):
            return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM relay_progress WHERE status = "pending"')
        pending_count = cursor.fetchone()[0]
        conn.close()
        
        if pending_count > 0:
            choice = select(
                "Найдена незавершенная работа. Что делать?",
                choices=[
                    Choice("Продолжить с того места", "resume"),
                    Choice("Начать заново", "restart")
                ]
            ).ask()
            
            if choice == "restart":
                os.remove(self.db_path)
                self._init_database()
                return False
            return True
        
        return False
    
    def _get_processed_wallets(self) -> set:
        """Получение списка уже обработанных кошельков"""
        processed = set()
        
        if os.path.exists(self.db_path):
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT private_key_hash FROM relay_progress WHERE status != "pending"')
            results = cursor.fetchall()
            processed = {result[0] for result in results}
            conn.close()
        
        return processed
    
    def _get_native_token_price_in_usdt(self, chain_id: int) -> float:
        """Получение курса нативного токена сети в USDT"""
        # Маппинг chain_id на CoinGecko ID
        coingecko_ids = {
            1: 'ethereum',      # Ethereum - ETH
            10: 'ethereum',     # Optimism - ETH
            137: 'matic-network',  # Polygon - MATIC
            8453: 'ethereum',   # Base - ETH
            42161: 'ethereum'   # Arbitrum - ETH
        }
        
        coingecko_id = coingecko_ids.get(chain_id, 'ethereum')
        network_name = NETWORK_SETTINGS[chain_id]['name']
        token_symbol = NETWORK_SETTINGS[chain_id]['native_symbol']
        
        # Попробуем несколько раз с разными прокси
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Используем случайный прокси для API запроса
                api_proxy = self._get_random_proxy_for_api()
                proxies = None
                if api_proxy:
                    proxies = {
                        'http': f'http://{api_proxy}',
                        'https': f'http://{api_proxy}'
                    }
                    if attempt == 0:  # Показываем только первую попытку
                        log_info(f"🌐 Используем прокси для API: {api_proxy[:20]}...")
                
                response = requests.get(
                    f'https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies=usd', 
                    proxies=proxies, 
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                price = data[coingecko_id]['usd']
                log_info(f"💱 Курс {token_symbol} ({network_name}): ${price:.2f}")
                return float(price)
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and attempt < max_attempts - 1:
                    log_warning(f"⚠️ Rate limit попытка {attempt + 1}, пробуем другой прокси...")
                    time.sleep(1)  # Небольшая пауза перед следующей попыткой
                    continue
                else:
                    raise e
            except Exception as e:
                if attempt < max_attempts - 1:
                    log_warning(f"⚠️ Ошибка API попытка {attempt + 1}: {e}")
                    time.sleep(1)
                    continue
                else:
                    raise e
        
        # Если все попытки провалились, используем fallback курсы
        log_warning(f"⚠️ Не удалось получить курс {token_symbol} после {max_attempts} попыток, используем fallback")
        fallback_prices = {
            1: 3000.0,    # ETH
            10: 3000.0,   # ETH на Optimism
            137: 0.5,     # MATIC
            8453: 3000.0, # ETH на Base
            42161: 3000.0 # ETH на Arbitrum
        }
        return fallback_prices.get(chain_id, 3000.0)
    
    def _check_gas_cost_limit(self, chain_id: int, gas_limit: int, gas_price: int) -> bool:
        """Проверка лимита стоимости газа в текущей сети"""
        # Получаем курс нативного токена текущей сети
        token_price = self._get_native_token_price_in_usdt(chain_id)
        token_symbol = NETWORK_SETTINGS[chain_id]['native_symbol']
        network_name = NETWORK_SETTINGS[chain_id]['name']
        
        # Вычисляем стоимость газа в нативном токене
        gas_cost_wei = gas_limit * gas_price
        gas_cost_native = Web3.from_wei(gas_cost_wei, 'ether')
        
        # Конвертируем в USDT
        gas_cost_usdt = float(gas_cost_native) * token_price
        
        limit_usdt = GAS['LIMIT_GAS_COST']
        
        log_info(f"⛽ Стоимость газа в {network_name}: {gas_cost_native:.6f} {token_symbol} (${gas_cost_usdt:.4f})")
        log_info(f"📊 Лимит: ${limit_usdt}")
        
        if gas_cost_usdt > limit_usdt:
            log_warning(f"⚠️ Газ слишком дорогой: ${gas_cost_usdt:.4f} > ${limit_usdt}")
            return False
        
        log_success(f"✅ Газ в пределах лимита: ${gas_cost_usdt:.4f} ≤ ${limit_usdt}")
        return True
    
    def _wait_for_acceptable_gas_price(self, web3: Web3, gas_limit: int, chain_id: int) -> int:
        """Ожидание приемлемой цены газа"""
        while True:
            try:
                current_gas_price = web3.eth.gas_price
                
                if self._check_gas_cost_limit(chain_id, gas_limit, current_gas_price):
                    return current_gas_price
                
                log_warning(f"⏳ Ожидание снижения цены газа... Повторная проверка через {GAS['WHITE_TIMEOUT']} сек")
                time.sleep(GAS['WHITE_TIMEOUT'])
                
            except Exception as e:
                log_error(f"❌ Ошибка при проверке цены газа: {e}")
                # В случае ошибки используем умеренную цену
                return web3.to_wei('20', 'gwei')
    
    def run(self):
        """Основная функция запуска"""
        try:
            log_info("🌉 Запуск Relay Bridge")
            
            # Проверка возможности продолжения
            resume = self._check_resume_option()
            
            # Показ параметров и подтверждение
            log_info(f"📋 Параметры запуска:")
            log_info(f"   💰 Сумма: {SUM_TO_RELAY[0]} - {SUM_TO_RELAY[1]}")
            log_info(f"   🔄 Маршрут: {NETWORKS_TO_RELAY[0]} → {NETWORKS_TO_RELAY[1]}")
            log_info(f"   👛 Кошельков: {len(self.private_keys)}")
            log_info(f"   🌐 Прокси: {len(self.proxies)}")
            
            if not resume:
                choice = select(
                    "Запустить с этими параметрами?",
                    choices=[
                        Choice("Да", True),
                        Choice("Нет", False)
                    ]
                ).ask()
                
                if not choice:
                    log_info("👋 Работа отменена пользователем")
                    return
            
            # Получение списка обработанных кошельков при продолжении
            processed_wallets = self._get_processed_wallets() if resume else set()
            
            # Обработка кошельков
            total_wallets = len(self.private_keys)
            successful = 0
            
            for i, private_key in enumerate(self.private_keys):
                key_hash = hash(private_key)
                
                if resume and key_hash in processed_wallets:
                    log_info(f"⏭️ Кошелек {i + 1} уже обработан, пропускаем")
                    successful += 1
                    continue
                
                success = self._process_wallet(private_key, i)
                if success:
                    successful += 1
                
                # Небольшая пауза между кошельками
                if i < total_wallets - 1:
                    time.sleep(random.uniform(2, 5))
            
            log_success(f"🎉 Работа завершена! Успешно обработано: {successful}/{total_wallets}")
            
        except KeyboardInterrupt:
            log_warning("👋 Работа прервана пользователем")
        except Exception as e:
            log_error(f"❌ Критическая ошибка: {e}")

def main():
    """Точка входа в программу"""
    bridge = RelayBridge()
    bridge.run()

if __name__ == "__main__":
    main()
