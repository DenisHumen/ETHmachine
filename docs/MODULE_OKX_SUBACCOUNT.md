# Балансы и субаккаунты OKX

`modules/cex/okx/okx_SubAccount.py` — два действия над одним и тем же
клиентом `OKXClient`: посмотреть балансы и собрать средства с
субаккаунтов на основной аккаунт.

| Меню | Функция |
|---|---|
| `CEX → OKX → Балансы` | `get_balances_okx()` |
| `CEX → OKX → Сбор с субаккаунтов` | `check_okx_subaccounts_and_balances()` |

Аккаунт выбирается через `select_okx_account()` — см.
[MULTIPLE_EXCHANGE_ACCOUNTS.md](MULTIPLE_EXCHANGE_ACCOUNTS.md).
Требуются `api_key`, `api_secret` и `passphrase`; при пустом любом из них
модуль останавливается с ошибкой.

---

## Что именно делается

### Балансы

1. `/api/v5/asset/balances` — активы основного аккаунта.
2. `/api/v5/users/subaccount/list` — список субаккаунтов.
3. `/api/v5/asset/subaccount/balances` — активы каждого субаккаунта.

В отчёт попадают только позиции с балансом больше нуля. В консоль
выводится сводка: сколько аккаунтов, сколько из них с балансом, какие
валюты найдены.

### Сбор с субаккаунтов

Для каждой ненулевой позиции субаккаунта вызывается
`/api/v5/asset/transfer` с параметрами `from='6'`, `to='6'`, `type='2'`,
`subAcct=<имя>` — это внутренний перевод «субаккаунт → основной». Средства
после этого лежат на финансовом счёте основного аккаунта, откуда их и
выводит [MODULE_OKX_WITHDRAW.md](MODULE_OKX_WITHDRAW.md).

Перевод не идёт на блокчейн: комиссии сети нет, транзакции в обозревателе
не будет.

---

## Подпись запросов

HMAC-SHA256 по строке `timestamp + method + request_path + body`,
результат в base64. Заголовки: `OK-ACCESS-KEY`, `OK-ACCESS-SIGN`,
`OK-ACCESS-TIMESTAMP`, `OK-ACCESS-PASSPHRASE`. Таймаут запроса — 30 сек.

Для чтения балансов и внутренних переводов права на вывод у ключа **не
нужны** — достаточно чтения и трейдинга. Это разумный способ ограничить
ущерб от утечки ключа.

---

## Результат

`result/okx_balances.csv`, колонки:
`Account Name, Account Type, Currency, Balance, Available, Frozen`.

Файл **перезаписывается** при каждом запуске. `Account Type` — `main` для
основного аккаунта.

---

## Смежное

- Вывод на кошельки — [MODULE_OKX_WITHDRAW.md](MODULE_OKX_WITHDRAW.md)
- Спотовая торговля — `modules/cex/okx/okx_SpotTrade.py`, настройки в
  `config/modules/cfg_spot_trade.py`
