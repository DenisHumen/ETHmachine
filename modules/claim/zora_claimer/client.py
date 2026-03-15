"""
Zora Protocol Rewards Claimer Client
Проверка и клейм наград протокола Zora на Base и Zora сетях
"""

import random
from typing import Optional, Tuple, Dict
from web3 import Web3
from eth_account import Account

from modules.simple_logger import logger
from modules.proxy_manager import parse_proxy
from config.modules.cfg_claimer import (
    PROTOCOL_REWARDS_CONTRACT,
    CLAIMER_NETWORKS,
    MIN_CLAIM_AMOUNT_ETH,
    MIN_GAS_BALANCE_ETH,
    CLAIM_TO_SELF,
    CLAIM_TO_ADDRESS,
)
from config.modules.cfg_base import (
    WHAITE_TRANSACTION_PENDING,
    WHAITE_TRANSACTION_PENDING_COUNT,
    TX_SEND_ATTEMPTS,
)

# Минимальный ABI для ProtocolRewards контракта
PROTOCOL_REWARDS_ABI = [
    {
        "inputs": [{"name": "", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "withdraw",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
]


class ZoraClaimerClient:
    """Клиент для клейма Zora Protocol Rewards"""

    def __init__(self, private_key: str, proxy: Optional[str] = None):
        self.private_key = private_key if private_key.startswith('0x') else f'0x{private_key}'
        self.account = Account.from_key(self.private_key)
        self.address = self.account.address
        self.proxy = proxy

    def _get_web3(self, network: str) -> Optional[Web3]:
        """Получить Web3 инстанс для указанной сети"""
        net_config = CLAIMER_NETWORKS.get(network)
        if not net_config or not net_config.get('enabled'):
            return None

        rpc_urls = list(net_config['rpc_urls'])
        random.shuffle(rpc_urls)

        request_kwargs = {'timeout': 30}
        if self.proxy:
            proxy_url = parse_proxy(self.proxy)
            if proxy_url:
                request_kwargs['proxies'] = {'http': proxy_url, 'https': proxy_url}

        from web3.providers import HTTPProvider

        for rpc_url in rpc_urls:
            try:
                provider = HTTPProvider(rpc_url, request_kwargs=request_kwargs)
                w3 = Web3(provider)
                if w3.is_connected():
                    return w3
            except Exception:
                continue

        logger.error(f"[{self.address}] Не удалось подключиться к {network}")
        return None

    def _get_contract(self, w3: Web3):
        """Получить инстанс контракта"""
        return w3.eth.contract(
            address=Web3.to_checksum_address(PROTOCOL_REWARDS_CONTRACT),
            abi=PROTOCOL_REWARDS_ABI
        )

    def check_claimable(self, network: str) -> Tuple[int, float]:
        """
        Проверить доступный для клейма баланс

        Returns:
            (claimable_wei, claimable_eth)
        """
        w3 = self._get_web3(network)
        if not w3:
            return 0, 0.0

        try:
            contract = self._get_contract(w3)
            balance_wei = contract.functions.balanceOf(self.address).call()
            balance_eth = float(Web3.from_wei(balance_wei, 'ether'))
            return balance_wei, balance_eth
        except Exception as e:
            logger.error(f"[{self.address}] Ошибка проверки баланса на {network}: {e}")
            return 0, 0.0

    def check_gas_balance(self, network: str) -> float:
        """Проверить баланс ETH для газа"""
        w3 = self._get_web3(network)
        if not w3:
            return 0.0

        try:
            balance_wei = w3.eth.get_balance(self.address)
            return float(Web3.from_wei(balance_wei, 'ether'))
        except Exception as e:
            logger.error(f"[{self.address}] Ошибка проверки баланса газа на {network}: {e}")
            return 0.0

    def claim(self, network: str) -> Dict:
        """
        Выполнить клейм наград на указанной сети

        Returns:
            dict с результатами: success, tx_hash, claimed_wei, claimed_eth,
            gas_used, gas_price, gas_cost_eth, error
        """
        result = {
            'success': False,
            'tx_hash': None,
            'explorer_link': None,
            'claimed_wei': '0',
            'claimed_eth': 0.0,
            'gas_used': None,
            'gas_price': None,
            'gas_cost_eth': 0.0,
            'error': None,
        }

        net_config = CLAIMER_NETWORKS.get(network)
        if not net_config:
            result['error'] = f'Неизвестная сеть: {network}'
            return result

        w3 = self._get_web3(network)
        if not w3:
            result['error'] = f'Не удалось подключиться к {network}'
            return result

        try:
            contract = self._get_contract(w3)

            # 1. Проверяем claimable баланс
            claimable_wei = contract.functions.balanceOf(self.address).call()
            claimable_eth = float(Web3.from_wei(claimable_wei, 'ether'))

            if claimable_eth < MIN_CLAIM_AMOUNT_ETH:
                result['error'] = f'Баланс {claimable_eth:.8f} ETH < минимум {MIN_CLAIM_AMOUNT_ETH} ETH'
                return result

            # 2. Проверяем баланс для газа
            gas_balance = w3.eth.get_balance(self.address)
            gas_balance_eth = float(Web3.from_wei(gas_balance, 'ether'))

            if gas_balance_eth < MIN_GAS_BALANCE_ETH:
                result['error'] = f'Недостаточно ETH для газа: {gas_balance_eth:.8f} < {MIN_GAS_BALANCE_ETH}'
                return result

            # 3. Определяем адрес получателя
            to_address = self.address
            if not CLAIM_TO_SELF and CLAIM_TO_ADDRESS:
                to_address = Web3.to_checksum_address(CLAIM_TO_ADDRESS)

            # 4. Строим транзакцию withdraw(to, 0) - 0 значит забрать всё
            nonce = w3.eth.get_transaction_count(self.address)
            chain_id = net_config['chain_id']

            # Оцениваем газ
            try:
                gas_estimate = contract.functions.withdraw(
                    to_address, 0
                ).estimate_gas({'from': self.address})
                gas_limit = int(gas_estimate * 1.3)  # +30% запас
            except Exception as e:
                logger.warning(f"[{self.address}] Не удалось оценить газ на {network}: {e}, используем 100000")
                gas_limit = 100000

            # Получаем цену газа
            try:
                gas_price_wei = w3.eth.gas_price
                # Для Base/L2 сетей используем EIP-1559 если поддерживается
                try:
                    latest_block = w3.eth.get_block('latest')
                    base_fee = latest_block.get('baseFeePerGas', 0)
                    if base_fee > 0:
                        max_priority_fee = w3.eth.max_priority_fee
                        max_fee = base_fee * 2 + max_priority_fee

                        tx = contract.functions.withdraw(to_address, 0).build_transaction({
                            'from': self.address,
                            'nonce': nonce,
                            'gas': gas_limit,
                            'maxFeePerGas': max_fee,
                            'maxPriorityFeePerGas': max_priority_fee,
                            'chainId': chain_id,
                        })
                    else:
                        raise ValueError("No base fee")
                except Exception:
                    tx = contract.functions.withdraw(to_address, 0).build_transaction({
                        'from': self.address,
                        'nonce': nonce,
                        'gas': gas_limit,
                        'gasPrice': gas_price_wei,
                        'chainId': chain_id,
                    })
            except Exception as e:
                result['error'] = f'Ошибка построения транзакции: {e}'
                return result

            # 5. Проверяем, что стоимость газа не превышает клейм
            estimated_gas_cost = gas_limit * gas_price_wei
            estimated_gas_cost_eth = float(Web3.from_wei(estimated_gas_cost, 'ether'))

            if estimated_gas_cost_eth >= claimable_eth:
                result['error'] = (
                    f'Газ ({estimated_gas_cost_eth:.8f} ETH) >= клейм ({claimable_eth:.8f} ETH)'
                )
                return result

            # 6. Подписываем и отправляем
            for attempt in range(TX_SEND_ATTEMPTS):
                try:
                    signed_tx = w3.eth.account.sign_transaction(tx, self.private_key)
                    # Совместимость: eth_account <0.12 — rawTransaction, >=0.12 — raw_transaction
                    raw_tx = getattr(signed_tx, 'raw_transaction', None) or signed_tx.rawTransaction
                    tx_hash = w3.eth.send_raw_transaction(raw_tx)
                    tx_hash_hex = tx_hash.hex()

                    logger.info(
                        f"[{self.address}] TX отправлена на {network}: {tx_hash_hex}"
                    )

                    # 7. Ждём подтверждение
                    import time
                    for check in range(WHAITE_TRANSACTION_PENDING_COUNT):
                        try:
                            receipt = w3.eth.get_transaction_receipt(tx_hash)
                            if receipt:
                                if receipt['status'] == 1:
                                    actual_gas_cost = receipt['gasUsed'] * receipt.get('effectiveGasPrice', gas_price_wei)
                                    actual_gas_cost_eth = float(Web3.from_wei(actual_gas_cost, 'ether'))

                                    explorer_link = f"{net_config['explorer_tx']}{tx_hash_hex}"

                                    result['success'] = True
                                    result['tx_hash'] = tx_hash_hex
                                    result['explorer_link'] = explorer_link
                                    result['claimed_wei'] = str(claimable_wei)
                                    result['claimed_eth'] = claimable_eth
                                    result['gas_used'] = str(receipt['gasUsed'])
                                    result['gas_price'] = str(receipt.get('effectiveGasPrice', gas_price_wei))
                                    result['gas_cost_eth'] = actual_gas_cost_eth
                                    return result
                                else:
                                    result['error'] = f'Транзакция reverted: {tx_hash_hex}'
                                    return result
                        except Exception:
                            pass
                        time.sleep(WHAITE_TRANSACTION_PENDING)

                    result['error'] = f'Таймаут ожидания транзакции: {tx_hash_hex}'
                    result['tx_hash'] = tx_hash_hex
                    return result

                except Exception as e:
                    if attempt < TX_SEND_ATTEMPTS - 1:
                        logger.warning(
                            f"[{self.address}] Попытка {attempt + 1}/{TX_SEND_ATTEMPTS} failed: {e}"
                        )
                        import time
                        time.sleep(2)
                    else:
                        result['error'] = f'Все попытки отправки TX исчерпаны: {e}'
                        return result

        except Exception as e:
            result['error'] = f'Ошибка клейма: {e}'
            return result

        return result
