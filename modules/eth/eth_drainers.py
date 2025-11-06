import os
import csv
import time
import random
from web3 import Web3
from eth_account import Account
from modules.eth.rpc_return_module import get_network_rpc_selection
from config.config import EVM_MAIN_WALLET, MAIN_PROXY, NUM_THREADS
from config.networks import get_explorer_url
from colorama import Fore, Style, init
from itertools import cycle
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger
from pathlib import Path

init()

# Настройка логирования для модуля drainers
def setup_drainer_logging():
    """Настраивает логирование для модуля дренирования"""
    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f'drainer_{timestamp}.log'
    
    # Добавляем обработчик для записи в файл
    logger.add(
        log_file,
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level="DEBUG",
        encoding="utf-8"
    )
    
    logger.info(f"Логирование настроено. Файл: {log_file}")

def process_single_wallet(private_key, rpc_url, explorer_url, wallet_index, total_wallets):
    """Обрабатывает один кошелек в отдельном потоке"""
    session = None
    try:
        dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Получение аккаунта
        account = Account.from_key(private_key)
        wallet_address = account.address
        
        # Подключение к Web3 с прокси если есть
        if MAIN_PROXY:
            proxies = {'http': MAIN_PROXY, 'https': MAIN_PROXY}
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'proxies': proxies}))
        else:
            w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        if not w3.is_connected():
            logger.error(f"Кошелек {wallet_index}/{total_wallets}: {wallet_address} - Не удалось подключиться к RPC")
            return {
                'wallet': wallet_address,
                'balance': '0',
                'status': 'connection_error',
                'tx_hash': '',
                'explorer_link': '',
                'error': 'Не удалось подключиться к RPC'
            }
        
        # Получение баланса
        balance_wei = w3.eth.get_balance(wallet_address)
        balance_eth = w3.from_wei(balance_wei, 'ether')
        
        if balance_wei == 0:
            logger.warning(f"[{dt_str}] Кошелек {wallet_index}/{total_wallets}: {wallet_address} - Пустой (0 ETH)")
            return {
                'wallet': wallet_address,
                'balance': '0',
                'status': 'empty',
                'tx_hash': '',
                'explorer_link': '',
                'error': 'Нулевой баланс'
            }
        
        logger.info(f"[{dt_str}] Кошелек {wallet_index}/{total_wallets}: {wallet_address} - Баланс: {balance_eth} ETH")
        
        # Получение газа для транзакции
        gas_price = w3.eth.gas_price
        
        # Получение nonce
        nonce = w3.eth.get_transaction_count(wallet_address)
        
        # Проверяем поддержку EIP-1559
        try:
            latest_block = w3.eth.get_block('latest')
            supports_eip1559 = hasattr(latest_block, 'baseFeePerGas') and latest_block.baseFeePerGas is not None
        except:
            supports_eip1559 = False
        
        # Построение тестовой транзакции для оценки газа
        if supports_eip1559:
            # EIP-1559 транзакция
            try:
                max_priority_fee = w3.eth.max_priority_fee
            except:
                max_priority_fee = w3.to_wei(1, 'gwei')  # 1 gwei fallback
            
            max_fee_per_gas = int(gas_price * 1.5)  # Увеличиваем множитель
            
            test_tx = {
                'type': 0x2,
                'from': Web3.to_checksum_address(wallet_address),
                'to': Web3.to_checksum_address(EVM_MAIN_WALLET),
                'value': 1000000,  # Тестовое значение
                'nonce': nonce,
                'chainId': w3.eth.chain_id,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': min(max_priority_fee, max_fee_per_gas)
            }
        else:
            # Legacy транзакция
            test_tx = {
                'from': Web3.to_checksum_address(wallet_address),
                'to': Web3.to_checksum_address(EVM_MAIN_WALLET),
                'value': 1000000,  # Тестовое значение
                'nonce': nonce,
                'gasPrice': int(gas_price * 1.5)  # Увеличиваем множитель
            }
        
        # Оценка газа
        try:
            estimated_gas = w3.eth.estimate_gas(test_tx)
            gas_limit = int(estimated_gas * 1.5)  # Увеличиваем запас до 50%
        except Exception as e:
            logger.warning(f"Не удалось оценить газ, используем 21000: {e}")
            gas_limit = 25000  # Увеличиваем базовый лимит
        
        # Расчет стоимости газа
        if supports_eip1559:
            gas_cost = gas_limit * max_fee_per_gas
        else:
            gas_cost = gas_limit * int(gas_price * 1.5)
        
        # Проверка достаточности средств для газа
        if balance_wei <= gas_cost:
            logger.warning(f"⚠️ Недостаточно средств для оплаты газа. Баланс: {w3.from_wei(balance_wei, 'ether')} ETH, Газ: {w3.from_wei(gas_cost, 'ether')} ETH")
            return {
                'wallet': wallet_address,
                'balance': str(balance_eth),
                'status': 'insufficient_gas',
                'tx_hash': '',
                'explorer_link': '',
                'error': f'Недостаточно средств для газа. Нужно: {w3.from_wei(gas_cost, "ether"):.8f} ETH'
            }
        
        # Сумма к отправке (баланс минус газ с дополнительным запасом)
        amount_to_send = balance_wei - int(gas_cost * 1.1)  # Дополнительный запас 10%
        
        if amount_to_send <= 0:
            logger.warning(f"⚠️ После вычета газа сумма к отправке <= 0")
            return {
                'wallet': wallet_address,
                'balance': str(balance_eth),
                'status': 'insufficient_amount',
                'tx_hash': '',
                'explorer_link': '',
                'error': 'Сумма к отправке после вычета газа <= 0'
            }
        
        # Построение финальной транзакции
        if supports_eip1559:
            transaction = {
                'type': 0x2,
                'from': Web3.to_checksum_address(wallet_address),
                'to': Web3.to_checksum_address(EVM_MAIN_WALLET),
                'value': amount_to_send,
                'gas': gas_limit,
                'nonce': nonce,
                'chainId': w3.eth.chain_id,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': min(max_priority_fee, max_fee_per_gas)
            }
        else:
            transaction = {
                'from': Web3.to_checksum_address(wallet_address),
                'to': Web3.to_checksum_address(EVM_MAIN_WALLET),
                'value': amount_to_send,
                'gas': gas_limit,
                'nonce': nonce,
                'gasPrice': int(gas_price * 1.5)
            }
        
        # Подписание транзакции
        signed_txn = w3.eth.account.sign_transaction(transaction, private_key)
        
        # Отправка транзакции
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        tx_hash_hex = w3.to_hex(tx_hash)
        
        logger.info(f"📤 Транзакция отправлена: {tx_hash_hex}")
        logger.info(f"🔗 Explorer: {explorer_url}{tx_hash_hex}")
        
        # Ожидание подтверждения
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            if receipt.status == 1:
                amount_sent_eth = w3.from_wei(amount_to_send, 'ether')
                logger.success(f"✅ Успешно отправлено {amount_sent_eth:.8f} ETH")
                return {
                    'wallet': wallet_address,
                    'balance': str(balance_eth),
                    'status': 'success',
                    'tx_hash': tx_hash_hex,
                    'explorer_link': f"{explorer_url}{tx_hash_hex}",
                    'error': '',
                    'amount_sent': f"{amount_sent_eth:.8f}"
                }
            else:
                logger.error(f"❌ Транзакция провалена")
                return {
                    'wallet': wallet_address,
                    'balance': str(balance_eth),
                    'status': 'failed',
                    'tx_hash': tx_hash_hex,
                    'explorer_link': f"{explorer_url}{tx_hash_hex}",
                    'error': 'Транзакция провалена'
                }
        except Exception as e:
            logger.error(f"❌ Timeout при ожидании подтверждения: {str(e)[:50]}...")
            return {
                'wallet': wallet_address,
                'balance': str(balance_eth),
                'status': 'timeout',
                'tx_hash': tx_hash_hex,
                'explorer_link': f"{explorer_url}{tx_hash_hex}",
                'error': f'Timeout: {str(e)[:100]}'
            }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Ошибка при обработке кошелька {private_key[:10]}...: {error_msg[:100]}...")
        return {
            'wallet': account.address if 'account' in locals() else 'unknown',
            'balance': str(balance_eth) if 'balance_eth' in locals() else '0',
            'status': 'error',
            'tx_hash': '',
            'explorer_link': '',
            'error': error_msg[:200]
        }

