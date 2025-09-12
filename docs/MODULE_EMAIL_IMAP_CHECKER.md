# 📧 Модуль Email IMAP Checker

## 📖 Описание

Модуль для массовой проверки email аккаунтов через IMAP протокол. Поддерживает многопоточность, работу с HTTP прокси, автоматическое определение IMAP серверов и детальное логирование результатов.

## 🎯 Основные функции

### `EmailChecker`

- Основной класс для проверки email аккаунтов
- Поддержка HTTP прокси для каждого потока
- Автоматическое определение IMAP настроек
- Retry механизм при ошибках подключения

### `setup_http_proxy(proxy_string)`

- Настройка HTTP прокси для urllib
- Поддержка авторизации (login:password@ip:port)
- Интеграция с imaplib через urllib
- Обработка ошибок прокси

### `get_imap_settings(email_domain)`

- Автоматическое определение IMAP сервера и порта
- База данных популярных email провайдеров
- Поддержка Gmail, Outlook, Yahoo, Mail.ru и других
- Fallback на стандартные настройки

### `check_email_account(email, password, proxy)`

- Проверка доступности email аккаунта
- Подключение через IMAP с SSL
- Получение информации о папках
- Подсчет количества сообщений

### `run_email_checker()`

- Главная функция запуска модуля
- Многопоточная обработка аккаунтов
- Прогресс-бар с ETA расчетами
- Сохранение результатов в CSV

## ⚙️ Настройки

```python
# config/config.py
NUM_THREADS = 5                # Количество потоков для проверки
SLEEP_BETWEEN_ACTIONS = 2      # Пауза между операциями (секунды)
```

## 📂 Входные данные

### Файл с email аккаунтами

- **Путь**: `data/email.csv`
- **Формат**: CSV с заголовками
- **Кодировка**: UTF-8

```csv
email,password,imap_domain
test@gmail.com,password123,gmail.com
user@outlook.com,mypass456,outlook.com
admin@mail.ru,secretpass,mail.ru
```

### Файл с прокси

- **Путь**: `data/proxy.csv`
- **Формат**: `login:password@ip:port`

```csv
user1:pass1@192.168.1.1:8080
user2:pass2@10.0.0.1:3128
user3:pass3@172.16.0.1:1080
```

## 🌐 Поддерживаемые провайдеры

### Автоматическое определение IMAP

```python
IMAP_SETTINGS = {
    'gmail.com': ('imap.gmail.com', 993),
    'outlook.com': ('outlook.office365.com', 993),
    'hotmail.com': ('outlook.office365.com', 993),
    'live.com': ('outlook.office365.com', 993),
    'yahoo.com': ('imap.mail.yahoo.com', 993),
    'mail.ru': ('imap.mail.ru', 993),
    'yandex.ru': ('imap.yandex.ru', 993),
    'rambler.ru': ('imap.rambler.ru', 993),
    'aol.com': ('imap.aol.com', 993),
    'zoho.com': ('imap.zoho.com', 993)
}
```

### Fallback настройки

- **Сервер**: imap.{domain}
- **Порт**: 993 (IMAP SSL)
- **Шифрование**: SSL/TLS

## 📊 Результаты

### Выходной CSV файл

- **Путь**: `result/email_check_results.csv`
- **Формат**: детальные результаты проверки

```csv
email,password,imap_domain,status,error_message,inbox_count,proxy_used,check_time
test@gmail.com,password123,gmail.com,success,,157,192.168.1.1:8080,2024-01-15 14:30:25
user@outlook.com,mypass456,outlook.com,failed,Authentication failed,,10.0.0.1:3128,2024-01-15 14:30:30
admin@mail.ru,secretpass,mail.ru,success,,42,172.16.0.1:1080,2024-01-15 14:30:35
```

### Поля результата

- **email** - проверяемый email адрес
- **password** - использованный пароль
- **imap_domain** - домен для IMAP подключения
- **status** - результат проверки (success/failed)
- **error_message** - описание ошибки при неудаче
- **inbox_count** - количество сообщений в INBOX
- **proxy_used** - использованный прокси
- **check_time** - время проверки

## 🚀 Использование

### Запуск через главное меню

1. Запустите `main.py`
2. Выберите `📧 Email` → `📧 Check IMAP emails`
3. Дождитесь завершения проверки
4. Результаты сохранятся в `result/email_check_results.csv`

### Программный запуск

```python
from modules.email.email_imap_checker import run_email_checker

# Запуск проверки email аккаунтов
run_email_checker()
```

### Проверка одного аккаунта

```python
from modules.email.email_imap_checker import EmailChecker

# Создание checker экземпляра
checker = EmailChecker()

# Проверка одного аккаунта
result = checker.check_email_account(
    email="test@gmail.com",
    password="password123", 
    proxy="user:pass@192.168.1.1:8080"
)

print(f"Status: {result['status']}")
if result['status'] == 'success':
    print(f"Inbox messages: {result['inbox_count']}")
```

## 🔧 HTTP Прокси настройка

### Формат прокси

```python
# Поддерживаемые форматы:
"login:password@192.168.1.1:8080"  # С авторизацией
"192.168.1.1:8080"                 # Без авторизации
```

### Функция настройки прокси

```python
def setup_http_proxy(proxy_string):
    """Настройка HTTP прокси для urllib"""
    if not proxy_string:
        return
    
    try:
        if '@' in proxy_string:
            # Формат: login:password@ip:port
            auth_part, addr_part = proxy_string.split('@', 1)
            proxy_url = f"http://{auth_part}@{addr_part}"
        else:
            # Формат: ip:port
            proxy_url = f"http://{proxy_string}"
        
        # Настройка urllib для использования прокси
        proxy_handler = urllib.request.ProxyHandler({
            'http': proxy_url,
            'https': proxy_url
        })
        
        opener = urllib.request.build_opener(proxy_handler)
        urllib.request.install_opener(opener)
        
    except Exception as e:
        logger.error(f"Ошибка настройки прокси {proxy_string}: {e}")
```

