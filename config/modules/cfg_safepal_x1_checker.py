"""Конфиг модуля SafePal X1 Eligibility Checker.

URL вида: https://www.safepal.com/en/claimX1/v2/#/v/<ACT_CODE>/<CHANNEL_CODE>
"""

# Кампания (из URL ?v/<actCode>/<channelCode>).
ACT_CODE = "party100912"
CHANNEL_CODE = "w7xv4u"

# EVM chainId для подписи. Чекер на стороне SafePal не привязан к конкретной сети
# (chainType=0 для этой кампании — «любая EVM»). По умолчанию используем Ethereum.
# Допустимые значения по UI: 1 (ETH), 56 (BSC), 42161 (ARB), 137 (POLY), 10 (OP), 43114 (AVAX).
CHAIN_ID = 1

# Таймаут на каждый HTTP-вызов SafePal API, секунды.
HTTP_TIMEOUT = 30
