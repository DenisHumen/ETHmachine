# ========================================================================================
# FHENIX — настройки проекта
# ========================================================================================

# ----------------------------------------------------------------------------------------
# Ghost Faucet (https://ghostchain.io/faucet/ethereum-sepolia/)
# ----------------------------------------------------------------------------------------
GHOST_FAUCET_URL = "https://ghostchain.io/faucet/ethereum-sepolia/"
GHOST_FAUCET_AJAX_URL = "https://ghostchain.io/wp-admin/admin-ajax.php"
GHOST_FAUCET_NETWORK_KEY = "sepolia"
GHOST_FAUCET_TURNSTILE_SITEKEY = "0x4AAAAAACDtEWtNVETrBTV2"

# Кулдаун крана: одна заявка в 24 часа
GHOST_FAUCET_COOLDOWN_HOURS = 24

# Максимум ожидания зачисления на кошелек (минут)
GHOST_FAUCET_ARRIVAL_TIMEOUT_MIN = 10
# Интервал проверки баланса (секунд)
GHOST_FAUCET_BALANCE_POLL_INTERVAL = 30

# RPC для проверки баланса на Sepolia (round-robin)
GHOST_FAUCET_SEPOLIA_RPCS = [
    "https://1rpc.io/sepolia",
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://rpc.sepolia.org",
]

# HTTP таймаут запросов
GHOST_FAUCET_HTTP_TIMEOUT = 30

# Глобальный rate-limit для POST submit_claim между потоками.
# Faucet-хот-кошелёк шлёт tx последовательно: если два потока попадают одновременно,
# сервер падает с "INTERNAL_ERROR: could not replace existing tx" и капча сгорает зря.
# Минимальный интервал между submit-ами (секунды). Sepolia block ~12s — берём с запасом.
GHOST_FAUCET_SUBMIT_MIN_INTERVAL = 13


# ----------------------------------------------------------------------------------------
# Alchemy Faucet — Base Sepolia (https://www.alchemy.com/faucets/base-sepolia)
# ----------------------------------------------------------------------------------------
# Реверс-инжиниринг подтверждён на чанке _next/static/chunks/0b_y0tnec2m-9.js:
#   POST /api/faucets/{slug}/send body={"address":"0x..","turnstileToken":".."}
#   Ответ: {"transactionHash":"0x.."} | {"error":"..."}
ALCHEMY_FAUCET_URL = "https://www.alchemy.com/faucets/base-sepolia"
ALCHEMY_FAUCET_API_SEND = "https://www.alchemy.com/api/faucets/base-sepolia/send"
ALCHEMY_FAUCET_TURNSTILE_SITEKEY = "0x4AAAAAAB_Xdru0nbY8rQu_"

# Кран отдаёт 0.1 ETH на Base Sepolia, лимит — 1 раз в 24 часа.
ALCHEMY_FAUCET_COOLDOWN_HOURS = 24

# Максимум ожидания зачисления на кошелёк (минут)
ALCHEMY_FAUCET_ARRIVAL_TIMEOUT_MIN = 5
# Интервал проверки баланса (секунд)
ALCHEMY_FAUCET_BALANCE_POLL_INTERVAL = 15

# RPC для Base Sepolia (chainId 84532), round-robin.
ALCHEMY_FAUCET_BASE_SEPOLIA_RPCS = [
    "https://sepolia.base.org",
    "https://base-sepolia-rpc.publicnode.com",
    "https://base-sepolia.gateway.tenderly.co",
    "https://1rpc.io/base-sepolia",
]

# HTTP таймаут запросов
ALCHEMY_FAUCET_HTTP_TIMEOUT = 30
