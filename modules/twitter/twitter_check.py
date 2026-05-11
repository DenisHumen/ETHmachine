import asyncio
import csv
import sys
import random
from datetime import datetime
from curl_cffi.requests import AsyncSession
from pathlib import Path
from colorama import Fore, Style, init

init()

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from modules.simple_logger import logger, setup_file_logging
from modules.proxy_manager import get_random_proxy, get_proxy_dict, mask_proxy
from config.modules.cfg_twitter import MAIN_AUTH_TOKEN, MAIN_PROXY_TWITTER, RANDOM_PROXIES_TWITTER, COUNT_REPLACE_TWITTER_AUTH_TOKEN
from config.modules.general_config import NUM_THREADS, SLEEP_BETWEEN_ACTIONS

# Настройка логирования для модуля twitter_check
_logging_configured = False

def setup_twitter_logging():
    """Настраивает логирование для модуля проверки Twitter"""
    global _logging_configured
    
    if not _logging_configured:
        _logging_configured = True
    
    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f'twitter_check_{timestamp}.log'
    
    # Добавляем файловый обработчик (без цветов)
    logger.add(
        log_file,
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level="DEBUG",
        encoding="utf-8",
        colorize=False
    )
    
    logger.info(f"📝 Логирование настроено. Файл: {log_file}")

class Constants:
    BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

class TokenManager:
    """Менеджер для управления ротацией auth токенов"""
    
    def __init__(self):
        self.tokens = MAIN_AUTH_TOKEN if isinstance(MAIN_AUTH_TOKEN, list) else [MAIN_AUTH_TOKEN]
        self.max_uses_per_token = COUNT_REPLACE_TWITTER_AUTH_TOKEN
        self.current_token_index = 0
        self.current_token_uses = 0
        self.total_checks_made = 0
        
        # Валидация токенов
        self.tokens = [token.strip() for token in self.tokens if token and token.strip()]
        
        if not self.tokens:
            raise Exception("MAIN_AUTH_TOKEN пуст! Добавьте хотя бы один токен.")
    
    def get_current_token(self) -> str:
        """Возвращает текущий активный токен"""
        return self.tokens[self.current_token_index]
    
    def get_max_possible_checks(self) -> int:
        """Возвращает максимальное количество проверок с доступными токенами"""
        return len(self.tokens) * self.max_uses_per_token
    
    def increment_usage(self):
        """Увеличивает счетчик использований и переключает токен при необходимости"""
        self.current_token_uses += 1
        self.total_checks_made += 1
        
        if self.current_token_uses >= self.max_uses_per_token:
            # Переключаемся на следующий токен
            if self.current_token_index < len(self.tokens) - 1:
                old_index = self.current_token_index
                self.current_token_index += 1
                self.current_token_uses = 0
                logger.info(f"\033[35m🔄 Переключение токена:\033[0m \033[33m{old_index + 1}\033[0m \033[37m→\033[0m \033[32m{self.current_token_index + 1}\033[0m \033[37m(использовано {self.max_uses_per_token}/{self.max_uses_per_token})\033[0m")
            else:
                # Все токены исчерпаны
                logger.warning(f"\033[31m⚠️  Все токены использованы\033[0m \033[37m({self.total_checks_made} проверок)\033[0m")
    
    def has_tokens_available(self) -> bool:
        """Проверяет, есть ли доступные токены"""
        return self.total_checks_made < self.get_max_possible_checks()
    
    def get_stats(self) -> dict:
        """Возвращает статистику использования токенов"""
        return {
            "total_tokens": len(self.tokens),
            "current_token": self.current_token_index + 1,
            "current_token_uses": self.current_token_uses,
            "max_uses_per_token": self.max_uses_per_token,
            "total_checks_made": self.total_checks_made,
            "max_possible_checks": self.get_max_possible_checks(),
            "remaining_checks": self.get_max_possible_checks() - self.total_checks_made
        }

# Глобальный экземпляр менеджера токенов
token_manager = None

def initialize_token_manager():
    """Инициализирует глобальный менеджер токенов"""
    global token_manager
    if token_manager is None:
        token_manager = TokenManager()
    return token_manager

