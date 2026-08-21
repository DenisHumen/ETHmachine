# Вывод средств с Bitget

`modules/cex/bitget/bitget_withdraw.py` — массовый вывод одного токена с
Bitget на список адресов из `data/data.csv`.

**Меню:** `CEX → Bitget → Вывод средств`
**Точка входа:** `bitget_withdraw()`

Устройство общее с остальными выводами
([OKX](MODULE_OKX_WITHDRAW.md), [Binance](MODULE_BINANCE_WITHDRAW.md),
[MEXC](MODULE_MEXC_WITHDRAW.md)); ниже — специфика Bitget.

---

## Что нужно заполнить

| Что | Где |
|---|---|
| `api_key`, `api_secret`, `passphrase` | `config/cex_settings.py`, список `BITGET_ACCOUNTS` |
| Адреса-получатели | колонка `wallet_address` в `data/data.csv` |
| Правила суммы | `config/modules/cfg_cex.py` |

Подпись — HMAC-SHA256 в base64, заголовок `ACCESS-SIGN`; passphrase
обязателен, как у OKX.

---

## Прокси

В отличие от OKX, где прокси используется точечно, Bitget-модуль
подставляет случайный прокси из `data/data.csv`
(`modules.proxy_manager.get_random_proxy_dict()`) в запросы к API. Это
удобно, когда IP основной машины не входит в белый список ключа.

Если строка прокси не разбирается, запрос уйдёт напрямую — следите за
предупреждениями `proxy_manager` в логе.

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

1. Выбор аккаунта (`select_bitget_account()`).
2. Проверка незавершённого прогресса в `db/bitget_withdraw_progress.db`.
3. Запрос балансов (`/api/spot/v1/account/assets`), выбор токена.
4. Запрос сетей токена и выбор сети.
5. Подтверждение и запуск пула потоков.
6. При `WAIT_FOR_BALANCE = True` — ожидание поступления на адрес.

---

## Результаты

| Путь | Что внутри |
|---|---|
| `db/bitget_withdraw_progress.db` | таблица `withdraw_progress` |
| `result/bitget_withdraw_results_<ГГГГММДД>.csv` | лог выводов за день |

Колонки CSV: `timestamp, wallet_address, token, chain, amount, status,
error_message`.

Статусы: `pending`, `processing`, `success`, `failed`,
`balance_timeout`, `error`.

---

## Ограничение

Пункт `CEX → Bitget → Балансы` помечен `is_wip=True` в
`config/menu_config.py`: `main.py` показывает на него панель «Функционал
ещё в разработке». Балансы субаккаунтов и сбор с
них доступны через `CEX → Bitget → Сбор с субаккаунтов`
(`modules/cex/bitget/bitget_SubAccount.py`,
`check_bitget_subaccounts_and_balances()`).
