# AGENTS.md — справочник по модулям ETHmachine

Документ для AI-агентов. Не туториал — конкретные конвенции, пути и сигнатуры,
которым обязан следовать любой новый модуль. Если что-то расходится с этим
документом — приоритет у текущего кода в `modules/eth/swap_all_*`.

Общее описание проекта для пользователя — в [README.md](README.md).

---

## 1. Структура модуля

Каждый «свап-всё» / on-chain модуль живёт в `modules/eth/<module_name>/`
и состоит из 7 файлов:

| Файл | Назначение |
|---|---|
| `__init__.py` | Реэкспорт `run_<module_name>` из `menu.py` |
| `menu.py` | UX, оркестрация phase-1/phase-2, многопоточность |
| `planner.py` | Phase-1: загрузка балансов, классификация, запись задач в БД |
| `executor.py` | Phase-2: web3 sign+send, polling статуса моста, апдейт БД |
| `database.py` | SQLite-схема и CRUD: `init_database`, `upsert_task`, `update_task`, `get_statistics`, `list_wallets_with_pending`, `reset_database`, `DB_PATH` |
| `excel_export.py` | 3-листовый отчёт `result/<module>/run_<ts>/swap_all_report.xlsx` |
| `<bridge>.py` | Клиент моста (`rhinofi.py`, `layerswap.py`) |

Пример canonical: `modules/eth/swap_all_zksync_era_to_base/`.
Второй экземпляр той же схемы — `modules/eth/swap_all_polygon_zkevm_to_base/`;
сравнивать полезно оба, различия между ними отмечены ниже по тексту.

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

Полный список колонок — в `data_manager.HEADERS` и в таблице README.

В `planner._build_records()` адрес EVM выводится из `private_key` через
`eth_account.Account.from_key(...)` (не доверять `wallet_address` из CSV).
Там же отсеиваются дубликаты по адресу.

### 2.2 Балансы (EVM)
`modules/eth/oklink_balance_checker.py`:

```python
fetch_oklink_tokens(wallet, oklink_chain, proxy_dict=None, max_retries=None)
# → {ok: bool, tokens: [...], total_usd: float, error: str|None}
_make_proxy_dict(proxy_str)  # строка прокси → dict для requests
```

`max_retries=None` означает «взять `RETRY_COUNT` из `general_config`».
`oklink_chain` — слаг OKLink (`zksync`, `base`, `polygon_zkevm`, …), **не**
имя сети из `NETWORKS`. При 404 пробуй варианты слага.

Кеш балансов: `db/eth_balance_tasks.db`, таблица `eth_balance_tasks`,
`task_type='oklink_tokens'`, JSON списка токенов лежит в колонке `balance`
у строк со `status='completed'`. Planner читает его как fallback, если
OKLink недоступен (`planner._load_cached_tokens`).

### 2.3 Сети / RPC
`config/networks.py` — словарь `NETWORKS`. **Ключ — отображаемое имя вместе
с эмодзи** (`'🚀 Base'`, `'🧪 Sepolia'`), отдельного поля `name` нет.
Значение:

| Поле | Есть везде | Содержимое |
|---|---|---|
| `rpc_urls` | да | список RPC — пул для перебора при ошибках |
| `symbol` | да | тикер нативного токена |
| `tx_url` | да | префикс ссылки на транзакцию в эксплорере |
| `type` | да | `mainnet` / `testnet` |
| `chain_id` | нет | только там, где нужен модулям |
| `oklink_chain` | нет | только у Polygon zkEVM |

Не хардкодь один URL — перебирай `rpc_urls`. Готовые хелперы там же:
`get_all_networks()`, `get_mainnet_networks()`, `get_testnet_networks()`,
`get_network_rpc_urls(name)`, `get_network_symbol(name)`,
`get_explorer_url(name)`, `get_network_info(name)`, `get_network_type(name)`,
`get_network_display_name(name)`.

---

## 3. Стандартные параметры (general_config.py)

`config/modules/general_config.py` — единый источник для всех модулей.
Значения ниже — дефолты из репозитория; пользователь их правит, поэтому
читай константу, а не подставляй число.

