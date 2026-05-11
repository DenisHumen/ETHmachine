# ETHmachine Web Dashboard — План разработки

Документ ведёт разработку веб-морды мониторинга и управления для ETHmachine.
Каждая фича помечена статусом:

- `[ ]` **Stage 1** — не реализовано
- `[~]` **Stage 2** — реализовано, не протестировано
- `[x]` **Stage 3** — реализовано и протестировано

Не вычёркивать пункты — обновлять статус и оставлять историю.

---

## 0. Цели

ETHmachine — многомодульная Python-утилита, запускающая по N экземпляров
on-chain задач. Существующее UX — терминал. Веб-морда добавляет:

1. **Мониторинг live-логов** из всех запущенных экземпляров (single source).
2. **Просмотр SQLite-баз** в `db/` в read-only режиме.
3. **Просмотр и скачивание** файлов из `result/`, `data/`, `db/`.
4. **Редактирование конфигов** в `config/` (любой файл) с показом diff и
   индикатором «нужен перезапуск».
5. **Управление пользователями** — первая регистрация = root, отдельная
   БД `db/web_admin.db`, готовая к расширению (роли, audit).

---

## 1. Технологический стек

| Слой | Выбор | Причина |
|---|---|---|
| HTTP | `aiohttp` 3.13 | уже в `requirements.txt`, поддерживает websockets без доп. либ |
| Templates | `jinja2` 3.1 | минимальный server-side rendering |
| WebSocket | `aiohttp.WSMessage` | live-логи и события БД |
| DB | `sqlite3` (stdlib) | то же, что использует остальной проект |
| Auth | hand-rolled session, `hashlib.scrypt` для паролей, signed cookie | без bcrypt-зависимости, без OAuth |
| Frontend | vanilla HTML / CSS / JS, без сборки | проще, киберпанк-глитчи на pure CSS |
| Стиль | claude.ai-like layout, palette = красный + чёрный + неон | по запросу пользователя |

Зависимости, которые мы добавили: `jinja2`. Остальное — стандартная либа или
уже было в `requirements.txt`.

---

## 2. Архитектура

```
web/
├── PLAN.md                        ← этот файл
├── __init__.py                    ← public API: startup() / stop() / is_running()
├── preflight.py                   ← проверка зависимостей + инструкция установки
├── server.py                      ← aiohttp.web.Application factory + threaded launcher
│
├── core/
│   ├── auth.py                    ← scrypt + signed-cookies + session middleware
│   ├── templating.py              ← Jinja2 env + render() с CSP
│   └── paths.py                   ← ROOT/DATA/RESULT/DB/CONFIG/STATIC и safe_under
│
├── storage/
│   └── database.py                ← db/web_admin.db: схема + CRUD
│
├── logs/
│   ├── bus.py                     ← in-memory ring buffer + WS подписчики
│   └── sink.py                    ← loguru-sink → LogsBus
│
├── browsers/
│   ├── databases.py               ← read-only SQLite explorer для db/*.db
│   ├── files.py                   ← листинг + скачивание data/, result/, db/
│   └── configs.py                 ← перечисление config/, чтение/запись + diff
│
├── handlers/                      ← HTTP/WebSocket контроллеры
│   ├── auth.py                    ← /login, /register, /logout
│   ├── dashboard.py               ← /dashboard, /api/ws/logs, /api/health
│   ├── databases.py               ← /databases, /databases/{db}, /databases/{db}/{table}
│   ├── files.py                   ← /files, /files/download
│   ├── configs.py                 ← /configs, /configs/edit, /configs/save
│   └── settings.py                ← /settings (users + audit)
│
├── tests/
│   └── smoke_test.py              ← end-to-end: бутстрап сервера + 27 проверок
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── databases.html
│   ├── files.html
│   ├── configs.html
│   └── settings.html
└── static/
    ├── css/
    │   ├── theme.css              ← red/cyberpunk palette + glitch
    │   └── layout.css             ← claude.ai-like layout
    └── js/
        ├── app.js                 ← глобальные утилиты, fetch wrapper
        ├── logs.js                ← WebSocket подписка, ring buffer на клиенте
        └── editor.js              ← простой редактор конфигов + diff
```

