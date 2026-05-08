# ========================================================================================
# НАСТРОЙКИ модуля 💱 Swap All zkSync Era → Base USDC
# ========================================================================================
# Маршруты Rhino.fi (mode=pay):
#   USDC (zkSync Era) → USDC (Base)
#   USDT (zkSync Era) → USDC (Base)
# Прочие токены пропускаются (статус "skipped"). Native ETH не трогаем — нужен на газ.
#
# Глобальные параметры (NUM_THREADS, SLEEP_BETWEEN_ACTIONS, DELAY_BETWEEN_ACCOUNTS,
# TX_SEND_ATTEMPTS, RETRY_COUNT) берутся из config/modules/cfg_base.py.

# --- Параметры свапа ---
ARRIVAL_TIMEOUT_SEC = 25 * 60     # Таймаут ожидания прихода USDC в Base (сек)
RHINOFI_POLL_INTERVAL = 15        # Период опроса Rhino.fi по статусу (сек)
TX_RECEIPT_TIMEOUT_SEC = 600      # Таймаут ожидания подтверждения on-chain tx (сек)

# --- API ---
# Публичный widget-key, извлечён из бандла app.rhino.fi (SDA Widget prod).
# Если оставить пустым — попытается работать без ключа (вернёт 401).
RHINOFI_API_KEY = "PUBLIC-ef7459b7-208b-46f4-839e-99bf81b88fee"
RHINOFI_BASE_URL = "https://api.rhino.fi"

# Минимальная сумма (в токене) для подачи в quote — quote сам отвергает
# слишком мелкие суммы; здесь — лишь грубый локальный фильтр.
MIN_AMOUNT_USDC = "0.5"
MIN_AMOUNT_USDT = "0.5"
