# AGENTS.md — справочник по модулям ETHmachine

Документ для AI-агентов. Не туториал — конкретные конвенции, пути и сигнатуры,
которым обязан следовать любой новый модуль. Если что-то расходится с этим
документом — приоритет у текущего кода в `modules/eth/swap_all_*`.

---

## 1. Структура модуля

Каждый «свап-всё» / on-chain модуль живёт в `modules/eth/<module_name>/`
и состоит из 7 файлов:

| Файл | Назначение |
|---|---|
| `__init__.py` | Реэкспорт `run_<module_name>` из `menu.py` |
| `menu.py` | UX (questionary), оркестрация phase-1/phase-2, многопоточность |
| `planner.py` | Phase-1: загрузка балансов, классификация, запись задач в БД |
| `executor.py` | Phase-2: web3 sign+send, polling статуса моста, апдейт БД |
| `database.py` | SQLite-схема и CRUD: `init_database`, `upsert_task`, `update_task`, `get_statistics`, `list_wallets_with_pending`, `reset_database`, `DB_PATH` |
| `excel_export.py` | 3-листовый отчёт `result/<module>/run_<ts>/<module>_report.xlsx` |
| `<bridge>.py` | Клиент моста (например `rhinofi.py`, `layerswap.py`) |

Пример canonical: `modules/eth/swap_all_zksync_era_to_base/`.

---

## 2. Источники данных

### 2.1 Кошельки
`modules/data_manager.load_data()` → `List[dict]` со столбцами из
`data/data.csv`. Поля, на которые опираются модули:

- `name` — отображаемое имя
- `private_key` — обязательно; если пусто — запись пропускается
- `proxy` — основной HTTP/SOCKS прокси
- `reserve_proxy` — fallback
- `wallet_address`, `mnemonic`, `sol_address` — опциональны

В `planner._build_records()` адрес EVM выводится из `private_key` через
`eth_account.Account.from_key(...)` (не доверять `wallet_address` из CSV).

### 2.2 Балансы (EVM)
`modules/eth/oklink_balance_checker.py`:
- `fetch_oklink_tokens(address, chain_key, proxies_dict)` → `{ok, tokens, total_usd, error}`
- `_make_proxy_dict(proxy_str)` — нормализует строку прокси в dict для `requests`
- chain-key — слаг OKLink (`zksync`, `base`, `polygonzkevm`, …).
  **Не** RPC-name. При 404 пробуй варианты слага.

Кеш балансов: `db/eth_balance_tasks.db`, таблица `eth_balance_tasks`,
`task_type='oklink_tokens'`. Используется как fallback, если OKLink упал.

### 2.3 Сети / RPC
`config/networks.py` — словарь `NETWORKS`. Каждая запись:
`{name, rpc_urls: [...], chain_id, oklink_chain, …}`. Используй
`rpc_urls` как пул для round-robin при ошибках; не хардкодь один URL.

---

## 3. Стандартные параметры (general_config.py)

`config/modules/general_config.py` — единый источник для всех модулей:

```python
NUM_THREADS = 25                  # параллелизм; min 5
SLEEP_BETWEEN_ACTIONS = [2, 4]    # random.uniform внутри
DELAY_BETWEEN_ACCOUNTS = [3, 5]
TX_SEND_ATTEMPTS = 1              # повторы send_raw_transaction
RETRY_COUNT = 2                   # внешние вызовы (proxy/rpc fallback)
WHAITE_TRANSACTION_PENDING = 10   # секунд между check_receipt
WHAITE_TRANSACTION_PENDING_COUNT = 30
MAIN_PROXY = ''                   # на не-кошелёчные запросы
SHUFLE_ACCOUNTS = True/False # перемешивать ли кошельки при запуске
```

Любой module-specific knob — в `config/modules/cfg_<module_name>.py`,
импорт через `from config.modules.cfg_<module> import ...`.
Не плодить локальные константы там, где уже есть глобальная в `general_config`.

---

## 4. Многопоточность

Шаблон (см. `swap_all_zksync_era_to_base/menu.py`):

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from config.modules.general_config import NUM_THREADS as _CFG_NUM_THREADS

PLAN_NUM_THREADS = max(1, int(_CFG_NUM_THREADS))
SWAP_NUM_THREADS = max(1, int(_CFG_NUM_THREADS))

