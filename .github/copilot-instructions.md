# ETHmachine - AI Coding Agent Instructions

## Project Overview
ETHmachine — инструмент автоматизации работы с криптовалютными кошельками, CEX биржами и Twitter. Основной язык: **Python 3.10+**. Интерфейс через CLI меню с `questionary`.

## Architecture

### Directory Structure
```
config/           # Конфигурация: сети, биржи, настройки модулей
  ├── config.py        # Главный конфиг (все настройки модулей)
  ├── networks.py      # Определения сетей EVM (RPC, символы, эксплореры)
  ├── cex_settings.py  # API-ключи бирж (OKX, Binance, Bitget, MEXC)
data/             # Входные данные (кошельки, прокси, CSV-файлы)
modules/          # Функциональные модули
  ├── cex/            # Биржевые интеграции (okx/, binance/, bitget/, mexc/)
  ├── eth/            # EVM операции (балансы, переводы, генерация)
  ├── sol/            # Solana операции
  ├── twitter/        # Twitter автоматизация
  ├── backup/         # Бэкапы (локальные + SFTP)
result/           # Выходные данные и логи операций
db/               # Прогресс и состояние (JSON)
```

### Module Pattern
Каждый модуль следует структуре:
```python
# 1. Импорты с явным указанием project_root
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

# 2. Импорты из config/config.py
from config.config import NUM_THREADS, RETRY_COUNT, ...
from config.networks import get_network_symbol, get_explorer_url

# 3. Настройка логирования через loguru
from loguru import logger

# 4. Функция *_menu() для интерактивного меню модуля
def check_wallet_balances_menu():
    ...
```

## Key Conventions

### Configuration
- **Все настройки в `config/config.py`** — параметры сгруппированы по модулям с разделителями `# ===`
- **Диапазоны как списки**: `SLEEP_BETWEEN_ACTIONS = [1, 3]` означает случайную задержку 1-3 сек
- **CEX аккаунты**: список dict'ов с `enabled: bool` флагом в `config/cex_settings.py`
- **Сети**: dict в `config/networks.py` с ключами `rpc_urls`, `symbol`, `tx_url`, `type` (mainnet/testnet)

### Data Files
- `data/walletss.txt` — адреса EVM кошельков (по строке)
- `data/proxy.csv` — прокси в формате `login:password@ip:port`
- `data/transfer_token.csv` — CSV: `from_wallet,to_wallet,intermediary,amount`
- `data/private_keys.txt` — приватные ключи (по строке)

### Logging & Output
- Используй `loguru.logger` для всего логирования
- Цветной вывод через `colorama.Fore` (GREEN=успех, RED=ошибка, YELLOW=предупреждение)
- Результаты в `result/` в формате CSV
- Логи ошибок в `log/` с timestamp в имени файла

### Error Handling & Retries
```python
from config.config import RETRY_COUNT  # обычно 3
for attempt in range(RETRY_COUNT):
    try:
        # операция
        break
    except Exception as e:
        logger.warning(f"Попытка {attempt+1}/{RETRY_COUNT}: {e}")
        # смена прокси/RPC если есть
```

### Telegram Notifications
Используй `modules/notifications.py`:
```python
from modules.notifications import send_telegram_notification
send_telegram_notification(
    notif_type="success",  # info/success/error/warning
    title="Операция завершена",
    message="Детали...",
    main_title="ETHmachine Transfer"
)
```

## CEX Integration Pattern
Биржи в `modules/cex/{exchange}/`:
```python
from modules.cex.exchange_selector import ExchangeSelector
selector = ExchangeSelector(specific_exchange='OKX')
exchange, account = selector.select_exchange_and_account()
```
Каждая биржа имеет: `*_withdraw.py`, `*_SubAccount.py`, опционально `*_SpotTrade.py`

## Build & Run
```bash
pip install -r requirements.txt
python main.py  # Запуск интерактивного меню
```

## Common Patterns

### Menu Function Template
```python
def my_module_menu():
    from questionary import Choice, select
    action = select(
        "Выберите действие:",
        choices=[
            Choice('🔹 Action Name     🌟 Description', 'action_key'),
            Choice('🔙 Back', 'back')
        ],
        qmark='🛠️', pointer='👉'
    ).ask()
    match action:
        case 'action_key': ...
        case 'back': return
```

### Network Selection
```python
from config.networks import get_mainnet_networks, get_testnet_networks
networks = {**get_mainnet_networks(), **get_testnet_networks()}
# Затем questionary select для выбора
```

## Testing
Ручное тестирование через меню. Логи ошибок автоматически пишутся в `log/`.
