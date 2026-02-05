"""
Модуль управления бэкапами
Объединяет локальное и SFTP резервное копирование с поддержкой live синхронизации и шифрования
"""

import os
import sys
import shutil
import zipfile
import time
import hashlib
import threading
import json
import getpass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Добавляем путь к корневой директории проекта
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
sys.path.append(project_root)

from modules.simple_logger import logger
from config.modules.cfg_backup import (
    SFTP_SERVER_INTO_BACKUP_ENABLE,
    SFTP_LIVE_SYNC_ENABLE,
    SFTP_SERVER_INTO_BACKUP,
    DIRECTORIES_TO_BACKUP,
    MAX_BACKUPS_TO_KEEP
)

# Попытка импорта paramiko для SFTP
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False
    logger.warning("⚠️  Paramiko не установлен. SFTP функции недоступны. Установите: pip install paramiko")

# Путь для логов
log_dir = os.path.join(project_root, 'log')

# Флаг инициализации логгера (больше не нужен, но оставим для совместимости)
_logger_initialized = False

def _setup_logging():
    """Настройка логирования - теперь используем simple_logger"""
    global _logger_initialized
    if _logger_initialized:
        return
    _logger_initialized = True
    
    os.makedirs(log_dir, exist_ok=True)
    
    # Добавляем только файловый лог, консольный уже настроен в simple_logger
    logger.add(
        os.path.join(log_dir, 'backup.log'),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="30 days"
    )


