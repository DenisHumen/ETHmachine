# ========================================================================================
# НАСТРОЙКИ RELAY LINK
# ========================================================================================

# Адреса токенов по сетям
TOKEN_ADDRESSES = {
    1: {  # Ethereum
        "ETH": "0x0000000000000000000000000000000000000000",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC": "0xA0b86a33E6441446FF2EAE9f6c6B0DfEc9E8Ca51"
    },
    10: {  # Optimism
        "ETH": "0x0000000000000000000000000000000000000000",
        "USDT": "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58",
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"
    },
    137: {  # Polygon
        "MATIC": "0x0000000000000000000000000000000000000000",
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    },
    8453: {  # Base
        "ETH": "0x0000000000000000000000000000000000000000",
        "USDT": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "USDC": "0xA0b86a33E6441446FF2EAE9f6c6B0DfEc9E8Ca51"
    },
    42161: {  # Arbitrum
        "ETH": "0x0000000000000000000000000000000000000000",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
        "USDC": "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"
    },
    1868: {  # Soneium
        "ETH": "0x0000000000000000000000000000000000000000",
        "USDT": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "USDC": "0xA0b86a33E6441446FF2EAE9f6c6B0DfEc9E8Ca51"
    },
    2741: {  # Abstract
        "ETH": "0x0000000000000000000000000000000000000000"
    },
    169: {  # Manta Pacific Mainnet
        "ETH": "0x0000000000000000000000000000000000000000"
    }
}

# Сопоставление названий сетей с Chain ID
NETWORK_MAPPING = {
    'ethereum': 1,
    'optimism': 10,
    'polygon': 137,
    'base': 8453,
    'arbitrum': 42161,
    'soneium': 1868,
    'abstract': 2741
}

# Reverse mapping для получения названия по ID
CHAIN_ID_TO_NAME = {v: k for k, v in NETWORK_MAPPING.items()}

# Настройки для каждой сети
NETWORK_SETTINGS = {
    1: {
        "name": "Ethereum",
        "native_symbol": "ETH",
        "decimals": 18,
        "min_native_balance": 0.01  # Минимальный баланс для работы
    },
    10: {
        "name": "Optimism",
        "native_symbol": "ETH",
        "decimals": 18,
        "min_native_balance": 0.005
    },
    137: {
        "name": "Polygon",
        "native_symbol": "MATIC",
        "decimals": 18,
        "min_native_balance": 10.0
    },
    8453: {
        "name": "Base",
        "native_symbol": "ETH",
        "decimals": 18,
        "min_native_balance": 0.005
    },
    42161: {
        "name": "Arbitrum",
        "native_symbol": "ETH",
        "decimals": 18,
        "min_native_balance": 0.005
    },
    1868: {
        "name": "Soneium",
        "native_symbol": "ETH",
        "decimals": 18,
        "min_native_balance": 0.005
    },
    2741: {
        "name": "Abstract",
        "native_symbol": "ETH",
        "decimals": 18,
        "min_native_balance": 0.005
    },
    169: {
        "name": "Manta Pacific Mainnet",
        "native_symbol": "ETH",
        "decimals": 18,
        "min_native_balance": 0.005
    }
}

# Минимальные суммы для бриджинга
MINIMUM_BRIDGE_AMOUNTS = {
    "ETH": 0.005,
    "MATIC": 5.0,
    "USDT": 10.0,
    "USDC": 10.0,
}

# Минимальные суммы по парам сетей
NETWORK_PAIR_MINIMUMS = {
    (1, 10): {"ETH": 0.01},
    (1, 137): {"ETH": 0.01},
    (1, 8453): {"ETH": 0.01},
    (1, 42161): {"ETH": 0.01},
    (10, 1): {"ETH": 0.005},
    (10, 137): {"ETH": 0.005},
    (10, 8453): {"ETH": 0.005},
    (10, 42161): {"ETH": 0.005},
    (42161, 1): {"ETH": 0.005},
    (42161, 10): {"ETH": 0.005},
    (42161, 137): {"ETH": 0.005},
    (42161, 8453): {"ETH": 0.005},
    (8453, 1): {"ETH": 0.005},
    (8453, 10): {"ETH": 0.005},
    (8453, 137): {"ETH": 0.005},
    (8453, 42161): {"ETH": 0.005},
    (137, 1): {"MATIC": 10.0},
    (137, 10): {"MATIC": 10.0},
    (137, 8453): {"MATIC": 10.0},
    (137, 42161): {"MATIC": 10.0},
}

# Настройки времени ожидания
BALANCE_CHECK_TIMEOUT = 3600  # 1 час в секундах
BALANCE_CHECK_INTERVAL = 30   # Проверять каждые 30 секунд
TRANSACTION_TIMEOUT = 300     # 5 минут на подтверждение транзакции
