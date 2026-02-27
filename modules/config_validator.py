#!/usr/bin/env python3
"""
Модуль проверки конфигурации
Проверяет корректность всех настроек и файлов данных
"""

import sys
import re
import csv
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
        self.check_config_files()
        self.check_cex_settings()
        self.check_data_files()
        
        self.show_results()
        return len(self.errors) == 0
    
    def check_config_files(self):
        """Проверка наличия и корректности конфигурационных файлов"""
        logger.debug("📋 Проверка конфигурационных файлов...")
        
        
        cex_settings_file = self.config_dir / "cex_settings.py"
        if not cex_settings_file.exists():
            self.errors.append("❌ Отсутствует файл config/cex_settings.py")
        else:
            logger.debug("✅ Файл config/cex_settings.py найден")
    
    def _validate_config_py(self, config_file):
        """Проверка содержимого config.py"""
        try:
            sys.path.insert(0, str(self.config_dir.parent))
            from config.modules.cfg_cex import (
                TYPE_WITHDRAW, VALUES_TO_WITHDRAW, WAIT_FOR_BALANCE
            )
            from config.modules.cfg_base import (
                SLEEP_BETWEEN_ACTIONS, NUM_THREADS
            )
            
            try:
                from config.modules.cfg_generators import NICKNAME_GENERATOR
                nickname_generator_exists = True
            except ImportError:
                nickname_generator_exists = False
                self.warnings.append("⚠️ NICKNAME_GENERATOR не найден в конфиге (добавьте настройки для генератора никнеймов)")
            
            try:
                from config.modules.cfg_twitter import RANDOM_PROXIES_TWITTER
                if not isinstance(RANDOM_PROXIES_TWITTER, bool):
                    self.warnings.append("⚠️ RANDOM_PROXIES_TWITTER должен быть True или False")
            except ImportError:
                self.warnings.append("⚠️ RANDOM_PROXIES_TWITTER не найден в конфиге (добавьте для использования рандомных прокси в Twitter)")
            
            try:
                from config.modules.cfg_backup import SFTP_SERVER_INTO_BACKUP_ENABLE, SFTP_SERVER_INTO_BACKUP
                self._validate_sftp_config(SFTP_SERVER_INTO_BACKUP_ENABLE, SFTP_SERVER_INTO_BACKUP)
            except ImportError:
                self.warnings.append("⚠️ Настройки SFTP бэкапа не найдены в конфиге (добавьте SFTP_SERVER_INTO_BACKUP_ENABLE и SFTP_SERVER_INTO_BACKUP)")
            
            if TYPE_WITHDRAW not in [0, 1]:
                self.warnings.append("⚠️ TYPE_WITHDRAW должен быть 1 или 0")
            
            if not isinstance(VALUES_TO_WITHDRAW, list) or len(VALUES_TO_WITHDRAW) != 2:
                self.errors.append("❌ VALUES_TO_WITHDRAW должен быть списком из 2 элементов")
            
            if not isinstance(NUM_THREADS, int) or NUM_THREADS < 1:
                self.warnings.append("⚠️ NUM_THREADS должен быть положительным числом")
            
            if nickname_generator_exists:
                self._validate_nickname_generator(NICKNAME_GENERATOR)
            
            logger.debug("✅ Файл config/config.py корректен")
            
        except ImportError as e:
            self.errors.append(f"❌ Ошибка импорта config/config.py: {e}")
        except Exception as e:
            self.errors.append(f"❌ Ошибка в config/config.py: {e}")
    
    def _validate_nickname_generator(self, config):
        """Проверка настроек генератора никнеймов"""
        if not isinstance(config, dict):
            self.errors.append("❌ NICKNAME_GENERATOR должен быть словарем")
            return
        
        min_length = config.get('MIN_LENGTH')
        if min_length is None or min_length == '':
            self.errors.append("❌ NICKNAME_GENERATOR['MIN_LENGTH'] не может быть пустым")
        elif not isinstance(min_length, int) or min_length < 1:
            self.errors.append("❌ NICKNAME_GENERATOR['MIN_LENGTH'] должен быть положительным числом")
        elif min_length < 3:
            self.warnings.append("⚠️ NICKNAME_GENERATOR['MIN_LENGTH'] слишком мал (рекомендуется >= 3)")
        elif min_length > 20:
            self.warnings.append("⚠️ NICKNAME_GENERATOR['MIN_LENGTH'] слишком большой (рекомендуется <= 20)")
        
        max_length = config.get('MAX_LENGTH')
        if max_length is None or max_length == '':
            self.errors.append("❌ NICKNAME_GENERATOR['MAX_LENGTH'] не может быть пустым")
        elif not isinstance(max_length, int) or max_length < 1:
            self.errors.append("❌ NICKNAME_GENERATOR['MAX_LENGTH'] должен быть положительным числом")
        elif max_length > 50:
            self.warnings.append("⚠️ NICKNAME_GENERATOR['MAX_LENGTH'] слишком большой (рекомендуется <= 50)")
        
        if isinstance(min_length, int) and isinstance(max_length, int):
            if min_length > max_length:
                self.errors.append("❌ NICKNAME_GENERATOR['MIN_LENGTH'] не может быть больше MAX_LENGTH")
            elif max_length - min_length > 30:
                self.warnings.append("⚠️ Слишком большой диапазон длины никнеймов (рекомендуется <= 30)")
        
        use_special = config.get('USE_SPECIAL_CHARS')
        if use_special is None or use_special == '':
            self.errors.append("❌ NICKNAME_GENERATOR['USE_SPECIAL_CHARS'] не может быть пустым")
        elif not isinstance(use_special, bool):
            self.errors.append("❌ NICKNAME_GENERATOR['USE_SPECIAL_CHARS'] должен быть True или False")
        
        quantity = config.get('QUANTITY')
        if quantity is None or quantity == '':
            self.errors.append("❌ NICKNAME_GENERATOR['QUANTITY'] не может быть пустым")
        elif not isinstance(quantity, int) or quantity < 1:
            self.errors.append("❌ NICKNAME_GENERATOR['QUANTITY'] должен быть положительным числом")
        elif quantity > 100000:
            self.warnings.append("⚠️ NICKNAME_GENERATOR['QUANTITY'] очень большой (может занять много времени)")
        elif quantity < 1:
            self.warnings.append("⚠️ NICKNAME_GENERATOR['QUANTITY'] слишком мал (рекомендуется >= 1)")
        
        use_numbers = config.get('USE_NUMBERS')
        if use_numbers is not None and not isinstance(use_numbers, bool):
            self.errors.append("❌ NICKNAME_GENERATOR['USE_NUMBERS'] должен быть True или False")
        
        if use_numbers:
            min_numbers = config.get('MIN_NUMBERS')
            if min_numbers is not None:
                if not isinstance(min_numbers, int) or min_numbers < 0:
                    self.errors.append("❌ NICKNAME_GENERATOR['MIN_NUMBERS'] должен быть неотрицательным числом")
                elif min_numbers > 5:
                    self.warnings.append("⚠️ NICKNAME_GENERATOR['MIN_NUMBERS'] слишком большой (рекомендуется <= 5)")
            
            max_numbers = config.get('MAX_NUMBERS')
            if max_numbers is not None:
                if not isinstance(max_numbers, int) or max_numbers < 0:
                    self.errors.append("❌ NICKNAME_GENERATOR['MAX_NUMBERS'] должен быть неотрицательным числом")
                elif max_numbers > 10:
                    self.warnings.append("⚠️ NICKNAME_GENERATOR['MAX_NUMBERS'] слишком большой (рекомендуется <= 10)")
            
            if (min_numbers is not None and max_numbers is not None and 
                isinstance(min_numbers, int) and isinstance(max_numbers, int)):
                if min_numbers > max_numbers:
                    self.errors.append("❌ NICKNAME_GENERATOR['MIN_NUMBERS'] не может быть больше MAX_NUMBERS")
        
        nice_numbers = config.get('NICE_NUMBERS')
        if nice_numbers is not None:
            if not isinstance(nice_numbers, list):
                self.errors.append("❌ NICKNAME_GENERATOR['NICE_NUMBERS'] должен быть списком")
            else:
                for i, num in enumerate(nice_numbers):
                    if not isinstance(num, int) or num < 0:
                        self.errors.append(f"❌ NICKNAME_GENERATOR['NICE_NUMBERS'][{i}] должен быть неотрицательным числом")
                    elif num > 99999:
                        self.warnings.append(f"⚠️ NICKNAME_GENERATOR['NICE_NUMBERS'][{i}] очень большой (может не поместиться в никнейм)")
        
        logger.debug("✅ Настройки генератора никнеймов проверены")
    
    def _validate_sftp_config(self, enabled, config):
        """Проверка настроек SFTP бэкапа"""
        if not enabled:
            logger.debug("ℹ️ SFTP бэкап отключен, пропускаем проверку")
            return
        
        if not isinstance(config, dict):
            self.warnings.append("⚠️ SFTP_SERVER_INTO_BACKUP должен быть словарем")
            return
        
        required_fields = {
            'host': 'Хост SFTP сервера',
            'port': 'Порт SFTP сервера', 
            'username': 'Имя пользователя SFTP',
            'remote_path': 'Путь на SFTP сервере'
        }
        
        for field, description in required_fields.items():
            value = config.get(field)
            
            if field == 'port':
                if not isinstance(value, int) or value <= 0 or value > 65535:
                    self.warnings.append(f"⚠️ SFTP_SERVER_INTO_BACKUP['{field}'] ({description}) должен быть числом от 1 до 65535")
            else:
                if not value or (isinstance(value, str) and not value.strip()):
                    self.warnings.append(f"⚠️ SFTP_SERVER_INTO_BACKUP['{field}'] ({description}) не может быть пустым при включенном SFTP")
        
        password = config.get('password', '')
        key_file = config.get('key_file', '')
        
        if (not password or not password.strip()) and (not key_file or not key_file.strip()):
            self.warnings.append("⚠️ SFTP_SERVER_INTO_BACKUP: должен быть заполнен либо 'password' либо 'key_file' для авторизации")
        
        if key_file and key_file.strip():
            key_path = Path(key_file)
            if not key_path.exists():
                self.warnings.append(f"⚠️ SFTP_SERVER_INTO_BACKUP['key_file']: файл '{key_file}' не найден")
            elif not key_path.is_file():
                self.warnings.append(f"⚠️ SFTP_SERVER_INTO_BACKUP['key_file']: '{key_file}' не является файлом")
        
        logger.debug("✅ Настройки SFTP бэкапа проверены")
    
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
        
        self._validate_mnemonic_file()
        self._validate_email_file() 
        self._validate_private_keys_file()
        self._validate_proxy_file()
        self._validate_transfer_token_file()
        self._validate_wallets_file()
    
    def _is_valid_eth_address(self, address):
        """Проверка корректности ETH адреса"""
        if not isinstance(address, str):
            return False
        return bool(re.match(r'^0x[a-fA-F0-9]{40}$', address.strip()))
    
    def _is_valid_private_key(self, private_key):
        """Проверка корректности приватного ключа"""
        if not isinstance(private_key, str):
            return False
        private_key = private_key.strip()
        if private_key.startswith('0x'):
            private_key = private_key[2:]
        return bool(re.match(r'^[a-fA-F0-9]{64}$', private_key))
    
    def _is_valid_email(self, email):
        """Проверка корректности email"""
        if not isinstance(email, str):
            return False
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email.strip()))
    
    def _is_valid_proxy_format(self, proxy):
        """Проверка корректности формата прокси login:password@ip:port"""
        if not isinstance(proxy, str):
            return False
        pattern = r'^[^:]+:[^@]+@\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{1,5}$'
        return bool(re.match(pattern, proxy.strip()))
    
    def _is_valid_amount_format(self, amount):
        """Проверка корректности формата amount"""
        if not isinstance(amount, str):
            return False
        amount = amount.strip()
        if not amount:
            return False
        
        patterns = [
            r'^\d+(\.\d+)?-\d+(\.\d+)?$',
            r'^\d+(\.\d+)?-\d+(\.\d+)?eth$',
            r'^\d+(\.\d+)?-\d+(\.\d+)?%$',
        ]
        
        return any(re.match(pattern, amount, re.IGNORECASE) for pattern in patterns)
    
    def _validate_mnemonic_file(self):
        """Проверка файла мнемоник"""
        file_path = self.data_dir / 'mnemonic.txt'
        if not file_path.exists():
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return
                
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                for i, line in enumerate(lines, 1):
                    words = line.split()
                    if len(words) != 12:
                        self.warnings.append(f"⚠️ data/mnemonic.txt строка {i}: должно быть 12 слов, найдено {len(words)}")
                    
                logger.debug(f"✅ Мнемоники проверены: {len(lines)} записей")
                        
        except Exception as e:
            self.warnings.append(f"⚠️ Ошибка чтения data/mnemonic.txt: {e}")
    
    def _validate_email_file(self):
        """Проверка файла email.csv"""
        file_path = self.data_dir / 'email.csv'
        if not file_path.exists():
            self.warnings.append("⚠️ Отсутствует файл data/email.csv")
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                lines = list(reader)
                
                if not lines:
                    self.warnings.append("⚠️ Пустой файл data/email.csv")
                    return
                
                start_idx = 1 if lines and lines[0] == ['email', 'password', 'imap_domain'] else 0
                
                data_lines = 0
                for i, row in enumerate(lines[start_idx:], start_idx + 1):
                    if not row or not any(cell.strip() for cell in row):
                        continue
                        
                    data_lines += 1
                    if len(row) != 3:
                        self.warnings.append(f"⚠️ data/email.csv строка {i}: ожидается 3 колонки (email,password,imap_domain), найдено {len(row)}")
                        continue
                    
                    email, password, imap_domain = [cell.strip() for cell in row]
                    
                    if not self._is_valid_email(email):
                        self.warnings.append(f"⚠️ data/email.csv строка {i}: некорректный email '{email}'")
                    
                    if not password:
                        self.warnings.append(f"⚠️ data/email.csv строка {i}: пустой пароль")
                        
                    if not imap_domain:
                        self.warnings.append(f"⚠️ data/email.csv строка {i}: пустой imap_domain")
                
                if data_lines > 0:
                    logger.debug(f"✅ Email файл проверен: {data_lines} записей")
                        
        except Exception as e:
            self.warnings.append(f"⚠️ Ошибка чтения data/email.csv: {e}")
    
    def _validate_private_keys_file(self):
        """Проверка файла private_keys.txt"""
        file_path = self.data_dir / 'private_keys.txt'
        if not file_path.exists():
            self.warnings.append("⚠️ Отсутствует файл data/private_keys.txt")
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    self.warnings.append("⚠️ Пустой файл data/private_keys.txt")
                    return
                
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                for i, line in enumerate(lines, 1):
                    if not self._is_valid_private_key(line):
                        self.warnings.append(f"⚠️ data/private_keys.txt строка {i}: некорректный приватный ключ")
                        
                logger.debug(f"✅ Приватные ключи проверены: {len(lines)} записей")
                        
        except Exception as e:
            self.warnings.append(f"⚠️ Ошибка чтения data/private_keys.txt: {e}")
    
    def _validate_proxy_file(self):
        """Проверка файла proxy.csv"""
        file_path = self.data_dir / 'proxy.csv'
        if not file_path.exists():
            self.warnings.append("⚠️ Отсутствует файл data/proxy.csv")
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    self.warnings.append("⚠️ Пустой файл data/proxy.csv")
                    return
                
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                for i, line in enumerate(lines, 1):
                    if not self._is_valid_proxy_format(line):
                        self.warnings.append(f"⚠️ data/proxy.csv строка {i}: некорректный формат прокси (ожидается login:password@ip:port)")
                        
                logger.debug(f"✅ Прокси проверены: {len(lines)} записей")
                        
        except Exception as e:
            self.warnings.append(f"⚠️ Ошибка чтения data/proxy.csv: {e}")
    
    def _validate_transfer_token_file(self):
        """Проверка файла transfer_token.csv"""
        file_path = self.data_dir / 'transfer_token.csv'
        if not file_path.exists():
            self.warnings.append("⚠️ Отсутствует файл data/transfer_token.csv")
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                lines = list(reader)
                
                if not lines:
                    self.warnings.append("⚠️ Пустой файл data/transfer_token.csv")
                    return
                
                start_idx = 1 if lines and lines[0] == ['from_wallet', 'to_wallet', 'amount'] else 0

                data_lines = 0
                for i, row in enumerate(lines[start_idx:], start_idx + 1):
                    if not row or not any(cell.strip() for cell in row):
                        continue

                    data_lines += 1
                    if len(row) != 3:
                        self.warnings.append(f"⚠️ data/transfer_token.csv строка {i}: ожидается 3 колонки (from_wallet,to_wallet,amount), найдено {len(row)}")
                        continue

                    from_wallet, to_wallet, amount = [cell.strip() for cell in row]

                    if not self._is_valid_private_key(from_wallet):
                        self.warnings.append(f"⚠️ data/transfer_token.csv строка {i}: from_wallet должен быть приватным ключом")

                    if not self._is_valid_private_key(to_wallet) and not self._is_valid_eth_address(to_wallet):
                        self.warnings.append(f"⚠️ data/transfer_token.csv строка {i}: to_wallet должен быть приватным ключом или публичным ETH адресом")

                    if not self._is_valid_amount_format(amount):
                        self.warnings.append(f"⚠️ data/transfer_token.csv строка {i}: некорректный формат amount (ожидается: 1-2, 1-2eth, или 1-2%)")
                
                if data_lines > 0:
                    logger.debug(f"✅ Transfer token файл проверен: {data_lines} записей")
                        
        except Exception as e:
            self.warnings.append(f"⚠️ Ошибка чтения data/transfer_token.csv: {e}")
    
    def _validate_wallets_file(self):
        """Проверка файла walletss.txt"""
        file_path = self.data_dir / 'walletss.txt'
        if not file_path.exists():
            self.warnings.append("⚠️ Отсутствует файл data/walletss.txt")
            return
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    self.warnings.append("⚠️ Пустой файл data/walletss.txt")
                    return
                
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                for i, line in enumerate(lines, 1):
                    if not self._is_valid_eth_address(line):
                        self.warnings.append(f"⚠️ data/walletss.txt строка {i}: некорректный ETH адрес")
                        
                logger.debug(f"✅ Кошельки проверены: {len(lines)} записей")
                        
        except Exception as e:
            self.warnings.append(f"⚠️ Ошибка чтения data/walletss.txt: {e}")
    
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
    print("🧪 Тестирование валидатора конфигурации")
    is_valid = validate_configuration()
    
    if is_valid:
        print("\n✅ Конфигурация готова к работе!")
        sys.exit(0)
    else:
        print("\n❌ Конфигурация требует исправлений!")
        sys.exit(1)