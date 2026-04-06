NETWORKS = {
    # === MAINNET СЕТИ ===
    '🚀 Ethereum Mainnet': {
        'rpc_urls': ["https://rpc.flashbots.net"],
        'symbol': 'ETH',
        'tx_url': "https://etherscan.io/tx/",
        'type': 'mainnet'
    },
    '🚀 Base': {
        'rpc_urls': ['https://mainnet.base.org', 'https://base-rpc.publicnode.com', 'https://base.llamarpc.com'],
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
    '🚀 Arbitrum Nova': {
        'rpc_urls': ['https://arbitrum-nova-rpc.publicnode.com'],
        'symbol': 'ETH',
        'tx_url': "https://nova-explorer.arbitrum.io/tx/",
        'chain_id': 42170,
        'type': 'mainnet'
    },
    '🚀 Optimism': {
        'rpc_urls': ['https://public-op-mainnet.fastnode.io'],
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
        'rpc_urls': ['https://binance.llamarpc.com'],
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
        'rpc_urls': ['https://abstract.drpc.org', 'https://api.mainnet.abs.xyz'],
        'symbol': 'ETH',
        'tx_url': "https://explorer.mainnet.abs.xyz/tx/",
        'type': 'mainnet'
    },
    '🚀 Somnia': {
        'rpc_urls': ['https://api.infra.mainnet.somnia.network/'],
        'symbol': 'SOMI',
        'tx_url': "https://explorer.somnia.network/tx/",
        'type': 'mainnet'
    },    
    '🚀 Linea': {
        'rpc_urls': ['https://linea.drpc.org', 'https://1rpc.io/linea'],
        'symbol': 'ETH',
        'tx_url': "https://lineascan.build/tx/",
        'type': 'mainnet'
    },
    '🚀 zkSync Era': {
        'rpc_urls': ['https://mainnet.era.zksync.io'],
        'symbol': 'ETH',
        'tx_url': "https://explorer.zksync.io/tx/",
        'type': 'mainnet'
    },
    '🚀 MONAD': {
        'rpc_urls': ['https://infra.originstake.com/monad/evm'],
        'symbol': 'MON',
        'tx_url': "https://pacific-explorer.manta.network/tx/",
        'type': 'mainnet'
    },
    '🚀 Manta Pacific Mainnet': {
        'rpc_urls': ['https://pacific-rpc.manta.network/http'],
        'symbol': 'ETH',
        'tx_url': "https://explorer.manta.network/tx/",
        'type': 'mainnet'
    },
    '🚀 ApeChain': {
        'rpc_urls': ['https://apechain.drpc.org'],
        'symbol': 'APE',
        'tx_url': "https://apescan.io/tx/",
        'type': 'mainnet'
    },
    
    # === TESTNET СЕТИ ===
    '🚀 Sepolia': {
        'rpc_urls': ['https://1rpc.io/sepolia'],
        'symbol': 'ETH',
        'tx_url': "https://sepolia.etherscan.io/tx/",
        'type': 'testnet'
    },
    '🚀 Pharos Testnet': {
        'rpc_urls': ['https://atlantic.dplabs-internal.com'],
        'symbol': 'ETH',
        'tx_url': "https://atlantic.pharosscan.xyz/tx/",
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
    '🚀 ARC Testnet': {
        'chain_id': 5042002,
        'rpc_urls': ['https://rpc.testnet.arc.network'],
        'symbol': 'USDC',
        'tx_url': "https://testnet.arcscan.app/tx/",
        'type': 'testnet'
    },
}

SOL_NETWORKS = {
    '🚀 Solana Mainnet': {
        'rpc_urls': ['https://api.mainnet-beta.solana.com'],
        'symbol': 'SOL',
        'tx_url': "https://solscan.io/tx/",
        'type': 'mainnet'
    },
        '🚀 Eclipse Mainnet': {
        'rpc_urls': ['https://mainnetbeta-rpc.eclipse.xyz'],
        'symbol': 'ETH',
        'tx_url': "https://eclipsescan.xyz/tx/",
        'type': 'mainnet'
    },
}

# === ФУНКЦИИ ДЛЯ ПОЛУЧЕНИЯ ДАННЫХ ===

def get_all_networks():
    return list(NETWORKS.keys())


def get_mainnet_networks():
    return {name: data['rpc_urls'] for name, data in NETWORKS.items() if data['type'] == 'mainnet'}


def get_testnet_networks():
    return {name: data['rpc_urls'] for name, data in NETWORKS.items() if data['type'] == 'testnet'}


def get_network_rpc_urls(network_name):
    network = NETWORKS.get(network_name)
    return network['rpc_urls'] if network else []


def get_network_symbol(network_name):
    network = NETWORKS.get(network_name)
    return network['symbol'] if network else 'ETH'


def get_explorer_url(network_name):
    network = NETWORKS.get(network_name)
    if network:
        return network['tx_url']
    return "ошибка получения explorer URL для сети: "


def get_network_info(network_name):
    return NETWORKS.get(network_name)


def get_network_type(network_name):
    network = NETWORKS.get(network_name)
    return network['type'] if network else None



# === ОБРАТНАЯ СОВМЕСТИМОСТЬ ===
# Для совместимости со старым кодом создаем переменные

# Старые переменные из rpc.py (для обратной совместимости)
# Backwards-compatible RPC variables (used by older modules)
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

# Provide uppercase alias for Base
BASE = base
