import os
import zipfile
import shutil
import sys
from pathlib import Path
from datetime import datetime
from colorama import Fore, Style, init

init()

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from config.config import MAX_BACKUPS_TO_KEEP, DIRECTORIES_TO_BACKUP

def create_backup():
    """
    Создает архив backup с важными данными проекта
    """
    print(Fore.MAGENTA + "\n" + "="*60)
    print(Fore.YELLOW + "🗂️ Запуск модуля автоматического резервного копирования")
    print(Fore.MAGENTA + "="*60)
    
    backup_dir = project_root / 'backups'
    backup_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"backup_{timestamp}.zip"
    backup_path = backup_dir / backup_filename
    
    dirs_to_backup = DIRECTORIES_TO_BACKUP
    
    print(Fore.CYAN + f"📁 Директории для архивирования: {', '.join(dirs_to_backup)}")
    
    print(Fore.CYAN + "🔍 Проверка существующих архивов backup...")
    existing_backups = sorted(backup_dir.glob("backup_*.zip"), key=lambda x: x.stat().st_ctime)
    
    backups_to_remove = len(existing_backups) - (MAX_BACKUPS_TO_KEEP - 1)
    old_backups_removed = 0
    
    if backups_to_remove > 0:
        for backup_file in existing_backups[:backups_to_remove]:
            try:
                backup_file.unlink()
                old_backups_removed += 1
                print(Fore.YELLOW + f"🗑️ Удален старый архив: {backup_file.name}")
            except Exception as e:
                print(Fore.RED + f"❌ Ошибка удаления {backup_file.name}: {e}")
    
    if old_backups_removed == 0:
        print(Fore.GREEN + f"✅ Удаление не требуется (лимит: {MAX_BACKUPS_TO_KEEP} архивов)")
    else:
        print(Fore.GREEN + f"✅ Удалено {old_backups_removed} старых архивов (лимит: {MAX_BACKUPS_TO_KEEP})")
    
    print(Fore.CYAN + f"\n📦 Создание нового архива: {backup_filename}")
    
    files_added = 0
    dirs_found = 0
    total_files_per_dir = {}
    
    try:
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for dir_path in dirs_to_backup:
                full_dir_path = project_root / dir_path
                
                if not full_dir_path.exists():
                    print(Fore.YELLOW + f"⚠️ Директория не найдена: {dir_path}")
                    total_files_per_dir[dir_path] = 0
                    continue
                
                if not full_dir_path.is_dir():
                    print(Fore.YELLOW + f"⚠️ Путь не является директорией: {dir_path}")
                    total_files_per_dir[dir_path] = 0
                    continue
                
                dirs_found += 1
                files_in_dir = 0
                print(Fore.GREEN + f"📁 Архивирование директории: {dir_path}")
                
                for root, dirs, files in os.walk(full_dir_path):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(project_root)
                        
                        try:
                            zipf.write(file_path, arcname)
                            files_added += 1
                            files_in_dir += 1
                            
                            if files_added % 50 == 0:
                                print(Fore.BLUE + f"  📄 Добавлено файлов: {files_added}", end='\r')
                        except Exception as e:
                            print(Fore.RED + f"\n❌ Ошибка добавления файла {file_path}: {e}")
                
                total_files_per_dir[dir_path] = files_in_dir
                if files_in_dir > 0:
                    print(Fore.BLUE + f"  📄 Файлов в {dir_path}: {files_in_dir}")
                else:
                    print(Fore.YELLOW + f"  📭 Директория {dir_path} пуста")
        
        backup_size = backup_path.stat().st_size
        backup_size_mb = backup_size / (1024 * 1024)
        
        print(Fore.MAGENTA + "\n" + "-"*60)
        print(Fore.GREEN + "✅ Резервное копирование завершено успешно!")
        print(Fore.CYAN + f"📦 Имя архива: {backup_filename}")
        print(Fore.CYAN + f"📊 Размер архива: {backup_size_mb:.2f} MB")
        print(Fore.CYAN + f"📁 Директорий обработано: {dirs_found}/{len(dirs_to_backup)}")
        print(Fore.CYAN + f"📄 Файлов заархивировано: {files_added}")
        print(Fore.CYAN + f"💾 Путь к архиву: {backup_path}")
        
        print(Fore.CYAN + "\n📋 Детализация по директориям:")
        for dir_name, file_count in total_files_per_dir.items():
            status = "✅" if file_count > 0 else ("⚠️" if file_count == 0 else "❌")
            print(Fore.CYAN + f"  {status} {dir_name}: {file_count} файлов")
        
        if dirs_found == 0:
            print(Fore.YELLOW + "\n⚠️ Ни одна из указанных директорий не найдена!")
            print(Fore.YELLOW + "💡 Убедитесь, что существуют директории:")
            for dir_path in dirs_to_backup:
                print(Fore.YELLOW + f"   - {dir_path}")
        elif files_added == 0:
            print(Fore.YELLOW + "\n⚠️ В найденных директориях нет файлов для архивирования!")
        
        print(Fore.MAGENTA + "="*60 + "\n")
        
        return str(backup_path)
        
    except Exception as e:
        print(Fore.RED + f"\n❌ Ошибка создания архива: {e}")
        
        if backup_path.exists():
            try:
                backup_path.unlink()
                print(Fore.YELLOW + "🗑️ Поврежденный архив удален")
            except Exception as cleanup_error:
                print(Fore.RED + f"❌ Ошибка удаления поврежденного архива: {cleanup_error}")
        
        print(Fore.MAGENTA + "="*60 + "\n")
        return None

