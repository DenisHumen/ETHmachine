import hmac
import hashlib
import base64
import json
import time
import requests
from datetime import datetime
from colorama import Fore, Style, init
from loguru import logger
import sys
from pathlib import Path

# Импорт селектора аккаунтов
from modules.cex.exchange_selector import select_okx_account

init()

# Настройка логгера - исправленные пути
project_root = Path(__file__).parent.parent.parent.parent
log_dir = project_root / 'log'
log_dir.mkdir(exist_ok=True)

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)

logger.add(
    log_dir / "okx_subaccount_errors.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="ERROR",
    rotation="10 MB",
    retention="7 days"
)

logger.add(
    log_dir / "okx_subaccount_full.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="50 MB",
    retention="3 days"
)

class OKXClient:
    def __init__(self, api_key, secret_key, passphrase, sandbox=False):
        """
        Инициализация клиента OKX
        
        Args:
            api_key: API ключ
            secret_key: Секретный ключ
            passphrase: Парольная фраза
            sandbox: Использовать sandbox окружение
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        
        if sandbox:
            self.base_url = "https://www.okx.com"  # Sandbox URL
        else:
            self.base_url = "https://www.okx.com"  # Production URL
        
        self.session = requests.Session()
        
    def _generate_signature(self, timestamp, method, request_path, body=''):
        """Генерация подписи для запроса"""
        message = timestamp + method + request_path + body
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf8'), 
            bytes(message, encoding='utf-8'), 
            digestmod=hashlib.sha256
        )
        d = mac.digest()
        return base64.b64encode(d).decode()

    def _get_headers(self, method, request_path, body=''):
        """Получение заголовков для запроса"""
        timestamp = datetime.utcnow().isoformat()[:-3] + 'Z'
        signature = self._generate_signature(timestamp, method, request_path, body)
        
        headers = {
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json'
        }
        return headers

    def _make_request(self, method, endpoint, params=None, data=None):
        """Выполнение запроса к API"""
        url = self.base_url + endpoint
        
        if params:
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            request_path = endpoint + '?' + query_string
        else:
            request_path = endpoint
            
        body = json.dumps(data) if data else ''
        headers = self._get_headers(method, request_path, body)
        
        try:
            if method == 'GET':
                response = self.session.get(url, headers=headers, params=params, timeout=30)
            elif method == 'POST':
                response = self.session.post(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Неподдерживаемый метод: {method}")
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка запроса к OKX API: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка декодирования JSON ответа: {e}")
            raise

    def get_subaccounts_list(self):
        """Получение списка субаккаунтов"""
        try:
            #logger.info("Получение списка субаккаунтов...")
            endpoint = "/api/v5/users/subaccount/list"
            response = self._make_request('GET', endpoint)
            
            if response.get('code') == '0':
                subaccounts = response.get('data', [])
                logger.info(f"Найдено {len(subaccounts)} субаккаунтов")
                return subaccounts
            else:
                logger.error(f"Ошибка получения субаккаунтов: {response.get('msg', 'Неизвестная ошибка')}")
                return []
                
        except Exception as e:
            logger.error(f"Исключение при получении субаккаунтов: {e}")
            return []

    def get_subaccount_balance(self, subacct_name):
        """Получение баланса конкретного субаккаунта"""
        try:
            endpoint = "/api/v5/asset/subaccount/balances"
            params = {'subAcct': subacct_name}
            
            response = self._make_request('GET', endpoint, params=params)
            
            if response.get('code') == '0':
                return response.get('data', [])
            else:
                logger.error(f"Ошибка получения баланса для {subacct_name}: {response.get('msg', 'Неизвестная ошибка')}")
                return []
                
        except Exception as e:
            logger.error(f"Исключение при получении баланса для {subacct_name}: {e}")
            return []

    def get_main_account_balance(self):
        """Получение баланса основного аккаунта"""
        try:
            endpoint = "/api/v5/asset/balances"
            response = self._make_request('GET', endpoint)
            
            if response.get('code') == '0':
                return response.get('data', [])
            else:
                logger.error(f"Ошибка получения баланса основного аккаунта: {response.get('msg', 'Неизвестная ошибка')}")
                return []
                
        except Exception as e:
            logger.error(f"Исключение при получении баланса основного аккаунта: {e}")
            return []

    def transfer_from_subaccount_to_main(self, subacct_name, currency, amount):
        """Перевод средств с субаккаунта на основной аккаунт"""
        try:
            endpoint = "/api/v5/asset/transfer"
            data = {
                'ccy': currency,
                'amt': str(amount),
                'from': '6',  # 6 = субаккаунт
                'to': '6',    # 6 = основной аккаунт  
                'type': '2',  # 2 = между основным и субаккаунтом
                'subAcct': subacct_name
            }
            
            response = self._make_request('POST', endpoint, data=data)
            
            if response.get('code') == '0':
                logger.info(f"✅ Успешно переведено {amount} {currency} с {subacct_name} на основной аккаунт")
                return True
            else:
                logger.error(f"❌ Ошибка перевода {amount} {currency} с {subacct_name}: {response.get('msg', 'Неизвестная ошибка')}")
                return False
                
        except Exception as e:
            logger.error(f"Исключение при переводе с {subacct_name}: {e}")
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
                subacct_name = subacct.get('subAcct', 'Unknown')
                logger.info(Fore.CYAN + f"📊 [{i}/{len(subaccounts)}] Проверка баланса для сбора: {subacct_name}")
                
                # Получение баланса субаккаунта
                balance = self.get_subaccount_balance(subacct_name)
                
                if balance:
                    # Фильтруем только ненулевые балансы
                    non_zero_balances = [b for b in balance if float(b.get('bal', 0)) > 0]
                    
                    if non_zero_balances:
                        logger.info(f"💰 Найдено {len(non_zero_balances)} активов для перевода")
                        
                        for bal in non_zero_balances:
                            currency = bal.get('ccy', 'Unknown')
                            amount = float(bal.get('bal', 0))
                            
                            if amount > 0:
                                logger.info(f"🔄 Переводим {amount} {currency} с {subacct_name}")
                                total_transfers += 1
                                
                                # Выполняем перевод
                                if self.transfer_from_subaccount_to_main(subacct_name, currency, amount):
                                    successful_transfers += 1
                                else:
                                    failed_transfers += 1
                                
                                # Пауза между переводами
                                time.sleep(1)
                    else:
                        logger.info(f"⚪ {subacct_name} - нет активов для перевода")
                else:
                    logger.info(f"❌ {subacct_name} - ошибка получения баланса")
                
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

def check_okx_subaccounts_and_balances():
    """Основная функция для проверки субаккаунтов и балансов OKX"""
    
    logger.info(Fore.MAGENTA + "="*80)
    logger.info(Fore.YELLOW + "🚀 Запуск проверки субаккаунтов и балансов OKX")
    logger.info(Fore.MAGENTA + "="*80)
    
    # Выбираем аккаунт OKX
    exchange_name, account = select_okx_account()
    if not account:
        logger.error("❌ Не выбран аккаунт OKX")
        return
    
    logger.info(f"🏢 Используется аккаунт: {account['name']}")
    
    # Получаем данные аккаунта
    api_key = account['api_key']
    api_secret = account['api_secret'] 
    passphrase = account['passphrase']
    
    # Проверяем настройки API
    if not all([api_key, api_secret, passphrase]):
        logger.error("❌ Не настроены API ключи OKX в выбранном аккаунте")
        return
    
    # Инициализация клиента
    client = OKXClient(
        api_key=api_key,
        secret_key=api_secret,
        passphrase=passphrase,
        sandbox=False  # Используем production
    )
    
    all_balances = []
    total_accounts = 0
    accounts_with_balance = 0
    
    try:
        # Получение баланса основного аккаунта
        logger.info(Fore.CYAN + "📊 Проверка баланса основного аккаунта...")
        main_balance = client.get_main_account_balance()
        
        if main_balance:
            non_zero_balances = [b for b in main_balance if float(b.get('bal', 0)) > 0]
            if non_zero_balances:
                logger.info(Fore.GREEN + f"✅ Основной аккаунт - найдено {len(non_zero_balances)} активов с балансом")
                for balance in non_zero_balances:
                    currency = balance.get('ccy', 'Unknown')
                    amount = float(balance.get('bal', 0))
                    logger.info(f"   💰 {currency}: {amount}")
                    
                all_balances.append({
                    'account_name': 'Main Account',
                    'account_type': 'main',
                    'balances': non_zero_balances
                })
                accounts_with_balance += 1
            else:
                logger.info(Fore.YELLOW + "⚠️ Основной аккаунт - нет активов с балансом")
        
        total_accounts += 1
        
        # Получение списка субаккаунтов
        logger.info(Fore.CYAN + "📋 Получение списка субаккаунтов...")
        subaccounts = client.get_subaccounts_list()
        
        if not subaccounts:
            logger.info(Fore.YELLOW + "⚠️ Субаккаунты не найдены")
        else:
            logger.info(Fore.GREEN + f"✅ Найдено {len(subaccounts)} субаккаунтов")
            
            # Проверка баланса каждого субаккаунта
            subaccounts_with_balance = []
            
            for i, subacct in enumerate(subaccounts, 1):
                subacct_name = subacct.get('subAcct', 'Unknown')
                logger.info(Fore.CYAN + f"📊 [{i}/{len(subaccounts)}] Проверка баланса: {subacct_name}")
                
                balance = client.get_subaccount_balance(subacct_name)
                total_accounts += 1
                
                if balance:
                    non_zero_balances = [b for b in balance if float(b.get('bal', 0)) > 0]
                    if non_zero_balances:
                        logger.info(Fore.GREEN + f"✅ {subacct_name} - найдено {len(non_zero_balances)} активов с балансом")
                        for bal in non_zero_balances:
                            currency = bal.get('ccy', 'Unknown')
                            amount = float(bal.get('bal', 0))
                            logger.info(f"   💰 {currency}: {amount}")
                            
                        all_balances.append({
                            'account_name': subacct_name,
                            'account_type': 'subaccount',
                            'balances': non_zero_balances
                        })
                        accounts_with_balance += 1
                        subaccounts_with_balance.append(subacct_name)
                    else:
                        logger.info(Fore.YELLOW + f"⚠️ {subacct_name} - нет активов с балансом")
                else:
                    logger.info(Fore.RED + f"❌ {subacct_name} - ошибка получения баланса")
                
                # Небольшая пауза между запросами
                time.sleep(0.5)
            
            # АВТОМАТИЧЕСКИЙ СБОР СРЕДСТВ С СУБАККАУНТОВ
            if subaccounts_with_balance:
                logger.info(Fore.YELLOW + f"🔄 Обнаружено {len(subaccounts_with_balance)} субаккаунтов с балансом")
                logger.info(Fore.YELLOW + "🤖 Запускаем автоматический сбор средств на основной аккаунт...")
                
                # Выполняем сбор средств
                client.collect_all_subaccount_balances()
                
                # Повторная проверка баланса основного аккаунта после сбора
                logger.info(Fore.CYAN + "📊 Повторная проверка баланса основного аккаунта после сбора...")
                main_balance_after = client.get_main_account_balance()
                
                if main_balance_after:
                    non_zero_balances_after = [b for b in main_balance_after if float(b.get('bal', 0)) > 0]
                    if non_zero_balances_after:
                        logger.info(Fore.GREEN + f"✅ Основной аккаунт после сбора - {len(non_zero_balances_after)} активов:")
                        for balance in non_zero_balances_after:
                            currency = balance.get('ccy', 'Unknown')
                            amount = float(balance.get('bal', 0))
                            logger.info(f"   💰 {currency}: {amount}")
        
        # Сохранение результатов в CSV
        logger.info(Fore.CYAN + "💾 Сохранение результатов...")
        save_results_to_csv(all_balances)
        
        # Итоговая статистика
        logger.info(Fore.MAGENTA + "="*80)
        logger.info(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА OKX:")
        logger.info(Fore.CYAN + f"📈 Всего аккаунтов проверено: {total_accounts}")
        logger.info(Fore.GREEN + f"✅ Аккаунтов с балансом: {accounts_with_balance}")
        logger.info(Fore.RED + f"⚪ Пустых аккаунтов: {total_accounts - accounts_with_balance}")
        
        if all_balances:
            # Подсчет уникальных валют
            all_currencies = set()
            for account in all_balances:
                for balance in account['balances']:
                    all_currencies.add(balance.get('ccy', 'Unknown'))
            logger.info(Fore.CYAN + f"💰 Найдено валют: {len(all_currencies)}")
            logger.info(Fore.CYAN + f"💰 Валюты: {', '.join(sorted(all_currencies))}")
        
        logger.info(Fore.GREEN + "💾 Результаты сохранены в result/okx_balances.csv")
        logger.info(Fore.MAGENTA + "="*80)
        
        # Отправка уведомления
        try:
            from modules.notifications import send_telegram_notification
            result_file_path = project_root / 'result' / 'okx_balances.csv'
            send_telegram_notification(
                notif_type="success",
                title="Проверка балансов OKX завершена",
                message=f"Всего аккаунтов: {total_accounts}С балансом: {accounts_with_balance}Пустых: {total_accounts - accounts_with_balance}",
                main_title="OKX баланс чек завершён",
                file_path=str(result_file_path)
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")
            
    except Exception as e:
        logger.error(f"Критическая ошибка при проверке OKX: {e}")

def save_results_to_csv(all_balances):
    """Сохранение результатов в CSV файл"""
    try:
        result_dir = project_root / 'result'
        result_dir.mkdir(exist_ok=True)
        
        result_file = result_dir / 'okx_balances.csv'
        
        import csv
        with open(result_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Account Name', 'Account Type', 'Currency', 'Balance', 'Available', 'Frozen'])
            
            for account in all_balances:
                account_name = account['account_name']
                account_type = account['account_type']
                
                for balance in account['balances']:
                    currency = balance.get('ccy', 'Unknown')
                    total_balance = balance.get('bal', '0')
                    available_balance = balance.get('availBal', '0')
                    frozen_balance = balance.get('frozenBal', '0')
                    
                    writer.writerow([
                        account_name,
                        account_type,
                        currency,
                        total_balance,
                        available_balance,
                        frozen_balance
                    ])
        
        logger.info(f"✅ Результаты сохранены в {result_file}")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения результатов: {e}")

def get_balances_okx():
    """
    Простая функция для получения всех балансов OKX.
    Выводит в терминал и сохраняет в result/okx_balances.csv
    """
    
    logger.info(Fore.MAGENTA + "" + "="*80)
    logger.info(Fore.YELLOW + "📊 ПОЛУЧЕНИЕ БАЛАНСОВ OKX")
    logger.info(Fore.MAGENTA + "="*80)
    
    # Выбираем аккаунт OKX
    exchange_name, account = select_okx_account()
    if not account:
        logger.error("❌ Не выбран аккаунт OKX")
        return
    
    logger.info(f"🏢 Используется аккаунт: {account['name']}")
    
    # Используем выбранный аккаунт
    api_key = account['api_key']
    api_secret = account['api_secret']
    passphrase = account['passphrase']
    
    # Проверяем настройки API
    if not all([api_key, api_secret, passphrase]):
        logger.error("❌ Не настроены API ключи OKX в выбранном аккаунте")
        return
    
    # Инициализация клиента
    client = OKXClient(
        api_key=api_key,
        secret_key=api_secret,
        passphrase=passphrase,
        sandbox=False
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
            non_zero_balances = [b for b in main_balance if float(b.get('bal', 0)) > 0]
            if non_zero_balances:
                logger.info(Fore.GREEN + f"✅ Найдено {len(non_zero_balances)} активов:")
                for balance in non_zero_balances:
                    currency = balance.get('ccy', 'Unknown')
                    amount = float(balance.get('bal', 0))
                    available = float(balance.get('availBal', 0))
                    frozen = float(balance.get('frozenBal', 0))
                    
                    logger.info(f"   💰 {currency}: {amount:,.8f}")
                    if available != amount:
                        logger.info(f"      ├─ Доступно: {available:,.8f}")
                    if frozen > 0:
                        logger.info(f"      └─ Заморожено: {frozen:,.8f}")
                    
                all_balances.append({
                    'account_name': 'Main Account',
                    'account_type': 'main',
                    'balances': non_zero_balances
                })
                accounts_with_balance += 1
            else:
                logger.info(Fore.YELLOW + "⚪ Нет активов с балансом")
        else:
            logger.info(Fore.RED + "❌ Ошибка получения баланса (вомозжно субаккаун пустой)")
        
        # === СУБАККАУНТЫ ===
        logger.info(Fore.CYAN + "📋 СУБАККАУНТЫ:")
        logger.info("-" * 50)
        
        subaccounts = client.get_subaccounts_list()
        
        if not subaccounts:
            logger.info(Fore.YELLOW + "⚠️ Субаккаунты не найдены")
        else:
            logger.info(Fore.GREEN + f"Найдено {len(subaccounts)} субаккаунтов")
            
            for i, subacct in enumerate(subaccounts, 1):
                subacct_name = subacct.get('subAcct', 'Unknown')
                total_accounts += 1
                
                logger.info(Fore.CYAN + f"📊 [{i}/{len(subaccounts)}] {subacct_name}:")
                
                balance = client.get_subaccount_balance(subacct_name)
                
                if balance:
                    non_zero_balances = [b for b in balance if float(b.get('bal', 0)) > 0]
                    if non_zero_balances:
                        logger.info(Fore.GREEN + f"   ✅ Найдено {len(non_zero_balances)} активов:")
                        for bal in non_zero_balances:
                            currency = bal.get('ccy', 'Unknown')
                            amount = float(bal.get('bal', 0))
                            available = float(bal.get('availBal', 0))
                            frozen = float(bal.get('frozenBal', 0))
                            
                            logger.info(f"      💰 {currency}: {amount:,.8f}")
                            if available != amount:
                                logger.info(f"         ├─ Доступно: {available:,.8f}")
                            if frozen > 0:
                                logger.info(f"         └─ Заморожено: {frozen:,.8f}")
                            
                        all_balances.append({
                            'account_name': subacct_name,
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
        logger.info(Fore.MAGENTA + "" + "="*80)
        logger.info(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА:")
        logger.info(Fore.CYAN + f"📈 Всего аккаунтов проверено: {total_accounts}")
        logger.info(Fore.GREEN + f"✅ Аккаунтов с балансом: {accounts_with_balance}")
        logger.info(Fore.RED + f"⚪ Пустых аккаунтов: {total_accounts - accounts_with_balance}")
        
        if all_balances:
            # Подсчет уникальных валют
            all_currencies = set()
            total_assets = 0
            for account in all_balances:
                for balance in account['balances']:
                    all_currencies.add(balance.get('ccy', 'Unknown'))
                    total_assets += 1
            
            logger.info(Fore.CYAN + f"💰 Всего активов: {total_assets}")
            logger.info(Fore.CYAN + f"💱 Уникальных валют: {len(all_currencies)}")
            logger.info(Fore.CYAN + f"💱 Валюты: {', '.join(sorted(all_currencies))}")
        
        result_file_path = project_root / 'result' / 'okx_balances.csv'
        logger.info(Fore.GREEN + f"💾 Результаты сохранены в {result_file_path}")
        logger.info(Fore.MAGENTA + "="*80 + "")
        
    except Exception as e:
        logger.error(f"Критическая ошибка при получении балансов OKX: {e}")

if __name__ == "__main__":
    # Можно вызвать напрямую для тестирования
    get_balances_okx()
