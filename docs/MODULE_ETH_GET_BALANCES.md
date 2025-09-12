# 💰 Модуль ETH Get Balances

## 📖 Описание

Модуль для массовой проверки балансов ETH кошельков в различных сетях. Поддерживает многопоточность, работу с прокси, множественные RPC endpoints и детальное логирование ошибок.

## 🎯 Основные функции

### `load_wallets()`

- Загрузка адресов кошельков из `data/walletss.txt`
- Автоматическая фильтрация пустых строк
- Проверка существования файла

### `load_proxies()`

- Загрузка прокси из `data/proxy.csv`
- Валидация формата CSV
- Fallback при отсутствии прокси

### `get_wallet_balance_with_retry(wallet, network, rpc_urls, proxies)`

- Получение баланса кошелька с повторными попытками
- Автоматическое переключение между RPC
- Ротация прокси при ошибках
- Retry механизм до RETRY_COUNT раз

### `check_balance_for_network(wallet, network_name, rpc_urls, proxy)`

- Проверка баланса в конкретной сети
- Подключение к Web3 через RPC
- Конвертация Wei в нативную валюту
- Обработка ошибок подключения

### `setup_error_logging()`

- Настройка детального логирования ошибок
- Создание уникальных файлов логов с timestamp
- Форматирование с контекстной информацией
- Ротация и сохранение в `log/` директории

### `log_error(logger, wallet, error, proxy, rpc_url, network, attempt)`

- Детальная запись ошибок с контекстом
- Включение информации о попытках
- Сокращение длинных прокси строк
- Структурированный формат записей

## ⚙️ Настройки

```python
# config/config.py
NUM_THREADS = 5        # Количество потоков для параллельной обработки
RETRY_COUNT = 3        # Количество повторных попыток при ошибках
```

## 📂 Входные данные

### Файл кошельков
- **Путь**: `data/walletss.txt`
- **Формат**: один адрес на строку

```text
0x742d35Cc6634C0532925a3b8D6a98E8f9C1D68B1
0x8ba1f109551bD432803012645Hac136c5d66d8
0x1234567890123456789012345678901234567890
```

### Файл прокси
- **Путь**: `data/proxy.csv`
- **Формат**: `login:password@ip:port`

```csv
user1:pass1@192.168.1.1:8080
user2:pass2@10.0.0.1:3128
user3:pass3@172.16.0.1:1080
```

## 🌐 Поддерживаемые сети

### Mainnet сети
- **Ethereum** - основная сеть ETH
- **BSC** - Binance Smart Chain
- **Polygon** - Polygon PoS
- **Arbitrum** - Arbitrum One
- **Optimism** - Optimism mainnet
- **Avalanche** - Avalanche C-Chain
- **Fantom** - Fantom Opera
- **Base** - Base mainnet

### Получение символа нативной валюты

```python
from config.explorer_url import get_network_symbol

# Автоматическое определение символа
native_symbol = get_network_symbol('Ethereum')  # Returns 'ETH'
native_symbol = get_network_symbol('BSC')       # Returns 'BNB'
native_symbol = get_network_symbol('Polygon')   # Returns 'MATIC'
```

## 📊 Результаты и логи

### Структура результата

```python
{
    'wallet': '0x742d35Cc6634C0532925a3b8D6a98E8f9C1D68B1',
    'network': 'Ethereum',
    'balance_wei': 1500000000000000000,
    'balance_native': 1.5,
    'native_symbol': 'ETH',
    'balance_usd': 3600.0,  # Если доступен курс
    'rpc_url': 'https://eth.llamarpc.com',
    'success': True,
    'error': None,
    'attempts_used': 1,
    'proxy_used': 'user1:pass1@192.168.1.1:8080'
}
```

### Файлы логов

- **Ошибки**: `log/balance_check_errors_YYYYMMDD_HHMMSS.log`
- **Формат**: timestamp, level, retry_count, детали ошибки

```text
2024-01-15 14:30:25 | ERROR | RETRY_COUNT=3 | Wallet: 0x123... | Network: Ethereum | Attempt: 2 | Proxy: user1:pass1@192.168... | RPC: https://eth.llamarpc.com | Error: Connection timeout | Full Error: HTTPSConnectionPool...
```

## 🔄 Retry механизм

### Стратегия повторов

1. **Первичный запрос** с текущим прокси и RPC
2. **Смена прокси** при ошибке
3. **Retry до RETRY_COUNT** раз с разными прокси
4. **Переход к следующему RPC** после исчерпания попыток
5. **Финальная ошибка** если все RPC endpoints failed

### Ротация прокси

```python
def rotate_proxy(proxies, current_proxy):
    """Выбор следующего прокси для retry"""
    if not proxies:
        return None
    
    available_proxies = [p for p in proxies if p != current_proxy]
    return random.choice(available_proxies) if available_proxies else random.choice(proxies)
```

## 🚀 Использование

### Проверка баланса одного кошелька

