# Балансы и субаккаунты Binance

`modules/cex/binance/binance_SubAccount.py` — просмотр балансов и сбор
средств с субаккаунтов на основной аккаунт.

| Меню | Функция |
|---|---|
| `CEX → Binance → Балансы` | `get_balances_binance()` |
| `CEX → Binance → Сбор с субаккаунтов` | `subaccount_collector_binance()` |

Есть и третья точка входа, `check_binance_subaccounts_and_balances()` —
из меню она не вызывается.

Аккаунт выбирается через `select_binance_account()` — см.
[MULTIPLE_EXCHANGE_ACCOUNTS.md](MULTIPLE_EXCHANGE_ACCOUNTS.md).
Нужны `api_key` и `api_secret`; passphrase у Binance нет.

---

## Используемые эндпоинты

| Действие | Эндпоинт |
|---|---|
| Баланс основного аккаунта | `GET /api/v3/account` |
| Список субаккаунтов | `GET /sapi/v1/sub-account/list` |
| Баланс субаккаунта | `GET /sapi/v1/sub-account/assets` |
| Перевод на основной | `POST /sapi/v1/sub-account/universalTransfer` |

Перевод идёт со `SPOT` на `SPOT`, поле `toEmail` оставлено пустым — для
Binance это и означает основной аккаунт. Успехом считается ответ с
`tranId`.

Подпись — HMAC-SHA256 от query-строки, ключ передаётся в заголовке
`X-MBX-APIKEY`.

> `/sapi/v1/sub-account/*` доступны только основному аккаунту и только
> если у ключа включены соответствующие права. Право на вывод для этого
> модуля не нужно: переводы между своими аккаунтами не покидают биржу.

---

## Что показывает сборщик

`subaccount_collector_binance()` печатает баланс основного аккаунта
**до** и **после** сбора, чтобы разницу было видно сразу и не приходилось
сверять цифры вручную. Позиции с ненулевым `locked` расписываются на
свободную и заблокированную части — заблокированное не переводится.

---

## Результат

`result/binance_balances.csv`, колонки:
`Account Name, Account Type, Asset, Free, Locked, Total`.

Файл перезаписывается при каждом запуске.

---

## Смежное

Вывод на кошельки — [MODULE_BINANCE_WITHDRAW.md](MODULE_BINANCE_WITHDRAW.md).
