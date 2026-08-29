# ========================================================================================
# НАСТРОЙКИ RELAY LINK
# ========================================================================================
# Пользовательские ручки модуля лежат в config/modules/cfg_relay.py (SUM_TO_RELAY, GAS).
# Здесь — только техническая карта сетей для Relay API. Файл сохранён по старому пути,
# чтобы не ломать импорты, но адреса токенов он больше НЕ хранит.
#
# Почему: раньше тут лежала вторая копия таблицы адресов, разошедшаяся с
# config/token_address_erc20.py (Base USDC был подписан как USDT, а "USDC"
# 0xA0b86a33...Ca51 стоял сразу в трёх сетях и не существует ни в одной).
# Две правды про адреса — это перевод средств в никуда, поэтому адреса берём
# из единственного источника — config/token_address_erc20.py.

from config import token_address_erc20

# Сопоставление названий сетей с Chain ID
NETWORK_MAPPING = {
    'ethereum': 1,
    'optimism': 10,
    'polygon': 137,
    'base': 8453,
    'arbitrum': 42161,
    'arbitrum_nova': 42170,
    'soneium': 1868,
    'abstract': 2741,
    'manta_pacific': 169,
    'linea': 59144,
    'solana': 792703809
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
    42170: {
        "name": "Arbitrum Nova",
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
        "min_native_balance": 0.00004
    },
    59144: {
        "name": "Linea",
        "native_symbol": "ETH",
        "decimals": 18,
        "min_native_balance": 0.005
    },
    792703809: {
        "name": "Solana",
        "native_symbol": "SOL",
        "decimals": 9,
        "min_native_balance": 0.01
    }
}

# ========================================================================================
# АДРЕСА ТОКЕНОВ
# ========================================================================================
# chain_id Solana в Relay API (свой, не EVM-совместимый).
_SOLANA_CHAIN_ID = 792703809

# Relay ждёт нулевой адрес как обозначение нативной монеты сети
NATIVE_TOKEN_ADDRESS = "0x0000000000000000000000000000000000000000"
# У Solana роль "нулевого адреса" играет System Program
SOLANA_NATIVE_MINT = "11111111111111111111111111111111"

# chain_id -> имя переменной в config/token_address_erc20.py.
# Сюда добавляется только имя переменной, сами адреса живут в config/.
# Сети, которых нет в этом словаре (Arbitrum Nova, Manta, Linea), получают
# только нативный токен — так честнее, чем подставлять непроверенный адрес.
_ERC20_CONFIG_VARS = {
    1: 'ethereum_mainnet',
    10: 'optimism',
    137: 'polygon',
    8453: 'base',
    42161: 'arbitrum',
    1868: 'soneium',
    2741: 'abstract',
}


def _build_token_addresses() -> dict:
    """Собрать карту chain_id -> {SYMBOL: address} из config/token_address_erc20.py."""
    result = {}

    for chain_id, settings in NETWORK_SETTINGS.items():
        native_symbol = settings['native_symbol']
        native_address = SOLANA_NATIVE_MINT if chain_id == _SOLANA_CHAIN_ID else NATIVE_TOKEN_ADDRESS
        chain_tokens = {native_symbol: native_address}

        config_var = _ERC20_CONFIG_VARS.get(chain_id)
        if config_var:
            for symbol, address in getattr(token_address_erc20, config_var, {}).items():
                # 'native' — сентинел нативной монеты в config, он уже добавлен выше
                if not address or address == 'native':
                    continue
                chain_tokens.setdefault(symbol.upper(), address)

        result[chain_id] = chain_tokens

    return result


# Адреса токенов по сетям (производная от config/token_address_erc20.py)
TOKEN_ADDRESSES = _build_token_addresses()

# Минимальные суммы для бриджинга
MINIMUM_BRIDGE_AMOUNTS = {
    "ETH": 0.00017,
    "SOL": 0.01,
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
    (137, 42170): {"MATIC": 10.0},
    (42170, 137): {"ETH": 0.005},
    (1, 42170): {"ETH": 0.005},
    (42170, 1): {"ETH": 0.005},
    (42170, 10): {"ETH": 0.005},
    (10, 42170): {"ETH": 0.005},
    (59144, 1): {"ETH": 0.005},
    (1, 59144): {"ETH": 0.01},
    (59144, 10): {"ETH": 0.005},
    (10, 59144): {"ETH": 0.005},
    (59144, 8453): {"ETH": 0.000005},
    (8453, 59144): {"ETH": 0.000005},
    (59144, 42161): {"ETH": 0.005},
    (42161, 59144): {"ETH": 0.005},
}

# Настройки времени ожидания
BALANCE_CHECK_INTERVAL = 20   # Интервал между проверками поступления средств (в секундах)
# Оставлены для обратной совместимости: общий бюджет ожидания моста считается по
# WHAITE_TRANSACTION_PENDING * WHAITE_TRANSACTION_PENDING_COUNT из general_config (AGENTS.md §9.4).
BALANCE_CHECK_TIMEOUT = 3600  # 1 час в секундах (не используется)
TRANSACTION_TIMEOUT = 300     # 5 минут на подтверждение транзакции (не используется)
