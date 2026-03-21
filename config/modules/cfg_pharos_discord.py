# ========================================================================================
# PHAROS DISCORD CONNECT — Конфигурация
# ========================================================================================
# Основные параметры (потоки, ретраи) — в cfg_base.py
# Здесь только параметры специфичные для привязки Discord к Pharos

# Pharos API
PHAROS_BASE_URL = "https://api.pharosnetwork.xyz"
PHAROS_SITE_URL = "https://testnet.pharosnetwork.xyz"

# Сообщение для подписи (эмуляция MetaMask)
SIGN_MESSAGE = "pharos"

# Время жизни сессии (JWT) в секундах (по умолчанию 23 часа)
SESSION_TTL_SECONDS = 82800

# Заголовки для Pharos API
PHAROS_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://testnet.pharosnetwork.xyz",
    "Referer": "https://testnet.pharosnetwork.xyz/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# Заголовки для Discord API
DISCORD_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://discord.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Реферальный код Pharos
REF_CODE = ""

# Таймаут запросов (секунды)
REQUEST_TIMEOUT = 30

# Директория результатов
RESULT_DIR = "result/pharos_discord"
