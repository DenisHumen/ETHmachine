# 📚 Документация модулей ETHmachine

## 📋 Индекс документации

Полная документация всех модулей проекта ETHmachine. Каждый модуль имеет детальное описание функций, настроек, использования и примеров кода.

> 🗄️ Журнал закрытых / отработанных проектов: [closed_projects/README.md](closed_projects/README.md)

---

## 🔧 Основные утилиты

### [MODULE_AUTO_BACKUP.md](MODULE_AUTO_BACKUP.md)
**Автоматическое резервное копирование**
- Создание ZIP архивов с timestamp
- Очистка старых бэкапов
- Настраиваемое расписание
- Детальное логирование

### [MODULE_LIVE_BACKUP_SYNC.md](MODULE_LIVE_BACKUP_SYNC.md) 🆕
**Live синхронизация бэкапов на SFTP**
- 🔄 Автоматическая синхронизация каждые 60 секунд
- 🔐 Шифрование данных (Fernet + PBKDF2)
- ☁️ Единая актуальная версия на сервере
- 📥 Восстановление на любом устройстве
- 🎯 Поддержка нескольких независимых копий
- **[Быстрый старт →](LIVE_BACKUP_QUICKSTART.md)**

### [MODULE_CHECK_PROXY.md](MODULE_CHECK_PROXY.md)
**Проверка прокси серверов**
- Валидация HTTP/HTTPS/SOCKS прокси
- Тестирование производительности
- Массовая проверка списков
- Экспорт рабочих прокси

### [MODULE_PASSWORD_GENERATOR.md](MODULE_PASSWORD_GENERATOR.md)
**Генератор криптостойких паролей**
- Настраиваемые параметры безопасности
- Массовая генерация
- Исключение похожих символов
- Верификация качества

---

## 🔐 Генераторы кошельков

### [MODULE_ETH_WALLET_GENERATOR.md](MODULE_ETH_WALLET_GENERATOR.md)
**Генератор Ethereum кошельков**
- BIP39/BIP44 стандарты
- Множественные форматы экспорта
- Верификация созданных кошельков
- Поддержка мнемоник и приватных ключей

### [MODULE_SOL_WALLET_GENERATOR.md](MODULE_SOL_WALLET_GENERATOR.md)
**Генератор Solana кошельков**
- Ed25519 криптография
- Base58 кодировка ключей
- Двухэтапная верификация
- Прогресс-бары генерации

---

## 💰 Модули блокчейна

### [MODULE_ETH_GET_BALANCES.md](MODULE_ETH_GET_BALANCES.md)
**Проверка балансов ETH кошельков**
- Многопоточная обработка
- Поддержка множественных сетей
- Retry механизм с прокси ротацией
- Детальное логирование ошибок

---

## 💱 CEX интеграции

### [MODULE_OKX_WITHDRAW.md](MODULE_OKX_WITHDRAW.md)
**Вывод средств с OKX**
- Поддержка множественных сетей
- HMAC-SHA256 подпись запросов
- Многопоточная обработка
- База данных отслеживания

### [MODULE_OKX_SUBACCOUNT.md](MODULE_OKX_SUBACCOUNT.md)
**Управление субаккаунтами OKX**
- Автоматический сбор средств
- Мониторинг балансов
- Universal Transfer API
- Массовые операции

### [MODULE_BINANCE_WITHDRAW.md](MODULE_BINANCE_WITHDRAW.md)
**Вывод средств с Binance**
- Интерактивный выбор токенов и сетей
- Красивые прогресс-бары
- Расчет в USD эквиваленте
- SQLite отслеживание статуса

### [MODULE_BINANCE_SUBACCOUNT.md](MODULE_BINANCE_SUBACCOUNT.md)
**Управление субаккаунтами Binance**
- Сбор средств с субаккаунтов
- SPOT балансы
- Универсальные переводы
- Детальная статистика

