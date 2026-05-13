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
# Максимум одновременно живых browser-contexts (LRU). Каждый context
# съедает 100–200MB ОЗУ; без лимита при 100+ кошельках = OOM.
LITVM_VERCEL_BYPASS_MAX_CONTEXTS = 4
# После N выполненных tRPC-вызовов — перезапускаем весь Chromium
# (боремся с внутренними ликами patchright/chromium).
LITVM_VERCEL_BYPASS_RESTART_EVERY = 60

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


# ============================================================================
# Lester Minter — ERC-20 token factory на LiteForge
# ============================================================================
# Контракт: createToken(name, symbol, totalSupply, decimals,
#                       mintable, burnable, pausable) payable
# Фабрика берёт фиксированную комиссию (0.05 zkLTC) и деплоит токен,
# минтит totalSupply владельцу (caller).
LITVM_MINTER_FACTORY = "0x93acc61fcdc2e3407A0c03450Adfd8aE78964948"
LITVM_MINTER_DEPLOY_FEE_WEI = 50_000_000_000_000_000  # 0.05 zkLTC

# Сколько токенов деплоим с одного кошелька (random в диапазоне).
LITVM_MINTER_TX_PER_WALLET = [1, 1]

# Decimals — взвешенный выбор. 18 — стандарт, реже 6/8/9.
LITVM_MINTER_DECIMALS_CHOICES = [6, 8, 9, 18, 18, 18, 18, 18]

# Total supply: random integer внутри диапазона (в whole tokens, без decimals).
LITVM_MINTER_SUPPLY_RANGE = [100_000, 1_000_000_000]

# Вероятность каждого feature (mintable/burnable/pausable) = True.
LITVM_MINTER_FEATURE_TRUE_PROB = 0.55

# Резерв native для gas (zkLTC). Если на кошельке < fee + reserve — пропуск.
LITVM_MINTER_GAS_RESERVE_ZKLTC = 0.02

# Пауза между deploy-tx одного кошелька (random.uniform).
LITVM_MINTER_SLEEP_BETWEEN_TX = [10, 30]

# Подбирать ли логотип с Pinterest (только для метаданных в БД/Excel —
# фабрика logo не принимает, ImgBB key недоступен).
LITVM_MINTER_USE_PINTEREST_LOGO = False

# Поведение при ошибке отправки одной tx: сколько раз повторять перед failed.
LITVM_MINTER_TX_ATTEMPTS = 2



# ========================================================================================
# MIDAS PREDICTION MARKET (https://www.midashand.xyz/) — пресет проекта LiteForge
# ========================================================================================
# Что делает модуль для каждого кошелька:
#   1. Регистрация на сайте (если ещё нет): SIWE-like подпись + nickname +
#      Cloudflare Turnstile token. Сервер возвращает JWT (accessToken).
#   2. USDC faucet (1h cooldown) — забирает testnet USDC на кошелёк.
#   3. zkLTC native faucet (24h cooldown) — газ для on-chain транзакций.
#   4. Daily check-in (раз в UTC-сутки даёт points).
#   5. N случайных ставок в USDC на случайные исходы случайных активных
#      USDC-маркетов. На каждый маркет вызывается approve + buy().

# ----------------------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------------------
MIDAS_API_BASE = "https://predict-testnet-api.midashand.xyz/api"
MIDAS_SITE_URL = "https://www.midashand.xyz/"

# Cloudflare Turnstile sitekey (виден в JS-бандле фронта; форма register).
MIDAS_TURNSTILE_SITEKEY = "0x4AAAAAADBuL4jfcuLoSewv"

# Таймауты HTTP-запросов к API.
MIDAS_HTTP_TIMEOUT = 30
MIDAS_HTTP_ATTEMPTS = 3            # повторов на каждый запрос при network-ошибках
MIDAS_HTTP_RETRY_DELAY = 3.0       # секунд между ретраями

