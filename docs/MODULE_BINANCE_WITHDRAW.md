# Вывод средств с Binance

`modules/cex/binance/binance_withdraw.py` — массовый вывод одного токена
с Binance на список адресов из `data/data.csv`.

**Меню:** `CEX → Binance → Вывод средств`
**Точка входа:** `binance_withdraw()`

Модуль устроен так же, как остальные три вывода
([OKX](MODULE_OKX_WITHDRAW.md), [Bitget](MODULE_BITGET_WITHDRAW.md),
[MEXC](MODULE_MEXC_WITHDRAW.md)); ниже — только то, что специфично для
Binance.

---

## Что нужно заполнить

| Что | Где |
|---|---|
| `api_key`, `api_secret` | `config/cex_settings.py`, список `BINANCE_ACCOUNTS` |
| Адреса-получатели | колонка `wallet_address` в `data/data.csv` |
| Правила суммы | `config/modules/cfg_cex.py` |

Passphrase у Binance нет — в отличие от OKX и Bitget. Аутентификация:
заголовок `X-MBX-APIKEY` плюс подпись HMAC-SHA256 от query-строки.

У API-ключа должно быть включено право на вывод, а адреса добавлены в
белый список Binance.

---

## Настройки

`config/modules/cfg_cex.py` — общий файл для всех бирж:

| Параметр | Значение по умолчанию | Что делает |
|---|---|---|
| `TYPE_WITHDRAW` | `0` | `0` — сумма в токене, `1` — в USDT по курсу |
| `VALUES_TO_WITHDRAW` | `[0.00496102, 0.005]` | диапазон `[min, max]`, своё случайное значение на каждый кошелёк |
| `WAIT_FOR_BALANCE` | `True` | ждать поступления на кошелёк, таймаут 1 час |

Потоки и паузы — `NUM_THREADS` и `SLEEP_BETWEEN_ACTIONS` из
`config/modules/general_config.py`.

---

## Ход работы

1. Выбор аккаунта (`select_binance_account()`).
2. Проверка незавершённого прогресса в `db/binance_withdraw_progress.db`:
   `Продолжить`, `Очистить и начать заново` или `Отменить`.
3. Запрос балансов, выбор токена с положительным балансом.
4. Запрос сетей токена и выбор сети.
5. Подтверждение и запуск пула потоков.
6. При `WAIT_FOR_BALANCE = True` — ожидание поступления, статус
   `balance_timeout`, если за час не пришло.

Сумма для каждого кошелька считается отдельно и округляется до 6 знаков.

---

## Результаты

| Путь | Что внутри |
|---|---|
| `db/binance_withdraw_progress.db` | таблица `withdraw_progress` |
| `result/binance_withdraw_results_<ГГГГММДД>.csv` | лог выводов за день |

Колонки CSV: `Timestamp, Wallet, Token, Network, Amount, Status, Error`.

Статусы — те же, что у OKX: `pending`, `processing`, `success`,
`failed`, `balance_timeout`, `error`.

---

## Смежное

Сбор средств с субаккаунтов и просмотр балансов — отдельный модуль,
[MODULE_BINANCE_SUBACCOUNT.md](MODULE_BINANCE_SUBACCOUNT.md).