lock = threading.Lock()
threads = max(1, min(num_threads, total)) if total else 1
with ThreadPoolExecutor(max_workers=threads, thread_name_prefix="plan") as ex:
    futs = [ex.submit(_one, i, rec) for i, rec in enumerate(records, 1)]
    try:
        for fut in as_completed(futs):
            fut.result()        # пробрасываем KeyboardInterrupt
    except KeyboardInterrupt:
        for f in futs:
            f.cancel()
        raise
```

Правила:
- Индекс `[i/total]` = позиция в `data.csv`, **не** порядок завершения.
- Все мутации счётчиков и логи — под `lock`.
- SQLite-апсерты thread-safe только при WAL и отдельном connection на вызов
  (см. `database.py` существующих модулей).
- При `threads <= 1 or total <= 1` — последовательный путь без пула.

---

## 5. База данных

### 5.1 Путь и режим
- `db/<module_name>.db`, экспортируется как `database.DB_PATH`.
- WAL mode (`PRAGMA journal_mode=WAL`).
- Каждая операция открывает свой connection (`sqlite3.connect(str(DB_PATH))`),
  закрывает после use. Не шарь connection между потоками.

### 5.2 Канонический lifecycle статусов
```
pending → swap_created → tx_sent → awaiting_arrival → arrived
                                                    ↘ failed
                                                    ↘ skipped
```
`pending` = задача создана planner-ом.
`skipped` = `supported=False` (нет route, native-for-gas, risk).
`arrived` / `failed` — терминальные.

### 5.3 Обязательные методы `database.py`
```python
init_database()                         # idempotent CREATE TABLE IF NOT EXISTS
upsert_task(wallet_address, account_name, private_key, proxy, reserve_proxy,
            token, contract, decimals, raw_balance, human_balance,
            usd_value, supported, extra)        # PK = (wallet, contract)
update_task(wallet, contract, **fields)         # частичный апдейт
get_statistics() -> dict                        # {status: count, ..., 'total': N}
list_wallets_with_pending() -> list[str]        # адреса в lower-case
reset_database()                                # DROP+CREATE
DB_PATH                                         # pathlib.Path
```

`extra` — JSON-сериализуемый dict, хранится как TEXT.

---

## 6. Хранение результатов

```
result/<module_name>/run_<YYYYMMDD_HHMMSS>/<module_name>_report.xlsx
```

3 листа:
1. **Matrix** — wallet × token, значения = human_balance / received.
2. **Tasks** — плоский dump всех задач (все колонки БД).
3. **Summary** — агрегаты: counts по status, totals USD, time bounds.

`excel_export.export_report() -> Path` — единая точка входа.
Используй `openpyxl`; не пиши csv-fallback (его нет в репо).

---

## 7. Логирование

`modules/simple_logger.py`:

```python
logger                                          # loguru.logger, .info/.warning/.error/.success/.exception
log_simple(message, level)                      # plain line, без [i/N]
log_wallet_task(wallet, idx, total, message,    # [i/N] wallet … message
                level, account_name="")          # level: info|success|warning|error
