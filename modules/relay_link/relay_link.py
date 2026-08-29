import os
import sys
import csv
import json
import time
import random
import sqlite3
import requests
import binascii
from typing import Dict, List, Optional, Tuple
from web3 import Web3

# Добавляем путь к корневой директории проекта
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
sys.path.append(project_root)

from modules.simple_logger import logger
from modules.ui import ui
from modules.ui.menu_model import BACK_KEY
# Импорты из проекта
from config.modules.cfg_relay import SUM_TO_RELAY, GAS
from config.modules.general_config import (
    MAIN_PROXY,
    WHAITE_TRANSACTION_PENDING,
    WHAITE_TRANSACTION_PENDING_COUNT,
)
from config.networks import NETWORKS, SOL_NETWORKS, get_explorer_url
# Явный список вместо `import *`: так видно, что именно модуль берёт из настроек,
# и линтер ловит опечатки в именах вместо тихого NameError на проде.
from modules.relay_link.settings.settings_relay_link import (
    BALANCE_CHECK_INTERVAL,
    CHAIN_ID_TO_NAME,
    MINIMUM_BRIDGE_AMOUNTS,
    NETWORK_MAPPING,
    NETWORK_SETTINGS,
    TOKEN_ADDRESSES,
)

# Импорты для деривации ключей из мнемоники
from modules.eth.eth_wallet_generator import mnemonic_to_private_key as eth_mnemonic_to_private_key, PublicKey, ETH_DERIVATION_PATH
from bip_utils import Bip39SeedGenerator, Bip39MnemonicValidator, Bip44, Bip44Coins, Bip44Changes
from solders.keypair import Keypair as SolKeypair
from solders.pubkey import Pubkey as SolPubkey
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.instruction import Instruction as SolInstruction, AccountMeta as SolAccountMeta
from solders.hash import Hash as SolHash
from solders.address_lookup_table_account import AddressLookupTableAccount
import base58

# Константа chain_id для Solana в Relay API
SOLANA_CHAIN_ID = 792703809



def log_wallet_summary(wallet_address: str, sent_amount: float, received_amount: float,
                       bridge_fee: float, from_network: str, to_network: str,
                       token_symbol: str, price_usd: float):
    """Вывод итогов кошелька через глобальный логер"""
    sent_usd = sent_amount * price_usd
    received_usd = received_amount * price_usd
    fee_usd = bridge_fee * price_usd
    fee_percent = (bridge_fee / sent_amount * 100) if sent_amount > 0 else 0

    logger.info(f"{'='*20} {wallet_address} {'='*20}")
    logger.success(f"  отправлено: {sent_amount:.6f} {token_symbol} ({from_network}) - ${sent_usd:.2f}")
    logger.success(f"  получено: {received_amount:.6f} {token_symbol} ({to_network}) - ${received_usd:.2f}")
    logger.error(f"  комиссия: {bridge_fee:.6f} {token_symbol} ({fee_percent:.2f}%) - ${fee_usd:.2f}")

def derive_eth_private_key_from_mnemonic(mnemonic: str) -> str:
    """Деривация ETH приватного ключа из мнемоники (BIP44 m/44'/60'/0'/0/0)"""
    private_key_bytes = eth_mnemonic_to_private_key(mnemonic, str_derivation_path=f'{ETH_DERIVATION_PATH}/0')
    return '0x' + binascii.hexlify(private_key_bytes).decode('utf-8')


def derive_sol_address_from_mnemonic(mnemonic: str) -> Tuple[str, str]:
    """
    Деривация Solana адреса и приватного ключа из мнемоники (BIP44 m/44'/501'/0'/0')

    Returns:
        Tuple[sol_address, sol_private_key_b58]
    """
    seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
    bip44_mst_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
    bip44_acc_ctx = bip44_mst_ctx.Purpose().Coin().Account(0)
    bip44_chg_ctx = bip44_acc_ctx.Change(Bip44Changes.CHAIN_EXT)

    priv_key = bip44_chg_ctx.PrivateKey().Raw().ToBytes()
    pub_key = bip44_chg_ctx.PublicKey().RawCompressed().ToBytes()[1:]

    full_keypair_bytes = priv_key + pub_key
    keypair = SolKeypair.from_bytes(full_keypair_bytes)

    sol_address = str(keypair.pubkey())
    sol_private_key_b58 = base58.b58encode(full_keypair_bytes).decode()

    return sol_address, sol_private_key_b58


