import asyncio
import csv
import sys
import random
from datetime import datetime
from loguru import logger
from curl_cffi.requests import AsyncSession
from pathlib import Path
from colorama import Fore, Style, init

init()

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import MAIN_AUTH_TOKEN, MAIN_PROXY_TWITTER, NUM_THREADS, SLEEP_BETWEEN_ACTIONS, RANDOM_PROXIES_TWITTER, COUNT_REPLACE_TWITTER_AUTH_TOKEN

# Настройка логирования для модуля twitter_check
def setup_twitter_logging():
    """Настраивает логирование для модуля проверки Twitter"""
    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f'twitter_check_{timestamp}.log'
    
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
                self.current_token_index += 1
                self.current_token_uses = 0
                logger.info(f"🔄 Переключение на токен #{self.current_token_index + 1}/{len(self.tokens)}")
            else:
                # Все токены исчерпаны
                logger.warning(f"⚠️ Все токены использованы ({self.total_checks_made} проверок)")
    
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
    """Загружает случайный прокси из файла data/proxy.csv"""
    proxy_file = Path("data/proxy.csv")
    
    if not proxy_file.exists():
        logger.warning(f"Файл прокси не найден: {proxy_file}")
        return None
    
    try:
        with open(proxy_file, 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        
        if not proxies:
            logger.warning("Файл прокси пустой")
            return None
        
        selected_proxy = random.choice(proxies)
        logger.info(f"Выбран случайный прокси из {len(proxies)} доступных")
        return selected_proxy
    
    except Exception as e:
        logger.error(f"Ошибка при загрузке прокси из файла: {e}")
        return None

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
        session.proxies = {
            'http': f'http://{proxy_to_use}',
            'https': f'http://{proxy_to_use}'
        }
        # Маскируем часть прокси для безопасности в логах
        proxy_display = proxy_to_use.split('@')[1] if '@' in proxy_to_use else proxy_to_use
        logger.info(f"Using proxy: {proxy_display}")
    else:
        logger.info("No proxy configured")
    
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
                logger.error(f"Access denied (403) for @{nickname}. Token may be invalid or rate limited.")
                return self._create_error_result(nickname, "Access denied (403)")
            elif response.status_code == 401:
                logger.error(f"Unauthorized (401) for @{nickname}. Auth token is invalid or expired.")
                return self._create_error_result(nickname, "Unauthorized (401)")
            elif response.status_code == 429:
                logger.error(f"Rate limit exceeded (429) for @{nickname}. Please wait.")
                return self._create_error_result(nickname, "Rate limit exceeded (429)")
            elif response.status_code == 404:
                logger.error(f"User not found (404) for @{nickname}.")
                return self._create_error_result(nickname, "User not found (404)")
            elif response.status_code != 200:
                logger.error(f"Failed to get user info for @{nickname}. Status: {response.status_code}")
                return self._create_error_result(nickname, f"HTTP {response.status_code}")

            data = response.json()
            
            if "errors" in data:
                error_msg = str(data['errors'])
                logger.error(f"API returned errors for @{nickname}: {error_msg}")
                return self._create_error_result(nickname, f"API Error: {error_msg}")
                
            if "data" not in data or "user" not in data["data"]:
                logger.error(f"Invalid response structure for @{nickname}")
                return self._create_error_result(nickname, "Invalid response structure")
                
            user_data = data["data"]["user"]["result"]
            
            if not user_data or "legacy" not in user_data:
                logger.error(f"User data not found for @{nickname}")
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
            logger.error(f"Failed to get user followers count for @{nickname}: {e}")
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
        logger.error(f"File {filename} not found!")
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
                    
        logger.info(f"Loaded {len(nicknames)} nicknames from {filename}")
        return nicknames
        
    except Exception as e:
        logger.error(f"Error loading nicknames from {filename}: {e}")
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
                
        logger.success(f"Results saved to {filename} (delimiter: '{delimiter}')")
        
    except Exception as e:
        logger.error(f"Error saving results to {filename}: {e}")

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
    
    logger.info(f"[{index+1}/{total}] Checking @{nickname}...")
    
    try:
        user_info = await checker.get_user_followers_count(nickname)
        
        # Увеличиваем счетчик использования токена после успешной проверки
        if token_manager:
            token_manager.increment_usage()
            stats = token_manager.get_stats()
            logger.debug(f"📊 Token usage: {stats['current_token_uses']}/{stats['max_uses_per_token']} "
                        f"(Token {stats['current_token']}/{stats['total_tokens']}, "
                        f"Total: {stats['total_checks_made']}/{stats['max_possible_checks']})")
        
        if user_info:
            if user_info['status'] == 'success':
                logger.success(f"✅ @{nickname}: {user_info['followers_count']:,} followers")
            else:
                logger.error(f"❌ @{nickname}: {user_info['status']}")
            return user_info
        else:
            logger.error(f"❌ No data returned for @{nickname}")
            return checker._create_error_result(nickname, "No data returned")
            
    except Exception as e:
        logger.error(f"❌ Error checking @{nickname}: {e}")
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
    logger.info(f"🔄 Обработка пакета {batch_num}/{total_batches} ({len(nicknames_batch)} аккаунтов)")
    
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
                logger.error(f"❌ Exception for @{nickname}: {result}")
                batch_results[i] = checker._create_error_result(nickname, f"Exception: {str(result)}")
    
    logger.success(f"✅ Пакет {batch_num}/{total_batches} завершен")
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

    logger.info("🚀 Twitter Followers Checker")
    logger.info("=" * 50)
    logger.info(f"Current Date and Time (UTC): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Current User's Login: DenisHumen")
    logger.info(f"Operating System: {os_display}")
    logger.info(f"CSV Delimiter: '{csv_delimiter}'")
    logger.info(f"Threads: {NUM_THREADS}")
    logger.info(f"Delay between requests: {SLEEP_BETWEEN_ACTIONS[0]}-{SLEEP_BETWEEN_ACTIONS[1]}s")
    logger.info(f"Proxy: {MAIN_PROXY_TWITTER if MAIN_PROXY_TWITTER else 'No proxy'}")
    logger.info("=" * 50)
    
    # Инициализируем менеджер токенов
    global token_manager
    try:
        token_manager = initialize_token_manager()
        stats = token_manager.get_stats()
        
        logger.info("\n🔑 Конфигурация токенов:")
        logger.info(f"   📊 Всего токенов: {stats['total_tokens']}")
        logger.info(f"   🔢 Использований на токен: {stats['max_uses_per_token']}")
        logger.info(f"   📈 Максимум проверок: {stats['max_possible_checks']}")
        logger.info("=" * 50)
    except Exception as e:
        logger.error(f"❌ ОШИБКА инициализации токенов: {e}")
        logger.info("\n📋 Как настроить MAIN_AUTH_TOKEN:")
        logger.info("="*60)
        logger.info("1. Откройте браузер и войдите в Twitter/X")
        logger.info("2. Нажмите F12 (Developer Tools)")
        logger.info("3. Перейдите на вкладку Application/Storage → Cookies")
        logger.info("4. Найдите cookie с именем 'auth_token'")
        logger.info("5. Скопируйте его значение")
        logger.info("="*60)
        logger.info("💡 Пример в config.py:")
        logger.info("   MAIN_AUTH_TOKEN = ['токен1', 'токен2']")
        logger.info("   COUNT_REPLACE_TWITTER_AUTH_TOKEN = 5")
        return
    
    if not MAIN_AUTH_TOKEN or MAIN_AUTH_TOKEN == "":
        logger.error("❌ ОШИБКА: Необходимо указать MAIN_AUTH_TOKEN в config/config.py!")
        logger.info("\n📋 Как получить MAIN_AUTH_TOKEN:")
        logger.info("="*60)
        logger.info("1. Откройте браузер и войдите в Twitter/X")
        logger.info("2. Нажмите F12 (Developer Tools)")
        logger.info("3. Перейдите на вкладку Application/Storage → Cookies")
        logger.info("4. Найдите cookie с именем 'auth_token'")
        logger.info("5. Скопируйте его значение и вставьте в MAIN_AUTH_TOKEN в config/config.py")
        logger.info("="*60)
        logger.info("💡 Пример: MAIN_AUTH_TOKEN = ['ваш_длинный_токен_здесь']")
        return
    
    nicknames = load_nicknames_from_csv(INPUT_FILE)
    if not nicknames:
        logger.error(f"❌ No nicknames found in {INPUT_FILE}")
        logger.info(f"\n📋 Создайте файл {INPUT_FILE} с форматом:")
        logger.info("="*40)
        logger.info("nickname,auth_token,ct0")
        logger.info("s_nakotomo,,,")
        logger.info("elonmusk,,,")
        logger.info("twitter,,,")
        logger.info("="*40)
        logger.info("💡 Скрипт использует только колонку 'nickname'")
        return
    
    logger.success(f"📋 Found {len(nicknames)} nicknames to check")
    
    # Проверяем достаточность токенов
    max_checks = token_manager.get_max_possible_checks()
    if len(nicknames) > max_checks:
        logger.warning("\n⚠️ ВНИМАНИЕ: Недостаточно токенов!")
        logger.warning(f"   📊 Аккаунтов для проверки: {len(nicknames)}")
        logger.warning(f"   🔑 Максимум проверок с текущими токенами: {max_checks}")
        logger.warning(f"   ❌ Не хватает проверок: {len(nicknames) - max_checks}")
        logger.warning("\n💡 Решение:")
        logger.warning(f"   1. Добавьте еще {((len(nicknames) - max_checks) // COUNT_REPLACE_TWITTER_AUTH_TOKEN) + 1} токен(ов)")
        logger.warning(f"   2. Или увеличьте COUNT_REPLACE_TWITTER_AUTH_TOKEN")
        logger.warning(f"   3. Или уменьшите количество аккаунтов для проверки")
        logger.info("\n⚠️ Будут проверены только первые {} аккаунтов!".format(max_checks))
        
        # Ограничиваем список до максимально возможного
        nicknames = nicknames[:max_checks]
    else:
        logger.success(f"✅ Токенов достаточно: {max_checks} проверок доступно для {len(nicknames)} аккаунтов")
    
    batch_size = max(1, len(nicknames) // NUM_THREADS)
    if len(nicknames) % NUM_THREADS != 0:
        batch_size += 1
    
    batches = []
    for i in range(0, len(nicknames), batch_size):
        batch = nicknames[i:i + batch_size]
        batches.append(batch)
    
    logger.info(f"🔄 Разделено на {len(batches)} пакетов по ~{batch_size} аккаунтов")
    
    all_results = []
    
    for batch_num, batch in enumerate(batches, 1):
        try:
            batch_results = await process_nicknames_batch(batch, batch_num, len(batches))
            all_results.extend(batch_results)
            
            if batch_num < len(batches):
                delay = random.uniform(SLEEP_BETWEEN_ACTIONS[0] * 2, SLEEP_BETWEEN_ACTIONS[1] * 2)  # Увеличенная задержка между пакетами
                logger.info(f"⏳ Пауза {delay:.1f}с между пакетами...")
                await asyncio.sleep(delay)
                
        except Exception as e:
            logger.error(f"❌ Ошибка обработки пакета {batch_num}: {e}")
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
        
        logger.info("="*80)
        logger.info(f"РЕЗУЛЬТАТЫ ПРОВЕРКИ ({len(all_results)} аккаунтов)")
        logger.info("="*80)
        logger.info(f"{'Nickname':<20} | {'Name':<25} | {'Followers':<12} | {'Status':<15}")
        logger.info("-"*80)
        
        successful_checks = 0
        total_followers = 0
        
        for user in all_results:
            if user['status'] == 'success':
                successful_checks += 1
                total_followers += user['followers_count']
                status_display = "✅ Success"
            else:
                status_display = "❌ Error"
            
            logger.info(f"@{user['nickname']:<19} | {user['name'][:24]:<25} | {user['followers_count']:>10,} | {status_display}")
        
        logger.info("-"*80)
        logger.success(f"Успешно проверено: {successful_checks}/{len(all_results)} аккаунтов")
        logger.info(f"Общее количество подписчиков: {total_followers:,}")
        logger.info(f"Время проверки: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        logger.success(f"Результаты сохранены в: {OUTPUT_FILE} (разделитель: '{csv_delimiter}')")
        logger.info("="*80)
    else:
        logger.error("❌ No results to save")