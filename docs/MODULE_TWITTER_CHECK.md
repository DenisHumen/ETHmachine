# 🐦 Модуль Twitter Check

## 📖 Описание

Модуль для асинхронной проверки аккаунтов Twitter/X с получением детальной информации о пользователях, включая количество подписчиков, статус верификации и активность. Поддерживает работу с прокси и массовую обработку.

## 🎯 Основные функции

### `create_twitter_client()`

- Создание асинхронного HTTP клиента для Twitter API
- Настройка заголовков и cookies для аутентификации
- Получение CSRF токена для защищенных запросов
- Поддержка прокси соединений

### `TwitterFollowersChecker`

- Класс для проверки информации о Twitter аккаунтах
- Async context manager для автоматического управления ресурсами
- Retry механизм при ошибках API
- Детальная обработка различных типов ошибок

### `get_user_followers_count(nickname)`

- Получение полной информации о пользователе по никнейму
- Извлечение количества подписчиков и подписок
- Проверка статуса верификации (legacy и blue checkmark)
- Получение метаданных профиля

### `setup_twitter_logging()`

- Настройка детального логирования
- Создание уникальных файлов с timestamp
- Ротация логов по размеру (10 MB)
- Хранение в течение 7 дней

## ⚙️ Настройки

```python
# config/config.py
MAIN_AUTH_TOKEN = "your_auth_token"           # Auth token из cookies Twitter
MAIN_PROXY_TWITTER = "user:pass@ip:port"      # Прокси для Twitter (опционально)
NUM_THREADS = 5                               # Количество потоков
SLEEP_BETWEEN_ACTIONS = 2                     # Пауза между запросами (сек)
```

## 🔐 Аутентификация

### Получение Auth Token

1. **Войти в Twitter/X** в браузере
2. **Открыть DevTools** (F12)
3. **Перейти в Application/Storage → Cookies**
4. **Найти cookie с именем `auth_token`**
5. **Скопировать значение** в config

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
```

## ⚡ Производительность и ограничения

### Rate Limits

- **Официальные лимиты**: ~300 запросов/15 минут
- **Рекомендуемые паузы**: 2-5 секунд между запросами
- **Прокси ротация**: для увеличения лимитов

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

### HTTP Status Codes

1. **403 Forbidden**
   ```
   Error: Access denied - invalid token or suspended account
   Solution: Обновить auth_token, проверить аккаунт
   ```

2. **401 Unauthorized**
   ```
   Error: Auth token expired or invalid
   Solution: Получить новый auth_token из браузера
   ```

3. **429 Too Many Requests**
   ```
   Error: Rate limit exceeded
   Solution: Увеличить паузы, использовать прокси
   ```

4. **404 Not Found**
   ```
   Error: User not found or suspended
   Solution: Проверить правильность никнейма
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