def load_random_proxy():
    proxy = get_random_proxy()
    if proxy:
        logger.info(f"🌐 Выбран случайный прокси")
    return proxy

async def create_twitter_client():
    """Создает Twitter клиент"""
    global token_manager
    
    if token_manager is None:
        token_manager = initialize_token_manager()
    
    # Проверяем доступность токенов
    if not token_manager.has_tokens_available():
        raise Exception("Все токены исчерпаны! Невозможно продолжить проверку.")
    
    current_token = token_manager.get_current_token()
    
    if not current_token:
        raise Exception("MAIN_AUTH_TOKEN is not set! Please set your auth token in config/config.py")
    
    session = AsyncSession()
    
    # Выбираем прокси в зависимости от настроек
    proxy_to_use = None
    if RANDOM_PROXIES_TWITTER:
        proxy_to_use = load_random_proxy()
        if not proxy_to_use:
            logger.warning("Не удалось загрузить случайный прокси, используем MAIN_PROXY_TWITTER")
            proxy_to_use = MAIN_PROXY_TWITTER
    else:
        proxy_to_use = MAIN_PROXY_TWITTER
    
    if proxy_to_use:
        proxy_dict = get_proxy_dict(proxy_to_use)
        if proxy_dict:
            session.proxies = proxy_dict
        logger.info(f"🌐 Использую прокси: {mask_proxy(proxy_to_use)}")
    else:
        logger.info("🌐 Прокси не настроен")
    
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "authorization": f"Bearer {Constants.BEARER_TOKEN}",
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
    })
    
    session.cookies.set("auth_token", current_token)
    
    try:
        response = await session.get("https://x.com/home")
        
        csrf_token = None
        for cookie_name, cookie_value in session.cookies.get_dict().items():
            if cookie_name == "ct0":
                csrf_token = cookie_value
                break
        
        if not csrf_token:
            raise Exception("Failed to get CSRF token - invalid auth_token?")
        
        session.headers["x-csrf-token"] = csrf_token
        
        return session, csrf_token
        
    except Exception as e:
        logger.error(f"Failed to initialize Twitter client: {e}")
        raise

