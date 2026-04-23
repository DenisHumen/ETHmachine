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