# ----------------------------------------------------------------------------------------
# Faucet cooldowns (берём с запасом + сервер ругнётся `cooldown` если рано)
# ----------------------------------------------------------------------------------------
MIDAS_FAUCET_USDC_COOLDOWN_SEC = 60 * 60          # 1h
MIDAS_FAUCET_NATIVE_COOLDOWN_SEC = 24 * 60 * 60   # 24h
# Минимальный native баланс (zkLTC), при котором НЕ запрашиваем native faucet.
# Если на кошельке уже >= этого, считаем что газа хватит и не зовём faucet.
MIDAS_NATIVE_SUFFICIENT_BALANCE = 0.005

# ----------------------------------------------------------------------------------------
# Check-in (daily)
# ----------------------------------------------------------------------------------------
# Сервер сам контролирует «можно ли». Локально считаем: «делали сегодня по UTC»
# — пропускаем. Иначе — пробуем; на ответ «уже сделано» помечаем как успех.
MIDAS_CHECKIN_ENABLED = True

# ----------------------------------------------------------------------------------------
# Ставки (USDC)
# ----------------------------------------------------------------------------------------
# Сколько ставок делает один кошелёк за прогон (random.randint).
MIDAS_BETS_PER_WALLET = [1, 2]

# Размер одной ставки в USDC (random.uniform). Сервер min=1 USDC, max=1 М USDC
# (см. /api/markets/collateral-tokens · minTradeSizeInCollateral=1 000 000).
# Важно: фактически в buy() передаётся maxCost в raw — с учётом
# alpha-фее и slippage выставляем с запасом.
MIDAS_BET_AMOUNT_USDC = [1.5, 3.0]

# Минимальный cost одной сделки, raw USDC (жёсткий floor из API).
MIDAS_USDC_MIN_TRADE_RAW = 1_000_000  # = 1 USDC

# Slippage для maxCost (мультипликатор на view-cost). АММ с alpha-фее
# может поднимать фактическую цену на десятки процентов — лучше
# выставлять щедрый буфер (фактический cost «возвращается» refundom).
MIDAS_BET_MAX_COST_MULTIPLIER = 1.5

# Минимум маркетов, которые должны быть найдены до того как начнём ставки.
# Если найдено меньше — пропуск bet-phase, лог warning.
MIDAS_MIN_MARKETS_TO_BET = 1

# Сколько маркетов берём из /markets за один запрос (отфильтруем активные).
MIDAS_MARKETS_FETCH_LIMIT = 50

# Минимум секунд до экспирации маркета, чтобы он считался «торгуемым».
MIDAS_MARKET_MIN_TTL_SEC = 5 * 60

# Пауза между двумя bet-операциями одного кошелька (random.uniform).
MIDAS_SLEEP_BETWEEN_BETS = [10, 30]

# Резерв native (zkLTC) для газа — не трогаем при оценке доступности баланса.
MIDAS_GAS_RESERVE_ZKLTC = 0.002

# Сколько раз пытаемся отправить on-chain tx (approve / buy) при temporary errors.
MIDAS_TX_ATTEMPTS = 2

# ----------------------------------------------------------------------------------------
# Контракты (LiteForge testnet, chain_id=4441)
# ----------------------------------------------------------------------------------------
# USDC mock на LiteForge (подтверждено через /api/markets/collateral-tokens).
MIDAS_USDC_ADDRESS = "0xd5118dee968d1533b2a57ab66c266010ad8957fa"
MIDAS_USDC_DECIMALS = 6


