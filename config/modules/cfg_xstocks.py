# ========================================================================================
# xStocks DeFi Points — настройки модуля
# ========================================================================================

# URL проекта
BASE_URL = "https://defi.xstocks.fi"
API_BASE_URL = "https://api.backed.fi/xdrop-api/api/v1"

# HTTP настройки
REQUEST_TIMEOUT = 30  # Таймаут запросов (секунды)

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://defi.xstocks.fi",
    "Referer": "https://defi.xstocks.fi/points",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
}

# Сообщения для подписи (из JS бандла фронтенда)
SIGN_MESSAGES = {
    "REGISTRATION": "By signing this message, I confirm wallet ownership and register for xPoints",
    "SAY_GM": "Say GM",
    "DAILY_SPIN_MULTIPLIER": "Reveal daily spin multiplier",
    "INITIATE_TELEGRAM_AUTH": "Initiate Telegram Auth",
    "REFERRAL_CODE_UPDATE_PREFIX": "Update referral code: ",
}

# GM (Say GM) настройки
GM_COOLDOWN_HOURS = 24  # Кулдаун Say GM (часы) — SAY_GM_DAILY_CLICK_LIMIT=1
GM_CHECK_INTERVAL_MINUTES = 5  # Интервал проверки готовности GM (минуты)

# Режим работы
SHUFFLE_WALLETS = True  # Перемешивать кошельки
INFINITE_LOOP = True  # Бесконечный цикл (GM farming)
LOOP_CHECK_INTERVAL = [300, 600]  # Проверка состояния цикла (секунды) [min, max]

# Реферальная система
# Максимальная разница использований реферальных кодов (50%)
REFERRAL_MAX_USAGE_DIFF_PERCENT = 50
