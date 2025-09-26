#!/usr/bin/env python3
"""
Модуль для выбора аккаунта биржи
Позволяет выбрать из настроенных аккаунтов через questionary
Обновлено для работы из директории modules/cex
"""

import sys
import os
from questionary import Choice, select
from loguru import logger

# Добавляем корневую директорию проекта в sys.path
project_root = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, project_root)


def _get_cex_settings():
    """Получить настройки бирж с обработкой ошибок"""
    try:
        from config.cex_settings import (
            OKX_ACCOUNTS, BINANCE_ACCOUNTS, 
            BITGET_ACCOUNTS, MEXC_ACCOUNTS
        )
        return OKX_ACCOUNTS, BINANCE_ACCOUNTS, BITGET_ACCOUNTS, MEXC_ACCOUNTS
    except ImportError as e:
        logger.error(f"Ошибка импорта настроек бирж: {e}")
        logger.error("Убедитесь, что файл config/cex_settings.py создан. Запустите main.py для автоматического создания.")
        return [], [], [], []
    except Exception as e:
        logger.error(f"Ошибка в настройках бирж: {e}")
        return [], [], [], []


class ExchangeSelector:
    """Класс для выбора биржи и аккаунта"""
    
    def __init__(self, specific_exchange=None):
        """
        Инициализация селектора
        
        Args:
            specific_exchange (str): Если указано, работает только с этой биржей
                                   Возможные значения: 'OKX', 'Binance', 'Bitget', 'MEXC'
        """
        # Получаем настройки бирж через безопасную функцию
        OKX_ACCOUNTS, BINANCE_ACCOUNTS, BITGET_ACCOUNTS, MEXC_ACCOUNTS = _get_cex_settings()
        
        self.exchanges = {
            'OKX': OKX_ACCOUNTS,
            'Binance': BINANCE_ACCOUNTS,
            'Bitget': BITGET_ACCOUNTS,
            'MEXC': MEXC_ACCOUNTS,
        }
        self.specific_exchange = specific_exchange
    
    def get_available_exchanges(self):
        """Получить список бирж с активными аккаунтами"""
        available = {}
        
        # Если указана конкретная биржа, работаем только с ней
        if self.specific_exchange:
            if self.specific_exchange not in self.exchanges:
                logger.error(f"Неизвестная биржа: {self.specific_exchange}")
                return {}
            
            accounts = self.exchanges[self.specific_exchange]
            active_accounts = [acc for acc in accounts if acc.get('enabled', False) and acc.get('api_key')]
            if active_accounts:
                available[self.specific_exchange] = active_accounts
            return available
        
        # Иначе проверяем все биржи
        for exchange_name, accounts in self.exchanges.items():
            active_accounts = [acc for acc in accounts if acc.get('enabled', False) and acc.get('api_key')]
            if active_accounts:
                available[exchange_name] = active_accounts
        return available
    
    def select_exchange(self):
        """Выбрать биржу из доступных"""
        available_exchanges = self.get_available_exchanges()
        
        if not available_exchanges:
            if self.specific_exchange:
                logger.error(f"❌ Нет настроенных аккаунтов для биржи {self.specific_exchange}!")
                logger.info(f"Настройте хотя бы один аккаунт для {self.specific_exchange} в config/cex_settings.py")
            else:
                logger.error("❌ Нет настроенных аккаунтов бирж!")
                logger.info("Настройте хотя бы один аккаунт в config/cex_settings.py")
            return None, None
        
        # Если указана конкретная биржа, используем её
        if self.specific_exchange:
            if self.specific_exchange in available_exchanges:
                logger.info(f"🔄 Используется биржа: {self.specific_exchange}")
                return self.specific_exchange, self.select_account(self.specific_exchange)
            else:
                return None, None
        
        # Если только одна биржа доступна
        if len(available_exchanges) == 1:
            exchange_name = list(available_exchanges.keys())[0]
            logger.info(f"🔄 Автоматически выбрана биржа: {exchange_name}")
            return exchange_name, self.select_account(exchange_name)
        
        # Выбор из нескольких бирж
        choices = [
            Choice(f"🏢 {name} ({len(accounts)} аккаунтов)", name)
            for name, accounts in available_exchanges.items()
        ]
        
        selected_exchange = select(
            "🏛️ Выберите биржу для работы:",
            choices=choices
        ).ask()
        
        if not selected_exchange:
            return None, None
            
        return selected_exchange, self.select_account(selected_exchange)
    
    def select_account(self, exchange_name):
        """Выбрать аккаунт конкретной биржи"""
        if exchange_name not in self.exchanges:
            logger.error(f"Неизвестная биржа: {exchange_name}")
            return None
        
        accounts = self.exchanges[exchange_name]
        active_accounts = [acc for acc in accounts if acc.get('enabled', False) and acc.get('api_key')]
        
        if not active_accounts:
            logger.error(f"❌ Нет активных аккаунтов для {exchange_name}")
            return None
        
        if len(active_accounts) == 1:
            selected_account = active_accounts[0]
            logger.info(f"🔄 Автоматически выбран аккаунт: {selected_account['name']}")
            return selected_account
        
        choices = [
            Choice(f"👤 {account['name']}", account)
            for account in active_accounts
        ]
        
        selected_account = select(
            f"👤 Выберите аккаунт {exchange_name}:",
            choices=choices
        ).ask()
        
        return selected_account
    
    def get_account_info(self, exchange_name, account):
        """Получить информацию об аккаунте для логирования"""
        if not account:
            return "Аккаунт не выбран"
        
        api_key_preview = account['api_key'][:8] + "..." if account.get('api_key') else "Не задан"
        return f"{exchange_name}: {account['name']} (API: {api_key_preview})"


