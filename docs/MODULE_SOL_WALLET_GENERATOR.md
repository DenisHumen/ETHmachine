# 🌌 Модуль SOL Wallet Generator

## 📖 Описание

Модуль для генерации Solana кошельков с использованием стандарта BIP39/BIP44. Создает мнемонические фразы, приватные ключи и адреса кошельков с автоматической верификацией и прогресс-барами.

## 🎯 Основные функции

### `mnemonic_to_private_key(mnemonic)`

- Конвертация мнемонической фразы в приватный ключ Solana
- Использование BIP39 для генерации seed
- Деривация ключей по BIP44 стандарту для Solana
- Создание Keypair и возврат Base58 формата

### `sol_generate_wallets(num_wallets)`

- Массовая генерация Solana кошельков
- Двухэтапный процесс: генерация + верификация
- Прогресс-бары для отслеживания процесса
- Автоматическое сохранение в CSV формате

## 🔐 Криптографические стандарты

### BIP39 - Мнемонические фразы
- **12 слов** для каждого кошелька
- **Стандартный словарь** BIP39
- **Энтропия**: 128 бит (высокая безопасность)

### BIP44 - Иерархическая деривация
- **Coin type**: Solana (501)
- **Путь деривации**: m/44'/501'/0'/0/0
- **Account**: 0 (по умолчанию)
- **Change**: External chain (0)

### Формат ключей
- **Приватный ключ**: Base58 кодировка (64 байта)
- **Публичный ключ**: Ed25519 (32 байта)
- **Адрес**: Base58 публичного ключа

## 📊 Процесс генерации

### Этап 1: Генерация (GEN)
```text
[GEN] [████████████████████░░░░░░░░░░] 150/200 | / Generating wallets...
```

1. **Создание мнемоники** - 12 случайных слов
2. **Генерация seed** из мнемоники
3. **Деривация ключей** по BIP44
4. **Создание Keypair** Solana
5. **Сохранение в CSV**

### Этап 2: Верификация (CHK)
```text
[CHK] [███████████████████████████░░░] 180/200 | \ Verifying wallets...
```

1. **Проверка по мнемонике** - импорт и сравнение адреса
2. **Проверка по приватному ключу** - импорт и сравнение
3. **Маркировка ошибок** - ⚠️ при несоответствии
4. **Обновление CSV** с результатами верификации

## 📂 Результаты

### Файл результатов
- **Путь**: `result/result.csv`
- **Кодировка**: UTF-8
- **Формат**: CSV с заголовками

### Структура CSV
```csv
mnemonic,wallet_address,private_key,check
abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about,9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM,2b4be7f19ee27bbf30c667b642d5f4aa69fd169872f8fc3059c08ebf2eb5e9d4b,
```

### Поля CSV
- **mnemonic** - 12-словная мнемоническая фраза
- **wallet_address** - публичный адрес кошелька (Base58)
- **private_key** - приватный ключ (Base58, 64 байта)
- **check** - маркер ошибок (⚠️ при проблемах)

## 🚀 Использование

### Базовая генерация
```python
from modules.sol.sol_wallet_generator import sol_generate_wallets

# Генерация 100 кошельков
sol_generate_wallets(100)
```

### Генерация с проверкой
```python
# Генерация большого количества кошельков
num_wallets = 1000
print(f"🌌 Генерируем {num_wallets} Solana кошельков...")

sol_generate_wallets(num_wallets)

print("✅ Генерация завершена!")
print("📄 Результаты сохранены в result/result.csv")
```

### Проверка отдельной мнемоники
```python
from modules.sol.sol_wallet_generator import mnemonic_to_private_key

mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
private_key, address = mnemonic_to_private_key(mnemonic)

print(f"Address: {address}")
print(f"Private Key: {private_key}")
```

## 🔧 Технические детали

### Зависимости
```python
from bip_utils import (
    Bip39MnemonicGenerator,    # Генерация мнемоник
    Bip39SeedGenerator,        # Генерация seed
    Bip44,                     # BIP44 деривация
    Bip44Coins,               # Константы монет
    Bip44Changes              # Типы изменений
)
from solders.keypair import Keypair  # Solana keypair
import base58                        # Base58 кодировка
```

