import requests
from datetime import datetime
import random
import csv
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

from modules.simple_logger import logger
from config.modules.cfg_etherscan import ETHER_SCAN_API_KEY_v2
from config.modules.cfg_base import RETRY_COUNT, NUM_THREADS
from modules.eth.rpc_return_module import get_network_rpc_selection

def get_network_info():
    """Возвращает информацию о сети для проверки транзакций"""
    network_chain_map = {
        'Ethereum Mainnet': {'name': 'Ethereum', 'chain_id': 1},
        'Base': {'name': 'Base', 'chain_id': 8453},
        'Arbitrum One': {'name': 'Arbitrum', 'chain_id': 42161},
        'Optimism': {'name': 'Optimism', 'chain_id': 10},
        'Polygon': {'name': 'Polygon', 'chain_id': 137},
        'Binance Smart Chain': {'name': 'BSC', 'chain_id': 56},
        'Avalanche': {'name': 'Avalanche', 'chain_id': 43114},
        'Fantom': {'name': 'Fantom', 'chain_id': 250},
        'Sepolia': {'name': 'Sepolia', 'chain_id': 11155111},
    }
    
    selected_rpc_urls, network_type, clean_network = get_network_rpc_selection()
    
    if clean_network is None:
        logger.error("Сеть не выбрана")
        return None
    
    network_info = network_chain_map.get(clean_network)
    if network_info:
        return network_info
    
    for key, value in network_chain_map.items():
        if clean_network.lower() in key.lower() or key.lower() in clean_network.lower():
            return value
    
    logger.warning(f"Сеть '{clean_network}' не найдена в карте, используем Ethereum по умолчанию")
    return network_chain_map['Ethereum Mainnet']

class LastTxChecker:
    def __init__(self):
        self.network_info = get_network_info()
        if not self.network_info:
            raise ValueError("Не удалось получить информацию о сети")
            
        self.proxies = self.load_proxies()
        self.wallets = self.load_wallets()
        self.results = {}  
        self.lock = threading.Lock()
        self.wallet_counter = 0
        
    def load_proxies(self):
        """Загрузка прокси из data.csv"""
        from modules.data_manager import get_proxies
        raw_proxies = get_proxies()
        proxies = []
        for proxy_str in raw_proxies:
            if '@' in proxy_str:
                auth, address = proxy_str.split('@')
                proxies.append(f"http://{auth}@{address}")
            else:
                proxies.append(f"http://{proxy_str}")
        logger.info(f"Загружено {len(proxies)} прокси")
        return proxies

    def load_wallets(self):
        """Загрузка адресов кошельков из data.csv"""
        from modules.data_manager import get_wallet_addresses
        wallets = get_wallet_addresses()
        if not wallets:
            from modules.data_manager import get_private_keys
            from eth_account import Account
            for pk in get_private_keys():
                try:
                    pk_hex = pk if pk.startswith('0x') else f'0x{pk}'
                    wallets.append(Account.from_key(pk_hex).address)
                except Exception:
                    pass
        logger.info(f"Загружено {len(wallets)} кошельков")
        return wallets
    
    def get_last_incoming_tx(self, address, network_name, chain_id, wallet_num):
        """Получение последней входящей транзакции с повторными попытками"""
        for attempt in range(RETRY_COUNT):
            if not self.proxies:
                return None, None
                
            proxy = random.choice(self.proxies)
            session = requests.Session()
            session.proxies = {"http": proxy, "https": proxy}
            
            url = "https://api.etherscan.io/v2/api"
            params = {
                "chainid": chain_id,
                "module": "account", 
                "action": "txlist",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "sort": "desc",
                "apikey": ETHER_SCAN_API_KEY_v2
            }
            
            try:
                r = session.get(url, params=params, timeout=15)
                data = r.json()
                session.close()
                
                if data.get("status") == "1" and data.get("result"):
                    for tx in data["result"]:
                        if tx.get("to", "").lower() == address.lower():
                            ts = int(tx["timeStamp"])
                            date_str = datetime.fromtimestamp(ts).strftime("%d:%m:%Y(%H:%M)")
                            return date_str, tx["hash"]
                
                return None, None
                
            except Exception as e:
                session.close()
                
                if proxy in self.proxies:
                    self.proxies.remove(proxy)
                
                if attempt < RETRY_COUNT - 1:
                    time.sleep(random.uniform(1, 3))
                    
        return None, None
    
    def process_wallet(self, wallet_data):
        """Обработка одного кошелька"""
        wallet, wallet_num = wallet_data
        try:
            network_name = self.network_info.get('name', 'Unknown')
            chain_id = self.network_info.get('chain_id', 1)
            
            date, tx_hash = self.get_last_incoming_tx(wallet, network_name, chain_id, wallet_num)
            
            if date:
                logger.success(f"[{wallet_num}/{len(self.wallets)}] {wallet}: Последняя транзакция {date}")
            else:
                logger.warning(f"[{wallet_num}/{len(self.wallets)}] {wallet}: Транзакций не найдено")
            
            result = {
                'wallet': wallet,
                'network': network_name,
                'chain_id': chain_id,
                'last_tx_date': date or 'Не найдено',
                'tx_hash': tx_hash or 'Не найдено',
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            with self.lock:
                self.results[wallet_num] = result 
                
        except Exception as e:
            logger.error(f"[{wallet_num}/{len(self.wallets)}] {wallet}: Ошибка обработки - {e}")

    def save_results(self):
        """Сохранение результатов в CSV"""
        if not self.results:
            logger.warning("Нет результатов для сохранения")
            return
            
        Path("result").mkdir(exist_ok=True)
        
        filename = f"result/last_transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['wallet', 'network', 'chain_id', 'last_tx_date', 'tx_hash', 'timestamp']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for i in range(1, len(self.wallets) + 1):
                if i in self.results:
                    writer.writerow(self.results[i])
            
        logger.success(f"Результаты сохранены в {filename}")
    
    def run(self):
        """Основная функция запуска"""
        if not self.wallets:
            logger.error("Нет кошельков для обработки")
            return
            
        logger.info(f"Запуск проверки для {len(self.wallets)} кошельков в {NUM_THREADS} потоков")
        
        wallet_data = [(wallet, i+1) for i, wallet in enumerate(self.wallets)]
        
        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            executor.map(self.process_wallet, wallet_data)
            
        self.save_results()
        logger.info("Обработка завершена")

def check_last_transactions():
    """Функция для одного вызова проверки последних транзакций"""
    try:
        checker = LastTxChecker()
        checker.run()
    except ValueError as e:
        logger.error(f"Ошибка инициализации: {e}")
