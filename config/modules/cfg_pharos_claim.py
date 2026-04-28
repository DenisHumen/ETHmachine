# ========================================================================================
# PHAROS CLAIM CHECKER — Конфигурация (claim.pharos.xyz)
# ========================================================================================
# Флоу бэкенда сайта (реверс JS-бандла):
#   1. Строим сообщение AUTH_MESSAGE_TEMPLATE
#   2. Подписываем приватным ключом (personal_sign / EIP-191)
#   3. POST {API_BASE_URL}{AUTH_ENDPOINT}
#         body: {address, message, mode:"evm", signature}
#         ответ: {success:true, data:{verified:true, token:"..."}}
#   4. GET {API_BASE_URL}{INFO_ENDPOINT}
#         header: Authorization: TOKEN <token>
#         ответ-eligible: data содержит allocation/tiers/...
#         ответ-not-eligible: {code:40001, message:"no data", data:null}
#
# Параметры потоков/ретраев берутся из cfg_base.py:
#   NUM_THREADS, SLEEP_BETWEEN_ACTIONS, DELAY_BETWEEN_ACCOUNTS, RETRY_COUNT
# ========================================================================================

# ───────── Адреса сайта / API ─────────
SITE_URL = "https://claim.pharos.xyz/"
API_BASE_URL = "https://api.claim.pharos.xyz"
AUTH_ENDPOINT = "/accounts/sign_in_blockchain"
INFO_ENDPOINT = "/airdrop/airdrop_info"

# ───────── Подпись ─────────
# Точный шаблон сообщения, как формирует фронт:
# `Sign this message to authenticate with Pharos.\n\nWallet: <addr>\nTimestamp: <ms>`
AUTH_MESSAGE_TEMPLATE = (
    "Sign this message to authenticate with Pharos.\n\n"
    "Wallet: {address}\nTimestamp: {timestamp}"
)

# ───────── HTTP ─────────
# Базовые заголовки. User-Agent ставится автоматически fake-useragent на каждый запуск.
CLAIM_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://claim.pharos.xyz",
    "Referer": "https://claim.pharos.xyz/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# TLS-импресонация curl_cffi (маскируемся под реальный Chrome).
CLAIM_IMPERSONATE = "chrome131"

# Таймаут одного HTTP-запроса (сек)
CLAIM_REQUEST_TIMEOUT = 30

# Прогрев сессии (GET главной claim.pharos.xyz) перед POST-ом auth — получаем
# CDN/cookie, как реальный браузер.
CLAIM_WARMUP_SESSION = True

# Если True — кошельки без прокси в data.csv помечаются failed.
REQUIRE_PROXY = True


# ========================================================================================
# CLAIMER — он-чейн исполнение клейма (для eligible/not-claimed кошельков)
# ========================================================================================
# Реверс JS-бандла claim.pharos.xyz (PROD, mainnet включён):
#   • сеть Pharos Mainnet, chain id 1672, native gas-токен PROS
#   • контракт 0xe5bfde2310fa2a315f814dcc0c8b97c159c8062d (SSR airdropContractAddress)
#   • окно клейма: 2026-04-28T11:00:00Z → 2026-10-25T11:00:00Z
#   • JS-флоу (chunk 5027, claim:async):
#         1. n = K(tier, address)                 — скачать proof-файл с CDN
#         2. o = stringToHex(tier, {size:32})     — bytes32 right-padded
#         3. e = claimTiers(o)                    — вернёт (merkleRoot, token, start, end)
#            if e[0] == 0x00×32 → "This tier is not configured yet"
#         4. ok = check_proof(o, address, BigInt(amount), e[0], merkleProof)
#            if !ok → "Invalid merkle proof"
#         5. tx = claim(o, BigInt(amount), merkleProof)
#   • proof-файл лежит на статике (chunk 4878):
#       https://static.claim.pharos.xyz/resources/airdrops/PROD/PHAROSAIRDROP/<tier>/proof_<md5>_<tier>.json
#       md5 = md5(("pharosairdrop" + tier + address.lower()[2:5]).toLowerCase())
#   • tier для Instant Airdrop = "now"
# ========================================================================================

