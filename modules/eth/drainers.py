import os
import csv
import time
import random
from web3 import Web3
from eth_account import Account
from modules.rpc_return_module import get_network_rpc_selection
from config.config import EVM_MAIN_WALLET, MAIN_PROXY, NUM_THREADS
from config.explorer_url import get_explorer_url
from colorama import Fore, Style, init
from itertools import cycle
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

init()

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
            print(Fore.YELLOW + f"[{dt_str}] Кошелек {wallet_index}/{total_wallets}: {wallet_address} - Пустой (0 ETH)")
            return {
                'wallet': wallet_address,
                'balance': '0',
                'status': 'empty',
                'tx_hash': '',
                'explorer_link': '',
                'error': 'Нулевой баланс'
            }
        
        print(Fore.CYAN + f"[{dt_str}] Кошелек {wallet_index}/{total_wallets}: {wallet_address} - Баланс: {balance_eth} ETH")
        
        # Получение газа для транзакции
        gas_price = w3.eth.gas_price
        
        # Построение тестовой транзакции для оценки газа
        test_tx = {
            'type': 0x2,
            'from': Web3.to_checksum_address(wallet_address),
            'to': Web3.to_checksum_address(EVM_MAIN_WALLET),
            'value': 1000000,  # Тестовое значение
            'gas': 1000000,
            'nonce': w3.eth.get_transaction_count(wallet_address),
            'chainId': w3.eth.chain_id,
            'maxFeePerGas': int(gas_price * 1.2),
            'maxPriorityFeePerGas': 0
        }
        
        # Оценка газа
        try:
            estimated_gas = w3.eth.estimate_gas(test_tx)
            gas_limit = int(estimated_gas * 1.2)  # +20% запас
        except Exception as e:
            print(Fore.YELLOW + f"Не удалось оценить газ, используем 21000: {e}")
            gas_limit = int(21000 * 1.2)
        
        gas_cost = gas_limit * int(gas_price * 1.2)
        
        # Проверка достаточности средств для газа
        if balance_wei <= gas_cost:
            print(Fore.YELLOW + "⚠️ Недостаточно средств для оплаты газа")
            return {
                'wallet': wallet_address,
                'balance': str(balance_eth),
                'status': 'insufficient_gas',
                'tx_hash': '',
                'explorer_link': '',
                'error': 'Недостаточно средств для газа'
            }
        
        # Сумма к отправке (баланс минус газ)
        amount_to_send = balance_wei - gas_cost
        
        # Получение nonce
        nonce = w3.eth.get_transaction_count(wallet_address)
        
        # Построение транзакции в том же формате что и в transefer_wallets_to_wallets.py
        transaction = {
            'type': 0x2,
            'from': Web3.to_checksum_address(wallet_address),
            'to': Web3.to_checksum_address(EVM_MAIN_WALLET),
            'value': amount_to_send,
            'gas': gas_limit,
            'nonce': nonce,
            'chainId': w3.eth.chain_id,
            'maxFeePerGas': int(gas_price * 1.2),
            'maxPriorityFeePerGas': 0
        }
        
        # Подписание транзакции
        signed_txn = w3.eth.account.sign_transaction(transaction, private_key)
        
        # Отправка транзакции
        tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        tx_hash_hex = w3.to_hex(tx_hash)
        
        print(Fore.BLUE + f"📤 Транзакция отправлена: {tx_hash_hex}")
        print(Fore.LIGHTBLUE_EX + f"🔗 Explorer: {explorer_url}{tx_hash_hex}")
        
        # Ожидание подтверждения
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            if receipt.status == 1:
                print(Fore.GREEN + f"✅ Успешно отправлено {w3.from_wei(amount_to_send, 'ether'):.6f} ETH")
                return {
                    'wallet': wallet_address,
                    'balance': str(balance_eth),
                    'status': 'success',
                    'tx_hash': tx_hash_hex,
                    'explorer_link': f"{explorer_url}{tx_hash_hex}",
                    'error': ''
                }
            else:
                print(Fore.RED + f"❌ Транзакция провалена")
                return {
                    'wallet': wallet_address,
                    'balance': str(balance_eth),
                    'status': 'failed',
                    'tx_hash': tx_hash_hex,
                    'explorer_link': f"{explorer_url}{tx_hash_hex}",
                    'error': 'Транзакция провалена'
                }
        except Exception as e:
            print(Fore.RED + f"❌ Timeout при ожидании подтверждения: {str(e)[:50]}...")
            return {
                'wallet': wallet_address,
                'balance': str(balance_eth),
                'status': 'timeout',
                'tx_hash': tx_hash_hex,
                'explorer_link': f"{explorer_url}{tx_hash_hex}",
                'error': f'Timeout: {str(e)}'
            }
        
    except Exception as e:
        print(Fore.RED + f"❌ Ошибка при обработке кошелька {private_key[:10]}...: {str(e)[:50]}...")
        return {
            'wallet': 'unknown',
            'balance': '0',
            'status': 'error',
            'tx_hash': '',
            'explorer_link': '',
            'error': str(e)
        }