set_auto_progress(False)                         # отключает tqdm-bar если [i/N] уже в строке
```

Правило: если в логах уже есть `[i/total]` — `set_auto_progress(False)` в начале
`menu.py`. Иначе будет двойная индикация.

---

## 8. Меню и регистрация модуля

### 8.1 menu.py — пример меню
```
🤖 Авто-режим (pipeline + резюм + Excel)   → _handle_auto
📋 Планирование (баланс + классификация)   → _handle_plan
▶️  Запуск свапа                            → _handle_run
📊 Статистика БД                           → _show_stats
📑 Экспорт Excel-отчёта                    → _handle_export
🗑️  Очистить БД                            → _handle_reset
📖 Информация                              → _print_info
🔙 Назад                                    → return
```

`run_<module_name>()` — public entry, реэкспортируется из `__init__.py`.

### 8.2 Регистрация в главном меню
- `config/menu_config.py` → `MenuItem(key, label, description, icon)` внутри
  соответствующего `*_SUBMENU` (для bridges/swaps — `TOOLS_SUBMENU`).
- `main.py` → `case '<key>':` импорт + вызов `run_<module>()`.

Ключ `MenuItem.key` обязан совпадать с case-строкой в `main.py`.

---

## 9. EVM-исполнение

### 9.1 Подпись
```python
signed = w3.eth.account.sign_transaction(tx, private_key)
raw = getattr(signed, "rawTransaction", None) or signed.raw_transaction
tx_hash = w3.eth.send_raw_transaction(raw)
```
Поддерживаем оба именования (web3 ≤6 / ≥7).

### 9.2 Тип tx
По умолчанию legacy gas (`gasPrice`), не EIP-1559 — у zkSync/zkEVM/Base разные
требования. Возьми из существующего `executor.py` (`_build_legacy_tx`).

### 9.3 RPC fallback
Перебирай `NETWORKS[chain]['rpc_urls']`. На исключениях `requests`/`web3` —
переключи URL и повтори до `RETRY_COUNT` раз.

### 9.4 Polling моста
- Интервал — module-specific knob (`<BRIDGE>_POLL_INTERVAL`, default 15s).
- Таймаут — `WHAITE_TRANSACTION_PENDING * WHAITE_TRANSACTION_PENDING_COUNT`.
- Терминальные множества хранить в bridge-клиенте (`TERMINAL_OK`, `TERMINAL_FAIL`).
  При неизвестном статусе — продолжать polling, не падать.

---

## 10. Чеклист нового модуля

1. Скопировать соседний модуль той же категории.
2. Заменить chain-keys, контракты, RPC, путь БД, путь result/.
3. Реализовать bridge-клиент (если нужен новый): `is_supported`, `quote`/`limits`,
   `create_swap`, `get_swap`, `<Error>`.
4. `set_auto_progress(False)` если есть `[i/N]` в логах.
5. Проверить, что `database.DB_PATH` уникален и не пересекается.
6. Зарегистрировать в `config/menu_config.py` и `main.py`.
7. Smoke на 1 кошельке с реальным балансом до полного прогона.
8. Контрольный live-тест: проверить, что `dst_balance_after > dst_balance_before`
   на целевой сети, а не только статус моста.

---

## 11. Что НЕ делать

- Не хардкодить `NUM_THREADS` локально — читать из `general_config`.
- Не использовать одну SQLite-connection в нескольких потоках.
- Не доверять `wallet_address` из CSV — выводи из `private_key`.
- Не молча ловить `Exception` без логирования и без апдейта статуса задачи.
- Не писать новый `*.md` рядом с модулем — документация только здесь и в CLAUDE.md.
- Не шарить `requests.Session` между потоками без необходимости (у Rhino-клиента
  оправдано из-за JWT-кеша; в общем случае — отдельная сессия на тред).
- **Не переписывать функционал из §12** — если задача покрыта существующим
  shared-модулем, обязательно импортировать его. Парсинг CSV, прокси,
  логи, капча, генерация/конвертация ключей,
  отправка ERC-20, чтение балансов через OKLink — всё уже есть.

---

## 12. Обязательные общие модули (reuse, don't rewrite)

Перед тем как писать любую вспомогательную логику — проверь, нет ли её здесь.
Дублирование запрещено: используй импорт.

### 12.1 Данные и инфраструктура

| Модуль | Импорт | Public API | Когда обязателен |
|---|---|---|---|
| **data_manager** | `from modules.data_manager import load_data, get_private_keys, get_proxies, get_wallet_addresses, get_transfer_rows, select_data_file` | возвращают унифицированные структуры из `data/data.csv` | Любой доступ к кошелькам/прокси/мнемоникам. Не читать CSV напрямую. |
| **proxy_manager** | `from modules.proxy_manager import ProxyManager, parse_proxy, get_proxy_dict, get_random_proxy` | `ProxyManager().load_proxies()`, `.get_random()`; `parse_proxy(str)` нормализует все форматы (`http://`, `socks5://`, `user:pass@host:port`) | Любая работа с прокси. Не писать свой парсер. |
| **simple_logger** | `from modules.simple_logger import logger, log_simple, log_wallet_task, log_task, set_auto_progress` | loguru + tqdm-прогресс + `[i/N] wallet … msg` | Все логи. `print()` запрещён в production-путях. |
| **config_validator** | `from modules.config_validator import ConfigValidator` | `ConfigValidator().validate_all()` — схема CSV, CEX, конфиг | Перед запуском долгих операций. |
| **requirements_checker** | `from modules.requirements_checker import check_requirements` | авто-установка зависимостей (на Linux + build-essential) | Запуск/обновление окружения. |

### 12.2 Прокси / капча / бэкап / статистика

| Модуль | Импорт | Когда обязателен |
|---|---|---|