| Константа | Дефолт | Что задаёт |
|---|---|---|
| `NUM_THREADS` | `5` | параллелизм; при значении >100 нужен более широкий пул RPC |
| `SLEEP_BETWEEN_ACTIONS` | `[2, 4]` | пауза между действиями, сек (`random.uniform`) |
| `DELAY_BETWEEN_ACCOUNTS` | `[3, 5]` | пауза между стартом аккаунтов, сек |
| `TX_SEND_ATTEMPTS` | `1` | повторы `send_raw_transaction` |
| `RETRY_COUNT` | `15` | повторы внешних вызовов со сменой прокси/RPC |
| `SHUFLE_ACCOUNTS` | `True` | перемешивать ли кошельки при запуске |
| `CAPTCHA_SERVICE` | `'yescaptcha'` | `2captcha` / `anticaptcha` / `capsolver` / `yescaptcha` / `capmonster` |
| `TWOCAPTCHA_API_KEY` … `CAPMONSTER_API_KEY` | `''` | по ключу на каждый сервис капчи |
| `WHAITE_TRANSACTION_PENDING` | `10` | секунд между проверками receipt |
| `WHAITE_TRANSACTION_PENDING_COUNT` | `30` | число проверок receipt |
| `MAIN_PROXY` | `''` | прокси для запросов, не привязанных к кошельку |
| `EVM_MAIN_WALLET` | `''` | главный EVM-кошелёк (коллекторы, дренеры) |
| `SOL_MAIN_WALLET` | `''` | главный Solana-кошелёк |
| `WEB_ENABLED` | `False` | поднимать ли веб-панель при старте `main.py` |

Любой module-specific knob — в `config/modules/cfg_<module_name>.py`,
импорт через `from config.modules.cfg_<module> import ...`.
Не плодить локальные константы там, где уже есть глобальная в `general_config`.

Новая константа в `general_config` должна быть реально прочитана кодом:
`tests/test_config_surface.py` статически сверяет, что всё импортируемое из
`config/` там существует.

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
  (см. `database._connect()` существующих модулей).
- При `threads <= 1 or total <= 1` — последовательный путь без пула.

---

## 5. База данных

### 5.1 Путь и режим
- `db/<module_name>.db`, экспортируется как `database.DB_PATH`.
- WAL mode (`PRAGMA journal_mode=WAL`), `sqlite3.connect(..., timeout=30)`,
  `row_factory = sqlite3.Row`.
- Каждая операция открывает свой connection и закрывает после use.
  Не шарь connection между потоками.

### 5.2 Канонический lifecycle статусов
```
pending → swap_created → tx_sent → awaiting_arrival → arrived
   ↘ failed
skipped
```
`pending` = задача создана planner-ом для поддержанного токена.
`skipped` = `supported=False` (нет route, native-for-gas, risk-флаг) —
проставляется сразу в `upsert_task`, терминальный.
`arrived` — терминальный успех.

`failed` **терминален не везде** — это решение модуля, и оно кодируется
кортежем `TERMINAL` в его `database.py`:

| Модуль | `TERMINAL` | Что это значит |
|---|---|---|
| `swap_all_zksync_era_to_base` | `(skipped, arrived)` | `failed` попадает в `list_pending_for_wallet` и повторяется на следующем запуске |
| `swap_all_polygon_zkevm_to_base` | `(skipped, arrived, failed)` | `failed` больше не берётся в работу |

Выбирай осознанно: авто-ретрай уместен для транзиентных ошибок моста,
но бесконечно повторять невозможный маршрут не нужно. Набор для phase-2
должен считаться одним и тем же условием и в `list_pending_for_wallet`,
и в `list_wallets_with_pending` — иначе меню покажет кошельки, для которых
исполнитель не найдёт ни одной задачи.

### 5.3 Обязательные методы `database.py`
```python
init_database() -> None                 # idempotent CREATE TABLE IF NOT EXISTS
reset_database() -> None                # DROP + CREATE

upsert_task(*, wallet_address, account_name, private_key, proxy,
            reserve_proxy, token, contract, decimals, raw_balance,
            human_balance, usd_value, supported, extra=None) -> int
# только keyword-аргументы; возвращает id задачи

update_task(task_id: int, **fields) -> None    # частичный апдейт по id
increment_attempts(task_id: int) -> None

list_pending_for_wallet(wallet_address) -> list[dict]
list_wallets_with_pending() -> list[str]       # адреса в lower-case
list_all_tasks() -> list[dict]
get_statistics() -> dict                       # {status: count, ..., 'total': N}

DB_PATH                                        # pathlib.Path
```

Схема: `id INTEGER PRIMARY KEY AUTOINCREMENT` + `UNIQUE(wallet_address,
token, contract)`. Апсерт ищет строку по этой тройке; `wallet_address` и
`contract` пишутся в lower-case, `token` — в upper-case. Повторный
`upsert_task` сбрасывает статус в `pending`/`skipped` только если текущий
статус — `pending`, `skipped` или `failed`; начатую работу он не откатывает.

