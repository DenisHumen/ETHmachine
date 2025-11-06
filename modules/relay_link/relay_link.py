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
from config.config import SUM_TO_RELAY, GAS, MAIN_PROXY, SLEEP_BETWEEN_ACTIONS
from config.networks import *
from config.networks import get_explorer_url
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

def log_wallet_summary(wallet_address: str, sent_amount: float, received_amount: float, 
                       bridge_fee: float, from_network: str, to_network: str, 
                       token_symbol: str, price_usd: float):
    """Красивый цветной вывод итогов кошелька"""
    from colorama import Fore, Style, init
    init()
    
    sent_usd = sent_amount * price_usd
    received_usd = received_amount * price_usd
    fee_usd = bridge_fee * price_usd
    fee_percent = (bridge_fee / sent_amount * 100) if sent_amount > 0 else 0
    
    print(f"\n{Fore.CYAN}{'='*20} {wallet_address} {'='*20}{Style.RESET_ALL}")
    print(f"     {Fore.GREEN}• отправлено: {Fore.YELLOW}{sent_amount:.6f} {token_symbol} {Fore.BLUE}({from_network}) {Fore.GREEN}- ${sent_usd:.2f}{Style.RESET_ALL}")
    print(f"     {Fore.GREEN}• получено: {Fore.YELLOW}{received_amount:.6f} {token_symbol} {Fore.BLUE}({to_network}) {Fore.GREEN}- ${received_usd:.2f}{Style.RESET_ALL}")
    print(f"     {Fore.RED}• комиссия: {Fore.YELLOW}{bridge_fee:.6f} {token_symbol} {Fore.MAGENTA}({fee_percent:.2f}%) {Fore.RED}- ${fee_usd:.2f}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*84}{Style.RESET_ALL}\n")

