# Проверка Twitter-аккаунтов

`modules/twitter/twitter_check.py` — сбор публичного профиля по списку
никнеймов: жив ли аккаунт, сколько подписчиков, есть ли галочка.

**Меню:** `Twitter → Проверка аккаунтов`
**Точка входа:** `run_twitter_check(os_type)` — `main.py` передаёт тип ОС,
от него зависит только разделитель в итоговом CSV.

Модуль **читает** чужие профили через свой рабочий аккаунт. Ваши
собственные аккаунты для этого не нужны — нужен один живой `auth_token`,
от имени которого делаются запросы.

---

## Файлы

| Путь | Роль |
|---|---|
| `data/twitter/twitters.csv` | вход; используется **только колонка `nickname`** |
| `result/twitter/result.csv` | выход |
| `log/` | лог настраивается `setup_twitter_logging()` |

`data/twitter/twitters.csv` создаётся при первом запуске с заголовком
`nickname,auth_token,ct0,proxy` (`modules/bootstrap.py`).

Перед чтением вызывается `validate_and_fix_csv_format()`: он приводит
заголовок к `nickname,auth_token,ct0` и чинит строки с неверным числом
запятых. Ведущий `@` в никнейме отбрасывается.

---

## Настройки

`config/modules/cfg_twitter.py`:

| Параметр | Значение по умолчанию | Что делает |
|---|---|---|
| `MAIN_AUTH_TOKEN` | `['']` | список рабочих `auth_token`; нужен минимум один |
| `COUNT_REPLACE_TWITTER_AUTH_TOKEN` | `50` | сколько проверок делать одним токеном, прежде чем взять следующий |
| `MAIN_PROXY_TWITTER` | `''` | прокси в формате `log:password@ip:port` |
| `RANDOM_PROXIES_TWITTER` | `True` | брать случайный прокси из колонки `proxy` в `data/data.csv` |

`config/modules/general_config.py`:

| Параметр | Как влияет |
|---|---|
| `NUM_THREADS` | на сколько пакетов делится список никнеймов |
| `SLEEP_BETWEEN_ACTIONS` | пауза между запросами внутри пакета; между пакетами — удвоенная |

> Комментарий в `cfg_twitter.py` упоминает `data/proxy.csv` — этого файла
> давно нет. Прокси берутся из `data/data.csv` через
> `modules/proxy_manager.py`.

### Где взять `auth_token`

Браузер → вход в X/Twitter → F12 → Application/Storage → Cookies →
cookie `auth_token`. Скопируйте значение:

```python
MAIN_AUTH_TOKEN = ['токен1', 'токен2']
COUNT_REPLACE_TWITTER_AUTH_TOKEN = 50
```

Максимум проверок за прогон = `len(MAIN_AUTH_TOKEN) *
COUNT_REPLACE_TWITTER_AUTH_TOKEN`. Если никнеймов больше, модуль
предупредит, посчитает, сколько токенов не хватает, и **обрежет список**
до доступного числа.

---

## Как работает

1. `TokenManager` собирает токены и считает использования каждого.
2. Список никнеймов делится на пакеты: размер ≈ `len(nicknames) /
   NUM_THREADS`, всего пакетов около `NUM_THREADS`.
3. На пакет поднимается одна сессия: заголовки браузера, `auth_token` в
   cookie, `x-csrf-token` из cookie `ct0`, полученного после захода на
   `https://x.com/home`.
4. Внутри пакета запросы ставятся в очередь с паузой
   `SLEEP_BETWEEN_ACTIONS` и выполняются через `asyncio.gather`.
5. Профиль забирается GraphQL-запросом `UserByScreenName`.
6. Между пакетами — увеличенная пауза (удвоенный
   `SLEEP_BETWEEN_ACTIONS`).

Если CSRF-токен получить не удалось, сессия падает с
`Failed to get CSRF token - invalid auth_token?` — это самый частый
признак протухшего токена.

---

## Что собирается

| Поле | Источник |
|---|---|
| `nickname` | из входного файла |
| `name` | `legacy.name` |
| `followers_count` | `legacy.followers_count` |
| `following_count` | `legacy.friends_count` |
| `tweets_count` | `legacy.statuses_count` |
| `verified` | `legacy.verified` — старая галочка |
| `is_blue_verified` | `result.is_blue_verified` — подписка Blue |
| `description`, `location`, `created_at` | `legacy.*` |
| `protected` | закрытый профиль |
| `check_time` | UTC на момент проверки |
| `status` | `success` или текст ошибки |

Ошибочные проверки не выбрасываются: в результат попадает строка с
нулями и статусом ошибки, так что список никнеймов и список строк CSV
совпадают.

---

## Коды ошибок

| Статус | Что означает |
|---|---|
| `Access denied (403)` | токен невалиден либо сработал rate limit |
| `Unauthorized (401)` | `auth_token` истёк |
| `Rate limit exceeded (429)` | слишком часто; увеличьте `SLEEP_BETWEEN_ACTIONS` или добавьте токенов |
| `User not found (404)` | аккаунт удалён или переименован |
| `API Error: …` | GraphQL вернул `errors` |
| `Invalid response structure`, `User data not found` | ответ не разобрался |
| `Exception: …` | сетевая или иная ошибка |

---

## Результат

`result/twitter/result.csv`. Разделитель зависит от ОС: `;` на Windows,
`,` на Linux и macOS. Колонки — те же, что в таблице выше.

Файл перезаписывается при каждом запуске. По завершении в консоль
выводится таблица `Nickname | Name | Followers | Status`.

---

## Смежное

Выполнение действий от имени своих аккаунтов (лайки, ретвиты,
комментарии) — [MODULE_TWITTER_TASKS.md](MODULE_TWITTER_TASKS.md).