`extra` — JSON-сериализуемый dict, хранится в колонке `extra_json` как TEXT.

---

## 6. Хранение результатов

```
result/<module_name>/run_<YYYYMMDD_HHMMSS>/swap_all_report.xlsx
```

Каталог модуля — `excel_export.RESULT_DIR`, подкаталог запуска и имя файла
собирает `export_report(out_dir=None) -> Path`.

3 листа:
1. **Matrix** — wallet × token, значения = human_balance / received.
2. **Tasks** — плоский dump всех задач (все колонки БД).
3. **Summary** — агрегаты: counts по status, totals USD, time bounds.

`excel_export.export_report()` — единая точка входа.
Используй `openpyxl`; не пиши csv-fallback (его нет в репо).

---

## 7. Логирование

`modules/simple_logger.py`:

```python
logger                    # loguru.logger: .info/.warning/.error/.success/.exception
log_simple(message, status="info", account_name=None)
log_wallet_task(wallet, index, total, message, status="info", account_name=None)
log_task(index, total, message, status="info", account_name=None)
set_auto_progress(enabled: bool)
set_progress_description(desc: str)
setup_file_logging(log_file: str) -> int
```

`status` принимает `info` | `success` | `warning` | `error` | `debug`;
неизвестное значение трактуется как `info`.

Формат строки:
`HH:MM:SS │ account_name │ ██ LABEL ██ │ [i/N] │ wallet │ message`.
`account_name` печатается, только если задан и не совпадает с адресом.

Правило: если в логах уже есть `[i/total]` — `set_auto_progress(False)` на
уровне модуля `menu.py`. Иначе будет двойная индикация (tqdm + `[i/N]`).

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
← Назад                                     → return
```

Отрисовка — через `modules/ui` (§15.1), не через прямые вызовы questionary.
Вне `modules/ui` прямых вызовов `questionary` не осталось, и это проверяет
`tests/test_ui_consistency.py` — новый модуль обязан брать меню из `ui`.

`run_<module_name>()` — public entry, реэкспортируется из `__init__.py`.

### 8.2 Регистрация в главном меню
- `config/menu_config.py` → `MenuItem(key=..., label=..., icon=...,
  description=...)` внутри соответствующего `*_SUBMENU`
  (для bridges/swaps — `TOOLS_SUBMENU`).
- `main.py` → ветка `elif choice == "<key>":` в соответствующем
  `MenuHandlers.handle_*`: ленивый импорт модуля и вызов `run_<module>()`.
  Импорт обязан быть внутри функции — иначе старт `main.py` тянет весь проект.

Ключ `MenuItem.key` обязан совпадать со строкой в `main.py`. Эту связку
проверяют `tests/test_menu_config.py` и `tests/test_main_routes.py`:
второй достаёт ленивые импорты из AST и убеждается, что они резолвятся.

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
требования. Возьми из существующего `executor.py` (`_build_legacy_fees(w3)`).

### 9.3 RPC fallback
Перебирай `NETWORKS[chain]['rpc_urls']`. На исключениях `requests`/`web3` —
переключи URL и повтори до `RETRY_COUNT` раз.

### 9.4 Polling моста
- Интервал — module-specific knob (`RHINOFI_POLL_INTERVAL`,
  `LAYERSWAP_POLL_INTERVAL`; в обоих cfg сейчас `15` секунд).
- Таймаут ожидания прихода — тоже module-specific: `ARRIVAL_TIMEOUT_SEC`
  (`25 * 60`). `WHAITE_TRANSACTION_PENDING*` из `general_config` — про
  ожидание on-chain receipt, не про мост; у swap-модулей для receipt свой
  `TX_RECEIPT_TIMEOUT_SEC`.
- Терминальные множества хранить в bridge-клиенте: у Rhino.fi это
  `TERMINAL_OK` / `TERMINAL_FAIL` в `rhinofi.py`. При неизвестном статусе —
  продолжать polling, не падать.

---

## 10. Чеклист нового модуля

1. Скопировать соседний модуль той же категории.
2. Заменить chain-keys, контракты, RPC, путь БД, путь result/.
3. Реализовать bridge-клиент (если нужен новый): `is_supported`, `quote`
   (и `limits`, если API их отдаёт), `create_swap`, `get_swap`, `<Bridge>Error`.
4. `set_auto_progress(False)` если есть `[i/N]` в логах.
5. Проверить, что `database.DB_PATH` уникален и не пересекается.
6. Зарегистрировать в `config/menu_config.py` и `main.py`.
7. Прогнать `pytest` — новый модуль обязан импортироваться, а его пункт меню
   резолвиться (§15.3).
8. Smoke на 1 кошельке с реальным балансом до полного прогона.
9. Контрольный live-тест: проверить, что `dst_balance_after > dst_balance_before`
   на целевой сети, а не только статус моста.

---

## 11. Что НЕ делать

- Не хардкодить `NUM_THREADS` локально — читать из `general_config`.
- Не использовать одну SQLite-connection в нескольких потоках.
- Не доверять `wallet_address` из CSV — выводи из `private_key`.
- Не молча ловить `Exception` без логирования и без апдейта статуса задачи.
- Не писать новый `*.md` рядом с модулем. Документация живёт в двух местах:
  `docs/` — для пользователя (индекс — `docs/README.md`), этот файл — для
  агентов. Единственное исключение — проектные документы подсистемы,
  которые описывают не модуль, а отдельное приложение внутри репозитория:
  сейчас это `web/PLAN.md`. Новых исключений не заводить.
- Не собирать ANSI-рамки и меню руками — есть `modules/ui` (§15.1).
- Не создавать рабочие каталоги и файлы из модуля — это делает
  `modules/bootstrap.py` на старте (§15.2).
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
| **data_manager** | `from modules.data_manager import load_data, get_private_keys, get_proxies, get_wallet_addresses, get_transfer_rows, select_data_file` | возвращают унифицированные структуры из `data/data.csv`; полный список — в `__all__` | Любой доступ к кошелькам/прокси/мнемоникам. Не читать CSV напрямую. |
| **proxy_manager** | `from modules.proxy_manager import ProxyManager, parse_proxy, get_proxy_dict, get_random_proxy, mask_proxy` | `ProxyManager.load_proxies()`, `.get_all()`, `.get_random()`, `.count()` (classmethod-ы); `parse_proxy(str)` нормализует форматы (`http://`, `socks5://`, `user:pass@host:port`); `mask_proxy(str)` — для логов | Любая работа с прокси. Не писать свой парсер. |
| **simple_logger** | `from modules.simple_logger import logger, log_simple, log_wallet_task, log_task, set_auto_progress` | loguru + tqdm-прогресс + `[i/N] wallet … msg` (§7) | Все логи. `print()` запрещён в production-путях. |
| **config_validator** | `from modules.config_validator import ConfigValidator` | `ConfigValidator(project_root=None).validate_all()`, `.show_results()`; шорткат `validate_configuration()` | Перед запуском долгих операций. |
| **requirements_checker** | `from modules.requirements_checker import check_requirements` | `check_requirements() -> bool` — проверка и авто-установка зависимостей (на Debian-подобных ещё и build-essential) | Запуск/обновление окружения. |

