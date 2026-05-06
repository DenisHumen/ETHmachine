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

### [MODULE_NOTIFICATIONS.md](MODULE_NOTIFICATIONS.md)
**Система уведомлений Telegram**
- Отправка сообщений и файлов
- Типизированные уведомления с эмодзи
- Поддержка HTML разметки
- Множественные чаты

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
private_key,proxy,reserve_proxy,wallet_address,mnemonic,sol_address,discord_token,email,email_password,email_imap
```

| Колонка | Описание |
|---------|----------|
| `private_key` | Приватный ключ EVM кошелька |
| `proxy` | Основной прокси (`login:pass@ip:port`) |
| `reserve_proxy` | Резервный прокси (fallback) |
| `wallet_address` | ETH-адрес (если без private_key) |
| `mnemonic` | Мнемоническая фраза (12/24 слова) |
| `sol_address` | Solana-адрес |
| `discord_token` | Discord токен |
| `email` | Email адрес |
| `email_password` | Пароль от email |
| `email_imap` | IMAP сервер |

### Несколько профилей

Файлы данных должны начинаться с `data_` и заканчиваться на `.csv` (или `data.csv` для совместимости):

- `data.csv` — основной файл
- `data_main.csv`, `data_test.csv` — дополнительные профили

Если в `data/` несколько таких файлов — при запуске будет предложен интерактивный выбор.

### Отдельные файлы (не объединяются)

- `data/transfer_token.csv` — настройки переводов ERC-20
- `data/twitter/` — Twitter аккаунты и задачи

### Централизованный загрузчик

Все модули используют `modules/data_manager.py` для загрузки данных:

```python
from modules.data_manager import (
    get_private_keys,    # List[str] — приватные ключи
    get_proxies,         # List[str] — прокси
    get_wallet_addresses,# List[str] — ETH адреса
    get_mnemonics,       # List[str] — мнемоники
    get_sol_addresses,   # List[str] — SOL адреса
    get_discord_tokens,  # List[str] — Discord токены
    get_emails,          # List[dict] — email данные
    get_proxy_for_key,   # Optional[str] — прокси для ключа
    load_data,           # List[dict] — все строки
    select_data_file,    # Path — интерактивный выбор файла
)
```

---

## 🔍 Как использовать документацию

1. Выберите нужный модуль из списка выше
2. Откройте соответствующий .md файл
3. Изучите раздел "🚀 Использование"
4. Настройте параметры в разделе "⚙️ Настройки"

---

## 🔄 Обновления документации

### Последнее обновление: март 2026

- Объединение всех файлов данных в единый `data/data.csv`
- Добавлены колонки: `sol_address`, `discord_token`, `email`, `email_password`, `email_imap`
- Поддержка нескольких профилей данных (`data_*.csv`)
- Централизованный загрузчик `modules/data_manager.py`

---

*Документация проекта ETHmachine. Все модули протестированы и готовы к использованию.*
