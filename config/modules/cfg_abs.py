# ========================================================================================
# Abstract Portal — настройки модуля
# ========================================================================================

# URL проекта
PORTAL_URL = "https://portal.abs.xyz"
BACKEND_URL = "https://backend.portal.abs.xyz"

# Privy Auth
PRIVY_APP_ID = "cm04asygd041fmry9zmcyn5o5"
PRIVY_API_URL = "https://privy.abs.xyz"

# Abstract Chain
CHAIN_ID = 2741
RPC_URL = "https://api.mainnet.abs.xyz"

# HTTP настройки
REQUEST_TIMEOUT = 30  # Таймаут запросов (секунды)

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://portal.abs.xyz",
    "Referer": "https://portal.abs.xyz/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Sec-Ch-Ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

# Privy-specific headers
PRIVY_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "privy-app-id": PRIVY_APP_ID,
    "privy-client": "react-auth:3.19.0-snapshot-20260327195028",
    "Origin": "https://portal.abs.xyz",
    "Referer": "https://portal.abs.xyz/",
}

# privy-client-id из реального браузера (общий для всех)
PRIVY_CLIENT_ID = "client-WY5amHUxxFHMHHMmPJvBQgGPJQ1WuMFjP57qUmHcbu4g2"

# Бейджи
MIN_CLAIM_BALANCE = 0.0001  # Минимальный баланс ETH для клейма бейджа

# Режим работы
SHUFFLE_WALLETS = True  # Перемешивать кошельки