### 2.1 Поток live-логов

```
loguru.logger ──► log_sink (custom sink)
                    │
                    ▼
              LogsBus.put(record)
              ├── ring_buffer (deque, maxlen=2000)
              └── для каждого WS-клиента: queue.put_nowait(record)

WebSocket /api/ws/logs ◄── client subscribes ◄── /logs page
```

`log_sink` подключается к `loguru.logger` один раз — в `simple_logger.py`
при первом импорте, **только если веб-сервер активен**. Это избегает
лишней работы для CLI-only режимов.

### 2.2 Поток жизни запущенного модуля

`runs_registry` хранит таблицу `runs(id, module, started_at, ended_at, status, pid, run_token)`.

При старте любого модуля (через main.py) можно (опционально) вызвать
`runs_registry.start(module='ghost_faucet')`, при завершении — `runs_registry.end(...)`.
Эта интеграция — задача *Phase 2*, не блокирует базовую работу веб-морды.

---

## 3. Схема БД `db/web_admin.db`

Все таблицы создаются с `IF NOT EXISTS`.

### 3.1 `users`
| col | type | notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| username | TEXT UNIQUE NOT NULL | |
| password_hash | TEXT NOT NULL | scrypt(salt, password) base64 |
| password_salt | TEXT NOT NULL | base64 |
| role | TEXT NOT NULL | `root` / `admin` / `viewer` |
| is_active | INTEGER NOT NULL DEFAULT 1 | |
| created_at | TEXT NOT NULL | ISO UTC |
| last_login_at | TEXT | ISO UTC |

Первая регистрация: если в `users` 0 строк — форма `/register` доступна
без авторизации, новый пользователь получает `role='root'`. Дальше эта
форма недоступна (только root может приглашать).

### 3.2 `sessions`
| col | type | notes |
|---|---|---|
| id | TEXT PK | secrets.token_urlsafe(32) |
| user_id | INTEGER REFERENCES users(id) ON DELETE CASCADE | |
| created_at | TEXT NOT NULL | |
| last_seen_at | TEXT NOT NULL | |
| user_agent | TEXT | |
| ip | TEXT | |
| expires_at | TEXT NOT NULL | created + 30 дней |

### 3.3 `audit_log`
| col | type | notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| ts | TEXT NOT NULL | |
| user_id | INTEGER | nullable (system) |
| action | TEXT NOT NULL | login / config_edit / db_browse / file_download / register / role_change |
| target | TEXT | файл/таблица/имя пользователя |
| metadata | TEXT | JSON |

### 3.4 `config_changes`
| col | type | notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| user_id | INTEGER NOT NULL | |
| path | TEXT NOT NULL | относительно корня репо |
| ts | TEXT NOT NULL | |
| diff | TEXT NOT NULL | unified diff |
| restart_required | INTEGER NOT NULL | 0/1 |
| applied | INTEGER NOT NULL DEFAULT 1 | |

### 3.5 `runs` (Phase 2)
| col | type | notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| module | TEXT NOT NULL | ключ модуля (`ghost_faucet`, `swap_zksync`...) |
| started_at | TEXT NOT NULL | |
| ended_at | TEXT | |
| status | TEXT NOT NULL | `running` / `done` / `error` / `cancelled` |
| pid | INTEGER | |
| run_token | TEXT NOT NULL UNIQUE | для будущей рег-ции дочерних логов |

---

## 4. Запуск

### 4.1 Конфиг
В `config/modules/cfg_web.py`:
```python
WEB_ENABLED = True
WEB_HOST = "127.0.0.1"
WEB_PORT = 8765
WEB_AUTOSTART_FROM_MAIN = True       # если True — старт при импорте main.py
WEB_LOG_RING_SIZE = 2000
WEB_SESSION_TTL_DAYS = 30
WEB_COOKIE_SECRET_FILE = "db/.web_cookie_secret"   # генерится автоматически
```

### 4.2 Интеграция с main.py
`main.py` в начале вызывает `web.start_web_server_thread()`, который:
- проверяет `WEB_ENABLED`,
- если `True` — запускает aiohttp в отдельном потоке (через свой asyncio loop),
- ставит loguru-sink в `simple_logger`.

