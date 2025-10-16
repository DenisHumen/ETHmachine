"""
Интерактивное меню для управления бэкапами
"""

import os
import sys
from questionary import select, Choice, confirm
from loguru import logger

# Добавляем путь к корневой директории проекта
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
sys.path.append(project_root)

from modules.backup.backup_manager import BackupManager
from config import config


def toggle_sftp_backup():
    """Включение/выключение SFTP бэкапа"""
    
    current_status = config.SFTP_SERVER_INTO_BACKUP_ENABLE
    status_text = "✅ Включен" if current_status else "❌ Выключен"
    
    logger.info("=" * 60)
    logger.info("⚙️  НАСТРОЙКА SFTP БЭКАПА")
    logger.info("=" * 60)
    logger.info(f"Текущий статус: {status_text}")
    logger.info("=" * 60)
    
    choice = select(
        "Что вы хотите сделать?",
        choices=[
            Choice("✅ Включить SFTP бэкап", "enable"),
            Choice("❌ Выключить SFTP бэкап", "disable"),
            Choice("🔙 Вернуться в меню", "back")
        ]
    ).ask()
    
    if choice == "back":
        return
    
    new_status = choice == "enable"
    
    if new_status == current_status:
        action = "включен" if new_status else "выключен"
        logger.info(f"ℹ️  SFTP бэкап уже {action}")
        return
    
    # Если включаем, проверяем настройки
    if new_status:
        manager = BackupManager()
        sftp_config = config.SFTP_SERVER_INTO_BACKUP
        
        if not sftp_config.get('host') or not sftp_config.get('username'):
            logger.error("❌ Не настроены параметры SFTP сервера!")
            logger.error("📝 Отредактируйте файл config/config.py и укажите:")
            logger.error("   - host: адрес SFTP сервера")
            logger.error("   - username: имя пользователя")
            logger.error("   - password или key_file: авторизация")
            return
        
        # Тестируем подключение
        logger.info("🧪 Тестирование подключения к SFTP серверу...")
        if not manager.test_sftp_connection():
            logger.error("❌ Не удалось подключиться к SFTP серверу")
            logger.error("📝 Проверьте настройки в config/config.py")
            
            force_enable = confirm(
                "Все равно включить SFTP бэкап?",
                default=False
            ).ask()
            
            if not force_enable:
                return
    
    # Обновляем настройку в файле конфигурации
    config_path = os.path.join(project_root, 'config', 'config.py')
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Заменяем значение
        old_line = f"SFTP_SERVER_INTO_BACKUP_ENABLE = {current_status}"
        new_line = f"SFTP_SERVER_INTO_BACKUP_ENABLE = {new_status}"
        
        if old_line in content:
            content = content.replace(old_line, new_line)
            
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Обновляем в памяти
            config.SFTP_SERVER_INTO_BACKUP_ENABLE = new_status
            
            action = "включен" if new_status else "выключен"
            logger.success(f"✅ SFTP бэкап {action}")
            
            if new_status:
                logger.info("💡 Теперь при создании бэкапов они будут автоматически загружаться на SFTP сервер")
        else:
            logger.error("❌ Не удалось найти настройку в файле конфигурации")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении конфигурации: {e}")