```python
from modules.eth.eth_get_balaces import check_balance_for_network
import config.rpc as rpc

# Проверка баланса в Ethereum
result = check_balance_for_network(
    wallet="0x742d35Cc6634C0532925a3b8D6a98E8f9C1D68B1",
    network_name="Ethereum",
    rpc_urls=rpc.ethereum_rpc,
    proxy=None
)

if result['success']:
    print(f"Balance: {result['balance_native']} {result['native_symbol']}")
```

### Массовая проверка балансов

```python
from modules.eth.eth_get_balaces import load_wallets, load_proxies
from concurrent.futures import ThreadPoolExecutor

wallets = load_wallets()
proxies = load_proxies()

def process_wallet(wallet):
    return get_wallet_balance_with_retry(
        wallet=wallet,
        network="Ethereum", 
        rpc_urls=rpc.ethereum_rpc,
        proxies=proxies
    )

# Параллельная обработка
with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
    results = list(executor.map(process_wallet, wallets))

# Фильтрация успешных результатов
successful_results = [r for r in results if r['success']]
print(f"Успешно проверено: {len(successful_results)}/{len(wallets)} кошельков")
```

### Проверка в множественных сетях

```python
networks = {
    'Ethereum': rpc.ethereum_rpc,
    'BSC': rpc.bsc_rpc,
    'Polygon': rpc.polygon_rpc
}

for wallet in wallets:
    for network_name, rpc_urls in networks.items():
        result = check_balance_for_network(wallet, network_name, rpc_urls, None)
        
        if result['success'] and result['balance_native'] > 0:
            print(f"{wallet}: {result['balance_native']} {result['native_symbol']} ({network_name})")
```

## ⚡ Производительность

### Оптимизации

- **Многопоточность**: до NUM_THREADS кошельков одновременно
- **Connection pooling**: переиспользование HTTP сессий
- **Прокси ротация**: равномерное распределение нагрузки
- **RPC fallback**: автоматический переход к резервным endpoints
- **Batch processing**: группировка запросов

### Метрики производительности

```python
# Примерная скорость обработки
# 1000 кошельков с 5 потоками: ~3-5 минут
# 10000 кошельков с 10 потоками: ~20-30 минут
# Зависит от качества RPC и прокси
```

## 🛠️ Диагностика ошибок

### Классификация ошибок

```python
def get_short_error_message(error_str):
    """Преобразование технических ошибок в понятные"""
    error_mappings = {
        'connection': 'Ошибка подключения',
        'timeout': 'Таймаут соединения',
        'proxy': 'Ошибка прокси',
        'rpc': 'RPC недоступен',
        'invalid address': 'Неверный адрес кошелька',
        'rate limit': 'Превышен лимит запросов'
    }
```

### Типичные проблемы

1. **RPC перегружен**
   ```
   Error: Too many requests
   Solution: Использовать больше RPC endpoints, увеличить delays
   ```

2. **Прокси заблокированы**
   ```
   Error: Proxy connection failed
   Solution: Обновить список прокси, проверить их валидность
   ```

3. **Неверные адреса кошельков**
   ```
   Error: Invalid address format
   Solution: Валидировать адреса перед обработкой
   ```

## 📈 Статистика и мониторинг

### Отчеты по сетям

```python
def generate_network_report(results):
    """Генерация отчета по результатам проверки"""
    report = {
        'total_wallets': len(results),
        'successful_checks': len([r for r in results if r['success']]),
        'total_balance': sum(r['balance_native'] for r in results if r['success']),
        'networks': {},
        'errors': {}
    }
    
    for result in results:
        network = result['network']
        if network not in report['networks']:
            report['networks'][network] = {'count': 0, 'balance': 0}
        
        if result['success']:
            report['networks'][network]['count'] += 1
            report['networks'][network]['balance'] += result['balance_native']
```

### Интеграция с уведомлениями

```python
from modules.notifications import send_telegram_notification

def send_balance_alert(wallet, balance, network):
    """Отправка уведомления о высоком балансе"""
    if balance > 1.0:  # Более 1 ETH/BNB/MATIC
        send_telegram_notification(
            notif_type="success",
            title="Высокий баланс обнаружен",
            message=f"Кошелек имеет {balance} {network}",
            wallet_address=wallet,
            balance=f"{balance} {get_network_symbol(network)}",
            main_title="Balance Monitor"
        )
```

## 🔧 Дополнительные возможности

### Экспорт результатов

```python
def export_to_csv(results, filename):
    """Экспорт результатов в CSV"""
    with open(f"result/{filename}", 'w', newline='') as csvfile:
        fieldnames = ['wallet', 'network', 'balance_native', 'native_symbol', 'balance_usd', 'success']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in results:
            writer.writerow({
                'wallet': result['wallet'],
                'network': result['network'],
                'balance_native': result['balance_native'],
                'native_symbol': result['native_symbol'],
                'balance_usd': result.get('balance_usd', ''),
                'success': result['success']
            })
```

### Фильтрация результатов

```python
def filter_high_balances(results, min_balance=0.1):
    """Фильтрация кошельков с высокими балансами"""
    return [r for r in results if r['success'] and r['balance_native'] >= min_balance]

def filter_by_network(results, network_name):
    """Фильтрация по конкретной сети"""
    return [r for r in results if r['network'] == network_name]
```
