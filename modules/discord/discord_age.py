import requests
import json
import base64
from datetime import datetime, timezone
import csv
import random
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from config.modules.cfg_base import NUM_THREADS, SLEEP_BETWEEN_ACTIONS, RETRY_COUNT
from modules.simple_logger import logger

def decode_token_user_id(token):
    """
    Извлекает User ID из Discord токена
    """
    try:
        # Токен состоит из трех частей, разделенных точками
        parts = token.split('.')
        if len(parts) < 1:
            return None
        
        # Первая часть - это base64 закодированный User ID
        user_id_encoded = parts[0]
        
        # Добавляем padding если необходимо
        padding = 4 - (len(user_id_encoded) % 4)
        if padding != 4:
            user_id_encoded += '=' * padding
        
        # Декодируем base64
        user_id_bytes = base64.b64decode(user_id_encoded)
        user_id = user_id_bytes.decode('utf-8')
        
        return user_id
    except Exception as e:
        logger.error(f"Ошибка при декодировании токена: {e}")
        return None

def read_tokens(file_path=None):
    """Читает Discord-токены из data.csv"""
    from modules.data_manager import get_discord_tokens
    return get_discord_tokens()

def read_proxies(file_path=None):
    """Читает прокси из data.csv"""
    from modules.data_manager import get_proxies
    return get_proxies()

def get_proxy_dict(proxy_string):
    """Преобразует строку прокси в формат для requests"""
    try:
        # Формат: login:pass@ip:port
        if '@' in proxy_string:
            auth_part, address_part = proxy_string.split('@')
            login, password = auth_part.split(':')
            ip, port = address_part.split(':')
            
            proxy_url = f"http://{login}:{password}@{ip}:{port}"
            return {
                'http': proxy_url,
                'https': proxy_url
            }
        else:
            # Если нет авторизации: ip:port
            ip, port = proxy_string.split(':')
            proxy_url = f"http://{ip}:{port}"
            return {
                'http': proxy_url,
                'https': proxy_url
            }
    except Exception as e:
        logger.error(f"Ошибка при обработке прокси {proxy_string}: {e}")
        return None

def select_proxy(proxies, tokens, index):
    """Выбирает прокси для токена"""
    if not proxies:
        return None
    
    if len(proxies) >= len(tokens):
        # 1к1 если прокси больше или равно токенам
        return proxies[index]
    else:
        # Рандомно если прокси меньше
        return random.choice(proxies)

