#!/usr/bin/env python3
"""
Модуль проверки конфигурации
Проверяет корректность всех настроек и файлов данных
"""

import os
import sys
from pathlib import Path
from loguru import logger

class ConfigValidator:
    """Валидатор конфигурации проекта"""
    
    def __init__(self, project_root=None):
        if project_root is None:
            self.project_root = Path(__file__).parent.parent
        else:
            self.project_root = Path(project_root)
        
        self.config_dir = self.project_root / "config"
        self.data_dir = self.project_root / "data"
        
        self.errors = []
        self.warnings = []
        
    def validate_all(self):
        """Выполнить полную проверку конфигурации"""
        logger.info("🔍 Начинаем проверку конфигурации...")
        
        self.check_config_files()
        self.check_cex_settings()
        self.check_data_files()
        
        self.show_results()
        return len(self.errors) == 0
    
    def check_config_files(self):
        """Проверка наличия и корректности конфигурационных файлов"""
        logger.debug("📋 Проверка конфигурационных файлов...")
        
        # Проверка config/config.py
        config_file = self.config_dir / "config.py"
        if not config_file.exists():
            self.errors.append("❌ Отсутствует файл config/config.py")
        else:
            self._validate_config_py(config_file)
        
        # Проверка config/cex_settings.py
        cex_settings_file = self.config_dir / "cex_settings.py"
        if not cex_settings_file.exists():
            self.errors.append("❌ Отсутствует файл config/cex_settings.py")
        else:
            logger.debug("✅ Файл config/cex_settings.py найден")
    
    def _validate_config_py(self, config_file):
        """Проверка содержимого config.py"""
        try:
            # Импортируем и проверяем основные настройки
            sys.path.insert(0, str(self.config_dir.parent))
            from config.config import (
                TYPE_WITHDRAW, VALUES_TO_WITHDRAW, 
                SLEEP_BETWEEN_ACTIONS, WAIT_FOR_BALANCE, 
                NUM_THREADS
            )
            
            # Проверки значений
            if TYPE_WITHDRAW not in [0, 1]:
                self.warnings.append("⚠️ TYPE_WITHDRAW должен быть 1 или 0")
            
            if not isinstance(VALUES_TO_WITHDRAW, list) or len(VALUES_TO_WITHDRAW) != 2:
                self.errors.append("❌ VALUES_TO_WITHDRAW должен быть списком из 2 элементов")
            
            if not isinstance(NUM_THREADS, int) or NUM_THREADS < 1:
                self.warnings.append("⚠️ NUM_THREADS должен быть положительным числом")
            
            logger.debug("✅ Файл config/config.py корректен")
            
        except ImportError as e:
            self.errors.append(f"❌ Ошибка импорта config/config.py: {e}")
        except Exception as e:
            self.errors.append(f"❌ Ошибка в config/config.py: {e}")
    
    def check_cex_settings(self):
        """Проверка настроек бирж"""
        logger.debug("🏢 Проверка настроек бирж...")
        
        try:
            sys.path.insert(0, str(self.config_dir.parent))
            from config.cex_settings import (
                OKX_ACCOUNTS, BINANCE_ACCOUNTS, 
                BITGET_ACCOUNTS, MEXC_ACCOUNTS
            )
            
            exchanges = {
                'OKX': OKX_ACCOUNTS,
                'Binance': BINANCE_ACCOUNTS,
                'Bitget': BITGET_ACCOUNTS,
                'MEXC': MEXC_ACCOUNTS,
            }
            
            total_configured = 0
            
            for exchange_name, accounts in exchanges.items():
                active_count = 0
                
                for account in accounts:
                    if not isinstance(account, dict):
                        self.errors.append(f"❌ Неверная структура аккаунта в {exchange_name}")
                        continue
                    
                    if account.get('enabled', False) and account.get('api_key'):
                        if self._validate_exchange_account(exchange_name, account):
                            active_count += 1
                            total_configured += 1
                
                if active_count > 0:
                    logger.debug(f"✅ {exchange_name}: {active_count} активных аккаунтов")
                else:
                    logger.debug(f"⚪ {exchange_name}: нет активных аккаунтов")
            
            if total_configured == 0:
                self.warnings.append("⚠️ Нет настроенных аккаунтов бирж! Добавьте API ключи в config/cex_settings.py")
            else:
                logger.info(f"✅ Найдено {total_configured} настроенных аккаунтов бирж")
                
        except ImportError as e:
            self.errors.append(f"❌ Ошибка импорта config/cex_settings.py: {e}")
        except Exception as e:
            self.errors.append(f"❌ Ошибка в config/cex_settings.py: {e}")
    
    def _validate_exchange_account(self, exchange_name, account):
        """Проверка отдельного аккаунта биржи"""
        required_fields = {
            'OKX': ['name', 'api_key', 'api_secret', 'passphrase'],
            'Binance': ['name', 'api_key', 'api_secret'],
            'Bitget': ['name', 'api_key', 'api_secret', 'passphrase'],
            'MEXC': ['name', 'api_key', 'api_secret'],
        }
        
        required = required_fields.get(exchange_name, ['name', 'api_key', 'api_secret'])
        
        for field in required:
            if not account.get(field):
                self.warnings.append(f"⚠️ {exchange_name} аккаунт '{account.get('name', 'Unnamed')}': пустое поле '{field}'")
                return False
        
        return True
    
    def check_data_files(self):
        """Проверка файлов данных"""
        logger.debug("📁 Проверка файлов данных...")
        
        data_files = {
            'proxy.csv': 'файл прокси',
            'walletss.txt': 'файл кошельков', 
            'private_keys.txt': 'файл приватных ключей'
        }
        
        for filename, description in data_files.items():
            file_path = self.data_dir / filename
            
            if not file_path.exists():
                self.warnings.append(f"⚠️ Отсутствует {description}: data/{filename}")
            else:
                # Проверяем, не пустой ли файл
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if not content:
                            self.warnings.append(f"⚠️ Пустой {description}: data/{filename}")
                        else:
                            lines = len([line for line in content.split('\n') if line.strip()])
                            logger.debug(f"✅ {description}: {lines} записей")
                except Exception as e:
                    self.warnings.append(f"⚠️ Ошибка чтения {description}: {e}")
    
    def show_results(self):
        """Показать результаты проверки"""
        print("\n" + "="*70)
        print("📊 РЕЗУЛЬТАТЫ ПРОВЕРКИ КОНФИГУРАЦИИ")
        print("="*70)
        
        if self.errors:
            print("🚨 КРИТИЧЕСКИЕ ОШИБКИ:")
            for error in self.errors:
                print(f"  {error}")
            print()
        
        if self.warnings:
            print("⚠️  ПРЕДУПРЕЖДЕНИЯ:")
            for warning in self.warnings:
                print(f"  {warning}")
            print()
        
        if not self.errors and not self.warnings:
            print("✅ Все проверки пройдены успешно!")
        elif not self.errors:
            print("✅ Критических ошибок не найдено")
            print("⚠️  Обратите внимание на предупреждения выше")
        else:
            print("❌ Найдены критические ошибки!")
            print("Исправьте их перед запуском скрипта")
        
        print("="*70)


def validate_configuration(project_root=None):
    """
    Основная функция для проверки конфигурации
    Возвращает True если нет критических ошибок
    """
    validator = ConfigValidator(project_root)
    return validator.validate_all()


if __name__ == "__main__":
    # Тест валидатора
    print("🧪 Тестирование валидатора конфигурации")
    is_valid = validate_configuration()
    
    if is_valid:
        print("\n✅ Конфигурация готова к работе!")
        sys.exit(0)
    else:
        print("\n❌ Конфигурация требует исправлений!")
        sys.exit(1)