### 12.2 Капча / бэкап / прокси-чекер / статистика

| Модуль | Импорт | Public API | Когда обязателен |
|---|---|---|---|
| **captcha** | `from modules.captcha import CaptchaManager, get_captcha_solver` | `CaptchaManager(proxy=None)`; свойства `.is_available`, `.solver`, `.session_stats`; методы `solve_hcaptcha(sitekey, pageurl, user_agent=None, is_invisible=False)`, `solve_turnstile(sitekey, pageurl, action=None, user_agent=None)`, `solve_recaptcha_v2(sitekey, pageurl, is_invisible=False)`, `solve_recaptcha_v3(sitekey, pageurl, page_action="", min_score=0.3)` — все возвращают `Optional[str]` | Любая капча. Сервис выбирается `general_config.CAPTCHA_SERVICE`, ключ берётся оттуда же; напрямую 2captcha/anticaptcha/capsolver/yescaptcha/capmonster не дёргать. |
| **backup** | `from modules.backup import BackupManager, create_backup, list_backups, backup_menu` | `BackupManager()`: `create_backup(upload_to_sftp=True)`, `create_local_backup()`, `restore_local_backup(name=None)`, `list_local_backups()`, `cleanup_old_local_backups()`, `create_live_backup(silent=False)`, `restore_live_backup()`, `start_live_monitoring()` / `stop_live_monitoring()`, `upload_to_sftp(...)`, `download_from_sftp(...)`, `test_sftp_connection()`. Рядом — `EncryptionManager(password)` (Fernet + PBKDF2) и `LiveSyncMonitor` | Любой бэкап/восстановление и шифрование архивов. Настройки — `config/modules/cfg_backup.py`. |
| **check_proxy** | `from modules.check_proxy.tester import run_proxy_test, get_geo`; `from modules.check_proxy.probe import staged_probe` | `run_proxy_test(proxy, level) -> dict` — сводка, готовая для записи в БД; `get_geo(proxy, timeout=10.0) -> dict` (ip/country/city/asn); `staged_probe(target_url, proxy, *, timeout=12.0, measure_download=False) -> StageTimings` — тайминги DNS/TCP/TLS/CONNECT/TTFB и место поломки | Проверка живости и геолокации прокси. Отдельного `geo`-модуля больше нет — гео живёт в `tester.get_geo`. |
| **статистика задач** | `from modules.ui import ui` + `database.get_statistics()` модуля | `get_statistics() -> {status: count, ..., 'total': N}` (§5.3), отрисовка — `ui.stats_panel(title, stats, total_key="total", footer=None)` | Пункт «Статистика БД» в меню модуля. Свои рамки и выравнивание не рисовать. Для кеша балансов есть `modules.eth.database.get_task_statistics(task_type=None, network=None)`. |

