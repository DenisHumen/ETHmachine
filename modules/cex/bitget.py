#!/usr/bin/env python3
# coding: utf-8
"""
Bitget сборщик балансов для стандартных субаккаунтов с виртуальным email.
Проверяет балансы и автоматически переводит средства на основной аккаунт.

Требования:
    pip install requests loguru colorama

Файл конфигурации: config/cex_settings.py
    bitget_api_key = 'your_api_key'
    bitget_api_secret = 'your_secret_key'
    bitget_passphrase = 'your_passphrase'
"""

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
import math

init()

# --- Project paths ---
project_root = Path(__file__).resolve().parent.parent.parent  # Поднимаемся до корня проекта
log_dir = project_root / 'log'  # Корневая директория log/
log_dir.mkdir(parents=True, exist_ok=True)

result_dir = project_root / 'result'
result_dir.mkdir(parents=True, exist_ok=True)

# --- Logger setup ---
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    log_dir / "bitget.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="ERROR",
    rotation="10 MB",
    retention="30 days"
)

# --- Configurable flags ---
AUTO_TRANSFER = False   # Если True — будет автоматически пытаться переводить найденные ненулевые балансы на 'main'
TRANSFER_MIN_AMOUNT = 1e-8  # Минимум для попытки перевода (в единицах монеты)
REQUEST_TIMEOUT = 30  # seconds
PAUSE_BETWEEN_REQUESTS = 0.5

