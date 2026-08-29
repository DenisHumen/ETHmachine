# Проверка прокси

`modules/check_proxy/` — многоуровневый чекер: живой ли прокси, откуда он
географически, какие сайты через него открываются и с какой скоростью.

**Меню:** `Tools → Проверка прокси`
**Точка входа:** `check_proxy_menu()` (`modules/check_proxy/menu.py`)

| Файл | Роль |
|---|---|
| `menu.py` | вопросы пользователю, пул потоков, прогресс |
| `services.py` | каталог сайтов и RPC, разбитый по уровням |
| `tester.py` | проверка одного прокси, подсчёт score |
| `database.py` | `db/proxy_checker.db` — прогоны, задачи, результаты по сервисам |
| `excel_export.py` | отчёт `result/proxy/run_<id>_<таймштамп>/proxy_report.xlsx` |

---

## Откуда берутся прокси

Колонка `proxy` в `data/data.csv` (через
`modules/proxy_manager.load_proxies()`). Отдельного файла со списком
прокси нет.

Поддерживаемые формы строки: `host:port`, `user:pass@host:port` и те же
две со схемой `http://`, `https://`, `socks4://`, `socks4a://`,
`socks5://`, `socks5h://`. Без схемы подставляется `http`.

---

## Уровни детализации

Меню спрашивает уровень 1–4. Чем выше, тем больше запросов на каждый
прокси и тем дольше прогон.

| Уровень | Что проверяется |
|---|---|
| 1 | alive-пробинг + гео: IP, страна, город, ASN |
| 2 | + общие сайты и соцсети |
| 3 | + криптобиржи, крипто-API и EVM/Solana RPC |
| 4 | + speed-test и jitter |

Состав каталога (`services.py`):

| Группа | Сервисы |
|---|---|
| Гео (L1) | ipapi.co, ipinfo.io, ipify.org, ifconfig.me |
| Общие (L2+) | Google, Cloudflare, GitHub, YouTube, Wikipedia, Amazon, Microsoft |
| Соцсети (L2+) | Twitter/X, Discord, Telegram, Reddit, Instagram, TikTok |
| Биржи (L3+) | Binance, OKX, Bybit, Bitget, MEXC, Coinbase, Kraken |
| Крипто-данные (L3+) | CoinGecko, CoinMarketCap, Etherscan, DeBank, DexScreener |
| RPC (L3+) | ETH (LlamaRPC, Merkle), Base, Arbitrum One, Optimism, Polygon, BSC, Solana |
| Speed (L4) | Cloudflare `__down?bytes=1048576` (1 МБ) + jitter по 4 замерам |

Alive-пробинг — `https://www.cloudflare.com/cdn-cgi/trace`, он же
разбивается на стадии DNS / TCP / TLS / TTFB, что позволяет назвать
`failed_stage` при обрыве.

---

## Дополнительные вопросы

После выбора уровня меню спрашивает:

1. **Сколько прокси проверить** — Enter берёт все.
2. **Сколько потоков** — по умолчанию `NUM_THREADS` из
   `config/modules/general_config.py`, но не выше потолка: **20** для
   уровня 4 и **80** для уровней 1–3. Speed-test тяжёлый, и сотня
   параллельных загрузок по мегабайту искажает замеры друг друга.

---

## Как считается вердикт

`score` = доля сервисов со статусом `OK` от общего числа проверенных, в
процентах. Если сервисы не проверялись (уровень 1), `score` равен 100 при
живом прокси и 0 при мёртвом.

| Вердикт | Условие |
|---|---|
| `WORKING` | `score >= 70` |
| `PARTIAL` | `score > 0` либо прокси жив, но не дотянул до 70 |
| `BROKEN` | остальное |

Статус отдельного сервиса — `OK`, `BLOCKED` (сервис ответил, но отдал
блокировку) или код ошибки. `BLOCKED` не считается за `OK`, но и не
приравнивается к обрыву: прокси рабочий, просто конкретный сайт его не
пускает. Список таких сервисов уходит в `blocked_list` и в отдельный лист
Excel.

`avg_latency` считается только по сервисам со статусом `OK`; если таких
нет, берётся время alive-пробинга.

---

## Результаты

| Путь | Что внутри |
|---|---|
| `db/proxy_checker.db` | прогоны (`runs`), задачи (`tasks`), результаты по сервисам (`service_results`) |
| `result/proxy/run_<id>_<таймштамп>/proxy_report.xlsx` | отчёт |
| `log/proxy_checker_L<уровень>_<таймштамп>.log` | лог прогона |

Листы отчёта: `Summary`, `Overview`, `Services`, `Blocked`, `Working`,
`Errors`. Лист `Working` — чистый список прокси, которые можно забрать
обратно в `data/data.csv`.

Отчёт строится **из базы**, а не из памяти процесса. Поэтому `Ctrl+C`
посреди прогона не теряет работу: прерывание помечает прогон как
`interrupted` и всё равно выгружает частичный Excel.