### 12.3 EVM-утилиты (`modules/eth/*`)

| Модуль | Назначение | Использовать вместо |
|---|---|---|
| `oklink_balance_checker.fetch_oklink_tokens` | Баланс всех токенов на сети через OKLink web-API | Своих парсеров скан-эксплореров. |
| `oklink_balance_checker._make_proxy_dict` | Прокси-dict для `requests` | Дублирующего кода. |
| `eth_get_balances` | Native-balance по списку кошельков: `load_wallets()`, `get_balance_rpc(...)`, `process_wallets(...)`, меню `check_wallet_balances_menu()` | Цикла с web3 + RPC fallback вручную. |
| `eth_get_token_balance` | ERC-20 `balanceOf` с перебором RPC: `get_token_balance_rpc(...)`, `resolve_token_decimals(...)`, `process_wallets_tokens(...)` | Прямых `eth_call`. |
| `eth_private_key_to_wallet_address.process_private_keys` | Bulk PK→address | `Account.from_key` в цикле без логов. |
| `eth_mnemonic_to_privkey.process_mnemonics` | Mnemonic→PK (BIP39/44) | Свой derive. |
| `eth_wallet_generator.eth_generate_wallets` | Генерация новых EVM-кошельков (BIP39) | Ad-hoc генератора. |
| `transfer_erc20_tokens.transfer_erc20_tokens` | Отправка ERC-20 и нативного токена: парсинг сумм и процентов, failover по RPC и прокси, запись задачи в БД | Своей реализации `transfer`. Это же — база для collector-потоков. |
| `eth_collectors.eth_collectors` | Сбор нативных балансов на главный кошелёк (`EVM_MAIN_WALLET`) | Своего сборщика. |
| `rpc_return_module.get_network_rpc_selection` | **Интерактивный** выбор сети через questionary. Возвращает `(rpc_urls, network_type, network_name)` для одиночной сети и `('ALL_NETWORKS', {имя: rpc_urls}, подпись)` для вариантов «все», либо `(None, None, None)` при отмене | Копипасты меню выбора сети. Живость RPC он **не** проверяет — перебор `NETWORKS[chain]['rpc_urls']` остаётся на вызывающем (§9.3). В фоновом потоке не вызывать: это блокирующий вопрос пользователю. |
| `eth.database` | Общая БД `db/eth_balance_tasks.db` (`DB_FILE`), таблица `eth_balance_tasks`: `create_balance_tasks`, `get_pending_tasks`, `update_task_status`, `get_task_statistics`, `get_all_results`, `reset_database_for_new_run` | Не путать с per-module БД (§5) — это шаренный кеш чекеров балансов. |

### 12.4 Правило выбора

> Если задача — «проверить балансы / отправить токены / сгенерить кошельки /
> распарсить CSV или прокси / посчитать капчу / залогать / нарисовать меню» —
> **ищи в таблицах выше и в §15**. Свою реализацию писать только если найденная
> функция объективно не подходит, и в коммите указать причину (можно сделать копию и переписать под новый модуль если в этом есть смысл).

---

## 13. Логирование и UI-стиль

Подробности уже частично описаны в §7. Здесь — общие принципы, которые
обязаны соблюдаться во всех модулях, чтобы UX был консистентным.

### 13.1 Какой вызов выбрать