### Алгоритм деривации
```python
# 1. Генерация seed из мнемоники
seed_bytes = Bip39SeedGenerator(mnemonic).Generate()

# 2. Создание master context для Solana
bip44_mst_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)

# 3. Деривация по пути m/44'/501'/0'/0/0
bip44_acc_ctx = bip44_mst_ctx.Purpose().Coin().Account(0)
bip44_chg_ctx = bip44_acc_ctx.Change(Bip44Changes.CHAIN_EXT)

# 4. Извлечение ключей
priv_key = bip44_chg_ctx.PrivateKey().Raw().ToBytes()
pub_key = bip44_chg_ctx.PublicKey().RawCompressed().ToBytes()[1:]

# 5. Создание полного 64-байтового ключа
full_keypair_bytes = priv_key + pub_key
```

## ⚡ Производительность

### Скорость генерации
- **100 кошельков**: ~5-10 секунд
- **1,000 кошельков**: ~30-60 секунд  
- **10,000 кошельков**: ~5-10 минут

### Оптимизации
- **Прогресс-бары** для визуального контроля
- **Потоковая запись** в CSV для экономии памяти
- **Двухэтапная верификация** для надежности
- **Spinner анимация** для интерактивности

## 🔒 Безопасность

### Криптографическая стойкость
- **128-бит энтропия** мнемонических фраз
- **Ed25519** криптография для ключей
- **BIP39/BIP44** проверенные стандарты
- **Secure random** генерация

### Верификация
- **Двойная проверка** каждого кошелька
- **Сравнение адресов** при импорте по мнемонике
- **Сравнение адресов** при импорте по приватному ключу
- **Маркировка ошибок** для проблемных кошельков

## 🛠️ Диагностика ошибок

### Типичные проблемы

1. **Ошибка генерации мнемоники**
   ```
   Error: Invalid mnemonic generation
   Solution: Проверить bip_utils версию и зависимости
   ```

2. **Ошибка создания Keypair**
   ```
   Error: Invalid keypair bytes
   Solution: Проверить правильность 64-байтового формата
   ```

3. **Ошибка Base58 кодировки**
   ```
   Error: Invalid Base58 format
   Solution: Проверить корректность приватного ключа
   ```

### Отладочная информация
```python
# Добавление debug информации
try:
    mnemonic = Bip39MnemonicGenerator().FromWordsNumber(12)
    priv_key, pub_key = mnemonic_to_private_key(mnemonic)
    print(f"Debug: Mnemonic length: {len(mnemonic.split())}")
    print(f"Debug: Private key length: {len(base58.b58decode(priv_key))}")
    print(f"Debug: Address format: {len(pub_key)}")
except Exception as e:
    print(f"Error details: {e}")
```

## 📊 Статистика и мониторинг

### Метрики генерации
```python
def generate_stats(num_wallets):
    """Статистика процесса генерации"""
    start_time = time.time()
    
    sol_generate_wallets(num_wallets)
    
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"📊 Статистика генерации:")
    print(f"   Кошельков: {num_wallets}")
    print(f"   Время: {duration:.2f} секунд")
    print(f"   Скорость: {num_wallets/duration:.1f} кошельков/сек")
```

### Проверка качества
```python
def check_wallet_quality(csv_file):
    """Проверка качества сгенерированных кошельков"""
    import pandas as pd
    
    df = pd.read_csv(csv_file)
    
    # Статистика
    total = len(df)
    errors = len(df[df['check'].str.contains('⚠️', na=False)])
    success_rate = ((total - errors) / total) * 100
    
    print(f"📈 Качество кошельков:")
    print(f"   Всего: {total}")
    print(f"   Ошибок: {errors}")
    print(f"   Успешность: {success_rate:.2f}%")
```

## 🔧 Интеграция

### С другими модулями
```python
# Использование в основном скрипте
from modules.sol.sol_wallet_generator import sol_generate_wallets

def wallet_generation_menu():
    try:
        count = int(input("Введите количество кошельков: "))
        sol_generate_wallets(count)
        print("✅ Кошельки созданы успешно!")
    except ValueError:
        print("❌ Введите корректное число")
```

### Экспорт в другие форматы
```python
def export_to_txt(csv_file):
    """Экспорт приватных ключей в TXT"""
    import pandas as pd
    
    df = pd.read_csv(csv_file)
    
    with open('result/solana_private_keys.txt', 'w') as f:
        for key in df['private_key']:
            f.write(f"{key}\n")
    
    print("📄 Приватные ключи экспортированы в TXT")
```
