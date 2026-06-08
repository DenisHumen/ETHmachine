# ========================================================================================
# SAHARA AI — Knowledge Drop / Earndrop клеймер
# ========================================================================================
# Сайт:  https://knowledgedrop.saharaai.com
# API:   https://earndrop.prd.galaxy.eco
# Сеть claim: BSC (chain_id=56), оплата claim_fee в BNB.
# Токен SAHARA (BEP-20): 0xfdffb411c4a70aa7c95d5c981a6fb4da867e1111
#
# Параметры NUM_THREADS / SLEEP_BETWEEN_ACTIONS / DELAY_BETWEEN_ACCOUNTS /
# TX_SEND_ATTEMPTS / RETRY_COUNT / SHUFLE_ACCOUNTS / WHAITE_TRANSACTION_PENDING* —
# берутся из config/modules/general_config.py (общие для всех модулей).

# ----------------------------------------------------------------------------------------
# Главный переключатель авто-вывода
# ----------------------------------------------------------------------------------------
# True  — сразу после успешного claim переводить SAHARA на evm_cex_address из data.csv
#         (для каждого кошелька — свой адрес «суба»).
# False — только claim, без перевода.
AUTO_WITHDRAW_TO_CEX = False

# Если evm_cex_address у конкретного кошелька пустой — авто-вывод пропускается
# (даже когда AUTO_WITHDRAW_TO_CEX = True). Это безопасное поведение по умолчанию.

# ----------------------------------------------------------------------------------------
# Параметры on-chain (BSC)
# ----------------------------------------------------------------------------------------
CHAIN_KEY = '🚀 Binance Smart Chain'   # ключ в config/networks.NETWORKS
CHAIN_ID = 56

SAHARA_TOKEN_ADDRESS = '0xfdffb411c4a70aa7c95d5c981a6fb4da867e1111'  # BEP-20 SAHARA

# Минимум BNB, который должен остаться на кошельке после claim+withdraw (для будущего газа).
# Не трогаем оставшийся BNB — переводим только SAHARA.
MIN_BNB_FOR_GAS = 0.0005

# ----------------------------------------------------------------------------------------
# Ожидание зачисления на кошелёк (после on-chain claim)
# ----------------------------------------------------------------------------------------
CLAIM_BALANCE_WAIT_TIMEOUT = 180       # секунд — общий таймаут
CLAIM_BALANCE_POLL_INTERVAL = 6        # секунд между проверками balanceOf

# ----------------------------------------------------------------------------------------
# Ожидание зачисления на CEX-адрес (после withdraw-перевода)
# ----------------------------------------------------------------------------------------
WITHDRAW_BALANCE_WAIT_TIMEOUT = 300
WITHDRAW_BALANCE_POLL_INTERVAL = 10

# ----------------------------------------------------------------------------------------
# Earndrop API
# ----------------------------------------------------------------------------------------
EARNDROP_API_BASE = 'https://earndrop.prd.galaxy.eco'
SITE_DOMAIN = 'knowledgedrop.saharaai.com'
SITE_ORIGIN = 'https://knowledgedrop.saharaai.com'
SIWE_STATEMENT = 'Sign in with Ethereum to the app.'

# Request timeouts
HTTP_TIMEOUT = 30
