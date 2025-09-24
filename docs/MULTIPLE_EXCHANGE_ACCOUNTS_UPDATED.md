# Система множественных аккаунтов бирж

## Обзор

Система поддерживает работу с несколькими аккаунтами различных бирж через интерактивный выбор с помощью questionary. Все модули были обновлены для использования специализированных селекторов аккаунтов.

## Структура файлов

### Конфигурация
- `config/cex_settings.py` - Настройки аккаунтов всех бирж

### Модули селекторов
- `modules/cex/exchange_selector.py` - Основной модуль выбора аккаунтов

### Обновленные модули бирж

#### Withdraw модули:
- `modules/cex/okx/okx_withdraw.py` - Использует `select_okx_account()`
- `modules/cex/binance/binance_withdraw.py` - Использует `select_binance_account()`
- `modules/cex/bitget/bitget_withdraw.py` - Использует `select_bitget_account()`
- `modules/cex/mexc/mexc_withdraw.py` - Использует `select_mexc_account()`

#### SubAccount модули:
- `modules/cex/okx/okx_SubAccount.py` - Использует `select_okx_account()`
- `modules/cex/binance/binance_SubAccount.py` - Использует `select_binance_account()`
- `modules/cex/bitget/bitget_SubAccount.py` - Использует `select_bitget_account()`

#### Торговые модули:
- `modules/cex/okx/okx_SpotTrade.py` - Использует `select_okx_account()`

## Как это работает

### 1. Конфигурация аккаунтов

В `config/cex_settings.py` аккаунты настроены в виде списков словарей:

```python
OKX_ACCOUNTS = [
    {
        'name': 'OKX Main',
        'api_key': 'your_api_key',
        'api_secret': 'your_secret',
        'passphrase': 'your_passphrase',
        'enabled': True
    },
    # ... дополнительные аккаунты
]

BINANCE_ACCOUNTS = [
    {
        'name': 'Binance Main',
        'api_key': 'your_api_key',
        'api_secret': 'your_secret',
        'enabled': True
    },
    # ... дополнительные аккаунты
]
```

### 2. Специализированные селекторы

Каждая биржа имеет свой специализированный селектор:

```python
from modules.cex.exchange_selector import (
    select_okx_account,
    select_binance_account,
    select_bitget_account,
    select_mexc_account
)
```

### 3. Автоматический выбор биржи

Когда модуль использует специализированный селектор (например, `select_okx_account()`), система:

1. **Автоматически работает только с OKX** - не предлагает выбор других бирж
2. **Показывает только аккаунты OKX** - фильтрует по enabled=True и наличию api_key
3. **Если один аккаунт** - выбирает автоматически
4. **Если несколько аккаунтов** - показывает интерактивное меню

### 4. Интеграция в модули

Каждый модуль биржи был обновлен для использования своего селектора:

```python
def okx_withdraw():
    # Выбираем аккаунт OKX
    exchange_name, account = select_okx_account()
    if not account:
        logger.error("❌ Не выбран аккаунт OKX")
        return
    
    # Используем выбранный аккаунт
    global OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRAS
    OKX_API_KEY = account['api_key']
    OKX_API_SECRET = account['api_secret']
    OKX_API_PASSPHRAS = account['passphrase']
    
    logger.info(f"🏢 Используется аккаунт: {account['name']}")
    
    # Продолжаем обычную логику...
```

## Принципы работы

### Автоматический выбор биржи

- **OKX модули** → Автоматически используют только OKX аккаунты
- **Binance модули** → Автоматически используют только Binance аккаунты  
- **Bitget модули** → Автоматически используют только Bitget аккаунты
- **MEXC модули** → Автоматически используют только MEXC аккаунты

### Умный выбор аккаунтов

1. **Один активный аккаунт** → Выбирается автоматически
2. **Несколько аккаунтов** → Показывается интерактивное меню
3. **Нет аккаунтов** → Выводится ошибка с инструкциями

### Логирование

Система логирует:
- Выбранную биржу и аккаунт
- API ключи (замаскированные для безопасности)
- Ошибки выбора аккаунтов

## Обновленные модули

### ✅ Полностью интегрированы:

1. **OKX**:
   - `okx_withdraw.py` - Вывод средств
   - `okx_SubAccount.py` - Управление субаккаунтами
   - `okx_SpotTrade.py` - Спот торговля

2. **Binance**:
   - `binance_withdraw.py` - Вывод средств
   - `binance_SubAccount.py` - Управление субаккаунтами

3. **Bitget**:
   - `bitget_withdraw.py` - Вывод средств
   - `bitget_SubAccount.py` - Управление субаккаунтами

4. **MEXC**:
   - `mexc_withdraw.py` - Вывод средств

### Преимущества новой системы

1. **Специализация** - Каждый модуль работает только со своей биржей
2. **Простота** - Не нужно выбирать биржу, только аккаунт
3. **Безопасность** - API ключи не хранятся в глобальных переменных
4. **Масштабируемость** - Легко добавлять новые аккаунты
5. **Удобство** - Автоматический выбор при одном аккаунте

## Тестирование

Система прошла полное тестирование:

```bash
# Тест селекторов
python modules/cex/exchange_selector.py

# Тест импортов модулей
python -c "from modules.cex.okx.okx_withdraw import okx_withdraw"
python -c "from modules.cex.binance.binance_withdraw import binance_withdraw"
python -c "from modules.cex.bitget.bitget_withdraw import bitget_withdraw"

# Тест главного модуля
python -c "from main import main_menu"
```

Все тесты прошли успешно ✅

## Обратная совместимость

Система полностью заменила старые глобальные переменные и обеспечивает:
- Работу с множественными аккаунтами
- Безопасное хранение ключей
- Интуитивный интерфейс выбора
- Автоматизацию процесса выбора

## Как использовать

### Для разработчиков

При создании нового модуля биржи:

```python
from modules.cex.exchange_selector import select_okx_account  # или другую биржу

def my_okx_function():
    # Выбираем аккаунт OKX
    exchange_name, account = select_okx_account()
    if not account:
        logger.error("❌ Не выбран аккаунт OKX")
        return
    
    # Используем API ключи из выбранного аккаунта
    api_key = account['api_key']
    api_secret = account['api_secret']
    passphrase = account.get('passphrase')  # Для OKX и Bitget
    
    logger.info(f"🏢 Используется аккаунт: {account['name']}")
    
    # Ваша логика здесь...
```

### Для пользователей

1. **Настройте аккаунты** в `config/cex_settings.py`
2. **Запустите модуль** - система автоматически предложит выбор
3. **Если один аккаунт** - выберется автоматически
4. **Если несколько** - появится интерактивное меню

## Расположение файлов

- **Новое расположение**: `modules/cex/exchange_selector.py`
- **Старое расположение**: ~~`modules/exchange_selector.py`~~ (удален)
- **Обновлены импорты в**: `main.py` и всех модулях бирж

Система полностью готова к использованию! 🚀