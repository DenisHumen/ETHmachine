NETWORKS = {
    # === MAINNET СЕТИ ===
    '🚀 Ethereum Mainnet': {
        'rpc_urls': ["https://eth.merkle.io", 'https://eth.llamarpc.com', 'https://rpc.mevblocker.io', 
                     'https://eth.drpc.org', 'https://rpc.payload.de', 'https://eth.blockrazor.xyz'],
        'symbol': 'ETH',
        'tx_url': "https://etherscan.io/tx/",
        'type': 'mainnet'
    },
    '🚀 Base': {
        'rpc_urls': ["https://base.llamarpc.com", 'https://base-rpc.publicnode.com'],
        'symbol': 'ETH',
        'tx_url': "https://basescan.org/tx/",
        'type': 'mainnet'
    },
    '🚀 Arbitrum One': {
        'rpc_urls': ['https://arbitrum.drpc.org'],
        'symbol': 'ETH',
        'tx_url': "https://arbiscan.io/tx/",
        'type': 'mainnet'
    },
    '🚀 Optimism': {
        'rpc_urls': ['https://optimism-rpc.publicnode.com', 'https://optimism.drpc.org'],
        'symbol': 'ETH',
        'tx_url': "https://optimistic.etherscan.io/tx/",
        'type': 'mainnet'
    },
    '🚀 Soneium': {
        'rpc_urls': ['https://rpc.soneium.org', 'https://soneium.drpc.org'],
        'symbol': 'ETH',
        'tx_url': "https://soneium.blockscout.com/tx/",
        'type': 'mainnet'
    },
    '🚀 Polygon': {
        'rpc_urls': ['https://1rpc.io/matic'],
        'symbol': 'MATIC',
        'tx_url': "https://polygonscan.com/tx/",
        'type': 'mainnet'
    },
    '🚀 Binance Smart Chain': {
        'rpc_urls': ['https://bsc.meowrpc.com'],
        'symbol': 'BNB',
        'tx_url': "https://bscscan.com/tx/",
        'type': 'mainnet'
    },
    '🚀 Avalanche': {
        'rpc_urls': ['https://avax-pokt.nodies.app/ext/bc/C/rpc', 'https://avax.meowrpc.com', 'https://1rpc.io/avax/c'],
        'symbol': 'AVAX',
        'tx_url': "https://subnets.avax.network/p-chain/tx/",
        'type': 'mainnet'
    },
    '🚀 Fantom': {
        'rpc_urls': ['https://fantom.drpc.org', 'https://fantom-pokt.nodies.app', 'https://rpcapi.fantom.network'],
        'symbol': 'FTM',
        'tx_url': "https://explorer.fantom.network/transactions/",
        'type': 'mainnet'
    },
    '🚀 Gravity Alpha Mainnet (сеть Gravity )': {
        'rpc_urls': ['https://rpc.gravity.xyz', 'https://rpc.ankr.com/gravity'],
        'symbol': 'G',
        'tx_url': "https://explorer.gravity.xyz/tx/",
        'type': 'mainnet'
    },
    '🚀 Zora': {
        'rpc_urls': ['https://rpc.zora.energy'],
        'symbol': 'ETH',
        'tx_url': "https://explorer.zora.energy/tx/",
        'type': 'mainnet'
    },
    '🚀 Abstract': {
        'rpc_urls': ['https://api.mainnet.abs.xyz'],
        'symbol': 'ETH',
        'tx_url': "https://explorer.testnet.abs.xyz/tx/",
        'type': 'mainnet'
    },
    '🚀 Somnia': {
        'rpc_urls': ['https://api.infra.mainnet.somnia.network/'],
        'symbol': 'SOMI',
        'tx_url': "https://explorer.somnia.network/tx/",
        'type': 'mainnet'
    },
    
    # === TESTNET СЕТИ ===
    '🚀 Sepolia': {
        'rpc_urls': ['https://1rpc.io/sepolia'],
        'symbol': 'ETH',
        'tx_url': "https://sepolia.etherscan.io/tx/",
        'type': 'testnet'
    },
    '🚀 Mega ETH Testnet': {
        'rpc_urls': ['https://carrot.megaeth.com/rpc'],
        'symbol': 'ETH',
        'tx_url': "https://www.oklink.com/ru/megaeth-testnet/tx/",
        'type': 'testnet'
    },
    '🚀 Pharos Testnet': {
        'rpc_urls': ['https://testnet.dplabs-internal.com'],
        'symbol': 'ETH',
        'tx_url': "https://testnet.pharosscan.xyz/tx/",
        'type': 'testnet'
    },
    '🚀 Kite Testnet': {
        'rpc_urls': ['https://rpc-testnet.gokite.ai'],
        'symbol': 'KITE',
        'tx_url': "https://testnet.kitescan.ai/tx/",
        'type': 'testnet'
    },
    '🚀 Neura Testnet': {
        'rpc_urls': ['https://testnet.rpc.neuraprotocol.io'],
        'symbol': 'ANKR',
        'tx_url': "https://testnet-blockscout.infra.neuraprotocol.io/tx/",
        'type': 'testnet'
    },
    '🚀 Nexus Testnet': {
        'rpc_urls': ['https://testnet.rpc.nexus.xyz'],
        'symbol': 'NEX',
        'tx_url': "https://nexus.testnet.blockscout.com/tx/",
        'type': 'testnet'
    },
}