# ========================================================================================
# Aynilabs — wrap zkLTC → WzkLTC (https://www.aynilabs.xyz/dashboard/)
# ========================================================================================
# Контракт-обёртка WzkLTC. Принимает payable deposit() и (по дизайну) минтит 1:1.
#
# Замечание по адресам: в JS-бандле сайта зашит адрес "получателя" с опечаткой
# (b76aea5BB458... вместо b76aea5B8458...). По этому адресу — EOA, не контракт,
# поэтому функция deposit() фактически игнорируется EVM, и native zkLTC просто
# уходит на EOA команды. Реальный ERC-20 WzkLTC задеплоен по правильному
# адресу и кредитуется off-chain (централизованно). Мы повторяем поведение
# сайта (отправляем на DEPOSIT_TARGET с calldata deposit()), а баланс WzkLTC
# читаем с TOKEN_ADDRESS — для аудита/Excel, но не как failure-критерий.
AYNI_WZKLTC_DEPOSIT_TARGET = "0x60a84ebc3483fefb251b76aea5bb458026ef4bea"
AYNI_WZKLTC_TOKEN_ADDRESS = "0x60A84eBC3483fEFB251B76Aea5B8458026Ef4bea"
# Старое имя — оставляем как алиас, чтобы не сломать импорты, если где-то ещё используется.
AYNI_WZKLTC_ADDRESS = AYNI_WZKLTC_DEPOSIT_TARGET
AYNI_CHAIN_ID = 4441

# Какую долю native zkLTC заворачиваем (random.uniform). 1.0 = всё минус резерв.
AYNI_WRAP_PCT_RANGE = [0.30, 0.50]

# Резерв на газ (zkLTC) — не трогаем при WRAP_PCT_RANGE[1] = 1.0.
AYNI_GAS_RESERVE_ZKLTC = 0.0005

# Минимальный native zkLTC, при котором имеет смысл вообще делать wrap.
AYNI_MIN_NATIVE_BALANCE_ZKLTC = 0.001

# Сколько попыток на отправку tx до признания failed.
AYNI_TX_ATTEMPTS = 2

# Сколько ждём receipt (сек).
AYNI_TX_TIMEOUT_SEC = 180

# Пауза между двумя wrap-tx одного кошелька (если будут несколько). Сейчас 1 tx/кошелёк.
AYNI_SLEEP_BETWEEN_TX = [3.0, 6.0]

# ========================================================================================
# Onmi.fun — meme coin launchpad на LITVM (https://app.onmi.fun/?chain=LITVM)
# ========================================================================================
# Token-launch factory: createToken / createTokenAndBuy (создание + опционально баи в одной tx).
# Бондинг-кривая (для последующих trade-операций после создания): bondingCurveManager.
ONMI_TOKEN_FACTORY = "0x432b8b70a63eBB6b90CDFa1F7FeCDf2DD34e7c4E"
ONMI_BONDING_CURVE_MANAGER = "0x2B151AC223aD45C6c06379D68F4BeF67fB08E6e5"
ONMI_PLATFORM = "0x174F8a75F9acf9c2DBb4aD20482Ab4bC4c41828C"
ONMI_CHAIN_ID = 4441

# API роуты (Next.js на app.onmi.fun + публичный api.onmi.fun).
ONMI_API_BASE = "https://app.onmi.fun"
ONMI_AI_API_BASE = "https://api.onmi.fun"
ONMI_HTTP_TIMEOUT = 60

# Сколько native zkLTC засовываем как Initial Buy при createTokenAndBuy.
# Если 0..ONMI_INITIAL_BUY_RANGE_ZKLTC[0] выпадает — создаём БЕЗ initial buy (createToken).
ONMI_INITIAL_BUY_PROBABILITY = 0.85   # с какой вероятностью делать createTokenAndBuy (vs createToken)
ONMI_INITIAL_BUY_RANGE_ZKLTC = [0.0005, 0.002]

# Описание заполняем только в ~5% случаев (по ТЗ пользователя).
ONMI_DESCRIPTION_PROBABILITY = 0.05

# Резервы / лимиты.
ONMI_GAS_RESERVE_ZKLTC = 0.0008
ONMI_MIN_NATIVE_BALANCE_ZKLTC = 0.002

# Tx retry / timing.
ONMI_TX_ATTEMPTS = 2
ONMI_TX_TIMEOUT_SEC = 240
ONMI_SLEEP_BETWEEN_TX = [3.0, 6.0]

