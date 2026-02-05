# 🏢 Система множественных аккаунтов бирж

## 📖 Описание

Новая система позволяет настроить и использовать несколько аккаунтов для каждой биржи, а также выбирать между ними при запуске модулей.

## 🔧 Настройка

### 1. Конфигурация аккаунтов в `config/cex_settings.py`

```python
# Пример настройки для OKX
OKX_ACCOUNTS = [
    {
        'name': 'OKX Main',
        'api_key': 'your_api_key_here',
        'api_secret': 'your_api_secret_here', 
        'passphrase': 'your_passphrase_here',
        'type': OKX_EU_TYPE,
        'enabled': True,  # Активировать этот аккаунт
    },
    {
        'name': 'OKX Trading',
        'api_key': 'another_api_key',
        'api_secret': 'another_api_secret',
        'passphrase': 'another_passphrase', 
        'type': OKX_EU_TYPE,
        'enabled': True,
    },
]
```

### 2. Поддерживаемые биржи

- **OKX** - `OKX_ACCOUNTS`
- **Binance** - `BINANCE_ACCOUNTS`
- **Bitget** - `BITGET_ACCOUNTS`
- **MEXC** - `MEXC_ACCOUNTS`

## 🚀 Использование

### 1. Проверка конфигурации

При запуске `main.py` автоматически выполняется проверка:

```python
from modules.config_validator import validate_configuration

if not validate_configuration():
    print("❌ Обнаружены проблемы в конфигурации!")
    exit(1)
```

### 2. Выбор биржи и аккаунта

```python
from modules.exchange_selector import select_exchange_account

# Выбор биржи через интерактивное меню
exchange_name, account = select_exchange_account()

if exchange_name and account:
    print(f"Выбрана биржа: {exchange_name}")
    print(f"Аккаунт: {account['name']}")
    print(f"API Key: {account['api_key']}")
```

### 3. Интеграция в модули бирж

Обновленные модули автоматически предлагают выбор аккаунта:

```python
def mexc_withdraw():
    # Выбор аккаунта MEXC
    exchange_name, selected_account = select_exchange_account()
    
    if exchange_name == 'MEXC' and selected_account:
        api_key = selected_account['api_key']
        api_secret = selected_account['api_secret']
        # Работа с выбранным аккаунтом
```

## ⚠️ Проверки валидатора

### Критические ошибки (остановят выполнение):

- ❌ Отсутствие файлов `config/modules/cfg_*.py` или `config/cex_settings.py`
- ❌ Неверная структура настроек в конфигурационных файлах
- ❌ Синтаксические ошибки в Python файлах

### Предупреждения (не останавливают выполнение):

- ⚠️ Отсутствие настроенных аккаунтов бирж
- ⚠️ Пустые файлы данных (`proxy.csv`, `walletss.txt`, `private_keys.txt`)
- ⚠️ Неполные настройки аккаунтов (пустые API ключи)
- ⚠️ Неправильные значения параметров в `config.py`

## 📁 Структура файлов

```
config/
├── cex_settings.py     # Настройки аккаунтов бирж
├── config.py           # Основная конфигурация
└── rpc.py              # RPC настройки

modules/
├── exchange_selector.py    # Модуль выбора биржи
├── config_validator.py     # Валидатор конфигурации
└── cex/
    ├── okx/
    ├── binance/
    ├── bitget/
    └── mexc/

data/
├── proxy.csv           # Прокси
├── walletss.txt        # Кошельки
└── private_keys.txt    # Приватные ключи
```

## 🔄 Обратная совместимость

Старые переменные (`mexc_api_key`, `binance_api_key`, etc.) поддерживаются автоматически через первый активный аккаунт:

```python
# Автоматически берется из первого активного аккаунта
mexc_api_key = MEXC_ACCOUNTS[0]['api_key'] if MEXC_ACCOUNTS[0]['enabled'] else ""
```

## 📝 Пример полной настройки

```python
# config/cex_settings.py

# Множественные аккаунты MEXC
MEXC_ACCOUNTS = [
    {
        'name': 'MEXC Personal',
        'api_key': 'mx0vglR0vJshjETdzL',
        'api_secret': '9a11f39898c64ff0959347b00fc306fd',
        'enabled': True,
    },
    {
        'name': 'MEXC Business', 
        'api_key': 'mx1234567890abcdef',
        'api_secret': 'abcdef1234567890abcdef1234567890',
        'enabled': True,
    },
]

# Множественные аккаунты OKX
OKX_ACCOUNTS = [
    {
        'name': 'OKX Main',
        'api_key': '62540323-2e3c-4fef-8bcf-70afe3ef8a21',
        'api_secret': '96F046C783898844FC2485AC7AD07CA4',
        'passphrase': 'Ltybc2019$',
        'type': 0,
        'enabled': True,
    },
]
```

При запуске модуля пользователь увидит:

```
🏛️ Выберите биржу для работы:
  🏢 OKX (1 аккаунтов)
  🏢 MEXC (2 аккаунта)

👤 Выберите аккаунт MEXC:
  👤 MEXC Personal
  👤 MEXC Business
```

## 🎯 Преимущества новой системы

- ✅ **Множественные аккаунты** - можно настроить несколько аккаунтов для каждой биржи
- ✅ **Интерактивный выбор** - удобный выбор через questionary
- ✅ **Проверка конфигурации** - автоматическая валидация при запуске
- ✅ **Обратная совместимость** - старый код продолжает работать
- ✅ **Централизованное управление** - все настройки в одном месте
- ✅ **Безопасность** - проверка корректности API ключей перед использованием