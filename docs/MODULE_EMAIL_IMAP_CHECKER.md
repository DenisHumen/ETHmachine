# Проверка почт через IMAP

`modules/email/email_imap_checker.py` — массовая проверка, что пара
«ящик + пароль» действительно логинится по IMAP и даёт доступ к папкам.

**Меню:** `Tools → Проверка почт`
**Точка входа:** `run_email_checker()`

Вопросов не задаёт: берёт все ящики из `data/data.csv` и запускает пул
потоков.

---

## Откуда берутся данные

Через `modules.data_manager.get_emails()` — строки, у которых заполнена
колонка `email`:

| Колонка `data/data.csv` | Назначение |
|---|---|
| `email` | адрес ящика |
| `email_password` | пароль (для Gmail, Yahoo, Outlook — пароль приложения, не основной) |
| `email_imap` | IMAP-сервер; если пусто, определяется по домену |

---

## Определение IMAP-сервера

Если `email_imap` пуст, сервер выбирается по домену из таблицы,
зашитой в `get_imap_server()`:

| Домены | Сервер |
|---|---|
| gmail.com, googlemail.com | `imap.gmail.com` |
| yahoo.com, yahoo.co.uk, yahoo.fr | `imap.mail.yahoo.com` |
| outlook.com/.fr, hotmail.com/.fr, live.com/.fr, msn.com | `imap-mail.outlook.com` |
| mail.ru, internet.ru, bk.ru, list.ru, inbox.ru | `imap.mail.ru` |
| yandex.ru, yandex.com, ya.ru | `imap.yandex.ru` |
| rambler.ru | `imap.rambler.ru` |
| aol.com | `imap.aol.com` |
| icloud.com, me.com, mac.com | `imap.mail.me.com` |
| zoho.com | `imap.zoho.com` |
| protonmail.com | `imap.protonmail.com` |
| tutanota.com | `imap.tutanota.com` |

Для неизвестного домена подставляется `imap.<домен>`. Если у вашего
провайдера сервер называется иначе — заполните `email_imap` явно.

---

## Прокси не поддерживаются

**Проверка идёт с реального IP.** `imaplib.IMAP4_SSL` открывает сырой
сокет, а HTTP-прокси из `data/data.csv` к нему не применяются. Модуль
загружает список прокси, но, обнаружив его непустым, печатает
предупреждение до начала логинов — и работает напрямую.

Раньше здесь стоял `urllib.request.install_opener`, который создавал
видимость прокси, но на IMAP не влиял вообще и вдобавок менял глобальное
состояние `urllib` из рабочих потоков. Поэтому имитацию убрали в пользу
честного предупреждения.

Если проверка с реального IP неприемлема — гоняйте модуль на машине с
нужным IP или через системный VPN.

---

## Настройки

Используется `config/modules/general_config.py`:

| Параметр | Значение по умолчанию | Как влияет |
|---|---|---|
| `NUM_THREADS` | `5` | размер пула потоков |
| `SLEEP_BETWEEN_ACTIONS` | `[2, 4]` | случайная пауза перед каждым логином, сек |

Таймаут подключения — 30 секунд, порт — 993 (IMAPS), оба заданы в коде.

> В `config/modules/cfg_email.py` лежат `ENABLE_SEARCH_EMAIL`,
> `IMAP_SERVER`, `MAIN_MAIL`, `PROXY`. Модуль их импортирует, но нигде не
> использует — на поведение чекера они не влияют.

---

## Статусы

| Статус | Что означает |
|---|---|
| `WORKING` | логин прошёл, `INBOX` открылся, список папок получен |
| `AUTH_FAILED` | неверный логин или пароль |
| `FOLDER_ACCESS_ERROR` | логин прошёл, но список папок не отдался |
| `IMAP_ERROR: …` | прочая ошибка протокола |
| `SSL_ERROR: …` | ошибка TLS |
| `TIMEOUT` | сервер не ответил за 30 секунд |
| `DNS_ERROR: …` | домен IMAP-сервера не резолвится |
| `UNKNOWN_ERROR: …` | всё остальное |

Строки без `email` или без пароля пропускаются и в результат не попадают.

---

## Результаты

`result/email/email_check_results_<ГГГГММДД_ЧЧММСС>.csv`, колонки:
`email, password, imap_domain, status, checked_at`.

Лог: `log/email_checker.log`.

> Файл результатов содержит пароли в открытом виде — обращайтесь с ним
> как с `data/data.csv`.

В консоль по завершении выводится сводка: рабочих, нерабочих, всего,
время и процент успешных.