# Картинка (требования сайта: max 1 MB, jpg/png/gif, min 1000x1000, 1:1).
ONMI_IMAGE_MAX_BYTES = 1024 * 1024
ONMI_IMAGE_SIDE = 1000  # квадратный crop, минимум 1000x1000
ONMI_IMAGE_JPEG_QUALITY = 85
ONMI_PINTEREST_QUERIES = [
    "meme coin art", "pepe meme", "doge meme", "crypto cat", "shiba inu",
    "moon rocket", "neon cat", "pixel art frog", "cute cartoon mascot",
    "retro gaming sprite", "psychedelic mushroom", "rainbow cat",
    "kawaii animal", "comic mascot", "8bit character",
]

# Сколько раз можно подряд пробовать получить картинку с Pinterest, если не подходит.
ONMI_IMAGE_FETCH_ATTEMPTS = 5


# ========================================================================================
# Onmi.fun — Wallet ↔ Wallet trading (buy/sell на bonding curve)
# ========================================================================================
# Trading router (factory.getRouter()). Принимает buyExactIn(payable) и sellExactIn.
ONMI_TRADE_ROUTER = "0xb0e39b72824fA03b2CbD4486ddDc3630D680eA1b"

# Сколько всего операций (buy/sell) делать за одну сессию.
ONMI_TRADE_TOTAL_OPS_RANGE = [30, 100]

# Размер buy-операции (native zkLTC).
ONMI_TRADE_BUY_VALUE_RANGE_ZKLTC = [0.0001, 0.003]

# Размер sell-операции — процент от текущего token-баланса кошелька.
ONMI_TRADE_SELL_PCT_RANGE = [10.0, 95.0]

# Если у кошелька есть баланс токена > dust — вероятность что он SELL (иначе BUY).
ONMI_TRADE_PROB_SELL_IF_HAS = 0.45

# Минимальный native баланс кошелька для участия в trade-сессии.
ONMI_TRADE_MIN_NATIVE_BALANCE_ZKLTC = 0.0005

# Резерв native zkLTC под gas (не тратим на buy).
ONMI_TRADE_GAS_RESERVE_ZKLTC = 0.0005

# Случайная пауза между операциями [мин, макс] секунд (чтобы выглядеть живым).
ONMI_TRADE_SLEEP_BETWEEN_OPS = [3.0, 18.0]

ONMI_TRADE_TX_TIMEOUT_SEC = 240
ONMI_TRADE_TX_ATTEMPTS = 2

# Минимальный остаток токена (в wei) — ниже этого считаем что баланса нет.
ONMI_TRADE_ERC20_DUST_WEI = 10**9

# Если у кошелька есть несколько токенов — вероятность выбрать тот, что уже в портфеле
# (vs случайный из общего списка known_tokens, чтобы выглядело как органическая торговля).
ONMI_TRADE_PROB_REUSE_PORTFOLIO_TOKEN = 0.55


# ========================================================================================
# Onmi.fun · OnmiSwap — UniswapV2-style swap для graduated токенов
# ========================================================================================
# UniswapV2 router (factory.getRouter())
ONMI_SWAP_ROUTER = "0xe351c47c3b96844F46e9808a7D5bBa8101BfFB57"
# Pair factory
ONMI_SWAP_FACTORY = "0x9ec0eFf74A188B33C29c31849e6D37CbA6E0F586"
# Wrapped native (WzkLTC). Используется как промежуточный токен в path.
ONMI_SWAP_WETH = "0x60A84eBC3483fEFB251B76Aea5B8458026Ef4bea"
# initCodeHash для CREATE2 pair-address (если потребуется офчейн).
ONMI_SWAP_INIT_CODE_HASH = "0x8f3e81720db33e14925a307158d291bb5d812d5cb6c34e54ecf0b33c126eab3f"