class RelayBridge:
    def __init__(self):
        self.base_url = "https://api.relay.link"
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
            42161: arbitrum,  # Arbitrum
            1868: soneium  # Soneium
        }
        
        # Маппинг chain_id на названия сетей в explorer_url.py
        self.chain_id_to_explorer_network = {
            1: '🚀 Ethereum Mainnet',
            10: '🚀 Optimism',
            137: '🚀 Polygon',
            8453: '🚀 Base',
            42161: '🚀 Arbitrum One',
            1868: '🚀 Soneium'
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
                bridge_fee REAL DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                error_message TEXT,
                error_count INTEGER DEFAULT 0
            )
        ''')
        
        # Проверяем и добавляем поле error_count если его нет (миграция)
        cursor.execute("PRAGMA table_info(relay_progress)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'error_count' not in columns:
            cursor.execute('ALTER TABLE relay_progress ADD COLUMN error_count INTEGER DEFAULT 0')
        
        # Миграция: добавляем поле bridge_fee и удаляем старые поля газа
        if 'bridge_fee' not in columns:
            cursor.execute('ALTER TABLE relay_progress ADD COLUMN bridge_fee REAL DEFAULT 0')
        
        # Удаляем старые поля газа если они есть (в SQLite нельзя просто удалить колонки, но можем их игнорировать)
        
        conn.commit()
        conn.close()
    
    def _select_network_and_token(self, prompt_text: str, exclude_chain_id: int = None) -> Tuple[Optional[int], Optional[str]]:
        """
        Интерактивный выбор сети и токена
        
        Args:
            prompt_text: Текст приглашения для выбора
            exclude_chain_id: ID сети которую нужно исключить из списка
            
        Returns:
            Tuple[chain_id, token_symbol] или (None, None) при отмене
        """
        # Список доступных сетей
        available_networks = []
        for network_name, chain_id in NETWORK_MAPPING.items():
            if exclude_chain_id and chain_id == exclude_chain_id:
                continue
            network_display = f"🌐 {NETWORK_SETTINGS[chain_id]['name']}"
            available_networks.append(Choice(network_display, (network_name, chain_id)))
        
        available_networks.append(Choice('🔙 Назад', None))
        
        # Выбор сети
        log_info(f"\n{prompt_text}")
        selected = select(
            "Выберите сеть:",
            choices=available_networks,
            qmark='🛠️',
            pointer='👉'
        ).ask()
        
        if selected is None:
            return None, None
        
        network_name, chain_id = selected
        
        # Получаем доступные токены для выбранной сети
        available_tokens = TOKEN_ADDRESSES.get(chain_id, {})
        if not available_tokens:
            log_error(f"❌ Нет доступных токенов для сети {NETWORK_SETTINGS[chain_id]['name']}")
            return None, None
        
        # Формируем список токенов с нативным первым
        native_symbol = NETWORK_SETTINGS[chain_id]['native_symbol']
        token_choices = []
        
        # Нативный токен всегда первый
        if native_symbol in available_tokens:
            token_choices.append(Choice(f"💎 {native_symbol} (нативный)", native_symbol))
        
        # Остальные токены
        for token_symbol in available_tokens.keys():
            if token_symbol != native_symbol:
                token_choices.append(Choice(f"🪙 {token_symbol}", token_symbol))
        
        token_choices.append(Choice('🔙 Назад', None))
        
        # Выбор токена
        selected_token = select(
            f"Выберите токен в сети {NETWORK_SETTINGS[chain_id]['name']}:",
            choices=token_choices,
            qmark='💰',
            pointer='👉'
        ).ask()
        
        if selected_token is None:
            return None, None
        
        return chain_id, selected_token
    
    def _check_wallet_token_balance(self, wallet_address: str, chain_id: int, token_symbol: str) -> float:
        """
        Проверка баланса токена на кошельке
        
        Args:
            wallet_address: Адрес кошелька
            chain_id: ID сети
            token_symbol: Символ токена
            
        Returns:
            Баланс токена
        """
        native_symbol = NETWORK_SETTINGS[chain_id]['native_symbol']
        
        # Для нативного токена используем _get_native_balance
        if token_symbol == native_symbol:
            return self._get_native_balance(chain_id, wallet_address, show_log=False)
        
        # Для ERC20 токенов (если потребуется в будущем)
        # TODO: добавить поддержку ERC20 токенов
        log_warning(f"⚠️ Проверка баланса ERC20 токенов пока не реализована")
        return 0.0
    
    def _create_work_plan(self, from_chain_id: int, from_token: str, to_chain_id: int, to_token: str):
        """Создание полного плана работ в базе данных"""
        from_network = CHAIN_ID_TO_NAME[from_chain_id]
        to_network = CHAIN_ID_TO_NAME[to_chain_id]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Проверяем, есть ли уже записи в базе
        cursor.execute("SELECT COUNT(*) FROM relay_progress")
        existing_count = cursor.fetchone()[0]
        
        if existing_count == 0:
            for private_key in self.private_keys:
                # Получение адреса кошелька
                account = Web3().eth.account.from_key(private_key)
                wallet_address = account.address
                
                # Генерация случайной суммы для каждого кошелька
                min_amount, max_amount = SUM_TO_RELAY
                amount = random.uniform(min_amount, max_amount)
                
                # Добавление записи в БД (используем пустую строку для private_key_hash, т.к. теперь ищем по wallet_address)
                cursor.execute('''
                    INSERT INTO relay_progress (wallet_address, private_key_hash, from_network, to_network, amount, status)
                    VALUES (?, ?, ?, ?, ?, 'pending')
                ''', (wallet_address, '', from_network, to_network, amount))
            
            conn.commit()
            log_success(f"✅ План работ создан для {len(self.private_keys)} кошельков")
        elif existing_count > 0:
            log_info(f"📋 Найдено {existing_count} записей в базе данных")
        
        conn.close()
        return True
    
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
    
    def _load_private_keys(self) -> List[str]:
        """Загрузка приватных ключей из файла"""
        keys_path = os.path.join(project_root, 'data', 'private_keys.txt')
        if not os.path.exists(keys_path):
            log_error(f"❌ Файл с приватными ключами не найден: {keys_path}")
            return []
        
        with open(keys_path, 'r', encoding='utf-8') as f:
            keys = [line.strip() for line in f if line.strip()]
        
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
    
    def _get_web3_connection(self, chain_id: int) -> Optional[Web3]:
        """Получение Web3 подключения с ротацией RPC"""
        if chain_id not in self.rpc_pools:
            log_error(f"❌ Нет RPC для сети {chain_id}")
            return None
        
        cache_key = chain_id
        if cache_key in self.web3_connections:
            web3 = self.web3_connections[cache_key]
            if web3.is_connected():
                #log_info(f"🔗 Используем кешированное подключение к {NETWORK_SETTINGS[chain_id]['name']}")
                return web3
            else:
                log_warning(f"⚠️ Кешированное подключение к {NETWORK_SETTINGS[chain_id]['name']} не активно, переподключаемся...")
        
        # Перебираем RPC пока не найдем рабочий (тихо)
        rpc_list = self.rpc_pools[chain_id]
        
        for i, rpc_url in enumerate(rpc_list):
            try:
                web3 = Web3(Web3.HTTPProvider(rpc_url))
                if web3.is_connected():
                    self.web3_connections[cache_key] = web3
                    return web3
                else:
                    log_warning(f"⚠️ RPC не отвечает: {rpc_url[:50]}...")
            except Exception as e:
                log_warning(f"⚠️ RPC ошибка: {rpc_url[:50]}... - {e}")
                continue
        
        log_error(f"❌ Все RPC для сети {chain_id} ({NETWORK_SETTINGS[chain_id]['name']}) недоступны")
        return None
    
    def _get_native_balance(self, chain_id: int, wallet_address: str, show_log: bool = False) -> float:
        """Получение баланса нативного токена со всех RPC для получения актуального значения"""
        rpc_list = self.rpc_pools.get(chain_id, [])
        
        # Проверяем ВСЕ RPC для получения самого актуального баланса
        balances = []
        
        for rpc_url in rpc_list:
            try:
                # Создаем новое подключение для каждого запроса
                web3 = Web3(Web3.HTTPProvider(rpc_url))
                if not web3.is_connected():
                    continue
                
                balance_wei = web3.eth.get_balance(wallet_address)
                balance = float(web3.from_wei(balance_wei, 'ether'))
                
                balances.append(balance)
                
            except Exception as e:
                continue
        
        if balances:
            # Возвращаем максимальный баланс (наиболее актуальный)
            max_balance = max(balances)
            # Выводим сообщение только при show_log=True (первоначальная проверка)
            if show_log:
                network_name = NETWORK_SETTINGS[chain_id]['name']
                log_info(f"📊 Текущий баланс {network_name}: {max_balance:.8f} ETH")
            return max_balance
        
        # Если все RPC не работают, возвращаем 0
        if show_log:
            log_error(f"❌ Все RPC для {NETWORK_SETTINGS[chain_id]['name']} недоступны")
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
    
    def _check_balances(self, wallet_address: str, from_chain_id: int, to_chain_id: int) -> Dict[str, Dict]:
        """Проверка балансов в указанных сетях"""
        balances = {}
        
        for chain_id in [from_chain_id, to_chain_id]:
            network_name = CHAIN_ID_TO_NAME[chain_id]
            balance = self._get_native_balance(chain_id, wallet_address, show_log=True)
            
            if balance > 0:
                balances[network_name] = {
                    'chain_id': chain_id,
                    'balance': balance,
                    'symbol': NETWORK_SETTINGS[chain_id]['native_symbol']
                }
        
        return balances
    
    def _get_quote(self, from_chain_id: int, to_chain_id: int, amount_wei: int, wallet_address: str) -> Tuple[Optional[Dict], Optional[str]]:
        """Получение котировки для бриджа. Возвращает (quote_data, error_message)"""
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
            return response.json(), None
        except Exception as e:
            error_msg = f"Ошибка получения котировки: {e}"
            log_error(f"❌ {error_msg}")
            return None, error_msg
    
    def _check_balance_changes(self, wallet_address: str, from_chain_id: int, to_chain_id: int, sent_amount: float, initial_from_balance: float, initial_to_balance: float, max_wait_minutes: int = 15) -> bool:
        """
        Проверка изменения балансов для подтверждения успешности транзакции
        Основной критерий успеха - поступление средств в целевую сеть
        
        Args:
            wallet_address: Адрес кошелька
            from_chain_id: ID сети откуда отправили
            to_chain_id: ID сети куда должно прийти
            sent_amount: Отправленная сумма
            initial_from_balance: Начальный баланс в исходной сети  
            initial_to_balance: Начальный баланс в целевой сети
            max_wait_minutes: Максимальное время ожидания в минутах
        
        Returns:
            True если средства поступили в целевую сеть
        """
        max_attempts = (max_wait_minutes * 60) // SLEEP_BETWEEN_ACTIONS[1]  # Количество попыток
        log_info(f"⏱️ Максимальное время ожидания: {max_wait_minutes} минут ({max_attempts} проверок)")
        
        for attempt in range(max_attempts):
            try:
                log_info(f"🔍 Проверка {attempt + 1}/{max_attempts}: проверяем баланс в {NETWORK_SETTINGS[to_chain_id]['name']}...")
                
                # Получаем АКТУАЛЬНЫЙ баланс целевой сети через Web3 RPC (используем все доступные RPC)
                current_to_balance = self._get_native_balance(to_chain_id, wallet_address)
                
                # Рассчитываем изменение в целевой сети
                to_change = current_to_balance - initial_to_balance
                
                log_info(f"📊 Баланс: {initial_to_balance:.8f} → {current_to_balance:.8f} (изменение: {to_change:.8f} {NETWORK_SETTINGS[to_chain_id]['native_symbol']})")
                
                # Главный критерий успеха - если есть поступление в целевую сеть
                if to_change > 0.000001:  # Минимальное изменение для учета
                    log_success(f"✅ Транзакция успешна! Получено: {to_change:.6f} {NETWORK_SETTINGS[to_chain_id]['native_symbol']}")
                    return True
                
                # Показываем что ждем еще
                if attempt < max_attempts - 1:
                    log_info(f"⏳ Средства еще не поступили, ожидание {SLEEP_BETWEEN_ACTIONS[1]} сек...")
                    sleep_time = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
                    time.sleep(sleep_time)
                    
            except Exception as e:
                log_error(f"❌ Ошибка при проверке баланса (попытка {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    log_info(f"🔄 Повторная попытка через {SLEEP_BETWEEN_ACTIONS[1]} сек...")
                time.sleep(SLEEP_BETWEEN_ACTIONS[1])
                
        # Если время истекло и средства не поступили
        log_error(f"❌ Средства не поступили в {NETWORK_SETTINGS[to_chain_id]['name']} в течение {max_wait_minutes} минут")
        return False

    def _execute_bridge(self, quote_data: Dict, wallet_address: str, private_key: str, from_chain_id: int, to_chain_id: int, sent_amount: float) -> bool:
        """Выполнение бридж транзакции"""
        try:
            # Вычисляем комиссию из котировки для сохранения в результат
            quote_fee_eth = 0.0
            if quote_data and 'details' in quote_data and 'currencyOut' in quote_data['details']:
                amount_out_wei = int(quote_data['details']['currencyOut']['amount'])
                amount_out_eth = float(Web3.from_wei(amount_out_wei, 'ether'))
                quote_fee_eth = sent_amount - amount_out_eth
                #log_info(f"💰 Комиссия из котировки: {quote_fee_eth:.8f} ETH")
            
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
            
            # Получаем начальные балансы для проверки
            initial_from_balance = self._get_native_balance(from_chain_id, wallet_address)
            initial_to_balance = self._get_native_balance(to_chain_id, wallet_address)

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
            
            # Проверяем поддержку EIP-1559 (Type 2 transactions)
            try:
                latest_block = web3.eth.get_block('latest')
                supports_eip1559 = hasattr(latest_block, 'baseFeePerGas') and latest_block.baseFeePerGas is not None
            except:
                supports_eip1559 = False
            
            # Финальная транзакция
            if supports_eip1559:
                # EIP-1559 транзакция (Type 2)
                
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
            
            # Ждем небольшое время перед проверкой
            log_info(f"⏰ Ожидание 30 секунд перед проверкой статуса транзакции...")
            time.sleep(30)
            
            # Проверяем статус транзакции в исходной сети
            try:
                tx_receipt = web3.eth.get_transaction_receipt(tx_hash)
                if tx_receipt.status == 1:
                    log_success(f"✅ Транзакция подтверждена в {NETWORK_SETTINGS[chain_id]['name']}")
                else:
                    log_error(f"❌ Транзакция отклонена в {NETWORK_SETTINGS[chain_id]['name']}")
                    return False
            except Exception as e:
                log_warning(f"⚠️ Не удалось получить статус транзакции: {e}")
            
            # Проверяем успешность через изменение балансов
            log_info(f"🔍 Проверка поступления средств в {NETWORK_SETTINGS[to_chain_id]['name']}...")
            transaction_success = self._check_balance_changes(
                wallet_address, from_chain_id, to_chain_id, sent_amount, 
                initial_from_balance, initial_to_balance
            )
            
            # Если балансы изменились, транзакция успешна
            if transaction_success:
                log_success(f"✅ Транзакция подтверждена")
            
            # Сохранение результата
            if transaction_success:
                self._save_transaction_result(
                    wallet_address, tx_hash.hex(), quote_fee_eth, 'completed'
                )
                return True
            else:
                self._save_transaction_result(wallet_address, tx_hash.hex(), 0, 'failed')
                return False
                
        except Exception as e:
            log_error(f"❌ Ошибка выполнения транзакции: {e}")
            self._save_transaction_result(wallet_address, None, 0, 'error', str(e))
            return False
    
    def _save_transaction_result(self, wallet_address: str, tx_hash: str, bridge_fee: float, status: str, error_msg: str = None):
        """Сохранение результата транзакции в БД"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE relay_progress 
            SET tx_hash = ?, bridge_fee = ?, status = ?, completed_at = CURRENT_TIMESTAMP, error_message = ?
            WHERE wallet_address = ? AND status = 'pending'
        ''', (tx_hash, bridge_fee, status, error_msg, wallet_address))
        
        conn.commit()
        conn.close()
    
    def _save_to_csv(self, wallet_address: str, from_network: str, to_network: str, 
                     amount: float, tx_hash: str, bridge_fee: float, status: str, quote_data: Dict = None):
        """Сохранение результата в CSV файл"""
        os.makedirs(os.path.dirname(self.result_path), exist_ok=True)
        
        with open(self.result_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Рассчитываем реальную полученную сумму и комиссию из котировки
            if quote_data and 'details' in quote_data and 'currencyOut' in quote_data['details']:
                # Используем реальные данные из котировки
                amount_out_wei = int(quote_data['details']['currencyOut']['amount'])
                amount_out_eth = Web3.from_wei(amount_out_wei, 'ether')
                calculated_bridge_fee = amount - float(amount_out_eth)
            else:
                # Fallback к примерной комиссии если нет данных котировки
                estimated_received = amount * 0.995  # Примерно 0.5% комиссия
                calculated_bridge_fee = amount - estimated_received
                amount_out_eth = estimated_received
                
                log_warning("⚠️ Используем примерную комиссию, так как нет данных котировки")
            
            # Используем bridge_fee из базы данных, если он больше 0, иначе рассчитанный
            final_bridge_fee = bridge_fee if bridge_fee > 0 else calculated_bridge_fee
            
            writer.writerow([
                wallet_address, 
                from_network.capitalize(), 
                to_network.capitalize(), 
                f"{amount:.8f}",
                tx_hash or 'N/A', 
                f"{final_bridge_fee:.8f}" if final_bridge_fee > 0 else 'N/A',
                status.upper(), 
                time.strftime('%Y-%m-%d %H:%M:%S'),
                f"{amount_out_eth:.8f}",
                f"{final_bridge_fee:.8f}"
            ])
    
    def _check_quote_fees(self, quote_data: Dict, amount_eth: float, from_chain_id: int, to_chain_id: int, amount_wei: int, wallet_address: str) -> Dict:
        """Проверка комиссий в котировке перед выполнением с ожиданием снижения комиссии"""
        # Берем лимит комиссии из конфигурации
        max_fee_usd = GAS.get('LIMIT_GAS_COST', 0.1)  # Лимит комиссии в USD из config.py
        
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
                
                # Тихо проверяем комиссии без лишних логов
                
                # Проверяем лимит комиссии
                if fee_usd > max_fee_usd:
                    log_warning(f"⚠️ Комиссия слишком высокая: ${fee_usd:.4f} > ${max_fee_usd}")
                    log_warning(f"   💡 Ожидание снижения комиссии... Повторная проверка через {GAS['WHITE_TIMEOUT']} сек")
                    
                    # Ждем перед следующей проверкой
                    time.sleep(GAS['WHITE_TIMEOUT'])
                    
                    # Получаем новую котировку
                    log_info("🔄 Получение новой котировки...")
                    new_quote, error_msg = self._get_quote(from_chain_id, to_chain_id, amount_wei, wallet_address)
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

    def _process_wallet(self, private_key: str, wallet_index: int) -> bool:
        """Обработка одного кошелька"""
        try:
            # Получение адреса кошелька сначала для логирования
            account = Web3().eth.account.from_key(private_key)
            wallet_address = account.address
            
            # Получение записи кошелька из базы данных
            wallet_record = self._get_wallet_record(private_key)
            if not wallet_record:
                log_error(f"❌ Запись кошелька {wallet_address} не найдена в базе данных")
                return False
            
            # Проверка статуса - если уже выполнен, пропускаем
            if wallet_record['status'] == 'completed' or wallet_record['status'] == 'completed_no_confirmation':
                return True

            log_progress(f"🔄 Кошелек {wallet_index + 1}: {wallet_address}")
            
            # Получаем данные из записи базы
            from_network = wallet_record['from_network']
            to_network = wallet_record['to_network']
            amount = wallet_record['amount']
            
            # Получаем chain_id для сетей
            from_chain_id = NETWORK_MAPPING[from_network]
            to_chain_id = NETWORK_MAPPING[to_network]
            
            # Проверка балансов
            balances = self._check_balances(wallet_address, from_chain_id, to_chain_id)
            if not balances:
                log_warning(f"⚠️ Нет балансов для бриджа у кошелька {wallet_address}")
                return False
            
            if from_network not in balances:
                log_warning(f"⚠️ Нет баланса в сети {from_network} у кошелька {wallet_address}")
                return False
            
            # Проверка достаточности баланса
            available_balance = balances[from_network]['balance']
            if amount > available_balance:
                # Попробуем сделать мост на максимально доступную сумму
                if available_balance > 0.0001:  # Минимальная сумма для моста (0.0001 ETH)
                    amount = available_balance * 0.95  # Оставляем 5% для газа
                else:
                    log_error(f"❌ {wallet_address}: Баланс слишком мал: {available_balance:.6f} ETH")
                    return False
            
            # Получение котировки
            amount_wei = Web3.to_wei(amount, 'ether')
            quote, error_msg = self._get_quote(from_chain_id, to_chain_id, amount_wei, wallet_address)
            
            if not quote:
                # Записываем ошибку в базу и пропускаем кошелек
                self._update_wallet_error(wallet_record['id'], error_msg or "Неизвестная ошибка котировки")
                log_error(f"❌ Не удалось получить котировку для кошелька {wallet_address}, пропускаем")
                return False
            
            # Проверка комиссий в котировке с ожиданием снижения
            quote = self._check_quote_fees(quote, amount, from_chain_id, to_chain_id, amount_wei, wallet_address)
            
            # Выполнение бриджа
            bridge_success = self._execute_bridge(quote, wallet_address, private_key, from_chain_id, to_chain_id, amount)
            if not bridge_success:
                log_error(f"❌ Ошибка выполнения бриджа для кошелька {wallet_address}")
                return False
            
            # Если bridge_success = True, значит средства уже поступили (проверено в _execute_bridge)
            status = 'completed'
            
            # Сохранение в CSV
            last_tx_hash = None
            bridge_fee = 0
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT tx_hash, bridge_fee FROM relay_progress WHERE wallet_address = ? ORDER BY id DESC LIMIT 1', (wallet_address,))
            result = cursor.fetchone()
            if result:
                last_tx_hash, bridge_fee = result
            conn.close()
            
            self._save_to_csv(wallet_address, from_network, to_network, amount, last_tx_hash, bridge_fee or 0, status, quote)

            # Красивый вывод итогов кошелька
            try:
                # Получаем курс токена
                token_symbol = NETWORK_SETTINGS[from_chain_id]['native_symbol']
                price_usd = self._get_native_token_price_in_usdt(from_chain_id)
                
                # Рассчитываем полученную сумму (отправленная минус комиссия)
                received_amount = amount - (bridge_fee or 0)
                
                log_wallet_summary(
                    wallet_address, 
                    amount, 
                    received_amount, 
                    bridge_fee or 0, 
                    from_network, 
                    to_network, 
                    token_symbol, 
                    price_usd
                )
            except Exception as e:
                log_error(f"❌ Ошибка получения курса для итогов: {e}")
                print(f"\n{'='*20} {wallet_address} {'='*20}")
                print(f"     ✅ Обработан успешно: {amount:.6f} {NETWORK_SETTINGS[from_chain_id]['native_symbol']}")
                print(f"     Из {from_network} в {to_network}\n")
            
            return True
            
        except Exception as e:
            # Пытаемся получить адрес кошелька для логирования если возможно
            try:
                account = Web3().eth.account.from_key(private_key)
                wallet_address = account.address
                log_error(f"❌ Ошибка обработки кошелька {wallet_address}: {e}")
            except:
                log_error(f"❌ Ошибка обработки кошелька {wallet_index + 1}: {e}")
            return False
    
    def _check_resume_option(self) -> bool:
        """Проверка возможности продолжения работы"""
        if not os.path.exists(self.db_path):
            return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM relay_progress')
        total_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM relay_progress WHERE status = "pending"')
        pending_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM relay_progress WHERE status IN ("completed", "completed_no_confirmation")')
        completed_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM relay_progress WHERE error_count > 0')
        error_count = cursor.fetchone()[0]
        conn.close()
        
        if total_count > 0:
            log_info(f"📊 Статистика базы данных:")
            log_info(f"   📋 Всего записей: {total_count}")
            log_info(f"   ⏳ Ожидающих: {pending_count}")
            log_info(f"   ✅ Завершенных: {completed_count}")
            if error_count > 0:
                log_info(f"   ❌ С ошибками: {error_count}")
            
            if pending_count > 0:
                choice = select(
                    "Найдена существующая база данных с незавершенной работой. Что делать?",
                    choices=[
                        Choice("Продолжить работу с того места где остановились", "resume"),
                        Choice("Очистить базу и начать заново", "restart")
                    ]
                ).ask()
            else:
                choice = select(
                    "Найдена существующая база данных (все задания выполнены). Что делать?",
                    choices=[
                        Choice("Использовать существующую базу (пропустить выполненные)", "resume"),
                        Choice("Очистить базу и создать новый план работ", "restart")
                    ]
                ).ask()
            
            if choice == "restart":
                log_info("🗑️ Очистка базы данных...")
                os.remove(self.db_path)
                self._init_database()
                return False
            
            log_info("📂 Использование существующей базы данных")
            return True
        
        return False
    
    def _get_wallet_record(self, private_key: str) -> Optional[Dict]:
        """Получить запись кошелька из базы данных"""
        # Получаем адрес кошелька из приватного ключа
        try:
            account = Web3().eth.account.from_key(private_key)
            wallet_address = account.address
        except Exception as e:
            log_error(f"❌ Ошибка получения адреса из приватного ключа: {e}")
            return None
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, wallet_address, from_network, to_network, amount, status, error_count, error_message
            FROM relay_progress 
            WHERE wallet_address = ?
        ''', (wallet_address,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'id': result[0],
                'wallet_address': result[1],
                'from_network': result[2],
                'to_network': result[3],
                'amount': result[4],
                'status': result[5],
                'error_count': result[6],
                'error_message': result[7]
            }
        return None
    
    def _update_wallet_error(self, wallet_id: int, error_message: str):
        """Обновить счетчик ошибок для кошелька"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE relay_progress 
            SET error_count = error_count + 1, error_message = ?
            WHERE id = ?
        ''', (error_message, wallet_id))
        
        conn.commit()
        conn.close()
    
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
                
                response = requests.get(
                    f'https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies=usd', 
                    proxies=proxies, 
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                price = data[coingecko_id]['usd']
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
            log_info("🌉 Relay Bridge - запуск обработки кошельков")
            
            # Проверка возможности продолжения
            resume = self._check_resume_option()
            
            # Если не resume mode, то выбираем сети и токены
            if not resume:
                log_info("\n" + "="*60)
                log_info("🔧 НАСТРОЙКА ПАРАМЕТРОВ МОСТА")
                log_info("="*60)
                
                # Шаг 1: Выбор исходной сети и токена
                log_info("\n📤 ШАГ 1: Выбор сети и токена для отправки")
                from_chain_id, from_token = self._select_network_and_token("Откуда отправить?")
                if from_chain_id is None:
                    log_info("👋 Работа отменена пользователем")
                    return
                
                log_success(f"✅ Выбрано: {NETWORK_SETTINGS[from_chain_id]['name']} → {from_token}")
                
                # Шаг 2: Выбор целевой сети и токена
                log_info(f"\n📥 ШАГ 2: Выбор сети и токена для получения")
                to_chain_id, to_token = self._select_network_and_token("Куда отправить?", exclude_chain_id=from_chain_id)
                if to_chain_id is None:
                    log_info("👋 Работа отменена пользователем")
                    return
                
                log_success(f"✅ Выбрано: {NETWORK_SETTINGS[to_chain_id]['name']} → {to_token}")
                
                # Показываем итоговую конфигурацию
                log_info("="*60)
                log_info("🔧 ИТОГОВАЯ КОНФИГУРАЦИЯ")
                log_info("="*60)
                log_info(f"🌐 Из сети: {NETWORK_SETTINGS[from_chain_id]['name']}")
                log_info(f"💎 Токен отправки: {from_token}")
                log_info(f"🌐 В сеть: {NETWORK_SETTINGS[to_chain_id]['name']}")
                log_info(f"💎 Токен получения: {to_token}")
                log_info(f"💰 Сумма: {SUM_TO_RELAY[0]}-{SUM_TO_RELAY[1]} {from_token}")
                log_info(f"👛 Кошельков: {len(self.private_keys)}")
                log_info("="*60 + "\n")
                
                # Подтверждение запуска
                choice = select(
                    "Запустить мост с этими параметрами?",
                    choices=[
                        Choice("✅ Да, запустить", True),
                        Choice("❌ Нет, отменить", False)
                    ],
                    qmark='🛠️',
                    pointer='👉'
                ).ask()
                
                if not choice:
                    log_info("👋 Работа отменена пользователем")
                    return
                
                # Создание плана работ с новыми параметрами
                if not self._create_work_plan(from_chain_id, from_token, to_chain_id, to_token):
                    return
            else:
                # Resume mode - параметры уже есть в базе
                log_info("📂 Продолжение работы с существующими параметрами")
            
            # Обработка кошельков
            total_wallets = len(self.private_keys)
            successful = 0
            
            for i, private_key in enumerate(self.private_keys):
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
