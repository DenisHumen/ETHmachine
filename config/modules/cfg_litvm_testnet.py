# ========================================================================================
# LITVM TESTNET (LiteForge) — настройки проекта
# ========================================================================================
# Network info:
#   name      LiteForge
#   chain_id  4441
#   symbol    zkLTC (нативный токен)
#   rpc       https://liteforge.rpc.caldera.xyz/http  (wss://.../ws — websocket)
#   explorer  https://liteforge.explorer.caldera.xyz

# ----------------------------------------------------------------------------------------
# Faucet (https://liteforge.hub.caldera.xyz/)
# ----------------------------------------------------------------------------------------
# Хаб развёрнут на Vercel, поэтому при первом заходе показывается
# "Vercel Security Checkpoint" — JS PoW + hCaptcha. После прохождения
# challenge ставится cookie `_vcrcs`, по которой пускают на сам сайт.
# Faucet-API крана — стандартный для Caldera Hub: POST /api/faucet
# с телом {"address": "0x..", "captchaToken": ".."}. Если ответ
# отличается — поправь LITVM_FAUCET_API_PATH и парсер.

LITVM_FAUCET_URL = "https://liteforge.hub.caldera.xyz/"
# tRPC mutation: POST /api/trpc/faucet.requestFaucetFunds?batch=1
# Запрос делается из браузера (Vercel BotID режет HTTP вне Chrome).
LITVM_FAUCET_API_PATH = "/api/trpc/faucet.requestFaucetFunds?batch=1"
# rollupSubdomain в payload tRPC. У других Caldera-хабов он отличается
# (см. URL вида <subdomain>.hub.caldera.xyz).
LITVM_FAUCET_ROLLUP_SUBDOMAIN = "liteforge"

# Captcha (Caldera Hub использует Cloudflare Turnstile).
# Sitekey подтверждён по iframe widget'а: 0x4AAAAAAASRorjU_k9HAdVc.
# Если хаб мигрирует на hCaptcha/recaptcha — поменяй LITVM_FAUCET_CAPTCHA_TYPE
# на 'hcaptcha' / 'recaptcha_v2' / 'recaptcha_v3' и обнови sitekey.
LITVM_FAUCET_CAPTCHA_SITEKEY = "0x4AAAAAAASRorjU_k9HAdVc"
LITVM_FAUCET_AUTO_SITEKEY = False  # auto-парсинг бесполезен пока Vercel BotID активен
LITVM_FAUCET_CAPTCHA_TYPE = "turnstile"

# ----------------------------------------------------------------------------------------
# Vercel Security Checkpoint (BotID) bypass
# ----------------------------------------------------------------------------------------
# Хаб развёрнут на Vercel, и /api/faucet тоже под BotID. BotID — это JS-PoW,
# pure-`requests` его пройти не может. Решение: patchright (anti-detect форк
# Playwright) запускает Chromium через прокси кошелька, проходит чек-поинт,
# извлекает cookie `_vcrcs` и сохраняет в db/litvm.db (таблица vcrcs_cookies,
# ключ — proxy). На повторных запусках cookie берётся из кэша. При 429 от
# хаба cookie инвалидируется и фетчится заново.
#
# Cookie привязана к IP, поэтому у каждого уникального прокси своя cookie.
# Один и тот же прокси у нескольких кошельков шарит cookie.

# headless=True по умолчанию (быстрее, не мешает). Если patchright не
# справляется — поставь False и увидишь окно браузера во время бапасса.
LITVM_VERCEL_BYPASS_HEADLESS = True
# Таймаут на одну попытку обхода (от старта браузера до появления _vcrcs).
LITVM_VERCEL_BYPASS_TIMEOUT_SEC = 60

# Кулдаун крана (часов). Стандарт Caldera Hub — раз в 24h на адрес.
LITVM_FAUCET_COOLDOWN_HOURS = 24

# ----------------------------------------------------------------------------------------
# Average arrival time / wait-for-balance
# ----------------------------------------------------------------------------------------
# Считаем «кран запрошен» только когда баланс реально вырос. Среднее время
# зачисления собирается из request_history (метки sent_at vs arrived_at).
# Таймаут для конкретной попытки = avg(последние N) * (1 + margin), с min/max.
LITVM_FAUCET_AVG_SAMPLES = 20                 # сколько последних замеров учитывать
LITVM_FAUCET_AVG_MARGIN = 0.20                # +20% к среднему времени
LITVM_FAUCET_ARRIVAL_MIN_SEC = 60             # нижняя граница ожидания
LITVM_FAUCET_ARRIVAL_MAX_SEC = 30 * 60        # верхняя граница (защита от вечного poll)
LITVM_FAUCET_ARRIVAL_FALLBACK_SEC = 5 * 60    # используется, пока нет статистики
LITVM_FAUCET_BALANCE_POLL_INTERVAL = 10       # секунд между проверками баланса

