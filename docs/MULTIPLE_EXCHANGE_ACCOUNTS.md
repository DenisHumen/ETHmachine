# Несколько аккаунтов на бирже

Каждая биржа в проекте описывается **списком** аккаунтов, а не одной
парой ключей. Перед работой модуль спрашивает, с каким аккаунтом
работать — или выбирает сам, если активный один.

**Конфиг:** `config/cex_settings.py`
**Селектор:** `modules/cex/exchange_selector.py`

`config/cex_settings.py` не входит в git и создаётся при первом запуске
шаблоном из `modules/bootstrap.py`.

---

## Как описываются аккаунты

```python
# OKX — https://www.okx.com/ru/account/my-api
# Поставьте 1, если депозиты приходят на Торговый аккаунт вместо Финансового.
OKX_EU_TYPE = 0

OKX_ACCOUNTS = [
    {
        'name': 'OKX Main',
        'api_key': '',
        'api_secret': '',
        'passphrase': '',
        'type': OKX_EU_TYPE,
        'enabled': False,
    },
]

BINANCE_ACCOUNTS = [
    {
        'name': 'Binance Main',
        'api_key': '',
        'api_secret': '',
        'enabled': False,
    },
]

BITGET_ACCOUNTS = [
    {
        'name': 'Bitget Main',
        'api_key': '',
        'api_secret': '',
        'passphrase': '',
        'enabled': False,
    },
]

MEXC_ACCOUNTS = [
    {
        'name': 'MEXC Main',
        'api_key': '',
        'api_secret': '',
        'enabled': False,
    },
]
```

Чтобы добавить второй аккаунт — скопируйте словарь в тот же список,
поменяйте `name` и ключи, поставьте `enabled=True`.

### Поля

| Поле | Кому нужно | Комментарий |
|---|---|---|
| `name` | всем | подпись в меню выбора и в логах |
| `api_key`, `api_secret` | всем | — |
| `passphrase` | OKX, Bitget | у Binance и MEXC такого поля нет |
| `enabled` | всем | `False` — аккаунт не появится в выборе |
| `type` | OKX | лежит в шаблоне, но модули читают не его, а константу `OKX_EU_TYPE` на уровне файла |

`OKX_EU_TYPE = 0` заставляет `okx_withdraw` перед выводом перевести
остаток с торгового счёта на финансовый. Поставьте `1`, если депозиты у
вас и так приходят на торговый — перевод тогда не нужен.

---

## Как выбирается аккаунт

`ExchangeSelector` считает аккаунт активным, если у него
`enabled=True` **и** непустой `api_key`. Дальше:

| Ситуация | Что произойдёт |
|---|---|
| Ни одного активного | ошибка с подсказкой заполнить `config/cex_settings.py` |
| Ровно один активный | выбирается автоматически, в лог пишется имя |
| Несколько активных | интерактивный список |

Каждый модуль зовёт свой селектор, поэтому биржу выбирать не приходится —
только аккаунт:

```python
from modules.cex.exchange_selector import (
    select_okx_account,
    select_binance_account,
    select_bitget_account,
    select_mexc_account,
)

exchange_name, account = select_okx_account()
if not account:
    logger.error("Не выбран аккаунт OKX")
    return

api_key = account['api_key']
api_secret = account['api_secret']
passphrase = account.get('passphrase')   # только OKX и Bitget
```

Есть и общий `select_exchange_account()` без привязки к бирже: он
показывает список бирж, у которых есть активные аккаунты, и уже потом —
аккаунты выбранной. Если биржа с активными аккаунтами одна, шаг выбора
биржи пропускается.

При успешном выборе в лог уходит строка вида
`OKX: OKX Main (API: 1a2b3c4d...)` — ключ обрезается до восьми символов.

---

## Кто использует селекторы

| Модуль | Селектор |
|---|---|
| `modules/cex/okx/okx_withdraw.py` | `select_okx_account()` |
| `modules/cex/okx/okx_SubAccount.py` | `select_okx_account()` |
| `modules/cex/okx/okx_SpotTrade.py` | `select_okx_account()` |
| `modules/cex/binance/binance_withdraw.py` | `select_binance_account()` |
| `modules/cex/binance/binance_SubAccount.py` | `select_binance_account()` |
| `modules/cex/bitget/bitget_withdraw.py` | `select_bitget_account()` |
| `modules/cex/bitget/bitget_SubAccount.py` | `select_bitget_account()` |
| `modules/cex/mexc/mexc_withdraw.py` | `select_mexc_account()` |

---

## Проверка настроек

Валидатор конфигурации при старте программы проверяет структуру
аккаунтов: у активных должны быть заполнены обязательные поля (для OKX и
Bitget — включая `passphrase`). Подробности —
[MODULE_CONFIG_VALIDATOR_NICKNAME.md](MODULE_CONFIG_VALIDATOR_NICKNAME.md).

Проверить селектор отдельно:

```bash
python modules/cex/exchange_selector.py
```

---

## Безопасность

- `config/cex_settings.py` исключён из git — держите его только локально.
- Выдавайте ключам минимум прав. Для балансов и сбора с субаккаунтов
  право на вывод **не нужно**.
- Включайте белый список IP на стороне биржи.
- Адреса вывода добавляйте в белый список биржи заранее.
