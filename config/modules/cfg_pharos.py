# ========================================================================================
# PHAROS TESTNET FAUCET & QUEST BOT — Конфигурация
# ========================================================================================
# Основные параметры (потоки, ретраи, ключи капчи) — в cfg_base.py
# Здесь только параметры специфичные для Pharos

# API
BASE_URL = "https://api.pharosnetwork.xyz"
RPC_URL = "https://testnet.dplabs-internal.com"
CHAIN_ID = 688688
EXPLORER_URL = "https://testnet.pharosscan.xyz/tx/"

# Реферальный код
REF_CODE = "8G8MJ3zGE5B7tJgP"

# FaroSwap Faucet (DODO API)
FAROSWAP_FAUCET_URL = "https://api.dodoex.io/gas-faucet-server/faucet/claim"
FAROSWAP_CHAIN_ID = 688689
FAROSWAP_CAPTCHA_URL = "https://faroswap.xyz/faucet"
FAROSWAP_WEBSITE_KEY = "0x4AAAAAACAb9Tup9M-ewXTN"

# Капча Pharos (Google reCAPTCHA)
PHAROS_CAPTCHA_URL = "https://testnet.pharosnetwork.xyz/"
PHAROS_WEBSITE_KEY = "6Lfx1iwrAAAAAJp_suDVjStYCUs0keW8tQ722uZR"

# Заголовки запросов
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://testnet.pharosnetwork.xyz",
    "Referer": "https://testnet.pharosnetwork.xyz/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# ID задач, которые можно верифицировать напрямую через /task/verify
VERIFIABLE_TASK_IDS = [201, 202, 203, 204, 205]

# Суб-задачи #205 (Follow us on X) — верифицируются автоматически при верификации #205
FOLLOW_SUB_TASK_IDS = [301, 302, 303, 304]

# Исторические on-chain задачи (были в прошлых сезонах, сейчас invalid)
HISTORICAL_TASK_IDS = [
    101, 102, 103, 104, 105, 106, 107, 108,
    111, 112, 114, 116, 117, 119,
    121, 122, 125, 126, 127, 128, 129, 131,
    401,
]

# Все ID для учёта в статистике (включая исторические)
ALL_TASK_IDS = VERIFIABLE_TASK_IDS + FOLLOW_SUB_TASK_IDS + HISTORICAL_TASK_IDS

# ========================================================================================
# ЗАДЕРЖКИ (секунды)
# ========================================================================================
DELAY_BETWEEN_ACCOUNTS = (3, 8)                    # задержка между стартом аккаунтов
DELAY_BETWEEN_ACTIONS = (2, 5)                      # задержка между действиями внутри аккаунта
DELAY_BETWEEN_CYCLES = (43200, 44000)               # задержка между циклами (12ч по умолчанию)
DELAY_BETWEEN_CYCLES_CHECKIN = (86400, 90000)       # задержка между циклами Check-in (24-25ч)
REQUEST_TIMEOUT = 30

# ========================================================================================
# МНОГОПОТОЧНОСТЬ
# ========================================================================================
MAX_CONCURRENT_WALLETS = 20                          # макс. параллельных кошельков
SHUFFLE_WALLETS = True                               # перемешивать порядок кошельков каждый цикл