| **captcha.manager** | `from modules.captcha.manager import CaptchaManager` | `solve_hcaptcha / solve_turnstile / solve_recaptcha_v2 / solve_recaptcha_v3`. Поддерживает 2captcha/anticaptcha/capsolver/yescaptcha/capmonster через `general_config.CAPTCHA_SERVICE`. Не вызывать сервисы напрямую. |

### 12.3 EVM-утилиты (`modules/eth/*`)

| Модуль | Назначение | Использовать вместо |
|---|---|---|
| `oklink_balance_checker.fetch_oklink_tokens` | Баланс всех токенов на сети через OKLink web-API | Своих парсеров скан-эксплореров. |
| `oklink_balance_checker._make_proxy_dict` | Прокси-dict для `requests` | Дублирующего кода. |
| `eth_get_balaces.load_wallets` | Native-balance check по списку кошельков | Цикла с web3 + RPC fallback вручную. |
| `eth_get_token_balance` | ERC-20 `balanceOf` с RPC-fallback | Прямых eth_call. |
| `eth_private_key_to_wallet_address.process_private_keys` | Bulk PK→address | `Account.from_key` в цикле без логов. |
| `eth_mnemonic_to_privkey.process_mnemonics` | Mnemonic→PK (BIP39/44) | Свой derive. |
| `eth_wallet_generator` | Генерация новых EVM-кошельков (BIP39) | Ad-hoc генератора. |
| `transfer_erc20_tokens` | Отправка ERC-20 (с поддержкой промежуточного кошелька / collector) | Своей реализации `transfer`. Use this for drainer/collector flows. |
| `rpc_return_module` | Подбор живого RPC из `config/networks.NETWORKS` | Хардкода URL. |
| `eth.database` | Общая БД `db/eth_balance_tasks.db` для кеша балансов | Не путать с per-module БД (§5) — это шаренный кеш для OKLink. |

### 12.4 Правило выбора

> Если задача — «проверить балансы / отправить токены / сгенерить кошельки /
> распарсить CSV или прокси / посчитать капчу / залогать / уведомить» —
> **ищи в таблицах выше**. Свою реализацию писать только если найденная
> функция объективно не подходит, и в коммите указать причину (можно сделать копию и переписать под новый модуль если в этом есть смысл).

---

## 13. Логирование и UI-стиль

Подробности уже частично описаны в §7. Здесь — общие принципы, которые
обязаны соблюдаться во всех модулях, чтобы UX был консистентным.

### 13.1 Какой вызов выбрать

| Вызов | Когда |
|---|---|
| `log_wallet_task(wallet, idx, total, msg, status, account_name=name)` | Любая операция, привязанная к конкретному кошельку. Формат `[i/N] wallet │ msg`. |
| `log_simple(msg, status)` | Заголовки фаз, агрегированные счётчики, сообщения вне цикла кошельков. |
| `logger.exception(msg)` | Только для непредвиденных исключений (Excel-export, конфиг). Не для ошибок задач — они идут через `log_wallet_task(..., "error")` + апдейт `error_message` в БД. |
| `logger.success / .info / .warning / .error` | Финальные итоги меню (`готово: …`, `прервано пользователем`). |
| `print()` | **Запрещён** в production-путях. Допустим только: (а) меню/баннеры с colorama, (б) разделители `'=' * 60` в `_show_stats()`. |

### 13.2 Уровни статуса
`info` (старт/прогресс) · `success` (терминальный успех) · `warning` (skip, no-route, retry) · `error` (failed) · `debug` (только при отладке, не в main).

### 13.3 Эмодзи-префиксы (канон)
```
📋 plan / planning             📊 stats / counters
💱 swap / bridge / swapping…   📑 export / report
✅ done / completed             ⏭  skip / no route
⚠ warning / partial            ❌ failed / unrecoverable
🔓 approve tx                   📤 deposit / send tx
🔁 resume / pending recovered   🤖 auto-mode / pipeline
🗑️ reset / clear DB             🔙 back
```
Использовать те же символы — пользователь распознаёт их за такт.

### 13.4 Прогресс-бар
- В phase-2 (executor) есть `[i/N]` в каждой строке → `set_auto_progress(False)`.
- В долгих фазах без `[i/N]` — `set_auto_progress(True)` (по умолчанию).
- Двойной индикации (tqdm + `[i/N]`) быть не должно.