# ----------------------------------------------------------------------------------------
# RPC для проверки баланса на LiteForge (round-robin)
# ----------------------------------------------------------------------------------------
LITVM_RPCS = [
    "https://liteforge.rpc.caldera.xyz/http",
]

# HTTP таймаут запросов
LITVM_FAUCET_HTTP_TIMEOUT = 30


# ========================================================================================
# Bridge (Sepolia ⇄ LiteForge)
# ========================================================================================
# Каким направлением работает модуль по умолчанию.
#   'l2_to_l1' — вывод zkLTC из LiteForge на Sepolia (для кошельков из крана).
#   'l1_to_l2' — депозит zkLTC из Sepolia в LiteForge.
# Обратный мост (если включён) — противоположное направление.
LITVM_BRIDGE_PRIMARY_DIRECTION = "l2_to_l1"

# Сколько транзакций отправлять с каждого кошелька и какой % баланса за tx.
LITVM_BRIDGE_TX_COUNT_RANGE = [3, 6]
LITVM_BRIDGE_AMOUNT_PCT_RANGE = [3.0, 6.0]

# Минимальный размер одной транзакции (zkLTC).
LITVM_BRIDGE_MIN_AMOUNT_ZKLTC = 0.001

# Резерв gas-токена — не тратим из баланса.
LITVM_BRIDGE_GAS_RESERVE_ETH = 0.002      # Sepolia ETH под газ L1
LITVM_BRIDGE_GAS_RESERVE_ZKLTC = 0.01     # L2 native под газ withdraw/finalize

# Обратный мост: после успешного выполнения основного направления
# отправить ОДНУ транзакцию в противоположную сторону (% от баланса).
LITVM_BRIDGE_RETURN_ENABLED = False
LITVM_BRIDGE_RETURN_PCT = 100.0

# Пауза между транзакциями одного кошелька (секунды, рандом).
LITVM_BRIDGE_SLEEP_BETWEEN_TX = [20, 60]

# Опрос баланса при ожидании зачисления на destination (для L1→L2).
LITVM_BRIDGE_BALANCE_POLL_INTERVAL = 15
LITVM_BRIDGE_ARRIVAL_TIMEOUT_SEC = 30 * 60

# Авто-финализация L1 для L2→L1 вывода. Модуль на каждом запуске пытается
# вызвать Outbox.executeTransaction по всем submitted-tx. Если outbox ещё
# не готов (challenge window не закрылся / оператор сети не подтвердил
# ассерцию) — задача остаётся в submitted и будет повторно проверена при
# следующем запуске модуля. Никаких ручных действий не требуется.
LITVM_BRIDGE_AUTO_FINALIZE_L1 = True
LITVM_BRIDGE_FINALIZE_RETRY_INTERVAL_SEC = 30 * 60   # не чаще чем раз в N сек на одну tx

# Сетевые таймауты.
LITVM_BRIDGE_RPC_TIMEOUT = 20
LITVM_BRIDGE_RECEIPT_TIMEOUT_SEC = 300
LITVM_BRIDGE_SUBMIT_MIN_INTERVAL = 1.0

# Контракты и RPC.
LITVM_BRIDGE_SEPOLIA_CHAIN_ID = 11155111
LITVM_BRIDGE_LITEFORGE_CHAIN_ID = 4441
LITVM_BRIDGE_L1_TOKEN_ZKLTC = "0xaE9190aEca45F50dCDa0483c0223E191E6811ad2"
LITVM_BRIDGE_L1_INBOX = "0x8A381f8822E512E50dd4679E678271E9a83226E6"
LITVM_BRIDGE_L1_BRIDGE = "0x9BC68f8B2fEa572eDc0813F76C186A31E4150F6F"
LITVM_BRIDGE_L2_ARBSYS = "0x0000000000000000000000000000000000000064"
LITVM_BRIDGE_L2_NODE_INTERFACE = "0x00000000000000000000000000000000000000C8"

LITVM_BRIDGE_SEPOLIA_RPCS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://1rpc.io/sepolia",
    "https://rpc.sepolia.org",
    "https://endpoints.omniatech.io/v1/eth/sepolia/public",
]

