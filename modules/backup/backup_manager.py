"""
Модуль управления бэкапами
Объединяет локальное и SFTP резервное копирование
"""

import os
import sys
import shutil
import zipfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple
from loguru import logger

# Добавляем путь к корневой директории проекта
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
sys.path.append(project_root)

# Импорт настроек
from config.config import (
    SFTP_SERVER_INTO_BACKUP_ENABLE,
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

# Настройка логирования
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
    colorize=True
)

# Добавляем файл для логирования
log_dir = os.path.join(project_root, 'log')
os.makedirs(log_dir, exist_ok=True)
logger.add(
    os.path.join(log_dir, 'backup.log'),
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    level="DEBUG",
    rotation="10 MB",
    retention="30 days"
)


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
        self.project_root = project_root
        self.backup_local_dir = os.path.join(self.project_root, 'backups')
        self.sftp_config = SFTP_SERVER_INTO_BACKUP
        self.sftp_enabled = SFTP_SERVER_INTO_BACKUP_ENABLE and PARAMIKO_AVAILABLE
        
        # Создаем локальную директорию для бэкапов
        os.makedirs(self.backup_local_dir, exist_ok=True)
    
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
            
            logger.info(f"📦 Создание локального бэкапа: {backup_filename}")
            
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for directory in DIRECTORIES_TO_BACKUP:
                    dir_path = os.path.join(self.project_root, directory)
                    
                    if not os.path.exists(dir_path):
                        logger.warning(f"⚠️ Директория не найдена: {directory}")
                        continue
                    
                    logger.info(f"📁 Добавление директории: {directory}")
                    
                    # Добавляем все файлы из директории
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
                logger.info(f"📊 Локальных бэкапов: {len(backups)}/{MAX_BACKUPS_TO_KEEP}")
                return
            
            backups_to_delete = backups[MAX_BACKUPS_TO_KEEP:]
            
            logger.info(f"🗑️ Удаление старых локальных бэкапов: {len(backups_to_delete)} шт.")
            
            for backup in backups_to_delete:
                backup_path = os.path.join(self.backup_local_dir, backup)
                try:
                    os.remove(backup_path)
                    logger.info(f"🗑️ Удален: {backup}")
                except Exception as e:
                    logger.error(f"❌ Ошибка удаления {backup}: {e}")
            
            logger.success(f"✅ Очистка завершена. Осталось бэкапов: {MAX_BACKUPS_TO_KEEP}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка очистки старых бэкапов: {e}")
    
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
    
    def _connect_sftp(self) -> Optional[Tuple[paramiko.SSHClient, paramiko.SFTPClient]]:
        """Подключение к SFTP серверу"""
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
            
            logger.info(f"🔐 Подключение к SFTP серверу {host}:{port}...")
            
            # Подключение с ключом или паролем
            if key_file and os.path.exists(key_file):
                logger.info(f"🔑 Использование ключа: {key_file}")
                ssh.connect(hostname=host, port=port, username=username, key_filename=key_file, timeout=30)
            elif password:
                logger.info("🔑 Использование пароля для авторизации")
                ssh.connect(hostname=host, port=port, username=username, password=password, timeout=30)
            else:
                logger.error("❌ Не указан ни пароль, ни файл ключа")
                return None
            
            sftp = ssh.open_sftp()
            logger.success(f"✅ Успешное подключение к SFTP серверу")
            
            return ssh, sftp
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к SFTP: {e}")
            return None
    
    def upload_to_sftp(self, local_file: str) -> bool:
        """Загрузка файла на SFTP сервер"""
        if not self.sftp_enabled:
            logger.warning("⚠️ SFTP бэкап отключен или недоступен")
            return False
        
        connection = self._connect_sftp()
        if not connection:
            return False
        
        ssh, sftp = connection
        
        try:
            remote_path = self.sftp_config.get('remote_path', '/backups/')
            filename = os.path.basename(local_file)
            remote_file = os.path.join(remote_path, filename).replace('\\', '/')
            
            # Создаем удаленную директорию если её нет
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                logger.info(f"📁 Создание удаленной директории: {remote_path}")
                self._create_remote_directory(sftp, remote_path)
            
            logger.info(f"⬆️ Загрузка файла на SFTP сервер: {filename}")
            
            # Получаем размер файла и создаем прогресс-бар
            file_size = os.path.getsize(local_file)
            progress = SFTPProgressBar(file_size, filename)
            
            # Загружаем с прогресс-баром
            sftp.put(local_file, remote_file, callback=progress)
            
            size_mb = file_size / (1024 * 1024)
            logger.success(f"✅ Файл загружен на SFTP: {remote_file} ({size_mb:.2f} MB)")
            
            return True
            
        except Exception as e:
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
        
        connection = self._connect_sftp()
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
        
        connection = self._connect_sftp()
        if not connection:
            return
        
        ssh, sftp = connection
        
        try:
            backups = self.list_sftp_backups()
            
            if len(backups) <= MAX_BACKUPS_TO_KEEP:
                logger.info(f"📊 SFTP бэкапов: {len(backups)}/{MAX_BACKUPS_TO_KEEP}")
                return
            
            remote_path = self.sftp_config.get('remote_path', '/backups/')
            backups_to_delete = backups[MAX_BACKUPS_TO_KEEP:]
            
            logger.info(f"🗑️ Удаление старых SFTP бэкапов: {len(backups_to_delete)} шт.")
            
            for backup in backups_to_delete:
                remote_file = os.path.join(remote_path, backup).replace('\\', '/')
                try:
                    sftp.remove(remote_file)
                    logger.info(f"🗑️ Удален: {backup}")
                except Exception as e:
                    logger.error(f"❌ Ошибка удаления {backup}: {e}")
            
            logger.success(f"✅ Очистка завершена. Осталось бэкапов: {MAX_BACKUPS_TO_KEEP}")
            
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
        logger.info("=" * 60)
        logger.info("🚀 Запуск создания бэкапа")
        logger.info("=" * 60)
        
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
        
        logger.info("=" * 60)
        logger.success("✅ Создание бэкапа завершено")
        logger.info("=" * 60)
        
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