### 13.5 Меню (questionary)
```python
select(
    "💱 <Заголовок модуля>:",
    choices=[Choice("🤖 Авто-режим …", "auto"), …, Choice("🔙 Назад", "back")],
    qmark="💱", pointer="👉",
).ask()
```
После каждого действия: `input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")`.

### 13.6 Статистика
Только в `_show_stats()` допустимо рисовать рамки colorama: cyan-разделитель
`'=' * 60`, ключ-выровнен `f"  {k:<22} {v}"`, total отделён `'-' * 40`.
Любые «красивые таблицы» в других местах — через `log_simple`.

---

## 14. Pipeline и резюмируемость задач

Стандартный поток для любого «свап-всё / drain / collector»-модуля — три
фазы с общей SQLite как единственным источником правды.

### 14.1 Три фазы

```
Phase 1  planner._build_records() → plan_one_wallet()
         ─ снимает баланс OKLink
         ─ классифицирует (supported / no_route / native_kept_for_gas / risk)
         ─ upsert_task(...) на КАЖДЫЙ токен (включая skipped)
         ─ результат: БД полностью отражает scope работы

Phase 2  executor.run_wallet(wallet)
         ─ читает только pending-задачи кошелька
         ─ approve → bridge create → on-chain send → poll status
         ─ update_task(status, src_tx, dst_tx, received_amount, error)
         ─ idempotent: повторный запуск не дублирует работу

Phase 3  excel_export.export_report()
         ─ читает БД ЦЕЛИКОМ (не только текущий run)
         ─ строит Matrix / Tasks / Summary
         ─ Excel — производная от БД, не отдельный лог запуска
```

### 14.2 Lifecycle статусов
```
pending ──► swap_created ──► tx_sent ──► awaiting_arrival ──► arrived ✅
                                                          └► failed   ❌
skipped (создаётся сразу planner-ом для unsupported токенов) — terminal
```
Терминальные: `arrived`, `failed`, `skipped`. Pending-набор для phase-2 =
«всё, что не терминально».

### 14.3 Резюмируемость — обязательно

Любой запуск phase-2 должен переживать `KeyboardInterrupt`, RPC-фейлы,
рестарт скрипта **без потери прогресса**.

Правила:
1. **Создавай задачи до начала работы.** Phase-1 — отдельный шаг. Никаких
   «по ходу выполнения добавлю задачу».
2. **Обновляй статус сразу после каждого I/O-шага** (`tx_sent` после
   `send_raw_transaction`, `awaiting_arrival` после успешного receipt и т.д.).
   Не копи 5 шагов в памяти, чтобы записать одним апдейтом.
3. **Идемпотентность.** Перед `swap_created` проверь — нет ли уже `swap_id`
   у задачи (значит, мост уже выдал quote — продолжаем с polling).
4. **Возобновление сценариев** — поддерживается `list_wallets_with_pending()`
   (см. §5.3). Меню «▶️ Запуск свапа» использует именно её.
5. **Прерывание.** В `menu.py` ловим `KeyboardInterrupt` на обоих фазах,
   логируем «состояние в БД сохранено» и выходим. Excel — экспортируем
   даже при прерывании, если фаза-2 успела что-то сделать.

### 14.4 Хранение результатов в БД

В таблице задач (PK = `(wallet, contract)`) обязаны быть колонки:

| Колонка | Содержание |
|---|---|
| `status` | см. lifecycle |
| `swap_id` / `quote_id` | ID операции у моста |
| `src_tx_hash` | tx на исходной сети |
| `dst_tx_hash` | tx на целевой сети |
| `sent_amount_raw`, `sent_amount_human` | сколько отправлено |
| `received_amount` | сколько пришло (из API моста) |
| `dst_balance_after` | факт. баланс на целевой сети после ✅ |
| `error_message` | текст ошибки, обрезанный (~500 chars) |
| `attempts` | счётчик попыток (для ретраев) |
| `created_at`, `updated_at` | метки времени |

Не храни результаты в файлах рядом (`logs/<run>.json`, отдельные CSV) —
БД единственный источник. Excel — функция от БД.

### 14.5 Запрещённые практики

- Считать состояние «по логам» вместо БД.
- Удалять или пересоздавать БД при каждом запуске (для этого есть
  явный пункт меню «🗑️ Очистить БД»).
- Записывать результаты только в memory и сбрасывать в БД в конце —
  при interrupt всё пропадёт.
- Зависимость excel-отчёта от структур времени запуска (run-folder) —
  допускается только в имени файла; данные берутся из БД.