class TwitterFollowersChecker:
    def __init__(self):
        self.session = None
        self.csrf_token = None

    async def __aenter__(self):
        """Async context manager entry"""
        self.session, self.csrf_token = await create_twitter_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def close(self):
        """Закрывает сессию"""
        if self.session:
            try:
                await self.session.close()
            except:
                pass

    async def get_user_followers_count(self, nickname: str):
        """
        Получает количество подписчиков пользователя по никнейму
        
        Args:
            nickname (str): Никнейм пользователя без @
            
        Returns:
            dict: Информация о пользователе с количеством подписчиков
        """
        try:
            headers = {
                "content-type": "application/json",
                "referer": f"https://x.com/{nickname}",
                "x-csrf-token": self.csrf_token,
            }
            
            params = {
                "variables": f'{{"screen_name":"{nickname}","withSafetyModeUserFields":true}}',
                "features": '{"hidden_profile_subscriptions_enabled":true,"profile_label_improvements_pcf_label_in_post_enabled":true,"rweb_tipjar_consumption_enabled":true,"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"subscriptions_verification_info_is_identity_verified_enabled":true,"subscriptions_verification_info_verified_since_enabled":true,"highlights_tweets_tab_ui_enabled":true,"responsive_web_twitter_article_notes_tab_enabled":true,"subscriptions_feature_can_gift_premium":true,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"responsive_web_graphql_timeline_navigation_enabled":true}',
                "fieldToggles": '{"withAuxiliaryUserLabels":true}',
            }

            response = await self.session.get(
                "https://x.com/i/api/graphql/32pL5BWe9WKeSK1MoPvFQQ/UserByScreenName",
                params=params,
                headers=headers,
            )

            if response.status_code == 403:
                logger.error(f"\033[31mAccess denied (403) для\033[0m \033[33m@{nickname}\033[0m\033[37m. Токен может быть невалидным или rate limited.\033[0m")
                return self._create_error_result(nickname, "Access denied (403)")
            elif response.status_code == 401:
                logger.error(f"\033[31mUnauthorized (401) для\033[0m \033[33m@{nickname}\033[0m\033[37m. Auth token невалиден или истек.\033[0m")
                return self._create_error_result(nickname, "Unauthorized (401)")
            elif response.status_code == 429:
                logger.error(f"\033[33mRate limit exceeded (429) для\033[0m \033[33m@{nickname}\033[0m\033[37m. Пожалуйста, подождите.\033[0m")
                return self._create_error_result(nickname, "Rate limit exceeded (429)")
            elif response.status_code == 404:
                logger.error(f"\033[31mUser not found (404) для\033[0m \033[33m@{nickname}\033[0m\033[37m.\033[0m")
                return self._create_error_result(nickname, "User not found (404)")
            elif response.status_code != 200:
                logger.error(f"\033[31mНе удалось получить информацию для\033[0m \033[33m@{nickname}\033[0m\033[37m. Status:\033[0m \033[31m{response.status_code}\033[0m")
                return self._create_error_result(nickname, f"HTTP {response.status_code}")

            data = response.json()
            
            if "errors" in data:
                error_msg = str(data['errors'])
                logger.error(f"\033[31mAPI вернул ошибки для\033[0m \033[33m@{nickname}\033[0m\033[37m:\033[0m \033[31m{error_msg}\033[0m")
                return self._create_error_result(nickname, f"API Error: {error_msg}")
                
            if "data" not in data or "user" not in data["data"]:
                logger.error(f"\033[31mНеверная структура ответа для\033[0m \033[33m@{nickname}\033[0m")
                return self._create_error_result(nickname, "Invalid response structure")
                
            user_data = data["data"]["user"]["result"]
            
            if not user_data or "legacy" not in user_data:
                logger.error(f"\033[31mДанные пользователя не найдены для\033[0m \033[33m@{nickname}\033[0m")
                return self._create_error_result(nickname, "User data not found")
                
            legacy_data = user_data.get("legacy", {})
            
            user_info = {
                "nickname": nickname,
                "name": legacy_data.get("name", "Unknown"),
                "followers_count": legacy_data.get("followers_count", 0),
                "following_count": legacy_data.get("friends_count", 0),
                "tweets_count": legacy_data.get("statuses_count", 0),
                "verified": legacy_data.get("verified", False),
                "is_blue_verified": user_data.get("is_blue_verified", False),
                "description": legacy_data.get("description", ""),
                "location": legacy_data.get("location", ""),
                "created_at": legacy_data.get("created_at", ""),
                "protected": legacy_data.get("protected", False),
                "check_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "success"
            }
            
            return user_info

        except Exception as e:
            logger.error(f"\033[31mНе удалось получить количество подписчиков для\033[0m \033[33m@{nickname}\033[0m\033[37m:\033[0m \033[31m{e}\033[0m")
            return self._create_error_result(nickname, f"Exception: {str(e)}")

    def _create_error_result(self, nickname: str, error_msg: str):
        """Создает результат с ошибкой"""
        return {
            "nickname": nickname,
            "name": "Error",
            "followers_count": 0,
            "following_count": 0,
            "tweets_count": 0,
            "verified": False,
            "is_blue_verified": False,
            "description": "",
            "location": "",
            "created_at": "",
            "protected": False,
            "check_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "status": f"error: {error_msg}"
        }

