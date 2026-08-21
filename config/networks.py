NETWORKS = {
    # === MAINNET СЕТИ ===
    '🚀 Ethereum Mainnet': {
        'rpc_urls': ["https://rpc.flashbots.net"],
        'symbol': 'ETH',
        'tx_url': "https://etherscan.io/tx/",
        'type': 'mainnet'
    },
    '🚀 Base': {
        'rpc_urls': ['https://mainnet.base.org', 'https://base-rpc.publicnode.com'],
        'symbol': 'ETH',
        'tx_url': "https://basescan.org/tx/",
        'type': 'mainnet'
    },
    '🚀 Arbitrum One': {
        'rpc_urls': [
            'https://arbitrum.drpc.org',
            'https://arb1.arbitrum.io/rpc',
            'https://arbitrum-one.publicnode.com',
            'https://1rpc.io/arb',
        ],
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
        'rpc_urls': [
            'https://bsc-dataseed.bnbchain.org',
            'https://bsc-dataseed1.binance.org',
            'https://bsc-dataseed2.binance.org',
            'https://bsc.publicnode.com',
            'https://bsc-rpc.publicnode.com',
            'https://1rpc.io/bnb',
            'https://bsc.meowrpc.com',
            'https://bsc-dataseed1.defibit.io',
            'https://bsc-dataseed1.ninicoin.io',
        ],
        'symbol': 'BNB',
        'tx_url': "https://bscscan.com/tx/",
        'chain_id': 56,
        'type': 'mainnet'
    },
    '🚀 Sahara AI': {
        'rpc_urls': [
            'https://mainnet.saharalabs.ai',
        ],
        'symbol': 'SAHARA',
        'tx_url': "https://explorer.saharalabs.ai/tx/",
        'chain_id': 3132023,
        'type': 'mainnet'
    },
    '🚀 Avalanche C-Chain': {
        'rpc_urls': [
            'https://api.avax.network/ext/bc/C/rpc',
            'https://avalanche-c-chain-rpc.publicnode.com',
            'https://avalanche.drpc.org',
        ],
        'symbol': 'AVAX',
        'tx_url': "https://snowtrace.io/tx/",
        'chain_id': 43114,
        'type': 'mainnet'
    },
    '🚀 Core DAO': {
        'rpc_urls': [
            'https://rpc.coredao.org',
            'https://core.drpc.org',
            'https://1rpc.io/core',
            'https://rpc-core.icecreamswap.com',
        ],
        'symbol': 'CORE',
        'tx_url': "https://scan.coredao.org/tx/",
        'chain_id': 1116,
        'type': 'mainnet'
    },
    '🚀 Kava': {
        'rpc_urls': [
            'https://evm.kava.io',
            'https://evm.kava-rpc.com',
            'https://kava-evm.publicnode.com',
            'https://kava.drpc.org',
        ],
        'symbol': 'KAVA',
        'tx_url': "https://kavascan.com/tx/",
        'chain_id': 2222,
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
        # Здесь по ошибке (копипаста из Manta Pacific ниже) стоял explorer Manta,
        # из-за чего каждая ссылка на транзакцию MONAD вела в чужую сеть.
        # RPC выше отдаёт chain_id 0x8f (143) — это mainnet, поэтому берём
        # mainnet-explorer из документации Monad, а не testnet-овый monadexplorer.com.
        'tx_url': "https://monadscan.com/tx/",
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
    '🚀 Polygon zkEVM': {
        'rpc_urls': [
            'https://zkevm-rpc.com',
            'https://polygon-zkevm.drpc.org',
            'https://1rpc.io/polygon/zkevm',
        ],
        'symbol': 'ETH',
        'tx_url': "https://zkevm.polygonscan.com/tx/",
        'chain_id': 1101,
        'oklink_chain': 'polygon_zkevm',
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
    '🚀 LiteForge Testnet': {
        'chain_id': 4441,
        'rpc_urls': ['https://liteforge.rpc.caldera.xyz/http'],
        'ws_urls': ['wss://liteforge.rpc.caldera.xyz/ws'],
        'symbol': 'zkLTC',
        'tx_url': "https://liteforge.explorer.caldera.xyz/tx/",
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

# Сети, помеченные как закрытые — отображаются с красным бейджем «сеть закрылась»
# по аналогии с бейджем «ПАУЗА» в config/menu_config.py.
CLOSED_NETWORKS = {'🚀 Polygon zkEVM'}

# Стиль красного бейджа должен совпадать с config/menu_config.py (_BADGE_RED)
_BADGE_RED = "\033[41m\033[97;1m {text} \033[0m"


def get_network_display_name(network_name: str):
    """Имя сети для отображения в select-меню.

    Для сетей из CLOSED_NETWORKS добавляется красный бейдж
    «сеть закрылась» (тот же стиль, что и «ПАУЗА» у MenuItem).
    Возвращаемое значение используется только как label —
    значение Choice по-прежнему должно быть оригинальным ключом сети.

    Возвращает либо строку (если сеть не закрыта), либо FormattedText
    (для закрытых сетей) — обе формы корректно принимает меню из modules/ui.
    Без обёртки ANSI-escape байты рендерятся литерально (^[[41m...).
    """
    if network_name not in CLOSED_NETWORKS:
        return network_name

    raw = f"{network_name}  " + _BADGE_RED.format(text='сеть закрылась')
    try:
        from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    except ImportError:
        return raw
    return to_formatted_text(ANSI(raw))


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
Avalanche = NETWORKS['🚀 Avalanche C-Chain']['rpc_urls']
core_dao = NETWORKS['🚀 Core DAO']['rpc_urls']
kava = NETWORKS['🚀 Kava']['rpc_urls']
Fantom = NETWORKS['🚀 Fantom']['rpc_urls']
Gravity_Alpha_Mainnet = NETWORKS['🚀 Gravity Alpha Mainnet (сеть Gravity )']['rpc_urls']
zora = NETWORKS['🚀 Zora']['rpc_urls']
Abstract = NETWORKS['🚀 Abstract']['rpc_urls']
somnia = NETWORKS['🚀 Somnia']['rpc_urls']

# Provide uppercase alias for Base
BASE = base

# Тестнет-алиасы. Модули вывода с бирж (okx/mexc/binance_withdraw) собирают словарь
# chain_mapping целиком, ещё до вызова .get(), поэтому отсутствие любого из этих имён
# роняло AttributeError на ЛЮБОЙ сети, а не только на тестнете: вывод с OKX, MEXC и
# Binance не работал вообще. Bitget уцелел лишь потому, что тестнетов в его словаре нет.
sepolia = NETWORKS['🚀 Sepolia']['rpc_urls']
pharos_testnet = NETWORKS['🚀 Pharos Testnet']['rpc_urls']

# Kite и MegaETH в NETWORKS не заведены, а публичный RPC подбирать наугад нельзя.
# Пустой список — честный вариант: перебор RPC просто не находит рабочего узла и
# get_working_web3_connection возвращает None с понятной ошибкой в логе.
# Чтобы включить сеть — добавьте её в NETWORKS и замените [] на её rpc_urls.
kite_testnet = []
mega_eth_testnet = []
