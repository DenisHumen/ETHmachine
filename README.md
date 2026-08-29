<div align="center">

<img src="assets/logo.jpeg" alt="ETHmachine" width="640">

# ETHmachine

**Терминальный комбайн для крипто-рутины: кошельки, балансы, переводы, биржи, тестнеты.**

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-success)](#быстрый-старт)
[![Networks](https://img.shields.io/badge/EVM%20сетей-29-6f42c1)](#поддерживаемые-сети)
[![Telegram](https://img.shields.io/badge/Telegram-@DenisHumen-26A5E4?logo=telegram&logoColor=white)](https://t.me/DenisHumen)

</div>

---

## Что это

ETHmachine — консольный инструмент для тех, кто ведёт много кошельков сразу.
Один CSV-файл с аккаунтами, одно меню — и оттуда доступны проверка балансов,
переводы, вывод с бирж, активности в тестнетах и набор бытовых утилит
(генераторы кошельков, паролей, ников, чекеры прокси и почт).

Ключевые принципы, на которых построен проект:

| | |
|---|---|
| **Один источник данных** | все аккаунты — в `data/data.csv`. Модули не читают свои файлы и не просят вводить ключи заново. |
| **Возобновляемость** | долгие операции пишут прогресс в SQLite. Прервали на 300-м кошельке — следующий запуск продолжит с 301-го, а не начнёт заново. |
| **Отчёты из базы, а не из логов** | Excel-отчёт всегда собирается из БД, поэтому он не врёт после падения. |
| **Многопоточность по умолчанию** | число потоков задаётся один раз в `general_config.py` и работает во всех модулях. |
| **Прокси на аккаунт** | у каждой строки данных свой прокси и резервный прокси. |

---

## Быстрый старт

Нужны **Python 3.10+** и **Git**.

```bash
git clone https://github.com/DenisHumen/ETHmachine
cd ETHmachine
python -m venv venv
```

Активация окружения:

```bash
venv\Scripts\activate
```

<details>
<summary>Linux / macOS</summary>

```bash
source venv/bin/activate
```

</details>

Установка зависимостей:

```bash
pip install -r requirements.txt
```

Браузерные модули (DeBank, Dune, xStocks, часть тестнетов) требуют Chromium:

```bash
python -m playwright install chromium
```

Запуск:

```bash
python main.py
```

При первом запуске программа создаст каталоги `data/`, `db/`, `result/`, `log/`,
`backups/` и шаблоны конфигов. Заполните `data/data.csv` — и можно работать.

> **Linux:** для сборки некоторых пакетов нужны заголовки Python и компилятор:
> `sudo apt install -y python3-dev build-essential`

---

## Данные: `data/data.csv`

Все аккаунты живут в одном CSV. Заполняйте только те колонки, которые нужны
вашим задачам — остальные можно оставить пустыми.

| Колонка | Что это | Пример |
|---|---|---|
| `name` | Имя аккаунта для логов | `acc-01` |
| `private_key` | Приватный ключ EVM | `0xabc…` |
| `proxy` | Основной прокси | `user:pass@ip:port` |
| `reserve_proxy` | Запасной прокси | `user:pass@ip:port` |
| `wallet_address` | EVM-адрес, если ключа нет | `0x742d…` |
| `mnemonic` | Мнемоника (12/24 слова) | `word1 word2 …` |
| `sol_address` | Адрес Solana | `7xKXt…` |
| `sol_private_key` | Приватный ключ Solana (base58) | `5J…` |
| `discord_token` | Токен Discord | `MTIx…` |
| `email` | Почта | `user@mail.com` |
| `email_password` | Пароль от почты | `••••` |
| `email_imap` | IMAP-сервер | `imap.mail.com` |
| `referral_code` | Реферальный код | `REF123` |
| `evm_cex_address` | Адрес-получатель EVM (депозит биржи) | `0x742d…` |
| `sol_cex_address` | Адрес-получатель Solana | `7xKXt…` |
| `transfer_amount` | Сумма для модулей перевода | `0.1-0.2` или `90-100%` |

**Формат `transfer_amount`:** `0.1-0.2` — случайная сумма из диапазона в
нативном токене; `"0.1-0.2"` (в кавычках) или `0.1-0.2%` — процент от баланса.

### Несколько профилей

Файлы данных должны называться `data.csv` или `data_<профиль>.csv`. Если в
`data/` их несколько, при запуске программа спросит, с каким работать:

```
data/data.csv        ← основной
data/data_main.csv
data/data_farm.csv
```

Twitter-аккаунты и задания хранятся отдельно, в `data/twitter/`.

---

## Возможности

### Балансы

| Модуль | Что делает |
|---|---|
| **EVM-сети** | Нативный токен в любой из 29 сетей |
| **ERC-20** | Балансы токенов из `config/token_address_erc20.py` |
| **Solana / Eclipse** | Нативные балансы |
| **DeBank Checker** | Все токены во всех сетях сразу (перехват API через браузер) |
| **DeBank Protocols** | DeFi-позиции: стейкинг, лендинг, LP, locked |
| **zkSync Lite** | Балансы на lite.zksync.io |

### Транзакции

| Модуль | Что делает |
|---|---|
| **Collectors** | Сбор балансов со всех кошельков на главный |
| **Перевод нативных токенов** | Между кошельками, суммой или процентом от баланса |
| **Перевод ERC-20** | То же для токенов |
| **KAVA → биржа** | Нативный KAVA на CEX через Cosmos SDK (`kava1…` → `0x…`) |
| **Relay Bridge** | Мост между сетями через Relay Link, с прогрессом в БД |

### Биржи

| Биржа | Вывод | Балансы | Субаккаунты | Спот |
|---|:---:|:---:|:---:|:---:|
| OKX | ✅ | ✅ | ✅ | ✅ |
| Binance | ✅ | ✅ | ✅ | — |
| Bitget | ✅ | — | ✅ | — |
| MEXC | ✅ | — | — | — |

Несколько аккаунтов на биржу настраиваются в `config/cex_settings.py` —
см. [docs/MULTIPLE_EXCHANGE_ACCOUNTS.md](docs/MULTIPLE_EXCHANGE_ACCOUNTS.md).

### Проекты

| Проект | Что делает |
|---|---|
| **Dune Analytics** | Проверка кошельков по дашбордам |
| **Fhenix** | Краны ghostchain и Alchemy (Sepolia) |
| **LiteForge Testnet** | Кран zkLTC, мост, свапы, NFT-минты, домены ZNS |
| **Sahara AI** | Клейм Knowledge Drop и вывод на биржу |
| **SafePal X1** | Проверка права на клейм аппаратного кошелька |
| **xStocks DeFi** | Регистрация, GM, рефералы, поинты *(на паузе)* |
| **Neura** | Статистика по аккаунтам |

### Twitter

Проверка валидности аккаунтов и автоматическое выполнение заданий
(лайки, репосты, комментарии) с сохранением прогресса в БД.

### Инструменты

| Инструмент | Что делает |
|---|---|
| **Генерация кошельков** | EVM и Solana, включая «красивые» адреса (Python или Rust) |
| **Конвертер ключей** | Мнемоника ↔ приватный ключ ↔ адрес |
| **Генератор паролей** | Криптостойкие пароли по заданным правилам |
| **Генератор никнеймов** | Правдоподобные ники под регистрации |
| **Генератор имён** | Имена и фамилии: RU / UA / ENG |
| **Проверка прокси** | Доступность, скорость, геолокация, доступ к сервисам |
| **Возраст Discord** | Дата регистрации аккаунтов по токенам |
| **Проверка почт** | Валидация ящиков по IMAP |
| **Загрузка с Pinterest** | Случайные картинки под аватарки |
| **Polygon zkEVM → Base** | Свап всех токенов в USDC через Layerswap |
| **zkSync Era → Base** | Свап USDC/USDT в USDC через Rhino.fi |

### Бэкапы

Локальные ZIP-архивы с ротацией, синхронизация на SFTP-сервер и live-режим
с шифрованием (Fernet + PBKDF2). Подробности —
[docs/MODULE_AUTO_BACKUP.md](docs/MODULE_AUTO_BACKUP.md).

---

## Конфигурация

Настройки разложены по файлам: общие — в одном месте, специфичные для модуля —
рядом с его именем.

```
config/
├── modules/
│   ├── general_config.py   ← потоки, задержки, ретраи, капча, главные кошельки
│   ├── cfg_backup.py       ← локальные бэкапы и SFTP
│   ├── cfg_cex.py          ← правила вывода с бирж
│   ├── cfg_transfer.py     ← переводы нативных токенов
│   ├── cfg_transfer_erc20.py
│   ├── cfg_twitter.py
│   ├── cfg_password.py     ← генератор паролей
│   ├── cfg_generators.py   ← генераторы ников и имён
│   ├── cfg_nice_address.py ← маски «красивых» адресов
│   └── …                   ← по одному файлу на модуль
├── cex_settings.py         ← API-ключи бирж (создаётся при первом запуске, не в git)
├── networks.py             ← RPC-эндпоинты и параметры сетей
├── token_address_erc20.py  ← адреса токенов по сетям
└── menu_config.py          ← состав меню: что показывать, в каком порядке
```

Чаще всего правят `config/modules/general_config.py`:

```python
NUM_THREADS = 5                    # параллельных аккаунтов
SLEEP_BETWEEN_ACTIONS = [2, 4]     # пауза между действиями, сек
DELAY_BETWEEN_ACCOUNTS = [3, 5]    # пауза между стартом аккаунтов, сек
RETRY_COUNT = 15                   # попыток при ошибке (смена прокси/RPC)
SHUFLE_ACCOUNTS = True             # перемешивать аккаунты при запуске
CAPTCHA_SERVICE = 'yescaptcha'     # 2captcha | anticaptcha | capsolver | yescaptcha | capmonster
```

> **Капча:** ключи сервисов пустые по умолчанию — впишите свой в
> `general_config.py`, иначе модули с капчей сообщат, что сервис не настроен.

### Отключить ненужные пункты меню

В `config/menu_config.py` у любого пункта поставьте `enabled=False` — он исчезнет
из меню. Порядок разделов задаётся списком `MAIN_MENU_ORDER`.

---

## Что происходит при запуске

`python main.py` выполняет по порядку:

1. **Проверка зависимостей** — при нехватке предложит установить.
2. **Подготовка окружения** — создаёт недостающие каталоги и шаблоны конфигов.
3. **Веб-панель** — если включена (по умолчанию **выключена**), поднимается в фоне.
4. **Проверка обновлений** — сравнивает вашу версию с GitHub. Если согласитесь
   обновиться, программа отложит ваши правки (`git stash`), выполнит `git pull`
   и **вернёт правки обратно**. При конфликте покажет, какие файлы разошлись.
5. **Бэкап** — автоматическая копия перед началом работы.
6. **Проверка конфигурации** — ищет очевидные ошибки в настройках.
7. **Выбор профиля данных** — если файлов `data_*.csv` несколько.

---

## Веб-панель

В комплекте есть локальная веб-панель (aiohttp): live-логи, просмотр баз в
`db/`, скачивание отчётов, редактирование конфигов из браузера.

**По умолчанию выключена.** Включение — в `config/modules/general_config.py`:

```python
WEB_ENABLED = True
```

Адрес и порт — в `config/modules/cfg_web.py` (по умолчанию `127.0.0.1:8765`).
Первый вход открывает `/register` и создаёт root-пользователя.

> ⚠️ **Панель показывает содержимое `data/` и `db/`, то есть ваши приватные
> ключи.** Не меняйте `WEB_HOST` на `0.0.0.0` — это откроет доступ всей
> локальной сети без шифрования.

---

## Дополнительные зависимости

Нужны только для конкретных модулей — остальное работает без них.

| Модуль | Требуется | Установка |
|---|---|---|
| DeBank, Dune, xStocks | Chromium для Playwright | `python -m playwright install chromium` |
| LiteForge (обход Vercel) | Patchright + Chromium | `pip install patchright && python -m patchright install chromium` |
| zkSync Lite → Era | Node.js 18+ | `cd modules/zksync_lite/swap/node_helper && npm install` |
| Красивые адреса (Rust) | Cargo | [rustup.rs](https://rustup.rs) |

---

## Поддерживаемые сети

**Mainnet (23):** Ethereum, Base, Arbitrum One, Arbitrum Nova, Optimism,
Soneium, Polygon, BNB Smart Chain, Sahara AI, Avalanche C-Chain, Core DAO,
Kava, Fantom, Gravity Alpha, Zora, Abstract, Somnia, Linea, zkSync Era,
Monad, Manta Pacific, ApeChain, Polygon zkEVM.

**Testnet (6):** Sepolia, Pharos, Neura, Nexus, ARC, LiteForge.

**Не-EVM:** Solana, Eclipse.

Свою сеть можно добавить в `config/networks.py` — формат виден по соседним
записям. У каждой сети список RPC: при ошибке модули перебирают их по кругу.

---

## Структура проекта

```
ETHmachine/
├── main.py              ← точка входа, маршрутизация меню
├── config/              ← всё, что правит пользователь
├── modules/
│   ├── ui/              ← общий терминальный UI: меню, панели, ввод
│   ├── data_manager.py  ← единый доступ к data/data.csv
│   ├── proxy_manager.py ← разбор и ротация прокси
│   ├── simple_logger.py ← логи и прогресс-бары
│   ├── eth/  sol/  cex/  twitter/  …
│   └── backup/          ← локальные и SFTP бэкапы
├── web/                 ← веб-панель (aiohttp + jinja2)
├── tests/               ← pytest
├── docs/                ← документация по модулям
└── data/  db/  result/  log/  backups/     ← создаются при первом запуске
```

---

## Безопасность

- `data/`, `db/`, `result/`, `log/`, `backups/` и `config/cex_settings.py`
  исключены из git — приватные ключи не уедут в репозиторий случайным `git add`.
- Никогда не публикуйте `data/data.csv` и не выкладывайте бэкапы: в них
  приватные ключи, мнемоники и пароли.
- API-ключи бирж выдавайте с минимальными правами и белым списком IP.
- Веб-панель держите на `127.0.0.1`.
- Перед крупными операциями делайте бэкап через меню **Backup**.

---

## Разработка

```bash
pip install -r requirements-dev.txt
pytest
```

Тесты не ходят в сеть и не трогают пользовательские данные: проверяются
импорты всех модулей, целостность меню, соответствие конфигов тому, что
импортирует код, и вёрстка UI.

Конвенции для новых модулей — в [AGENTS.md](AGENTS.md): структура модуля,
работа с БД, статусы задач, логирование, возобновляемость.

---

## Документация

- [Полный индекс](docs/README.md)
- [Twitter: задания](docs/MODULE_TWITTER_TASKS.md)
- [Вывод с OKX](docs/MODULE_OKX_WITHDRAW.md) · [Binance](docs/MODULE_BINANCE_WITHDRAW.md) · [Bitget](docs/MODULE_BITGET_WITHDRAW.md) · [MEXC](docs/MODULE_MEXC_WITHDRAW.md)
- [Несколько аккаунтов на бирже](docs/MULTIPLE_EXCHANGE_ACCOUNTS.md)
- [Бэкапы](docs/MODULE_AUTO_BACKUP.md) · [Live-синхронизация](docs/LIVE_BACKUP_QUICKSTART.md)
- [Проверка прокси](docs/MODULE_CHECK_PROXY.md)

---

## Обновление

Из меню обновления при запуске — программа сама отложит ваши настройки,
подтянет новую версию и вернёт настройки на место.

Вручную:

```bash
git pull
pip install -r requirements.txt
```

Формат `data/data.csv`, пути баз в `db/` и имена настроек не меняются между
версиями: после обновления ничего перенастраивать не нужно.

---

## Поддержать автора

Если проект оказался полезен:

```
ERC-20: 0xa24fbbd57720ec580395aedba3ad37f6a6067727
```

<img src="assets/usdt.jpg" alt="Донат" width="220">

---

## Лицензия

См. [LICENSE.txt](LICENSE.txt).

**Автор:** [@DenisHumen](https://t.me/DenisHumen) · [GitHub](https://github.com/DenisHumen)