class RelayBridge:
    def __init__(self):
        self.base_url = "https://api.relay.link"
        self.db_path = os.path.join(project_root, 'db', 'relay_progress.db')
        self.result_path = os.path.join(project_root, 'result', 'relay_link.csv')

        # Инициализация базы данных
        self._init_database()

        # Загрузка данных
        self.proxies = self._load_proxies()

        # Флаг использования мнемоник (для Solana маршрутов)
        self.use_mnemonics = False
        # Словарь: eth_address -> {eth_private_key, sol_address, sol_private_key, mnemonic}
        self.wallet_pairs = {}
        # Приватные ключи (загружаются из файла или из мнемоник)
        self.private_keys = []

        # Настройка RPC для сетей
        self.rpc_pools = {
            1: NETWORKS['🚀 Ethereum Mainnet']['rpc_urls'],  # Ethereum
            10: NETWORKS['🚀 Optimism']['rpc_urls'],  # Optimism
            137: NETWORKS['🚀 Polygon']['rpc_urls'],  # Polygon
            8453: NETWORKS['🚀 Base']['rpc_urls'],  # Base
            42161: NETWORKS['🚀 Arbitrum One']['rpc_urls'],  # Arbitrum
            42170: NETWORKS['🚀 Arbitrum Nova']['rpc_urls'],  # Arbitrum Nova
            1868: NETWORKS['🚀 Soneium']['rpc_urls'],  # Soneium
            2741: NETWORKS['🚀 Abstract']['rpc_urls'],  # Abstract
            169: NETWORKS['🚀 Manta Pacific Mainnet']['rpc_urls'],  # Manta Pacific
            59144: NETWORKS['🚀 Linea']['rpc_urls']  # Linea
        }

        # Solana RPC URLs
        self.solana_rpc_urls = SOL_NETWORKS['🚀 Solana Mainnet']['rpc_urls']

        # Маппинг chain_id на названия сетей в explorer_url.py
        self.chain_id_to_explorer_network = {
            1: '🚀 Ethereum Mainnet',
            10: '🚀 Optimism',
            137: '🚀 Polygon',
            8453: '🚀 Base',
            42161: '🚀 Arbitrum One',
            42170: '🚀 Arbitrum Nova',
            1868: '🚀 Soneium',
            2741: '🚀 Abstract',
            169: '🚀 Manta Pacific Mainnet',
            59144: '🚀 Linea',
            SOLANA_CHAIN_ID: '🚀 Solana Mainnet'
        }

        # Кеш для Web3 подключений
        self.web3_connections = {}

        # Инициализация CSV файла с заголовками
        self._init_csv_file()

    def _init_database(self):
        """Инициализация базы данных для отслеживания прогресса"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS relay_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                private_key_hash TEXT NOT NULL,
                from_network TEXT NOT NULL,
                to_network TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                tx_hash TEXT,
                bridge_fee REAL DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                error_message TEXT,
                error_count INTEGER DEFAULT 0
            )
        ''')

        # Проверяем и добавляем поле error_count если его нет (миграция)
        cursor.execute("PRAGMA table_info(relay_progress)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'error_count' not in columns:
            cursor.execute('ALTER TABLE relay_progress ADD COLUMN error_count INTEGER DEFAULT 0')

        # Миграция: добавляем поле bridge_fee и удаляем старые поля газа
        if 'bridge_fee' not in columns:
            cursor.execute('ALTER TABLE relay_progress ADD COLUMN bridge_fee REAL DEFAULT 0')

        # Удаляем старые поля газа если они есть (в SQLite нельзя просто удалить колонки, но можем их игнорировать)

        conn.commit()
        conn.close()

    def _select_network_and_token(self, prompt_text: str, exclude_chain_id: int = None) -> Tuple[Optional[int], Optional[str]]:
        """
        Интерактивный выбор сети. Токен всегда нативный — см. комментарий ниже.

        Args:
            prompt_text: Текст приглашения для выбора
            exclude_chain_id: ID сети которую нужно исключить из списка

        Returns:
            Tuple[chain_id, token_symbol] или (None, None) при отмене
        """
        available_networks = []
        for network_name, chain_id in NETWORK_MAPPING.items():
            if exclude_chain_id and chain_id == exclude_chain_id:
                continue
            available_networks.append((
                f"🌐 {NETWORK_SETTINGS[chain_id]['name']}",
                (network_name, chain_id),
            ))

        selected = ui.choose(prompt_text, available_networks)

        if selected in (None, BACK_KEY):
            return None, None

        network_name, chain_id = selected

        # Токен не спрашиваем: весь путь ниже (котировка, расчёт суммы, проверка
        # поступления) работает только с нативной монетой сети. Раньше меню
        # предлагало USDC/USDT, выбор логировался в итоговой конфигурации,
        # а мост всё равно отправлял ETH — то есть меню врало пользователю.
        # Вернём выбор, когда появится реальная поддержка ERC-20.
        native_symbol = NETWORK_SETTINGS[chain_id]['native_symbol']
        logger.info(f"💎 Токен: {native_symbol} (нативный) — бридж ERC-20 токенов пока не поддерживается")

        return chain_id, native_symbol

    def _calculate_bridge_amount(self, wallet_address: str, from_chain_id: int) -> float:
        """
        Вычисление суммы для бриджа на основе SUM_TO_RELAY
        Поддерживает как фиксированную сумму, так и проценты от баланса

        Args:
            wallet_address: ETH адрес кошелька
            from_chain_id: ID сети откуда будет бридж

        Returns:
            Сумма для бриджа (в нативных единицах: ETH для EVM, SOL для Solana)
        """
        token_symbol = NETWORK_SETTINGS[from_chain_id]['native_symbol']

        if isinstance(SUM_TO_RELAY[0], str):
            # Это процент от баланса
            min_percent = float(SUM_TO_RELAY[0])
            max_percent = float(SUM_TO_RELAY[1])

            # Получаем баланс кошелька
            if from_chain_id == SOLANA_CHAIN_ID:
                sol_address = self._get_sol_address_for_eth(wallet_address)
                if not sol_address:
                    logger.warning(f"⚠️ SOL адрес не найден для {wallet_address}")
                    return 0.0
                balance = self._get_solana_balance(sol_address, show_log=False)
            else:
                balance = self._get_native_balance(from_chain_id, wallet_address, show_log=False)

            if balance <= 0:
                logger.warning(f"⚠️ Нулевой баланс у кошелька {wallet_address}")
                return 0.0

            percent = random.uniform(min_percent, max_percent)
            original_amount = balance * (percent / 100.0)
            amount = original_amount

            # Резерв на газ
            gas_reserve = 0.0
            if from_chain_id == SOLANA_CHAIN_ID:
                gas_reserve = 0.001  # ~0.001 SOL на комиссию Solana (реальные комиссии ~0.000005)
            else:
                try:
                    web3_temp = self._get_web3_connection(from_chain_id)
                    if web3_temp:
                        current_gas_price = web3_temp.eth.gas_price
                        gas_reserve_wei = 150000 * int(current_gas_price * 1.5)
                        gas_reserve = gas_reserve_wei / 10**18
                except Exception:
                    pass
                if gas_reserve < 0.0000001:
                    gas_reserve = max(0.00001, balance * 0.001)

            adjusted = False
            if amount + gas_reserve > balance:
                amount = balance - gas_reserve
                adjusted = True

            if amount <= 0:
                logger.warning(f"⚠️ После вычета газа сумма для бриджа <= 0 у кошелька {wallet_address}")
                return 0.0

            if adjusted:
                logger.info(f"💰 Вычислено {percent:.2f}% от баланса {balance:.6f} = {original_amount:.6f} {token_symbol} -> скорректировано до {amount:.6f} (резерв газа: {gas_reserve:.6f})")
            else:
                logger.info(f"💰 Вычислено {percent:.2f}% от баланса {balance:.6f} = {amount:.6f} {token_symbol} (резерв газа: {gas_reserve:.6f})")
            return amount
        else:
            min_amount, max_amount = SUM_TO_RELAY
            amount = random.uniform(min_amount, max_amount)
            return amount

    def _create_work_plan(self, from_chain_id: int, to_chain_id: int):
        """Создание полного плана работ в базе данных.

        Токены не принимаем: бридж всегда идёт нативной монетой сети,
        а прежние параметры from_token/to_token тут никогда не использовались.
        """
        from_network = CHAIN_ID_TO_NAME[from_chain_id]
        to_network = CHAIN_ID_TO_NAME[to_chain_id]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Проверяем, есть ли уже записи в базе
        cursor.execute("SELECT COUNT(*) FROM relay_progress")
        existing_count = cursor.fetchone()[0]

        if existing_count == 0:
            for private_key in self.private_keys:
                # Получение адреса кошелька
                account = Web3().eth.account.from_key(private_key)
                wallet_address = account.address

                # Вычисление суммы для бриджа (с поддержкой процентов)
                amount = self._calculate_bridge_amount(wallet_address, from_chain_id)

                if amount <= 0:
                    logger.warning(f"⚠️ Пропускаем кошелек {wallet_address} - недостаточно средств")
                    continue

                # Добавление записи в БД (используем пустую строку для private_key_hash, т.к. теперь ищем по wallet_address)
                cursor.execute('''
                    INSERT INTO relay_progress (wallet_address, private_key_hash, from_network, to_network, amount, status)
                    VALUES (?, ?, ?, ?, ?, 'pending')
                ''', (wallet_address, '', from_network, to_network, amount))

            conn.commit()
            logger.success(f"✅ План работ создан для {len(self.private_keys)} кошельков")
        elif existing_count > 0:
            logger.info(f"📋 Найдено {existing_count} записей в базе данных")

        conn.close()
        return True

    def _init_csv_file(self):
        """Инициализация CSV файла с заголовками"""
        os.makedirs(os.path.dirname(self.result_path), exist_ok=True)

        # Всегда создаем новый файл или перезаписываем существующий
        with open(self.result_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            headers = [
                'Wallet Address',
                'From Network',
                'To Network',
                'Amount Sent',
                'Transaction Hash',
                'Gas Cost (ETH)',
                'Status',
                'Timestamp',
                'Amount Received',
                'Bridge Fee'
            ]
            writer.writerow(headers)

    def _load_private_keys(self) -> List[str]:
        """Загрузка приватных ключей из data.csv"""
        from modules.data_manager import get_private_keys
        keys = get_private_keys()
        if not keys:
            logger.error("❌ Нет приватных ключей в data/data.csv")
        return keys

    def _load_mnemonics_and_derive_keys(self) -> List[str]:
        """
        Загрузка мнемоник из файла и деривация ETH + SOL ключей.
        Возвращает список ETH приватных ключей (для совместимости с основным потоком).
        Заполняет self.wallet_pairs с маппингом eth_address -> {eth_private_key, sol_address, ...}
        """
        from modules.data_manager import get_mnemonics
        mnemonics = get_mnemonics()

        if not mnemonics:
            logger.error("❌ Нет мнемоник в data/data.csv")
            return []

        eth_private_keys = []
        for mnemonic in mnemonics:
            try:
                # Валидация мнемоники
                if not Bip39MnemonicValidator().IsValid(mnemonic):
                    logger.error(f"❌ Невалидная мнемоника: {mnemonic[:20]}...")
                    continue

                # Деривация ETH ключа
                eth_private_key = derive_eth_private_key_from_mnemonic(mnemonic)
                eth_account = Web3().eth.account.from_key(eth_private_key)
                eth_address = eth_account.address

                # Деривация SOL адреса и ключа
                sol_address, sol_private_key = derive_sol_address_from_mnemonic(mnemonic)

                # Сохраняем пару
                self.wallet_pairs[eth_address] = {
                    'eth_private_key': eth_private_key,
                    'sol_address': sol_address,
                    'sol_private_key': sol_private_key,
                    'mnemonic': mnemonic
                }

                eth_private_keys.append(eth_private_key)
                logger.info(f"✅ Мнемоника загружена: ETH {eth_address} | SOL {sol_address}")

            except Exception as e:
                logger.error(f"❌ Ошибка деривации ключей из мнемоники: {e}")
                continue

        logger.info(f"📋 Загружено {len(eth_private_keys)} пар кошельков из мнемоник")

        # Сохраняем ключи и адреса в файл результатов
        self._save_wallet_keys_to_csv()

        return eth_private_keys

    def _save_wallet_keys_to_csv(self):
        """Сохранение приватных ключей и адресов ETH/SOL в файл результатов"""
        wallets_path = os.path.join(project_root, 'result', 'relay_link_wallets.csv')
        os.makedirs(os.path.dirname(wallets_path), exist_ok=True)

        with open(wallets_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Mnemonic', 'ETH Address', 'ETH Private Key', 'SOL Address', 'SOL Private Key'])
            for eth_address, pair in self.wallet_pairs.items():
                writer.writerow([
                    pair['mnemonic'],
                    eth_address,
                    pair['eth_private_key'],
                    pair['sol_address'],
                    pair['sol_private_key']
                ])

        logger.info(f"💾 Ключи кошельков сохранены в {wallets_path} ({len(self.wallet_pairs)} шт.)")

    def _load_proxies(self) -> List[str]:
        """Загрузка прокси из data.csv"""
        from modules.data_manager import get_proxies
        return get_proxies()

    def _get_random_proxy_for_api(self) -> Optional[str]:
        """Получение случайного прокси для API запросов"""
        # Сначала пробуем использовать случайный прокси из списка
        if self.proxies:
            return random.choice(self.proxies)

        # Если список пуст, используем MAIN_PROXY
        if MAIN_PROXY:
            return MAIN_PROXY

        # Если нет ни того, ни другого, возвращаем None
        return None

    def _get_web3_connection(self, chain_id: int) -> Optional[Web3]:
        """Получение Web3 подключения с ротацией RPC"""
        if chain_id not in self.rpc_pools:
            logger.error(f"❌ Нет RPC для сети {chain_id}")
            return None

        cache_key = chain_id
        if cache_key in self.web3_connections:
            web3 = self.web3_connections[cache_key]
            if web3.is_connected():
                #logger.info(f"🔗 Используем кешированное подключение к {NETWORK_SETTINGS[chain_id]['name']}")
                return web3
            else:
                logger.warning(f"⚠️ Кешированное подключение к {NETWORK_SETTINGS[chain_id]['name']} не активно, переподключаемся...")

        # Перебираем RPC пока не найдем рабочий (тихо)
        rpc_list = self.rpc_pools[chain_id]

        for i, rpc_url in enumerate(rpc_list):
            try:
                web3 = Web3(Web3.HTTPProvider(rpc_url))
                if web3.is_connected():
                    self.web3_connections[cache_key] = web3
                    return web3
                else:
                    logger.warning(f"⚠️ RPC не отвечает: {rpc_url[:50]}...")
            except Exception as e:
                logger.warning(f"⚠️ RPC ошибка: {rpc_url[:50]}... - {e}")
                continue

        logger.error(f"❌ Все RPC для сети {chain_id} ({NETWORK_SETTINGS[chain_id]['name']}) недоступны")
        return None

    def _get_native_balance(self, chain_id: int, wallet_address: str, show_log: bool = False) -> float:
        """Получение баланса нативного токена — ответ первой живой ноды.

        Раньше опрашивались ВСЕ RPC и возвращался max(). Это не «самое актуальное»
        значение, а ровно наоборот: отставшая нода после исходящей транзакции
        показывает БОЛЬШИЙ баланс, поэтому max() системно выбирал устаревшие данные
        и завышал сумму бриджа. Плюс на каждый вызов поднималось len(rpc_urls)
        новых HTTP-подключений — при опросе моста это тысячи коннектов на кошелёк.
        """
        network_name = NETWORK_SETTINGS.get(chain_id, {}).get('name', str(chain_id))
        # Символ берём из настроек сети: раньше в лог всегда писалось "ETH", даже для Polygon
        symbol = NETWORK_SETTINGS.get(chain_id, {}).get('native_symbol', '')

        def _read(web3: Web3) -> float:
            return float(web3.from_wei(web3.eth.get_balance(wallet_address), 'ether'))

        # Сначала пробуем кешированное подключение (его же переиспользует остальной модуль)
        cached = self.web3_connections.get(chain_id)
        if cached is not None:
            try:
                balance = _read(cached)
                if show_log:
                    logger.info(f"📊 Текущий баланс {network_name}: {balance:.8f} {symbol}")
                return balance
            except Exception:
                # Подключение протухло — выкидываем из кеша и идём по списку RPC
                self.web3_connections.pop(chain_id, None)

        for rpc_url in self.rpc_pools.get(chain_id, []):
            try:
                web3 = Web3(Web3.HTTPProvider(rpc_url))
                if not web3.is_connected():
                    continue

                balance = _read(web3)
                self.web3_connections[chain_id] = web3
                if show_log:
                    logger.info(f"📊 Текущий баланс {network_name}: {balance:.8f} {symbol}")
                return balance
            except Exception:
                continue

        # Если все RPC не работают, возвращаем 0
        if show_log:
            logger.error(f"❌ Все RPC для {network_name} недоступны")
        return 0.0

    def _get_solana_balance(self, sol_address: str, show_log: bool = False) -> float:
        """Получение баланса SOL через Solana JSON-RPC"""
        for rpc_url in self.solana_rpc_urls:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBalance",
                    "params": [sol_address]
                }
                response = requests.post(rpc_url, json=payload, timeout=10)
                response.raise_for_status()
                data = response.json()

                if 'result' in data and 'value' in data['result']:
                    balance_lamports = data['result']['value']
                    balance_sol = balance_lamports / 1_000_000_000  # 9 decimals
                    if show_log:
                        logger.info(f"📊 Баланс Solana ({sol_address[:8]}...): {balance_sol:.6f} SOL")
                    return balance_sol
            except Exception as e:
                continue

        if show_log:
            logger.error(f"❌ Не удалось получить баланс Solana для {sol_address}")
        return 0.0

    def _get_solana_latest_blockhash(self) -> Optional[str]:
        """Получение последнего blockhash из Solana RPC"""
        for rpc_url in self.solana_rpc_urls:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getLatestBlockhash",
                    "params": [{"commitment": "finalized"}]
                }
                response = requests.post(rpc_url, json=payload, timeout=10)
                response.raise_for_status()
                data = response.json()
                if 'result' in data and 'value' in data['result']:
                    return data['result']['value']['blockhash']
            except Exception:
                continue
        return None

    def _get_solana_address_lookup_table(self, table_address: str) -> Optional[AddressLookupTableAccount]:
        """Загрузка Address Lookup Table из Solana RPC"""
        for rpc_url in self.solana_rpc_urls:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getAccountInfo",
                    "params": [
                        table_address,
                        {"encoding": "base64", "commitment": "finalized"}
                    ]
                }
                response = requests.post(rpc_url, json=payload, timeout=10)
                response.raise_for_status()
                data = response.json()

                if 'result' not in data or data['result']['value'] is None:
                    continue

                import base64
                account_data = base64.b64decode(data['result']['value']['data'][0])

                # Парсинг Address Lookup Table
                # Формат: 4 bytes deactivation_slot + 4 bytes last_extended_slot + 1 byte last_extended_slot_start_index + ... + addresses
                # Реальный формат: первые 56 байт - метаданные, далее - 32-байтовые публичные ключи
                LOOKUP_TABLE_META_SIZE = 56
                if len(account_data) < LOOKUP_TABLE_META_SIZE:
                    continue

                addresses_data = account_data[LOOKUP_TABLE_META_SIZE:]
                addresses = []
                for i in range(0, len(addresses_data), 32):
                    if i + 32 <= len(addresses_data):
                        addresses.append(SolPubkey.from_bytes(addresses_data[i:i+32]))

                return AddressLookupTableAccount(
                    key=SolPubkey.from_string(table_address),
                    addresses=addresses
                )
            except Exception as e:
                logger.warning(f"⚠️ Ошибка загрузки ALT {table_address[:12]}...: {e}")
                continue
        return None

    def _send_solana_transaction(self, signed_tx: VersionedTransaction) -> Optional[str]:
        """Отправка подписанной Solana транзакции через RPC"""
        tx_bytes = bytes(signed_tx)
        tx_base64 = __import__('base64').b64encode(tx_bytes).decode('utf-8')

        for rpc_url in self.solana_rpc_urls:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        tx_base64,
                        {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}
                    ]
                }
                response = requests.post(rpc_url, json=payload, timeout=30)
                response.raise_for_status()
                data = response.json()

                if 'error' in data:
                    logger.error(f"❌ Solana RPC ошибка: {data['error']}")
                    continue

                if 'result' in data:
                    return data['result']  # tx signature
            except Exception as e:
                logger.warning(f"⚠️ Ошибка отправки Solana TX: {e}")
                continue
        return None

    def _confirm_solana_transaction(self, tx_signature: str, max_wait_seconds: int = 60) -> bool:
        """Ожидание подтверждения Solana транзакции"""
        for attempt in range(max_wait_seconds // 5):
            for rpc_url in self.solana_rpc_urls:
                try:
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getSignatureStatuses",
                        "params": [[tx_signature], {"searchTransactionHistory": True}]
                    }
                    response = requests.post(rpc_url, json=payload, timeout=10)
                    data = response.json()

                    if 'result' in data and data['result']['value']:
                        status = data['result']['value'][0]
                        if status is not None:
                            if status.get('err') is None:
                                conf = status.get('confirmationStatus', '')
                                if conf in ('confirmed', 'finalized'):
                                    return True
                            else:
                                logger.error(f"❌ Solana TX ошибка: {status['err']}")
                                return False
                except Exception:
                    continue
            time.sleep(5)
        return False

    def _execute_solana_bridge(self, quote_data: Dict, wallet_address: str, sol_private_key_b58: str,
                                from_chain_id: int, to_chain_id: int, sent_amount_sol: float) -> bool:
        """Выполнение Solana бридж-транзакции (SOL -> EVM)"""
        try:
            steps = quote_data.get('steps', [])
            if not steps:
                logger.error("❌ Нет шагов в котировке")
                return False

            tx_step = None
            for step in steps:
                if step.get('kind') == 'transaction':
                    tx_step = step
                    break

            if not tx_step:
                logger.error("❌ Не найден шаг с транзакцией")
                return False

            items = tx_step.get('items', [])
            if not items:
                logger.error("❌ Нет элементов транзакции")
                return False

            tx_data = items[0].get('data', {})
            instructions_data = tx_data.get('instructions', [])
            alt_addresses = tx_data.get('addressLookupTableAddresses', [])

            if not instructions_data:
                logger.error("❌ Нет инструкций в транзакции Solana")
                return False

            # Получаем начальный баланс ETH в целевой сети
            eth_address = wallet_address  # ETH адрес
            initial_to_balance = self._get_native_balance(to_chain_id, eth_address)

            # Собираем Solana Keypair
            sol_keypair = SolKeypair.from_bytes(base58.b58decode(sol_private_key_b58))
            sol_address = str(sol_keypair.pubkey())

            # Начальный баланс SOL
            initial_from_balance = self._get_solana_balance(sol_address)

            # Получаем blockhash
            blockhash_str = self._get_solana_latest_blockhash()
            if not blockhash_str:
                logger.error("❌ Не удалось получить blockhash")
                return False

            recent_blockhash = SolHash.from_string(blockhash_str)

            # Собираем инструкции
            instructions = []
            for instr_data in instructions_data:
                program_id = SolPubkey.from_string(instr_data['programId'])
                accounts = []
                for key_info in instr_data['keys']:
                    accounts.append(SolAccountMeta(
                        pubkey=SolPubkey.from_string(key_info['pubkey']),
                        is_signer=key_info['isSigner'],
                        is_writable=key_info['isWritable']
                    ))
                data_hex = instr_data['data']
                data_bytes = bytes.fromhex(data_hex)
                instructions.append(SolInstruction(program_id, data_bytes, accounts))

            # Загружаем Address Lookup Tables
            lookup_tables = []
            for alt_addr in alt_addresses:
                alt = self._get_solana_address_lookup_table(alt_addr)
                if alt:
                    lookup_tables.append(alt)

            # Собираем и подписываем транзакцию
            message = MessageV0.try_compile(
                payer=sol_keypair.pubkey(),
                instructions=instructions,
                address_lookup_table_accounts=lookup_tables,
                recent_blockhash=recent_blockhash
            )

            tx = VersionedTransaction(message, [sol_keypair])

            # Отправляем
            logger.info(f"📤 Отправка Solana транзакции...")
            tx_signature = self._send_solana_transaction(tx)
            if not tx_signature:
                logger.error("❌ Не удалось отправить Solana транзакцию")
                return False

            # Подпись в БД сразу после отправки — как и в EVM-ветке, до всех ожиданий
            self._save_transaction_result(eth_address, tx_signature, 0, 'tx_sent')

            explorer_link = f"https://solscan.io/tx/{tx_signature}"
            logger.info(f"📤 Solana транзакция: {explorer_link}")

            # Ждем подтверждения на Solana
            logger.info("⏳ Ожидание подтверждения Solana транзакции...")
            confirmed = self._confirm_solana_transaction(tx_signature)
            if confirmed:
                logger.success(f"✅ Solana транзакция подтверждена")
                self._save_transaction_result(eth_address, tx_signature, 0, 'awaiting_arrival')
            else:
                logger.warning(f"⚠️ Не удалось подтвердить Solana транзакцию, проверяем баланс...")

            # Проверяем поступление ETH в целевую сеть
            logger.info(f"🔍 Проверка поступления средств в {NETWORK_SETTINGS[to_chain_id]['name']}...")
            transaction_success = self._check_balance_changes(
                eth_address, from_chain_id, to_chain_id, sent_amount_sol,
                initial_from_balance, initial_to_balance
            )

            if transaction_success:
                logger.success(f"✅ Бридж SOL -> ETH подтвержден")
                self._save_transaction_result(eth_address, tx_signature, 0, 'completed')
                return True
            else:
                self._save_transaction_result(eth_address, tx_signature, 0, 'failed')
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка выполнения Solana транзакции: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _get_transaction_explorer_link(self, chain_id: int, tx_hash: str) -> str:
        """Получение ссылки на транзакцию в explorer"""
        # Solana explorer
        if chain_id == SOLANA_CHAIN_ID:
            return f"https://solscan.io/tx/{tx_hash}"

        explorer_network = self.chain_id_to_explorer_network.get(chain_id)
        if explorer_network:
            explorer_url = get_explorer_url(explorer_network)
            if explorer_url and not explorer_url.startswith("ошибка"):
                return f"{explorer_url}{tx_hash}"

        # Fallback для неизвестных сетей
        network_name = NETWORK_SETTINGS.get(chain_id, {}).get('name', 'Unknown')
        return f"Транзакция {tx_hash} в сети {network_name}"

    def _check_balances(self, wallet_address: str, from_chain_id: int, to_chain_id: int) -> Dict[str, Dict]:
        """Проверка балансов в указанных сетях (включая Solana)"""
        balances = {}

        for chain_id in [from_chain_id, to_chain_id]:
            network_name = CHAIN_ID_TO_NAME[chain_id]

            if chain_id == SOLANA_CHAIN_ID:
                # Для Solana используем SOL адрес из wallet_pairs
                sol_address = self._get_sol_address_for_eth(wallet_address)
                if sol_address:
                    balance = self._get_solana_balance(sol_address, show_log=True)
                else:
                    logger.warning(f"⚠️ SOL адрес не найден для {wallet_address}")
                    balance = 0.0
            else:
                balance = self._get_native_balance(chain_id, wallet_address, show_log=True)

            if balance >= 0:
                balances[network_name] = {
                    'chain_id': chain_id,
                    'balance': balance,
                    'symbol': NETWORK_SETTINGS[chain_id]['native_symbol']
                }

        return balances

    def _get_sol_address_for_eth(self, eth_address: str) -> Optional[str]:
        """Получить SOL адрес по ETH адресу из wallet_pairs"""
        pair = self.wallet_pairs.get(eth_address)
        if pair:
            return pair['sol_address']
        return None

    def _get_quote(self, from_chain_id: int, to_chain_id: int, amount: int, wallet_address: str,
                   sol_recipient: str = None, sol_sender: str = None) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Получение котировки для бриджа. Возвращает (quote_data, error_message)

        Args:
            amount: Сумма в минимальных единицах (wei для EVM, lamports для SOL)
            wallet_address: ETH адрес кошелька
            sol_recipient: SOL адрес получателя (для EVM->SOL)
            sol_sender: SOL адрес отправителя (для SOL->EVM)
        """
        url = f"{self.base_url}/quote"

        from_token = TOKEN_ADDRESSES[from_chain_id][NETWORK_SETTINGS[from_chain_id]['native_symbol']]
        to_token = TOKEN_ADDRESSES[to_chain_id][NETWORK_SETTINGS[to_chain_id]['native_symbol']]

        # Определяем user и recipient в зависимости от направления
        if from_chain_id == SOLANA_CHAIN_ID and sol_sender:
            # SOL -> EVM: user=SOL, recipient=ETH
            user = sol_sender
            recipient = wallet_address
        elif to_chain_id == SOLANA_CHAIN_ID and sol_recipient:
            # EVM -> SOL: user=ETH, recipient=SOL
            user = wallet_address
            recipient = sol_recipient
        else:
            # EVM -> EVM
            user = wallet_address
            recipient = wallet_address

        payload = {
            "user": user,
            "originChainId": from_chain_id,
            "destinationChainId": to_chain_id,
            "originCurrency": from_token,
            "destinationCurrency": to_token,
            "amount": str(amount),
            "tradeType": "EXACT_INPUT",
            "recipient": recipient
        }

        # Для EVM->EVM маршрутов оставляем старые параметры
        if from_chain_id != SOLANA_CHAIN_ID and to_chain_id != SOLANA_CHAIN_ID:
            payload["slippageBps"] = "0"
            payload["useExternalLiquidity"] = False

        headers = {"Content-Type": "application/json"}

        try:
            api_proxy = self._get_random_proxy_for_api()
            proxies = None
            if api_proxy:
                proxies = {
                    'http': f'http://{api_proxy}',
                    'https': f'http://{api_proxy}'
                }

            logger.info(f"📡 Запрос котировки: {NETWORK_SETTINGS[from_chain_id]['name']} -> {NETWORK_SETTINGS[to_chain_id]['name']}, user: {user[:12]}..., получатель: {recipient[:12]}...")
            response = requests.post(url, json=payload, headers=headers, proxies=proxies, timeout=30)
            response.raise_for_status()
            return response.json(), None
        except requests.exceptions.HTTPError as e:
            response_body = ""
            try:
                response_body = e.response.text if e.response else ""
            except Exception:
                pass
            error_msg = f"Ошибка получения котировки: {e}"
            if response_body:
                error_msg += f" | Ответ API: {response_body[:500]}"
            logger.error(f"❌ {error_msg}")
            return None, error_msg
        except Exception as e:
            error_msg = f"Ошибка получения котировки: {e}"
            logger.error(f"❌ {error_msg}")
            return None, error_msg

    @staticmethod
    def _arrival_poll_plan() -> Tuple[int, int]:
        """Интервал и число проверок поступления средств.

        AGENTS.md §9.4: интервал — ручка модуля (BALANCE_CHECK_INTERVAL),
        бюджет ожидания — WHAITE_TRANSACTION_PENDING * WHAITE_TRANSACTION_PENDING_COUNT.
        Раньше интервал брался из SLEEP_BETWEEN_ACTIONS (2-4 сек) — это давало
        ~225 проверок на кошелёк вместо десятка и заваливало RPC запросами.
        """
        interval = max(1, int(BALANCE_CHECK_INTERVAL))
        budget = max(interval, int(WHAITE_TRANSACTION_PENDING) * int(WHAITE_TRANSACTION_PENDING_COUNT))
        return interval, max(1, budget // interval)

    def _check_balance_changes(self, wallet_address: str, from_chain_id: int, to_chain_id: int, sent_amount: float, initial_from_balance: float, initial_to_balance: float) -> bool:
        """
        Проверка изменения балансов для подтверждения успешности транзакции
        Основной критерий успеха - поступление средств в целевую сеть

        Args:
            wallet_address: ETH адрес кошелька
            from_chain_id: ID сети откуда отправили
            to_chain_id: ID сети куда должно прийти
            sent_amount: Отправленная сумма
            initial_from_balance: Начальный баланс в исходной сети
            initial_to_balance: Начальный баланс в целевой сети

        Returns:
            True если средства поступили в целевую сеть
        """
        poll_interval, max_attempts = self._arrival_poll_plan()
        total_minutes = poll_interval * max_attempts / 60
        logger.info(f"⏱️ Максимальное время ожидания: {total_minutes:.0f} мин ({max_attempts} проверок раз в {poll_interval} сек)")

        # Определяем, проверяем ли Solana баланс
        is_solana_dest = (to_chain_id == SOLANA_CHAIN_ID)
        sol_address = None
        if is_solana_dest:
            sol_address = self._get_sol_address_for_eth(wallet_address)
            if not sol_address:
                logger.error(f"❌ SOL адрес не найден для {wallet_address}")
                return False

        for attempt in range(max_attempts):
            try:
                logger.info(f"🔍 Проверка {attempt + 1}/{max_attempts}: проверяем баланс в {NETWORK_SETTINGS[to_chain_id]['name']}...")

                # Получаем АКТУАЛЬНЫЙ баланс целевой сети
                if is_solana_dest:
                    current_to_balance = self._get_solana_balance(sol_address)
                else:
                    current_to_balance = self._get_native_balance(to_chain_id, wallet_address)

                # Рассчитываем изменение в целевой сети
                to_change = current_to_balance - initial_to_balance

                logger.info(f"📊 Баланс: {initial_to_balance:.8f} → {current_to_balance:.8f} (изменение: {to_change:.8f} {NETWORK_SETTINGS[to_chain_id]['native_symbol']})")

                # Главный критерий успеха
                if to_change > 0.000001:
                    logger.success(f"✅ Транзакция успешна! Получено: {to_change:.6f} {NETWORK_SETTINGS[to_chain_id]['native_symbol']}")
                    return True

                if attempt < max_attempts - 1:
                    logger.info(f"⏳ Средства еще не поступили, ожидание {poll_interval} сек...")
                    time.sleep(poll_interval)

            except Exception as e:
                logger.error(f"❌ Ошибка при проверке баланса (попытка {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    logger.info(f"🔄 Повторная попытка через {poll_interval} сек...")
                    time.sleep(poll_interval)

        logger.error(f"❌ Средства не поступили в {NETWORK_SETTINGS[to_chain_id]['name']} в течение {total_minutes:.0f} мин")
        return False

    def _execute_bridge(self, quote_data: Dict, wallet_address: str, private_key: str, from_chain_id: int, to_chain_id: int, sent_amount: float) -> bool:
        """Выполнение бридж транзакции"""
        try:
            # Вычисляем комиссию из котировки для сохранения в результат
            quote_fee_eth = 0.0
            if quote_data and 'details' in quote_data and 'currencyOut' in quote_data['details']:
                if to_chain_id == SOLANA_CHAIN_ID:
                    # Для ETH->SOL: берем комиссию из fees секции
                    fees_section = quote_data.get('fees', {})
                    relayer_fee = fees_section.get('relayer', {})
                    if 'amountFormatted' in relayer_fee:
                        quote_fee_eth = float(relayer_fee['amountFormatted'])
                else:
                    amount_out_wei = int(quote_data['details']['currencyOut']['amount'])
                    amount_out_eth = float(Web3.from_wei(amount_out_wei, 'ether'))
                    quote_fee_eth = sent_amount - amount_out_eth

            steps = quote_data.get('steps', [])
            if not steps:
                logger.error("❌ Нет шагов в котировке")
                return False

            # Находим шаг с транзакцией
            tx_step = None
            for step in steps:
                if step.get('kind') == 'transaction':
                    tx_step = step
                    break

            if not tx_step:
                logger.error("❌ Не найден шаг с транзакцией")
                return False

            items = tx_step.get('items', [])
            if not items:
                logger.error("❌ Нет элементов транзакции")
                return False

            tx_data = items[0].get('data', {})
            if not tx_data:
                logger.error("❌ Нет данных транзакции")
                return False

            # Подключение к сети
            chain_id = tx_data.get('chainId', 1)
            web3 = self._get_web3_connection(chain_id)
            if not web3:
                return False

            # Получаем начальные балансы для проверки
            initial_from_balance = self._get_native_balance(from_chain_id, wallet_address)
            if to_chain_id == SOLANA_CHAIN_ID:
                sol_address = self._get_sol_address_for_eth(wallet_address)
                initial_to_balance = self._get_solana_balance(sol_address) if sol_address else 0.0
            else:
                initial_to_balance = self._get_native_balance(to_chain_id, wallet_address)

            # Подготовка транзакции
            account = web3.eth.account.from_key(private_key)

            value_amount = tx_data.get('value', '0')
            if isinstance(value_amount, str):
                value_amount = int(value_amount) if value_amount != '0' else 0
            elif value_amount is None:
                value_amount = 0

            # Создание и оценка транзакции для получения лимита газа
            transaction_for_estimate = {
                'from': wallet_address,
                'to': Web3.to_checksum_address(tx_data['to']),
                'data': tx_data.get('data', '0x'),
                'value': value_amount,
                'nonce': web3.eth.get_transaction_count(wallet_address),
                'chainId': chain_id  # Добавляем chainId для EIP-155
            }

            try:
                estimated_gas = web3.eth.estimate_gas(transaction_for_estimate)
                gas_limit = int(estimated_gas * 1.2)
            except Exception as e:
                logger.warning(f"⚠️ Не удалось оценить газ: {e}")
                gas_limit = tx_data.get('gas', 200000)
                if isinstance(gas_limit, str):
                    gas_limit = int(gas_limit)
                gas_limit = int(gas_limit * 1.1)

            # Ожидание приемлемой цены газа с учетом лимита

            # Проверяем поддержку EIP-1559 (Type 2 transactions)
            try:
                latest_block = web3.eth.get_block('latest')
                supports_eip1559 = hasattr(latest_block, 'baseFeePerGas') and latest_block.baseFeePerGas is not None
            except:
                supports_eip1559 = False

            # Финальная транзакция
            if supports_eip1559:
                # EIP-1559 транзакция (Type 2)

                # Получаем актуальный gas_price от ноды (уже включает base + priority)
                current_gas_price = web3.eth.gas_price
                latest_block = web3.eth.get_block('latest')
                base_fee = latest_block.baseFeePerGas

                # maxPriorityFee: разница между рекомендуемым gas_price и base_fee, минимум 0.001 gwei
                max_priority_fee_per_gas = max(
                    current_gas_price - base_fee,
                    web3.to_wei('0.001', 'gwei')
                )
                # maxFeePerGas: gas_price + priority для запаса на рост base_fee
                max_fee_per_gas = current_gas_price + max_priority_fee_per_gas

                final_transaction = {
                    'to': Web3.to_checksum_address(tx_data['to']),
                    'data': tx_data.get('data', '0x'),
                    'value': value_amount,
                    'gas': gas_limit,
                    'maxFeePerGas': max_fee_per_gas,
                    'maxPriorityFeePerGas': max_priority_fee_per_gas,
                    'nonce': web3.eth.get_transaction_count(wallet_address),
                    'chainId': chain_id,
                    'type': 2  # EIP-1559 transaction type
                }
            else:
                # Legacy транзакция (Type 0)
                gas_price = self._wait_for_acceptable_gas_price(web3, gas_limit, chain_id)

                final_transaction = {
                    'to': Web3.to_checksum_address(tx_data['to']),
                    'data': tx_data.get('data', '0x'),
                    'value': value_amount,
                    'gas': gas_limit,
                    'gasPrice': gas_price,
                    'nonce': web3.eth.get_transaction_count(wallet_address),
                    'chainId': chain_id  # Добавляем chainId для EIP-155 (replay protection)
                }

            # Подпись и отправка
            signed_tx = web3.eth.account.sign_transaction(final_transaction, private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)

            # Хеш в БД СРАЗУ после отправки (AGENTS.md §14.3): дальше идёт долгое
            # ожидание поступления средств, и Ctrl+C / краш / обрыв RPC посреди него
            # не должен приводить к повторному бриджу тех же денег на следующем запуске.
            self._save_transaction_result(wallet_address, tx_hash.hex(), 0, 'tx_sent')

            # Получаем ссылку на explorer
            explorer_link = self._get_transaction_explorer_link(chain_id, tx_hash.hex())
            logger.info(f"📤 Транзакция отправлена: {explorer_link}")

            # Ждем небольшое время перед проверкой
            logger.info(f"⏰ Ожидание 30 секунд перед проверкой статуса транзакции...")
            time.sleep(30)

            # Проверяем статус транзакции в исходной сети
            try:
                tx_receipt = web3.eth.get_transaction_receipt(tx_hash)
                if tx_receipt.status == 1:
                    logger.success(f"✅ Транзакция подтверждена в {NETWORK_SETTINGS[chain_id]['name']}")
                    self._save_transaction_result(wallet_address, tx_hash.hex(), 0, 'awaiting_arrival')
                else:
                    logger.error(f"❌ Транзакция отклонена в {NETWORK_SETTINGS[chain_id]['name']}")
                    # Сеть откатила транзакцию — средства остались на кошельке,
                    # поэтому этот статус единственный, после которого повтор безопасен.
                    self._save_transaction_result(wallet_address, tx_hash.hex(), 0, 'reverted')
                    return False
            except Exception as e:
                logger.warning(f"⚠️ Не удалось получить статус транзакции: {e}")

            # Проверяем успешность через изменение балансов
            logger.info(f"🔍 Проверка поступления средств в {NETWORK_SETTINGS[to_chain_id]['name']}...")
            transaction_success = self._check_balance_changes(
                wallet_address, from_chain_id, to_chain_id, sent_amount,
                initial_from_balance, initial_to_balance
            )

            # Если балансы изменились, транзакция успешна
            if transaction_success:
                logger.success(f"✅ Транзакция подтверждена")

            # Сохранение результата
            if transaction_success:
                self._save_transaction_result(
                    wallet_address, tx_hash.hex(), quote_fee_eth, 'completed'
                )
                return True
            else:
                self._save_transaction_result(wallet_address, tx_hash.hex(), 0, 'failed')
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка выполнения транзакции: {e}")
            self._save_transaction_result(wallet_address, None, 0, 'error', str(e))
            return False

    def _save_transaction_result(self, wallet_address: str, tx_hash: str, bridge_fee: float, status: str, error_msg: str = None):
        """Сохранение результата (и промежуточного состояния) транзакции в БД.

        Два неочевидных момента:
        1. tx_hash пишем через COALESCE — ветка с ошибкой передаёт None, но затирать
           уже сохранённый хеш нельзя: именно по нему резюме понимает, что деньги ушли.
        2. Обновляем последнюю НЕзавершённую запись кошелька, а не строго 'pending'.
           После промежуточного 'tx_sent' условие status='pending' не совпадало ни с
           одной строкой, и финальный статус молча терялся (UPDATE на 0 строк).
        completed_at используем как «время последнего обновления» — имя колонки
        менять нельзя, это живое состояние пользователей.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE relay_progress
            SET tx_hash = COALESCE(?, tx_hash),
                bridge_fee = ?,
                status = ?,
                completed_at = CURRENT_TIMESTAMP,
                error_message = ?
            WHERE id = (
                SELECT id FROM relay_progress
                WHERE wallet_address = ?
                  AND status NOT IN ('completed', 'completed_no_confirmation')
                ORDER BY id DESC LIMIT 1
            )
        ''', (tx_hash, bridge_fee, status, error_msg, wallet_address))

        conn.commit()
        conn.close()

    def _save_to_csv(self, wallet_address: str, from_network: str, to_network: str,
                     amount: float, tx_hash: str, bridge_fee: float, status: str, quote_data: Dict = None):
        """Сохранение результата в CSV файл"""
        os.makedirs(os.path.dirname(self.result_path), exist_ok=True)

        with open(self.result_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Рассчитываем реальную полученную сумму и комиссию из котировки
            if quote_data and 'details' in quote_data and 'currencyOut' in quote_data['details']:
                currency_out = quote_data['details']['currencyOut']
                out_chain_id = currency_out.get('currency', {}).get('chainId', 0)
                amount_out_raw = int(currency_out['amount'])
                # Для Solana - 9 decimals, для EVM - 18 decimals
                if out_chain_id == SOLANA_CHAIN_ID:
                    amount_out_eth = amount_out_raw / 1_000_000_000  # SOL amount
                else:
                    amount_out_eth = float(Web3.from_wei(amount_out_raw, 'ether'))
                # Для кросс-чейн ETH->SOL комиссия берется из fees
                fees_section = quote_data.get('fees', {})
                relayer_fee = fees_section.get('relayer', {})
                if out_chain_id == SOLANA_CHAIN_ID and 'amountFormatted' in relayer_fee:
                    calculated_bridge_fee = float(relayer_fee['amountFormatted'])
                else:
                    calculated_bridge_fee = amount - float(amount_out_eth)
            else:
                # Fallback к примерной комиссии если нет данных котировки
                estimated_received = amount * 0.995  # Примерно 0.5% комиссия
                calculated_bridge_fee = amount - estimated_received
                amount_out_eth = estimated_received

                logger.warning("⚠️ Используем примерную комиссию, так как нет данных котировки")

            # Используем bridge_fee из базы данных, если он больше 0, иначе рассчитанный
            final_bridge_fee = bridge_fee if bridge_fee > 0 else calculated_bridge_fee

            writer.writerow([
                wallet_address,
                from_network.capitalize(),
                to_network.capitalize(),
                f"{amount:.8f}",
                tx_hash or 'N/A',
                f"{final_bridge_fee:.8f}" if final_bridge_fee > 0 else 'N/A',
                status.upper(),
                time.strftime('%Y-%m-%d %H:%M:%S'),
                f"{amount_out_eth:.8f}",
                f"{final_bridge_fee:.8f}"
            ])

    def _check_quote_fees(self, quote_data: Dict, amount_eth: float, from_chain_id: int, to_chain_id: int, amount_wei: int, wallet_address: str, sol_recipient: str = None, sol_sender: str = None) -> Dict:
        """Проверка комиссий в котировке перед выполнением с ожиданием снижения комиссии"""
        max_fee_usd = GAS.get('LIMIT_GAS_COST', 0.1)

        while True:
            if not quote_data or 'details' not in quote_data:
                logger.warning("⚠️ Нет детальной информации о комиссиях в котировке")
                return quote_data

            details = quote_data['details']

            if 'currencyOut' in details:
                # Для кросс-чейн маршрутов с Solana используем fees.relayer.amountUsd из API
                is_solana_route = (to_chain_id == SOLANA_CHAIN_ID or from_chain_id == SOLANA_CHAIN_ID)
                if is_solana_route:
                    fee_usd = 0.0
                    fees_section = quote_data.get('fees', {})
                    for fee_type in ['relayer', 'gas']:
                        fee_entry = fees_section.get(fee_type, {})
                        if 'amountUsd' in fee_entry:
                            fee_usd += float(fee_entry['amountUsd'])
                    if fee_usd == 0:
                        logger.info(f"ℹ️ Кросс-чейн Solana: комиссия не определена, пропускаем проверку")
                        return quote_data
                else:
                    amount_out_wei = int(details['currencyOut']['amount'])
                    amount_out_eth = float(Web3.from_wei(amount_out_wei, 'ether'))
                    actual_fee = amount_eth - amount_out_eth
                    eth_price = 3000
                    fee_usd = actual_fee * eth_price

                if fee_usd > max_fee_usd:
                    logger.warning(f"⚠️ Комиссия слишком высокая: ${fee_usd:.4f} > ${max_fee_usd}")
                    logger.warning(f"   💡 Ожидание снижения комиссии... Повторная проверка через {GAS['WHITE_TIMEOUT']} сек")

                    time.sleep(GAS['WHITE_TIMEOUT'])

                    logger.info("🔄 Получение новой котировки...")
                    new_quote, error_msg = self._get_quote(from_chain_id, to_chain_id, amount_wei, wallet_address, sol_recipient=sol_recipient, sol_sender=sol_sender)
                    if new_quote:
                        quote_data = new_quote
                        continue
                    else:
                        logger.warning("⚠️ Не удалось получить новую котировку, используем текущую")
                        return quote_data
                else:
                    logger.success(f"✅ Комиссия в пределах лимита: ${fee_usd:.4f} ≤ ${max_fee_usd}")
                    return quote_data
            else:
                logger.warning("⚠️ Нет информации о выходной сумме в котировке")
                return quote_data

    def _process_wallet(self, private_key: str, wallet_index: int) -> bool:
        """Обработка одного кошелька"""
        try:
            # Получение адреса кошелька (всегда ETH)
            account = Web3().eth.account.from_key(private_key)
            wallet_address = account.address

            wallet_record = self._get_wallet_record(private_key)
            if not wallet_record:
                logger.error(f"❌ Запись кошелька {wallet_address} не найдена в базе данных")
                return False

            if wallet_record['status'] in ('completed', 'completed_no_confirmation'):
                return True

            from_network = wallet_record['from_network']
            to_network = wallet_record['to_network']
            amount = wallet_record['amount']

            from_chain_id = NETWORK_MAPPING[from_network]
            to_chain_id = NETWORK_MAPPING[to_network]

            # Транзакция по кошельку уже отправлена — второй бридж означал бы
            # повторную трату реальных денег (деньги могут быть просто в пути).
            # 'reverted' — единственное исключение: сеть откатила tx, средства на месте.
            existing_tx_hash = wallet_record.get('tx_hash')
            if existing_tx_hash and wallet_record['status'] != 'reverted':
                logger.warning(
                    f"⚠️ {wallet_address}: транзакция уже отправлена "
                    f"(статус '{wallet_record['status']}') — повторный бридж пропущен"
                )
                logger.warning(f"   Проверьте вручную: {self._get_transaction_explorer_link(from_chain_id, existing_tx_hash)}")
                return False

            logger.info(f"🔄 Кошелек {wallet_index + 1}: {wallet_address}")

            # Определяем SOL адреса для маршрутов с Solana
            sol_recipient = None
            sol_sender = None
            sol_private_key = None
            wallet_pair = self.wallet_pairs.get(wallet_address)

            if to_chain_id == SOLANA_CHAIN_ID:
                if not wallet_pair:
                    logger.error(f"❌ SOL адрес не найден для {wallet_address}. Используйте мнемоники")
                    return False
                sol_recipient = wallet_pair['sol_address']
                logger.info(f"🔗 SOL получатель: {sol_recipient}")

            if from_chain_id == SOLANA_CHAIN_ID:
                if not wallet_pair:
                    logger.error(f"❌ SOL адрес не найден для {wallet_address}. Используйте мнемоники")
                    return False
                sol_sender = wallet_pair['sol_address']
                sol_private_key = wallet_pair['sol_private_key']
                logger.info(f"🔗 SOL отправитель: {sol_sender}")

            # Проверка балансов
            balances = self._check_balances(wallet_address, from_chain_id, to_chain_id)
            if not balances:
                logger.warning(f"⚠️ Нет балансов для бриджа у кошелька {wallet_address}")
                return False

            if from_network not in balances:
                logger.warning(f"⚠️ Нет баланса в сети {from_network} у кошелька {wallet_address}")
                return False

            # Проверка достаточности баланса
            available_balance = balances[from_network]['balance']
            min_balance = 0.01 if from_chain_id == SOLANA_CHAIN_ID else 0.0001
            if amount > available_balance:
                if available_balance > min_balance:
                    amount = available_balance * 0.95
                else:
                    logger.error(f"❌ {wallet_address}: Баланс слишком мал: {available_balance:.6f} {NETWORK_SETTINGS[from_chain_id]['native_symbol']}")
                    return False

            # Проверка минимальной суммы для бриджа
            token_symbol = NETWORK_SETTINGS[from_chain_id]['native_symbol']
            min_bridge = MINIMUM_BRIDGE_AMOUNTS.get(token_symbol, 0)
            if amount < min_bridge:
                logger.error(f"❌ {wallet_address}: Сумма {amount:.6f} {token_symbol} меньше минимальной для бриджа ({min_bridge} {token_symbol})")
                self._update_wallet_error(wallet_record['id'], f"Сумма {amount:.6f} меньше минимальной {min_bridge} {token_symbol}")
                return False

            # Получение котировки
            if from_chain_id == SOLANA_CHAIN_ID:
                # SOL -> EVM: amount в lamports
                amount_units = int(amount * 1_000_000_000)
            else:
                # EVM: amount в wei
                amount_units = Web3.to_wei(amount, 'ether')

            quote, error_msg = self._get_quote(
                from_chain_id, to_chain_id, amount_units, wallet_address,
                sol_recipient=sol_recipient, sol_sender=sol_sender
            )

            if not quote:
                self._update_wallet_error(wallet_record['id'], error_msg or "Неизвестная ошибка котировки")
                logger.error(f"❌ Не удалось получить котировку для кошелька {wallet_address}, пропускаем")
                return False

            # Проверка комиссий
            quote = self._check_quote_fees(
                quote, amount, from_chain_id, to_chain_id, amount_units, wallet_address,
                sol_recipient=sol_recipient, sol_sender=sol_sender
            )

            # Выполнение бриджа
            if from_chain_id == SOLANA_CHAIN_ID:
                # SOL -> EVM: используем Solana транзакцию
                bridge_success = self._execute_solana_bridge(
                    quote, wallet_address, sol_private_key,
                    from_chain_id, to_chain_id, amount
                )
            else:
                # EVM -> (EVM|SOL): используем EVM транзакцию
                bridge_success = self._execute_bridge(
                    quote, wallet_address, private_key,
                    from_chain_id, to_chain_id, amount
                )

            if not bridge_success:
                logger.error(f"❌ Ошибка выполнения бриджа для кошелька {wallet_address}")
                return False

            status = 'completed'

            # Сохранение в CSV
            last_tx_hash = None
            bridge_fee = 0
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT tx_hash, bridge_fee FROM relay_progress WHERE wallet_address = ? ORDER BY id DESC LIMIT 1', (wallet_address,))
            result = cursor.fetchone()
            if result:
                last_tx_hash, bridge_fee = result
            conn.close()

            self._save_to_csv(wallet_address, from_network, to_network, amount, last_tx_hash, bridge_fee or 0, status, quote)

            # Красивый вывод итогов кошелька
            try:
                token_symbol = NETWORK_SETTINGS[from_chain_id]['native_symbol']
                price_usd = self._get_native_token_price_in_usdt(from_chain_id)
                received_amount = amount - (bridge_fee or 0)

                display_address = wallet_address
                if to_chain_id == SOLANA_CHAIN_ID and sol_recipient:
                    display_address = f"{wallet_address} -> SOL:{sol_recipient[:12]}..."
                elif from_chain_id == SOLANA_CHAIN_ID and sol_sender:
                    display_address = f"SOL:{sol_sender[:12]}... -> {wallet_address}"

                log_wallet_summary(
                    display_address, amount, received_amount,
                    bridge_fee or 0, from_network, to_network,
                    token_symbol, price_usd
                )
            except Exception as e:
                logger.error(f"❌ Ошибка получения курса для итогов: {e}")
                print(f"\n{'='*20} {wallet_address} {'='*20}")
                print(f"     ✅ Обработан успешно: {amount:.6f} {NETWORK_SETTINGS[from_chain_id]['native_symbol']}")
                print(f"     Из {from_network} в {to_network}\n")

            return True

        except Exception as e:
            try:
                account = Web3().eth.account.from_key(private_key)
                wallet_address = account.address
                logger.error(f"❌ Ошибка обработки кошелька {wallet_address}: {e}")
            except:
                logger.error(f"❌ Ошибка обработки кошелька {wallet_index + 1}: {e}")
            return False

    def _check_resume_option(self) -> bool:
        """Проверка возможности продолжения работы"""
        if not os.path.exists(self.db_path):
            return False

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM relay_progress')
        total_count = cursor.fetchone()[0]
        # Незавершённым считаем всё, что не терминально: после промежуточных
        # 'tx_sent'/'awaiting_arrival'/'failed' счёт по status='pending' показывал 0
        # и меню врало, что вся работа выполнена.
        cursor.execute('SELECT COUNT(*) FROM relay_progress WHERE status NOT IN ("completed", "completed_no_confirmation")')
        pending_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM relay_progress WHERE status IN ("completed", "completed_no_confirmation")')
        completed_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM relay_progress WHERE error_count > 0')
        error_count = cursor.fetchone()[0]
        conn.close()

        if total_count > 0:
            logger.info(f"📊 Статистика базы данных:")
            logger.info(f"   📋 Всего записей: {total_count}")
            logger.info(f"   ⏳ Ожидающих: {pending_count}")
            logger.info(f"   ✅ Завершенных: {completed_count}")
            if error_count > 0:
                logger.info(f"   ❌ С ошибками: {error_count}")

            if pending_count > 0:
                choice = ui.menu("В базе есть незавершённая работа. Что делать?", [
                    ("▶️ Продолжить с того места, где остановились", "resume"),
                    ("🗑️ Очистить базу и начать заново", "restart"),
                ])
            else:
                choice = ui.menu("В базе все задания выполнены. Что делать?", [
                    ("▶️ Использовать базу — пропустить выполненные", "resume"),
                    ("🗑️ Очистить базу и создать новый план работ", "restart"),
                ])

            if choice == "restart":
                logger.info("🗑️ Очистка базы данных...")
                os.remove(self.db_path)
                self._init_database()
                return False

            logger.info("📂 Использование существующей базы данных")
            return True

        return False

    def _get_wallet_record(self, private_key: str) -> Optional[Dict]:
        """Получить запись кошелька из базы данных"""
        # Получаем адрес кошелька из приватного ключа
        try:
            account = Web3().eth.account.from_key(private_key)
            wallet_address = account.address
        except Exception as e:
            logger.error(f"❌ Ошибка получения адреса из приватного ключа: {e}")
            return None

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, wallet_address, from_network, to_network, amount, status, error_count, error_message, tx_hash
            FROM relay_progress
            WHERE wallet_address = ?
        ''', (wallet_address,))

        result = cursor.fetchone()
        conn.close()

        if result:
            return {
                'id': result[0],
                'wallet_address': result[1],
                'from_network': result[2],
                'to_network': result[3],
                'amount': result[4],
                'status': result[5],
                'error_count': result[6],
                'error_message': result[7],
                # tx_hash нужен резюме: по нему видно, что деньги уже отправлены
                'tx_hash': result[8]
            }
        return None

    def _update_wallet_error(self, wallet_id: int, error_message: str):
        """Обновить счетчик ошибок для кошелька"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE relay_progress
            SET error_count = error_count + 1, error_message = ?
            WHERE id = ?
        ''', (error_message, wallet_id))

        conn.commit()
        conn.close()

    def _get_native_token_price_in_usdt(self, chain_id: int) -> float:
        """Получение курса нативного токена сети в USDT"""
        # Маппинг chain_id на CoinGecko ID
        coingecko_ids = {
            1: 'ethereum',      # Ethereum - ETH
            10: 'ethereum',     # Optimism - ETH
            137: 'matic-network',  # Polygon - MATIC
            8453: 'ethereum',   # Base - ETH
            42161: 'ethereum',   # Arbitrum - ETH
            169: 'ethereum',   # Manta Pacific - ETH
            42170: 'ethereum',  # Arbitrum Nova - ETH
            59144: 'ethereum',  # Linea - ETH
            SOLANA_CHAIN_ID: 'solana'  # Solana - SOL
        }

        coingecko_id = coingecko_ids.get(chain_id, 'ethereum')
        network_name = NETWORK_SETTINGS[chain_id]['name']
        token_symbol = NETWORK_SETTINGS[chain_id]['native_symbol']

        # Попробуем несколько раз с разными прокси
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Используем случайный прокси для API запроса
                api_proxy = self._get_random_proxy_for_api()
                proxies = None
                if api_proxy:
                    proxies = {
                        'http': f'http://{api_proxy}',
                        'https': f'http://{api_proxy}'
                    }

                response = requests.get(
                    f'https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies=usd',
                    proxies=proxies,
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                price = data[coingecko_id]['usd']
                return float(price)

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Rate limit попытка {attempt + 1}, пробуем другой прокси...")
                    time.sleep(1)  # Небольшая пауза перед следующей попыткой
                    continue
                else:
                    raise e
            except Exception as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Ошибка API попытка {attempt + 1}: {e}")
                    time.sleep(1)
                    continue
                else:
                    raise e

        # Если все попытки провалились, используем fallback курсы
        logger.warning(f"⚠️ Не удалось получить курс {token_symbol} после {max_attempts} попыток, используем fallback")
        fallback_prices = {
            1: 3000.0,    # ETH
            10: 3000.0,   # ETH на Optimism
            137: 0.5,     # MATIC
            8453: 3000.0, # ETH на Base
            42161: 3000.0, # ETH on Arbitrum
            42170: 3000.0,  # ETH on Arbitrum Nova
            59144: 3000.0,  # ETH on Linea
            SOLANA_CHAIN_ID: 150.0  # SOL
        }
        return fallback_prices.get(chain_id, 3000.0)

    def _check_gas_cost_limit(self, chain_id: int, gas_limit: int, gas_price: int) -> bool:
        """Проверка лимита стоимости газа в текущей сети"""
        # Получаем курс нативного токена текущей сети
        token_price = self._get_native_token_price_in_usdt(chain_id)
        token_symbol = NETWORK_SETTINGS[chain_id]['native_symbol']
        network_name = NETWORK_SETTINGS[chain_id]['name']

        # Вычисляем стоимость газа в нативном токене
        gas_cost_wei = gas_limit * gas_price
        gas_cost_native = Web3.from_wei(gas_cost_wei, 'ether')

        # Конвертируем в USDT
        gas_cost_usdt = float(gas_cost_native) * token_price

        limit_usdt = GAS['LIMIT_GAS_COST']

        logger.info(f"⛽ Стоимость газа в {network_name}: {gas_cost_native:.6f} {token_symbol} (${gas_cost_usdt:.4f})")
        logger.info(f"📊 Лимит: ${limit_usdt}")

        if gas_cost_usdt > limit_usdt:
            logger.warning(f"⚠️ Газ слишком дорогой: ${gas_cost_usdt:.4f} > ${limit_usdt}")
            return False

        logger.success(f"✅ Газ в пределах лимита: ${gas_cost_usdt:.4f} ≤ ${limit_usdt}")
        return True

    def _wait_for_acceptable_gas_price(self, web3: Web3, gas_limit: int, chain_id: int) -> int:
        """Ожидание приемлемой цены газа"""
        while True:
            try:
                current_gas_price = web3.eth.gas_price

                if self._check_gas_cost_limit(chain_id, gas_limit, current_gas_price):
                    return current_gas_price

                logger.warning(f"⏳ Ожидание снижения цены газа... Повторная проверка через {GAS['WHITE_TIMEOUT']} сек")
                time.sleep(GAS['WHITE_TIMEOUT'])

            except Exception as e:
                logger.error(f"❌ Ошибка при проверке цены газа: {e}")
                # В случае ошибки используем умеренную цену
                return web3.to_wei('20', 'gwei')

    def _is_solana_route(self, from_chain_id: int, to_chain_id: int) -> bool:
        """Проверяет, участвует ли Solana в маршруте"""
        return from_chain_id == SOLANA_CHAIN_ID or to_chain_id == SOLANA_CHAIN_ID

    def run(self):
        """Основная функция запуска"""
        try:
            logger.info("🌉 Relay Bridge - запуск обработки кошельков")

            # Проверка возможности продолжения
            resume = self._check_resume_option()

            # Если не resume mode, то выбираем сети и токены
            if not resume:
                logger.info("\n" + "="*60)
                logger.info("🔧 НАСТРОЙКА ПАРАМЕТРОВ МОСТА")
                logger.info("="*60)

                # Шаг 1: Выбор исходной сети и токена
                logger.info("\n📤 ШАГ 1: Выбор сети и токена для отправки")
                from_chain_id, from_token = self._select_network_and_token("Откуда отправить?")
                if from_chain_id is None:
                    logger.info("👋 Работа отменена пользователем")
                    return

                logger.success(f"✅ Выбрано: {NETWORK_SETTINGS[from_chain_id]['name']} → {from_token}")

                # Шаг 2: Выбор целевой сети и токена
                logger.info(f"\n📥 ШАГ 2: Выбор сети и токена для получения")
                to_chain_id, to_token = self._select_network_and_token("Куда отправить?", exclude_chain_id=from_chain_id)
                if to_chain_id is None:
                    logger.info("👋 Работа отменена пользователем")
                    return

                logger.success(f"✅ Выбрано: {NETWORK_SETTINGS[to_chain_id]['name']} → {to_token}")

                # Если маршрут включает Solana - загружаем мнемоники
                if self._is_solana_route(from_chain_id, to_chain_id):
                    logger.info("\n🔑 Маршрут включает Solana — загружаем мнемоники для деривации ETH+SOL ключей")
                    self.use_mnemonics = True
                    self.private_keys = self._load_mnemonics_and_derive_keys()

                    if not self.private_keys:
                        logger.error("❌ Не удалось загрузить мнемоники. Проверьте колонку mnemonic в data/data.csv")
                        return

                    # Показываем пары кошельков
                    logger.info(f"\n📋 Загруженные пары кошельков:")
                    for eth_addr, pair in self.wallet_pairs.items():
                        logger.info(f"   ETH: {eth_addr}")
                        logger.info(f"   SOL: {pair['sol_address']}")
                        logger.info(f"   {'─'*50}")
                else:
                    # Для EVM->EVM маршрутов используем приватные ключи как раньше
                    self.private_keys = self._load_private_keys()

                if not self.private_keys:
                    logger.error("❌ Нет ключей для работы")
                    return

                # Показываем итоговую конфигурацию
                logger.info("="*60)
                logger.info("🔧 ИТОГОВАЯ КОНФИГУРАЦИЯ")
                logger.info("="*60)
                logger.info(f"🌐 Из сети: {NETWORK_SETTINGS[from_chain_id]['name']}")
                logger.info(f"💎 Токен отправки: {from_token}")
                logger.info(f"🌐 В сеть: {NETWORK_SETTINGS[to_chain_id]['name']}")
                logger.info(f"💎 Токен получения: {to_token}")

                if isinstance(SUM_TO_RELAY[0], str):
                    logger.info(f"💰 Сумма: {SUM_TO_RELAY[0]}-{SUM_TO_RELAY[1]}% от баланса")
                else:
                    logger.info(f"💰 Сумма: {SUM_TO_RELAY[0]}-{SUM_TO_RELAY[1]} {from_token}")

                logger.info(f"👛 Кошельков: {len(self.private_keys)}")
                if self.use_mnemonics:
                    logger.info(f"🔑 Режим: мнемоники (ETH+SOL деривация)")
                logger.info("="*60 + "\n")

                choice = ui.confirm("Запустить мост с этими параметрами?",
                                    default=True)

                if not choice:
                    logger.info("👋 Работа отменена пользователем")
                    return

                # Создание плана работ с новыми параметрами
                if not self._create_work_plan(from_chain_id, to_chain_id):
                    return
            else:
                # Resume mode - проверяем нужны ли мнемоники
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('SELECT DISTINCT to_network FROM relay_progress LIMIT 1')
                row = cursor.fetchone()
                cursor.execute('SELECT DISTINCT from_network FROM relay_progress LIMIT 1')
                from_row = cursor.fetchone()
                conn.close()

                solana_involved = (row and row[0] == 'solana') or (from_row and from_row[0] == 'solana')
                if solana_involved:
                    logger.info("🔑 Resume: маршрут с Solana — загружаем мнемоники")
                    self.use_mnemonics = True
                    self.private_keys = self._load_mnemonics_and_derive_keys()
                else:
                    self.private_keys = self._load_private_keys()

                if not self.private_keys:
                    logger.error("❌ Нет ключей для работы")
                    return

                logger.info("📂 Продолжение работы с существующими параметрами")

            # Обработка кошельков
            total_wallets = len(self.private_keys)
            successful = 0

            for i, private_key in enumerate(self.private_keys):
                success = self._process_wallet(private_key, i)
                if success:
                    successful += 1

                if i < total_wallets - 1:
                    time.sleep(random.uniform(2, 5))

            logger.success(f"🎉 Работа завершена! Успешно обработано: {successful}/{total_wallets}")

        except KeyboardInterrupt:
            logger.warning("👋 Работа прервана пользователем")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")

def main():
    """Точка входа в программу"""
    bridge = RelayBridge()
    bridge.run()

if __name__ == "__main__":
    main()