# RPC и идентификаторы сети Pharos Mainnet
CLAIM_RPC_URL = "https://rpc.pharos.xyz"
CLAIM_RPC_FALLBACKS = (
    # zan.top требует API-ключ (403 без white-list), оставлено для отладки:
    # "https://api.zan.top/node/v1/pharos/mainnet/<KEY>",
)
CLAIM_CHAIN_ID = 1672
CLAIM_NATIVE_SYMBOL = "PROS"

# Контракт раздачи и эксплорер для tx-ссылок
CLAIM_CONTRACT_ADDRESS = "0xe5bfde2310fa2a315f814dcc0c8b97c159c8062d"
CLAIM_EXPLORER_TX = "https://pharosscan.xyz/tx/"

# Где лежат proof-файлы. {tier} и {md5} подставляются клиентом.
PROOF_BASE_URL = "https://static.claim.pharos.xyz"
PROOF_PATH_TEMPLATE = "/resources/airdrops/PROD/PHAROSAIRDROP/{tier}/proof_{md5}_{tier}.json"
PROOF_HASH_PREFIX = "pharosairdrop"

# ABI контракта (реверс из chunk 4878, модуль 11765).
# Функции, которые на самом деле вызывает фронт:
#   claim, hasClaimed (read), claimTiers (read), check_proof (pure).
CLAIM_CONTRACT_ABI = [
    {
        "type": "function",
        "name": "claim",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "tier", "type": "bytes32"},
            {"name": "amount", "type": "uint256"},
            {"name": "merkleProof", "type": "bytes32[]"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "hasClaimed",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "check_proof",
        "stateMutability": "pure",
        "inputs": [
            {"name": "tier", "type": "bytes32"},
            {"name": "claimer", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "merkleRoot", "type": "bytes32"},
            {"name": "merkleProof", "type": "bytes32[]"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "claimTiers",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "bytes32"}],
        "outputs": [
            {"name": "merkleRoot", "type": "bytes32"},
            {"name": "token", "type": "address"},
            {"name": "startTime", "type": "uint256"},
            {"name": "endTime", "type": "uint256"},
        ],
    },
]

# Параметры транзакции
CLAIM_GAS_LIMIT = 300_000          # запас, реально ~110k
CLAIM_GAS_PRICE_BUFFER = 1.20      # множитель на eth_gasPrice (защита от bumping)
CLAIM_TX_TIMEOUT = 180             # ожидание майнинга (сек)

# Тир по умолчанию, если airdrop_info вернул None.
# Допустимые значения: "now", "30days", "60days", "90days", "stake".
CLAIM_DEFAULT_TIER = "now"

# Если True — после успешного клейма пытаемся через 5 сек. дождаться
# подтверждения (tx receipt). False — возвращаем txhash как «pending».
CLAIM_WAIT_FOR_RECEIPT = True


# ========================================================================================
# REGISTRAR — регистрация tier (Instant Airdrop) ДО открытия клейма
# ========================================================================================
# Реверс JS claim.pharos.xyz:
#   Кнопка Confirm на странице выбора опции airdrop вызывает:
#     updateTier(tier) → SWR mutation → POST {API_BASE_URL}/airdrop/airdrop_info
#                                           header: Authorization: TOKEN <token>
#                                           body:   {"tier": "<tier>"}
#     Успех:       {success:true, code:0, data:{...обновлённое airdrop_info}}
#     Уже стоит:   тот же ответ (сервер идемпотентен)
#     Не eligible: {success:true, code:40002, message:"request failed", data:null}
#
# UI-маппинг (см. webpack chunk 1722, модуль 4219):
#   "now"    → "Instant Airdrop-PHRS"   (в UI после ребрендинга может отображаться PROS)
#   "30days" → 30-дневный delay +5%
#   "60days" → 60-дневный delay +12%
#   "90days" → 90-дневный delay +20%
#   "stake"  → "Instant Airdrop-stPHRS"
# ========================================================================================

# Эндпоинт обновления tier. По совпадению тот же, что и GET info, только метод POST.
UPDATE_TIER_ENDPOINT = "/airdrop/airdrop_info"

# Тир по умолчанию для регистрации (Instant Airdrop).
# Допустимые значения: "now", "30days", "60days", "90days", "stake".
REGISTER_DEFAULT_TIER = "now"

# Если True — после регистрации делаем повторный GET /airdrop_info, чтобы убедиться,
# что сервер действительно зафиксировал выбранный tier.
REGISTER_VERIFY_AFTER = True

