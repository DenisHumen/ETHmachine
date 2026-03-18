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
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event
from questionary import Choice, select

sys.path.append(str(Path(__file__).parent.parent.parent))
from modules.simple_logger import logger
from modules.proxy_manager import get_random_proxy, get_proxy_dict, load_proxies, parse_proxy
from config.modules.cfg_base import (
    NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS,
)
from modules.notifications import send_telegram_notification

import requests
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

try:
    from modules.browser_hcaptcha_solver import BrowserHCaptchaSolver
except ImportError:
    BrowserHCaptchaSolver = None

csv_lock = Lock()
db_lock = Lock()
progress_lock = Lock()  

current_progress = {
    'processed': 0,
    'success': 0,
    'errors': 0,
    'start_time': None
}

stop_monitoring = Event()

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


def log_success(message: str):
    logger.success(message)

def log_warning(message: str):
    logger.warning(message)

def log_error(message: str):
    logger.error(message)

def log_info(message: str):
    logger.info(message)


def update_progress(success: bool = None):
    global current_progress
    with progress_lock:
        current_progress['processed'] += 1
        if success is True:
            current_progress['success'] += 1
        elif success is False:
            current_progress['errors'] += 1


def show_progress_status(total_tasks: int):
    global current_progress
    with progress_lock:
        processed = current_progress['processed']
        success = current_progress['success']
        errors = current_progress['errors']
        
        if current_progress['start_time']:
            elapsed = time.time() - current_progress['start_time']
            if processed > 0:
                avg_time = elapsed / processed
                remaining = (total_tasks - processed) * avg_time
                eta_minutes = int(remaining / 60)
                eta_seconds = int(remaining % 60)
                eta_str = f"{eta_minutes}м {eta_seconds}с" if eta_minutes > 0 else f"{eta_seconds}с"
            else:
                eta_str = "расчёт..."
        else:
            eta_str = "расчёт..."
        
        progress_percent = (processed / total_tasks * 100) if total_tasks > 0 else 0
        
        bar_length = 30
        filled = int(bar_length * processed / total_tasks) if total_tasks > 0 else 0
        bar = '█' * filled + '░' * (bar_length - filled)
        
        log_info(
            f"📊 Прогресс: [{bar}] {processed}/{total_tasks} ({progress_percent:.1f}%) | "
            f"✅ {success} | ❌ {errors} | ⏱️ Осталось: ~{eta_str}"
        )


def progress_monitor_thread(total_tasks: int, interval: int = 60):
    log_info(f"🔄 Запущен мониторинг прогресса (обновление каждые {interval} секунд)")
    
    while not stop_monitoring.is_set():
        if stop_monitoring.wait(timeout=interval):
            break 
        
        show_progress_status(total_tasks)
    
    log_info("🛑 Мониторинг прогресса остановлен")


RESULT_DIR = Path("result/statistics")
DB_DIR = Path("db")
DB_FILE = DB_DIR / "neura_stats_progress.db"

CURRENT_CSV_FILE = None


def ensure_directories():
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    DB_DIR.mkdir(parents=True, exist_ok=True)


def create_new_csv_file() -> Path:
    ensure_directories()
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = RESULT_DIR / f"neura_stats_{timestamp_str}.csv"
    return filename


def init_database():
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
    with sqlite3.connect(str(DB_FILE)) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT wallet_address, attempts, error_message
            FROM processing_progress
            WHERE status IN ('pending', 'processing', 'error')
            AND attempts < ?
            ORDER BY attempts ASC, last_attempt ASC
        ''', (RETRY_COUNT,))
        
        results = cursor.fetchall()
        return [{'address': r[0], 'attempts': r[1], 'error': r[2]} for r in results]


def mark_wallet_processing(wallet_address: str, private_key_hash: str):
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
    with db_lock:
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO wallet_stats_json (wallet_address, timestamp, json_data)
                VALUES (?, ?, ?)
            ''', (wallet_address, datetime.now(), json.dumps(json_data, ensure_ascii=False, default=str)))
            conn.commit()


