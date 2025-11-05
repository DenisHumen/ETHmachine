"""
Модуль для получения статистики Neura Protocol
Многопоточная обработка с сохранением прогресса в БД
"""

import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', category=UserWarning)

import json
import csv
import uuid
import sys
import time
import random
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from questionary import Choice, select

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import NUM_THREADS, RETRY_COUNT, astrum_CAPTCHA_API_KEY

import requests
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from modules.statistics.astrum_captcha_solver import AstrumSolver

csv_lock = Lock()
db_lock = Lock()

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=False)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    class Fore:
        GREEN = RED = YELLOW = CYAN = RESET = ""
    class Style:
        RESET_ALL = ""

logger.remove()
logger.add(
    sys.stdout,
    format="{time:HH:mm:ss} | {level: <8} | {message}",
    colorize=False,  
    level="INFO"
)

def log_success(message: str):
    """Зелёный лог успеха"""
    logger.opt(colors=False).success(f"{Fore.GREEN}{message}{Style.RESET_ALL}")

def log_warning(message: str):
    """Жёлтый лог предупреждения"""
    logger.opt(colors=False).warning(f"{Fore.YELLOW}{message}{Style.RESET_ALL}")

def log_error(message: str):
    """Красный лог ошибки"""
    logger.opt(colors=False).error(f"{Fore.RED}{message}{Style.RESET_ALL}")

def log_info(message: str):
    """Обычный информационный лог"""
    logger.opt(colors=False).info(message)

RESULT_DIR = Path("result/statistics")
DB_DIR = Path("db")
DB_FILE = DB_DIR / "neura_stats_progress.db"

CURRENT_CSV_FILE = None


def ensure_directories():
    """Создание необходимых директорий"""
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    DB_DIR.mkdir(parents=True, exist_ok=True)


def create_new_csv_file() -> Path:
    """Создать новый CSV файл с датой и временем"""
    ensure_directories()
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = RESULT_DIR / f"neura_stats_{timestamp_str}.csv"
    return filename


def init_database():
    """Инициализация базы данных для хранения прогресса и JSON"""
    ensure_directories()
    
    with sqlite3.connect(str(DB_FILE)) as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processing_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT UNIQUE NOT NULL,
                private_key_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                last_attempt TIMESTAMP,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_stats_json (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                json_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_wallet_address ON processing_progress(wallet_address)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON processing_progress(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_wallet_stats ON wallet_stats_json(wallet_address)')
        
        conn.commit()


def get_unprocessed_wallets() -> List[Dict[str, Any]]:
    """Получить список необработанных кошельков из БД"""
    with sqlite3.connect(str(DB_FILE)) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wallet_address, attempts, error_message
            FROM processing_progress
            WHERE status IN ('pending', 'error')
            AND attempts < ?
            ORDER BY attempts ASC, last_attempt ASC
        ''', (RETRY_COUNT,))
        
        results = cursor.fetchall()
        return [{'address': r[0], 'attempts': r[1], 'error': r[2]} for r in results]


def mark_wallet_processing(wallet_address: str, private_key_hash: str):
    """Отметить кошелек как обрабатываемый"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO processing_progress 
                (wallet_address, private_key_hash, status, attempts, last_attempt, updated_at)
                VALUES (?, ?, 'processing', COALESCE((SELECT attempts FROM processing_progress WHERE wallet_address = ?), 0) + 1, ?, ?)
            ''', (wallet_address, private_key_hash, wallet_address, datetime.now(), datetime.now()))
            conn.commit()


def mark_wallet_success(wallet_address: str):
    """Отметить кошелек как успешно обработанный"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE processing_progress
                SET status = 'success', error_message = NULL, updated_at = ?
                WHERE wallet_address = ?
            ''', (datetime.now(), wallet_address))
            conn.commit()


def mark_wallet_error(wallet_address: str, error_message: str):
    """Отметить кошелек с ошибкой"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE processing_progress
                SET status = 'error', error_message = ?, updated_at = ?
                WHERE wallet_address = ?
            ''', (error_message, datetime.now(), wallet_address))
            conn.commit()


def save_json_to_db(wallet_address: str, json_data: dict):
    """Сохранить JSON данные в БД"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO wallet_stats_json (wallet_address, timestamp, json_data)
                VALUES (?, ?, ?)
            ''', (wallet_address, datetime.now(), json.dumps(json_data, ensure_ascii=False, default=str)))
            conn.commit()


