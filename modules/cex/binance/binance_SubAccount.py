import hmac
import hashlib
import json
import time
import requests
from datetime import datetime
from colorama import Fore, Style, init
from loguru import logger
import sys
from pathlib import Path
from urllib.parse import urlencode

# Импорт селектора аккаунтов
from modules.cex.exchange_selector import select_binance_account

init()

# Настройка логгера
project_root = Path(__file__).parent.parent.parent.parent
log_dir = project_root / 'log'

# Флаг инициализации логгера
_logger_initialized = False

def _setup_logging():
    """Настройка логирования - вызывается при запуске модуля"""
    global _logger_initialized
    if _logger_initialized:
        return
    _logger_initialized = True
    
    log_dir.mkdir(exist_ok=True)
    
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO"
    )

    logger.add(
        log_dir / "binance_subaccount_errors.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="ERROR",
        rotation="10 MB",
        retention="7 days"
    )

    logger.add(
        log_dir / "binance_subaccount_full.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="50 MB",
        retention="3 days"
    )

class BinanceClient:
    def __init__(self, api_key, secret_key, testnet=False):
        """
        Инициализация клиента Binance
        
        Args:
            api_key: API ключ
            secret_key: Секретный ключ
            testnet: Использовать testnet окружение
        """
        self.api_key = api_key
        self.secret_key = secret_key
        
        if testnet:
            self.base_url = "https://testnet.binance.vision"
        else:
            self.base_url = "https://api.binance.com"
        
        self.session = requests.Session()
        
    def _generate_signature(self, query_string):
        """Генерация подписи для запроса"""
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _get_headers(self):
        """Получение заголовков для запроса"""
        return {
            'X-MBX-APIKEY': self.api_key,
            'Content-Type': 'application/json'
        }

    def _make_request(self, method, endpoint, params=None, signed=False):
        """Выполнение запроса к API"""
        url = self.base_url + endpoint
        headers = self._get_headers()
        
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            query_string = urlencode(params)
            params['signature'] = self._generate_signature(query_string)
        
        try:
            if method == 'GET':
                response = self.session.get(url, headers=headers, params=params, timeout=30)
            elif method == 'POST':
                response = self.session.post(url, headers=headers, data=params, timeout=30)
            else:
                raise ValueError(f"Неподдерживаемый метод: {method}")
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка запроса к Binance API: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    logger.error(f"Детали ошибки: {error_data}")
                except:
                    logger.error(f"Ответ сервера: {e.response.text}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка декодирования JSON ответа: {e}")
            raise

    def get_subaccounts_list(self):
        """Получение списка субаккаунтов"""
        try:
            endpoint = "/sapi/v1/sub-account/list"
            response = self._make_request('GET', endpoint, signed=True)
            
            subaccounts = response.get('subAccounts', [])
            logger.info(f"Найдено {len(subaccounts)} субаккаунтов")
            return subaccounts
                
        except Exception as e:
            logger.error(f"Исключение при получении субаккаунтов: {e}")
            return []

    def get_subaccount_balance(self, email):
        """Получение баланса конкретного субаккаунта"""
        try:
            endpoint = "/sapi/v1/sub-account/assets"
            params = {'email': email}
            
            response = self._make_request('GET', endpoint, params=params, signed=True)
            
            balances = response.get('balances', [])
            return balances
                
        except Exception as e:
            logger.error(f"Исключение при получении баланса для {email}: {e}")
            return []

    def get_main_account_balance(self):
        """Получение баланса основного аккаунта"""
        try:
            endpoint = "/api/v3/account"
            response = self._make_request('GET', endpoint, signed=True)
            
            balances = response.get('balances', [])
            return balances
                
        except Exception as e:
            logger.error(f"Исключение при получении баланса основного аккаунта: {e}")
            return []

    def transfer_from_subaccount_to_main(self, fromEmail, asset, amount):
        """Перевод средств с субаккаунта на основной аккаунт"""
        try:
            endpoint = "/sapi/v1/sub-account/universalTransfer"
            params = {
                'fromEmail': fromEmail,
                'toEmail': '',  # Пустое значение означает основной аккаунт
                'fromAccountType': 'SPOT',
                'toAccountType': 'SPOT',
                'asset': asset,
                'amount': str(amount)
            }
            
            response = self._make_request('POST', endpoint, params=params, signed=True)
            
            if response.get('tranId'):
                logger.info(f"✅ Успешно переведено {amount} {asset} с {fromEmail} на основной аккаунт")
                return True
            else:
                logger.error(f"❌ Ошибка перевода {amount} {asset} с {fromEmail}: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Исключение при переводе с {fromEmail}: {e}")
            return False

    def collect_all_subaccount_balances(self):
        """Сбор всех балансов с субаккаунтов на основной аккаунт"""
        try:
            logger.info(Fore.YELLOW + "🔄 Начинаем сбор средств с субаккаунтов...")
            
            # Получение списка субаккаунтов
            subaccounts = self.get_subaccounts_list()
            
            if not subaccounts:
                logger.info("⚠️ Субаккаунты не найдены")
                return
            
            total_transfers = 0
            successful_transfers = 0
            failed_transfers = 0
            
            for i, subacct in enumerate(subaccounts, 1):
                email = subacct.get('email', 'Unknown')
                logger.info(Fore.CYAN + f"📊 [{i}/{len(subaccounts)}] Проверка баланса для сбора: {email}")
                
                # Получение баланса субаккаунта
                balance = self.get_subaccount_balance(email)
                
                if balance:
                    # Фильтруем только ненулевые балансы
                    non_zero_balances = [b for b in balance if float(b.get('free', 0)) > 0]
                    
                    if non_zero_balances:
                        logger.info(f"💰 Найдено {len(non_zero_balances)} активов для перевода")
                        
                        for bal in non_zero_balances:
                            asset = bal.get('asset', 'Unknown')
                            amount = float(bal.get('free', 0))
                            
                            if amount > 0:
                                logger.info(f"🔄 Переводим {amount} {asset} с {email}")
                                total_transfers += 1
                                
                                # Выполняем перевод
                                if self.transfer_from_subaccount_to_main(email, asset, amount):
                                    successful_transfers += 1
                                else:
                                    failed_transfers += 1
                                
                                # Пауза между переводами
                                time.sleep(1)
                    else:
                        logger.info(f"⚪ {email} - нет активов для перевода")
                else:
                    logger.info(f"❌ {email} - ошибка получения баланса")
                
                # Пауза между субаккаунтами
                time.sleep(0.5)
            
            # Итоговая статистика сбора
            logger.info(Fore.MAGENTA + "="*80)
            logger.info(Fore.YELLOW + "📊 ИТОГИ СБОРА СРЕДСТВ:")
            logger.info(Fore.CYAN + f"📈 Всего переводов: {total_transfers}")
            logger.info(Fore.GREEN + f"✅ Успешных переводов: {successful_transfers}")
            logger.info(Fore.RED + f"❌ Неудачных переводов: {failed_transfers}")
            
            if total_transfers > 0:
                success_rate = (successful_transfers / total_transfers) * 100
                logger.info(Fore.CYAN + f"📈 Процент успеха: {success_rate:.1f}%")
            
            logger.info(Fore.MAGENTA + "="*80)
            
        except Exception as e:
            logger.error(f"Критическая ошибка при сборе средств: {e}")