## ⚡ Производительность

### Многопоточность

- **NUM_THREADS потоков** одновременно
- **Прокси ротация** между потоками
- **Автоматические паузы** между операциями
- **Progress bar** с ETA расчетами

### Типичная скорость

- **100 аккаунтов**: ~2-5 минут (5 потоков)
- **1000 аккаунтов**: ~15-30 минут (5 потоков)
- **Зависит от**: качества прокси, ответа IMAP серверов

## 🛠️ Диагностика ошибок

### Типичные ошибки

1. **Authentication failed**
   ```
   Error: Неверный логин или пароль
   Solution: Проверить данные аккаунта, включить IMAP в настройках
   ```

2. **Connection timeout**
   ```
   Error: Таймаут подключения к IMAP серверу
   Solution: Проверить прокси, попробовать другой IMAP сервер
   ```

3. **Proxy connection failed**
   ```
   Error: Не удается подключиться через прокси
   Solution: Проверить данные прокси в data/proxy.csv
   ```

4. **IMAP server not found**
   ```
   Error: Не найден IMAP сервер для домена
   Solution: Добавить настройки в IMAP_SETTINGS или проверить домен
   ```

### Отладочная информация

```python
# Включение debug логирования
import logging
logging.basicConfig(level=logging.DEBUG)

# Проверка IMAP настроек
from modules.email.email_imap_checker import get_imap_settings
settings = get_imap_settings('gmail.com')
print(f"IMAP server: {settings[0]}:{settings[1]}")

# Тест прокси
from modules.email.email_imap_checker import setup_http_proxy
setup_http_proxy('user:pass@192.168.1.1:8080')
```

## 📊 Логирование

### Файлы логов

- **Основные логи**: консольный вывод с прогресс-баром
- **Ошибки**: автоматическое логирование в случае сбоев
- **Debug**: детальная информация о процессе

### Уровни логирования

```python
logger.info(f"✅ Успешно: {email} - {inbox_count} сообщений")
logger.warning(f"⚠️ Предупреждение: {email} - {warning_message}")
logger.error(f"❌ Ошибка: {email} - {error_message}")
```

## 🔒 Безопасность

### Защита данных

- **Локальное хранение** паролей в CSV
- **HTTP прокси** для анонимности
- **SSL/TLS шифрование** IMAP соединений
- **Не логируем пароли** в открытом виде

### Рекомендации

1. **Используйте app passwords** вместо основных паролей
2. **Настройте IMAP доступ** в почтовых клиентах
3. **Используйте качественные прокси** для защиты IP
4. **Регулярно меняйте прокси** при массовых проверках

## 🔧 Интеграция

### С уведомлениями

```python
from modules.notifications import send_telegram_notification

def send_results_notification(total_checked, successful):
    send_telegram_notification(
        notif_type="success",
        title="Email проверка завершена",
        message=f"Проверено: {total_checked}, Успешно: {successful}",
        main_title="Email Checker"
    )
```

### С другими модулями

```python
# Использование результатов для других задач
import pandas as pd

# Чтение результатов
df = pd.read_csv('result/email_check_results.csv')

# Фильтрация успешных аккаунтов
valid_emails = df[df['status'] == 'success']['email'].tolist()

# Использование для рассылок или других операций
for email in valid_emails:
    # Выполнить операции с валидными email
    pass
```

## 📈 Мониторинг и статистика

### Анализ результатов

```python
def analyze_results(csv_file):
    """Анализ результатов проверки email"""
    import pandas as pd
    
    df = pd.read_csv(csv_file)
    
    total = len(df)
    successful = len(df[df['status'] == 'success'])
    failed = len(df[df['status'] == 'failed'])
    
    success_rate = (successful / total) * 100 if total > 0 else 0
    
    print(f"📊 Статистика проверки:")
    print(f"   Всего проверено: {total}")
    print(f"   Успешных: {successful}")
    print(f"   Неудачных: {failed}")
    print(f"   Процент успеха: {success_rate:.1f}%")
    
    # Статистика по доменам
    domain_stats = df.groupby('imap_domain')['status'].value_counts()
    print(f"\n📈 Статистика по доменам:")
    print(domain_stats)

# Использование
analyze_results('result/email_check_results.csv')
```

### Real-time мониторинг

```python
# Прогресс-бар показывает:
# - Количество обработанных аккаунтов
# - Процент выполнения
# - Оценочное время завершения (ETA)
# - Скорость обработки
```

## 🎯 Примеры использования

### Проверка Gmail аккаунтов

```python
# data/email.csv
email,password,imap_domain
user1@gmail.com,apppassword1,gmail.com
user2@gmail.com,apppassword2,gmail.com

# Запуск проверки
run_email_checker()
```

### Проверка корпоративных email

```python
# Добавление корпоративного домена
IMAP_SETTINGS['company.com'] = ('mail.company.com', 993)

# data/email.csv  
email,password,imap_domain
admin@company.com,password123,company.com
```

### Использование результатов

```python
import pandas as pd

# Загрузка результатов
df = pd.read_csv('result/email_check_results.csv')

# Валидные аккаунты с большим количеством писем
high_activity = df[
    (df['status'] == 'success') & 
    (df['inbox_count'] > 100)
]

print(f"Найдено {len(high_activity)} активных аккаунтов")
```