CLI продолжает работать как раньше — веб-сервер не блокирует.

---

## 5. Безопасность

| Угроза | Контрмера |
|---|---|
| Bind на 0.0.0.0 без TLS | По умолчанию `127.0.0.1`. Изменение ip — ответственность пользователя; в UI пометка. |
| CSRF | Все мутирующие запросы — `POST` + `X-CSRF-Token` header (token = `sha256(session_id+secret)`) |
| XSS | Jinja2 autoescape + Content-Security-Policy header, без inline-JS |
| Path traversal в file browser | `pathlib.Path.resolve()` + проверка `is_relative_to(root)` |
| SQL injection в DB browser | Только параметризованные `SELECT * FROM "<sanitized>"` (whitelist таблиц) |
| Запись в config | Файл должен быть `*.py` под `config/`, проверка через `is_relative_to` |
| Log poisoning через UI | Любой ввод в логи — экранируется на клиенте |

---

## 6. Стиль (палитра / эффекты)

- Базовый фон: `#0a0a0a` (almost black)
- Акцент: `#e74c3c` / `#ff3366` (red/pink neon)
- Подсветка: `#ff66aa` glow для активного
- Шрифт: `"JetBrains Mono"`, `"Consolas"`, monospace
- Glitch-эффекты: CSS-keyframes + `clip-path`, лёгкие RGB-сдвиги при hover
- Layout: левая панель (claude.ai-like sidebar), верхний хедер с username,
  основная зона — карточки с rounded corners

CSS — в `web/static/css/theme.css` + `layout.css`.

---

## 7. Маршруты (план)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/` | редирект на `/dashboard` или `/login` |
| GET | `/login` | страница входа |
| POST | `/login` | приём формы |
| GET | `/register` | только при пустой `users`, иначе 403 |
| POST | `/register` | то же |
| POST | `/logout` | |
| GET | `/dashboard` | live-логи + сводка runs |
| GET | `/databases` | список БД из `db/`, кликом — таблицы |
| GET | `/databases/{file}/{table}` | страница таблицы (paginated) |
| GET | `/files` | дерево data/, result/, db/ |
| GET | `/files/download?path=...` | стриминг файла |
| GET | `/configs` | список config/ файлов |
| GET | `/configs/edit?path=...` | редактор |
| POST | `/configs/save` | сохранение + diff + audit |
| GET | `/api/ws/logs` | WebSocket-канал логов |
| GET | `/api/runs` | JSON: список runs |
| GET | `/api/health` | `{ok: true}` |

---

## 8. Tracking — статусы реализации

### 8.1 Подготовка инфраструктуры

- [x] Установить `jinja2` в venv (выполнено через `pip install`)
- [x] `web/PLAN.md` создан
- [x] Удалить старый `notifications.py` и `cfg_notifications.py`
- [x] Переименовать `general_config.py` → `general_config.py` и обновить 35 файлов
- [x] Обновить AGENTS.md (убрать упоминания Telegram, заменить general_config)
- [x] Создать `config/modules/cfg_web.py`

### 8.2 Web — backbone

- [x] `web/__init__.py` с `start_web_server_thread()`
- [x] `web/server.py` с aiohttp app, регистрация routes
- [x] `web/database.py` с миграцией схемы
- [x] `web/auth.py` (scrypt password, session middleware)
- [x] Cookie-secret persisted в `db/.web_cookie_secret`
- [x] CSRF middleware
- [x] Базовый `templates/base.html`
- [x] CSS (`theme.css` + `layout.css`)
- [x] JS (`app.js`)

### 8.3 Auth flow

- [x] `/register` доступен только при пустой `users`
- [x] `/login` ставит cookie, обновляет `last_login_at`
- [x] `/logout` стирает cookie
- [x] Аудит в `audit_log` (login / register / logout)
- [x] Тест: первый юзер получает `role=root`

### 8.4 Live-логи