def export_all_results_to_csv() -> Optional[str]:
    global CURRENT_CSV_FILE
    
    try:
        log_info("📊 Экспорт всех результатов из БД в CSV...")
        
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_csv = RESULT_DIR / f"neura_stats_FINAL_{timestamp_str}.csv"
        
        with sqlite3.connect(str(DB_FILE)) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT pp.wallet_address, pp.status, pp.attempts, pp.error_message,
                       pp.created_at, pp.updated_at, wsj.json_data, wsj.timestamp as json_timestamp
                FROM processing_progress pp
                LEFT JOIN wallet_stats_json wsj ON pp.wallet_address = wsj.wallet_address
                ORDER BY pp.created_at ASC
            ''')
            
            results = cursor.fetchall()
            
            if not results:
                log_warning("⚠️ Нет результатов для экспорта")
                return None
            
            with open(final_csv, 'w', newline='', encoding='utf-8') as f:
                fieldnames = [
                    'wallet_address', 'status', 'attempts', 'error_message',
                    'created_at', 'updated_at', 'stats_collected_at',
                    'balance', 'neura_points', 'trading_volume_month', 'trading_volume_all_time',
                    'pulses_count', 'pulses_collected', 'first_pulse_collected', 'last_pulse_collected',
                    'social_accounts',
                    'tasks_total', 'tasks_completed', 'tasks_points', 'transactions_count',
                    'neurapoints_rank', 'neurapoints_value',
                    'streak_rank', 'streak_value',
                    'ankrWhales_rank', 'ankrWhales_value',
                    'zotto_rank', 'zotto_value'
                ]
                
                writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                
                for row in results:
                    wallet_address, status, attempts, error_message, created_at, updated_at, json_data, json_timestamp = row
                    
                    csv_row = {
                        'wallet_address': wallet_address,
                        'status': status,
                        'attempts': attempts or 0,
                        'error_message': error_message or '',
                        'created_at': created_at,
                        'updated_at': updated_at,
                        'stats_collected_at': json_timestamp or '',
                        'balance': '',
                        'neura_points': '',
                        'trading_volume_month': '',
                        'trading_volume_all_time': '',
                        'pulses_count': '',
                        'pulses_collected': '',
                        'first_pulse_collected': '',
                        'last_pulse_collected': '',
                        'social_accounts': '',
                        'tasks_total': '',
                        'tasks_completed': '',
                        'tasks_points': '',
                        'transactions_count': '',
                        'neurapoints_rank': '',
                        'neurapoints_value': '',
                        'streak_rank': '',
                        'streak_value': '',
                        'ankrWhales_rank': '',
                        'ankrWhales_value': '',
                        'zotto_rank': '',
                        'zotto_value': ''
                    }
                    
                    if json_data:
                        try:
                            stats = json.loads(json_data)
                            
                            csv_row['balance'] = stats.get('balance', '')
                            
                            account_info = stats.get('account_info', {})
                            if account_info:
                                csv_row['neura_points'] = account_info.get('neuraPoints', '')
                                
                                trading_volume = account_info.get('tradingVolume', {})
                                if trading_volume:
                                    csv_row['trading_volume_month'] = trading_volume.get('month', '')
                                    csv_row['trading_volume_all_time'] = trading_volume.get('allTime', '')
                                
                                pulses = account_info.get('pulses', {})
                                if pulses:
                                    csv_row['first_pulse_collected'] = pulses.get('firstCollectedAt', '')
                                    csv_row['last_pulse_collected'] = pulses.get('lastCollectedAt', '')
                                    pulses_data = pulses.get('data', [])
                                    csv_row['pulses_count'] = len(pulses_data) if pulses_data else 0
                                    csv_row['pulses_collected'] = sum(1 for p in pulses_data if p.get('isCollected', False))
                                
                                social_accounts = account_info.get('socialAccounts', [])
                                if social_accounts:
                                    csv_row['social_accounts'] = ', '.join([f"{s.get('type', '')}:{s.get('username', '')}" for s in social_accounts])
                            
                            tasks = stats.get('tasks', [])
                            if tasks:
                                csv_row['tasks_total'] = len(tasks)
                                csv_row['tasks_completed'] = sum(1 for t in tasks if t.get('status') == 'completed')
                                csv_row['tasks_points'] = sum(t.get('points', 0) for t in tasks)
                            
                            transactions = stats.get('transactions', [])
                            csv_row['transactions_count'] = len(transactions) if transactions else 0
                            
                            leaderboards = stats.get('leaderboards', {})
                            if leaderboards:
                                csv_row['neurapoints_rank'] = leaderboards.get('neurapoints_rank', '')
                                csv_row['neurapoints_value'] = leaderboards.get('neurapoints_value', '')
                                csv_row['streak_rank'] = leaderboards.get('streak_rank', '')
                                csv_row['streak_value'] = leaderboards.get('streak_value', '')
                                csv_row['ankrWhales_rank'] = leaderboards.get('ankrWhales_rank', '')
                                csv_row['ankrWhales_value'] = leaderboards.get('ankrWhales_value', '')
                                csv_row['zotto_rank'] = leaderboards.get('zotto_rank', '')
                                csv_row['zotto_value'] = leaderboards.get('zotto_value', '')
                            
                        except (json.JSONDecodeError, TypeError) as e:
                            log_warning(f"⚠️ Ошибка парсинга JSON для {wallet_address}: {e}")
                    
                    writer.writerow(csv_row)
            
            CURRENT_CSV_FILE = final_csv
            
            log_success(f"✅ Экспорт завершен: {len(results)} записей → {final_csv.name}")
            return str(final_csv)
            
    except Exception as e:
        log_error(f"❌ Ошибка экспорта результатов в CSV: {e}")
        return None


def clear_database():
    with sqlite3.connect(str(DB_FILE)) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM processing_progress')
        cursor.execute('DELETE FROM wallet_stats_json')
        conn.commit()
    log_success("✅ База данных очищена")


def initialize_all_wallets(wallets: List[str]):
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
    with sqlite3.connect(str(DB_FILE)) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM processing_progress 
            WHERE status IN ('pending', 'processing', 'error')
        ''')
        count = cursor.fetchone()[0]
        return count > 0


