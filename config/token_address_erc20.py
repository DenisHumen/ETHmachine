# ========================================================================================
# АДРЕСА ТОКЕНОВ ERC-20 ДЛЯ РАЗНЫХ СЕТЕЙ
# ========================================================================================
# Формат: network_name = {'token_symbol': 'token_address'}
# Название переменной должно совпадать с названием сети из config/rpc.py (в нижнем регистре, пробелы заменены на _)



base = {
    'usdc': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
    'usdt': '0x2d1aDB45Bb1d7D2556c6558aDb76CFD4F9F4ed16',
    'weth': '0x4200000000000000000000000000000000000006',
    'dai': '0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb',
    'cbeth': '0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22',
    'comp': '0x9e1028F5F1D5eDE59748FFceE5532509976840E0',
    'aero': '0x940181a94A35A4569E4529A3CDfB74e38FD98631',
    'bald': '0x27D2DECb4bFC9C76F0309b8E88dec3a601Fe25a8',
    'LMTS': '0x9eadbe35f3ee3bf3e28180070c429298a1b02f93',
}



pharos_testnet = {
    'usdc': '0xad902cf99c2de2f1ba5ec4d642fd7e49cae9ee37',
    'usdt': '0xd4071393f8716661958f766df660033b3d35fd29',
    'wphrs': '0x3019b247381c850ab53dc0ee53bce7a07ea9155f',
    'weth': '0x60184f3f218a28a56ba31cb09363732ef5ec26d6',
    'usdc_1': '0x72df0bcd7276f2dfbac900d1ce63c272c4bccced',
    'usdc_2': '0x48249feeb47a8453023f702f15cf00206eebdf08',
    'usdt_2': '0x0b00fb1f513e02399667fba50772b21f34c1b5d9',
}



ethereum_mainnet = {
    'usdc': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
    'usdt': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
    'wbtc': '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
    'dai':  '0x6B175474E89094C44Da98b954EedeAC495271d0F',
    'weth': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
}

arbitrum = {
    'usdc': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
    'usdt': '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9',
    'ezETH': '0x2416092f143378750bb29b79ed961ab195cceea5',
}

optimism = {
    'usdc': '0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85',
    'usdt': '0x94b008aA00579c1307B0EF2c499aD98a8ce58e58',
}

polygon = {
    'usdc': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174',
    'usdt': '0xc2132D05D31c914a87C6611C10748AEb04B58e8F',
}

binance_smart_chain = {
    'usdc': '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d',
    'usdt': '0x55d398326f99059fF775485246999027B3197955',
}

# Сентинел 'native' — для нативного токена сети (без ERC-20 контракта).
# Модуль детектит его и шлёт обычную EVM-транзакцию (eth.get_balance + tx с value).
avalanche = {
    'AVAX': 'native',
    'WAVAX': '0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7',
    'usdc': '0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E',
    'usdt': '0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7',
}

core_dao = {
    'CORE': 'native',
    'WCORE': '0x40375C92d9FAf44d2f9db9Bd9ba41a3317a2404f',
    'usdt': '0x900101d06A7426441Ae63e9AB3B9b0F63Be145F1',
    'usdc': '0xa4151B2B3e269645181dCcF2D426cE75fcbDeca9',
}

kava = {
    'KAVA': 'native',
    'WKAVA': '0xc86c7C0eFbd6A49B35E8714C5f59D99De09A225b',
    'usdt': '0x919C1c267BC06a7039e03fcc2eF738525769109c',
    'usdc': '0xfA9343C3897324496A05fC75abeD6bAC29f8A40f',
}

fantom = {
    'usdc': '0x04068DA6C83AFCFA0e13ba15A6696662335D5B75',
    'usdt': '0x049d68029688eAbF473097a2fC38ef61633A3C7A',
}

zora = {
    'usdc': '0xCccCCccc7021b32EBb4e8C08314bD62F7c653EC4',
    'usdt': '0xf0F161fDA2712DB8b566946122a5af183995e2eD',
}

sepolia = {
    'usdc': '0xf08A50178dfcDe18524640EA6618a1f965821715',
    'usdt': '0x2E8D98fd126a32362F2Bd8aA427E59a1ec63F780',
}


abstract = {
    'usdc': '0x6c280dB098dB673d30d5B34eC04B6387185D3620',
    'usdt': '0x3E3B5C17F55fF6F52f52bE7AaDbC60b60D9B26eF',
}

soneium = {
    'ASTR': '0x2cae934a1e84f693fbb78ca5ed3b0a6893259441',
    'WETH': '0x4200000000000000000000000000000000000006',
    'USDC.e': '0xba9986d2381edf1da03b0b9c1f8b00dc4aacc369',
    'WBTC': '0x0555e30da8f98308edb960aa94c0db47230d2b9c',
    'USDT': '0x3a337a6ada9d885b6ad95ec48f9b75f197b5ae35',
}

# ВНИМАНИЕ: здесь лежали адреса USDC/USDT из сети Base (побайтово те же, что в `base` выше) —
# копипаста. eth_getCode на Somnia mainnet по обоим адресам возвращает "0x": контрактов
# там нет, так что баланс всегда читался бы как мусор, а перевод ушёл бы в пустоту.
# Пустой словарь безопаснее: get_tokens_for_network вернёт {}, и меню честно скажет
# «нет настроенных токенов», не дав построить транзакцию.
# Имя переменной оставлено — на файл есть `import *`, и удалять публичное имя нельзя.
# Реальные адреса Somnia подставьте сами, сверив их в explorer'е сети.
somnia = {}

tempo_testnet = {
    'BetaUSD':'0x20c0000000000000000000000000000000000002',
    'ThetaUSD':'0x20c0000000000000000000000000000000000003',
    'PatchUSD':'0x20c0000000000000000000000000000000000000',
    'AlphaUSD':'0x20c0000000000000000000000000000000000001',
}

apechain = {
    'APE_test': '0x4d224452801aced8b2f0aebe155379bb5d594381'
}

# Добавляйте новые сети здесь...
# Пример для новой сети:
# new_network = {
#     'usdc': '0x...',
#     'usdt': '0x...',
# }