def clear_database():
    """Очистить базу данных (начать заново)"""
    with sqlite3.connect(str(DB_FILE)) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM processing_progress')
        cursor.execute('DELETE FROM wallet_stats_json')
        conn.commit()
    log_success("✅ База данных очищена")


def initialize_all_wallets(wallets: List[str]):
    """Инициализировать все кошельки в БД как pending"""
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            for private_key in wallets:
                if not private_key.startswith('0x'):
                    private_key = '0x' + private_key
                
                account = Account.from_key(private_key)
                wallet_address = account.address
                private_key_hash = Web3.keccak(text=private_key).hex()
                
                cursor.execute('SELECT status FROM processing_progress WHERE wallet_address = ?', (wallet_address,))
                existing = cursor.fetchone()
                
                if not existing:
                    cursor.execute('''
                        INSERT INTO processing_progress 
                        (wallet_address, private_key_hash, status, attempts, created_at, updated_at)
                        VALUES (?, ?, 'pending', 0, ?, ?)
                    ''', (wallet_address, private_key_hash, datetime.now(), datetime.now()))
            
            conn.commit()


def has_pending_tasks() -> bool:
    """Проверить, есть ли незавершенные задачи"""
    with sqlite3.connect(str(DB_FILE)) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM processing_progress 
            WHERE status IN ('pending', 'processing', 'error')
        ''')
        count = cursor.fetchone()[0]
        return count > 0


def get_progress_stats() -> Dict[str, int]:
    """Получить статистику прогресса"""
    with sqlite3.connect(str(DB_FILE)) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                COUNT(CASE WHEN status = 'success' THEN 1 END) as success,
                COUNT(CASE WHEN status = 'error' THEN 1 END) as error,
                COUNT(CASE WHEN status = 'processing' THEN 1 END) as processing,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending
            FROM processing_progress
        ''')
        row = cursor.fetchone()
        return {
            'success': row[0] or 0,
            'error': row[1] or 0,
            'processing': row[2] or 0,
            'pending': row[3] or 0
        }