class EncryptionManager:
    """Менеджер шифрования/дешифрования файлов"""
    
    def __init__(self, password: str):
        """
        Инициализация с паролем
        
        Args:
            password: Пароль для шифрования
        """
        self.password = password
        self.key = self._derive_key(password)
        self.fernet = Fernet(self.key)
    
    @staticmethod
    def _derive_key(password: str, salt: bytes = b'ETHmachine_backup_salt_v1') -> bytes:
        """
        Генерация ключа из пароля
        
        Args:
            password: Пароль
            salt: Соль для генерации ключа
            
        Returns:
            Ключ для шифрования
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = kdf.derive(password.encode())
        # Конвертируем в base64 для Fernet
        import base64
        return base64.urlsafe_b64encode(key)
    
    def encrypt_file(self, input_path: str, output_path: str) -> bool:
        """
        Шифрование файла
        
        Args:
            input_path: Путь к исходному файлу
            output_path: Путь к зашифрованному файлу
            
        Returns:
            True при успехе
        """
        try:
            with open(input_path, 'rb') as f:
                data = f.read()
            
            encrypted_data = self.fernet.encrypt(data)
            
            with open(output_path, 'wb') as f:
                f.write(encrypted_data)
            
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка шифрования файла: {e}")
            return False
    
    def decrypt_file(self, input_path: str, output_path: str) -> bool:
        """
        Дешифрование файла
        
        Args:
            input_path: Путь к зашифрованному файлу
            output_path: Путь к расшифрованному файлу
            
        Returns:
            True при успехе
        """
        try:
            with open(input_path, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self.fernet.decrypt(encrypted_data)
            
            with open(output_path, 'wb') as f:
                f.write(decrypted_data)
            
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка дешифрования файла: {e}")
            return False


class LiveSyncMonitor:
    """Монитор для live синхронизации изменений"""
    
    def __init__(self, backup_manager):
        self.backup_manager = backup_manager
        self.running = False
        self.thread = None
        self.monitor_thread = None  # Алиас для совместимости
        self.check_interval = 60  # Проверка каждые 60 секунд
        self.file_hashes = {}  # Хэши файлов для отслеживания изменений
        self.project_root = backup_manager.project_root if hasattr(backup_manager, 'project_root') else os.getcwd()
    
    @property
    def is_running(self) -> bool:
        """Проверка что мониторинг активен"""
        return self.running
    
    def calculate_directory_hash(self, directory: str = None) -> Dict[str, str]:
        """
        Вычисление хэшей всех файлов в директории
        
        Args:
            directory: Путь к директории (если None - используется project_root)
            
        Returns:
            Словарь {относительный_путь: хэш}
        """
        if directory is None:
            directory = self.project_root
            
        hashes = {}
        
        if not os.path.exists(directory):
            return hashes
        
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, directory)
                
                try:
                    with open(file_path, 'rb') as f:
                        file_hash = hashlib.md5(f.read()).hexdigest()
                    hashes[rel_path] = file_hash
                except Exception as e:
                    logger.debug(f"Не удалось прочитать файл {file_path}: {e}")
        
        return hashes
    
    def check_for_changes(self) -> bool:
        """
        Проверка наличия изменений в отслеживаемых директориях
        
        Returns:
            True если есть изменения
        """
        current_hashes = {}
        
        for directory in DIRECTORIES_TO_BACKUP:
            dir_path = os.path.join(self.backup_manager.project_root, directory)
            dir_hashes = self.calculate_directory_hash(dir_path)
            current_hashes.update({f"{directory}/{k}": v for k, v in dir_hashes.items()})
        
        # Первый запуск - сохраняем текущие хэши
        if not self.file_hashes:
            self.file_hashes = current_hashes
            return False
        
        # Сравниваем с сохраненными хэшами
        if current_hashes != self.file_hashes:
            self.file_hashes = current_hashes
            return True
        
        return False
    
    def save_current_hash(self):
        """Сохранение текущего состояния хэшей"""
        current_hashes = {}
        
        for directory in DIRECTORIES_TO_BACKUP:
            dir_path = os.path.join(self.backup_manager.project_root, directory)
            dir_hashes = self.calculate_directory_hash(dir_path)
            current_hashes.update({f"{directory}/{k}": v for k, v in dir_hashes.items()})
        
        self.file_hashes = current_hashes
    
    def monitor_loop(self):
        """Основной цикл мониторинга"""
        # Используем отдельный логгер для минимального вывода
        from datetime import datetime
        
        # Инициализация - создаем первый бекап если его нет
        if not self.backup_manager.check_live_backup_exists():
            logger.info("📦 Live Backup: Создание начального бекапа...")
            self.backup_manager.create_live_backup()
        
        #logger.info("🔄 Live Backup: Мониторинг запущен (проверка каждые 60 сек)")
        
        while self.running:
            try:
                time.sleep(self.check_interval)
                
                if not self.running:
                    break
                
                if self.check_for_changes():
                    # Компактный вывод одной строкой
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    logger.info(f"� Live Backup [{timestamp}]: Изменения обнаружены → Создание backup...")
                    
                    if self.backup_manager.create_live_backup():
                        logger.success(f"✅ Live Backup [{timestamp}]: Синхронизация завершена")
                    else:
                        logger.error(f"❌ Live Backup [{timestamp}]: Ошибка синхронизации")
                    
            except Exception as e:
                logger.error(f"❌ Live Backup: Ошибка мониторинга - {e}")
    
    def start(self):
        """Запуск мониторинга в отдельном потоке"""
        if self.running:
            logger.warning("⚠️ Мониторинг уже запущен")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread = self.thread  # Алиас для совместимости
        self.thread.start()
        logger.success("✅ Live мониторинг запущен")
    
    def stop(self):
        """Остановка мониторинга"""
        if not self.running:
            return
        
        logger.info("🛑 Остановка live мониторинга...")
        self.running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.success("✅ Live мониторинг остановлен")



class SFTPProgressBar:
    """
    Прогресс-бар для передачи файлов SFTP в стиле Ubuntu
    Показывает: прогресс, скорость, время, процент
    """
    
    def __init__(self, total_size: int, filename: str):
        self.total_size = total_size
        self.filename = filename
        self.transferred = 0
        self.start_time = time.time()
        self.last_update_time = time.time()
        self.last_transferred = 0
        self.speeds = []  # История скоростей для сглаживания
        
    def __call__(self, transferred: int, total: int):
        """Callback для paramiko"""
        self.transferred = transferred
        current_time = time.time()
        
        # Обновляем не чаще чем раз в 0.1 секунды
        if current_time - self.last_update_time < 0.1 and transferred < total:
            return
        
        self.last_update_time = current_time
        self._display_progress()
    
    def _display_progress(self):
        """Отображение прогресс-бара"""
        # Расчет процента
        percent = (self.transferred / self.total_size * 100) if self.total_size > 0 else 0
        
        # Расчет скорости (с усреднением)
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            current_speed = self.transferred / elapsed
            self.speeds.append(current_speed)
            # Храним последние 10 значений для сглаживания
            if len(self.speeds) > 10:
                self.speeds.pop(0)
            avg_speed = sum(self.speeds) / len(self.speeds)
        else:
            avg_speed = 0
        
        # Расчет оставшегося времени
        if avg_speed > 0:
            remaining_bytes = self.total_size - self.transferred
            eta_seconds = remaining_bytes / avg_speed
            eta_str = self._format_time(eta_seconds)
        else:
            eta_str = "--:--"
        
        # Форматирование размеров
        transferred_str = self._format_size(self.transferred)
        total_str = self._format_size(self.total_size)
        speed_str = self._format_size(avg_speed) + "/s"
        
        # Создание прогресс-бара (50 символов)
        bar_length = 50
        filled_length = int(bar_length * percent / 100)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        # Форматирование времени с начала
        elapsed_str = self._format_time(elapsed)
        
        # Вывод в стиле Ubuntu
        output = (
            f"\r{self.filename[:30]:<30} "
            f"[{bar}] "
            f"{percent:5.1f}% "
            f"{transferred_str:>8}/{total_str:<8} "
            f"{speed_str:>12} "
            f"ETA: {eta_str:>6} "
            f"Elapsed: {elapsed_str:>6}"
        )
        
        sys.stdout.write(output)
        sys.stdout.flush()
        
        # Переход на новую строку при завершении
        if self.transferred >= self.total_size:
            print()  # Новая строка
    
    @staticmethod
    def _format_size(bytes_size: float) -> str:
        """Форматирование размера в читаемый вид"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:6.2f}{unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:6.2f}TB"
    
    @staticmethod
    def _format_time(seconds: float) -> str:
        """Форматирование времени в ЧЧ:ММ:СС"""
        if seconds < 0:
            return "--:--"
        
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"



