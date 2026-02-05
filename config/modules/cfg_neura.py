# ========================================================================================
# NEURA PROTOCOL - Конвейерная работа с модулями
# ========================================================================================
# Список модулей для конвейерной обработки
# Доступные модули: 'collect_pulses', 'faucet', 'swap', 'claim_tasks'
# ВАЖНО: 'claim_tasks' ВСЕГДА выполняется последним (автоматически перемещается в конец)
# Модули (кроме claim_tasks) выполняются в рандомном порядке для каждого кошелька
NEURA_MODULES = ['collect_pulses', 'claim_tasks']  # Список модулей

# Рандомизация порядка модулей
NEURA_RANDOM_MODULE_ORDER = True  # Включить рандомный порядок модулей (claim_tasks всегда последний)

# Настройки подключения
NEURA_USE_PROXY = True  # Использовать прокси из data/proxy.csv
NEURA_RANDOM_PROXY = False  # Рандомный выбор прокси для каждого кошелька

# Настройки повторных попыток (используются глобальные: NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS)
NEURA_MAX_RETRIES_PER_TASK = 3  # Максимум попыток для каждой задачи внутри модуля

# Telegram уведомления для Neura
NEURA_TELEGRAM_NOTIFICATIONS = False  # Включить уведомления
NEURA_TELEGRAM_LOG_LEVEL = 1  # 0 - ничего, 1 - только результаты, 2 - все логи
SHUFFLE_WALLET_LIST_NEURA = True  # Перемешать список кошельков перед началом работы

# ===== FAUCET SETTINGS =====
NEURA_FAUCET_TOKEN = '7e6f8f99fdca1d7bfb7956aebbd7b9110a51cf3af3'  # Токен для faucet (next-action header)

# ===== SWAP SETTINGS =====
NEURA_SWAP_COUNT = [5, 8]  # Количество swap транзакций для каждого кошелька (рандомно от до)
NEURA_SWAP_PERCENTAGE = [0.1, 0.2]  # Процент от баланса для свапа (0.3 = 30%, 0.7 = 70%)
NEURA_SWAP_SLIPPAGE = 20  # Slippage в процентах (20 = 20%)
NEURA_SWAP_PAUSE_BETWEEN_SWAPS = [10, 25]  # Задержка между свапами (в секундах)

# Доступные пары для свапа в Neura (ANKR - нативный токен)
# Токены: ANKR, WANKR, ETH, ARB, BTC, TRUST, MEME, OP, TRX, NADSCAM
NEURA_SWAP_PAIRS = [
    ('ANKR', 'ETH'),    # ANKR -> ETH
    ('ETH', 'ANKR'),    # ETH -> ANKR
    ('ANKR', 'ARB'),    # ANKR -> ARB
    ('ARB', 'ANKR'),    # ARB -> ANKR
]
NEURA_RANDOM_SWAP_PAIR = True  # Рандомный выбор пары для свапа

# Адреса контрактов Neura
NEURA_ROUTER_ADDRESS = '0x6836F8A9a66ab8430224aa9b4E6D24dc8d7d5d77'
NEURA_QUOTER_ADDRESS = '0x6FCc4d7CA545ed24F37eb188555Bb219b1C545a7'

# Адреса токенов Neura (chain_id: 267)
NEURA_TOKENS = {
    'ANKR': None,  # Native token
    'WANKR': '0x422F5Eae5fEE0227FB31F149E690a73C4aD02dB8',
    'ETH': '0x3A631ee99eF7fE2D248116982b14e7615ac77502',
    'ARB': '0x2444fae99f9aa127043032be8589fac4b601c733',
    'BTC': '0x5e06d1bd47dd726a9bcd637e3d2f86b236e50c26',
    'TRUST': '0x193fa458f8e95fb8a7319f8285533d6a62cd22c9',
    'MEME': '0x3442890133041090786645d610f2f92f092c89b9',
    'OP': '0x3630388bd5e6927b7b6f8b6eb5863315d9401401',
    'TRX': '0x3655ccbd4e10c74e5bb48b016fd88fa468f49324',
    'NADSCAM': '0x40f7b83e326e71eecbf9bedd55237e474a8c0bad',
}
