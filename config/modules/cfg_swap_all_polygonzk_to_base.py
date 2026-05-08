# ========================================================================================
# НАСТРОЙКИ модуля 💱 Swap All Polygon zkEVM → Base USDC
# ========================================================================================
# Маршруты Layerswap:
#   USDC (Polygon zkEVM) → USDC (Base)
#   ETH  (Polygon zkEVM) → ETH  (Base)
# Прочие токены пропускаются (статус "skipped").
#
# Глобальные параметры (NUM_THREADS, SLEEP_BETWEEN_ACTIONS, DELAY_BETWEEN_ACCOUNTS,
# TX_SEND_ATTEMPTS, RETRY_COUNT) берутся из config/modules/cfg_base.py.
# Здесь — только специфичные для swap-all.

# --- Параметры свапа ---
# Жёсткий floor резерва ETH (Polygon zkEVM) на газ. 0 = свапать максимально
# под ноль (резерв вычисляется динамически: gas_price × 30k × 2 safety —
# обычно ~0.00003 ETH). Поставьте >0 (например 0.00005) если хотите
# гарантированный минимум независимо от gas_price.
NATIVE_GAS_RESERVE_ETH = 0
ARRIVAL_TIMEOUT_SEC = 25 * 60     # Таймаут ожидания прихода средств в Base (сек)
LAYERSWAP_POLL_INTERVAL = 15      # Период опроса Layerswap по статусу свапа (сек)
TX_RECEIPT_TIMEOUT_SEC = 600      # Таймаут ожидания подтверждения on-chain tx (сек)

# --- API ---
LAYERSWAP_API_KEY = ''            # Опциональный X-LS-APIKEY (если пусто — без ключа)