def get_progress_stats() -> Dict[str, int]:
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
    
    def __init__(self, private_key: str, proxy_url: Optional[str] = None, proxies_list: List[str] = None):
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
            
        self.private_key = private_key
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.proxies_list = proxies_list or []
        
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
        
        if not BrowserHCaptchaSolver:
            log_warning("BrowserHCaptchaSolver not available - auth may fail")
    
    def change_proxy(self, new_proxy: str):
        if new_proxy:
            self.proxies = {
                'http': new_proxy,
                'https': new_proxy
            }
            self.session.proxies.update(self.proxies)
        else:
            self.proxies = None
            self.session.proxies.clear()
    
    def _get_nonce(self, wallet_index: int = None, total: int = None) -> Optional[str]:
        """Get nonce via browser-based hCaptcha solver (Playwright + stealth)."""
        import asyncio

        if not BrowserHCaptchaSolver:
            log_error("BrowserHCaptchaSolver not available")
            return None

        proxy_str = None
        if self.proxies:
            proxy_str = self.proxies.get('http') or self.proxies.get('https')

        for attempt in range(RETRY_COUNT):
            try:
                solver = BrowserHCaptchaSolver(proxy=proxy_str)
                nonce = asyncio.run(solver.solve_and_init(
                    wallet_address=self.address,
                    timeout=45,
                ))
                if nonce:
                    return nonce
            except Exception as e:
                log_warning(f"Browser captcha attempt {attempt + 1} failed: {e}")
                time.sleep(random.uniform(3, 7))

        return None
    
    def authenticate(self, max_retries: int = 3, wallet_index: int = None, total: int = None) -> bool:
        try:
            nonce = self._get_nonce(wallet_index=wallet_index, total=total)
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
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                token = data.get('identity_token')
                if token:
                    self.jwt_token = token
                    self.api_headers['authorization'] = f'Bearer {token}'
                    return True
                return False

            return False

        except Exception as e:
            return False
    
    def _api_get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.get(
                url,
                headers=self.api_headers,
                params=params,
                timeout=15 
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
        try:
            request_kwargs = {'timeout': 15}
            if self.proxies:
                request_kwargs['proxies'] = self.proxies
            
            web3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs=request_kwargs))
            balance_wei = web3.eth.get_balance(self.address)
            balance_eth = web3.from_wei(balance_wei, 'ether')
            
            return float(balance_eth)
        except Exception as e:
            return None
    
    def get_account_info(self) -> Optional[dict]:
        """Получить информацию об аккаунте с параметром epoch=base"""
        return self._api_get("/account", params={"epoch": "base"})
    
    def get_tasks(self) -> Optional[List[dict]]:
        """Получить список задач через отдельный endpoint /api/tasks"""
        result = self._api_get("/tasks")
        if result:
            return result.get('tasks', [])
        return None
    
    def get_transactions(self) -> Optional[List[dict]]:
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
                timeout=15  # Уменьшено с 30 до 15 секунд
            )
            
            if response.status_code == 200:
                data = response.json()
                txs = data.get('data', {}).get('transactions', [])
                return txs
            else:
                return None
                
        except Exception as e:
            return None
    
    def get_leaderboards(self) -> Optional[dict]:
        try:
            response = self.session.get(
                f"{self.base_url}/leaderboards",
                headers=self.api_headers,
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                leaderboards_data = data.get('leaderboards', [])
                
                ranks = {}
                for leaderboard in leaderboards_data:
                    lb_type = leaderboard.get('type', '')
                    account_rank = leaderboard.get('accountRank')
                    account_value = leaderboard.get('accountValue')
                    
                    if lb_type:
                        ranks[f'{lb_type}_rank'] = account_rank if account_rank is not None else 0
                        ranks[f'{lb_type}_value'] = account_value if account_value is not None else 0
                
                return ranks
            else:
                return None
                
        except Exception as e:
            return None
    
    def get_full_statistics(self) -> dict:
        account_info = self.get_account_info()
        balance = self.get_balance()
        tasks = self.get_tasks()
        transactions = self.get_transactions()
        leaderboards = self.get_leaderboards()
        
        stats = {
            'timestamp': datetime.now().isoformat(),
            'address': self.address,
            'balance': balance,
            'account_info': account_info,
            'tasks': tasks,
            'leaderboards': leaderboards,
            'transactions': transactions
        }
        
        return stats
    
    def save_to_json(self, stats: dict) -> str:
        save_json_to_db(stats['address'], stats)
        return "db"
    
    def save_to_csv(self, stats: dict) -> str:
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
        
        leaderboards = stats.get('leaderboards', {})
        if leaderboards:
            row['neurapoints_rank'] = leaderboards.get('neurapoints_rank', 0)
            row['neurapoints_value'] = leaderboards.get('neurapoints_value', 0)
            
            row['streak_rank'] = leaderboards.get('streak_rank', 0)
            row['streak_value'] = leaderboards.get('streak_value', 0)
            
            row['ankrWhales_rank'] = leaderboards.get('ankrWhales_rank', 0)
            row['ankrWhales_value'] = leaderboards.get('ankrWhales_value', 0)
            
            row['zotto_rank'] = leaderboards.get('zotto_rank', 0)
            row['zotto_value'] = leaderboards.get('zotto_value', 0)
        else:
            row['neurapoints_rank'] = 0
            row['neurapoints_value'] = 0
            row['streak_rank'] = 0
            row['streak_value'] = 0
            row['ankrWhales_rank'] = 0
            row['ankrWhales_value'] = 0
            row['zotto_rank'] = 0
            row['zotto_value'] = 0
        
        return [row]


def load_wallets() -> List[str]:
    from modules.data_manager import get_private_keys
    return get_private_keys()


def load_proxies() -> List[str]:
    from modules.data_manager import get_proxies
    return get_proxies()


def get_proxy_for_wallet(wallet_index: int, proxies: List[str]) -> Optional[str]:
    if not proxies:
        return None
    proxy_index = wallet_index % len(proxies)
    return parse_proxy(proxies[proxy_index])


def process_wallet_thread(wallet_data: Dict[str, Any]) -> bool:
    wallet_index = wallet_data['index'] 
    task_index = wallet_data['task_index'] 
    total_tasks = wallet_data['total_tasks'] 
    private_key = wallet_data['private_key']
    proxy = wallet_data['proxy']
    proxies = wallet_data['proxies']
    
    if task_index <= NUM_THREADS:
        delay = random.uniform(0, 0.5)
    else:
        delay = random.uniform(0, 1)
    
    time.sleep(delay)
    
    import hashlib
    private_key_hash = hashlib.sha256(private_key.encode()).hexdigest()[:16]
    
    try:
        account = Account.from_key(private_key)
        wallet_address = account.address
        
        progress_percent = (task_index / total_tasks) * 100
        bar_length = 30
        filled_length = int(bar_length * task_index // total_tasks)
        progress_bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        wallet_short = f"{wallet_address[:6]}...{wallet_address[-4:]}"
        
        print_lock = Lock()
        
        def update_status(status, log_level="INFO"):
            timestamp = datetime.now().strftime("%H:%M:%S")
            level_map = {
                "SUCCESS": "SUCCESS",
                "INFO": "INFO    ",
                "ERROR": "ERROR   ",
                "WARNING": "WARNING "
            }
            level = level_map.get(log_level, "INFO    ")
            
            log_line = f"{timestamp} | {level} | [{task_index:04d}/{total_tasks}] [{wallet_address}] [{progress_bar}] {progress_percent:.1f}% - {status}"
            
            with print_lock:
                print(f"\r{' ' * 200}\r{log_line}", end='', flush=True)
                
                if log_level in ["SUCCESS", "ERROR"]:
                    print()
        
        mark_wallet_processing(wallet_address, private_key_hash)
        
        update_status("🔧 Инициализация")
        client = NeuraProtocolClient(private_key, proxy, proxies)
        
        auth_success = False
        max_auth_attempts = 3
        
        for attempt in range(1, max_auth_attempts + 1):
            update_status(f"🔐 Авторизация {attempt}/{max_auth_attempts}")
            
            if client.authenticate(wallet_index=task_index, total=total_tasks):
                auth_success = True
                break
            
            if attempt < max_auth_attempts:
                update_status(f"🔄 Смена прокси {attempt}/{max_auth_attempts}", "WARNING")
                new_proxy = get_random_proxy(proxies)
                if new_proxy:
                    client.change_proxy(new_proxy)
                time.sleep(1)
        
        if not auth_success:
            error_msg = "Ошибка авторизации"
            mark_wallet_error(wallet_address, error_msg)
            update_progress(success=False)
            update_status(f"❌ {error_msg}", "ERROR")
            return False
        
        update_status("📊 Сбор данных")
        stats = client.get_full_statistics()
        
        # DEBUG: показать структуру account_info
        update_status("💾 Сохранение")
        client.save_to_json(stats)
        client.save_to_csv(stats)
        
        mark_wallet_success(wallet_address)
        
        account_info = stats.get('account_info') or {}
        points = account_info.get('neuraPoints', 0) if account_info else 0
        pulses_data = account_info.get('pulses', {}).get('data', []) if account_info else []
        pulses = len(pulses_data)
        balance = stats.get('balance', 0) or 0
        
        update_progress(success=True)
        update_status(f"✅ Points: {points} | Pulses: {pulses} | ANKR testnet: {balance:.4f}", "SUCCESS")
        
        sleep_time = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
        time.sleep(sleep_time)
        
        return True
        
    except Exception as e:
        error_msg = str(e)[:100]
        try:
            if 'wallet_address' in locals():
                mark_wallet_error(wallet_address, error_msg)
        except:
            pass
        update_progress(success=False)
        
        if 'update_status' in locals():
            try:
                update_status(f"❌ Критическая ошибка: {error_msg}", "ERROR")
            except:
                timestamp = datetime.now().strftime("%H:%M:%S")
                if 'wallet_address' in locals() and 'wallet_index' in locals():
                    print(f"\r{' ' * 200}\r{timestamp} | ERROR    | [{wallet_index:04d}] [{wallet_address}] ❌ {error_msg}")
                else:
                    print(f"\r{' ' * 200}\r{timestamp} | ERROR    | ❌ {error_msg}")
                print()
        else:
            timestamp = datetime.now().strftime("%H:%M:%S")
            if 'wallet_address' in locals() and 'wallet_index' in locals():
                print(f"\r{' ' * 200}\r{timestamp} | ERROR    | [{wallet_index:04d}] [{wallet_address}] ❌ {error_msg}")
            else:
                print(f"\r{' ' * 200}\r{timestamp} | ERROR    | ❌ {error_msg}")
            print()
        
        return False


def neura_statistics():
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
        log_warning(f"⚠️  Текущий ключ: {astrum_CAPTCHA_API_KEY[:10]} (длина: {len(astrum_CAPTCHA_API_KEY)})")
        log_info("ℹ️  Ожидается UUID формат: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 символов)")
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
    
    should_process = False
    
    if total_in_db > 0:
        has_pending = stats['pending'] + stats['processing'] + stats['error'] > 0
        all_completed = stats['success'] == total_in_db and total_in_db > 0
        
        if all_completed:
            print(f"\n📊 Все кошельки уже обработаны:")
            print(f"  ✅ Успешно: {stats['success']}\n")
            
            action = select(
                "Что делать дальше?",
                choices=[
                    Choice("📎 Экспортировать текущие результаты из БД в CSV", value='export'),
                    Choice("🔄 Начать заново (очистить БД и пересобрать статистику)", value='restart'),
                    Choice("❌ Выход", value='cancel')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()
            
            if action == 'cancel':
                log_info("👋 Завершено")
                return
            elif action == 'export':
                log_info("📊 Экспорт текущих результатов из БД...")
                final_csv_path = export_all_results_to_csv()
                if final_csv_path:
                    log_success(f"✅ Экспорт завершен: {Path(final_csv_path).name}")
                    
                    send_tg = select(
                        "Отправить CSV файл в Telegram?",
                        choices=[
                            Choice("✅ Да, отправить", value='yes'),
                            Choice("❌ Нет, не надо", value='no')
                        ],
                        qmark='📱',
                        pointer='👉'
                    ).ask()
                    
                    if send_tg == 'yes':
                        try:
                            send_telegram_notification(
                                notif_type="success",
                                title="Экспорт статистики Neura",
                                message=f"✅ Экспортировано: {stats['success']} записей из БД",
                                main_title="Neura Statistics Export",
                                file_path=final_csv_path
                            )
                            log_success("📱 CSV файл отправлен в Telegram")
                        except Exception as e:
                            log_error(f"❌ Ошибка отправки в Telegram: {e}")
                    
                    log_info(f"📂 Файл сохранен: {final_csv_path}")
                else:
                    log_error("❌ Не удалось экспортировать результаты")
                return
            elif action == 'restart':
                clear_database()
                initialize_all_wallets(wallets)
                CURRENT_CSV_FILE = create_new_csv_file()
                log_success("✅ БД очищена, созданы новые задачи")
                should_process = True 
        
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
                    Choice("📎 Экспортировать текущие результаты из БД в CSV", value='export'),
                    Choice("🔄 Начать заново (очистить БД)", value='restart'),
                    Choice("❌ Отмена", value='cancel')
                ],
                qmark='🛠️',
                pointer='👉'
            ).ask()
            
            if action == 'cancel':
                log_info("❌ Отменено пользователем")
                return
            elif action == 'export':
                log_info("📊 Экспорт текущих результатов из БД...")
                final_csv_path = export_all_results_to_csv()
                if final_csv_path:
                    log_success(f"✅ Экспорт завершен: {Path(final_csv_path).name}")
                    
                    send_tg = select(
                        "Отправить CSV файл в Telegram?",
                        choices=[
                            Choice("✅ Да, отправить", value='yes'),
                            Choice("❌ Нет, не надо", value='no')
                        ],
                        qmark='📱',
                        pointer='👉'
                    ).ask()
                    
                    if send_tg == 'yes':
                        try:
                            completed = stats['success'] + stats['error']
                            send_telegram_notification(
                                notif_type="info",
                                title="Экспорт статистики Neura (частичный)",
                                message=f"✅ Успешно: {stats['success']}\n❌ Ошибок: {stats['error']}\n⏸️ Не обработано: {stats['pending'] + stats['processing']}",
                                main_title="Neura Statistics Export",
                                file_path=final_csv_path
                            )
                            log_success("📱 CSV файл отправлен в Telegram")
                        except Exception as e:
                            log_error(f"❌ Ошибка отправки в Telegram: {e}")
                    
                    log_info(f"📂 Файл сохранен: {final_csv_path}")
                else:
                    log_error("❌ Не удалось экспортировать результаты")
                return
            elif action == 'restart':
                clear_database()
                initialize_all_wallets(wallets)
                CURRENT_CSV_FILE = create_new_csv_file()
                log_success("✅ БД очищена, созданы новые задачи")
                should_process = True 
            elif action == 'continue':
                should_process = True 
    else:
        log_info("📝 Создание задач для всех кошельков...")
        initialize_all_wallets(wallets)
        CURRENT_CSV_FILE = create_new_csv_file()
        log_success(f"✅ Создано {len(wallets)} задач")
        should_process = True 
    
    if not should_process:
        log_info("⏸️  Обработка не запущена")
        return
    
    log_info("📋 Получение списка необработанных кошельков...")
    unprocessed = get_unprocessed_wallets()
    
    if not unprocessed:
        log_success("✅ Все кошельки обработаны!")
        return
    
    log_info(f"🔍 Создание индекса приватных ключей для {len(wallets)} кошельков...")
    
    wallet_map = {}
    for i, pk in enumerate(wallets):
        normalized_pk = pk if pk.startswith('0x') else '0x' + pk
        try:
            acc = Account.from_key(normalized_pk)
            wallet_map[acc.address] = (normalized_pk, i)
        except Exception as e:
            log_warning(f"⚠️ Неверный приватный ключ #{i+1}: {str(e)[:50]}")
            continue
    
    log_success(f"✅ Индекс создан: {len(wallet_map)} валидных кошельков")
    log_info(f"🔨 Формирование задач для {len(unprocessed)} необработанных кошельков...")
    
    tasks = []
    for wallet_info in unprocessed:
        wallet_address = wallet_info['address']
        
        if wallet_address not in wallet_map:
            log_warning(f"⚠️ Не найден приватный ключ для {wallet_address[:10]}")
            continue
        
        private_key, idx = wallet_map[wallet_address]
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
    
    random.shuffle(tasks)
    
    total_tasks = len(tasks)
    for i, task in enumerate(tasks):
        task['task_index'] = i + 1 
        task['total_tasks'] = total_tasks 
    
    log_info(f"🎲 Порядок кошельков рандомизирован")
    
    log_info(f"\n{'='*70}")
    log_info(f"🚀 Запуск обработки {len(tasks)} кошельков")
    log_info(f"🧵 Количество потоков: {NUM_THREADS}")
    log_info(f"⚡ Первая волна ({min(NUM_THREADS, len(tasks))} кошельков) стартует сразу")
    log_info(f"⏱️  Остальные подтягиваются с минимальной задержкой")
    log_info(f"{'='*70}\n")
    
    global current_progress, stop_monitoring
    current_progress = {
        'processed': 0,
        'success': 0,
        'errors': 0,
        'start_time': time.time()
    }
    stop_monitoring.clear()  
    
    try:
        send_telegram_notification(
            notif_type="info",
            title="Сбор статистики Neura Protocol",
            message=f"🚀 Начата обработка {len(tasks)} кошельков\n🧵 Потоков: {NUM_THREADS}",
            main_title="Neura Statistics"
        )
        log_info("📱 Telegram уведомление о старте отправлено")
    except Exception as e:
        log_warning(f"⚠️ Не удалось отправить Telegram уведомление: {e}")
    
    success_count = 0
    error_count = 0
    progress_interval = 60 
    
    monitor_thread = threading.Thread(
        target=progress_monitor_thread,
        args=(len(tasks), progress_interval),
        daemon=True
    )
    monitor_thread.start()
    log_info("✅ Поток мониторинга прогресса запущен")
    
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
    
    stop_monitoring.set()
    monitor_thread.join(timeout=5)  
    
    show_progress_status(len(tasks))
    
    total_time = time.time() - current_progress['start_time']
    hours = int(total_time // 3600)
    minutes = int((total_time % 3600) // 60)
    seconds = int(total_time % 60)
    time_str = f"{hours}ч {minutes}м {seconds}с" if hours > 0 else f"{minutes}м {seconds}с" if minutes > 0 else f"{seconds}с"
    
    print(f"\n{Fore.CYAN}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{'📊 ИТОГОВАЯ СТАТИСТИКА':^70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*70}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}  ✅ Успешно:  {success_count:>3} кошельков{Style.RESET_ALL}")
    print(f"{Fore.RED}  ❌ Ошибок:   {error_count:>3} кошельков{Style.RESET_ALL}")
    print(f"  📝 Всего:    {len(tasks):>3} кошельков")
    print(f"  ⏱️  Время:    {time_str}")
    print(f"{Fore.CYAN}{'='*70}{Style.RESET_ALL}\n")
    
    stats = get_progress_stats()
    total_processed = stats['success'] + stats['error']
    
    log_info("📊 Создание итогового CSV файла с всеми результатами из БД...")
    final_csv_path = export_all_results_to_csv()
    
    try:
        if final_csv_path and Path(final_csv_path).exists():
            log_info(f"📎 Прикрепление итогового CSV файла: {Path(final_csv_path).name}")
            send_telegram_notification(
                notif_type="success",
                title="Статистика Neura собрана",
                message=f"✅ Успешно: {success_count}\n❌ Ошибок: {error_count}\n⏱️ Время: {time_str}\n📊 Экспорт: {total_processed} записей из БД",
                main_title="Neura Statistics",
                file_path=final_csv_path
            )
            log_success(f"📱 Telegram уведомление с итоговым CSV файлом отправлено ({Path(final_csv_path).name})")
        elif CURRENT_CSV_FILE and CURRENT_CSV_FILE.exists():
            log_warning("⚠️ Итоговый CSV не создан, отправляем рабочий файл")
            log_info(f"📎 Прикрепление рабочего CSV файла: {CURRENT_CSV_FILE.name}")
            send_telegram_notification(
                notif_type="success",
                title="Статистика Neura собрана",
                message=f"✅ Успешно: {success_count}\n❌ Ошибок: {error_count}\n⏱️ Время: {time_str}",
                main_title="Neura Statistics",
                file_path=str(CURRENT_CSV_FILE)
            )
            log_success(f"📱 Telegram уведомление с рабочим CSV файлом отправлено ({CURRENT_CSV_FILE.name})")
        else:
            log_warning(f"⚠️ Ни итоговый, ни рабочий CSV файлы не найдены")
            send_telegram_notification(
                notif_type="success",
                title="Статистика Neura собрана",
                message=f"✅ Успешно: {success_count}\n❌ Ошибок: {error_count}\n⏱️ Время: {time_str}",
                main_title="Neura Statistics"
            )
            log_info("📱 Telegram уведомление отправлено (без файла)")
    except Exception as e:
        log_error(f"❌ Не удалось отправить финальное Telegram уведомление: {e}")
    
    if total_processed >= len(wallets):
        log_success("✅ Все кошельки обработаны!")
        log_info("✅ Итоговая статистика сохранена в result/statistics/")


if __name__ == "__main__":
    neura_statistics()
