import random
import string
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from loguru import logger

# Настройка логирования для модуля password_generator
def setup_password_generator_logging():
    """Настраивает логирование для генератора паролей"""
    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f'password_generator_{timestamp}.log'
    
    # Добавляем обработчик для записи в файл
    logger.add(
        log_file,
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level="DEBUG",
        encoding="utf-8"
    )
    
    logger.info(f"Логирование настроено. Файл: {log_file}")

# Импорт параметров из config/modules/cfg_password.py
from config.modules.cfg_password import (
    USE_SPECIAL_CHARACTERS,
    EXCLUDE_CHARACTERS,
    USE_OF_SYMBOLS_IS_MANDATORY,
    PASSWORD_LENGTH,
    COUNT_GENERATED_PASSWORDS,
)

def get_charset():
    charset = list(string.ascii_letters + string.digits)
    if USE_SPECIAL_CHARACTERS:
        charset += list(string.punctuation)
    charset = [c for c in charset if c not in EXCLUDE_CHARACTERS]
    return charset

def generate_password():
    min_len, max_len = PASSWORD_LENGTH
    length = random.randint(min_len, max_len)
    charset = get_charset()
    if not charset:
        raise ValueError("Charset is empty after exclusions.")
    password = []
    # Гарантировать наличие обязательных символов
    for symbol in USE_OF_SYMBOLS_IS_MANDATORY:
        password.append(symbol)
    # Остальные символы
    while len(password) < length:
        c = random.choice(charset)
        password.append(c)
    random.shuffle(password)
    return ''.join(password[:length])

def save_password(password):
    os.makedirs("result", exist_ok=True)
    file_path = "result/password_generator.csv"
    write_header = not os.path.exists(file_path)
    with open(file_path, "a", newline="") as csvfile:
        writer = csv.writer(csvfile)
        if write_header:
            writer.writerow(["password"])
        writer.writerow([password])

def print_progress_bar(iteration, total, length=40):
    percent = 100 * (iteration / float(total))
    filled_length = int(length * iteration // total)
    bar = '█' * filled_length + '░' * (length - filled_length)
    print(f'\r[{bar}] {iteration}/{total} ({percent:.1f}%)', end='', flush=True)

def password_generator_menu():
    # Настраиваем логирование
    setup_password_generator_logging()
    
    try:
        total = COUNT_GENERATED_PASSWORDS
        logger.info(f"Начинаем генерацию {total} паролей")
        logger.info(f"Параметры: длина {PASSWORD_LENGTH}, спец. символы: {USE_SPECIAL_CHARACTERS}")
        
        for i in range(1, total + 1):
            password = generate_password()
            save_password(password)
            logger.debug(f"Пароль сгенерирован: {password}")
            print_progress_bar(i, total)
            
        print()  # Перевод строки после прогресс-бара
        logger.success(f"Генерация паролей завершена. Создано: {total} паролей")
        logger.info("Результаты сохранены в result/password_generator.csv")
        
    except Exception as e:
        logger.error(f"Ошибка при генерации пароля: {e}")
        raise