def eth_drainers():
    """Дренирование всех кошельков из private_keys.txt на главный кошелек, поддержка ВСЕХ сетей"""
    # Настраиваем логирование
    setup_drainer_logging()
    
    logger.info("="*80)
    logger.info("🚀 Запуск модуля дренирования кошельков")
    logger.info("="*80)

    # Выбор сети и получение RPC
    rpc_urls_list, network_type, clean_network = get_network_rpc_selection()
    if rpc_urls_list is None:
        logger.error("❌ Не удалось получить данные сети")
        return

    private_keys_file = 'data/private_keys.txt'
    if not os.path.exists(private_keys_file):
        logger.error(f"❌ Файл {private_keys_file} не найден")
        return

    with open(private_keys_file, 'r') as f:
        private_keys = [line.strip() for line in f.readlines() if line.strip()]

    if not private_keys:
        logger.error("❌ Приватные ключи не найдены")
        return

    logger.success(f"📂 Загружено {len(private_keys)} приватных ключей")

    # Проверка главного кошелька
    if not EVM_MAIN_WALLET:
        logger.error("❌ EVM_MAIN_WALLET не настроен в config.py")
        return

    if not Web3.is_address(EVM_MAIN_WALLET):
        logger.error("❌ Некорректный адрес главного кошелька")
        return

    logger.info(f"🎯 Главный кошелек: {EVM_MAIN_WALLET}")

    result_file = 'result/result.csv'
    os.makedirs('result', exist_ok=True)

    results = []
    successful_transactions = 0
    failed_transactions = 0

    # Настройка прогресс-бара
    total_wallets = len(private_keys)
    completed_wallets = 0
    bar_length = 50
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_cycle = cycle(spinner)
    
    logger.info("-"*80)
    logger.info("🔄 Начинаем дренирование кошельков...")
    logger.info("-"*80)
    
    if rpc_urls_list == 'ALL_NETWORKS':
        all_networks = network_type  # network_type содержит словарь сетей
        logger.info(f"🌍 Проверка ВСЕХ сетей: {len(all_networks)}")
        for network_name, rpc_list in all_networks.items():
            clean_network = network_name.replace('🚀 ', '')
            explorer_url = get_explorer_url(network_name)
            logger.info(f"\n--- Сеть: {clean_network} ---")
            # Для каждой сети - многопоточная обработка
            with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
                future_to_wallet = {
                    executor.submit(
                        process_single_wallet,
                        private_key,
                        random.choice(rpc_list),
                        explorer_url,
                        i + 1,
                        len(private_keys)
                    ): (private_key, i + 1)
                    for i, private_key in enumerate(private_keys)
                }
                for future in as_completed(future_to_wallet):
                    private_key, wallet_index = future_to_wallet[future]
                    try:
                        result = future.result(timeout=600)
                        result['network'] = clean_network
                        results.append(result)
                        if result['status'] == 'success':
                            successful_transactions += 1
                        else:
                            failed_transactions += 1
                    except Exception as e:
                        failed_transactions += 1
                        results.append({
                            'wallet': 'unknown',
                            'balance': '0',
                            'status': 'exception',
                            'tx_hash': '',
                            'explorer_link': '',
                            'error': str(e),
                            'network': clean_network
                        })
        # Сохраняем результаты по всем сетям
        logger.info(f"\n\n💾 Сохраняем результаты...")
        with open(result_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['wallet', 'balance', 'status', 'tx_hash', 'explorer_link', 'error', 'amount_sent', 'network']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for result in results:
                writer.writerow(result)
        logger.success(f"💾 Результаты сохранены в {result_file}")
        logger.info("="*80 + "\n")
        logger.info("📊 ИТОГИ ДРЕНИРОВАНИЯ:")
        logger.info(f"📈 Всего кошельков обработано: {len(results)}")
        logger.success(f"✅ Успешных транзакций: {successful_transactions}")
        logger.error(f"❌ Неудачных транзакций: {failed_transactions}")
        return

    # Выбираем случайный RPC из списка
    rpc_url = random.choice(rpc_urls_list)
    
    logger.info(f"🌐 Выбрана сеть: {clean_network} ({network_type})")
    logger.info(f"🔗 RPC URL: {rpc_url}")
    logger.info(f"🧵 Потоков: {NUM_THREADS}")
    
    # Получаем URL эксплорера для выбранной сети (добавляем эмодзи обратно)
    explorer_url = get_explorer_url(f"🚀 {clean_network}")
    logger.info(f"🔍 Explorer URL: {explorer_url}")
    
    # Подключение к Web3
    if MAIN_PROXY:
        proxies = {'http': MAIN_PROXY, 'https': MAIN_PROXY}
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'proxies': proxies}))
        proxy_hidden = f"{MAIN_PROXY.rsplit('.', 1)[0]}.x:{MAIN_PROXY.split(':')[-1]}" if '@' not in MAIN_PROXY else f"xxxx:xxx@{MAIN_PROXY.split('@')[-1].rsplit('.', 1)[0]}.x:{MAIN_PROXY.split(':')[-1]}"
        logger.info(f"🔀 Используется прокси: {proxy_hidden}")
    else:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        logger.warning("⚠️ Прокси не используется")
    
    if not w3.is_connected():
        logger.error("❌ Не удалось подключиться к сети")
        return
    
    logger.success("✅ Подключение к сети установлено")
    
    # Загрузка приватных ключей
    private_keys_file = 'data/private_keys.txt'
    if not os.path.exists(private_keys_file):
        logger.error(f"❌ Файл {private_keys_file} не найден")
        return
    
    with open(private_keys_file, 'r') as f:
        private_keys = [line.strip() for line in f.readlines() if line.strip()]
    
    if not private_keys:
        logger.error("❌ Приватные ключи не найдены")
        return
    
    logger.success(f"📂 Загружено {len(private_keys)} приватных ключей")
    
    # Проверка главного кошелька
    if not EVM_MAIN_WALLET:
        logger.error("❌ EVM_MAIN_WALLET не настроен в config.py")
        return
    
    if not Web3.is_address(EVM_MAIN_WALLET):
        logger.error("❌ Некорректный адрес главного кошелька")
        return
    
    logger.info(f"🎯 Главный кошелек: {EVM_MAIN_WALLET}")
    
    # Подготовка файла результатов
    result_file = 'result/result.csv'
    os.makedirs('result', exist_ok=True)
    
    results = []
    successful_transactions = 0
    failed_transactions = 0
    
    # Настройка прогресс-бара
    total_wallets = len(private_keys)
    completed_wallets = 0
    bar_length = 50
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_cycle = cycle(spinner)
    
    logger.info("-"*80)
    logger.info("🔄 Начинаем дренирование кошельков...")
    logger.info("-"*80)
    
    # Многопоточная обработка кошельков
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        # Создаем задачи для всех кошельков
        future_to_wallet = {
            executor.submit(
                process_single_wallet,
                private_key,
                random.choice(rpc_urls_list),  # Случайный RPC для каждого потока
                explorer_url,
                i + 1,
                total_wallets
            ): (private_key, i + 1)
            for i, private_key in enumerate(private_keys)
        }
        
        # Обрабатываем завершенные задачи
        for future in as_completed(future_to_wallet):
            private_key, wallet_index = future_to_wallet[future]
            
            try:
                result = future.result(timeout=600)  # 10 минут на кошелек
                results.append(result)
                
                if result['status'] == 'success':
                    successful_transactions += 1
                    status_color = Fore.GREEN
                    status_icon = "✅"
                    status_info = f"Отправлено {result.get('amount_sent', 'N/A')} ETH"
                else:
                    failed_transactions += 1
                    status_color = Fore.RED
                    status_icon = "❌"
                    status_info = result.get('error', 'Неизвестная ошибка')[:30]
                
                wallet_address = result.get('wallet', 'unknown')
                
            except Exception as e:
                failed_transactions += 1
                status_color = Fore.RED
                status_icon = "❌"
                status_info = f"Исключение: {str(e)[:20]}..."
                wallet_address = 'unknown'
                
                results.append({
                    'wallet': 'unknown',
                    'balance': '0',
                    'status': 'exception',
                    'tx_hash': '',
                    'explorer_link': '',
                    'error': str(e)
                })
            
            finally:
                # Обновление прогресс-бара
                completed_wallets += 1
                progress = int((completed_wallets / total_wallets) * bar_length)
                progress_percent = (completed_wallets / total_wallets) * 100
                bar = "█" * progress + "░" * (bar_length - progress)
                spinner_frame = next(spinner_cycle)
                
                remaining_wallets = total_wallets - completed_wallets
                
                print(
                    f"\r{Fore.BLUE}[{bar}] {completed_wallets}/{total_wallets} ({progress_percent:.1f}%) | "
                    f"{spinner_frame} | ✅{successful_transactions} | ❌{failed_transactions} | "
                    f"Осталось: {remaining_wallets} | {status_color}{status_icon} {wallet_address[:10] if wallet_address != 'unknown' else 'unknown'}...{wallet_address[-6:] if wallet_address != 'unknown' else ''} | {status_info}{Style.RESET_ALL}",
                    end="",
                    flush=True,
                )
    
    # Сохранение результатов в CSV
    logger.info(f"\n\n💾 Сохраняем результаты...")
    with open(result_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['wallet', 'balance', 'status', 'tx_hash', 'explorer_link', 'error', 'amount_sent']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result)
    
    # Итоговая статистика
    logger.info("="*80)
    logger.info("📊 ИТОГИ ДРЕНИРОВАНИЯ:")
    logger.info(f"📈 Всего кошельков обработано: {len(private_keys)}")
    logger.success(f"✅ Успешных транзакций: {successful_transactions}")
    logger.error(f"❌ Неудачных транзакций: {failed_transactions}")
    logger.info(f"📈 Процент успеха: {(successful_transactions/len(private_keys))*100:.1f}%")
    logger.success(f"💾 Результаты сохранены в {result_file}")
    logger.info("="*80 + "\n")

# if __name__ == "__main__":
#     eth_drainers()