# === ФУНКЦИИ ДЛЯ ПОЛУЧЕНИЯ ДАННЫХ ===

def get_all_networks():
    """
    Возвращает список всех доступных сетей
    
    Returns:
        list: Список названий сетей
    """
    return list(NETWORKS.keys())


def get_mainnet_networks():
    """
    Возвращает словарь только mainnet сетей
    
    Returns:
        dict: {network_name: rpc_urls}
    """
    return {name: data['rpc_urls'] for name, data in NETWORKS.items() if data['type'] == 'mainnet'}


def get_testnet_networks():
    """
    Возвращает словарь только testnet сетей
    
    Returns:
        dict: {network_name: rpc_urls}
    """
    return {name: data['rpc_urls'] for name, data in NETWORKS.items() if data['type'] == 'testnet'}


def get_network_rpc_urls(network_name):
    """
    Возвращает список RPC URLs для указанной сети
    
    Args:
        network_name (str): Название сети
        
    Returns:
        list: Список RPC URLs или пустой список
    """
    network = NETWORKS.get(network_name)
    return network['rpc_urls'] if network else []


def get_network_symbol(network_name):
    """
    Возвращает символ нативного токена для указанной сети
    
    Args:
        network_name (str): Название сети
        
    Returns:
        str: Символ токена или 'ETH' по умолчанию
    """
    network = NETWORKS.get(network_name)
    return network['symbol'] if network else 'ETH'


def get_explorer_url(network_name):
    """
    Возвращает URL обозревателя (tx_url) для указанной сети
    
    Args:
        network_name (str): Название сети
        
    Returns:
        str: URL обозревателя или сообщение об ошибке
    """
    network = NETWORKS.get(network_name)
    if network:
        return network['tx_url']
    return "ошибка получения explorer URL для сети: "


def get_network_info(network_name):
    """
    Возвращает полную информацию о сети
    
    Args:
        network_name (str): Название сети
        
    Returns:
        dict: Словарь с ключами 'rpc_urls', 'symbol', 'tx_url', 'type' или None
    """
    return NETWORKS.get(network_name)


def get_network_type(network_name):
    """
    Определяет тип сети (mainnet/testnet)
    
    Args:
        network_name (str): Название сети
        
    Returns:
        str: 'mainnet' или 'testnet' или None
    """
    network = NETWORKS.get(network_name)
    return network['type'] if network else None


def is_mainnet_network(network_name):
    """
    Проверяет, является ли сеть mainnet
    
    Args:
        network_name (str): Название сети
        
    Returns:
        bool: True если mainnet, False если testnet или не найдено
    """
    return get_network_type(network_name) == 'mainnet'


# === ОБРАТНАЯ СОВМЕСТИМОСТЬ ===
# Для совместимости со старым кодом создаем переменные

# Старые переменные из rpc.py (для обратной совместимости)
L1 = NETWORKS['🚀 Ethereum Mainnet']['rpc_urls']
base = NETWORKS['🚀 Base']['rpc_urls']
arbitrum = NETWORKS['🚀 Arbitrum One']['rpc_urls']
optimism = NETWORKS['🚀 Optimism']['rpc_urls']
soneium = NETWORKS['🚀 Soneium']['rpc_urls']
Polygon = NETWORKS['🚀 Polygon']['rpc_urls']
Binance_Smart_Chain = NETWORKS['🚀 Binance Smart Chain']['rpc_urls']
Avalanche = NETWORKS['🚀 Avalanche']['rpc_urls']
Fantom = NETWORKS['🚀 Fantom']['rpc_urls']
Gravity_Alpha_Mainnet = NETWORKS['🚀 Gravity Alpha Mainnet (сеть Gravity )']['rpc_urls']
zora = NETWORKS['🚀 Zora']['rpc_urls']
Abstract = NETWORKS['🚀 Abstract']['rpc_urls']
somnia = NETWORKS['🚀 Somnia']['rpc_urls']

sepolia = NETWORKS['🚀 Sepolia']['rpc_urls']
mega_eth_testnet = NETWORKS['🚀 Mega ETH Testnet']['rpc_urls']
pharos_testnet = NETWORKS['🚀 Pharos Testnet']['rpc_urls']
kite_testnet = NETWORKS['🚀 Kite Testnet']['rpc_urls']
neura_testnet = NETWORKS['🚀 Neura Testnet']['rpc_urls']
nexus_testnet = NETWORKS['🚀 Nexus Testnet']['rpc_urls']

# Старый словарь explorers (для обратной совместимости)
explorers = {name: {'symbol': data['symbol'], 'tx_url': data['tx_url']} 
             for name, data in NETWORKS.items()}