class NeuraProtocolClient:
    """Клиент для работы с Neura Protocol API"""
    
    def __init__(self, private_key: str, proxy_url: Optional[str] = None):
        """
        Инициализация клиента
        
        Args:
            private_key: Приватный ключ кошелька
            proxy_url: URL прокси (опционально)
        """
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
            
        self.private_key = private_key
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        
        self.proxies = None
        if proxy_url:
            self.proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
        
        self.session = requests.Session()
        if self.proxies:
            self.session.proxies.update(self.proxies)
        
        self.jwt_token = None
        
        self.base_url = "https://neuraverse-testnet.infra.neuraprotocol.io/api"
        self.privy_url = "https://privy.neuraverse.neuraprotocol.io/api/v1"
        self.rpc_url = "https://testnet.rpc.neuraprotocol.io/"
        self.graphql_url = "https://http-testnet-graph-eth.infra.neuraprotocol.io/subgraphs/name/test-eth"
        
        self.auth_headers = {
            'accept': 'application/json',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/json',
            'origin': 'https://neuraverse.neuraprotocol.io',
            'priority': 'u=1, i',
            'privy-app-id': 'cmbpempz2011ll10l7iucga14',
            'privy-ca-id': str(uuid.uuid4()),
            'privy-client': 'react-auth:2.25.0',
            'referer': 'https://neuraverse.neuraprotocol.io/',
            'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        }
        
        self.api_headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'origin': 'https://neuraverse.neuraprotocol.io',
            'priority': 'u=1, i',
            'referer': 'https://neuraverse.neuraprotocol.io/',
            'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        }
        
        self.captcha_api_key = self._load_captcha_key()
        
        self.captcha_solver = None
        if self.captcha_api_key:
            try:
                self.captcha_solver = AstrumSolver(api_key=self.captcha_api_key, proxy=proxy_url)
            except Exception as e:
                log_warning(f"⚠️ Ошибка инициализации AstrumSolver: {e}")
        else:
            log_warning("⚠️ API ключ капчи не найден")
    
    def change_proxy(self, new_proxy: str):
        """Смена прокси"""
        if new_proxy:
            self.proxies = {
                'http': new_proxy,
                'https': new_proxy
            }
            self.session.proxies.update(self.proxies)
            
            if self.captcha_solver:
                self.captcha_solver.proxy_url = new_proxy
        else:
            self.proxies = None
            self.session.proxies.clear()
    
    def _load_captcha_key(self) -> Optional[str]:
        """Загрузка API ключа капчи из config"""
        if astrum_CAPTCHA_API_KEY and len(astrum_CAPTCHA_API_KEY) > 0:
            return astrum_CAPTCHA_API_KEY
        
        try:
            with open('data/captcha_api_key.txt', 'r') as f:
                lines = f.readlines()
                if len(lines) >= 1:
                    return lines[0].strip()
        except Exception:
            pass
        
        return None
    
    def _solve_turnstile(self) -> Optional[str]:
        """Решение Turnstile captcha через AstrumSolver"""
        if not self.captcha_solver:
            log_error("❌ Решатель капчи недоступен")
            return None
        
        try:
            token = self.captcha_solver.solve_turnstile(
                sitekey='0x4AAAAAAAM8ceq5KhP1uJBt',
                pageurl='https://neuraverse.neuraprotocol.io/',
                action='cmbpempz2011ll10l7iucga14',
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
            )
            
            if token:
                return token
            else:
                log_error("❌ Не удалось решить Turnstile")
                return None
                
        except Exception as e:
            log_error(f"❌ Ошибка решения капчи: {e}")
            return None
    
    def _get_nonce(self) -> Optional[str]:
        """Получение nonce для SIWE аутентификации с Turnstile captcha"""
        try:
            turnstile_token = self._solve_turnstile()
            if not turnstile_token:
                log_error("❌ Не удалось получить Turnstile токен")
                return None
            
            json_data = {
                'address': self.address,
                'token': turnstile_token
            }
            
            response = self.session.post(
                f'{self.privy_url}/siwe/init',
                json=json_data,
                headers=self.auth_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                nonce = data.get('nonce')
                if nonce:
                    return nonce
            else:
                if response.status_code == 429:
                    log_warning(f"⚠️  Rate limit при получении nonce, смена прокси...")
                else:
                    log_error(f"❌ Ошибка получения nonce: HTTP {response.status_code}")
                
        except Exception as e:
            log_error(f"❌ Ошибка при получении nonce: {e}")
        
        return None
    
    def authenticate(self, max_retries: int = 3) -> bool:
        """
        Авторизация через SIWE (Sign-In with Ethereum) с retry при ошибках
        
        Args:
            max_retries: Максимальное количество попыток
            
        Returns:
            True если авторизация успешна
        """
        try:
            nonce = self._get_nonce()
            if not nonce:
                return False

            iso_time = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

            message = (
                f"neuraverse.neuraprotocol.io wants you to sign in with your Ethereum account:\n"
                f"{self.address}\n\n"
                f"By signing, you are proving you own this wallet and logging in. This does not initiate a transaction or cost any fees.\n\n"
                f"URI: https://neuraverse.neuraprotocol.io\n"
                f"Version: 1\n"
                f"Chain ID: 267\n"
                f"Nonce: {nonce}\n"
                f"Issued At: {iso_time}\n"
                f"Resources:\n"
                f"- https://privy.io"
            )

            message_hash = encode_defunct(text=message)
            signed = self.account.sign_message(message_hash)
            signature = signed.signature.hex()
            if not signature.startswith('0x'):
                signature = '0x' + signature

            json_data = {
                'message': message,
                'signature': signature,
                'chainId': 'eip155:267',
                'walletClientType': 'metamask',
                'connectorType': 'injected',
                'mode': 'login-or-sign-up',
            }

            response = self.session.post(
                f'{self.privy_url}/siwe/authenticate',
                json=json_data,
                headers=self.auth_headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                token = data.get('identity_token')
                if token:
                    self.jwt_token = token
                    self.api_headers['authorization'] = f'Bearer {token}'
                    log_success(f"✅ {self.address[:12]}... авторизован")
                    return True
                log_error("❌ JWT токен отсутствует в ответе")
                return False

            if response.status_code == 429:
                log_warning("⚠️  Rate limit (429), требуется смена прокси")
                return False

            log_error(f"❌ Ошибка авторизации: HTTP {response.status_code}")
            return False

        except Exception as e:
            log_error(f"❌ Ошибка авторизации: {e}")
            return False
    
    def _api_get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Универсальный GET запрос к API"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.get(
                url,
                headers=self.api_headers,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                log_warning(f"⚠️ {endpoint}: требуется авторизация (401)")
                return None
            elif response.status_code == 404:
                log_warning(f"⚠️ {endpoint}: не найдено (404)")
                return None
            else:
                log_error(f"❌ {endpoint}: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            log_error(f"❌ Ошибка запроса {endpoint}: {e}")
            return None
    
    def get_balance(self) -> Optional[float]:
        """Получение баланса кошелька"""
        try:
            web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            balance_wei = web3.eth.get_balance(self.address)
            balance_eth = web3.from_wei(balance_wei, 'ether')
            return float(balance_eth)
        except Exception as e:
            log_error(f"❌ Ошибка получения баланса: {e}")
            return None
    
    def get_account_info(self) -> Optional[dict]:
        """Получение информации об аккаунте"""
        return self._api_get("/account")
    
    def get_tasks(self) -> Optional[List[dict]]:
        """Получение списка задач"""
        account = self.get_account_info()
        if account:
            tasks = account.get('tasks', [])
            if tasks:
                log_success(f"✅ Получено задач: {len(tasks)}")
                return tasks
        return None
    
    def get_transactions(self) -> Optional[List[dict]]:
        """Получение транзакций через GraphQL"""
        query = {
            "query": f"""
            {{
              transactions(
                where: {{from: "{self.address.lower()}"}}
                orderBy: timestamp
                orderDirection: desc
                first: 100
              ) {{
                id
                from
                to
                value
                timestamp
                gasUsed
                gasPrice
              }}
            }}
            """
        }
        
        try:
            response = self.session.post(
                self.graphql_url,
                json=query,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                txs = data.get('data', {}).get('transactions', [])
                if txs:
                    log_success(f"✅ Транзакций: {len(txs)}")
                return txs
            else:
                log_error(f"❌ Ошибка GraphQL: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            log_error(f"❌ Ошибка получения транзакций: {e}")
            return None
    
    def get_full_statistics(self) -> dict:
        """Сбор полной статистики"""
        
        account_info = self.get_account_info()
        
        stats = {
            'timestamp': datetime.now().isoformat(),
            'address': self.address,
            'balance': self.get_balance(),
            'account_info': account_info,
            'tasks': self.get_tasks(),
            'transactions': self.get_transactions()
        }
        
        return stats
    
    def save_to_json(self, stats: dict) -> str:
        """Сохранение статистики в JSON (БД)"""
        save_json_to_db(stats['address'], stats)
        return "db"
    
    def save_to_csv(self, stats: dict) -> str:
        """Сохранение статистики в CSV (потокобезопасно)"""
        global CURRENT_CSV_FILE
        
        if CURRENT_CSV_FILE is None:
            CURRENT_CSV_FILE = create_new_csv_file()
        
        filename = CURRENT_CSV_FILE
        
        rows = self._parse_stats_to_rows(stats)
        
        if not rows:
            return str(filename)
        
        with csv_lock:
            new_fields = set()
            for row in rows:
                new_fields.update(row.keys())
            
            common_fields = ['timestamp', 'address', 'balance']
            all_fields = common_fields + sorted([f for f in new_fields if f not in common_fields])
            
            file_exists = filename.exists()
            
            existing_fieldnames = []
            if file_exists:
                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        existing_fieldnames = reader.fieldnames or []
                except:
                    existing_fieldnames = []
            
            if existing_fieldnames:
                fieldnames = existing_fieldnames.copy()
                for field in all_fields:
                    if field not in fieldnames:
                        fieldnames.append(field)
            else:
                fieldnames = all_fields
            
            if file_exists and existing_fieldnames and set(fieldnames) != set(existing_fieldnames):
                existing_rows = []
                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        existing_rows = list(reader)
                except:
                    pass
                
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    if existing_rows:
                        writer.writerows(existing_rows)
                    writer.writerows(rows)
            else:
                mode = 'a' if file_exists else 'w'
                with open(filename, mode, newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    
                    if not file_exists:
                        writer.writeheader()
                    
                    writer.writerows(rows)
        
        return str(filename)
    
    def _parse_stats_to_rows(self, stats: dict) -> List[dict]:
        """Преобразование статистики в одну строку CSV на кошелек"""
        timestamp = stats.get('timestamp', '')
        address = stats.get('address', '')
        balance = stats.get('balance', 0)
        
        row = {
            'timestamp': timestamp,
            'address': address,
            'balance': balance,
        }
        
        account_info = stats.get('account_info', {})
        if account_info:
            trading_volume = account_info.get('tradingVolume', {})
            pulses = account_info.get('pulses', {})
            pulses_data = pulses.get('data', []) if pulses else []
            
            row['neura_points'] = account_info.get('neuraPoints', 0)
            row['trading_volume_month'] = trading_volume.get('month', 0)
            row['trading_volume_all_time'] = trading_volume.get('allTime', 0)
            row['pulses_total'] = len(pulses_data)
            row['pulses_collected'] = sum(1 for p in pulses_data if p.get('isCollected', False))
            row['pulses_first_collected'] = pulses.get('firstCollectedAt', '') if pulses else ''
            row['pulses_last_collected'] = pulses.get('lastCollectedAt', '') if pulses else ''
            
            social_accounts = account_info.get('socialAccounts', [])
            if social_accounts:
                row['social_accounts'] = ', '.join([f"{s.get('type', '')}:{s.get('username', '')}" for s in social_accounts])
            else:
                row['social_accounts'] = ''
        else:
            row['neura_points'] = 0
            row['trading_volume_month'] = 0
            row['trading_volume_all_time'] = 0
            row['pulses_total'] = 0
            row['pulses_collected'] = 0
            row['pulses_first_collected'] = ''
            row['pulses_last_collected'] = ''
            row['social_accounts'] = ''
        
        tasks = stats.get('tasks', [])
        if tasks:
            row['tasks_total'] = len(tasks)
            row['tasks_completed'] = sum(1 for t in tasks if t.get('status') == 'completed')
            row['tasks_points'] = sum(t.get('points', 0) for t in tasks)
        else:
            row['tasks_total'] = 0
            row['tasks_completed'] = 0
            row['tasks_points'] = 0
        
        transactions = stats.get('transactions', [])
        row['transactions_count'] = len(transactions) if transactions else 0
        
        return [row]


def load_wallets() -> List[str]:
    """Загрузка приватных ключей из файла"""
    try:
        with open('data/private_keys.txt', 'r') as f:
            keys = [line.strip() for line in f if line.strip()]
        return keys
    except Exception as e:
        log_error(f"❌ Ошибка загрузки кошельков: {e}")
        return []


def load_proxies() -> List[str]:
    """Загрузка всех прокси"""
    try:
        with open('data/proxy.csv', 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        return proxies
    except Exception as e:
        log_warning(f"⚠️ Ошибка загрузки прокси: {e}")
        return []


def get_proxy_for_wallet(wallet_index: int, proxies: List[str]) -> Optional[str]:
    """Получить прокси для кошелька по индексу (1к1)"""
    if not proxies:
        return None
    proxy_index = wallet_index % len(proxies)
    return f"http://{proxies[proxy_index]}"


def get_random_proxy(proxies: List[str]) -> Optional[str]:
    """Получить случайную прокси"""
    if not proxies:
        return None
    return f"http://{random.choice(proxies)}"


def process_wallet_thread(wallet_data: Dict[str, Any]) -> bool:
    """Обработка одного кошелька в потоке"""
    wallet_index = wallet_data['index']
    private_key = wallet_data['private_key']
    proxy = wallet_data['proxy']
    proxies = wallet_data['proxies']
    total = wallet_data['total']
    
    import hashlib
    private_key_hash = hashlib.sha256(private_key.encode()).hexdigest()[:16]
    
    try:
        account = Account.from_key(private_key)
        wallet_address = account.address
        
        mark_wallet_processing(wallet_address, private_key_hash)
        
        client = NeuraProtocolClient(private_key, proxy)
        
        auth_success = False
        for attempt in range(1, RETRY_COUNT + 1):
            if client.authenticate():
                auth_success = True
                break
            
            if attempt < RETRY_COUNT:
                new_proxy = get_random_proxy(proxies)
                if new_proxy:
                    client.change_proxy(new_proxy)
                time.sleep(2)
        
        if not auth_success:
            error_msg = "Авторизация не удалась после всех попыток"
            mark_wallet_error(wallet_address, error_msg)
            log_error(f"❌ [{wallet_index}/{total}] {wallet_address[:12]}... - {error_msg}")
            return False
        
        stats = client.get_full_statistics()
        client.save_to_json(stats)
        client.save_to_csv(stats)
        
        mark_wallet_success(wallet_address)
        
        account_info = stats.get('account_info', {})
        points = account_info.get('neuraPoints', 0)
        pulses = len(account_info.get('pulses', {}).get('data', []))
        
        log_success(
            f"✅ [{wallet_index}/{total}] {wallet_address[:12]}... | "
            f"Points: {points} | "
            f"Pulses: {pulses}"
        )
        return True
        
    except Exception as e:
        error_msg = str(e)[:200]
        try:
            if 'wallet_address' in locals():
                mark_wallet_error(wallet_address, error_msg)
        except:
            pass
        log_error(f"❌ [{wallet_index}/{total}] Критическая ошибка: {error_msg}")
        return False


def neura_statistics():
    """Главная функция с многопоточностью"""
    global CURRENT_CSV_FILE
    
    print("\n" + "="*60)
    print("🔮 NEURA PROTOCOL STATISTICS (Multithreaded)")
    print("="*60 + "\n")
    
    if not astrum_CAPTCHA_API_KEY or len(astrum_CAPTCHA_API_KEY.strip()) == 0:
        log_error("❌ КРИТИЧЕСКАЯ ОШИБКА: API ключ капчи не настроен!")
        log_warning("⚠️  Установите astrum_CAPTCHA_API_KEY в config/config.py")
        log_info("ℹ️  Получить ключ можно в: https://t.me/astrumsolutionsbot")
        return
    
    if len(astrum_CAPTCHA_API_KEY) != 36 or astrum_CAPTCHA_API_KEY.count('-') != 4:
        log_error("❌ КРИТИЧЕСКАЯ ОШИБКА: Неверный формат API ключа капчи!")
        log_warning(f"⚠️  Текущий ключ: {astrum_CAPTCHA_API_KEY[:10]}... (длина: {len(astrum_CAPTCHA_API_KEY)})")
        log_info("ℹ️  Ожидается UUID формат: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 символов)")
        return
        return
    
    init_database()
    
    wallets = load_wallets()
    proxies = load_proxies()
    
    if not wallets:
        log_error("❌ Нет кошельков")
        return
    
    log_info(f"📁 Кошельков: {len(wallets)} | 🌐 Прокси: {len(proxies)} | 🧵 Потоков: {NUM_THREADS}")
    
    stats = get_progress_stats()
    total_in_db = sum(stats.values())
    
    if total_in_db > 0:
        has_pending = stats['pending'] + stats['processing'] + stats['error'] > 0
        all_completed = stats['success'] == total_in_db and total_in_db > 0
        
        if all_completed:
            print(f"\n📊 Все кошельки уже обработаны:")
            print(f"  ✅ Успешно: {stats['success']}\n")
            
            action = select(
                "Что делать дальше?",
                choices=[
                    Choice("🔄 Начать заново (очистить БД и пересобрать статистику)", value='restart'),
                    Choice("❌ Выход", value='cancel')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()
            
            if action == 'cancel':
                log_info("👋 Завершено")
                return
            elif action == 'restart':
                clear_database()
                initialize_all_wallets(wallets)
                CURRENT_CSV_FILE = create_new_csv_file()
                log_success("✅ БД очищена, созданы новые задачи")
        
        elif has_pending:
            print(f"\n📊 Найдены незавершенные задачи:")
            print(f"  ✅ Успешно: {stats['success']}")
            print(f"  ❌ Ошибки: {stats['error']}")
            print(f"  ⏳ В обработке: {stats['processing']}")
            print(f"  ⏸️  Ожидание: {stats['pending']}\n")
            
            action = select(
                "Что делать с незавершенными задачами?",
                choices=[
                    Choice("▶️  Продолжить обработку", value='continue'),
                    Choice("🔄 Начать заново (очистить БД)", value='restart'),
                    Choice("❌ Отмена", value='cancel')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()
            
            if action == 'cancel':
                log_info("❌ Отменено пользователем")
                return
            elif action == 'restart':
                clear_database()
                initialize_all_wallets(wallets)
                CURRENT_CSV_FILE = create_new_csv_file()
                log_success("✅ БД очищена, созданы новые задачи")
    else:
        log_info("📝 Создание задач для всех кошельков...")
        initialize_all_wallets(wallets)
        CURRENT_CSV_FILE = create_new_csv_file()
        log_success(f"✅ Создано {len(wallets)} задач")
    
    unprocessed = get_unprocessed_wallets()
    
    if not unprocessed:
        log_success("✅ Все кошельки обработаны!")
        return
    
    tasks = []
    for wallet_info in unprocessed:
        wallet_address = wallet_info['address']
        
        private_key = None
        idx = -1
        for i, pk in enumerate(wallets):
            normalized_pk = pk if pk.startswith('0x') else '0x' + pk
            try:
                acc = Account.from_key(normalized_pk)
                if acc.address == wallet_address:
                    private_key = normalized_pk
                    idx = i
                    break
            except:
                continue
        
        if not private_key or idx == -1:
            log_warning(f"⚠️ Не найден приватный ключ для {wallet_address[:10]}...")
            continue
        
        proxy = get_proxy_for_wallet(idx, proxies)
        
        tasks.append({
            'index': idx + 1,
            'private_key': private_key,
            'proxy': proxy,
            'proxies': proxies,
            'total': len(wallets)
        })
    
    if not tasks:
        log_success("✅ Все кошельки обработаны!")
        return
    
    log_info(f"\n🚀 Запуск {len(tasks)} задач...\n")
    
    success_count = 0
    error_count = 0
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = {executor.submit(process_wallet_thread, task): task for task in tasks}
        
        for future in as_completed(futures):
            try:
                if future.result():
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                error_count += 1
                log_error(f"❌ Критическая ошибка потока: {e}")
    
    print(f"\n{Fore.CYAN}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{'📊 ИТОГОВАЯ СТАТИСТИКА':^70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}  ✅ Успешно:  {success_count:>3} кошельков{Style.RESET_ALL}")
    print(f"{Fore.RED}  ❌ Ошибок:   {error_count:>3} кошельков{Style.RESET_ALL}")
    print(f"  📝 Всего:    {len(tasks):>3} кошельков")
    print(f"{Fore.CYAN}{'='*70}{Style.RESET_ALL}\n")
    
    stats = get_progress_stats()
    total_processed = stats['success'] + stats['error']
    if total_processed >= len(wallets):
        log_success("✅ Все кошельки обработаны!")
        log_info("✅ Итоговая статистика сохранена в result/statistics/")


if __name__ == "__main__":
    neura_statistics()
