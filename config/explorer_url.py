def get_explorer_url(network):
    explorers = {
        '🚀 Ethereum Mainnet': "https://etherscan.io/tx/",
        '🚀 Base': "https://basescan.org/tx/",
        '🚀 Arbitrum One': "https://arbiscan.io/tx/",
        '🚀 Optimism': "https://optimistic.etherscan.io/tx/",
        '🚀 Soneium': "https://soneium.blockscout.com/tx/",
        '🚀 Polygon': "https://polygonscan.com/tx/",
        '🚀 Binance Smart Chain': "https://bscscan.com/tx/",
        '🚀 Avalanche': "https://subnets.avax.network/p-chain/tx/",
        '🚀 Fantom': "https://explorer.fantom.network/transactions/",
        '🚀 Gravity Alpha Mainnet': "https://explorer.gravity.xyz/tx/",
        '🚀 Zora': "https://explorer.zora.energy/tx/",
        '🚀 Abstract': "https://explorer.testnet.abs.xyz/tx/",
        '🚀 Sepolia': "https://sepolia.etherscan.io/tx/",
        '🚀 Monad Testnet (native token MON)': "https://testnet.monvision.io/tx/",
        '🚀 Sahara testnet': "https://testnet-explorer.saharalabs.ai/tx/",
        '🚀 Somnia Testnet': "https://shannon-explorer.somnia.network/tx/",
        '🚀 Mega ETH': "https://www.oklink.com/ru/megaeth-testnet/tx/",
        '🚀 Pharos': "https://testnet.pharosscan.xyz/tx/",
    }
    return explorers.get(network, "ошибка получения explorer URL для сети: ")