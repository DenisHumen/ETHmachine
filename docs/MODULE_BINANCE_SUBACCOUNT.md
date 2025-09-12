# 👥 Модуль Binance Subaccount

## 📖 Описание

Модуль для управления субаккаунтами на бирже Binance. Обеспечивает автоматический сбор средств с субаккаунтов на основной аккаунт, мониторинг балансов и управление переводами между аккаунтами.

## 🎯 Основные функции

### `get_subaccounts_list()`

- Получение списка всех субаккаунтов
- Отображение статуса каждого аккаунта
- Подсчет активных субаккаунтов

### `get_subaccount_balance(email)`

- Проверка баланса конкретного субаккаунта
- Получение данных по всем активам
- Фильтрация положительных балансов

### `get_main_account_balance()`

- Мониторинг баланса основного аккаунта
- Проверка spot балансов
- Отслеживание изменений

### `transfer_from_subaccount_to_main()`

- Перевод средств с субаккаунта на основной
- Universal Transfer API
- Подтверждение успешных операций

### `collect_all_subaccount_balances()`

- Массовый сбор средств со всех субаккаунтов
- Автоматическая обработка всех активов
- Детальная статистика операций

## ⚙️ Настройки API

```python
# config/cex_settings.py
binance_api_key = "your_api_key"
secret_key = "your_secret_key"
```

## 🔧 Параметры клиента

```python
class BinanceClient:
    def __init__(self, api_key, secret_key, testnet=False):
        self.base_url = "https://api.binance.com"  # Production
        # self.base_url = "https://testnet.binance.vision"  # Testnet
```

## 📊 Результаты и логи

- **Логи ошибок**: `log/binance_subaccount_errors.log`
- **Полные логи**: `log/binance_subaccount_full.log`
- **Ротация**: 10 MB для ошибок, 50 MB для полных логов
- **Хранение**: 7 дней для ошибок, 3 дня для полных логов

## 🔄 Алгоритм работы

1. **Получение субаккаунтов**
   - Запрос к `/sapi/v1/sub-account/list`
   - Парсинг списка email адресов
   - Проверка статуса каждого аккаунта

2. **Проверка балансов**
   - Для каждого субаккаунта запрос `/sapi/v1/sub-account/assets`
   - Фильтрация положительных балансов
   - Определение активов для перевода

3. **Выполнение переводов**
   - Universal Transfer API (`/sapi/v1/sub-account/universalTransfer`)
   - Перевод SPOT → SPOT
   - Отслеживание transaction ID

4. **Статистика результатов**
   - Подсчет успешных переводов
   - Учет неудачных операций
   - Итоговый отчет

## 💰 Поддерживаемые активы

- **Все криптовалюты** доступные на Binance
- **Spot балансы** субаккаунтов
- **Основные токены**: BTC, ETH, BNB, USDT
- **Альткоины** и токены DeFi
- **Стейблкоины**: USDT, USDC, BUSD

## 🚀 Использование

1. **Настройка API**
   ```python
   client = BinanceClient(api_key, secret_key)
   ```

2. **Получение субаккаунтов**
   ```python
   subaccounts = client.get_subaccounts_list()
   ```

3. **Проверка баланса**
   ```python
   balance = client.get_subaccount_balance(email)
   ```

4. **Сбор средств**
   ```python
   client.collect_all_subaccount_balances()
   ```

## 🔒 Безопасность

- **HMAC-SHA256 подпись** всех запросов
- **Timestamp validation** для предотвращения replay-атак
- **API key permissions** с правами на субаккаунты
- **SSL/TLS шифрование** всех соединений
- **Детальное логирование** для аудита

## ⚡ Производительность

- **Последовательная обработка** субаккаунтов
- **Оптимизированные API вызовы**
- **Таймауты 30 секунд** для стабильности
- **Автоматические повторы** при временных сбоях
- **Цветовая индикация** прогресса

## 🛠️ Диагностика ошибок

### Типичные ошибки

1. **Недостаточные права API**
   ```
   Error: Permission denied for sub-account operations
   Solution: Включить права на субаккаунты в API настройках
   ```

2. **Неверный email субаккаунта**
   ```
   Error: Sub-account not found
   Solution: Проверить правильность email адреса
   ```

3. **Недостаточный баланс**
   ```
   Error: Insufficient balance for transfer
   Solution: Проверить доступный баланс на субаккаунте
   ```

4. **Rate limits**
   ```
   Error: Too many requests
   Solution: Увеличить паузы между запросами
   ```

### Отладочная информация

- **Подробные логи** всех API запросов
- **Response данные** от сервера
- **Статусы переводов** в реальном времени
- **Ошибки валидации** параметров

## 📈 Мониторинг

- **Real-time статус** операций переводов
- **Прогресс обработки** субаккаунтов
- **Цветные индикаторы** успеха/ошибок
- **Подсчет статистики** операций
- **Логирование результатов**

## 🔧 Настройки переводов

### Universal Transfer параметры

```python
transfer_params = {
    'fromEmail': 'subaccount@email.com',
    'toEmail': '',  # Пустое = основной аккаунт
    'fromAccountType': 'SPOT',
    'toAccountType': 'SPOT',
    'asset': 'USDT',
    'amount': '100.50'
}
```

### Поддерживаемые типы аккаунтов

- **SPOT** - Spot торговля
- **USDT_FUTURE** - USDT фьючерсы
- **COIN_FUTURE** - Coin фьючерсы
- **MARGIN** - Маржинальная торговля
- **ISOLATED_MARGIN** - Изолированная маржа

## 📋 Пример использования

```python
# Инициализация клиента
client = BinanceClient(api_key, secret_key)

# Получение списка субаккаунтов
subaccounts = client.get_subaccounts_list()
print(f"Найдено {len(subaccounts)} субаккаунтов")

# Проверка баланса первого субаккаунта
if subaccounts:
    email = subaccounts[0]['email']
    balance = client.get_subaccount_balance(email)
    print(f"Баланс {email}: {balance}")

# Автоматический сбор всех средств
client.collect_all_subaccount_balances()
```

## 🎨 Визуальные индикаторы

- 🔄 **Желтый** - Начало процесса
- ✅ **Зеленый** - Успешные операции
- ❌ **Красный** - Ошибки
- ⚠️ **Желтый** - Предупреждения
- 💰 **Золотой** - Информация о балансах
- 📊 **Синий** - Статистика и прогресс