def get_backup_info():
    """
    Возвращает информацию о существующих архивах backup
    """
    backup_dir = project_root / 'backups'
    if not backup_dir.exists():
        return None
        
    backup_files = list(backup_dir.glob("backup_*.zip"))
    
    if not backup_files:
        return None
    
    backup_info = []
    for backup_file in sorted(backup_files, key=lambda x: x.stat().st_ctime, reverse=True):
        try:
            stat = backup_file.stat()
            size_mb = stat.st_size / (1024 * 1024)
            creation_time = datetime.fromtimestamp(stat.st_ctime)
            
            backup_info.append({
                'filename': backup_file.name,
                'path': str(backup_file),
                'size_mb': size_mb,
                'created': creation_time
            })
        except Exception as e:
            print(Fore.RED + f"❌ Ошибка получения информации о {backup_file.name}: {e}")
    
    return backup_info

def list_backups():
    """
    Выводит список существующих архивов backup
    """
    print(Fore.MAGENTA + "\n" + "="*60)
    print(Fore.YELLOW + f"📋 Список существующих архивов backup (лимит: {MAX_BACKUPS_TO_KEEP})")
    print(Fore.MAGENTA + "="*60)
    
    backup_info = get_backup_info()
    
    if not backup_info:
        print(Fore.YELLOW + "📭 Архивы backup не найдены")
        print(Fore.CYAN + f"📁 Директория: {project_root / 'backups'}")
        print(Fore.MAGENTA + "="*60 + "\n")
        return
    
    print(Fore.CYAN + f"📁 Директория: {project_root / 'backups'}")
    print(Fore.CYAN + f"📊 Найдено архивов: {len(backup_info)}/{MAX_BACKUPS_TO_KEEP}")
    print()
    
    for i, info in enumerate(backup_info, 1):
        status_marker = ""
        if len(backup_info) > MAX_BACKUPS_TO_KEEP and i == len(backup_info):
            status_marker = f" {Fore.RED}[БУДЕТ УДАЛЕН ПРИ СЛЕДУЮЩЕМ BACKUP]{Fore.RESET}"
        
        print(Fore.CYAN + f"{i}. {info['filename']}{status_marker}")
        print(Fore.GREEN + f"   📊 Размер: {info['size_mb']:.2f} MB")
        print(Fore.GREEN + f"   📅 Создан: {info['created'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(Fore.BLUE + f"   📁 Путь: {info['path']}")
        if i < len(backup_info):
            print()
    
    if len(backup_info) > MAX_BACKUPS_TO_KEEP:
        excess = len(backup_info) - MAX_BACKUPS_TO_KEEP
        print(Fore.YELLOW + f"\n⚠️ Превышен лимит на {excess} архив(ов). Лишние будут удалены при следующем backup.")
    
    print(Fore.MAGENTA + "="*60 + "\n")