- [x] `web/logs_bus.py` (deque + asyncio.Queue per subscriber)
- [x] `web/log_sink.py` (loguru sink hook)
- [x] Wire-up в `simple_logger.py` (idempotent)
- [x] WS-эндпоинт `/api/ws/logs`
- [x] Frontend `static/js/logs.js` с auto-reconnect
- [x] Тест: 3 одновременных модуля → все строки видны на дашборде

### 8.5 DB browser

- [x] Перечисление `*.db` в `db/`
- [x] Перечисление таблиц + view на каждую
- [x] Pagination (`LIMIT/OFFSET`, по 100 строк)
- [x] Защита от path traversal
- [x] Тест: открыть `fhenix_ghost_faucet.db` → таблицы видны

### 8.6 Files browser

- [x] Дерево `data/`, `result/`, `db/`
- [x] Скачивание (стриминг)
- [x] Запрет на запись из UI
- [x] Тест: скачать любой файл из `result/`

### 8.7 Config editor

- [x] Перечисление `config/**/*.py` (рекурсивно)
- [x] Просмотр + edit textarea
- [x] Сохранение → diff → запись в `config_changes`
- [x] Флаг «restart required» для глобальных файлов (`general_config.py`, `networks.py`, `menu_config.py`)
- [x] Список изменённых файлов с указанием — нужен ли перезапуск
- [x] Тест: изменить `NUM_THREADS` → видно diff и флаг restart

### 8.8 Стиль / UX

- [x] Тема `theme.css` (красный/чёрный, неон)
- [x] Glitch-анимация на заголовках
- [x] Sidebar layout
- [x] Тест: визуальная проверка через curl/смок-запрос

### 8.9 Интеграция в main.py

- [x] `main.py` стартует поток веб-сервера
- [x] Логи CLI → дублируются на дашборд
- [x] Тест: `python main.py` запускает веб + меню работает

### 8.10 Smoke / E2E тесты

Тесты находятся в `web/tests/`. Запуск: `venv/Scripts/python.exe -m web.tests.run_all`.

- [x] `test_database_init` — миграция создаёт таблицы
- [x] `test_auth_first_register` — первая регистрация → root
- [x] `test_auth_login_logout` — happy path
- [x] `test_logs_bus` — push → подписчик получает
- [x] `test_config_diff` — сохранение конфига создаёт запись
- [x] `test_files_traversal_block` — `..` отклоняется
- [x] `test_db_browser_whitelist` — таблица не из БД → 404
- [x] `test_server_smoke` — поднять сервер, GET `/api/health`, GET `/login`

---

## 9. Out of scope (на будущее)

- Realtime push изменений БД (триггеры → WS): не нужно сейчас, polling достаточно.
- Запуск/остановка модулей через UI: только просмотр на этом этапе.
- Метрики (prometheus): нет.
- Multi-tenant: один юзер-root управляет всем.
- TLS: пользователь сам ставит nginx/caddy впереди.
- 2FA: добавим при необходимости.

---

## 10. Журнал изменений

- 2026-05-08 — создан PLAN.md, выбран стек.
- 2026-05-08 — переименован `general_config.py` → `general_config.py`.
- 2026-05-08 — удалены `modules/notifications.py` и `cfg_notifications.py`.
- 2026-05-08 — собран базовый каркас web/, добавлен auth + live-логи.
- 2026-05-08 — добавлены DB/files/config браузеры + smoke-тесты.
- 2026-05-08 — `web/server.py` + полный пакет `web/handlers/` (auth, dashboard,
  WS-логи, databases, files, configs, settings); зашит автозапуск из `main.py`.
- 2026-05-08 — `web/tests/smoke_test.py`: 27/27 PASS (server up, register/login/logout,
  все страницы 200, traversal заблокирован, configs save+diff+revert, WS стримит
  свежие записи loguru, статика, чистый shutdown).
- 2026-05-08 — реорганизация в `core/` `storage/` `logs/` `browsers/`; добавлен
  `web/preflight.py` (lazy import + понятная инструкция при отсутствии aiohttp/
  jinja2/loguru); `web.startup()` — единая точка входа; `requirements.txt`
  пополнен `jinja2`. Smoke-тесты после реорга — 27/27 PASS.
