# 🐦 Модуль Twitter Check

## 📖 Описание

Модуль для асинхронной проверки аккаунтов Twitter/X с получением детальной информации о пользователях, включая количество подписчиков, статус верификации и активность. Поддерживает работу с прокси, **автоматическую ротацию токенов** и массовую обработку.

**Новое в версии 2.0 (2025):**
- 🔄 Автоматическая ротация токенов для обхода rate limits
- 🌐 Случайные прокси из CSV файла
- ✅ Валидация достаточности токенов перед запуском
- 📊 Расширенная статистика использования
- ⏱️ Умные задержки с random паузами

## 🎯 Основные функции

### `TokenManager` 🆕

- **NEW 2025** - Класс для автоматической ротации токенов
- Отслеживание количества использований каждого токена
- Автоматическое переключение после достижения лимита
- Валидация достаточности токенов перед запуском
- Предоставление статистики использования

**Методы:**
- `get_current_token()` - получить текущий активный токен
- `increment_usage()` - увеличить счетчик использования
- `get_max_possible_checks()` - рассчитать максимум проверок
- `has_tokens_available()` - проверить доступность
- `get_stats()` - получить статистику

### `load_random_proxy()` 🆕

- **NEW 2025** - Загрузка случайного прокси из файла
- Поддержка формата `user:pass@ip:port`
- Fallback на основной прокси при ошибках
- Логирование выбранного прокси

### `create_twitter_client()`

- Создание асинхронного HTTP клиента для Twitter API
- Настройка заголовков и cookies для аутентификации
- Получение CSRF токена для защищенных запросов
- Поддержка прокси соединений и их ротации
- **NEW**: Интеграция с TokenManager

### `TwitterFollowersChecker`

- Класс для проверки информации о Twitter аккаунтах
- Async context manager для автоматического управления ресурсами
- Retry механизм при ошибках API
- Детальная обработка различных типов ошибок
- **NEW**: Интеграция с TokenManager для ротации

### `get_user_followers_count(nickname)`

- Получение полной информации о пользователе по никнейму
- Извлечение количества подписчиков и подписок
- Проверка статуса верификации (legacy и blue checkmark)
- Получение метаданных профиля
- **NEW**: Автоматическое инкрементирование счетчика токена

### `setup_twitter_logging()`

- Настройка детального логирования
- Создание уникальных файлов с timestamp
- Ротация логов по размеру (10 MB)
- Хранение в течение 7 дней

## ⚙️ Настройки

```python
# config/modules/cfg_twitter.py

# === Токены Twitter ===
MAIN_AUTH_TOKEN = ['token1', 'token2', 'token3']  # Массив auth токенов для ротации
COUNT_REPLACE_TWITTER_AUTH_TOKEN = 5              # Максимум использований каждого токена

# === Прокси ===
MAIN_PROXY_TWITTER = "user:pass@ip:port"          # Основной прокси для Twitter
RANDOM_PROXIES_TWITTER = True                     # Использовать случайные прокси из data/proxy.csv

# === Производительность ===
NUM_THREADS = 5                                   # Количество потоков
SLEEP_BETWEEN_ACTIONS = (2, 5)                    # Случайная пауза между запросами (мин, макс сек)
```

### 🔄 Ротация токенов

Модуль автоматически ротирует токены для предотвращения rate limiting:

- **Автоматическое переключение**: после достижения `COUNT_REPLACE_TWITTER_AUTH_TOKEN` использований
- **Валидация токенов**: проверка достаточности токенов перед запуском
- **Расчет лимитов**: `количество_токенов × max_uses_per_token = максимум_проверок`

**Пример:**
```python
MAIN_AUTH_TOKEN = ['token1', 'token2']
COUNT_REPLACE_TWITTER_AUTH_TOKEN = 10

# Результат: максимум 20 проверок (2 токена × 10 использований)
```

### 🌐 Случайные прокси

При включенной опции `RANDOM_PROXIES_TWITTER = True`:

- Автоматически загружаются прокси из `data/proxy.csv`
- Случайный выбор прокси для каждой проверки
- Fallback на `MAIN_PROXY_TWITTER` при ошибках
- Формат прокси: `user:pass@ip:port` или `ip:port`

