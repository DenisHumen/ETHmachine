import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from loguru import logger
import sys

# Убираем стандартный обработчик
logger.remove()

# Настраиваем пути для логирования
project_root = Path(__file__).resolve().parent.parent
log_dir = project_root / 'log'  # Корневая директория log/
log_dir.mkdir(parents=True, exist_ok=True)

# Добавляем консольный вывод
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO"
)

# Добавляем файловое логирование с ротацией (НЕ создает новый файл каждый раз)
logger.add(
    log_dir / "auto_backup.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="INFO",
    rotation="10 MB",  # Ротация по размеру
    retention="30 days",  # Хранить логи 30 дней
    compression="zip"  # Сжимать старые логи
)

def create_backup():
    """Создает резервную копию важных файлов"""
    
    try:
        # Создаем директорию для бэкапов
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = backup_dir / f"backup_{timestamp}.zip"
        
        logger.info("🔄 Начинаем создание резервной копии...")
        
        # Список директорий и файлов для бэкапа
        items_to_backup = [
            "config/",
            "data/",
            "result/",
            "db/",
            "README.md"
        ]
        
        with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for item in items_to_backup:
                item_path = Path(item)
                
                if item_path.is_file():
                    if item_path.exists():
                        zipf.write(item_path, item_path)
                        logger.info(f"📄 Добавлен файл: {item}")
                    else:
                        logger.warning(f"⚠️ Файл не найден: {item}")
                        
                elif item_path.is_dir():
                    if item_path.exists():
                        for file_path in item_path.rglob('*'):
                            if file_path.is_file():
                                # Относительный путь для архива
                                arcname = file_path.relative_to('.')
                                zipf.write(file_path, arcname)
                        logger.info(f"📁 Добавлена директория: {item}")
                    else:
                        logger.warning(f"⚠️ Директория не найдена: {item}")
        
        # Проверяем размер созданного архива
        backup_size = backup_filename.stat().st_size
        backup_size_mb = backup_size / (1024 * 1024)
        
        logger.success(f"✅ Резервная копия создана: {backup_filename}")
        logger.info(f"📦 Размер архива: {backup_size_mb:.2f} MB")
        
        # Очистка старых бэкапов (оставляем только последние 5)
        cleanup_old_backups(backup_dir)
        
        return str(backup_filename)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании резервной копии: {e}")
        raise

def cleanup_old_backups(backup_dir, keep_count=5):
    """Удаляет старые бэкапы, оставляя только последние keep_count"""
    try:
        backup_files = list(backup_dir.glob("backup_*.zip"))
        
        if len(backup_files) <= keep_count:
            logger.info(f"📁 Всего бэкапов: {len(backup_files)}, очистка не требуется")
            return
        
        # Сортируем по времени создания (старые первыми)
        backup_files.sort(key=lambda x: x.stat().st_mtime)
        
        # Удаляем старые файлы
        files_to_delete = backup_files[:-keep_count]
        
        for file_path in files_to_delete:
            file_path.unlink()
            logger.info(f"🗑️ Удален старый бэкап: {file_path.name}")
        
        logger.info(f"🧹 Очистка завершена. Удалено: {len(files_to_delete)} файлов")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при очистке старых бэкапов: {e}")

def restore_backup(backup_path):
    """Восстанавливает данные из резервной копии"""
    
    try:
        backup_file = Path(backup_path)
        
        if not backup_file.exists():
            logger.error(f"❌ Файл бэкапа не найден: {backup_path}")
            return False
        
        logger.info(f"🔄 Начинаем восстановление из: {backup_path}")
        
        # Создаем временную директорию для распаковки
        temp_dir = Path("temp_restore")
        temp_dir.mkdir(exist_ok=True)
        
        try:
            with zipfile.ZipFile(backup_file, 'r') as zipf:
                zipf.extractall(temp_dir)
            
            logger.info("📦 Архив успешно распакован")
            
            # Перемещаем файлы на свои места
            for item in temp_dir.rglob('*'):
                if item.is_file():
                    relative_path = item.relative_to(temp_dir)
                    target_path = Path(relative_path)
                    
                    # Создаем директории если нужно
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Копируем файл
                    shutil.copy2(item, target_path)
                    logger.debug(f"📄 Восстановлен: {relative_path}")
            
            logger.success("✅ Восстановление завершено успешно")
            return True
            
        finally:
            # Удаляем временную директорию
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                logger.info("🧹 Временные файлы удалены")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при восстановлении: {e}")
        return False

def auto_backup_menu():
    """Главное меню модуля резервного копирования"""
    
    try:
        logger.info("🚀 Запуск модуля автоматического резервного копирования")
        
        while True:
            logger.info("\n" + "="*50)
            logger.info("🔧 МЕНЮ РЕЗЕРВНОГО КОПИРОВАНИЯ")
            logger.info("="*50)
            logger.info("1. 💾 Создать резервную копию")
            logger.info("2. 📂 Просмотреть существующие бэкапы")
            logger.info("3. 🔄 Восстановить из бэкапа")
            logger.info("4. 🧹 Очистить старые бэкапы")
            logger.info("5. 🚪 Выход")
            
            choice = input("\nВыберите действие (1-5): ").strip()
            
            if choice == '1':
                backup_file = create_backup()
                logger.success(f"✅ Бэкап создан: {backup_file}")
                
            elif choice == '2':
                list_backups()
                
            elif choice == '3':
                backup_path = input("Введите путь к файлу бэкапа: ").strip()
                if restore_backup(backup_path):
                    logger.success("✅ Восстановление завершено")
                else:
                    logger.error("❌ Ошибка восстановления")
                    
            elif choice == '4':
                backup_dir = Path("backups")
                if backup_dir.exists():
                    cleanup_old_backups(backup_dir, keep_count=3)
                else:
                    logger.warning("⚠️ Директория бэкапов не найдена")
                    
            elif choice == '5':
                logger.info("👋 Выход из модуля резервного копирования")
                break
                
            else:
                logger.warning("⚠️ Неверный выбор. Попробуйте снова.")
                
    except KeyboardInterrupt:
        logger.info("\n👋 Выход из программы по запросу пользователя")
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}")

def list_backups():
    """Показывает список доступных бэкапов"""
    try:
        backup_dir = Path("backups")
        
        if not backup_dir.exists():
            logger.warning("⚠️ Директория бэкапов не найдена")
            return
        
        backup_files = list(backup_dir.glob("backup_*.zip"))
        
        if not backup_files:
            logger.warning("⚠️ Бэкапы не найдены")
            return
        
        # Сортируем по времени создания (новые первыми)
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        logger.info(f"\n📁 Найдено бэкапов: {len(backup_files)}")
        logger.info("-" * 50)
        
        for i, backup_file in enumerate(backup_files, 1):
            stat = backup_file.stat()
            size_mb = stat.st_size / (1024 * 1024)
            mtime = datetime.fromtimestamp(stat.st_mtime)
            
            logger.info(f"{i}. {backup_file.name}")
            logger.info(f"   📅 Создан: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"   📦 Размер: {size_mb:.2f} MB")
            logger.info("")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при получении списка бэкапов: {e}")

if __name__ == "__main__":
    auto_backup_menu()
