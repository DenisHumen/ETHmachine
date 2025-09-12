# 📱 Модуль Notifications

## 📖 Описание

Модуль для отправки уведомлений в Telegram. Поддерживает различные типы уведомлений с эмодзи, форматированием, прикреплением файлов и гибкой настройкой сообщений.

## 🎯 Основные функции

### `format_notification_message()`

- Форматирование сообщений с HTML разметкой
- Автоматическое добавление эмодзи по типам
- Поддержка множественных параметров
- Структурированный вывод информации

### `send_telegram_notification()`

- Отправка уведомлений в Telegram
- Поддержка множественных chat_id
- Прикрепление файлов к сообщениям
- Обработка ошибок и таймаутов

### `send_telegram_message(message, main_title)`

- Упрощенная отправка текстовых сообщений
- Автоматический тип "info"
- Настраиваемый главный заголовок

### `send_telegram_file(file_path, caption, main_title)`

- Отправка файлов с подписями
- Поддержка CSV, TXT, LOG файлов
- Автоматическое определение типа

## ⚙️ Настройки уведомлений

```python
# config/config.py
ENABLE_NOTIFICATIONS = True                    # Включить уведомления
TELEGRAM_BOT_TOKEN = "your_bot_token"         # Токен Telegram бота
TELEGRAM_CHAT_ID = ["chat_id1", "chat_id2"]   # ID чатов для отправки
```

## 🔔 Типы уведомлений

### Доступные типы

- **info** ℹ️ - Информационные сообщения
- **success** ✅ - Успешные операции  
- **error** ❌ - Ошибки и сбои
- **warning** ⚠️ - Предупреждения
- **critical** 🚨 - Критические ошибки
- **proxy** 🟨 - Информация о прокси
- **wallet** 👛 - Операции с кошельками
- **tx** 🔗 - Информация о транзакциях
- **balance** 💰 - Данные о балансах
- **default** 🔔 - Базовый тип

### Автоматические эмодзи

```python
TYPE_EMOJI = {
    "info": "ℹ️",
    "success": "✅", 
    "error": "❌",
    "warning": "⚠️",
    "critical": "🚨",
    "proxy": "🟨",
    "wallet": "👛",
    "tx": "🔗",
    "balance": "💰",
    "default": "🔔"
}
```

## 📨 Структура сообщений

### Базовый формат

```text
✨ ETHmachine ✨
ℹ️ INFO

🔹 Title: Заголовок сообщения
📝 Message: Основной текст
👛 Wallet: 0x742d35Cc6634C0532925a3b8D6a98E8f9C1D68B1
💰 Balance: 1.5 ETH
🔗 Tx Hash: 0xabcd1234...
🌐 Explorer Link
```

### Поддерживаемые поля

- **title** - Заголовок сообщения
- **message** - Основной текст
- **proxy** - Информация о прокси
- **wallet_address** - Адрес кошелька
- **status** - Статус операции
- **tx_hash** - Хэш транзакции
- **explorer_url** - Ссылка на explorer
- **balance** - Баланс кошелька
- **extra** - Дополнительная информация
- **main_title** - Главный заголовок
- **kwargs** - Любые дополнительные поля

## 🚀 Использование

### Базовое текстовое сообщение

```python
from modules.notifications import send_telegram_message

# Простое сообщение
send_telegram_message("Операция завершена успешно!")

# С кастомным заголовком
send_telegram_message(
    message="Кошелек создан",
    main_title="Wallet Generator"
)
```

### Детальное уведомление

```python
from modules.notifications import send_telegram_notification

# Уведомление о транзакции
send_telegram_notification(
    notif_type="success",
    title="Транзакция отправлена",
    message="Перевод выполнен успешно",
    wallet_address="0x742d35Cc6634C0532925a3b8D6a98E8f9C1D68B1",
    tx_hash="0xabcd1234567890",
    explorer_url="https://etherscan.io/tx/",
    balance="1.5 ETH",
    main_title="ETH Transfer"
)
```

### Отправка файлов