def get_account_age_via_api_with_proxy(token, proxy_dict=None):
    """
    Получает возраст Discord аккаунта через API с использованием прокси
    """
    session = None
    try:
        headers = {
            'Authorization': token,
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Создаем сессию для управления соединениями
        session = requests.Session()
        if proxy_dict:
            session.proxies.update(proxy_dict)
        session.headers.update(headers)
        
        # Запрос с сессией
        response = session.get(
            'https://discord.com/api/v10/users/@me', 
            timeout=30
        )
        
        if response.status_code == 200:
            user_data = response.json()
            user_id = user_data['id']
            username = user_data.get('username', 'Unknown')
            discriminator = user_data.get('discriminator', '0000')
            
            creation_timestamp = ((int(user_id) >> 22) + 1420070400000) / 1000
            creation_date = datetime.fromtimestamp(creation_timestamp, tz=timezone.utc)
            current_date = datetime.now(tz=timezone.utc)
            account_age = current_date - creation_date
            days = account_age.days
            years = days // 365
            remaining_days = days % 365
            
            return {
                'status': 'success',
                'username': username,
                'discriminator': discriminator,
                'user_id': user_id,
                'creation_date': creation_date.strftime('%Y-%m-%d %H:%M:%S UTC'),
                'age_days': days,
                'age_years': years,
                'remaining_days': remaining_days,
                'token': token
            }
            
        elif response.status_code == 401:
            user_id = decode_token_user_id(token)
            if user_id:
                result = calculate_age_from_id(user_id)
                if result:
                    result['status'] = 'token_decoded'
                    result['token'] = token
                    return result
            
            return {
                'status': 'invalid_token',
                'token': token,
                'error': 'Invalid token'
            }
            
        else:
            return {
                'status': 'api_error',
                'token': token,
                'error': f'API Error {response.status_code}'
            }
            
    except Exception as e:
        user_id = decode_token_user_id(token)
        if user_id:
            result = calculate_age_from_id(user_id)
            if result:
                result['status'] = 'fallback_success'
                result['token'] = token
                return result
        
        return {
            'status': 'error',
            'token': token,
            'error': str(e)
        }
    finally:
        # Обязательно закрываем сессию
        if session:
            try:
                session.close()
                logger.debug("Сессия прокси закрыта")
            except Exception as e:
                logger.warning(f"Ошибка при закрытии сессии: {e}")

def calculate_age_from_id(user_id):
    """
    Вычисляет возраст аккаунта по User ID
    """
    try:
        # Вычисляем дату создания из Snowflake ID
        creation_timestamp = ((int(user_id) >> 22) + 1420070400000) / 1000
        creation_date = datetime.fromtimestamp(creation_timestamp, tz=timezone.utc)
        
        # Текущая дата
        current_date = datetime.now(tz=timezone.utc)
        
        # Вычисляем возраст аккаунта
        account_age = current_date - creation_date
        days = account_age.days
        years = days // 365
        remaining_days = days % 365
        
        logger.info(f"=== Информация об аккаунте (из токена) ===")
        logger.info(f"User ID: {user_id}")
        logger.info(f"Дата создания: {creation_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        logger.info(f"Возраст аккаунта: {years} лет, {remaining_days} дней")
        logger.info(f"Общее количество дней: {days}")
        
        return {
            'username': '',
            'discriminator': '',
            'user_id': user_id,
            'creation_date': creation_date.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'age_days': days,
            'age_years': years,
            'remaining_days': remaining_days
        }
        
    except Exception as e:
        logger.error(f"Ошибка при вычислении возраста: {e}")
        return None

def save_results_to_csv(results, os_type):
    """Сохраняет результаты в CSV файл"""
    try:
        # Создаем директорию result если не существует
        os.makedirs('result', exist_ok=True)
        
        # Определяем разделитель
        delimiter = ';' if os_type.lower() == 'windows' else ','
        
        # Генерируем имя файла с timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'result/discord/discord_check_{timestamp}.csv'
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['status', 'username', 'discriminator', 'user_id', 'creation_date', 
                         'age_days', 'age_years', 'remaining_days', 'token', 'error']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=delimiter)
            
            writer.writeheader()
            for result in results:
                # Создаем копию и заполняем недостающие поля
                result_copy = result.copy()
                
                # Убираем thread_id если он есть
                if 'thread_id' in result_copy:
                    del result_copy['thread_id']
                
                # Заполняем недостающие поля пустыми значениями
                for field in fieldnames:
                    if field not in result_copy:
                        result_copy[field] = ''
                
                writer.writerow(result_copy)
        
        logger.success(f"Результаты сохранены в: {filename}")
        return filename
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении результатов: {e}")
        return None

def check_single_account_with_retry(token, proxy_dict, max_retries=RETRY_COUNT):
    """
    Проверяет один аккаунт с повторными попытками при ошибках
    """
    for attempt in range(max_retries):
        session = None
        try:
            # Задержка между действиями
            if SLEEP_BETWEEN_ACTIONS:
                sleep_time = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
                time.sleep(sleep_time)
            
            result = get_account_age_via_api_with_proxy(token, proxy_dict)
            
            # Если успешно или токен невалидный - не повторяем
            if result['status'] in ['success', 'invalid_token', 'token_decoded', 'fallback_success']:
                return result
            
            # При ошибке API или сети - пробуем еще раз
            if attempt < max_retries - 1:
                logger.warning(f"Попытка {attempt + 1} неудачна, повтор через 5 сек...")
                time.sleep(5)
            
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Ошибка при попытке {attempt + 1}: {e}, повтор...")
                time.sleep(5)
            else:
                return {
                    'status': 'error',
                    'token': token,
                    'error': f'Максимум попыток исчерпан: {str(e)}'
                }
        finally:
            # Закрываем сессию после каждой попытки
            if session:
                try:
                    session.close()
                except Exception:
                    pass
    
    return {
        'status': 'error',
        'token': token,
        'error': 'Максимум попыток исчерпан'
    }

def process_token_batch(tokens_with_proxies):
    """
    Обрабатывает батч токенов в одном потоке
    """
    results = []
    thread_id = threading.current_thread().ident
    
    try:
        for i, (token, proxy_dict, token_index) in enumerate(tokens_with_proxies):
            logger.debug(f"Поток {thread_id}: Проверка токена {token_index + 1}")
            
            result = check_single_account_with_retry(token, proxy_dict)
            results.append(result)
            
            # Добавляем отладочную информацию
            logger.debug(f"Результат для токена {token_index + 1}: {result}")
            
            if result and result.get('status') == 'success':
                username = result.get('username', 'Unknown')
                discriminator = result.get('discriminator', '0')
                age_days = result.get('age_days', 0)
                logger.success(f"✅ {username}#{discriminator} - {age_days} дней")
            elif result and result.get('status') in ['token_decoded', 'fallback_success']:
                age_days = result.get('age_days', 0)
                user_id = result.get('user_id', 'Unknown')
                logger.success(f"✅ ID:{user_id} - {age_days} дней (токен декодирован)")
            else:
                error_msg = result.get('error', 'Unknown error') if result else 'No result returned'
                status = result.get('status', 'unknown') if result else 'no_result'
                logger.error(f"❌ Статус: {status}, Ошибка: {error_msg}")

    except Exception as e:
        logger.error(f"Критическая ошибка в потоке {thread_id}: {e}")
    finally:
        # Принудительная очистка соединений для потока
        logger.debug(f"Поток {thread_id}: Завершение работы, очистка соединений")
    
    return results

def check_discord_accounts(os_type, tokens_file=None, proxies_file=None):
    """
    Основная функция проверки Discord аккаунтов с многопоточностью
    
    Args:
        os_type (str): 'windows', 'macos' или 'linux'
        tokens_file (str): путь к файлу с токенами
        proxies_file (str): путь к файлу с прокси
    """
    logger.info(f"Запуск проверки Discord аккаунтов для ОС: {os_type}")
    logger.info(f"Количество потоков: {NUM_THREADS}")
    logger.info(f"Задержки между действиями: {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]} сек")
    logger.info(f"Максимум попыток при ошибке: {RETRY_COUNT}")
    logger.info("=" * 60)
    
    # Читаем токены и прокси
    tokens = read_tokens(tokens_file)
    proxies = read_proxies(proxies_file)
    
    if not tokens:
        logger.error("Не найдены токены для проверки!")
        return None
    
    logger.info(f"Загружено токенов: {len(tokens)}")
    logger.info(f"Загружено прокси: {len(proxies)}")
    
    # Подготавливаем данные для потоков
    tokens_with_proxies = []
    for i, token in enumerate(tokens):
        proxy_string = select_proxy(proxies, tokens, i)
        proxy_dict = None
        
        if proxy_string:
            proxy_dict = get_proxy_dict(proxy_string)
        
        tokens_with_proxies.append((token, proxy_dict, i))
    
    # Разделяем токены между потоками
    chunk_size = max(1, len(tokens_with_proxies) // NUM_THREADS)
    token_chunks = [tokens_with_proxies[i:i + chunk_size] 
                   for i in range(0, len(tokens_with_proxies), chunk_size)]
    
    all_results = []
    start_time = time.time()
    
    logger.info(f"\nНачинаем обработку в {len(token_chunks)} потоках...")
    
    # Запускаем многопоточную обработку
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        # Отправляем задачи в пул потоков
        future_to_chunk = {executor.submit(process_token_batch, chunk): chunk 
                          for chunk in token_chunks}
        
        # Собираем результаты по мере завершения
        for future in as_completed(future_to_chunk):
            chunk_results = future.result()
            all_results.extend(chunk_results)
            #logger.info(f"Завершен батч из {len(chunk_results)} токенов")
    
    end_time = time.time()
    
    # Сохраняем результаты
    csv_file = save_results_to_csv(all_results, os_type)
    
    logger.info(f"\n=== Итоги проверки ===")
    logger.info(f"Всего проверено: {len(all_results)}")
    logger.info(f"Успешных: {sum(1 for r in all_results if r['status'] in ['success', 'token_decoded', 'fallback_success'])}")
    logger.info(f"Ошибок: {sum(1 for r in all_results if r['status'] in ['invalid_token', 'api_error', 'error'])}")
    logger.info(f"Время выполнения: {end_time - start_time:.2f} секунд")
    logger.success(f"Результаты сохранены в: {csv_file}")
    
    return all_results

def check_discord_account_age():
    logger.info("Discord Account Age Checker (Исправленная версия)")
    logger.info("=" * 50)
    
    # Ваш токен
    token = input("Введите Discord токен: ").strip()
    
    if not token:
        logger.error("Токен не может быть пустым!")
        return
    
    result = get_account_age_via_api_with_proxy(token)
    
    if result:
        logger.success("\n✅ Информация успешно получена!")
    else:
        logger.error("\n❌ Не удалось получить информацию")

if __name__ == "__main__":
    # Пример использования новой функции
    check_discord_accounts('windows')
    #check_discord_account_age()