# Сколько свапов делать за сессию (DEPRECATED — оставлено для обратной совместимости,
# сейчас сессия идёт по всем кошелькам, а число операций определяется per-wallet ниже).
ONMI_SWAP_TOTAL_OPS_RANGE = [10, 40]
# Сколько свапов делает КАЖДЫЙ кошелёк за сессию (random.randint в этом диапазоне).
ONMI_SWAP_OPS_PER_WALLET_RANGE = [1, 3]
# Размер native-leg buy (zkLTC → token).
ONMI_SWAP_NATIVE_VALUE_RANGE = [0.0001, 0.002]
# Размер sell (% от token-баланса).
ONMI_SWAP_SELL_PCT_RANGE = [20.0, 90.0]
# Вероятность SELL если у кошелька есть LP-токен (иначе BUY).
ONMI_SWAP_PROB_SELL_IF_HAS = 0.45
# Минимальный native баланс для участия в swap-сессии.
ONMI_SWAP_MIN_NATIVE_BALANCE = 0.0005
# Резерв под gas.
ONMI_SWAP_GAS_RESERVE = 0.0005
# Минимальный остаток ERC-20 (wei) — ниже = "ничего нет".
ONMI_SWAP_ERC20_DUST_WEI = 10**9
# Случайная пауза между операциями.
ONMI_SWAP_SLEEP_BETWEEN_OPS = [3.0, 15.0]
# Slippage (доля). 0.05 = принимаем -5% от quote.
ONMI_SWAP_SLIPPAGE = 0.05
# Только пары с native (WETH) в одной стороне. Пары token/token игнорируем.
ONMI_SWAP_NATIVE_PAIRS_ONLY = True
# Минимум резервов pair (wei native) — ниже бесполезно свапать.
ONMI_SWAP_MIN_RESERVE_NATIVE_WEI = 10**16  # 0.01 zkLTC
ONMI_SWAP_TX_TIMEOUT_SEC = 240
ONMI_SWAP_TX_ATTEMPTS = 2
# deadline для swap — теперь + N сек.
ONMI_SWAP_DEADLINE_SEC = 600


# ========================================================================================
# Onmi.fun · Liquidity (add/remove на UniswapV2-style router)
# ========================================================================================
# Размер LP-операции в native (zkLTC). На добавление и токен закупим эквивалент.
ONMI_LIQ_ADD_VALUE_RANGE = [0.0002, 0.001]
# Сколько LP-add попыток за одну сессию (DEPRECATED — см. ONMI_LIQ_OPS_PER_WALLET_RANGE).
ONMI_LIQ_ADD_OPS_RANGE = [1, 3]
# Сколько LP-add операций делает КАЖДЫЙ кошелёк за сессию.
ONMI_LIQ_OPS_PER_WALLET_RANGE = [1, 2]
# Минимальный native для add.
ONMI_LIQ_MIN_NATIVE_BALANCE = 0.001
# Резерв под gas.
ONMI_LIQ_GAS_RESERVE = 0.0008
# Случайная пауза между add-операциями.
ONMI_LIQ_SLEEP_BETWEEN_OPS = [4.0, 20.0]
# deadline.
ONMI_LIQ_DEADLINE_SEC = 600
ONMI_LIQ_TX_TIMEOUT_SEC = 240
ONMI_LIQ_TX_ATTEMPTS = 2
# Slippage для add (минимумы).
ONMI_LIQ_SLIPPAGE = 0.10


# ========================================================================================
# Onmi.fun — Web URLs (для подсказок в меню)
# ========================================================================================
ONMI_SITE_BOARD = "https://app.onmi.fun/board?chain=LITVM"
ONMI_SITE_CREATE = "https://app.onmi.fun/create-token?chain=LITVM"
ONMI_SITE_SWAP = "https://app.onmi.fun/swap?chain=LITVM"
ONMI_SITE_LIQUIDITY = "https://app.onmi.fun/liquidity?chain=LITVM"
ONMI_SITE_DOCS = "https://docs.onmi.fun/"