## 🔐 Аутентификация

### Получение Auth Token

1. **Войти в Twitter/X** в браузере
2. **Открыть DevTools** (F12)
3. **Перейти в Application/Storage → Cookies**
4. **Найти cookie с именем `auth_token`**
5. **Скопировать значение** в config

**Важно:** Для работы ротации токенов укажите массив токенов:

```python
# Один токен (старый формат)
MAIN_AUTH_TOKEN = ['your_auth_token_here']

# Несколько токенов для ротации (рекомендуется)
MAIN_AUTH_TOKEN = [
    'token_from_account_1',
    'token_from_account_2',
    'token_from_account_3'
]
```

### 🔄 TokenManager - Система ротации токенов

Класс `TokenManager` автоматически управляет использованием токенов:

**Основные методы:**

- `get_current_token()` - получить текущий активный токен
- `increment_usage()` - увеличить счетчик использования токена
- `get_max_possible_checks()` - рассчитать максимум проверок
- `has_tokens_available()` - проверить доступность токенов
- `get_stats()` - получить статистику использования

**Логика работы:**

```python
# Инициализация
token_manager = TokenManager(
    tokens=['token1', 'token2'],
    max_uses_per_token=10
)

# Автоматическое переключение после 10 использований
for i in range(25):
    token = token_manager.get_current_token()  # Автосмена каждые 10 раз
    # ... выполнение проверки ...
    token_manager.increment_usage()            # Увеличение счетчика

# Статистика
stats = token_manager.get_stats()
# {
#   'total_tokens': 2,
#   'max_uses_per_token': 10,
#   'max_possible_checks': 20,
#   'current_token_index': 1,
#   'current_token_uses': 5
# }
```

### Bearer Token

```python
BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
```

### Headers и User-Agent

```python
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "authorization": f"Bearer {BEARER_TOKEN}",
    "x-twitter-active-user": "yes",
    "x-twitter-auth-type": "OAuth2Session",
    "x-csrf-token": csrf_token
}
```

## 📊 Структура данных

### Результат проверки пользователя

```python
{
    "nickname": "elonmusk",
    "name": "Elon Musk", 
    "followers_count": 153000000,
    "following_count": 437,
    "tweets_count": 28341,
    "verified": False,                          # Legacy verification
    "is_blue_verified": True,                   # Twitter Blue verification
    "description": "Profile description...",
    "location": "Austin, Texas",
    "created_at": "Tue Jun 02 20:12:29 +0000 2009",
    "protected": False,                         # Private account
    "check_time": "2024-01-15 14:30:25",
    "status": "success"
}
```

### Структура ошибки

```python
{
    "nickname": "nonexistent_user",
    "status": "error",
    "error": "User not found (404)",
    "check_time": "2024-01-15 14:30:25"
}
```

## 🚀 Использование

### Проверка одного аккаунта

```python
import asyncio
from modules.twitter.twitter_check import TwitterFollowersChecker

async def check_single_user():
    async with TwitterFollowersChecker() as checker:
        result = await checker.get_user_followers_count("elonmusk")
        
        if result['status'] == 'success':
            print(f"@{result['nickname']}: {result['followers_count']} followers")
        else:
            print(f"Error checking @{result['nickname']}: {result['error']}")

# Запуск
asyncio.run(check_single_user())
```

### Массовая проверка аккаунтов

```python
async def check_multiple_users(nicknames):
    results = []
    
    async with TwitterFollowersChecker() as checker:
        for nickname in nicknames:
            try:
                result = await checker.get_user_followers_count(nickname)
                results.append(result)
                
                # Пауза между запросами
                await asyncio.sleep(SLEEP_BETWEEN_ACTIONS)
                
            except Exception as e:
                logger.error(f"Error checking @{nickname}: {e}")
                results.append({
                    "nickname": nickname,
                    "status": "error",
                    "error": str(e)
                })
    
    return results

# Список аккаунтов для проверки
nicknames = ["elonmusk", "twitter", "jack", "sundarpichai"]
results = asyncio.run(check_multiple_users(nicknames))
```

### Загрузка из CSV и сохранение результатов