def select_exchange_account(specific_exchange=None):
    """
    Основная функция для выбора биржи и аккаунта
    
    Args:
        specific_exchange (str): Если указано, работает только с этой биржей
        
    Returns:
        tuple: (exchange_name, account_dict) или (None, None)
    """
    selector = ExchangeSelector(specific_exchange=specific_exchange)
    exchange_name, account = selector.select_exchange()
    
    if exchange_name and account:
        logger.success(f"✅ Выбрана биржа: {selector.get_account_info(exchange_name, account)}")
        return exchange_name, account
    else:
        logger.error("❌ Биржа не выбрана")
        return None, None


def select_okx_account():
    """Выбрать аккаунт OKX"""
    return select_exchange_account(specific_exchange='OKX')


def select_binance_account():
    """Выбрать аккаунт Binance"""
    return select_exchange_account(specific_exchange='Binance')


def select_bitget_account():
    """Выбрать аккаунт Bitget"""
    return select_exchange_account(specific_exchange='Bitget')


def select_mexc_account():
    """Выбрать аккаунт MEXC"""
    return select_exchange_account(specific_exchange='MEXC')


def get_exchange_module_path(exchange_name):
    """Получить путь к модулю биржи"""
    exchange_paths = {
        'OKX': 'modules.cex.okx',
        'Binance': 'modules.cex.binance', 
        'Bitget': 'modules.cex.bitget',
        'MEXC': 'modules.cex.mexc',
    }
    return exchange_paths.get(exchange_name)


if __name__ == "__main__":
    # Тест модуля
    print("🧪 Тестирование модуля выбора биржи")
    
    # Тест общего выбора
    print("\n1. Общий выбор:")
    exchange, account = select_exchange_account()
    if exchange and account:
        print(f"Выбрано: {exchange} - {account['name']}")
    
    # Тест специфических бирж
    print("\n2. Тест OKX:")
    exchange, account = select_okx_account()
    if exchange and account:
        print(f"OKX: {account['name']}")
    
    print("\n3. Тест Binance:")
    exchange, account = select_binance_account()
    if exchange and account:
        print(f"Binance: {account['name']}")