class BackupManager:
    """Класс для управления локальными и SFTP бэкапами"""
    
    def __init__(self):
        _setup_logging()
        self.project_root = project_root
        self.backup_local_dir = os.path.join(self.project_root, 'backups')
        self.sftp_config = SFTP_SERVER_INTO_BACKUP
        self.sftp_enabled = SFTP_SERVER_INTO_BACKUP_ENABLE and PARAMIKO_AVAILABLE
        self.live_sync_enabled = SFTP_LIVE_SYNC_ENABLE and self.sftp_enabled
        self.live_monitor = None
        
        # Инициализация пароля шифрования из конфига
        self.encryption_password = self.sftp_config.get('password_encryption', '') or None
        
        # Создаем локальную директорию для бэкапов
        os.makedirs(self.backup_local_dir, exist_ok=True)
    
    # ==================== ШИФРОВАНИЕ ====================
    
    def get_encryption_password(self) -> Optional[str]:
        """
        Получение пароля для шифрования (из конфига или ручной ввод)
        
        Returns:
            Пароль или None
        """
        # Если уже есть в кэше - используем его
        if self.encryption_password:
            return self.encryption_password
        
        # Проверяем конфиг
        config_password = self.sftp_config.get('password_encryption', '')
        if config_password:
            self.encryption_password = config_password
            return config_password
        
        # Запрашиваем у пользователя
        logger.info("🔐 Пароль для шифрования не указан в конфиге")
        password = getpass.getpass("Введите пароль для шифрования бекапа: ")
        
        if not password:
            logger.warning("⚠️ Пароль не введен, шифрование не будет использовано")
            return None
        
        # Подтверждение пароля
        password_confirm = getpass.getpass("Подтвердите пароль: ")
        
        if password != password_confirm:
            logger.error("❌ Пароли не совпадают!")
            return None
        
        # Сохраняем в кэш для текущей сессии
        self.encryption_password = password
        return password
    
    def get_live_backup_name(self) -> str:
        """
        Генерация имени для live бекапа
        
        Returns:
            Имя файла live бекапа
        """
        identificator = self.sftp_config.get('identificator', 'main')
        return f'live_backup_{identificator}.zip.encrypted'
    
    # ==================== ЛОКАЛЬНЫЕ БЭКАПЫ ====================
    
    def create_local_backup(self) -> Optional[str]:
        """
        Создание локального бэкапа
        
        Returns:
            Путь к созданному архиву или None при ошибке
        """
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f'backup_{timestamp}.zip'
            backup_path = os.path.join(self.backup_local_dir, backup_filename)
            
            # Компактный вывод: создаем архив без промежуточных логов
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for directory in DIRECTORIES_TO_BACKUP:
                    dir_path = os.path.join(self.project_root, directory)
                    
                    if not os.path.exists(dir_path):
                        logger.warning(f"⚠️ Директория не найдена: {directory}")
                        continue
                    
                    # Добавляем все файлы из директории (без логов)
                    for root, dirs, files in os.walk(dir_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, self.project_root)
                            zipf.write(file_path, arcname)
            
            # Получаем размер архива
            size_mb = os.path.getsize(backup_path) / (1024 * 1024)
            logger.success(f"✅ Локальный бэкап создан: {backup_filename} ({size_mb:.2f} MB)")
            
            return backup_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка создания локального бэкапа: {e}")
            return None
    
    def list_local_backups(self) -> List[str]:
        """Получение списка локальных бэкапов"""
        try:
            backups = sorted([
                f for f in os.listdir(self.backup_local_dir)
                if f.startswith('backup_') and f.endswith('.zip')
            ], reverse=True)
            
            return backups
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка локальных бэкапов: {e}")
            return []
    
    def cleanup_old_local_backups(self):
        """Удаление старых локальных бэкапов"""
        try:
            backups = self.list_local_backups()
            
            if len(backups) <= MAX_BACKUPS_TO_KEEP:
                return
            
            backups_to_delete = backups[MAX_BACKUPS_TO_KEEP:]
            
            for backup in backups_to_delete:
                backup_path = os.path.join(self.backup_local_dir, backup)
                try:
                    os.remove(backup_path)
                except Exception as e:
                    logger.error(f"❌ Ошибка удаления {backup}: {e}")
            
            if backups_to_delete:
                logger.info(f"🗑️ Удалено локальных: {len(backups_to_delete)} | Осталось: {MAX_BACKUPS_TO_KEEP}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка очистки старых бэкапов: {e}")
    
    # ==================== LIVE БЭКАПЫ ====================
    
    def create_live_backup(self, silent: bool = False) -> bool:
        """
        Создание live бекапа с шифрованием и загрузкой на SFTP
        
        Args:
            silent: Тихий режим (минимальный вывод для фонового мониторинга)
            
        Returns:
            True при успехе
        """
        try:
            if not silent:
                logger.info("=" * 60)
                logger.info("🔄 Создание LIVE бекапа")
                logger.info("=" * 60)
            
            # Создаем временный обычный бекап
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            temp_backup_name = f'temp_live_{timestamp}.zip'
            temp_backup_path = os.path.join(self.backup_local_dir, temp_backup_name)
            
            if not silent:
                logger.info(f"📦 Создание временного архива...")
            
            with zipfile.ZipFile(temp_backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for directory in DIRECTORIES_TO_BACKUP:
                    dir_path = os.path.join(self.project_root, directory)
                    
                    if not os.path.exists(dir_path):
                        continue
                    
                    for root, dirs, files in os.walk(dir_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, self.project_root)
                            zipf.write(file_path, arcname)
            
            # Шифруем бекап
            password = self.get_encryption_password()
            
            if password:
                if not silent:
                    logger.info("🔐 Шифрование бекапа...")
                encrypted_name = f'{temp_backup_name}.encrypted'
                encrypted_path = os.path.join(self.backup_local_dir, encrypted_name)
                
                encryption_manager = EncryptionManager(password)
                
                if not encryption_manager.encrypt_file(temp_backup_path, encrypted_path):
                    if not silent:
                        logger.error("❌ Ошибка шифрования")
                    os.remove(temp_backup_path)
                    return False
                
                # Удаляем незашифрованный файл
                os.remove(temp_backup_path)
                final_backup_path = encrypted_path
                if not silent:
                    logger.success("✅ Бекап зашифрован")
            else:
                final_backup_path = temp_backup_path
                if not silent:
                    logger.warning("⚠️ Бекап не зашифрован (пароль не указан)")
            
            # Загружаем на SFTP
            if self.sftp_enabled:
                live_backup_name = self.get_live_backup_name()
                
                # Удаляем старый live бекап с сервера
                if not silent:
                    self._delete_remote_live_backup()
                else:
                    # Тихое удаление
                    try:
                        self._delete_remote_live_backup_silent()
                    except:
                        pass
                
                # Загружаем новый
                if not silent:
                    logger.info(f"📤 Загрузка на SFTP как {live_backup_name}...")
                    self.upload_to_sftp(final_backup_path, remote_filename=live_backup_name)
                    logger.success(f"✅ Live бекап обновлен на сервере: {live_backup_name}")
                else:
                    # Тихая загрузка без прогресс-бара
                    self.upload_to_sftp(final_backup_path, remote_filename=live_backup_name, silent=True)
            
            # Удаляем локальный временный файл
            os.remove(final_backup_path)
            
            if not silent:
                logger.info("=" * 60)
                logger.success("✅ Live бекап создан")
                logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            if not silent:
                logger.error(f"❌ Ошибка создания live бекапа: {e}")
            return False
    
    def check_live_backup_exists(self) -> bool:
        """
        Проверка существования live бекапа на сервере
        
        Returns:
            True если существует
        """
        if not self.sftp_enabled:
            return False
        
        try:
            connection = self._connect_sftp()
            if not connection:
                return False
            
            ssh, sftp = connection
            
            try:
                remote_path = self.sftp_config['remote_path']
                live_backup_name = self.get_live_backup_name()
                remote_file = os.path.join(remote_path, live_backup_name).replace('\\', '/')
                
                try:
                    sftp.stat(remote_file)
                    return True
                except FileNotFoundError:
                    return False
                    
            finally:
                sftp.close()
                ssh.close()
                
        except Exception as e:
            logger.debug(f"Ошибка проверки live бекапа: {e}")
            return False
    
    def _delete_remote_live_backup(self) -> bool:
        """
        Удаление live бекапа с SFTP сервера (внутренний метод)
        
        Returns:
            True при успехе
        """
        if not self.sftp_enabled:
            return False
        
        try:
            connection = self._connect_sftp()
            if not connection:
                return False
            
            ssh, sftp = connection
            
            try:
                remote_path = self.sftp_config['remote_path']
                live_backup_name = self.get_live_backup_name()
                remote_file = os.path.join(remote_path, live_backup_name).replace('\\', '/')
                
                try:
                    sftp.remove(remote_file)
                    logger.info(f"🗑️ Удален старый live бекап: {live_backup_name}")
                    return True
                except FileNotFoundError:
                    logger.debug(f"Live бекап не найден на сервере: {live_backup_name}")
                    return True
                    
            finally:
                sftp.close()
                ssh.close()
                
        except Exception as e:
            logger.error(f"❌ Ошибка удаления live бекапа: {e}")
            return False
    
    def _delete_remote_live_backup_silent(self) -> bool:
        """
        Тихое удаление live бекапа с SFTP сервера
        
        Returns:
            True при успехе
        """
        if not self.sftp_enabled:
            return False
        
        try:
            connection = self._connect_sftp()
            if not connection:
                return False
            
            ssh, sftp = connection
            
            try:
                remote_path = self.sftp_config['remote_path']
                live_backup_name = self.get_live_backup_name()
                remote_file = os.path.join(remote_path, live_backup_name).replace('\\', '/')
                
                try:
                    sftp.remove(remote_file)
                    return True
                except FileNotFoundError:
                    return True
                    
            finally:
                sftp.close()
                ssh.close()
                
        except Exception as e:
            return False
    
    def delete_live_backup_with_confirmation(self) -> bool:
        """
        Удаление live бекапа с подтверждением (для меню)
        
        Returns:
            True если удален
        """
        if not self.sftp_enabled:
            logger.warning("⚠️ SFTP отключен")
            return False
        
        # Проверяем существование
        if not self.check_live_backup_exists():
            logger.warning("⚠️ Live бекап не найден на сервере")
            return False
        
        live_backup_name = self.get_live_backup_name()
        
        logger.warning("=" * 60)
        logger.warning(f"⚠️  УДАЛЕНИЕ LIVE БЕКАПА")
        logger.warning("=" * 60)
        logger.warning(f"Файл: {live_backup_name}")
        logger.warning(f"Сервер: {self.sftp_config['host']}")
        logger.warning("=" * 60)
        
        while True:
            choice = input("\nВы уверены? (да/нет/назад): ").strip().lower()
            
            if choice in ['да', 'yes', 'y']:
                if self._delete_remote_live_backup():
                    logger.success("✅ Live бекап удален с сервера")
                    return True
                else:
                    logger.error("❌ Не удалось удалить live бекап")
                    return False
            elif choice in ['нет', 'no', 'n']:
                logger.info("❌ Удаление отменено")
                return False
            elif choice in ['назад', 'back', 'b']:
                logger.info("↩️  Возврат в меню")
                return False
            else:
                logger.warning("⚠️ Неверный выбор. Введите: да/нет/назад")
    
    def restore_live_backup(self) -> bool:
        """
        Восстановление из live бекапа с SFTP сервера
        
        Returns:
            True при успехе
        """
        if not self.sftp_enabled:
            logger.error("❌ SFTP отключен")
            return False
        
        try:
            logger.info("=" * 60)
            logger.info("🔄 Восстановление из LIVE бекапа")
            logger.info("=" * 60)
            
            # Проверяем существование
            if not self.check_live_backup_exists():
                logger.error("❌ Live бекап не найден на сервере")
                return False
            
            # Скачиваем с SFTP
            live_backup_name = self.get_live_backup_name()
            temp_encrypted_path = os.path.join(self.backup_local_dir, f'temp_{live_backup_name}')
            
            logger.info(f"📥 Скачивание live бекапа с сервера...")
            
            connection = self._connect_sftp()
            if not connection:
                return False
            
            ssh, sftp = connection
            
            try:
                remote_path = self.sftp_config['remote_path']
                remote_file = os.path.join(remote_path, live_backup_name).replace('\\', '/')
                
                # Скачиваем с прогрессом
                file_size = sftp.stat(remote_file).st_size
                progress = SFTPProgressBar(file_size, live_backup_name)
                
                sftp.get(remote_file, temp_encrypted_path, callback=progress)
                logger.success(f"✅ Файл скачан ({file_size / (1024*1024):.2f} MB)")
                
            finally:
                sftp.close()
                ssh.close()
            
            # Дешифруем если нужно
            if live_backup_name.endswith('.encrypted'):
                logger.info("🔓 Дешифрование бекапа...")
                
                # Запрашиваем пароль
                password = getpass.getpass("Введите пароль для дешифрования: ")
                
                if not password:
                    logger.error("❌ Пароль не введен")
                    os.remove(temp_encrypted_path)
                    return False
                
                temp_decrypted_path = temp_encrypted_path.replace('.encrypted', '')
                encryption_manager = EncryptionManager(password)
                
                if not encryption_manager.decrypt_file(temp_encrypted_path, temp_decrypted_path):
                    logger.error("❌ Ошибка дешифрования (неверный пароль?)")
                    os.remove(temp_encrypted_path)
                    return False
                
                os.remove(temp_encrypted_path)
                backup_path = temp_decrypted_path
                logger.success("✅ Бекап расшифрован")
            else:
                backup_path = temp_encrypted_path
            
            # Восстанавливаем из архива
            logger.info(f"📂 Восстановление файлов из: {os.path.basename(backup_path)}")
            
            with zipfile.ZipFile(backup_path, 'r') as zipf:
                # Извлекаем файлы
                for member in zipf.namelist():
                    target_path = os.path.join(self.project_root, member)
                    
                    # Создаем директории если нужно
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    
                    # Извлекаем файл
                    with zipf.open(member) as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
                    
                    logger.debug(f"✓ Восстановлен: {member}")
            
            # Удаляем временный файл
            os.remove(backup_path)
            
            logger.info("=" * 60)
            logger.success("✅ Восстановление из live бекапа завершено!")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка восстановления из live бекапа: {e}")
            return False
    
    # ==================== УПРАВЛЕНИЕ LIVE МОНИТОРИНГОМ ====================
    
    def start_live_monitoring(self) -> bool:
        """
        Запуск live мониторинга изменений
        
        Returns:
            True при успешном запуске
        """
        if not self.live_sync_enabled:
            logger.warning("⚠️ Live синхронизация отключена в конфиге")
            return False
        
        if self.live_monitor and self.live_monitor.running:
            logger.warning("⚠️ Live мониторинг уже запущен")
            return False
        
        self.live_monitor = LiveSyncMonitor(self)
        self.live_monitor.start()
        return True
    
    def stop_live_monitoring(self):
        """Остановка live мониторинга"""
        if self.live_monitor:
            self.live_monitor.stop()
            self.live_monitor = None
    
    # ==================== ЛОКАЛЬНОЕ ВОССТАНОВЛЕНИЕ ====================
    
    def restore_local_backup(self, backup_name: Optional[str] = None) -> bool:
        """
        Восстановление из локального бэкапа
        
        Args:
            backup_name: Имя файла бэкапа (если None, используется последний)
            
        Returns:
            True при успехе, False при ошибке
        """
        try:
            # Если не указано имя, берем последний бэкап
            if not backup_name:
                backups = self.list_local_backups()
                if not backups:
                    logger.error("❌ Локальные бэкапы не найдены")
                    return False
                backup_name = backups[0]
            
            backup_path = os.path.join(self.backup_local_dir, backup_name)
            
            if not os.path.exists(backup_path):
                logger.error(f"❌ Файл бэкапа не найден: {backup_path}")
                return False
            
            logger.info("=" * 60)
            logger.info(f"🔄 Восстановление из бэкапа: {backup_name}")
            logger.info("=" * 60)
            
            # Распаковываем архив
            with zipfile.ZipFile(backup_path, 'r') as zipf:
                logger.info("📦 Распаковка архива...")
                zipf.extractall(self.project_root)
            
            logger.info("=" * 60)
            logger.success("✅ Бэкап успешно восстановлен")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка восстановления из бэкапа: {e}")
            return False
    
    def show_local_backups_info(self):
        """Вывод информации о локальных бэкапах"""
        backups = self.list_local_backups()
        
        if not backups:
            logger.info("📭 Локальные бэкапы не найдены")
            return
        
        logger.info("=" * 60)
        logger.info(f"📋 Локальные бэкапы ({len(backups)} шт.):")
        logger.info("=" * 60)
        
        for i, backup in enumerate(backups, 1):
            backup_path = os.path.join(self.backup_local_dir, backup)
            
            try:
                stat = os.stat(backup_path)
                size_mb = stat.st_size / (1024 * 1024)
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                
                logger.info(f"{i}. {backup}")
                logger.info(f"   Размер: {size_mb:.2f} MB | Дата: {mtime}")
            except Exception as e:
                logger.warning(f"{i}. {backup} (ошибка получения информации: {e})")
        
        logger.info("=" * 60)
    
    # ==================== SFTP БЭКАПЫ ====================
    
    def _connect_sftp(self, silent: bool = False) -> Optional[Tuple[paramiko.SSHClient, paramiko.SFTPClient]]:
        """Подключение к SFTP серверу
        
        Args:
            silent: Тихий режим без логов подключения
        """
        if not PARAMIKO_AVAILABLE:
            logger.error("❌ Paramiko не установлен")
            return None
        
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            host = self.sftp_config.get('host', '')
            port = self.sftp_config.get('port', 22)
            username = self.sftp_config.get('username', '')
            password = self.sftp_config.get('password', '')
            key_file = self.sftp_config.get('key_file', '')
            
            if not host or not username:
                logger.error("❌ Не указаны обязательные параметры: host и username")
                return None
            
            # Подключение с ключом или паролем
            if key_file and os.path.exists(key_file):
                ssh.connect(hostname=host, port=port, username=username, key_filename=key_file, timeout=30)
            elif password:
                ssh.connect(hostname=host, port=port, username=username, password=password, timeout=30)
            else:
                logger.error("❌ Не указан ни пароль, ни файл ключа")
                return None
            
            sftp = ssh.open_sftp()
            
            # if not silent:
            #     logger.success(f"✅ Подключено к SFTP: {host}:{port}")
            
            return ssh, sftp
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к SFTP: {e}")
            return None
    
    def upload_to_sftp(self, local_file: str, remote_filename: Optional[str] = None, silent: bool = False) -> bool:
        """
        Загрузка файла на SFTP сервер
        
        Args:
            local_file: Путь к локальному файлу
            remote_filename: Имя файла на сервере (если None - используется имя локального файла)
            silent: Тихий режим без прогресс-бара
        
        Returns:
            True при успехе
        """
        if not self.sftp_enabled:
            if not silent:
                logger.warning("⚠️ SFTP бэкап отключен или недоступен")
            return False
        
        connection = self._connect_sftp(silent=True)  # Тихое подключение
        if not connection:
            return False
        
        ssh, sftp = connection
        
        try:
            remote_path = self.sftp_config.get('remote_path', '/backups/')
            
            # Используем кастомное имя или имя локального файла
            filename = remote_filename if remote_filename else os.path.basename(local_file)
            remote_file = os.path.join(remote_path, filename).replace('\\', '/')
            
            # Создаем удаленную директорию если её нет
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                self._create_remote_directory(sftp, remote_path)
            
            # Получаем размер файла
            file_size = os.path.getsize(local_file)
            
            if not silent:
                # Загружаем с прогресс-баром
                progress = SFTPProgressBar(file_size, filename)
                sftp.put(local_file, remote_file, callback=progress)
            else:
                # Тихая загрузка
                sftp.put(local_file, remote_file)
            
            if not silent:
                size_mb = file_size / (1024 * 1024)
                logger.success(f"✅ Файл загружен на SFTP: {remote_file} ({size_mb:.2f} MB)")
            
            return True
            
        except Exception as e:
            if not silent:
                logger.error(f"❌ Ошибка загрузки на SFTP: {e}")
            return False
        finally:
            sftp.close()
            ssh.close()
    
    def _create_remote_directory(self, sftp: 'paramiko.SFTPClient', path: str):
        """Рекурсивное создание директории на SFTP сервере"""
        dirs = []
        while path and path != '/':
            dirs.append(path)
            path = os.path.dirname(path)
        
        dirs.reverse()
        
        for directory in dirs:
            try:
                sftp.stat(directory)
            except FileNotFoundError:
                sftp.mkdir(directory)
    
    def list_sftp_backups(self) -> List[str]:
        """Получение списка бэкапов на SFTP сервере"""
        if not self.sftp_enabled:
            return []
        
        connection = self._connect_sftp(silent=True)  # Тихое подключение
        if not connection:
            return []
        
        ssh, sftp = connection
        
        try:
            remote_path = self.sftp_config.get('remote_path', '/backups/')
            
            try:
                files = sftp.listdir(remote_path)
            except FileNotFoundError:
                logger.warning(f"⚠️ Удаленная директория не найдена: {remote_path}")
                return []
            
            backups = [f for f in files if f.startswith('backup_') and f.endswith('.zip')]
            backups.sort(reverse=True)
            
            return backups
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка удаленных бэкапов: {e}")
            return []
        finally:
            sftp.close()
            ssh.close()
    
    def cleanup_old_sftp_backups(self):
        """Удаление старых бэкапов на SFTP сервере"""
        if not self.sftp_enabled:
            return
        
        connection = self._connect_sftp(silent=True)  # Тихое подключение
        if not connection:
            return
        
        ssh, sftp = connection
        
        try:
            backups = self.list_sftp_backups()
            
            if len(backups) <= MAX_BACKUPS_TO_KEEP:
                return
            
            remote_path = self.sftp_config.get('remote_path', '/backups/')
            backups_to_delete = backups[MAX_BACKUPS_TO_KEEP:]
            
            for backup in backups_to_delete:
                remote_file = os.path.join(remote_path, backup).replace('\\', '/')
                try:
                    sftp.remove(remote_file)
                except Exception as e:
                    logger.error(f"❌ Ошибка удаления {backup}: {e}")
            
            if backups_to_delete:
                logger.info(f"🗑️ Удалено SFTP: {len(backups_to_delete)} | Осталось: {MAX_BACKUPS_TO_KEEP}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка очистки старых SFTP бэкапов: {e}")
        finally:
            sftp.close()
            ssh.close()
    
    def download_from_sftp(self, backup_name: Optional[str] = None) -> bool:
        """Скачивание бэкапа с SFTP сервера"""
        if not self.sftp_enabled:
            logger.warning("⚠️ SFTP бэкап отключен или недоступен")
            return False
        
        connection = self._connect_sftp()
        if not connection:
            return False
        
        ssh, sftp = connection
        
        try:
            backups = self.list_sftp_backups()
            
            if not backups:
                logger.error("❌ На SFTP сервере нет бэкапов")
                return False
            
            # Выбираем файл для скачивания
            if backup_name:
                if backup_name not in backups:
                    logger.error(f"❌ Бэкап {backup_name} не найден на сервере")
                    return False
                selected_backup = backup_name
            else:
                selected_backup = backups[0]  # Последний бэкап
            
            remote_path = self.sftp_config.get('remote_path', '/backups/')
            remote_file = os.path.join(remote_path, selected_backup).replace('\\', '/')
            local_file = os.path.join(self.backup_local_dir, selected_backup)
            
            logger.info(f"⬇️ Скачивание бэкапа: {selected_backup}")
            
            # Получаем размер удаленного файла
            remote_file_attr = sftp.stat(remote_file)
            file_size = remote_file_attr.st_size
            
            # Создаем прогресс-бар
            progress = SFTPProgressBar(file_size, selected_backup)
            
            # Скачиваем с прогресс-баром
            sftp.get(remote_file, local_file, callback=progress)
            
            size_mb = file_size / (1024 * 1024)
            logger.success(f"✅ Бэкап скачан: {local_file} ({size_mb:.2f} MB)")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания бэкапа: {e}")
            return False
        finally:
            sftp.close()
            ssh.close()
    
    def show_sftp_backups_info(self):
        """Вывод информации об удаленных бэкапах"""
        if not self.sftp_enabled:
            logger.warning("⚠️ SFTP бэкап отключен или недоступен")
            return
        
        connection = self._connect_sftp()
        if not connection:
            return
        
        ssh, sftp = connection
        
        try:
            backups = self.list_sftp_backups()
            remote_path = self.sftp_config.get('remote_path', '/backups/')
            
            if not backups:
                logger.info("📭 На SFTP сервере нет бэкапов")
                return
            
            logger.info("=" * 60)
            logger.info(f"📋 SFTP бэкапы ({len(backups)} шт.):")
            logger.info("=" * 60)
            
            for i, backup in enumerate(backups, 1):
                remote_file = os.path.join(remote_path, backup).replace('\\', '/')
                
                try:
                    stat = sftp.stat(remote_file)
                    size_mb = stat.st_size / (1024 * 1024)
                    mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    
                    logger.info(f"{i}. {backup}")
                    logger.info(f"   Размер: {size_mb:.2f} MB | Дата: {mtime}")
                except Exception as e:
                    logger.warning(f"{i}. {backup} (ошибка получения информации: {e})")
            
            logger.info("=" * 60)
            
        finally:
            sftp.close()
            ssh.close()
    
    # ==================== ОБЩИЕ ФУНКЦИИ ====================
    
    def create_backup(self, upload_to_sftp: bool = True) -> bool:
        """
        Создание бэкапа (локального и опционально на SFTP)
        
        Args:
            upload_to_sftp: Загружать ли на SFTP сервер
            
        Returns:
            True при успехе, False при ошибке
        """
        logger.info("🚀 Создание бэкапа...")
        
        # Создаем локальный бэкап
        backup_path = self.create_local_backup()
        if not backup_path:
            return False
        
        # Загружаем на SFTP если включено
        if upload_to_sftp and self.sftp_enabled:
            self.upload_to_sftp(backup_path)
            self.cleanup_old_sftp_backups()
        
        # Очищаем старые локальные бэкапы
        self.cleanup_old_local_backups()
        
        logger.success("✅ Бэкап завершен")
        
        return True
    
    def test_sftp_connection(self) -> bool:
        """Тестирование подключения к SFTP серверу"""
        if not self.sftp_enabled:
            logger.warning("⚠️ SFTP бэкап отключен или недоступен")
            return False
        
        logger.info("🧪 Тестирование подключения к SFTP серверу...")
        
        connection = self._connect_sftp()
        if connection:
            ssh, sftp = connection
            sftp.close()
            ssh.close()
            logger.success("✅ Подключение успешно!")
            return True
        else:
            logger.error("❌ Не удалось подключиться к SFTP серверу")
            return False


# Совместимость со старым API
def create_backup():
    """Создание бэкапа (старая функция для совместимости)"""
    manager = BackupManager()
    manager.create_backup()

def list_backups():
    """Список бэкапов (старая функция для совместимости)"""
    manager = BackupManager()
    manager.show_local_backups_info()


if __name__ == '__main__':
    # Тестирование модуля
    manager = BackupManager()
    
    # Создаем бэкап
    manager.create_backup()
    
    # Показываем локальные бэкапы
    manager.show_local_backups_info()
    
    # Если SFTP включен, показываем и SFTP бэкапы
    if manager.sftp_enabled:
        manager.show_sftp_backups_info()