```python
from modules.notifications import send_telegram_file

# Отправка CSV файла с результатами
send_telegram_file(
    file_path="result/wallets.csv",
    caption="Сгенерированные кошельки",
    main_title="Wallet Generator"
)
```

### Продвинутые уведомления

```python
# С дополнительными полями
send_telegram_notification(
    notif_type="warning",
    title="Низкий баланс газа",
    message="Требуется пополнение",
    wallet_address="0x123...",
    gas_price="25 GWEI",
    network="Ethereum",
    estimated_cost="0.005 ETH",
    main_title="Gas Monitor"
)
```

## 🔧 Настройка Telegram бота

### 1. Создание бота

1. Найти @BotFather в Telegram
2. Отправить `/newbot`
3. Указать имя и username бота
4. Получить токен бота

### 2. Получение Chat ID

```python
# Отправить любое сообщение боту, затем:
import requests

token = "your_bot_token"
url = f"https://api.telegram.org/bot{token}/getUpdates"
response = requests.get(url)
data = response.json()

# Chat ID находится в data['result'][0]['message']['chat']['id']
```

### 3. Настройка config

```python
# config/config.py
ENABLE_NOTIFICATIONS = True
TELEGRAM_BOT_TOKEN = "1234567890:ABCDEF-your-bot-token"
TELEGRAM_CHAT_ID = ["123456789", "-987654321"]  # Личные чаты и группы
```

## 📁 Поддерживаемые файлы

### Типы файлов

- **CSV** - таблицы с результатами
- **TXT** - текстовые логи
- **LOG** - файлы логирования
- **JSON** - структурированные данные

### Ограничения Telegram

- **Размер файла**: до 50 MB
- **Таймаут**: 20 секунд для загрузки
- **Формат caption**: HTML разметка

## 🔒 Безопасность

### Защита токенов

- Хранение токенов в конфигурации
- Не включение токенов в логи
- Проверка доступности API

### Контроль доступа

- Валидация chat_id
- Ограничение типов файлов
- Таймауты для запросов

## ⚡ Производительность

- **Параллельная отправка** в множественные чаты
- **Таймауты**: 10 сек для сообщений, 20 сек для файлов
- **Fallback**: продолжение при ошибках в одном чате
- **Batch operations**: поддержка массовых уведомлений

## 🛠️ Диагностика ошибок

### Типичные ошибки

1. **Неверный токен бота**
   ```
   Error: 401 Unauthorized
   Solution: Проверить TELEGRAM_BOT_TOKEN в config
   ```

2. **Неверный Chat ID**
   ```
   Error: 400 Bad Request - chat not found
   Solution: Проверить TELEGRAM_CHAT_ID
   ```

3. **Файл не найден**
   ```
   Error: FileNotFoundError
   Solution: Проверить существование file_path
   ```

4. **Превышен размер файла**
   ```
   Error: 413 Request Entity Too Large
   Solution: Файл больше 50 MB, разделить на части
   ```

### Отладочная информация

- **HTTP status codes** от Telegram API
- **Error messages** в response
- **Timeout handling** для сетевых проблем
- **Fallback behavior** при частичных сбоях

## 📊 Примеры интеграции

### С модулями кошельков

```python
# В eth_wallet_generator.py
from modules.notifications import send_telegram_notification

def create_wallet():
    # ... код создания кошелька ...
    
    send_telegram_notification(
        notif_type="success",
        title="Кошелек создан",
        wallet_address=wallet.address,
        balance="0 ETH",
        main_title="ETH Wallet Generator"
    )
```

### С модулями CEX

```python
# В binance_withdraw.py
from modules.notifications import send_telegram_notification

def withdraw_complete(tx_id, amount, token):
    send_telegram_notification(
        notif_type="success",
        title="Вывод завершен",
        message=f"Выведено {amount} {token}",
        tx_hash=tx_id,
        main_title="Binance Withdraw"
    )
```

### С результатами операций

```python
# Отправка файлов с результатами
from modules.notifications import send_telegram_file

def send_results():
    send_telegram_file(
        file_path="result/operations.csv",
        caption="📊 Результаты операций за сегодня",
        main_title="Daily Report"
    )
```