| Вызов | Когда |
|---|---|
| `log_wallet_task(wallet, idx, total, msg, status, account_name=name)` | Любая операция, привязанная к конкретному кошельку. |
| `log_simple(msg, status)` | Заголовки фаз, агрегированные счётчики, сообщения вне цикла кошельков. |
| `logger.exception(msg)` | Только для непредвиденных исключений (Excel-export, конфиг). Не для ошибок задач — они идут через `log_wallet_task(..., "error")` + апдейт `error_message` в БД. |
| `logger.success / .info / .warning / .error` | Финальные итоги меню (`готово: …`, `прервано пользователем`). |
| `print()` | **Запрещён** в production-путях. Вывод блоков интерфейса — через `ui.print_lines(...)`. |

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
🗑️ reset / clear DB             ← back
```
Использовать те же символы — пользователь распознаёт их за такт.
Рисующие символы рамок брать из `ui.glyphs`: у них есть ASCII-фолбэк для
консолей без UTF-8 (§15.1).

### 13.4 Прогресс-бар
- В phase-2 (executor) есть `[i/N]` в каждой строке → `set_auto_progress(False)`.
- В долгих фазах без `[i/N]` — `set_auto_progress(True)` (по умолчанию).
- Двойной индикации (tqdm + `[i/N]`) быть не должно.

### 13.5 Меню
Меню модуля строится через `ui.menu` / `ui.choose`, пауза — через `ui.pause()`.
Прямые вызовы `questionary.select` со своими `qmark`/`pointer` больше не
допускаются: из-за них интерфейс выглядел собранным из разных программ.
Полный API и пример переноса — §15.1.

### 13.6 Статистика
Статистика БД рисуется `ui.stats_panel(...)`, справка модуля —
`ui.info_panel(...)`, произвольный блок — `ui.panel(...)`.
Собственные разделители вида `'=' * 60` и рамки из `╔═╗` не заводить:
ширина панелей считается по содержимому и по ширине терминала.

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

Phase 2  executor.run_wallet(wallet, task_index=..., task_total=...)
         ─ читает только незавершённые задачи кошелька
         ─ approve → bridge create → on-chain send → poll status
         ─ update_task(task_id, status=..., src_tx_hash=..., ...)
         ─ idempotent: повторный запуск не дублирует работу

Phase 3  excel_export.export_report()
         ─ читает БД ЦЕЛИКОМ (не только текущий run)
         ─ строит Matrix / Tasks / Summary
         ─ Excel — производная от БД, не отдельный лог запуска
```

### 14.2 Lifecycle статусов
См. §5.2 — там же таблица различий по терминальности `failed`.
Набор для phase-2 = «всё, что не входит в `TERMINAL` данного модуля»,
и это условие должно быть одинаковым в `list_pending_for_wallet` и
`list_wallets_with_pending`.

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

В таблице задач (`UNIQUE(wallet_address, token, contract)`) обязаны быть колонки:

| Колонка | Содержание |
|---|---|
| `status` | см. lifecycle |
| `swap_id` | ID операции у моста |
| `deposit_address` | адрес депозита, выданный мостом |
| `src_tx_hash` | tx на исходной сети |
| `dst_tx_hash` | tx на целевой сети |
| `sent_amount_raw`, `sent_amount_human` | сколько отправлено |
| `received_amount` | сколько пришло (из API моста) |
| `dst_balance_before`, `dst_balance_after` | факт. баланс на целевой сети до и после |
| `error_message` | текст ошибки, обрезанный (~500 chars) |
| `attempts` | счётчик попыток (`increment_attempts`) |
| `extra_json` | произвольный JSON-контекст задачи |
| `created_at`, `updated_at` | unix-время, `int` |

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

---

## 15. Общие слои: UI, bootstrap, тесты

Эти три слоя появились при рефакторинге и заменяют то, что раньше каждый
модуль делал сам. Новый код обязан ими пользоваться.

### 15.1 `modules/ui` — терминальный UI-кит

Единственное место, где задаются цвета, рамки и вид вопросов. Модуль не
собирает ANSI-строки руками: иначе интерфейс расползается, а на консолях
без UTF-8 (cp866/cp1251) рамки превращаются в мусор — фолбэк на ASCII
делает `theme`, один раз при импорте.

Точка входа одна:

```python
from modules.ui import ui
```

**Ввод**

