# ETHmachine

![logo](assets/logo.jpeg)

Если проект оказался полезен, поддержите разработчика:

**Telegram:** [@DenisHumen](https://t.me/DenisHumen)

Спасибо за поддержку!

```ETH - 0xa24fbbd57720ec580395aedba3ad37f6a6067727```

![Пожертвование](assets/usdt.jpg)

---

## 📋 О проекте

**ETHmachine** — мощный комплексный инструмент для автоматизации работы с криптовалютными кошельками, биржами, социальными сетями и утилитами для крипто-проектов. Поддерживает 50+ блокчейн-сетей, интеграцию с CEX, Twitter-автоматизацию, генерацию кошельков, управление балансами и многое другое.

## ⚡ Ключевые возможности

- 🔐 Генерация кошельков ETH/SOL с поддержкой "красивых" адресов
- 💰 Проверка балансов (нативные токены и ERC20/SPL)
- 🔄 Транзакции между кошельками и bridging через Relay
- 🏦 Интеграция с CEX: OKX, Binance, Bitget, MEXC (вывод, субаккаунты, торговля)
- 🐦 Twitter-автоматизация: проверка, сбор данных, выполнение заданий с базой данных
- 💾 Автоматическое резервное копирование (локальное + SFTP)
- 🛠️ Утилиты: проверка прокси, генераторы паролей/никнеймов/имён, проверка email через IMAP
- 📊 Детальное логирование всех операций

## 🚀 Установка

### Требования
- Python 3.10 или выше
- Git

### Шаги установки

1. **Клонируйте репозиторий:**
   ```bash
   git clone https://github.com/DenisHumen/ETHmachine
   cd ETHmachine
   ```

2. **Установите зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Запустите программу:**
   ```bash
   python main.py
   ```

## 📚 Доступные модули

### 🐦 Twitter Automation
- **Twitter Check** — Проверка валидности аккаунтов Twitter
- **Twitter Info** — Получение детальной информации о Twitter-аккаунтах
- **Twitter Tasks** — Автоматическое выполнение заданий (лайки, репосты, комментарии) с сохранением прогресса в БД

### 💼 Wallet Management
- **ETH Wallet Generator** — Генерация Ethereum кошельков с мнемоникой и приватными ключами
- **SOL Wallet Generator** — Генерация Solana кошельков
- **Nice Wallet Generator** — Генерация "красивых" адресов (с заданным префиксом/суффиксом)
- **ETH/SOL Convert Tool** — Конвертация мнемоника ↔ приватный ключ ↔ адрес кошелька

### 💰 Balance Checker
- **Check ETH Balances** — Проверка балансов нативных токенов и ERC20 в EVM-сетях
- **Check SOL Balances** — Проверка балансов SOL и SPL токенов
- **Check Eclipse Balances** — Проверка балансов в сети Eclipse

### 🔄 Transactions
- **Drainers** — Сборщик всех балансов с кошельков на главный кошелек (ETH/SOL)
- **Transfer Wallets to Wallets** — Перевод нативных токенов между кошельками
- **Transfer ERC20 Tokens** — Перевод ERC20 токенов между кошельками
- **Relay Bridge** — Мост между сетями через Relay Link с сохранением прогресса

### 🏦 CEX Integration

#### OKX
- **OKX Withdraw** — Вывод средств с OKX на кошельки с поддержкой возобновления
- **OKX Get Balances** — Получение балансов на OKX аккаунтах
- **OKX Subaccount Collector** — Сборщик средств с субаккаунтов на главный аккаунт
- **OKX Spot Trade** — Автоматическая спотовая торговля на бирже

#### Binance
- **Binance Withdraw** — Вывод средств с Binance с возможностью возобновления
- **Binance Get Balances** — Проверка балансов на Binance аккаунтах
- **Binance Subaccount Collector** — Сборщик средств с субаккаунтов Binance

#### Bitget
- **Bitget Withdraw** — Вывод средств с Bitget на кошельки

#### MEXC
- **MEXC Withdraw** — Вывод средств с MEXC на кошельки

### 💾 Backup & Sync
- **Auto Backup** — Автоматическое создание локальных резервных копий с ротацией старых бэкапов
- **Live Backup Sync** — Синхронизация бэкапов через SFTP на удаленный сервер

### 🛠️ Utilities
- **Check Gas Price** — Проверка текущей цены газа в выбранной сети
- **Check Proxy** — Массовая проверка работоспособности прокси-серверов
- **Password Generator** — Генерация криптостойких паролей по заданным параметрам
- **Nickname Generator** — Генерация реалистичных никнеймов для профилей
- **Fullname Generator** — Генерация имен и фамилий (RU/UA/ENG)
- **Last Transactions** — Проверка последних транзакций кошельков
- **Check Age Discord** — Проверка возраста Discord аккаунтов
- **Email IMAP Checker** — Валидация почтовых аккаунтов через IMAP подключение
- **Notifications** — Отправка уведомлений в Discord при завершении операций
- **Config Validator** — Проверка корректности конфигурационных файлов
- **Git Update** — Автоматическое обновление проекта через Git

## 🌐 Поддерживаемые блокчейны

**EVM-совместимые сети:**
- Ethereum (Mainnet, Sepolia, Holesky, Goerli)
- Arbitrum (Mainnet, Sepolia, Nova)
- Optimism (Mainnet, Sepolia)
- Base (Mainnet, Sepolia)
- Polygon (Mainnet, Amoy)
- Avalanche, Fantom, BSC
- Polygon zkEVM, zkSync Era
- Linea, Scroll, Mantle
- Blast, Taiko, Mode
- Zircuit, Ink, Morph
- Alienx, Lumia, Lisk
- Metal L2, Sei, XLayer
- Unichain, Swellchain, Treasure
- И многие другие...

**Solana и совместимые:**
- Solana (Mainnet, Devnet)
- Eclipse

## 📖 Документация

Детальная документация по каждому модулю доступна в папке `docs/`:
- [Модуль Twitter Tasks](docs/MODULE_TWITTER_TASKS.md) — работа с Twitter, база данных прогресса
- [Модуль OKX Withdraw](docs/MODULE_OKX_WITHDRAW.md) — настройка вывода с OKX
- [Модуль Binance Withdraw](docs/MODULE_BINANCE_WITHDRAW.md) — настройка вывода с Binance
- [Модуль Auto Backup](docs/MODULE_AUTO_BACKUP.md) — автоматическое резервное копирование
- [Полный список документации](docs/README.md)

## ⚙️ Конфигурация

Основные настройки находятся в папке `config/`:
- `config.py` — основные параметры (задержки, потоки, режимы работы)
- `cex_settings.py` — настройки бирж (API ключи, параметры вывода)
- `rpc.py` — RPC endpoints для блокчейн-сетей
- `token_address_erc20.py` — адреса токенов для работы

## 📝 Использование

После запуска `python main.py` вы увидите интерактивное меню с основными разделами:
- 💲 **BALANCES** — Проверка балансов
- 🚀 **TRANSACTIONS** — Транзакции между кошельками
- 🐦 **Twitter** — Работа с Twitter
- 🏦 **CEX** — Функционал централизованных бирж
- 🧰 **Tools** — Утилиты и генераторы
- 💾 **Backup** — Резервное копирование
- 📖 **INFO** — Справочная информация

Навигация осуществляется стрелками ↑↓ и клавишей Enter.

## 🔒 Безопасность

⚠️ **Важно:**
- Никогда не публикуйте файлы с приватными ключами (`private_keys.txt`, `mnemonic.txt`)
- Храните API ключи бирж в безопасности
- Используйте `.gitignore` для исключения конфиденциальных данных
- Регулярно создавайте резервные копии через модуль Backup

## 📊 Логирование

Все операции записываются в папку `log/`:
- Детальные логи операций (full logs)
- Логи ошибок (error logs)
- История выполнения задач

## 🤝 Вклад в проект

Если вы хотите внести свой вклад:
1. Fork репозитория
2. Создайте feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit изменений (`git commit -m 'Add some AmazingFeature'`)
4. Push в branch (`git push origin feature/AmazingFeature`)
5. Создайте Pull Request

## 📄 Лицензия

Проект распространяется под лицензией, указанной в файле [LICENSE.txt](LICENSE.txt).

---

**Разработчик:** [@DenisHumen](https://t.me/DenisHumen)  
**GitHub:** [DenisHumen/ETHmachine](https://github.com/DenisHumen/ETHmachine)