def validate_and_fix_csv_format(filename: str):
    """
    Проверяет и исправляет формат CSV файла.
    Обеспечивает, что каждая строка имеет правильное количество запятых.
    Ожидаемый формат: nickname,auth_token,ct0 (2 запятые между 3 колонками)
    
    Args:
        filename (str): Путь к CSV файлу
        
    Returns:
        bool: True если файл был исправлен, False если исправления не требовались
    """
    if not Path(filename).exists():
        logger.error(f"File {filename} not found!")
        return False
    
    try:
        lines_to_fix = []
        fixed = False
        
        # Читаем файл и проверяем формат
        with open(filename, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        
        if not lines:
            logger.warning(f"File {filename} is empty!")
            return False
        
        # Проверяем заголовок
        header = lines[0].strip()
        expected_columns = ['nickname', 'auth_token', 'ct0']
        
        if header != 'nickname,auth_token,ct0':
            logger.warning(f"Header format incorrect. Expected: 'nickname,auth_token,ct0', Got: '{header}'")
            # Исправляем заголовок
            lines[0] = 'nickname,auth_token,ct0\n'
            fixed = True
        
        # Проверяем каждую строку данных
        for i, line in enumerate(lines[1:], start=1):
            line = line.strip()
            if not line:  # Пропускаем пустые строки
                continue
            
            # Подсчитываем количество запятых
            comma_count = line.count(',')
            
            if comma_count == 0:  # Только nickname без запятых
                fixed_line = line + ',,\n'
                lines[i] = fixed_line
                fixed = True
                logger.info(f"Fixed line {i+1}: '{line}' → '{fixed_line.strip()}'")
            
            elif comma_count == 1:  # Формат: nickname, или nickname,auth_token
                # Добавляем недостающую запятую
                fixed_line = line + ',\n'
                lines[i] = fixed_line
                fixed = True
                logger.info(f"Fixed line {i+1}: '{line}' → '{fixed_line.strip()}'")
            
            elif comma_count == 2:  # Правильный формат: nickname,auth_token,ct0
                if not line.endswith('\n'):
                    lines[i] = line + '\n'
                continue
            
            elif comma_count > 2:  # Слишком много запятых - убираем лишние
                # Разбиваем строку по запятым и берем только первые 3 части
                parts = line.split(',')
                if len(parts) > 3:
                    fixed_line = ','.join(parts[:3]) + '\n'
                    lines[i] = fixed_line
                    fixed = True
                    logger.info(f"Fixed line {i+1}: '{line}' → '{fixed_line.strip()}' (removed extra commas)")
                else:
                    if not line.endswith('\n'):
                        lines[i] = line + '\n'
        
        # Если были исправления, сохраняем файл
        if fixed:
            # Создаем резервную копию
            backup_filename = f"{filename}.backup"
            with open(backup_filename, 'w', encoding='utf-8') as backup_file:
                backup_file.writelines(lines)
            logger.info(f"Backup created: {backup_filename}")
            
            # Сохраняем исправленный файл
            with open(filename, 'w', encoding='utf-8') as file:
                file.writelines(lines)
            
            logger.success(f"✅ CSV format fixed and saved: {filename}")
            return True
        else:
            logger.info(f"✅ CSV format is already correct: {filename}")
            return False
            
    except Exception as e:
        logger.error(f"Error validating/fixing CSV format in {filename}: {e}")
        return False

def load_nicknames_from_csv(filename: str):
    """
    Загружает никнеймы из CSV файла
    
    Args:
        filename (str): Путь к CSV файлу
        
    Returns:
        list: Список никнеймов
    """
    nicknames = []
    
    if not Path(filename).exists():
        logger.error(f"\033[31mФайл не найден:\033[0m \033[33m{filename}\033[0m\033[37m!\033[0m")
        return nicknames
    
    # Сначала проверяем и исправляем формат CSV
    validate_and_fix_csv_format(filename)
    
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for i, row in enumerate(reader):
                if 'nickname' in row:
                    nickname = row['nickname'].strip()
                    if nickname.startswith('@'):
                        nickname = nickname[1:]
                    
                    if nickname:
                        nicknames.append(nickname)
                    
        logger.info(f"\033[32m📥 Загружено\033[0m \033[36m{len(nicknames)}\033[0m \033[37mникнеймов из\033[0m \033[33m{filename}\033[0m")
        return nicknames
        
    except Exception as e:
        logger.error(f"\033[31mОшибка загрузки никнеймов из\033[0m \033[33m{filename}\033[0m\033[37m:\033[0m \033[31m{e}\033[0m")
        return nicknames

def save_results_to_csv(results: list, filename: str, delimiter: str = ','):
    """
    Сохраняет результаты в CSV файл
    
    Args:
        results (list): Список результатов
        filename (str): Имя файла для сохранения
        delimiter (str): Разделитель для CSV (';' для Windows, ',' для Linux/macOS)
    """
    try:
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            if results:
                fieldnames = [
                    'nickname', 'name', 'followers_count', 'following_count', 
                    'tweets_count', 'verified', 'is_blue_verified', 'description', 
                    'location', 'created_at', 'protected', 'check_time', 'status'
                ]
                writer = csv.DictWriter(file, fieldnames=fieldnames, delimiter=delimiter)
                writer.writeheader()
                writer.writerows(results)
                
        logger.success(f"\033[32m💾 Результаты сохранены в\033[0m \033[36m{filename}\033[0m \033[37m(разделитель: '{delimiter}')\033[0m")
        
    except Exception as e:
        logger.error(f"\033[31mОшибка сохранения результатов в\033[0m \033[33m{filename}\033[0m\033[37m:\033[0m \033[31m{e}\033[0m")

async def check_single_nickname(nickname: str, checker: TwitterFollowersChecker, index: int, total: int):
    """
    Проверяет один никнейм
    
    Args:
        nickname (str): Никнейм для проверки
        checker (TwitterFollowersChecker): Объект для проверки
        index (int): Текущий индекс
        total (int): Общее количество
        
    Returns:
        dict: Результат проверки
    """
    global token_manager
    
    logger.info(f"\033[36m[{index+1}/{total}]\033[0m \033[37mПроверка\033[0m \033[33m@{nickname}\033[0m\033[37m...\033[0m")
    
    try:
        user_info = await checker.get_user_followers_count(nickname)
        
        # Увеличиваем счетчик использования токена после успешной проверки
        if token_manager:
            token_manager.increment_usage()
            stats = token_manager.get_stats()
            logger.debug(f"\033[35m📊 Token usage: {stats['current_token_uses']}/{stats['max_uses_per_token']}\033[0m "
                        f"\033[37m(Token {stats['current_token']}/{stats['total_tokens']}, "
                        f"Total: {stats['total_checks_made']}/{stats['max_possible_checks']})\033[0m")
        
        if user_info:
            if user_info['status'] == 'success':
                # Форматируем количество подписчиков с красивым выводом
                followers = user_info['followers_count']
                if followers >= 1_000_000:
                    followers_str = f"{followers/1_000_000:.1f}M"
                    color = "\033[32m"
                elif followers >= 100_000:
                    followers_str = f"{followers/1_000:.0f}K"
                    color = "\033[36m"
                elif followers >= 10_000:
                    followers_str = f"{followers/1_000:.1f}K"
                    color = "\033[33m"
                else:
                    followers_str = f"{followers:,}"
                    color = "\033[37m"
                
                logger.success(f"\033[32m✅\033[0m \033[33m@{nickname}\033[0m\033[37m:\033[0m {color}{followers_str}\033[0m \033[37mподписчиков\033[0m")
            else:
                logger.error(f"\033[31m❌\033[0m \033[33m@{nickname}\033[0m\033[37m:\033[0m \033[31m{user_info['status']}\033[0m")
            return user_info
        else:
            logger.error(f"\033[31m❌ Нет данных для\033[0m \033[33m@{nickname}\033[0m")
            return checker._create_error_result(nickname, "No data returned")
            
    except Exception as e:
        logger.error(f"\033[31m❌ Ошибка при проверке\033[0m \033[33m@{nickname}\033[0m\033[37m:\033[0m \033[31m{e}\033[0m")
        return checker._create_error_result(nickname, f"Exception: {str(e)}")

async def process_nicknames_batch(nicknames_batch: list, batch_num: int, total_batches: int):
    """
    Обрабатывает пакет никнеймов
    
    Args:
        nicknames_batch (list): Список никнеймов для обработки
        batch_num (int): Номер текущего пакета
        total_batches (int): Общее количество пакетов
        
    Returns:
        list: Результаты проверки
    """
    logger.info(f"\033[35m🔄 Обработка пакета\033[0m \033[36m{batch_num}/{total_batches}\033[0m \033[37m({len(nicknames_batch)} аккаунтов)\033[0m")
    
    batch_results = []
    
    async with TwitterFollowersChecker() as checker:
        tasks = []
        for i, nickname in enumerate(nicknames_batch):
            if i > 0:
                # Используем рандомную задержку из конфигурации
                delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0], SLEEP_BETWEEN_ACTIONS[1])
                await asyncio.sleep(delay)
            
            task = check_single_nickname(nickname, checker, i, len(nicknames_batch))
            tasks.append(task)
        
        # Выполняем все задачи в пакете параллельно
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Обрабатываем исключения
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                nickname = nicknames_batch[i]
                logger.error(f"\033[31m❌ Исключение для\033[0m \033[33m@{nickname}\033[0m\033[37m:\033[0m \033[31m{result}\033[0m")
                batch_results[i] = checker._create_error_result(nickname, f"Exception: {str(result)}")
    
    logger.success(f"\033[32m✅ Пакет\033[0m \033[36m{batch_num}/{total_batches}\033[0m \033[32mзавершен\033[0m")
    return batch_results