def check_binance_subaccounts_and_balances():
    """Основная функция для проверки субаккаунтов и балансов Binance"""
    
    logger.info(Fore.MAGENTA + "="*80)
    logger.info(Fore.YELLOW + "🚀 Запуск проверки субаккаунтов и балансов Binance")
    logger.info(Fore.MAGENTA + "="*80)
    
    # Выбираем аккаунт Binance
    exchange_name, account = select_binance_account()
    if not account:
        logger.error("❌ Не выбран аккаунт Binance")
        return
    
    logger.info(f"🏢 Используется аккаунт: {account['name']}")
    
    # Получаем данные аккаунта
    binance_api_key = account['api_key']
    secret_key = account['api_secret']
    
    # Проверяем настройки API
    if not all([binance_api_key, secret_key]):
        logger.error("❌ Не настроены API ключи Binance в выбранном аккаунте")
        return
    
    # Инициализация клиента
    client = BinanceClient(
        api_key=binance_api_key,
        secret_key=secret_key,
        testnet=False  # Используем production
    )
    
    # ШАГ 1: Получение и отображение всех балансов
    logger.info(Fore.YELLOW + "📊 ШАГ 1: ПРОВЕРКА ВСЕХ БАЛАНСОВ")
    logger.info(Fore.MAGENTA + "="*80)
    
    all_balances = []
    total_accounts = 0
    accounts_with_balance = 0
    subaccounts_with_balance = []
    
    try:
        # Получение баланса основного аккаунта
        logger.info(Fore.CYAN + "📊 ОСНОВНОЙ АККАУНТ:")
        logger.info("-" * 50)
        
        main_balance = client.get_main_account_balance()
        total_accounts += 1
        
        if main_balance:
            non_zero_balances = [b for b in main_balance if float(b.get('free', 0)) > 0 or float(b.get('locked', 0)) > 0]
            if non_zero_balances:
                logger.info(Fore.GREEN + f"✅ Найдено {len(non_zero_balances)} активов:")
                for balance in non_zero_balances:
                    asset = balance.get('asset', 'Unknown')
                    free = float(balance.get('free', 0))
                    locked = float(balance.get('locked', 0))
                    total = free + locked
                    
                    logger.info(f"   💰 {asset}: {total:,.8f}")
                    if locked > 0:
                        logger.info(f"      ├─ Свободно: {free:,.8f}")
                        logger.info(f"      └─ Заблокировано: {locked:,.8f}")
                    
                all_balances.append({
                    'account_name': 'Main Account',
                    'account_type': 'main',
                    'balances': non_zero_balances
                })
                accounts_with_balance += 1
            else:
                logger.info(Fore.YELLOW + "⚪ Нет активов с балансом")
        else:
            logger.info(Fore.RED + "❌ Ошибка получения баланса")
        
        # Получение списка субаккаунтов
        logger.info(Fore.CYAN + "📋 СУБАККАУНТЫ:")
        logger.info("-" * 50)
        
        subaccounts = client.get_subaccounts_list()
        
        if not subaccounts:
            logger.info(Fore.YELLOW + "⚠️ Субаккаунты не найдены")
        else:
            logger.info(Fore.GREEN + f"Найдено {len(subaccounts)} субаккаунтов")
            
            for i, subacct in enumerate(subaccounts, 1):
                email = subacct.get('email', 'Unknown')
                total_accounts += 1
                
                logger.info(Fore.CYAN + f"📊 [{i}/{len(subaccounts)}] {email}:")
                
                balance = client.get_subaccount_balance(email)
                
                if balance:
                    non_zero_balances = [b for b in balance if float(b.get('free', 0)) > 0]
                    if non_zero_balances:
                        logger.info(Fore.GREEN + f"   ✅ Найдено {len(non_zero_balances)} активов:")
                        for bal in non_zero_balances:
                            asset = bal.get('asset', 'Unknown')
                            amount = float(bal.get('free', 0))
                            
                            logger.info(f"      💰 {asset}: {amount:,.8f}")
                            
                        all_balances.append({
                            'account_name': email,
                            'account_type': 'subaccount',
                            'balances': non_zero_balances
                        })
                        accounts_with_balance += 1
                        subaccounts_with_balance.append(email)
                    else:
                        logger.info(Fore.YELLOW + "   ⚪ Нет активов с балансом")
                else:
                    logger.info(Fore.RED + "   ❌ Ошибка получения баланса")
                
                logger.info("")  # Пустая строка для разделения
                time.sleep(0.3)  # Пауза между запросами
        
        # ШАГ 2: АВТОМАТИЧЕСКИЙ СБОР СРЕДСТВ С СУБАККАУНТОВ
        if subaccounts_with_balance:
            logger.info(Fore.YELLOW + "🔄 ШАГ 2: АВТОМАТИЧЕСКИЙ СБОР СРЕДСТВ")
            logger.info(Fore.MAGENTA + "="*80)
            logger.info(Fore.YELLOW + f"🤖 Обнаружено {len(subaccounts_with_balance)} субаккаунтов с балансом")
            logger.info(Fore.YELLOW + "🤖 Запускаем автоматический сбор средств на основной аккаунт...")
            
            # Выполняем сбор средств
            client.collect_all_subaccount_balances()
            
            # ШАГ 3: ПОВТОРНАЯ ПРОВЕРКА БАЛАНСА ОСНОВНОГО АККАУНТА
            logger.info(Fore.YELLOW + "📊 ШАГ 3: ПОВТОРНАЯ ПРОВЕРКА ОСНОВНОГО АККАУНТА")
            logger.info(Fore.MAGENTA + "="*80)
            logger.info(Fore.CYAN + "📊 Проверка баланса основного аккаунта после сбора...")
            
            main_balance_after = client.get_main_account_balance()
            
            if main_balance_after:
                non_zero_balances_after = [b for b in main_balance_after if float(b.get('free', 0)) > 0 or float(b.get('locked', 0)) > 0]
                if non_zero_balances_after:
                    logger.info(Fore.GREEN + f"✅ Основной аккаунт после сбора - {len(non_zero_balances_after)} активов:")
                    for balance in non_zero_balances_after:
                        asset = balance.get('asset', 'Unknown')
                        free = float(balance.get('free', 0))
                        locked = float(balance.get('locked', 0))
                        total = free + locked
                        logger.info(f"   💰 {asset}: {total:,.8f}")
                        if locked > 0:
                            logger.info(f"      ├─ Свободно: {free:,.8f}")
                            logger.info(f"      └─ Заблокировано: {locked:,.8f}")
        else:
            logger.info(Fore.YELLOW + "⚠️ Нет субаккаунтов с балансом для сбора")
        
        # Сохранение результатов в CSV
        logger.info(Fore.CYAN + "💾 Сохранение результатов...")
        save_results_to_csv(all_balances)
        
        # Итоговая статистика
        logger.info(Fore.MAGENTA + "="*80)
        logger.info(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА BINANCE:")
        logger.info(Fore.CYAN + f"📈 Всего аккаунтов проверено: {total_accounts}")
        logger.info(Fore.GREEN + f"✅ Аккаунтов с балансом: {accounts_with_balance}")
        logger.info(Fore.RED + f"⚪ Пустых аккаунтов: {total_accounts - accounts_with_balance}")
        
        if all_balances:
            # Подсчет уникальных валют
            all_currencies = set()
            for account in all_balances:
                for balance in account['balances']:
                    all_currencies.add(balance.get('asset', 'Unknown'))
            logger.info(Fore.CYAN + f"💰 Найдено валют: {len(all_currencies)}")
            logger.info(Fore.CYAN + f"💰 Валюты: {', '.join(sorted(all_currencies))}")
        
        logger.info(Fore.GREEN + "💾 Результаты сохранены в result/binance_balances.csv")
        logger.info(Fore.MAGENTA + "="*80)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при проверке Binance: {e}")

def save_results_to_csv(all_balances):
    """Сохранение результатов в CSV файл"""
    try:
        result_dir = project_root / 'result'
        result_dir.mkdir(exist_ok=True)
        
        result_file = result_dir / 'binance_balances.csv'
        
        import csv
        with open(result_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Account Name', 'Account Type', 'Asset', 'Free', 'Locked', 'Total'])
            
            for account in all_balances:
                account_name = account['account_name']
                account_type = account['account_type']
                
                for balance in account['balances']:
                    asset = balance.get('asset', 'Unknown')
                    free = balance.get('free', '0')
                    locked = balance.get('locked', '0')
                    total = float(free) + float(locked)
                    
                    writer.writerow([
                        account_name,
                        account_type,
                        asset,
                        free,
                        locked,
                        total
                    ])
        
        logger.info(f"✅ Результаты сохранены в {result_file}")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения результатов: {e}")

def get_balances_binance():
    """
    Функция только для получения и отображения всех балансов Binance.
    Выводит в терминал и сохраняет в result/binance_balances.csv
    """
    _setup_logging()
    
    logger.info(Fore.MAGENTA + "="*80)
    logger.info(Fore.YELLOW + "📊 ПОЛУЧЕНИЕ БАЛАНСОВ BINANCE")
    logger.info(Fore.MAGENTA + "="*80)
    
    # Выбираем аккаунт Binance
    exchange_name, account = select_binance_account()
    if not account:
        logger.error("❌ Не выбран аккаунт Binance")
        return
    
    logger.info(f"🏢 Используется аккаунт: {account['name']}")
    
    # Используем выбранный аккаунт
    binance_api_key = account['api_key']
    secret_key = account['api_secret']
    
    # Проверяем настройки API
    if not all([binance_api_key, secret_key]):
        logger.error("❌ Не настроены API ключи Binance в выбранном аккаунте")
        return
    
    # Инициализация клиента
    client = BinanceClient(
        api_key=binance_api_key,
        secret_key=secret_key,
        testnet=False
    )
    
    all_balances = []
    total_accounts = 0
    accounts_with_balance = 0
    
    try:
        # === ОСНОВНОЙ АККАУНТ ===
        logger.info(Fore.CYAN + "📊 ОСНОВНОЙ АККАУНТ:")
        logger.info("-" * 50)
        
        main_balance = client.get_main_account_balance()
        total_accounts += 1
        
        if main_balance:
            non_zero_balances = [b for b in main_balance if float(b.get('free', 0)) > 0 or float(b.get('locked', 0)) > 0]
            if non_zero_balances:
                logger.info(Fore.GREEN + f"✅ Найдено {len(non_zero_balances)} активов:")
                for balance in non_zero_balances:
                    asset = balance.get('asset', 'Unknown')
                    free = float(balance.get('free', 0))
                    locked = float(balance.get('locked', 0))
                    total = free + locked
                    
                    logger.info(f"   💰 {asset}: {total:,.8f}")
                    if locked > 0:
                        logger.info(f"      ├─ Свободно: {free:,.8f}")
                        logger.info(f"      └─ Заблокировано: {locked:,.8f}")
                    
                all_balances.append({
                    'account_name': 'Main Account',
                    'account_type': 'main',
                    'balances': non_zero_balances
                })
                accounts_with_balance += 1
            else:
                logger.info(Fore.YELLOW + "⚪ Нет активов с балансом")
        else:
            logger.info(Fore.RED + "❌ Ошибка получения баланса")
        
        # === СУБАККАУНТЫ ===
        logger.info(Fore.CYAN + "📋 СУБАККАУНТЫ:")
        logger.info("-" * 50)
        
        subaccounts = client.get_subaccounts_list()
        
        if not subaccounts:
            logger.info(Fore.YELLOW + "⚠️ Субаккаунты не найдены")
        else:
            logger.info(Fore.GREEN + f"Найдено {len(subaccounts)} субаккаунтов")
            
            for i, subacct in enumerate(subaccounts, 1):
                email = subacct.get('email', 'Unknown')
                total_accounts += 1
                
                logger.info(Fore.CYAN + f"📊 [{i}/{len(subaccounts)}] {email}:")
                
                balance = client.get_subaccount_balance(email)
                
                if balance:
                    non_zero_balances = [b for b in balance if float(b.get('free', 0)) > 0]
                    if non_zero_balances:
                        logger.info(Fore.GREEN + f"   ✅ Найдено {len(non_zero_balances)} активов:")
                        for bal in non_zero_balances:
                            asset = bal.get('asset', 'Unknown')
                            amount = float(bal.get('free', 0))
                            
                            logger.info(f"      💰 {asset}: {amount:,.8f}")
                            
                        all_balances.append({
                            'account_name': email,
                            'account_type': 'subaccount',
                            'balances': non_zero_balances
                        })
                        accounts_with_balance += 1
                    else:
                        logger.info(Fore.YELLOW + "   ⚪ Нет активов с балансом")
                else:
                    logger.info(Fore.RED + "   ❌ Ошибка получения баланса")
                
                logger.info("")  # Пустая строка для разделения
                time.sleep(0.3)  # Пауза между запросами
        
        # === СОХРАНЕНИЕ РЕЗУЛЬТАТОВ ===
        logger.info(Fore.CYAN + "💾 Сохранение результатов...")
        save_results_to_csv(all_balances)
        
        # === ИТОГОВАЯ СТАТИСТИКА ===
        logger.info(Fore.MAGENTA + "="*80)
        logger.info(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА:")
        logger.info(Fore.CYAN + f"📈 Всего аккаунтов проверено: {total_accounts}")
        logger.info(Fore.GREEN + f"✅ Аккаунтов с балансом: {accounts_with_balance}")
        logger.info(Fore.RED + f"⚪ Пустых аккаунтов: {total_accounts - accounts_with_balance}")
        
        if all_balances:
            # Подсчет уникальных валют
            all_currencies = set()
            for account in all_balances:
                for balance in account['balances']:
                    all_currencies.add(balance.get('asset', 'Unknown'))
            logger.info(Fore.CYAN + f"💰 Всего активов: {len(all_currencies)}")
            logger.info(Fore.CYAN + f"💱 Уникальных валют: {len(all_currencies)}")
            logger.info(Fore.CYAN + f"💱 Валюты: {', '.join(sorted(all_currencies))}")
        
        result_file_path = project_root / 'result' / 'binance_balances.csv'
        logger.info(Fore.GREEN + f"💾 Результаты сохранены в {result_file_path}")
        logger.info(Fore.MAGENTA + "="*80)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при получении балансов Binance: {e}")


def subaccount_collector_binance():
    """
    Функция только для сбора средств с субаккаунтов на основной аккаунт Binance.
    """
    _setup_logging()
    
    logger.info(Fore.MAGENTA + "="*80)
    logger.info(Fore.YELLOW + "🤖 СБОРЩИК СРЕДСТВ С СУБАККАУНТОВ BINANCE")
    logger.info(Fore.MAGENTA + "="*80)
    
    # Выбираем аккаунт Binance
    exchange_name, account = select_binance_account()
    if not account:
        logger.error("❌ Не выбран аккаунт Binance")
        return
    
    logger.info(f"🏢 Используется аккаунт: {account['name']}")
    
    # Получаем данные аккаунта
    binance_api_key = account['api_key']
    secret_key = account['api_secret']
    
    # Проверяем настройки API
    if not all([binance_api_key, secret_key]):
        logger.error("❌ Не настроены API ключи Binance в выбранном аккаунте")
        return
    
    # Инициализация клиента
    client = BinanceClient(
        api_key=binance_api_key,
        secret_key=secret_key,
        testnet=False
    )
    
    try:
        # Проверяем баланс основного аккаунта ДО сбора
        logger.info(Fore.CYAN + "📊 БАЛАНС ОСНОВНОГО АККАУНТА ДО СБОРА:")
        logger.info("-" * 50)
        
        main_balance_before = client.get_main_account_balance()
        if main_balance_before:
            non_zero_balances_before = [b for b in main_balance_before if float(b.get('free', 0)) > 0 or float(b.get('locked', 0)) > 0]
            if non_zero_balances_before:
                logger.info(Fore.GREEN + f"✅ Найдено {len(non_zero_balances_before)} активов:")
                for balance in non_zero_balances_before:
                    asset = balance.get('asset', 'Unknown')
                    free = float(balance.get('free', 0))
                    locked = float(balance.get('locked', 0))
                    total = free + locked
                    logger.info(f"   💰 {asset}: {total:,.8f}")
            else:
                logger.info(Fore.YELLOW + "⚪ Нет активов с балансом")
        else:
            logger.info(Fore.RED + "❌ Ошибка получения баланса")
        
        # Запускаем сбор средств с субаккаунтов
        logger.info(Fore.YELLOW + "🔄 ЗАПУСК СБОРА СРЕДСТВ:")
        logger.info("-" * 50)
        
        client.collect_all_subaccount_balances()
        
        # Проверяем баланс основного аккаунта ПОСЛЕ сбора
        logger.info(Fore.CYAN + "📊 БАЛАНС ОСНОВНОГО АККАУНТА ПОСЛЕ СБОРА:")
        logger.info("-" * 50)
        
        main_balance_after = client.get_main_account_balance()
        if main_balance_after:
            non_zero_balances_after = [b for b in main_balance_after if float(b.get('free', 0)) > 0 or float(b.get('locked', 0)) > 0]
            if non_zero_balances_after:
                logger.info(Fore.GREEN + f"✅ Найдено {len(non_zero_balances_after)} активов:")
                for balance in non_zero_balances_after:
                    asset = balance.get('asset', 'Unknown')
                    free = float(balance.get('free', 0))
                    locked = float(balance.get('locked', 0))
                    total = free + locked
                    logger.info(f"   💰 {asset}: {total:,.8f}")
                    if locked > 0:
                        logger.info(f"      ├─ Свободно: {free:,.8f}")
                        logger.info(f"      └─ Заблокировано: {locked:,.8f}")
            else:
                logger.info(Fore.YELLOW + "⚪ Нет активов с балансом")
        else:
            logger.info(Fore.RED + "❌ Ошибка получения баланса")
        
        # Сравнение балансов ДО и ПОСЛЕ
        if main_balance_before and main_balance_after:
            logger.info(Fore.YELLOW + "📊 СРАВНЕНИЕ БАЛАНСОВ:")
            logger.info("-" * 50)
            
            # Создаем словари для удобного сравнения
            before_dict = {}
            for b in main_balance_before:
                asset = b.get('asset', 'Unknown')
                free = float(b.get('free', 0))
                locked = float(b.get('locked', 0))
                before_dict[asset] = free + locked
            
            after_dict = {}
            for b in main_balance_after:
                asset = b.get('asset', 'Unknown')
                free = float(b.get('free', 0))
                locked = float(b.get('locked', 0))
                after_dict[asset] = free + locked
            
            # Показываем изменения
            all_assets = set(before_dict.keys()) | set(after_dict.keys())
            changes_found = False
            
            for asset in sorted(all_assets):
                before_amount = before_dict.get(asset, 0)
                after_amount = after_dict.get(asset, 0)
                difference = after_amount - before_amount
                
                if abs(difference) > 0.00000001:  # Учитываем погрешности округления
                    changes_found = True
                    if difference > 0:
                        logger.info(Fore.GREEN + f"   📈 {asset}: +{difference:,.8f} (было: {before_amount:,.8f}, стало: {after_amount:,.8f})")
                    else:
                        logger.info(Fore.RED + f"   📉 {asset}: {difference:,.8f} (было: {before_amount:,.8f}, стало: {after_amount:,.8f})")
            
            if not changes_found:
                logger.info(Fore.YELLOW + "   ⚪ Изменений в балансе не обнаружено")
        
        logger.info(Fore.MAGENTA + "="*80)
        logger.info(Fore.GREEN + "✅ СБОР СРЕДСТВ ЗАВЕРШЕН")
        logger.info(Fore.MAGENTA + "="*80)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при сборе средств Binance: {e}")

