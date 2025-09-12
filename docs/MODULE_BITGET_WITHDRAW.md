# 💎 Модуль Bitget Withdraw

## 📖 Описание

Модуль для автоматического вывода криптовалют с биржи Bitget. Поддерживает множественные сети блокчейна, работу с прокси, многопоточность и детальное отслеживание операций.

## 🎯 Основные функции

### `bitget_signature(timestamp, method, path, secret, body)`

- Создание HMAC-SHA256 подписи для API
- Подпись запросов по стандарту Bitget
- Base64 кодирование результата

### `bitget_data(api_key, secret, passphrase, path, body, method)`

- Подготовка заголовков для API запросов
- Генерация timestamp и подписи
- Формирование URL и headers

### `get_account_balances()`

- Получение всех балансов аккаунта
- Фильтрация положительных балансов
- Форматирование данных для отображения

### `pick_token_to_withdraw(balances)`

- Интерактивный выбор токена
- Отображение доступных балансов
- Навигация с возможностью возврата

### `pick_chain(token)`

- Выбор блокчейн сети для вывода
- Получение информации о комиссиях
- Проверка доступности вывода

### `calculate_withdraw_amount(token, balance)`

- Расчет суммы для вывода
- Поддержка USDT эквивалента
- Валидация минимальных сумм

### `process_withdraw_batch()`

- Многопоточная обработка выводов
- Прогресс-бары с ETA
- База данных для отслеживания

### `BeautifulProgressBar`

- Визуальные прогресс-бары
- Расчет времени выполнения
- Цветовые индикаторы

## ⚙️ Настройки API

```python
# config/cex_settings.py
bitget_api_key = "your_api_key"
bitget_api_secret = "your_api_secret"
bitget_passphrase = "your_passphrase"
```

## 🔧 Настройки вывода

```python
# config/config.py
TYPE_WITHDRAW = 0              # 0 - нативные токены, 1 - USDT эквивалент
VALUES_TO_WITHDRAW = [5, 10]   # Диапазон суммы вывода
WAIT_FOR_BALANCE = True        # Ждать поступления на кошелек
NUM_THREADS = 5                # Количество потоков
SLEEP_BETWEEN_ACTIONS = 3      # Пауза между операциями
```

## 🌐 Прокси поддержка

- **Файл**: `data/proxy.csv`
- **Формат**: `login:password@ip:port`
- **Случайное распределение** прокси по потокам
- **HTTP/HTTPS поддержка**

### Функции прокси

```python
def load_proxies():
    # Загрузка прокси из CSV файла
    # Перемешивание в случайном порядке
    # Валидация формата

def get_random_proxy(proxies):
    # Случайный выбор прокси
    # Форматирование для requests
    # Обработка авторизации
```

## 📂 Входные данные

- **Кошельки**: `data/walletss.txt`
- **Прокси**: `data/proxy.csv`
- **Формат кошельков**:

```text
0x742d35Cc6634C0532925a3b8D6a98E8f9C1D68B1
0x8ba1f109551bD432803012645Hac136c5d66d8
```

## 📊 Результаты и логи

- **База данных**: `db/bitget_withdraw_progress.db`
- **Логи ошибок**: `log/bitget_withdraw_errors.log`
- **Полные логи**: `log/bitget_withdraw_full.log`
- **Результаты**: CSV файлы с деталями выводов

### Схема БД

```sql
CREATE TABLE withdrawals (
    id INTEGER PRIMARY KEY,
    wallet_address TEXT,
    token TEXT,
    amount REAL,
    chain TEXT,
    withdraw_id TEXT,
    status TEXT,
    fee REAL,
    created_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

## 🌐 Поддерживаемые сети

- **Ethereum** (ETH) - ERC20 токены
- **BSC** (BNB) - BEP20 токены
- **Polygon** (MATIC) - Polygon токены
- **Arbitrum** (ARB) - Arbitrum токены
- **Optimism** (OP) - Optimism токены
- **Avalanche** (AVAX) - Avalanche токены
- **Solana** (SOL) - SPL токены
- **TRON** (TRX) - TRC20 токены
- **Fantom** (FTM) - Fantom токены
- **Base** (BASE) - Base токены

## 💰 Поддерживаемые токены

- **Стейблкоины**: USDT, USDC, BUSD, DAI
- **Основные**: BTC, ETH, BNB, SOL, ADA
- **DeFi токены**: UNI, SUSHI, COMP, AAVE
- **Layer 2**: MATIC, ARB, OP
- **Altcoins**: множество других токенов

## 🚀 Использование

1. **Настройка конфигурации**
   - API ключи в `config/cex_settings.py`
   - Параметры вывода в `config/config.py`
   - Прокси в `data/proxy.csv`

2. **Подготовка данных**
   - Адреса кошельков в `data/walletss.txt`
   - Проверка балансов на бирже
   - Выбор токена и сети

3. **Запуск процесса**
   ```python
   python -m modules.cex.bitget.bitget_withdraw
   ```

4. **Мониторинг**
   - Прогресс-бары в реальном времени
   - Логи операций
   - Статус в базе данных

## 🔒 Безопасность

- **API Security**
  - HMAC-SHA256 подпись всех запросов
  - Timestamp validation
  - Passphrase аутентификация

- **Network Security**
  - SSL/TLS шифрование
  - Прокси ротация
  - IP rotation через прокси

- **Data Protection**
  - Локальное хранение конфигов
  - Шифрование чувствительных данных
  - Безопасная очистка памяти

## ⚡ Производительность

- **Многопоточность**: до 10 потоков
- **Прокси ротация**: автоматическое распределение
- **Batch processing**: группировка операций
- **Rate limiting**: соблюдение лимитов API
- **Connection pooling**: переиспользование соединений

## 🛠️ Диагностика ошибок

### Типичные ошибки

1. **API ключи недействительны**
   ```
   Error: Invalid API credentials
   Solution: Проверить ключи в config/cex_settings.py
   ```

2. **Недостаточный баланс**
   ```
   Error: Insufficient balance
   Solution: Пополнить баланс или уменьшить сумму
   ```

3. **Сеть недоступна для вывода**
   ```
   Error: Chain not available for withdrawal
   Solution: Выбрать другую поддерживаемую сеть
   ```

4. **Прокси не работает**
   ```
   Error: Proxy connection failed
   Solution: Проверить прокси в data/proxy.csv
   ```

### Отладочная информация

- **Request/Response логирование**
- **Детали ошибок API**
- **Статусы транзакций**
- **Performance метрики**

## 📈 Мониторинг

- **Real-time прогресс** с ETA расчетами
- **Цветовые индикаторы** статуса
- **Статистика операций**
- **Детальные логи** выполнения
- **Dashboard** в консоли

## 🔧 Дополнительные возможности

- **Автоматические повторы** при временных сбоях
- **Гибкие настройки** интервалов и сумм
- **Multi-exchange поддержка** (интеграция с другими биржами)
- **Webhook уведомления** о статусе операций
- **CSV экспорт** результатов

## 📋 API Endpoints

### Основные endpoints

- **Балансы**: `/api/spot/v1/account/assets`
- **Информация о монетах**: `/api/v2/spot/public/coins`
- **Вывод средств**: `/api/spot/v1/wallet/withdrawal`
- **Статус вывода**: `/api/spot/v1/wallet/withdrawal-inner-list`

### Rate Limits

- **Public API**: 20 запросов/секунду
- **Private API**: 10 запросов/секунду
- **Withdrawal API**: 5 запросов/секунду