def run_twitter_check(os_type: str = 'linux'):
    """
    Основная функция для запуска проверки Twitter аккаунтов
    
    Args:
        os_type (str): Тип операционной системы ('windows', 'linux', 'macOS')
    """
    asyncio.run(main(os_type))

async def main(os_type: str = 'linux'):
    """
    Основная функция
    
    Args:
        os_type (str): Тип операционной системы для выбора разделителя CSV
    """
    # Настраиваем логирование
    setup_twitter_logging()
    
    if os_type.lower() == 'windows':
        csv_delimiter = ';'
        os_display = "Windows"
    elif os_type.lower() in ['linux', 'macos']:
        csv_delimiter = ','
        os_display = os_type
    else:
        csv_delimiter = ','
        os_display = f"{os_type} (unknown, using Linux defaults)"

    INPUT_FILE = project_root / "data" / "twitter" / "twitters.csv"
    OUTPUT_FILE = project_root / "result" / "twitter" / "result.csv"

    logger.info(f"\033[36m🚀 Twitter Followers Checker\033[0m")
    logger.info(f"\033[34m{'=' * 50}\033[0m")
    logger.info(f"⏰ Дата и время (UTC): \033[33m{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\033[0m")
    logger.info(f"👤 Пользователь: \033[36mDenisHumen\033[0m")
    logger.info(f"💻 Операционная система: \033[32m{os_display}\033[0m")
    logger.info(f"📄 Разделитель CSV: \033[33m'{csv_delimiter}'\033[0m")
    logger.info(f"🧵 Потоков: \033[35m{NUM_THREADS}\033[0m")
    logger.info(f"⏱️  Задержка между запросами: \033[33m{SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}s\033[0m")
    logger.info(f"🌐 Прокси: \033[36m{MAIN_PROXY_TWITTER if MAIN_PROXY_TWITTER else 'Не используется'}\033[0m")
    if RANDOM_PROXIES_TWITTER:
        logger.info(f"🔄 Случайные прокси: \033[32mВключено\033[0m")
    logger.info(f"\033[34m{'=' * 50}\033[0m")
    
    # Инициализируем менеджер токенов
    global token_manager
    try:
        token_manager = initialize_token_manager()
        stats = token_manager.get_stats()
        
        logger.info("\n\033[32m🔑 Конфигурация токенов:\033[0m")
        logger.info(f"   \033[37m📊 Всего токенов:\033[0m \033[36m{stats['total_tokens']}\033[0m")
        logger.info(f"   \033[37m🔢 Использований на токен:\033[0m \033[33m{stats['max_uses_per_token']}\033[0m")
        logger.info(f"   \033[37m📈 Максимум проверок:\033[0m \033[32m{stats['max_possible_checks']}\033[0m")
        logger.info("\033[34m" + "═" * 50 + "\033[0m")
    except Exception as e:
        logger.error(f"\033[31m❌ ОШИБКА инициализации токенов:\033[0m \033[33m{e}\033[0m")
        logger.info("\n\033[36m📋 Как настроить MAIN_AUTH_TOKEN:\033[0m")
        logger.info("\033[34m" + "═" * 60 + "\033[0m")
        logger.info("\033[37m1. Откройте браузер и войдите в Twitter/X\033[0m")
        logger.info("\033[37m2. Нажмите F12 (Developer Tools)\033[0m")
        logger.info("\033[37m3. Перейдите на вкладку Application/Storage → Cookies\033[0m")
        logger.info("\033[37m4. Найдите cookie с именем 'auth_token'\033[0m")
        logger.info("\033[37m5. Скопируйте его значение\033[0m")
        logger.info("\033[34m" + "═" * 60 + "\033[0m")
        logger.info("\033[32m💡 Пример в config.py:\033[0m")
        logger.info("\033[33m   MAIN_AUTH_TOKEN = ['токен1', 'токен2']\033[0m")
        logger.info("\033[33m   COUNT_REPLACE_TWITTER_AUTH_TOKEN = 5\033[0m")
        return
    
    if not MAIN_AUTH_TOKEN or MAIN_AUTH_TOKEN == "":
        logger.error("\033[31m❌ ОШИБКА: Необходимо указать MAIN_AUTH_TOKEN в config/config.py!\033[0m")
        logger.info("\n\033[36m📋 Как получить MAIN_AUTH_TOKEN:\033[0m")
        logger.info("\033[34m" + "═" * 60 + "\033[0m")
        logger.info("\033[37m1. Откройте браузер и войдите в Twitter/X\033[0m")
        logger.info("\033[37m2. Нажмите F12 (Developer Tools)\033[0m")
        logger.info("\033[37m3. Перейдите на вкладку Application/Storage → Cookies\033[0m")
        logger.info("\033[37m4. Найдите cookie с именем 'auth_token'\033[0m")
        logger.info("\033[37m5. Скопируйте его значение и вставьте в MAIN_AUTH_TOKEN в config/config.py\033[0m")
        logger.info("\033[34m" + "═" * 60 + "\033[0m")
        logger.info("\033[32m💡 Пример:\033[0m \033[33mMAIN_AUTH_TOKEN = ['ваш_длинный_токен_здесь']\033[0m")
        return
    
    nicknames = load_nicknames_from_csv(INPUT_FILE)
    if not nicknames:
        logger.error(f"\033[31m❌ No nicknames found in {INPUT_FILE}\033[0m")
        logger.info(f"\n\033[36m📋 Создайте файл {INPUT_FILE} с форматом:\033[0m")
        logger.info("\033[34m" + "═" * 40 + "\033[0m")
        logger.info("\033[37mnickname,auth_token,ct0\033[0m")
        logger.info("\033[33ms_nakotomo,,,\033[0m")
        logger.info("\033[33melonmusk,,,\033[0m")
        logger.info("\033[33mtwitter,,,\033[0m")
        logger.info("\033[34m" + "═" * 40 + "\033[0m")
        logger.info("\033[32m💡 Скрипт использует только колонку 'nickname'\033[0m")
        return
    
    logger.success(f"\033[32m📋 Загружено {len(nicknames)} никнеймов для проверки\033[0m")
    
    # Проверяем достаточность токенов
    max_checks = token_manager.get_max_possible_checks()
    if len(nicknames) > max_checks:
        logger.warning("\n\033[33m⚠️  ВНИМАНИЕ: Недостаточно токенов!\033[0m")
        logger.warning(f"   \033[37m📊 Аккаунтов для проверки:\033[0m \033[31m{len(nicknames)}\033[0m")
        logger.warning(f"   \033[37m🔑 Максимум проверок с текущими токенами:\033[0m \033[33m{max_checks}\033[0m")
        logger.warning(f"   \033[37m❌ Не хватает проверок:\033[0m \033[31m{len(nicknames) - max_checks}\033[0m")
        logger.warning("\n\033[36m💡 Решение:\033[0m")
        logger.warning(f"   \033[37m1. Добавьте еще\033[0m \033[32m{((len(nicknames) - max_checks) // COUNT_REPLACE_TWITTER_AUTH_TOKEN) + 1}\033[0m \033[37mтокен(ов)\033[0m")
        logger.warning(f"   \033[37m2. Или увеличьте\033[0m \033[33mCOUNT_REPLACE_TWITTER_AUTH_TOKEN\033[0m")
        logger.warning(f"   \033[37m3. Или уменьшите количество аккаунтов для проверки\033[0m")
        logger.info(f"\n\033[33m⚠️  Будут проверены только первые {max_checks} аккаунтов!\033[0m")
        
        # Ограничиваем список до максимально возможного
        nicknames = nicknames[:max_checks]
    else:
        logger.success(f"\033[32m✅ Токенов достаточно: {max_checks} проверок доступно для {len(nicknames)} аккаунтов\033[0m")
    
    batch_size = max(1, len(nicknames) // NUM_THREADS)
    if len(nicknames) % NUM_THREADS != 0:
        batch_size += 1
    
    batches = []
    for i in range(0, len(nicknames), batch_size):
        batch = nicknames[i:i + batch_size]
        batches.append(batch)
    
    logger.info(f"\033[35m🔄 Разделено на {len(batches)} пакетов по ~{batch_size} аккаунтов\033[0m")
    logger.info("\033[34m" + "═" * 50 + "\033[0m\n")
    
    all_results = []
    
    for batch_num, batch in enumerate(batches, 1):
        try:
            batch_results = await process_nicknames_batch(batch, batch_num, len(batches))
            all_results.extend(batch_results)
            
            if batch_num < len(batches):
                delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0] * 2, SLEEP_BETWEEN_ACTIONS[1] * 2)  # Увеличенная задержка между пакетами
                logger.info(f"\033[33m⏳ Пауза {delay:.1f}с между пакетами...\033[0m")
                await asyncio.sleep(delay)
                
        except Exception as e:
            logger.error(f"\033[31m❌ Ошибка обработки пакета\033[0m \033[36m{batch_num}\033[0m\033[37m:\033[0m \033[31m{e}\033[0m")
            for nickname in batch:
                error_result = {
                    "nickname": nickname,
                    "name": "Error",
                    "followers_count": 0,
                    "following_count": 0,
                    "tweets_count": 0,
                    "verified": False,
                    "is_blue_verified": False,
                    "description": "",
                    "location": "",
                    "created_at": "",
                    "protected": False,
                    "check_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "status": f"error: Batch processing failed: {str(e)}"
                }
                all_results.append(error_result)
    
    if all_results:
        save_results_to_csv(all_results, OUTPUT_FILE, csv_delimiter)
        
        logger.info("\n\033[34m" + "═" * 80 + "\033[0m")
        logger.info(f"\033[36m📊 РЕЗУЛЬТАТЫ ПРОВЕРКИ ({len(all_results)} аккаунтов)\033[0m")
        logger.info("\033[34m" + "═" * 80 + "\033[0m")
        logger.info(f"\033[37m{'Nickname':<20} | {'Name':<25} | {'Followers':<12} | {'Status':<15}\033[0m")
        logger.info("\033[34m" + "─" * 80 + "\033[0m")
        
        successful_checks = 0
        total_followers = 0
        
        for user in all_results:
            if user['status'] == 'success':
                successful_checks += 1
                total_followers += user['followers_count']
                status_display = "\033[32m✅ Success\033[0m"
                followers_color = "\033[36m"
                nickname_color = "\033[33m"
            else:
                status_display = "\033[31m❌ Error\033[0m"
                followers_color = "\033[31m"
                nickname_color = "\033[37m"
            
            logger.info(f"{nickname_color}@{user['nickname']:<19}\033[0m | \033[37m{user['name'][:24]:<25}\033[0m | {followers_color}{user['followers_count']:>10,}\033[0m | {status_display}")
        
        logger.info("\033[34m" + "─" * 80 + "\033[0m")
        logger.success(f"\033[32m✅ Успешно проверено: {successful_checks}/{len(all_results)} аккаунтов\033[0m")
        logger.info(f"\033[36m👥 Общее количество подписчиков:\033[0m \033[33m{total_followers:,}\033[0m")
        logger.info(f"\033[37m⏰ Время проверки:\033[0m \033[33m{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\033[0m")
        logger.success(f"\033[32m💾 Результаты сохранены в:\033[0m \033[36m{OUTPUT_FILE}\033[0m \033[37m(разделитель: '{csv_delimiter}')\033[0m")
        logger.info("\033[34m" + "═" * 80 + "\033[0m")
    else:
        logger.error("\033[31m❌ No results to save\033[0m")