| Вызов | Сигнатура | Поведение |
|---|---|---|
| `ui.menu` | `menu(title, options, *, qmark=QMARK, pointer=POINTER, default=None)` | `options` — последовательность пар `(текст, значение)`. Возвращает значение; при Ctrl+C — `None`. |
| `ui.choose` | `choose(title, options, *, back_label="Назад", **kwargs)` | то же, плюс автоматически добавленный пункт «Назад» со значением `"back"`. |
| `ui.confirm` | `confirm(question, *, default=True) -> bool` | Ctrl+C трактуется как «нет». |
| `ui.confirm_or_back` | `confirm_or_back(question, *, yes="Да", no="Нет")` | да / нет / назад: `True`, `False` или `"back"`; `None` при Ctrl+C. Для мастеров, где нужен возврат на шаг назад, а не отмена всей операции. |
| `ui.ask_int` | `ask_int(question, *, minimum=None, maximum=None, default=None) -> int \| None` | валидация и подсказка с диапазоном; `None` — отказ. |
| `ui.ask_text` | `ask_text(question, *, default="", allow_empty=True) -> str \| None` | |
| `ui.pause` | `pause(message="Enter — продолжить")` | Ctrl+C/EOF не роняют программу. |
| `ui.show_items` | `show_items(title, items, **kwargs)` | принимает `list[MenuItem]`, сам считает ширину колонки и возвращает `key`. |

**Блоки вывода**

| Вызов | Сигнатура |
|---|---|
| `ui.header` | `header(title, subtitle=None, *, width=None, color=theme.FG_ACCENT) -> str` |
| `ui.panel` | `panel(title, lines, *, width=None, color=theme.FG_ACCENT, footer=None) -> str` |
| `ui.info_panel` | `info_panel(title, sections, *, width=None, footer=None) -> str` — `sections` это `{заголовок: [строки]}` |
| `ui.stats_panel` | `stats_panel(title, stats, *, total_key="total", footer=None, width=None) -> str` |
| `ui.key_values` | `key_values(mapping, *, indent="  ", key_width=None, key_color=theme.FG_MUTED, value_color=theme.FG_TEXT) -> list[str]` |
| `ui.bullet_list` | `bullet_list(items, *, indent="  ", color=theme.FG_TEXT) -> list[str]` |
| `ui.rule` | `rule(width=None, *, bold=False, color=theme.FG_ACCENT) -> str` |
| `ui.badge` | `badge(text, style="info") -> str` — стили `ok`/`success`/`warn`/`warning`/`error`/`red`/`yellow`/`info` |
| `ui.gradient` | `gradient(text, start=GRADIENT_START, end=GRADIENT_END) -> str` |
| `ui.print_lines` | `print_lines(*blocks)` — печатает блоки с отступами |

Все `panel`-функции возвращают строку, а не печатают: печать — через
`ui.print_lines(...)`.

**Текст и тема.** `ui.fit`, `ui.pad`, `ui.truncate`, `ui.wrap`,
`ui.visual_width`, `ui.shorten_address(address, head=6, tail=4)` — счёт
ширины учитывает эмодзи и широкие символы. `ui.theme` — палитра
(`FG_TEXT`, `FG_MUTED`, `FG_ACCENT`, `FG_BRAND`, `FG_OK`, `FG_WARN`,
`FG_ERR`, `FG_INFO`, `RESET`, `BOLD`, `DIM`), `ui.glyphs` — символы
рисования с ASCII-фолбэком (`h`, `v`, `tl`, `tr`, `bl`, `br`, `bullet`,
`arrow`, `pointer`, `check`, `cross`, `dot`).

**Модель меню.** `MenuItem` / `SubMenu` живут в `modules/ui/menu_model.py`
и реэкспортируются из `config/menu_config.py`. `MenuItem` умеет
`requires_os` (`windows` / `macos` / `linux`), `is_wip`, `badge` +
`badge_style`, `enabled`. `render_items(items) -> [(строка, key), ...]`
считает ширину колонки по самому длинному пункту конкретного меню
(от 18 до 42 ячеек), поэтому длинные названия больше не ломают выравнивание.

**Баннер.** `modules/ui/banner.py`: `print_welcome(data_profile=None,
web_url=None)`, `print_farewell(animate=True)`, `render_logo()`,
`read_version()`. Вызывает только `main.py`.

**Было** (каждый модуль со своим оформлением):

```python
from colorama import Fore, Style
from questionary import Choice, select

action = select(
    "💱 zkSync Era → Base USDC swap-all:",
    choices=[
        Choice("🤖 Авто-режим", "auto"),
        Choice("📊 Статистика БД", "stats"),
        Choice("🔙 Назад", "back"),
    ],
    qmark="💱", pointer="👉",
).ask()
...
print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
for k, v in stats.items():
    print(f"  {k:<22} {v}")
input(f"\n{Fore.CYAN}Нажмите Enter для продолжения...{Style.RESET_ALL}")
```

**Стало:**

