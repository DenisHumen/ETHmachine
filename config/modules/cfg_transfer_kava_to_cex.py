"""Конфигурация модуля transfer_kava_to_cex.

Все «общие» параметры (NUM_THREADS, RETRY_COUNT и т.п.) берутся из
config.modules.general_config; здесь — только module-specific.

ВАЖНО: модуль отправляет нативный KAVA через Cosmos SDK `MsgSend` на
bech32 адрес `kava1...`. Это требуется для CEX-депозитов: индексаторы
бирж на Kava слушают Cosmos bank-события, а не EVM Transfer-логи.
EVM RPC используется только для совместимости (parse_proxy и др.);
сами транзакции идут через Kava REST LCD.
"""

# EVM-сеть из config.networks.NETWORKS — НЕ используется для отправки,
# но оставлен для совместимости (proxy_manager, network_name в логах).
NETWORK_NAME = "🚀 Kava"
NATIVE_SYMBOL = "KAVA"
NATIVE_DECIMALS_EVM = 18         # akava (EVM-side, для отображения)
NATIVE_DECIMALS_COSMOS = 6       # ukava (Cosmos-side, на чём считаем суммы)
CHAIN_ID_EVM = 2222

# ─── Cosmos / Kava SDK параметры ─────────────────────────────────────────
COSMOS_CHAIN_ID = "kava_2222-10"
COSMOS_DENOM = "ukava"                     # 1 KAVA = 1_000_000 ukava
COSMOS_LCD_URLS = [
    "https://api.data.kava.io",
    "https://kava-api.polkachu.com",
]
# Газ-параметры для Cosmos MsgSend.
# Минимальная gas-price на Kava обычно 0.001..0.025 ukava/gas;
# берём 0.05 с запасом — это ~0.005 KAVA на tx (≈ копейки).
COSMOS_GAS_PRICE_UKAVA = 0.05
COSMOS_GAS_LIMIT = 200_000
# fee_amount_ukava = ceil(GAS_LIMIT * GAS_PRICE)
# = 200000 * 0.05 = 10000 ukava = 0.01 KAVA на одну отправку

# Broadcast / polling
BROADCAST_MODE = "BROADCAST_MODE_SYNC"
TX_POLL_INTERVAL_SEC = 4          # ждём появления tx в блоке
TX_POLL_TIMEOUT_SEC = 90          # сколько ждём пока tx попадёт в блок

# Сколько ждать поступления (увеличение Cosmos bank-balance dst) в секундах.
ARRIVAL_TIMEOUT_SEC = 5 * 60

# Интервал между проверками dst-баланса
ARRIVAL_POLL_INTERVAL_SEC = 6

# Резерв на fee при отправке «100%».
# Multi-fee fee_estimate (мы знаем fee точно), плюс небольшой запас.
GAS_RESERVE_MULTIPLIER = 1.3

# Минимальный остаток src в ukava после перевода. 0 = отдать всё кроме fee.
MIN_KEEP_UKAVA = 0

# Минимальный баланс, при котором задача создаётся (в KAVA). Ниже — skipped.
MIN_TRANSFER_AMOUNT_KAVA = 0.01

# Если True — после halt при следующем запуске пробуем ОДИН probe-кошелёк
# (следующий по очереди). Если он успешен — продолжаем; нет — снова halt.
PROBE_NEXT_ON_RESUME = True

# Override для тестов: если задано (>0), это абсолютная сумма в KAVA,
# которую модуль отправит вне зависимости от transfer_amount_spec.
# 0 / None = использовать спецификацию из CSV.
TEST_OVERRIDE_AMOUNT_KAVA = 0.0