### [MODULE_BITGET_WITHDRAW.md](MODULE_BITGET_WITHDRAW.md)
**Вывод средств с Bitget**
- HTTP прокси поддержка
- Множественные блокчейн сети
- Прогресс-бары с ETA
- CSV результаты

---

## 🐦 Социальные сети

### [MODULE_TWITTER_CHECK.md](MODULE_TWITTER_CHECK.md)
**Проверка Twitter аккаунтов**
- Асинхронная обработка
- Получение количества подписчиков
- Статус верификации (legacy + blue)
- Rate limiting protection

---

## 📧 Email модули

### [MODULE_EMAIL_IMAP_CHECKER.md](MODULE_EMAIL_IMAP_CHECKER.md)
**IMAP проверка email аккаунтов**
- Массовая проверка через IMAP
- HTTP прокси поддержка
- Многопоточная обработка
- Автоматическое определение IMAP настроек

---

## 🎯 Статистика документации

- **Всего модулей задокументировано**: 14
- **Основные утилиты**: 5 модулей
- **Генераторы кошельков**: 2 модуля
- **Блокчейн модули**: 1 модуль
- **CEX интеграции**: 5 модулей
- **Социальные сети**: 1 модуль
- **Email модули**: 1 модуль

---

## 📂 Единый файл данных `data/data.csv`

Все данные проекта хранятся в одном CSV файле. Старые отдельные файлы (`private_keys.txt`, `proxy.csv`, `walletss.txt`, `mnemonic.txt`, `email.csv`, `discord_token.txt`, `walletss_sol.txt`) **объединены** в `data/data.csv`.

### Заголовки

```csv
name,private_key,proxy,reserve_proxy,wallet_address,mnemonic,sol_address,sol_private_key,discord_token,email,email_password,email_imap,referral_code,evm_cex_address,sol_cex_address,transfer_amount
```

| Колонка | Описание |
|---------|----------|
| `name` | Произвольное имя/метка строки |
| `private_key` | Приватный ключ EVM кошелька |
| `proxy` | Основной прокси (`login:pass@ip:port`) |
| `reserve_proxy` | Резервный прокси (fallback) |
| `wallet_address` | ETH-адрес (если без private_key) |
| `mnemonic` | Мнемоническая фраза (12/24 слова) |
| `sol_address` | Solana-адрес |
| `sol_private_key` | Solana приватный ключ (base58) |
| `discord_token` | Discord токен |
| `email` | Email адрес |
| `email_password` | Пароль от email |
| `email_imap` | IMAP сервер |
| `referral_code` | Реферальный код (на проект/кошелёк) |
| `evm_cex_address` | EVM адрес-получатель (CEX депозит / Transfer Wallets / Transfer ERC20) |
| `sol_cex_address` | SOL адрес-получатель (CEX депозит для Solana) |
| `transfer_amount` | Сумма для Transfer Wallets / Transfer ERC20 (см. форматы ниже) |

#### Форматы `transfer_amount`

| Запись | Семантика |
|---|---|
| `0.1-0.2` | диапазон сумм в нативном токене / токенах |
| `"0.1-0.2"` | процент от баланса (значение в кавычках) |
| `0.1-0.2%` | процент от баланса |
| `10-20token` | токены (фиксированное количество, для Transfer ERC20) |
| `5`, `5%`, `5token` | одиночные значения (без диапазона)

### Несколько профилей

Файлы данных должны начинаться с `data_` и заканчиваться на `.csv` (или `data.csv` для совместимости):

- `data.csv` — основной файл
- `data_main.csv`, `data_test.csv` — дополнительные профили

Если в `data/` несколько таких файлов — при запуске будет предложен интерактивный выбор.

### Отдельные файлы (не объединяются)

- `data/twitter/` — Twitter аккаунты и задачи

### Централизованный загрузчик

Все модули используют `modules/data_manager.py` для загрузки данных:

```python
from modules.data_manager import (
    # Базовые геттеры
    get_private_keys,                  # List[str] — приватные ключи
    get_proxies,                       # List[str] — прокси
    get_reserve_proxies,               # List[str] — резервные прокси
    get_wallet_addresses,              # List[str] — ETH адреса
    get_mnemonics,                     # List[str] — мнемоники
    get_sol_addresses,                 # List[str] — SOL адреса
    get_discord_tokens,                # List[str] — Discord токены
    get_emails,                        # List[dict] — email данные

    # CEX-адреса
    get_evm_cex_addresses,             # List[str] — EVM CEX-адреса
    get_sol_cex_addresses,             # List[str] — SOL CEX-адреса
    get_evm_cex_address_for_key,       # Optional[str] — EVM CEX по private_key
    get_sol_cex_address_for_key,       # Optional[str] — SOL CEX по private_key
    get_sol_cex_address_for_sol_key,   # Optional[str] — SOL CEX по sol_private_key

    # Переводы (Transfer Wallets / Transfer ERC20)
    get_transfer_rows,                 # List[dict] — {from_wallet, to_wallet, amount, intermediary}
    get_transfer_amount_for_key,       # Optional[str] — transfer_amount по private_key

    # Прочее
    get_referral_code_for_key,         # Optional[str] — реферальный код
    get_proxy_for_key,                 # Optional[str] — прокси по private_key
    get_reserve_proxy_for_key,         # Optional[str] — резервный прокси
    get_proxy_with_fallback,           # Optional[str] — прокси по индексу с fallback
    get_row_by_index,                  # Optional[dict] — строка по индексу

    # Управление файлом
    load_data,                         # List[dict] — все строки текущего файла
    reload_data,                       # принудительная перезагрузка
    list_data_files,                   # List[Path] — все data_*.csv
    migrate_all_data_files,            # int — добавляет недостающие колонки HEADERS
    select_data_file,                  # Path — интерактивный выбор файла
)
```

#### Автоматическая миграция CSV

При первом обращении к `data_manager` запускается миграция всех `data/*.csv`:
к файлам со «своей» схемой (заголовки — подмножество `HEADERS`) безопасно
дописываются недостающие колонки. Существующие данные не теряются, файлы
с чужой схемой (`from_wallet,to_wallet,amount` и т.п.) не трогаются.

---

## 🔍 Как использовать документацию

1. Выберите нужный модуль из списка выше
2. Откройте соответствующий .md файл
3. Изучите раздел "🚀 Использование"
4. Настройте параметры в разделе "⚙️ Настройки"

---

## 🔄 Обновления документации

### Май 2026

- 🆕 Колонки `evm_cex_address`, `sol_cex_address` — единый источник адресов-получателей для CEX-выводов и Transfer-модулей
- 🆕 Колонка `transfer_amount` — амаунт для Transfer Wallets / Transfer ERC20 (форматы: диапазон, процент, токены)
- 🗑️ Удалён отдельный файл `data/transfer_token.csv` — все его поля переехали в `data/data.csv`:
  - `from_wallet` ↔ `private_key`
  - `to_wallet` ↔ `evm_cex_address`
  - `amount` ↔ `transfer_amount`
- ⚙️ Автоматическая миграция CSV: недостающие колонки дописываются при старте без потери данных
- 📁 Лениво создаются каталоги `result/twitter`, `result/discord`, `result/email` — только при запуске соответствующего модуля
- 🆕 Хелперы `get_transfer_rows`, `get_evm_cex_addresses`, `get_sol_cex_addresses`, `get_transfer_amount_for_key`, и др.

### Март 2026

- Объединение всех файлов данных в единый `data/data.csv`
- Добавлены колонки: `sol_address`, `discord_token`, `email`, `email_password`, `email_imap`
- Поддержка нескольких профилей данных (`data_*.csv`)
- Централизованный загрузчик `modules/data_manager.py`

---

*Документация проекта ETHmachine. Все модули протестированы и готовы к использованию.*
