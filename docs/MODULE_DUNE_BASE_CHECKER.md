# MODULE: Dune Base Network Analytics Checker

Чекер кошельков по дашборду
[Base Network Analytics](https://dune.com/nvthao/base-network-analytics-dashboard)
с использованием официального Dune Analytics API.

## Что делает

Для каждого кошелька из выбранного `data/data*.csv` выполняет два запроса
к Dune (один за другим, через прокси этого же кошелька):

| Источник                                       | Что берётся                          |
|------------------------------------------------|--------------------------------------|
| **Top 2,500,000 Wallet Ranking**               | rank, native_volume, contract_count, gasfee_eth и т.д. |
| **Top 2,500,000 Wallets Ranking by Volume**    | volume‑центричные метрики            |

Если кошелёк не попал в Top 2.5M — он помечается как "NOT FOUND".

Запрос к Dune API формируется так:

```
GET https://api.dune.com/api/v1/query/{query_id}/results
    ?filters=<address_column> = '0x...'
    &limit=1
Header: X-Dune-API-Key: <DUNE_API_KEY>
```

Имя колонки адреса (`wallet`, `wallet_address`, `address` и т.п.) определяется
автоматически из метаданных Dune-запроса при первом обращении и кэшируется на
всё время сессии.

## Где в меню

```
ETHmachine → 🎮 PROJECTS → 🟦 Dune → 🟦 Base
```

В подменю **Base** доступны:

- ▶️  **Запуск чекера** — создаёт/догоняет задачи в БД и обрабатывает все
  pending/failed.
- 📊 **Статистика** — текущее состояние БД (всего / completed / pending /
  failed / found).
- 📥 **Экспорт в Excel** — выгружает текущее содержимое БД в
  `result/dune/dune_base_<timestamp>.xlsx` без обращения к API.
- 🗑️  **Очистка БД** — удаляет все задачи (с подтверждением).
- 📖 **Информация** — краткая справка прямо в TUI.

## Источник данных

- Файл: выбранный при старте `data/data*.csv` (через
  [`modules/data_manager.py`](../modules/data_manager.py)).
- Поле адреса:
  1. `private_key` → конвертируется в EVM-адрес через `eth_account.Account.from_key`;
  2. если `private_key` пуст — берётся `wallet_address`.
- **Прокси:** для каждого кошелька берётся **его собственный `proxy`** из той же
  строки CSV (через [`modules/proxy_manager.py`](../modules/proxy_manager.py)).
  Это снижает шанс рейт-лимита, когда кошельков много.
- Дубликаты адресов внутри CSV отбрасываются.

## Конфигурация

Все параметры берутся из
[`config/modules/general_config.py`](../config/modules/general_config.py):

| Параметр                   | Назначение                                            |
|----------------------------|-------------------------------------------------------|
| `NUM_THREADS`              | Количество одновременных потоков (≥1).               |
| `SLEEP_BETWEEN_ACTIONS`    | `[min, max]` сек. между двумя запросами по 1 кошельку и при ретраях. |
| `DELAY_BETWEEN_ACCOUNTS`   | `[min, max]` сек. между стартом потоков (jitter старта). |
| `RETRY_COUNT`              | Количество попыток при сетевых/5xx ошибках.          |
| `DUNE_API_KEY`             | API-ключ Dune Analytics. **Обязателен.**             |
| `DUNE_BASE_RANKING_QUERY_ID` | ID запроса с таблицей рангов (по умолчанию `5791511`). |
| `DUNE_BASE_VOLUME_QUERY_ID`  | ID запроса с таблицей по объёмам (по умолчанию `5805568`). |

API-ключ Dune (бесплатно): <https://dune.com/settings/api>

## Хранение состояния

SQLite-БД: **`db/dune_base_checker.db`**, таблица `check_tasks`.

| Колонка             | Назначение                                          |
|---------------------|-----------------------------------------------------|
| `wallet_address`    | EVM-адрес (UNIQUE).                                 |
| `account_name`      | Имя из CSV (поле `name`).                           |
| `status`            | `pending` / `completed` / `failed`.                 |
| `found_in_ranking`  | 1, если кошелёк есть в Top Ranking.                 |
| `found_in_volume`   | 1, если кошелёк есть в Top by Volume.               |
| `ranking_data`      | JSON со всей строкой Ranking-запроса.               |
| `volume_data`       | JSON со всей строкой Volume-запроса.                |
| `error_message`     | Последняя ошибка (для failed).                      |
| `attempts`          | Сколько раз обрабатывалась задача.                  |
| `created_at` / `updated_at` / `completed_at` | таймстампы.                |

Это позволяет:

- **Прервать** работу (Ctrl+C) и **продолжить** с того же места: повторный
  запуск обработает только `pending` и `failed`.
- **Повторно выгрузить** Excel в любой момент без обращения к API.
- **Очистить** БД и начать заново через пункт меню.

Если все задачи в БД уже `completed`, при следующем "Запуске чекера" БД
автоматически очищается.

## Результаты (Excel)

Выгрузка: **`result/dune/dune_base_<timestamp>.xlsx`** (создаётся
автоматически после прогона и при ручном экспорте из меню).

Колонки:

```
#  Account  Address  Status  Found Ranking  Found Volume  Attempts  Error  Completed At
+ R:<все колонки запроса Ranking>
+ V:<все колонки запроса Volume>
```

Подсветка строк:

- 🟩 зелёная — найден в Top 2.5M.
- 🟨 жёлтая — успешно проверен, но не найден.
- 🟥 красная — `failed`, см. колонку `Error`.
- ⬜ серая — `pending`.

## Логирование

Используется [`modules/simple_logger.py`](../modules/simple_logger.py) с
полями `account_name`, `task_index`, `task_total`, `wallet`. Пример:

```
12:34:01 │ acc_07 │ ██   OK  ██ │ [7/120] │ 0xabc... │ ✅ FOUND │ rank=412 │ native_volume=1.832 │ proxy: 154.6.88.63:40120
```

## Зависимости

Уже присутствуют в `requirements.txt`:

- `requests`, `urllib3`
- `web3` / `eth-account`
- `openpyxl`
- `colorama`, `questionary`, `loguru`

Дополнительно ничего ставить не нужно.

## Файлы модуля

```
modules/dune/
├── __init__.py
├── menu.py                  # внешнее меню Dune (выбор проекта)
└── base/
    ├── __init__.py
    ├── menu.py              # подменю Base (start / stats / export / clear / info)
    ├── checker.py           # API + многопоточная обработка
    └── database.py          # SQLite (db/dune_base_checker.db)
```

## Быстрый чек-лист

1. В `config/modules/general_config.py` задать `DUNE_API_KEY`.
2. Подготовить `data/data.csv` — заполнить `private_key` и `proxy`
   (по 1 строке на кошелёк).
3. `python main.py` → `🎮 PROJECTS` → `🟦 Dune` → `🟦 Base`
   → `▶️ Запуск чекера`.
4. Excel результат — в `result/dune/`.