class BitgetClient:
    def __init__(self, api_key, secret_key, passphrase, sandbox=False):
        """
        Инициализация клиента Bitget.

        Args:
            api_key (str)
            secret_key (str)
            passphrase (str)
            sandbox (bool)
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase

        # Production base
        self.base_url = "https://api.bitget.com"
        # If sandbox had different URL - можно добавить, но по умолчанию Bitget использует тот же хост.

        self.session = requests.Session()
        # Устанавливаем общие заголовки (Content-Type задаём в _get_headers)
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "BitgetBalanceCollector/1.0"
        })

    def _generate_signature(self, timestamp, method, request_path, body=''):
        """
        Генерация подписи по схеме Bitget: base64(hmac_sha256(secret, timestamp + method + path + body))
        timestamp должен быть строкой (миллисекунды).
        """
        sign_str = timestamp + method.upper() + request_path + body
        mac = hmac.new(self.secret_key.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(self, method, request_path, body=''):
        timestamp = str(time.time())  # секунды, а не миллисекунды
        signature = self._generate_signature(timestamp, method, request_path, body)
        return {
            'ACCESS-KEY': self.api_key,
            'ACCESS-SIGN': signature,
            'ACCESS-TIMESTAMP': timestamp,
            'ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json',
            'locale': 'en-US'
        }

    def _make_request(self, method, endpoint, params=None, data=None):
        """
        Универсальная обёртка для запросов. Логирует и бросает исключения при ошибках.
        method: 'GET'|'POST'
        endpoint: строка вида '/api/v2/....'
        params: dict -> query params
        data: dict -> будет сериализовано в json тело
        """
        url = self.base_url + endpoint

        # формируем request_path для подписи: endpoint + ?query (если есть)
        if params:
            # Важно: порядок параметров должен быть стабильным для подписи; сортируем по ключу.
            from urllib.parse import urlencode
            qs = urlencode(params, doseq=True)
            request_path = endpoint + '?' + qs
        else:
            request_path = endpoint

        body = json.dumps(data, separators=(',', ':')) if data else ''
        headers = self._get_headers(method, request_path, body)

        try:
            logger.debug(f"Отправляем {method} {url}")
            logger.debug(f"Request path for sign: {request_path}")
            logger.debug(f"Headers: {{'ACCESS-KEY': '{self.api_key[:6]}...', 'ACCESS-SIGN': '***', 'ACCESS-TIMESTAMP': '{headers.get('ACCESS-TIMESTAMP')}'}}")
            if body:
                logger.debug(f"Body: {body}")

            if method.upper() == 'GET':
                resp = self.session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            elif method.upper() == 'POST':
                resp = self.session.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
            else:
                raise ValueError("Unsupported HTTP method")

            logger.debug(f"Response status: {resp.status_code}")
            logger.debug(f"Response text: {resp.text}")

            # Raise for HTTP status codes >= 400
            resp.raise_for_status()
            # Try parse json
            try:
                return resp.json()
            except json.JSONDecodeError:
                raise RuntimeError("Response is not valid JSON")

        except requests.exceptions.HTTPError as e:
            # логируем текст ответа если он есть
            text = e.response.text if e.response is not None else 'No response body'
            logger.error(f"HTTPError: {e} | status={getattr(e.response, 'status_code', None)} | text={text}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"RequestException: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected exception during request: {e}")
            raise

    # --- Subaccounts list and balance (robust multi-endpoint attempts) ---
    def get_subaccounts_list(self):
        """
        Получение списка стандартных субаккаунтов через правильный API.
        Возвращает список нормализованных dict: {'subUid': str, 'subName': str, 'raw': <original>}
        """
        # Правильные эндпоинты для стандартных субаккаунтов
        endpoints = [
            # Основной эндпоинт для получения списка субаккаунтов
            ("/api/spot/v1/account/sub-account-spot-assets", {}),
            # Альтернативный эндпоинт
            ("/api/v2/spot/account/subaccount-assets", {}),
            # Список субаккаунтов (если доступен)
            ("/api/spot/v1/account/subAccount-list", {}),
        ]

        for endpoint, params in endpoints:
            try:
                logger.info(f"Пробуем endpoint для списка субаккаунтов: {endpoint}")
                resp = self._make_request('GET', endpoint, params=params)
                
                if not resp or isinstance(resp, str):
                    logger.debug(f"Endpoint {endpoint} вернул пустой ответ")
                    continue
                    
                # Проверяем успешность запроса
                if resp.get('code') == '00000' or resp.get('status') == 'ok':
                    data = resp.get('data') or []
                    
                    if not isinstance(data, list):
                        logger.debug(f"Endpoint {endpoint} вернул data не в виде списка: {type(data)}")
                        continue
                        
                    normalized = []

                    # Парсим разные форматы ответов
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                            
                        # Различные поля для идентификации субаккаунта
                        uid = str(item.get('userId') or item.get('subUid') or item.get('subaccountId') or item.get('id') or '')
                        name = (item.get('subaccountName') or 
                               item.get('subName') or 
                               item.get('email') or 
                               item.get('loginName') or 
                               f"sub_{uid}")
                        
                        if uid and uid != '0':
                            normalized.append({
                                'subUid': uid, 
                                'subName': name, 
                                'raw': item
                            })

                    if normalized:
                        logger.info(f"Найдено {len(normalized)} субаккаунтов через {endpoint}")
                        return normalized
                    else:
                        logger.debug(f"Endpoint {endpoint} не вернул валидных субаккаунтов")
                else:
                    logger.debug(f"Endpoint {endpoint} возвратил код: {resp.get('code') or resp.get('status')}")
                    
            except Exception as e:
                logger.warning(f"Ошибка при запросе {endpoint}: {e}")
                time.sleep(PAUSE_BETWEEN_REQUESTS)

        logger.info("⚠️ Субаккаунты не найдены через проверенные endpoints")
        return []

    def get_subaccount_balance(self, subacct_id):
        """
        Получение баланса стандартного субаккаунта.
        Возвращает список балансов в формате [{coin, available, frozen, ...}, ...] или [].
        """
        # Правильные эндпоинты для получения баланса стандартных субаккаунтов
        balance_endpoints = [
            # V1 API для spot активов субаккаунта
            ("/api/spot/v1/account/sub-account-spot-assets", {'subUid': subacct_id}),
            # V2 API альтернатива
            ("/api/v2/spot/account/subaccount-assets", {'subUid': subacct_id}),
            # Прямой запрос активов с параметром субаккаунта
            ("/api/spot/v1/account/assets", {'subUid': subacct_id}),
        ]
        
        for endpoint, params in balance_endpoints:
            try:
                logger.debug(f"Пробуем получить баланс через: {endpoint}")
                resp = self._make_request('GET', endpoint, params=params)
                
                if resp and (resp.get('code') == '00000' or resp.get('status') == 'ok'):
                    data = resp.get('data') or []
                    
                    # Если data это список активов
                    if isinstance(data, list):
                        # Фильтруем для конкретного субаккаунта
                        for item in data:
                            if not isinstance(item, dict):
                                continue
                                
                            item_uid = str(item.get('userId') or item.get('subUid') or '')
                            if item_uid == str(subacct_id):
                                assets = item.get('assetsList') or item.get('assets') or []
                                if assets:
                                    logger.debug(f"Найден баланс для {subacct_id}: {len(assets)} активов")
                                    return assets
                        
                        # Если не нашли по ID, возможно data уже содержит активы напрямую
                        if data and all(isinstance(item, dict) and ('coin' in item or 'currency' in item) for item in data):
                            logger.debug(f"Возвращаем data как список активов для {subacct_id}")
                            return data
                            
                    # Если data это объект с активами
                    elif isinstance(data, dict):
                        assets = data.get('assetsList') or data.get('assets') or []
                        if assets:
                            logger.debug(f"Найден баланс (объект) для {subacct_id}: {len(assets)} активов")
                            return assets
                            
                else:
                    logger.debug(f"Endpoint {endpoint} код: {resp.get('code') if resp else 'no_resp'}")
                    
            except Exception as e:
                logger.debug(f"Ошибка при запросе баланса {endpoint}: {e}")

        # Fallback: поиск через общий список всех субаккаунтов
        try:
            logger.debug(f"Fallback: поиск баланса {subacct_id} через общий список")
            resp = self._make_request('GET', '/api/spot/v1/account/sub-account-spot-assets', {})
            
            if resp and (resp.get('code') == '00000' or resp.get('status') == 'ok'):
                data = resp.get('data') or []
                if isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        uid = str(item.get('userId') or item.get('subUid') or '')
                        if uid == str(subacct_id):
                            assets = item.get('assetsList') or item.get('assets') or []
                            logger.debug(f"Fallback нашел баланс для {subacct_id}: {len(assets)} активов")
                            return assets
                            
        except Exception as e:
            logger.debug(f"Fallback ошибка: {e}")

        logger.warning(f"Не удалось получить баланс для субаккаунта {subacct_id}")
        return []

    def transfer_from_subaccount_to_main(self, subacct_id, currency, amount):
        """
        Перевод средств с субаккаунта на основной аккаунт.
        Использует правильные эндпоинты для стандартных субаккаунтов.
        """
        if float(amount) <= 0 or float(amount) < TRANSFER_MIN_AMOUNT:
            logger.warning(f"Сумма для перевода ({amount}) ниже минимальной отметки.")
            return False

        # Правильные эндпоинты для переводов со стандартных субаккаунтов
        transfer_endpoints = [
            # V1 API для переводов между субаккаунтами
            ("/api/spot/v1/account/sub-account-transfer", {
                "fromType": "spot",
                "toType": "spot",
                "amount": str(amount),
                "coin": currency,
                "fromUserId": str(subacct_id),
                "clientOid": str(int(time.time() * 1000))
            }),
            # V2 API альтернатива
            ("/api/v2/spot/wallet/subaccount-transfer", {
                "coin": currency,
                "amount": str(amount),
                "fromType": "spot", 
                "toType": "spot",
                "subUid": str(subacct_id),
                "clientOid": str(int(time.time() * 1000))
            }),
            # Прямой transfer API
            ("/api/spot/v1/wallet/transfer", {
                "fromType": "spot",
                "toType": "spot",
                "amount": str(amount),
                "coin": currency,
                "fromAccount": str(subacct_id),
                "toAccount": "main",
                "clientOid": str(int(time.time() * 1000))
            }),
        ]

        for endpoint, payload in transfer_endpoints:
            try:
                logger.info(f"Пытаемся перевод через {endpoint}: {amount} {currency} с {subacct_id}")
                resp = self._make_request('POST', endpoint, data=payload)
                
                if resp and (resp.get('code') == '00000' or resp.get('status') == 'ok'):
                    logger.info(f"✅ Успешно переведено {amount} {currency} с {subacct_id}")
                    return True
                else:
                    error_msg = resp.get('msg') or resp.get('message') or 'Unknown error'
                    logger.warning(f"Endpoint {endpoint} ошибка: {error_msg}")
                    
            except Exception as e:
                logger.warning(f"Перевод через {endpoint} не удался: {e}")
            
            time.sleep(1)  # пауза между попытками

        logger.error(f"❌ Не удалось выполнить перевод {amount} {currency} с {subacct_id}")
        return False

    # --- Transfer with fallback attempts ---
    def transfer_from_subaccount_to_main_old(self, subacct_id, currency, amount):
        """
        Пытается выполнить перевод с субаккаунта на основной аккаунт.
        Попробует несколько эндпоинтов в зависимости от типа аккаунта.
        Возвращает True при успехе, False иначе.
        """
        if float(amount) <= 0 or float(amount) < TRANSFER_MIN_AMOUNT:
            logger.warning(f"Сумма для перевода ({amount}) ниже минимальной отметки.")
            return False

        attempts = [
            # Standard subaccount transfer
            ("/api/v2/spot/wallet/transfer", {
                "fromType": "spot",
                "toType": "spot", 
                "amount": str(amount),
                "coin": currency,
                "fromAccount": "subaccount",
                "toAccount": "spot",
                "subUid": str(subacct_id)
            }),
            # Alternative standard transfer
            ("/api/v2/spot/account/subaccount-transfer", {
                "fromType": "spot",
                "toType": "spot",
                "amount": str(amount),
                "coin": currency,
                "fromUserId": str(subacct_id)
            }),
        ]

        for endpoint, payload in attempts:
            try:
                logger.info(f"Пытаемся перевод через {endpoint}: {amount} {currency} с {subacct_id} -> main")
                resp = self._make_request('POST', endpoint, data=payload)
                if resp and resp.get('code') == '00000':
                    logger.info(f"✅ Успешно переведено {amount} {currency} с {subacct_id} через {endpoint}")
                    return True
                else:
                    logger.warning(f"Endpoint {endpoint} вернул код {resp.get('code') if resp else 'no_resp'} msg: {resp.get('msg') if resp else 'no_msg'}")
            except Exception as e:
                logger.warning(f"Перевод через {endpoint} не удался: {e}")
            time.sleep(0.8)

        logger.error(f"❌ Не удалось выполнить перевод {amount} {currency} с {subacct_id} на main")
        return False

    def get_main_account_balance(self):
        """
        Получение баланса основного аккаунта (spot assets)
        """
        endpoint = "/api/v2/spot/account/assets"
        try:
            resp = self._make_request('GET', endpoint, params={'limit': 200})
            if resp and resp.get('code') == '00000':
                return resp.get('data') or []
            else:
                logger.error(f"Endpoint {endpoint} вернул code {resp.get('code') if resp else 'no_resp'} msg: {resp.get('msg') if resp else 'no_msg'}")
                return []
        except Exception as e:
            logger.error(f"Исключение при получении баланса основного аккаунта: {e}")
            return []

    # --- Helper: mask sensitive strings for logging ---
    @staticmethod
    def mask_secret(value, left=4, right=4):
        if not value:
            return ''
        if len(value) <= left + right:
            return '*' * len(value)
        return value[:left] + ('*' * (len(value) - left - right)) + value[-right:]

# --- Utility functions ---
def save_results_to_csv(all_balances):
    try:
        import csv
        result_file = result_dir / 'bitget_balances.csv'
        with open(result_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Account Name', 'Account Type', 'Currency', 'Available', 'Frozen', 'Total'])
            for account in all_balances:
                account_name = account.get('account_name', 'Unknown')
                account_type = account.get('account_type', 'Unknown')
                for balance in account.get('balances', []):
                    currency = balance.get('coin') or balance.get('currency') or balance.get('symbol') or 'Unknown'
                    available = balance.get('available', balance.get('availableBalance', '0'))
                    frozen = balance.get('frozen', balance.get('frozenBalance', '0'))
                    try:
                        total = float(available) + float(frozen)
                    except Exception:
                        total = available
                    writer.writerow([account_name, account_type, currency, available, frozen, total])
        logger.info(f"✅ Результаты сохранены в {result_file}")
    except Exception as e:
        logger.error(f"Ошибка сохранения результатов: {e}")

def pretty_float_str(x):
    try:
        fx = float(x)
        if math.isfinite(fx):
            # форматируем с 8 десятичными если <1, иначе до 6
            if abs(fx) < 1:
                return f"{fx:.8f}"
            return f"{fx:.6f}"
        return str(x)
    except Exception:
        return str(x)

# --- Main process ---
def check_bitget_subaccounts_and_balances(auto_transfer=True):  # Включаем автоперевод по умолчанию
    logger.info(Fore.MAGENTA + "\n" + "="*80)
    logger.info(Fore.YELLOW + "🚀 Запуск проверки стандартных субаккаунтов Bitget")
    logger.info(Fore.MAGENTA + "="*80)

    # Загружаем ключи
    try:
        from config.cex_settings import bitget_api_key, bitget_api_secret, bitget_passphrase
        if not all([bitget_api_key, bitget_api_secret, bitget_passphrase]):
            logger.error("❌ Не настроены API ключи Bitget в config/cex_settings.py")
            return
    except ImportError:
        logger.error("❌ Не найден файл config/cex_settings.py или переменные не заданы")
        return

    logger.info(f"🔑 API key: {bitget_api_key[:8]}...")
    logger.info(f"🔐 Secret: {BitgetClient.mask_secret(bitget_api_secret)}")
    logger.info(f"🗝️ Passphrase: {bitget_passphrase[:3]}...")
    logger.info(f"🔄 Автоперевод: {'ВКЛЮЧЕН' if auto_transfer else 'ВЫКЛЮЧЕН'}")

    client = BitgetClient(bitget_api_key, bitget_api_secret, bitget_passphrase, sandbox=False)

    all_balances = []
    total_accounts = 0
    accounts_with_balance = 0

    # --- Основной аккаунт (пропускаем, фокус только на субаккаунтах) ---
    
    # --- Субаккаунты ---
    logger.info(Fore.CYAN + "📋 Получение списка стандартных субаккаунтов...")
    subaccounts = client.get_subaccounts_list()
    time.sleep(PAUSE_BETWEEN_REQUESTS)

    if not subaccounts:
        logger.info(Fore.YELLOW + "⚠️ Стандартные субаккаунты не найдены")
        return
    
    logger.info(Fore.GREEN + f"✅ Найдено {len(subaccounts)} стандартных субаккаунтов")
    
    for i, sub in enumerate(subaccounts, start=1):
        sub_uid = sub.get('subUid') or ''
        sub_name = sub.get('subName') or f"sub_{sub_uid}"
        logger.info(Fore.CYAN + f"📊 [{i}/{len(subaccounts)}] Проверка: {sub_name} (ID: {sub_uid})")
        total_accounts += 1

        bal = client.get_subaccount_balance(sub_uid)
        time.sleep(PAUSE_BETWEEN_REQUESTS)

        if bal:
            # Фильтруем активы с ненулевым балансом
            non_zero = []
            for b in bal:
                available = float(b.get('available', 0) or 0)
                frozen = float(b.get('frozen', 0) or 0)
                if available > 0 or frozen > 0:
                    non_zero.append(b)
            
            if non_zero:
                logger.info(Fore.GREEN + f"✅ {sub_name} - найдено {len(non_zero)} активов с балансом")
                for b in non_zero:
                    coin = b.get('coin') or b.get('currency') or 'Unknown'
                    available = pretty_float_str(b.get('available', 0))
                    frozen = pretty_float_str(b.get('frozen', 0))
                    logger.info(f"   💰 {coin}: доступно {available}, заморожено {frozen}")
                    
                all_balances.append({
                    'account_name': sub_name, 
                    'account_type': 'subaccount', 
                    'balances': non_zero
                })
                accounts_with_balance += 1

                # Автоматический перевод средств
                if auto_transfer:
                    logger.info(Fore.YELLOW + f"🔄 Запускаем автоматический перевод с {sub_name}")
                    for b in non_zero:
                        coin = b.get('coin') or b.get('currency') or 'Unknown'
                        available = float(b.get('available', 0) or 0)
                        
                        if available > TRANSFER_MIN_AMOUNT:
                            logger.info(f"Переводим {available} {coin} с {sub_name} на основной аккаунт...")
                            success = client.transfer_from_subaccount_to_main(sub_uid, coin, available)
                            if success:
                                logger.info(Fore.GREEN + f"✅ Перевод {coin} {pretty_float_str(available)} - УСПЕШНО")
                            else:
                                logger.error(Fore.RED + f"❌ Перевод {coin} {pretty_float_str(available)} - ОШИБКА")
                            time.sleep(2)  # пауза между переводами
                        else:
                            logger.info(f"Сумма {available} {coin} слишком мала для перевода")
            else:
                logger.info(Fore.YELLOW + f"⚪ {sub_name} - нет активов с балансом")
        else:
            logger.error(Fore.RED + f"❌ {sub_name} - ошибка получения баланса")

    # Сохранение результатов
    logger.info(Fore.CYAN + "\n💾 Сохранение результатов...")
    save_results_to_csv(all_balances)

    # Итоговая статистика
    logger.info(Fore.MAGENTA + "\n" + "="*80)
    logger.info(Fore.YELLOW + "📊 ИТОГОВАЯ СТАТИСТИКА BITGET СУБАККАУНТОВ:")
    logger.info(Fore.CYAN + f"📈 Всего субаккаунтов проверено: {total_accounts}")
    logger.info(Fore.GREEN + f"✅ Субаккаунтов с балансом: {accounts_with_balance}")
    logger.info(Fore.RED + f"⚪ Пустых субаккаунтов: {total_accounts - accounts_with_balance}")

    if all_balances:
        all_currencies = set()
        for acc in all_balances:
            for bal in acc['balances']:
                all_currencies.add(bal.get('coin') or bal.get('currency') or 'Unknown')
        logger.info(Fore.CYAN + f"💰 Найдено валют: {len(all_currencies)}")
        logger.info(Fore.CYAN + f"💰 Валюты: {', '.join(sorted(all_currencies))}")

    logger.info(Fore.GREEN + f"💾 Результаты сохранены в {result_dir / 'bitget_balances.csv'}")
    logger.info(Fore.MAGENTA + "="*80 + "\n")

if __name__ == "__main__":
    check_bitget_subaccounts_and_balances()