```python
from modules.ui import ui

action = ui.choose("zkSync Era → Base USDC swap-all", [
    ("🤖 Авто-режим",    "auto"),
    ("📊 Статистика БД", "stats"),
])
if action in (None, "back"):
    return
...
ui.print_lines(ui.stats_panel("Статистика БД", db.get_statistics(),
                              footer=str(db.DB_PATH)))
ui.pause()
```

Ctrl+C обрабатывается внутри `ui`: `menu`/`choose`/`ask_*` возвращают `None`,
`confirm` — `False`, `pause` не бросает исключение. Модулю не нужно про это
помнить.

### 15.2 `modules/bootstrap.py` — подготовка окружения

Создание рабочих каталогов и шаблонов конфигов вынесено из `main.py`.
Модули не должны создавать каталоги «на всякий случай» — к моменту вызова
модуля они уже есть.

```python
PROJECT_ROOT                                   # корень репозитория, pathlib.Path
REQUIRED_DIRECTORIES                           # ('result', 'data', 'data/twitter',
                                               #  'db', 'backups', 'log')
CEX_SETTINGS_PATH = "config/cex_settings.py"
PINTEREST_CONFIG_PATH = "config/modules/cfg_pinterest.py"

ensure_directories(root=None) -> list[str]     # создаёт каталоги, возвращает созданные
ensure_files(root=None) -> list[str]           # CSV-заголовки + шаблоны конфигов
prepare_workspace(root=None, *, announce=True) -> list[str]
```

`prepare_workspace()` — то, что зовёт `main.py`. Дополнительно дёргает
`data_manager._ensure_data_file()`: схемой `data/data.csv` владеет
`data_manager`, он же умеет мигрировать старые файлы.

Все операции идемпотентны: существующий файл никогда не перезаписывается,
поэтому обновление проекта не затирает настройки пользователя. Если новому
модулю нужен свой каталог — добавляй его в `REQUIRED_DIRECTORIES`, а не в
код модуля.

### 15.3 `tests/` — pytest

```bash
pip install -r requirements-dev.txt
pytest
```

Тесты не ходят в сеть и не трогают пользовательские данные: сеть подменяется
заглушками, запись на диск идёт во временные каталоги (`conftest.py`).

| Файл | Что закрывает |
|---|---|
| `test_imports.py` | каждый модуль проекта импортируется без ошибок; у пакетов есть `__init__.py`; в дереве нет забытых `*.bak`-копий |
| `test_menu_config.py` | целостность меню: уникальность `key` внутри подменю, «Назад» присутствует и стоит последним, каждый включённый `key` обработан в `main.py`, выравнивание и тексты пунктов |
| `test_main_routes.py` | ленивые импорты в `main.py` вытаскиваются из AST и резолвятся — пункт меню не может указывать в никуда |
| `test_config_surface.py` | всё, что код импортирует из `config/`, там действительно есть; записи `NETWORKS` well-formed, без дублей RPC внутри сети и без совпадающих имён |
| `test_networks_config_regressions.py` | атрибуты `config/networks.py`, к которым обращаются модули; explorer одной сети не скопирован в другую; адреса токенов не заимствованы из чужой сети |
| `test_ui.py` | `modules/ui`: подсчёт визуальной ширины (эмодзи, ANSI), одинаковая ширина строк панелей, бейджи, ASCII-фолбэк глифов |
| `test_ui_consistency.py` | вне `modules/ui` никто не импортирует `questionary` — интерфейс собирается только из UI-набора |
| `test_docs.py` | README и `docs/`: относительные ссылки резолвятся, числа сетей совпадают с `NETWORKS`, каждый пункт меню упомянут в README, нет упоминаний давно удалённых конфигов |
| `test_proxy_manager.py` | нормализация форматов прокси |
| `test_balance_checkers.py` | регрессии чекеров балансов (парсинг прокси, возобновление задач) |
| `test_cex_okx.py`, `test_cex_bitget.py` | побайтовое совпадение подписи и тела POST-запросов |
| `test_transfer_erc20_amounts.py` | разбор сумм и процентов из `transfer_amount` |
| `test_twitter_tasks.py` | выполнение и учёт twitter-заданий |

**Новый модуль обязан оставить набор зелёным.** Практически это значит:
модуль импортируется без побочных эффектов (никаких запросов и вопросов
пользователю на уровне модуля), его пункт меню зарегистрирован в
`config/menu_config.py` с уникальным `key` и обработан в `main.py`, все
импортируемые из `config/` константы существуют, а упоминание модуля
добавлено в README (этого требует `test_docs.py`).
