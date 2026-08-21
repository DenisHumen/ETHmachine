"""
Python wrapper для Rust версии генератора nice адресов
Автоматически компилирует и запускает Rust бинарник
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from colorama import Fore, Style
import questionary

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Обёртку запускают и напрямую (`python eth_nice_address_rust_wrapper.py`),
# когда корня проекта нет в sys.path — иначе импорт ниже развалится.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from modules.eth.eth_wallet_generator import new_wallets_file

def check_cargo_installed():
    """Проверка установки Cargo (Rust)"""
    try:
        result = subprocess.run(
            ["cargo", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"{Fore.GREEN}✓ Cargo установлен: {version}{Style.RESET_ALL}")
            return True
        else:
            return False
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"{Fore.RED}Ошибка проверки Cargo: {e}{Style.RESET_ALL}")
        return False

def install_cargo_instructions():
    """Инструкции по установке Cargo"""
    print(f"\n{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.RED}❌ Cargo (Rust) не установлен!{Style.RESET_ALL}")
    print(f"\n{Fore.CYAN}Для установки Rust выполните:{Style.RESET_ALL}")
    print(f"\n{Fore.WHITE}macOS/Linux:{Style.RESET_ALL}")
    print(f"  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")
    print(f"\n{Fore.WHITE}Windows:{Style.RESET_ALL}")
    print(f"  Скачайте установщик: https://rustup.rs/")
    print(f"\n{Fore.CYAN}После установки перезапустите терминал и попробуйте снова.{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}{'='*60}{Style.RESET_ALL}\n")

def compile_rust_binary(force_rebuild=False):
    """Компиляция Rust бинарника"""
    rust_dir = Path(__file__).parent / "rust"
    binary_path = rust_dir / "target" / "release" / "eth_nice_address"
    
    # Проверяем, существует ли уже скомпилированный бинарник
    if binary_path.exists() and not force_rebuild:
        print(f"{Fore.GREEN}✓ Rust бинарник уже скомпилирован{Style.RESET_ALL}")
        return str(binary_path)
    
    print(f"\n{Fore.CYAN}🔨 Компиляция Rust версии...{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Это может занять несколько минут при первой компиляции{Style.RESET_ALL}\n")
    
    try:
        # Компиляция в release режиме для максимальной производительности
        result = subprocess.run(
            ["cargo", "build", "--release"],
            cwd=str(rust_dir),
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"{Fore.GREEN}✓ Компиляция успешна!{Style.RESET_ALL}")
            return str(binary_path)
        else:
            print(f"{Fore.RED}❌ Ошибка компиляции:{Style.RESET_ALL}")
            print(result.stderr)
            return None
            
    except Exception as e:
        print(f"{Fore.RED}❌ Ошибка при компиляции: {e}{Style.RESET_ALL}")
        return None

def run_rust_generator(num_wallets, config_path="config/modules/cfg_nice_address.py", 
                       output_path="result/result.csv", threads=0, display_process=False):
    """Запуск Rust генератора.

    Ключи бинарник пишет в собственный файл запуска (result/wallets/...),
    а в ``output_path`` кладётся копия — result/result.csv затирают чекеры
    балансов, и мнемоники оттуда пропадают безвозвратно.
    """

    # Проверяем Cargo
    if not check_cargo_installed():
        install_cargo_instructions()
        return False
    
    # Компилируем бинарник
    binary_path = compile_rust_binary()
    if not binary_path:
        print(f"{Fore.RED}❌ Не удалось скомпилировать Rust версию{Style.RESET_ALL}")
        return False
    
    print(f"\n{Fore.CYAN}🚀 Запуск Rust генератора...{Style.RESET_ALL}\n")
    
    # Пути должны быть абсолютными: бинарник запускается с другим cwd
    abs_config_path = PROJECT_ROOT / config_path
    abs_output_path = PROJECT_ROOT / output_path
    keys_path = new_wallets_file('eth_nice_wallets', PROJECT_ROOT / 'result' / 'wallets')

    # Создаем директорию для результатов если её нет
    abs_output_path.parent.mkdir(parents=True, exist_ok=True)

    # Формируем команду
    cmd = [
        str(binary_path),
        "-n", str(num_wallets),
        "-c", str(abs_config_path),
        "-o", str(keys_path),
        "-t", str(threads)
    ]
    
    if display_process:
        cmd.append("-d")
    
    try:
        # Запускаем процесс
        result = subprocess.run(cmd, cwd=os.path.dirname(binary_path))
        
        if result.returncode == 0:
            # Копию кладём туда, куда исторически смотрят пользователи и меню.
            if keys_path.exists() and keys_path != abs_output_path:
                shutil.copyfile(keys_path, abs_output_path)
            print(f"\n{Fore.GREEN}✓ Генерация завершена успешно!{Style.RESET_ALL}")
            print(f"{Fore.GREEN}✓ Ключи сохранены в {keys_path}{Style.RESET_ALL}")
            return True
        else:
            print(f"\n{Fore.RED}❌ Ошибка при выполнении{Style.RESET_ALL}")
            return False
            
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⚠ Генерация прервана пользователем{Style.RESET_ALL}")
        # Поиск идёт часами — найденное до обрыва лежит в файле запуска.
        if keys_path.exists():
            print(f"{Fore.YELLOW}Найденное сохранено в {keys_path}{Style.RESET_ALL}")
        return False
    except Exception as e:
        print(f"{Fore.RED}❌ Ошибка: {e}{Style.RESET_ALL}")
        return False

def main():
    """Основная функция для тестирования"""
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  ETH Nice Address Generator - Rust Wrapper{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # Получаем количество кошельков
    num_wallets = questionary.text(
        "Сколько nice кошельков сгенерировать?",
        default="10"
    ).ask()
    
    try:
        num_wallets = int(num_wallets)
    except ValueError:
        print(f"{Fore.RED}❌ Неверное число{Style.RESET_ALL}")
        return
    
    # Количество потоков
    threads = questionary.text(
        "Количество потоков (0 = auto):",
        default="0"
    ).ask()
    
    try:
        threads = int(threads)
    except ValueError:
        threads = 0
    
    # Отображение процесса
    display_process = questionary.confirm(
        "Отображать процесс поиска?",
        default=True
    ).ask()
    
    # Запускаем генератор
    success = run_rust_generator(
        num_wallets=num_wallets,
        threads=threads,
        display_process=display_process
    )
    
    if success:
        print(f"\n{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}✓ Ключи — в result/wallets/, копия в result/result.csv{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'='*60}{Style.RESET_ALL}\n")

if __name__ == "__main__":
    main()
