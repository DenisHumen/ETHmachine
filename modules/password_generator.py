import random
import string
import csv
import os
import logging
import sys
import time

# Логирование в log/password_generator.log
os.makedirs("log", exist_ok=True)
logger = logging.getLogger("password_generator")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
if not logger.handlers:
    fh = logging.FileHandler("log/password_generator.log")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

# Импорт параметров из config/config.py
from config.config import (
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
    try:
        total = COUNT_GENERATED_PASSWORDS
        logger.info(f"Start generating {total} passwords")
        for i in range(1, total + 1):
            password = generate_password()
            save_password(password)
            logger.info(f"Password generated: {password}")
            print_progress_bar(i, total)
            # time.sleep(0.05)  # Можно убрать или уменьшить задержку
        print()  # Перевод строки после прогресс-бара
        logger.info("Password generation completed")
    except Exception as e:
        logger.error(f"Error generating password: {e}")

