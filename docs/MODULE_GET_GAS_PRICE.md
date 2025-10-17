# ⛽ Модуль Get Gas Price

## 📖 Описание

Модуль для получения актуальных цен газа в различных блокчейн сетях. Поддерживает множественные RPC endpoints, работу с прокси, расчет стоимости транзакций и интеграцию с CoinGecko API для получения курсов валют.

## 🎯 Основные функции

### `get_gas_price_for_network(network_name, rpc_urls, proxy)`

- Получение цены газа для конкретной сети
- Автоматическое переключение между RPC endpoints
- Retry механизм с прокси ротацией
- Расчет стоимости различных типов транзакций

### `get_eth_price_usd()`

- Получение текущей цены ETH в USD
- Использование CoinGecko API
- Обработка ошибок и таймаутов

### `get_token_price_usd(token_symbol)`

- Получение цены токенов в USD
- Поддержка основных токенов (ETH, BNB, MATIC, AVAX, FTM)
- Маппинг символов на CoinGecko ID

### `get_all_networks()`

- Автоматическое сканирование config/rpc.py
- Разделение mainnet/testnet сетей
- Получение всех доступных RPC endpoints

### `setup_gas_price_logging()`

- Настройка детального логирования
- Ротация логов по размеру (10 MB)
- Временные метки в именах файлов

### `load_proxies()`

- Загрузка прокси из data/proxy.csv
- Валидация формата прокси
- Случайное распределение

## ⚙️ Настройки

```python
# config/config.py
NUM_THREADS = 5        # Количество потоков для параллельной обработки
RETRY_COUNT = 3        # Количество повторных попыток при ошибках
```

### Поддерживаемые токены

```python
token_ids = {
    'ETH': 'ethereum',
    'BNB': 'binancecoin',
    'MATIC': 'matic-network', 
    'AVAX': 'avalanche-2',
    'FTM': 'fantom',
    'G': 'gravity',
}
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

### Testnet сети

- **Ethereum Sepolia** - тестовая сеть ETH
- **BSC Testnet** - тестовая сеть BSC
- **Polygon Mumbai** - тестовая сеть Polygon
- **Avalanche Fuji** - тестовая сеть AVAX

## 💰 Расчет стоимости транзакций

### Типы транзакций

```python
gas_limits = {
    'simple_transfer': 21000,      # Простой перевод
    'erc20_transfer': 65000,       # Перевод ERC20 токенов
    'swap_uniswap': 150000,        # Swap на Uniswap
    'nft_mint': 200000,            # Минт NFT
    'contract_interaction': 100000  # Взаимодействие с контрактом
}
```

### Структура результата

```python
{
    'network_name': 'Ethereum',
    'gas_price_gwei': 25.5,
    'gas_price_wei': 25500000000,
    'block_number': 18123456,
    'tx_costs': {
        'simple_transfer': {
            'gas_limit': 21000,
            'cost_wei': 535500000000000,
            'cost_native': 0.0005355,
            'native_symbol': 'ETH'
        }
    },
    'rpc_url': 'https://eth.llamarpc.com',
    'native_symbol': 'ETH',
    'success': True,
    'error': None
}
```

## 📊 Результаты и логи

- **Логи**: `log/gas_price_YYYYMMDD_HHMMSS.log`
- **Ротация**: 10 MB
- **Хранение**: 7 дней
- **Формат**: timestamp, level, message

### Структура CSV результатов

```csv
network,gas_price_gwei,gas_price_wei,block_number,simple_transfer_cost,erc20_transfer_cost,native_symbol,rpc_url,status,error
Ethereum,25.5,25500000000,18123456,0.0005355,0.0016575,ETH,https://eth.llamarpc.com,success,
BSC,3.2,3200000000,32145678,0.0000672,0.000208,BNB,https://bsc-dataseed.binance.org,success,
```

## 🔄 Retry механизм

### Стратегия повторов

1. **Первичный запрос** к первому RPC
2. **Retry с тем же RPC** при ошибке (до RETRY_COUNT раз)
3. **Смена прокси** при каждом retry
4. **Переход к следующему RPC** после исчерпания попыток
5. **Финальная ошибка** если все RPC failed

### Обработка ошибок

```python
def get_short_error_message(error_str):
    # Преобразование технических ошибок в понятные
    error_mappings = {
        'connection/timeout': 'Ошибка подключения',
        'poa chain': 'Несовместимая сеть (POA)',
        'too many requests': 'Превышен лимит запросов',
        'proxy': 'Ошибка прокси',
        'ssl/certificate': 'Ошибка SSL сертификата'
    }