```python
import csv
import asyncio

async def process_twitter_accounts():
    # Загрузка списка аккаунтов
    with open('data/twitter_accounts.csv', 'r') as f:
        reader = csv.reader(f)
        nicknames = [row[0] for row in reader if row]
    
    # Проверка аккаунтов
    results = await check_multiple_users(nicknames)
    
    # Сохранение результатов
    with open('result/twitter_check_results.csv', 'w', newline='') as f:
        fieldnames = ['nickname', 'name', 'followers_count', 'following_count', 
                     'tweets_count', 'verified', 'is_blue_verified', 'status', 'error']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in results:
            writer.writerow(result)
    
    print(f"✅ Проверено {len(results)} аккаунтов")

asyncio.run(process_twitter_accounts())
```

## 🆕 Новые возможности (2025)

### 1. Ротация токенов

Автоматическая ротация токенов для обхода rate limits:

```python
# config/modules/cfg_twitter.py
MAIN_AUTH_TOKEN = [
    'token_from_account_1',
    'token_from_account_2',
    'token_from_account_3'
]
COUNT_REPLACE_TWITTER_AUTH_TOKEN = 10  # Каждый токен используется 10 раз

# При запуске модуль покажет:
# 🔑 Конфигурация токенов:
#    📊 Всего токенов: 3
#    🔢 Использований на токен: 10
#    📈 Максимум проверок: 30
```

**Автоматическая валидация:**

```python
# Если аккаунтов больше чем max_checks:
# ⚠️ ВНИМАНИЕ: Недостаточно токенов!
#    📊 Аккаунтов для проверки: 50
#    🔑 Максимум проверок с текущими токенами: 30
#    ❌ Не хватает проверок: 20
#
# 💡 Решение:
#    1. Добавьте еще 2 токен(ов)
#    2. Или увеличьте COUNT_REPLACE_TWITTER_AUTH_TOKEN до 17
```

### 2. Случайные прокси

Автоматическая ротация прокси из файла:

```python
# config/modules/cfg_twitter.py
RANDOM_PROXIES_TWITTER = True  # Включить случайные прокси
MAIN_PROXY_TWITTER = "user:pass@backup.proxy:8080"  # Fallback прокси

# data/proxy.csv
user1:pass1@192.168.1.1:8080
user2:pass2@192.168.1.2:8080
user3:pass3@192.168.1.3:8080
```

**Работа модуля:**

- Загружает все прокси из `data/proxy.csv` при старте
- Случайно выбирает прокси для каждой проверки
- При ошибке прокси использует `MAIN_PROXY_TWITTER`
- Логирует выбранный прокси: `🌐 Используем прокси: 192.168.1.1:8080`

### 3. Расширенная статистика

При запуске модуль показывает:

```text
🚀 Twitter Followers Checker
==================================================
Current Date and Time (UTC): 2025-10-08 14:30:25
Operating System: Windows
Threads: 5
Delay between requests: 2-5s
Proxy: user:pass@proxy.com:8080
==================================================

🔑 Конфигурация токенов:
   📊 Всего токенов: 3
   🔢 Использований на токен: 10
   📈 Максимум проверок: 30
==================================================

📋 Found 25 nicknames to check
✅ Токенов достаточно: 30 проверок доступно для 25 аккаунтов
```

### 4. Умные задержки

Случайные паузы между запросами:

```python
# config/modules/cfg_base.py
SLEEP_BETWEEN_ACTIONS = (2, 5)  # От 2 до 5 секунд

# В коде:
import random
await asyncio.sleep(random.uniform(2, 5))  # Случайная пауза
```

**Преимущества:**

- Имитация человеческого поведения
- Снижение вероятности бана
- Более естественный паттерн запросов

## 📁 Входные и выходные данные

### Входной файл

- **Путь**: `data/twitter_accounts.csv`
- **Формат**: один никнейм на строку (без @)

```csv
elonmusk
twitter
jack
sundarpichai
```

### Выходной файл

- **Путь**: `result/twitter_check_results.csv`
- **Формат**: детальная информация по каждому аккаунту

```csv
nickname,name,followers_count,following_count,tweets_count,verified,is_blue_verified,status,error
elonmusk,Elon Musk,153000000,437,28341,False,True,success,
twitter,Twitter,60500000,256,15023,True,True,success,
nonexistent,,,,,,,error,User not found (404)
```

