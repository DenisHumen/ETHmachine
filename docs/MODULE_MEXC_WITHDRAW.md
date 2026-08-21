# Вывод средств с MEXC

`modules/cex/mexc/mexc_withdraw.py` — массовый вывод одного токена с MEXC
на список адресов из `data/data.csv`.

**Меню:** `CEX → MEXC → Вывод средств`
**Точка входа:** `mexc_withdraw()`

Устройство общее с остальными выводами
([OKX](MODULE_OKX_WITHDRAW.md), [Binance](MODULE_BINANCE_WITHDRAW.md),
[Bitget](MODULE_BITGET_WITHDRAW.md)); ниже — специфика MEXC.

---

## Что нужно заполнить

| Что | Где |
|---|---|
| `api_key`, `api_secret` | `config/cex_settings.py`, список `MEXC_ACCOUNTS` |
| Адреса-получатели | колонка `wallet_address` в `data/data.csv` |
| Правила суммы | `config/modules/cfg_cex.py` |

Passphrase у MEXC нет. Аутентификация: заголовок `X-MEXC-APIKEY` плюс
подпись HMAC-SHA256 от query-строки. Метка времени берётся не с локальной
машины, а с `/api/v3/time` — так подпись не отваливается из-за
разъехавшихся часов.

---

## Прокси

Запросы к API идут через случайный прокси из `data/data.csv`
(`modules.proxy_manager.get_random_proxy_dict()`).

---

## Настройки

`config/modules/cfg_cex.py`:

| Параметр | Значение по умолчанию | Что делает |
|---|---|---|
| `TYPE_WITHDRAW` | `0` | `0` — сумма в токене, `1` — в USDT по курсу |
| `VALUES_TO_WITHDRAW` | `[0.00496102, 0.005]` | диапазон `[min, max]` на кошелёк |
| `WAIT_FOR_BALANCE` | `True` | ждать поступления, таймаут 1 час |

Потоки и паузы — `NUM_THREADS`, `SLEEP_BETWEEN_ACTIONS` из
`config/modules/general_config.py`.

---

## Ход работы

1. Выбор аккаунта (`select_mexc_account()`).
2. Проверка незавершённого прогресса в `db/mexc_withdraw_progress.db`.
3. Запрос балансов (`/api/v3/account`), выбор токена.
4. Запрос сетей токена, выбор сети, получение комиссии.
5. Подтверждение и запуск пула потоков.
6. При `WAIT_FOR_BALANCE = True` — ожидание поступления на адрес.

---

## Результаты

| Путь | Что внутри |
|---|---|
| `db/mexc_withdraw_progress.db` | таблица `withdraw_progress` |
| `result/mexc_withdraw_results_<ГГГГММДД>.csv` | лог выводов за день |

Колонки CSV: `timestamp, wallet_address, token, chain, amount, status,
error_message`.

Статусы: `pending`, `processing`, `success`, `failed`,
`balance_timeout`, `error`.

---

## Ограничение

У MEXC в проекте есть только вывод. Балансов и сбора с субаккаунтов нет —
в подменю `CEX → MEXC` один пункт.