def eth_drainers():
    """Дренирование всех кошельков из private_keys.txt на главный кошелек"""
    
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + "🚀 Запуск модуля дренирования кошельков")
    print(Fore.MAGENTA + "="*80)
    
    # Выбор сети и получение RPC
    rpc_urls_list, network_type, clean_network = get_network_rpc_selection()
    if rpc_urls_list is None:
        print(Fore.RED + "❌ Не удалось получить данные сети")
        return
    
    # Выбираем случайный RPC из списка
    rpc_url = random.choice(rpc_urls_list)
    
    print(Fore.CYAN + f"🌐 Выбрана сеть: {clean_network} ({network_type})")
    print(Fore.CYAN + f"🔗 RPC URL: {rpc_url}")
    print(Fore.CYAN + f"🧵 Потоков: {NUM_THREADS}")
    
    # Получаем URL эксплорера для выбранной сети
    explorer_url = get_explorer_url(f"🚀 {clean_network}")
    print(Fore.CYAN + f"🔍 Explorer URL: {explorer_url}")
    
    # Подключение к Web3
    if MAIN_PROXY:
        proxies = {'http': MAIN_PROXY, 'https': MAIN_PROXY}
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'proxies': proxies}))
        proxy_hidden = f"{MAIN_PROXY.rsplit('.', 1)[0]}.x:{MAIN_PROXY.split(':')[-1]}" if '@' not in MAIN_PROXY else f"xxxx:xxx@{MAIN_PROXY.split('@')[-1].rsplit('.', 1)[0]}.x:{MAIN_PROXY.split(':')[-1]}"
        print(Fore.CYAN + f"🔀 Используется прокси: {proxy_hidden}")
    else:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        print(Fore.YELLOW + "⚠️ Прокси не используется")
    
    if not w3.is_connected():
        print(Fore.RED + "❌ Не удалось подключиться к сети")
        return
    
    print(Fore.GREEN + "✅ Подключение к сети установлено")
    
    # Загрузка приватных ключей
    private_keys_file = 'data/private_keys.txt'
    if not os.path.exists(private_keys_file):
        print(Fore.RED + f"❌ Файл {private_keys_file} не найден")
        return
    
    with open(private_keys_file, 'r') as f:
        private_keys = [line.strip() for line in f.readlines() if line.strip()]
    
    if not private_keys:
        print(Fore.RED + "❌ Приватные ключи не найдены")
        return
    
    print(Fore.GREEN + f"📂 Загружено {len(private_keys)} приватных ключей")
    
    # Проверка главного кошелька
    if not EVM_MAIN_WALLET:
        print(Fore.RED + "❌ EVM_MAIN_WALLET не настроен в config.py")
        return
    
    if not Web3.is_address(EVM_MAIN_WALLET):
        print(Fore.RED + "❌ Некорректный адрес главного кошелька")
        return
    
    print(Fore.CYAN + f"🎯 Главный кошелек: {EVM_MAIN_WALLET}")
    
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
    
    print(Fore.MAGENTA + "\n" + "-"*80)
    print(Fore.YELLOW + "🔄 Начинаем дренирование кошельков...")
    print(Fore.MAGENTA + "-"*80)
    
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
    print(Fore.CYAN + f"\n\n💾 Сохраняем результаты...")
    with open(result_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['wallet', 'balance', 'status', 'tx_hash', 'explorer_link', 'error']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result)
    
    # Итоговая статистика
    print(Fore.MAGENTA + "\n" + "="*80)
    print(Fore.YELLOW + "📊 ИТОГИ ДРЕНИРОВАНИЯ:")
    print(Fore.CYAN + f"📈 Всего кошельков обработано: {len(private_keys)}")
    print(Fore.GREEN + f"✅ Успешных транзакций: {successful_transactions}")
    print(Fore.RED + f"❌ Неудачных транзакций: {failed_transactions}")
    print(Fore.CYAN + f"📈 Процент успеха: {(successful_transactions/len(private_keys))*100:.1f}%")
    print(Fore.GREEN + f"💾 Результаты сохранены в {result_file}")
    print(Fore.MAGENTA + "="*80 + "\n")

# if __name__ == "__main__":
#     eth_drainers()