## 📊 Логирование

### Файлы логов

- **Путь**: `log/twitter_check_YYYYMMDD_HHMMSS.log`
- **Ротация**: 10 MB
- **Хранение**: 7 дней

### Примеры логов

```text
2024-01-15 14:30:25 | INFO | Using proxy: 192.168.1.1:8080
2024-01-15 14:30:26 | INFO | Checking @elonmusk...
2024-01-15 14:30:27 | INFO | @elonmusk: 153M followers
2024-01-15 14:30:30 | ERROR | Access denied (403) for @private_user
2024-01-15 14:30:33 | ERROR | Rate limit exceeded (429). Waiting...
2024-01-15 14:30:34 | INFO | 🔄 Переключение токена: 0 → 1 (использовано 10/10)
```

## ⚡ Производительность и ограничения

### Rate Limits

- **Официальные лимиты**: ~300 запросов/15 минут (на токен)
- **Рекомендуемые паузы**: 2-5 секунд между запросами
- **Прокси ротация**: для увеличения лимитов
- **Ротация токенов**: автоматическая смена после лимита

### Оптимизации

```python
# Динамические задержки при rate limiting
async def smart_delay(response_status):
    if response_status == 429:  # Rate limit
        await asyncio.sleep(900)  # 15 минут
    elif response_status == 503:  # Service unavailable
        await asyncio.sleep(60)   # 1 минута
    else:
        await asyncio.sleep(SLEEP_BETWEEN_ACTIONS)
```

## 🛠️ Диагностика ошибок

### Диагностика ошибок

1. **403 Forbidden**

   ```text
   Error: Access denied - invalid token or suspended account
   Solution: Обновить auth_token, проверить аккаунт
   ```

2. **401 Unauthorized**

   ```text
   Error: Auth token expired or invalid
   Solution: Получить новый auth_token из браузера
   ```

3. **429 Too Many Requests**

   ```text
   Error: Rate limit exceeded
   Solution: Увеличить паузы, использовать прокси, добавить токены
   ```

4. **404 Not Found**

   ```text
   Error: User not found or suspended
   Solution: Проверить правильность никнейма
   ```

5. **Недостаточно токенов**

   ```text
   ⚠️ ВНИМАНИЕ: Недостаточно токенов!
   📊 Аккаунтов для проверки: 50
   🔑 Максимум проверок с текущими токенами: 20
   ❌ Не хватает проверок: 30
   
   💡 Решение:
   1. Добавьте еще 3 токен(ов)
   2. Или увеличьте COUNT_REPLACE_TWITTER_AUTH_TOKEN
   3. Или уменьшите количество аккаунтов для проверки
   ```

### Отладочная информация

```python
# Включение debug логирования
logger.add("twitter_debug.log", level="DEBUG")

# Вывод raw response при ошибках
if response.status_code != 200:
    logger.debug(f"Raw response: {response.text}")
    logger.debug(f"Headers: {response.headers}")
```

## 🔧 Дополнительные возможности

### Фильтрация результатов

```python
def filter_high_followers(results, min_followers=100000):
    """Фильтрация аккаунтов с большим количеством подписчиков"""
    return [r for r in results if r.get('followers_count', 0) >= min_followers]

def filter_verified_accounts(results):
    """Фильтрация верифицированных аккаунтов"""
    return [r for r in results if r.get('verified') or r.get('is_blue_verified')]
```

### Статистика и аналитика

```python
def generate_stats(results):
    """Генерация статистики по результатам"""
    successful = [r for r in results if r['status'] == 'success']
    
    if not successful:
        return {}
    
    total_followers = sum(r['followers_count'] for r in successful)
    avg_followers = total_followers / len(successful)
    verified_count = len([r for r in successful if r.get('verified')])
    blue_verified_count = len([r for r in successful if r.get('is_blue_verified')])
    
    return {
        'total_accounts': len(results),
        'successful_checks': len(successful),
        'total_followers': total_followers,
        'avg_followers': avg_followers,
        'verified_accounts': verified_count,
        'blue_verified_accounts': blue_verified_count
    }
```

### Интеграция с уведомлениями