```

## 🚀 Использование

### Получение цены газа для одной сети

```python
from modules.get_gas_price import get_gas_price_for_network
import config.rpc as rpc

# Получение цены газа для Ethereum
result = get_gas_price_for_network(
    network_name="Ethereum",
    rpc_urls=rpc.ethereum_rpc,
    proxy=None
)

if result['success']:
    print(f"Gas price: {result['gas_price_gwei']} GWEI")
    print(f"Simple transfer cost: {result['tx_costs']['simple_transfer']['cost_native']} ETH")
```

### Массовое получение цен газа

```python
from modules.get_gas_price import get_all_networks
from concurrent.futures import ThreadPoolExecutor

networks = get_all_networks()

def process_network(network_data):
    network_name, rpc_urls = network_data
    return get_gas_price_for_network(network_name, rpc_urls)

# Параллельная обработка всех сетей
with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
    results = list(executor.map(process_network, networks.items()))
```

### Получение цен токенов

```python
from modules.get_gas_price import get_token_price_usd

# Получение цены ETH
eth_price = get_token_price_usd('ETH')
print(f"ETH price: ${eth_price}")

# Получение цены BNB  
bnb_price = get_token_price_usd('BNB')
print(f"BNB price: ${bnb_price}")
```

## 🔧 Конфигурация прокси

### Формат файла data/proxy.csv

```text
login:password@ip:port
user1:pass1@192.168.1.1:8080
user2:pass2@10.0.0.1:3128
```

### Функции работы с прокси

```python
def get_proxy_dict(proxy_string):
    """Преобразует строку прокси в формат requests"""
    auth_part, address_part = proxy_string.split('@')
    login, password = auth_part.split(':')
    ip, port = address_part.split(':')
    
    return {
        'http': f"http://{login}:{password}@{ip}:{port}",
        'https': f"http://{login}:{password}@{ip}:{port}"
    }
```

## ⚡ Производительность

- **Многопоточность**: до NUM_THREADS сетей одновременно
- **Connection pooling**: переиспользование HTTP сессий
- **Прокси ротация**: автоматическое переключение при ошибках
- **RPC fallback**: автоматический переход к резервным RPC
- **Caching**: возможность кэширования результатов

## 🛠️ Диагностика ошибок

### Типичные ошибки сетей

1. **POA сети**
   ```
   Error: POA chain extradata error
   Solution: Использовать Web3.middleware для POA сетей
   ```

2. **Rate limiting**
   ```
   Error: Too many requests (429)
   Solution: Увеличить интервалы, использовать больше RPC
   ```

3. **Прокси проблемы**
   ```
   Error: Proxy connection failed
   Solution: Проверить валидность прокси в data/proxy.csv
   ```

4. **RPC недоступен**
   ```
   Error: Connection timeout
   Solution: Проверить RPC endpoints в config/rpc.py
   ```

### Отладочная информация

- **Детальные логи** всех запросов и ответов
- **Performance метрики** времени выполнения
- **Error statistics** по типам ошибок
- **RPC health checks** доступности endpoints

## 📈 Мониторинг

### Метрики производительности

- **Время отклика** каждого RPC
- **Success rate** по сетям
- **Error distribution** по типам
- **Proxy performance** статистика

### Алерты и уведомления

```python
# Интеграция с notifications модулем
from modules.notifications import send_telegram_notification

def alert_high_gas():
    if gas_price > 50:  # GWEI
        send_telegram_notification(
            notif_type="warning",
            title="Высокая цена газа",
            message=f"Gas price: {gas_price} GWEI",
            main_title="Gas Monitor"
        )
```

## 🔧 Интеграция с другими модулями

### С ETH модулями

```python
# В eth_wallet_generator.py
from modules.get_gas_price import get_gas_price_for_network

# Проверка цены газа перед транзакцией
gas_data = get_gas_price_for_network('Ethereum', rpc.ethereum_rpc)
if gas_data['gas_price_gwei'] > 30:
    print("⚠️ Высокая цена газа, ожидание...")
```

### С CEX модулями

```python
# Расчет оптимального времени для вывода
def optimal_withdraw_time():
    gas_data = get_gas_price_for_network('Ethereum', rpc.ethereum_rpc)
    return gas_data['gas_price_gwei'] < 20  # Вывод при газе < 20 GWEI
```
