# Словарь с обновлёнными данными
explorers = {
    '🚀 Ethereum Mainnet': {'symbol': 'ETH', 'tx_url': "https://etherscan.io/tx/"},
    '🚀 Base': {'symbol': 'ETH', 'tx_url': "https://basescan.org/tx/"},
    '🚀 Arbitrum One': {'symbol': 'ETH', 'tx_url': "https://arbiscan.io/tx/"},
    '🚀 Optimism': {'symbol': 'ETH', 'tx_url': "https://optimistic.etherscan.io/tx/"},
    '🚀 Soneium': {'symbol': 'ETH', 'tx_url': "https://soneium.blockscout.com/tx/"},
    '🚀 Polygon': {'symbol': 'MATIC', 'tx_url': "https://polygonscan.com/tx/"},
    '🚀 Binance Smart Chain': {'symbol': 'BNB', 'tx_url': "https://bscscan.com/tx/"},
    '🚀 Avalanche': {'symbol': 'AVAX', 'tx_url': "https://subnets.avax.network/p-chain/tx/"},
    '🚀 Fantom': {'symbol': 'FTM', 'tx_url': "https://explorer.fantom.network/transactions/"},
    '🚀 Gravity Alpha Mainnet (сеть Gravity )': {'symbol': 'G', 'tx_url': "https://explorer.gravity.xyz/tx/"},
    '🚀 Zora': {'symbol': 'ETH', 'tx_url': "https://explorer.zora.energy/tx/"},
    '🚀 Abstract': {'symbol': 'ETH', 'tx_url': "https://explorer.testnet.abs.xyz/tx/"},
    '🚀 Sepolia': {'symbol': 'ETH', 'tx_url': "https://sepolia.etherscan.io/tx/"},
    '🚀 Monad Testnet (native token MON)': {'symbol': 'MON', 'tx_url': "https://testnet.monvision.io/tx/"},
    '🚀 Kite Testnet': {'symbol': 'KITE', 'tx_url': "https://testnet.kitescan.ai/tx/"},
    '🚀 Somnia': {'symbol': 'SOMI', 'tx_url': "https://explorer.somnia.network/tx/"},
    '🚀 Mega ETH': {'symbol': 'ETH', 'tx_url': "https://www.oklink.com/ru/megaeth-testnet/tx/"},
    '🚀 Pharos Testnet': {'symbol': 'ETH', 'tx_url': "https://testnet.pharosscan.xyz/tx/"},
}

def get_explorer_url(network):
    """
    Возвращает URL обозревателя (tx_url) для указанной сети.
    Сохраняет обратную совместимость с предыдущей версией.
    
    Args:
        network (str): Название сети
        
    Returns:
        str: URL обозревателя или сообщение об ошибке
    """
    data = explorers.get(network)
    if data is not None:
        return data['tx_url']
    return "ошибка получения explorer URL для сети: "

def get_network_symbol(network):
    """
    Возвращает символ нативного токена для указанной сети.
    
    Args:
        network (str): Название сети
        
    Returns:
        str: Символ токена или 'ETH' по умолчанию
    """
    data = explorers.get(network)
    if data is not None:
        return data['symbol']
    return 'ETH'  # По умолчанию возвращаем ETH

def get_network_info(network):
    """
    Возвращает полную информацию о сети (символ токена и URL обозревателя).
    
    Args:
        network (str): Название сети
        
    Returns:
        dict: Словарь с ключами 'symbol' и 'tx_url' или None если сеть не найдена
    """
    return explorers.get(network)

def get_all_networks():
    """
    Возвращает список всех доступных сетей.
    
    Returns:
        list: Список названий сетей
    """
    return list(explorers.keys())