```python
from modules.notifications import send_telegram_notification

async def check_with_notifications(nickname):
    """Проверка с отправкой уведомлений"""
    async with TwitterFollowersChecker() as checker:
        result = await checker.get_user_followers_count(nickname)
        
        if result['status'] == 'success':
            if result['followers_count'] > 1000000:
                send_telegram_notification(
                    notif_type="success",
                    title="Популярный аккаунт найден",
                    message=f"@{nickname}: {result['followers_count']} подписчиков",
                    main_title="Twitter Monitor"
                )
        
        return result
```

## 💡 Best Practices

### Рекомендуемая конфигурация

```python
# config/modules/cfg_twitter.py & cfg_base.py

# Для малой нагрузки (до 20 аккаунтов)
MAIN_AUTH_TOKEN = ['token1', 'token2']
COUNT_REPLACE_TWITTER_AUTH_TOKEN = 10
SLEEP_BETWEEN_ACTIONS = (3, 6)
RANDOM_PROXIES_TWITTER = False

# Для средней нагрузки (20-100 аккаунтов)
MAIN_AUTH_TOKEN = ['token1', 'token2', 'token3', 'token4']
COUNT_REPLACE_TWITTER_AUTH_TOKEN = 15
SLEEP_BETWEEN_ACTIONS = (2, 5)
RANDOM_PROXIES_TWITTER = True

# Для высокой нагрузки (100+ аккаунтов)
MAIN_AUTH_TOKEN = ['token1', 'token2', 'token3', 'token4', 'token5', 'token6']
COUNT_REPLACE_TWITTER_AUTH_TOKEN = 20
SLEEP_BETWEEN_ACTIONS = (2, 4)
RANDOM_PROXIES_TWITTER = True
NUM_THREADS = 10
```

### Безопасность токенов

1. **Не коммитьте токены в Git**
2. **Используйте .env файлы** для хранения токенов
3. **Регулярно обновляйте** токены
4. **Используйте разные аккаунты** для токенов
5. **Мониторьте использование** через логи

### Оптимизация производительности

```python
# 1. Предварительная валидация
def validate_nicknames(nicknames):
    """Проверка корректности никнеймов перед запуском"""
    valid = []
    for nick in nicknames:
        if nick and len(nick) <= 15 and nick.replace('_', '').isalnum():
            valid.append(nick)
    return valid

# 2. Батчинг запросов
async def process_in_batches(nicknames, batch_size=50):
    """Обработка аккаунтов батчами"""
    for i in range(0, len(nicknames), batch_size):
        batch = nicknames[i:i + batch_size]
        await check_multiple_users(batch)
        await asyncio.sleep(300)  # Пауза между батчами

# 3. Кэширование результатов
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=1000)
def get_cached_result(nickname, timestamp):
    """Кэш результатов на 1 час"""
    # timestamp округлен до часа
    pass
```

## 📝 Changelog

### Версия 2.0 (Октябрь 2025)

- ✨ **NEW**: Автоматическая ротация токенов с TokenManager
- ✨ **NEW**: Случайные прокси из CSV файла (data/proxy.csv)
- ✨ **NEW**: Валидация достаточности токенов перед запуском
- ✨ **NEW**: Расширенная статистика использования токенов
- ✨ **NEW**: Умные задержки с random паузами (tuple support)
- ✨ **NEW**: Автоматический fallback на основной прокси
- 🐛 **FIX**: Улучшена обработка ошибок Twitter API
- 🐛 **FIX**: Оптимизирована работа с прокси-серверами
- 📚 **DOCS**: Полностью обновлена документация с примерами
- 🎨 **UI**: Улучшенные логи с эмодзи и цветами

### Версия 1.0 (2024)

- Начальная версия модуля
- Базовая проверка аккаунтов Twitter
- Поддержка прокси
- Асинхронная обработка

## 🤝 Поддержка

Если у вас возникли вопросы или проблемы:

1. Проверьте логи в `log/twitter_check_*.log`
2. Убедитесь что токены актуальны
3. Проверьте конфигурацию в `config/modules/cfg_twitter.py`
4. Создайте issue в репозитории

---

**Автор:** DenisHumen  
**Дата обновления:** 8 октября 2025  
**Версия:** 2.0

