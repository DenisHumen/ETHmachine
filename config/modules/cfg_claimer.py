# ========================================================================================
# НАСТРОЙКИ МОДУЛЯ CLAIMER (Zora Protocol Rewards)
# ========================================================================================
# Клейм наград протокола Zora на сетях Base и Zora

# Минимальная сумма для клейма (в ETH). Если баланс меньше - пропускаем
MIN_CLAIM_AMOUNT_ETH = 0.0000044

# Минимальный баланс ETH на кошельке для оплаты газа
# На L2 (Base/Zora) газ очень дешевый (~0.0000002 ETH за клейм), поэтому порог низкий
MIN_GAS_BALANCE_ETH = 0.0000003

# Использовать прокси
CLAIMER_USE_PROXY = True

# Случайный прокси (True) или по порядку (False)
CLAIMER_RANDOM_PROXY = True

# Перемешивать список кошельков
CLAIMER_SHUFFLE_WALLETS = True

# Сети для проверки клеймов
CLAIMER_NETWORKS = {
    'base': {
        'enabled': True,
        'rpc_urls': ['https://mainnet.base.org', 'https://base-rpc.publicnode.com', 'https://base.llamarpc.com'],
        'chain_id': 8453,
        'explorer_tx': 'https://basescan.org/tx/',
        'symbol': 'ETH',
        'name': 'Base',
    },
    'zora': {
        'enabled': True,
        'rpc_urls': ['https://rpc.zora.energy'],
        'chain_id': 7777777,
        'explorer_tx': 'https://explorer.zora.energy/tx/',
        'symbol': 'ETH',
        'name': 'Zora',
    },
}

# Адрес контракта Zora ProtocolRewards (одинаковый на всех сетях)
PROTOCOL_REWARDS_CONTRACT = '0x7777777F279eba3d3Ad8F4E708545291A6fDBA8B'

# Клеймить на тот же адрес кошелька (True) или на указанный CLAIM_TO_ADDRESS (False)
CLAIM_TO_SELF = True

# Адрес для вывода наград (если CLAIM_TO_SELF = False)
CLAIM_TO_ADDRESS = ''