def backup_menu():
    """Главное меню управления бэкапами"""
    
    manager = BackupManager()
    
    while True:
        sftp_status = "✅ Включен" if manager.sftp_enabled else "❌ Выключен"
        
        logger.info("=" * 60)
        logger.info(f"💾 УПРАВЛЕНИЕ БЭКАПАМИ | SFTP: {sftp_status}")
        logger.info("=" * 60)
        
        choices = [
            Choice("📦 Создать бэкап", "create"),
            Choice("📋 Показать локальные бэкапы", "list_local"),
            Choice("🔄 Восстановить из локального бэкапа", "restore_local"),
            Choice("🧹 Очистить старые локальные бэкапы", "cleanup_local"),
        ]
        
        # Добавляем SFTP опции если доступны
        if manager.sftp_enabled:
            choices.extend([
                Choice("☁️  Показать SFTP бэкапы", "list_sftp"),
                Choice("⬇️ Скачать бэкап с SFTP", "download_sftp"),
                Choice("🔄 Восстановить из SFTP бэкапа", "restore_sftp"),
                Choice("🧹 Очистить старые SFTP бэкапы", "cleanup_sftp"),
                Choice("🧪 Тест подключения к SFTP", "test_sftp"),
                Choice("⚙️  Выключить SFTP бэкап", "toggle_sftp"),
            ])
        else:
            choices.append(Choice("⚙️  Настроить SFTP бэкап", "toggle_sftp"))
        
        choices.append(Choice("🔙 Вернуться в главное меню", "back"))
        
        choice = select(
            "Выберите действие:",
            choices=choices,
            qmark='💾',
            pointer='👉'
        ).ask()
        
        if choice == "back":
            break
            
        elif choice == "create":
            upload_sftp = False
            if manager.sftp_enabled:
                upload_sftp = confirm(
                    "Загрузить бэкап на SFTP сервер?",
                    default=True
                ).ask()
            
            manager.create_backup(upload_to_sftp=upload_sftp)
            
        elif choice == "list_local":
            manager.show_local_backups_info()
            
        elif choice == "restore_local":
            manager.show_local_backups_info()
            backups = manager.list_local_backups()
            
            if backups:
                backup_choices = [Choice(f"{i+1}. {b}", b) for i, b in enumerate(backups)]
                backup_choices.append(Choice("🔙 Отмена", "cancel"))
                
                selected = select(
                    "Выберите бэкап для восстановления:",
                    choices=backup_choices
                ).ask()
                
                if selected != "cancel":
                    logger.warning("⚠️  ВНИМАНИЕ! Текущие данные будут перезаписаны!")
                    
                    if confirm("Продолжить восстановление?", default=False).ask():
                        manager.restore_local_backup(selected)
                    else:
                        logger.info("❌ Отменено пользователем")
            
        elif choice == "cleanup_local":
            if confirm("Удалить старые локальные бэкапы?", default=True).ask():
                manager.cleanup_old_local_backups()
            
        elif choice == "list_sftp":
            manager.show_sftp_backups_info()
            
        elif choice == "download_sftp":
            manager.show_sftp_backups_info()
            backups = manager.list_sftp_backups()
            
            if backups:
                backup_choices = [Choice(f"{i+1}. {b}", b) for i, b in enumerate(backups)]
                backup_choices.append(Choice("🔙 Отмена", "cancel"))
                
                selected = select(
                    "Выберите бэкап для скачивания:",
                    choices=backup_choices
                ).ask()
                
                if selected != "cancel":
                    manager.download_from_sftp(selected)
            
        elif choice == "restore_sftp":
            logger.info("📥 Скачивание последнего бэкапа с SFTP...")
            
            if manager.download_from_sftp():
                logger.warning("⚠️  ВНИМАНИЕ! Текущие данные будут перезаписаны!")
                
                if confirm("Продолжить восстановление?", default=False).ask():
                    backups = manager.list_local_backups()
                    if backups:
                        manager.restore_local_backup(backups[0])
                else:
                    logger.info("❌ Отменено пользователем")
            
        elif choice == "cleanup_sftp":
            if confirm("Удалить старые SFTP бэкапы?", default=True).ask():
                manager.cleanup_old_sftp_backups()
            
        elif choice == "test_sftp":
            manager.test_sftp_connection()
            
        elif choice == "toggle_sftp":
            toggle_sftp_backup()
            # Пересоздаем manager чтобы обновить статус
            manager = BackupManager()
        
        input("\n🔄 Нажмите Enter для продолжения...")


if __name__ == '__main__':
    backup_menu()
