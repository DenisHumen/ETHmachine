"""
Модуль для проверки почт через IMAP
Проверяет возможность подключения к почтовым серверам и чтения писем
"""

import imaplib
import csv
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import os
import ssl
import socket
import urllib.request
import urllib.parse
from urllib.parse import urlparse

from colorama import Fore, Style, init
from loguru import logger

# Импорт настроек
from config.config import (
    NUM_THREADS, SLEEP_BETWEEN_ACTIONS, 
    ENABLE_SEARCH_EMAIL, IMAP_SERVER, MAIN_MAIL, PROXY
)

# Инициализация colorama
init(autoreset=True)

# Флаг инициализации логгера
_logger_initialized = False

def _setup_logging():
    """Настройка логирования - вызывается при запуске модуля"""
    global _logger_initialized
    if _logger_initialized:
        return
    _logger_initialized = True
    
    import os
    os.makedirs("log", exist_ok=True)
    
    logger.add("log/email_checker.log", 
              format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
              level="INFO",
              rotation="10 MB")

class EmailChecker:
    """Класс для проверки email аккаунтов через IMAP"""
    
    def __init__(self):
        self.results = []
        self.lock = threading.Lock()
        self.total_checked = 0
        self.total_working = 0
        self.total_failed = 0
        
    def parse_proxy(self, proxy_string):
        """Парсинг прокси строки формата login:password@ip:port"""
        if not proxy_string or proxy_string.strip() == '':
            return None
            
        try:
            # Разделяем auth и адрес
            if '@' in proxy_string:
                auth_part, addr_part = proxy_string.rsplit('@', 1)
                username, password = auth_part.split(':', 1)
                host, port = addr_part.split(':')
                return {
                    'type': 'http',
                    'host': host,
                    'port': int(port),
                    'username': username,
                    'password': password
                }
            else:
                # Прокси без авторизации
                host, port = proxy_string.split(':')
                return {
                    'type': 'http',
                    'host': host,
                    'port': int(port)
                }
        except Exception as e:
            logger.error(f"Ошибка парсинга прокси {proxy_string}: {e}")
            return None
    
    def setup_proxy_socket(self, proxy_config):
        """Настройка HTTP прокси для IMAP подключения"""
        if not proxy_config:
            return None
            
        try:
            # Создаем HTTP прокси handler
            proxy_handler = urllib.request.ProxyHandler({
                'http': f"http://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['host']}:{proxy_config['port']}" if 'username' in proxy_config else f"http://{proxy_config['host']}:{proxy_config['port']}",
                'https': f"http://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['host']}:{proxy_config['port']}" if 'username' in proxy_config else f"http://{proxy_config['host']}:{proxy_config['port']}"
            })
            
            opener = urllib.request.build_opener(proxy_handler)
            urllib.request.install_opener(opener)
            
            logger.info(f"HTTP прокси настроен: {proxy_config['host']}:{proxy_config['port']}")
            return True
        except Exception as e:
            logger.error(f"Ошибка настройки HTTP прокси: {e}")
            return None
    
    def get_imap_server(self, email):
        """Определение IMAP сервера по домену email"""
        domain = email.split('@')[1].lower()
        
        # Популярные IMAP серверы
        imap_servers = {
            'gmail.com': 'imap.gmail.com',
            'googlemail.com': 'imap.gmail.com',
            'yahoo.com': 'imap.mail.yahoo.com',
            'yahoo.co.uk': 'imap.mail.yahoo.com',
            'yahoo.fr': 'imap.mail.yahoo.com',
            'outlook.com': 'imap-mail.outlook.com',
            'outlook.fr': 'imap-mail.outlook.com',
            'hotmail.com': 'imap-mail.outlook.com',
            'hotmail.fr': 'imap-mail.outlook.com',
            'live.com': 'imap-mail.outlook.com',
            'live.fr': 'imap-mail.outlook.com',
            'msn.com': 'imap-mail.outlook.com',
            'mail.ru': 'imap.mail.ru',
            'internet.ru': 'imap.mail.ru',
            'bk.ru': 'imap.mail.ru',
            'list.ru': 'imap.mail.ru',
            'inbox.ru': 'imap.mail.ru',
            'yandex.ru': 'imap.yandex.ru',
            'yandex.com': 'imap.yandex.ru',
            'ya.ru': 'imap.yandex.ru',
            'rambler.ru': 'imap.rambler.ru',
            'aol.com': 'imap.aol.com',
            'icloud.com': 'imap.mail.me.com',
            'me.com': 'imap.mail.me.com',
            'mac.com': 'imap.mail.me.com',
            'zoho.com': 'imap.zoho.com',
            'protonmail.com': 'imap.protonmail.com',
            'tutanota.com': 'imap.tutanota.com',
        }
        
        return imap_servers.get(domain, f'imap.{domain}')
    
    def test_email_connection(self, email, password, imap_domain=None, proxy=None):
        """Тестирование подключения к email через IMAP"""
        try:
            # Определяем IMAP сервер
            if imap_domain and imap_domain.strip():
                server = imap_domain.strip()
            else:
                server = self.get_imap_server(email)
            
            logger.info(f"Проверяем {email} на сервере {server}")
            
            # Настройка прокси
            proxy_config = self.parse_proxy(proxy) if proxy else None
            if proxy_config:
                self.setup_proxy_socket(proxy_config)
                logger.info(f"Используем прокси: {proxy_config['host']}:{proxy_config['port']}")
            
            # Подключение к серверу
            mail = imaplib.IMAP4_SSL(server, 993, timeout=30)
            
            # Попытка авторизации
            result = mail.login(email, password)
            
            if result[0] == 'OK':
                # Проверяем доступ к почтовому ящику
                mail.select('INBOX')
                
                # Пытаемся получить список папок
                typ, folders = mail.list()
                
                if typ == 'OK':
                    logger.success(f"✅ {email} - подключение успешно")
                    mail.logout()
                    return True, "SUCCESS"
                else:
                    logger.error(f"❌ {email} - ошибка доступа к папкам")
                    mail.logout()
                    return False, "FOLDER_ACCESS_ERROR"
            else:
                logger.error(f"❌ {email} - неверные учетные данные")
                return False, "AUTH_FAILED"
                
        except imaplib.IMAP4.error as e:
            error_msg = str(e).lower()
            if 'authentication failed' in error_msg or 'login failed' in error_msg:
                logger.error(f"❌ {email} - неверный логин/пароль")
                return False, "AUTH_FAILED"
            else:
                logger.error(f"❌ {email} - IMAP ошибка: {e}")
                return False, f"IMAP_ERROR: {e}"
                
        except ssl.SSLError as e:
            logger.error(f"❌ {email} - SSL ошибка: {e}")
            return False, f"SSL_ERROR: {e}"
            
        except socket.timeout:
            logger.error(f"❌ {email} - таймаут подключения")
            return False, "TIMEOUT"
            
        except socket.gaierror as e:
            logger.error(f"❌ {email} - ошибка DNS: {e}")
            return False, f"DNS_ERROR: {e}"
            
        except Exception as e:
            logger.error(f"❌ {email} - неожиданная ошибка: {e}")
            return False, f"UNKNOWN_ERROR: {e}"
    
    def process_email(self, email_data, proxy=None):
        """Обработка одного email аккаунта"""
        email = email_data.get('email', '').strip()
        password = email_data.get('password', '').strip()
        imap_domain = email_data.get('imap_domain', '').strip()
        
        if not email or not password:
            logger.error(f"Пропущен {email}: отсутствуют email или пароль")
            return
        
        # Задержка между проверками
        if SLEEP_BETWEEN_ACTIONS[0] > 0:
            delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
            time.sleep(delay)
        
        # Проверяем email
        is_working, status = self.test_email_connection(email, password, imap_domain, proxy)
        
        # Сохраняем результат
        result = {
            'email': email,
            'password': password,
            'imap_domain': imap_domain if imap_domain else self.get_imap_server(email),
            'status': 'WORKING' if is_working else status,
            'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        with self.lock:
            self.results.append(result)
            self.total_checked += 1
            if is_working:
                self.total_working += 1
                print(Fore.GREEN + f"✅ [{self.total_checked}] {email} - РАБОТАЕТ")
            else:
                self.total_failed += 1
                print(Fore.RED + f"❌ [{self.total_checked}] {email} - {status}")
    
    def load_emails_from_csv(self, filepath='data/email.csv'):
        """Загрузка email данных из CSV файла"""
        emails = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('email') and row.get('password'):
                        emails.append(row)
            logger.info(f"Загружено {len(emails)} email аккаунтов из {filepath}")
            return emails
        except FileNotFoundError:
            logger.error(f"Файл {filepath} не найден")
            return []
        except Exception as e:
            logger.error(f"Ошибка чтения файла {filepath}: {e}")
            return []
    
    def load_proxies_from_csv(self, filepath='data/proxy.csv'):
        """Загрузка прокси из CSV файла"""
        proxies = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    proxy = line.strip()
                    if proxy and not proxy.startswith('#'):
                        proxies.append(proxy)
            logger.info(f"Загружено {len(proxies)} прокси из {filepath}")
            return proxies
        except FileNotFoundError:
            logger.warning(f"Файл прокси {filepath} не найден. Работаем без прокси.")
            return []
        except Exception as e:
            logger.error(f"Ошибка чтения файла прокси {filepath}: {e}")
            return []
    
    def save_results_to_csv(self, filepath=None):
        """Сохранение результатов в CSV файл"""
        if not filepath:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filepath = f'result/email/email_check_results_{timestamp}.csv'
        
        # Создаем директорию если не существует
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                if self.results:
                    fieldnames = ['email', 'password', 'imap_domain', 'status', 'checked_at']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(self.results)
            logger.success(f"Результаты сохранены в {filepath}")
            print(Fore.GREEN + f"📄 Результаты сохранены в {filepath}")
        except Exception as e:
            logger.error(f"Ошибка сохранения результатов: {e}")
            print(Fore.RED + f"❌ Ошибка сохранения: {e}")
    
    def run_multithreaded_check(self):
        """Запуск многопоточной проверки email аккаунтов"""
        print(Fore.CYAN + f"\n{'='*60}")
        print(Fore.CYAN + f"📧 МОДУЛЬ ПРОВЕРКИ ПОЧТ ЧЕРЕЗ IMAP")
        print(Fore.CYAN + f"{'='*60}")
        
        # Загружаем данные
        emails = self.load_emails_from_csv()
        if not emails:
            print(Fore.RED + "❌ Нет email аккаунтов для проверки!")
            return
        
        proxies = self.load_proxies_from_csv()
        
        print(Fore.YELLOW + f"📊 Загружено:")
        print(Fore.YELLOW + f"   - Email аккаунтов: {len(emails)}")
        print(Fore.YELLOW + f"   - Прокси: {len(proxies)}")
        print(Fore.YELLOW + f"   - Потоков: {NUM_THREADS}")
        print(Fore.YELLOW + f"   - Задержка: {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]} сек")
        print(Fore.CYAN + f"{'='*60}\n")
        
        start_time = time.time()
        
        # Многопоточная проверка
        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            futures = []
            
            for i, email_data in enumerate(emails):
                # Выбираем случайный прокси, если есть
                proxy = random.choice(proxies) if proxies else None
                future = executor.submit(self.process_email, email_data, proxy)
                futures.append(future)
            
            # Ожидаем завершения всех задач
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Ошибка в потоке: {e}")
        
        # Подсчет времени выполнения
        end_time = time.time()
        duration = end_time - start_time
        
        # Сохраняем результаты
        self.save_results_to_csv()
        
        # Статистика
        print(Fore.CYAN + f"\n{'='*60}")
        print(Fore.CYAN + f"📊 ИТОГОВАЯ СТАТИСТИКА")
        print(Fore.CYAN + f"{'='*60}")
        print(Fore.GREEN + f"✅ Рабочих аккаунтов: {self.total_working}")
        print(Fore.RED + f"❌ Нерабочих аккаунтов: {self.total_failed}")
        print(Fore.YELLOW + f"📊 Всего проверено: {self.total_checked}")
        print(Fore.BLUE + f"⏱️ Время выполнения: {duration:.2f} сек")
        if self.total_checked > 0:
            success_rate = (self.total_working / self.total_checked) * 100
            print(Fore.MAGENTA + f"📈 Успешность: {success_rate:.1f}%")
        print(Fore.CYAN + f"{'='*60}\n")

def run_email_checker():
    """Главная функция запуска модуля проверки почт"""
    _setup_logging()
    try:
        checker = EmailChecker()
        checker.run_multithreaded_check()
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n⚠️ Проверка прервана пользователем")
    except Exception as e:
        print(Fore.RED + f"❌ Ошибка в модуле проверки почт: {e}")
        logger.error(f"Критическая ошибка: {e}")

def main():
    """Точка входа модуля"""
    run_email_checker()

if __name__ == "__main__":
    main()
