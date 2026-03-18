"""
Модуль для проверки балансов кошельков в сети Solana Mainnet
Поддерживает многопоточность, прокси и повторные попытки при ошибках
"""

import csv
import random
import time
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

import requests
from colorama import Fore, Style, init

init()

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from modules.simple_logger import logger
from config.modules.cfg_base import NUM_THREADS, RETRY_COUNT
from config.networks import SOL_NETWORKS
from modules.notifications import send_telegram_notification

total_wallets = 0
processed_wallets = 0
successful_checks = 0
failed_checks = 0

log_dir = project_root / 'log'

# Флаг инициализации логгера
_logger_initialized = False

def _setup_logging():
    """Настройка логирования - вызывается при запуске модуля"""
    global _logger_initialized
    if _logger_initialized:
        return
    _logger_initialized = True
    
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f'solana_balance_check_{timestamp}.log'
    
    # Только файловый лог, консольный уже настроен в simple_logger
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        encoding='utf-8'
    )


def load_wallets():
    """Загружает SOL-адреса из data.csv (колонка sol_address)"""
    from modules.data_manager import get_sol_addresses
    wallets = get_sol_addresses()
    if wallets:
        logger.success(f"✅ Загружено {len(wallets)} SOL кошельков")
    else:
        logger.error("❌ Нет SOL-адресов в data/data.csv (колонка sol_address)")
    return wallets


def load_proxies():
    """Загружает прокси из data.csv"""
    from modules.data_manager import get_proxies
    proxies = get_proxies()
    if proxies:
        logger.success(f"✅ Загружено {len(proxies)} прокси")
    else:
        logger.warning("⚠️ Нет прокси в data/data.csv. Работаем без прокси.")
    return proxies


def get_proxy_dict(proxy_string):
    """
    Преобразует строку прокси в формат для requests
    Формат: login:password@ip:port или http://login:password@ip:port
    """
    if not proxy_string:
        return None
    
    try:
        proxy_clean = proxy_string.replace('http://', '').replace('https://', '')
        
        if '@' in proxy_clean:
            proxy_url = f"http://{proxy_clean}"
        else:
            proxy_url = f"http://{proxy_clean}"
        
        return {
            'http': proxy_url,
            'https': proxy_url
        }
    except Exception as e:
        logger.debug(f"⚠️ Ошибка парсинга прокси {proxy_string}: {e}")
        return None


def get_assigned_proxy(wallet_index, proxies_list):
    """
    Назначает прокси кошельку (1 кошелек = 1 прокси по кругу)
    """
    if not proxies_list:
        return None
    return proxies_list[wallet_index % len(proxies_list)]


def get_random_proxy(proxies_list):
    """Возвращает случайную прокси из списка"""
    if not proxies_list:
        return None
    return random.choice(proxies_list)


def get_solana_rpc():
    """Получает RPC URL для Solana Mainnet"""
    solana_network = SOL_NETWORKS.get('🚀 Solana Mainnet', {})
    rpc_urls = solana_network.get('rpc_urls', [])
    
    if not rpc_urls:
        logger.error("❌ RPC URL для Solana Mainnet не найден в config/networks.py")
        return None
    
    return random.choice(rpc_urls)


def check_balance_with_retry(wallet_address, wallet_index, total, proxies_list):
    """
    Проверяет баланс кошелька с повторными попытками при ошибках
    
    Args:
        wallet_address: Адрес кошелька Solana
        wallet_index: Индекс кошелька (для назначения прокси)
        total: Общее количество кошельков
        proxies_list: Список прокси
        
    Returns:
        dict: Результат проверки с балансом или ошибкой
    """
    global processed_wallets, successful_checks, failed_checks
    
    assigned_proxy = get_assigned_proxy(wallet_index, proxies_list)
    
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            rpc_url = get_solana_rpc()
            if not rpc_url:
                raise Exception("RPC URL не найден")
            
            if attempt == 1:
                current_proxy = assigned_proxy
            else:
                current_proxy = get_random_proxy(proxies_list)
            
            proxy_dict = get_proxy_dict(current_proxy) if current_proxy else None
            proxy_display = current_proxy[:30] + '...' if current_proxy and len(current_proxy) > 30 else current_proxy or 'None'
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [wallet_address]
            }
            
            headers = {
                'Content-Type': 'application/json',
            }
            
            response = requests.post(
                rpc_url,
                json=payload,
                headers=headers,
                proxies=proxy_dict,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            if 'error' in result:
                error_msg = result['error'].get('message', 'Unknown RPC error')
                raise Exception(f"RPC Error: {error_msg}")
            
            balance_lamports = result.get('result', {}).get('value', 0)
            balance_sol = balance_lamports / 10**9
            
            processed_wallets += 1
            successful_checks += 1
            
            progress = f"[{processed_wallets}/{total}]"
            logger.success(
                f"{progress} ✅ {wallet_address[:8]}...{wallet_address[-6:]} | "
                f"Balance: {balance_sol:.6f} SOL | "
                f"Proxy: {proxy_display} | "
                f"Attempt: {attempt}/{RETRY_COUNT}"
            )
            
            return {
                'wallet': wallet_address,
                'balance': balance_sol,
                'balance_lamports': balance_lamports,
                'status': 'success',
                'attempts': attempt,
                'proxy_used': current_proxy or 'No proxy',
                'rpc_url': rpc_url
            }
            
        except requests.exceptions.Timeout:
            if attempt < RETRY_COUNT:
                logger.warning(
                    f"[{wallet_index + 1}/{total}] ⏱️ Timeout для {wallet_address[:8]}... | "
                    f"Попытка {attempt}/{RETRY_COUNT} | Смена прокси..."
                )
                time.sleep(1)
            else:
                processed_wallets += 1
                failed_checks += 1
                logger.error(
                    f"[{processed_wallets}/{total}] ❌ {wallet_address[:8]}...{wallet_address[-6:]} | "
                    f"Timeout после {RETRY_COUNT} попыток"
                )
                return {
                    'wallet': wallet_address,
                    'balance': 0,
                    'status': 'error',
                    'error': f'Timeout после {RETRY_COUNT} попыток',
                    'attempts': attempt
                }
                
        except requests.exceptions.RequestException as e:
            if attempt < RETRY_COUNT:
                logger.warning(
                    f"[{wallet_index + 1}/{total}] 🔄 Ошибка сети для {wallet_address[:8]}... | "
                    f"Попытка {attempt}/{RETRY_COUNT} | {str(e)[:50]}"
                )
                time.sleep(1)
            else:
                processed_wallets += 1
                failed_checks += 1
                logger.error(
                    f"[{processed_wallets}/{total}] ❌ {wallet_address[:8]}...{wallet_address[-6:]} | "
                    f"Ошибка после {RETRY_COUNT} попыток: {str(e)[:100]}"
                )
                return {
                    'wallet': wallet_address,
                    'balance': 0,
                    'status': 'error',
                    'error': str(e)[:200],
                    'attempts': attempt
                }
                
        except Exception as e:
            if attempt < RETRY_COUNT:
                logger.warning(
                    f"[{wallet_index + 1}/{total}] ⚠️ Ошибка для {wallet_address[:8]}... | "
                    f"Попытка {attempt}/{RETRY_COUNT} | {str(e)[:50]}"
                )
                time.sleep(1)
            else:
                processed_wallets += 1
                failed_checks += 1
                logger.error(
                    f"[{processed_wallets}/{total}] ❌ {wallet_address[:8]}...{wallet_address[-6:]} | "
                    f"Ошибка после {RETRY_COUNT} попыток: {str(e)[:100]}"
                )
                return {
                    'wallet': wallet_address,
                    'balance': 0,
                    'status': 'error',
                    'error': str(e)[:200],
                    'attempts': attempt
                }
    
    processed_wallets += 1
    failed_checks += 1
    return {
        'wallet': wallet_address,
        'balance': 0,
        'status': 'error',
        'error': f'Неизвестная ошибка после {RETRY_COUNT} попыток',
        'attempts': RETRY_COUNT
    }


def save_results_to_csv(results, filename='solana_balances.csv'):
    """
    Сохраняет результаты проверки в CSV файл
    
    Args:
        results: Список результатов проверки
        filename: Имя файла для сохранения
    """
    try:
        result_dir = project_root / 'result'
        result_dir.mkdir(exist_ok=True)
        
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = result_dir / f"solana_balances_{timestamp_str}.csv"
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['wallet', 'balance_sol', 'balance_lamports', 'status', 'attempts', 'proxy_used', 'error', 'rpc_url']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            writer.writeheader()
            for result in results:
                balance_sol = result.get('balance', 0)
                balance_sol_formatted = f"{balance_sol:.9f}".rstrip('0').rstrip('.') if balance_sol > 0 else '0'
                
                writer.writerow({
                    'wallet': result.get('wallet', ''),
                    'balance_sol': balance_sol_formatted,
                    'balance_lamports': result.get('balance_lamports', 0),
                    'status': result.get('status', 'unknown'),
                    'attempts': result.get('attempts', 0),
                    'proxy_used': result.get('proxy_used', ''),
                    'error': result.get('error', ''),
                    'rpc_url': result.get('rpc_url', '')
                })
        
        logger.success(f"✅ Результаты сохранены в {filepath}")
        return str(filepath)
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения результатов: {e}")
        return None


def solana_balance_checker():
    """
    Главная функция для проверки балансов Solana
    Запускает многопоточную проверку балансов всех кошельков
    """
    _setup_logging()
    global total_wallets, processed_wallets, successful_checks, failed_checks
    
    print("\n" + "="*70)
    print("🌞 SOLANA MAINNET BALANCE CHECKER")
    print("="*70 + "\n")
    
    logger.info("📁 Загрузка кошельков и прокси...")
    wallets = load_wallets()
    proxies = load_proxies()
    
    if not wallets:
        logger.error("❌ Нет кошельков для проверки!")
        return
    
    total_wallets = len(wallets)
    processed_wallets = 0
    successful_checks = 0
    failed_checks = 0
    
    logger.info(f"📊 Кошельков: {total_wallets} | Прокси: {len(proxies)} | Потоков: {NUM_THREADS}")
    logger.info(f"🔄 Максимум повторов при ошибке: {RETRY_COUNT}")
    
    rpc_url = get_solana_rpc()
    if not rpc_url:
        logger.error("❌ Не удалось получить RPC URL для Solana")
        return
    
    logger.info(f"🌐 Solana RPC: {rpc_url}\n")
    
    start_time = time.time()
    results = []
    
    try:
        send_telegram_notification(
            notif_type="info",
            title="Solana Balance Check Started",
            message=f"🚀 Начата проверка {total_wallets} кошельков\n🧵 Потоков: {NUM_THREADS}",
            main_title="Solana Balance Checker"
        )
    except Exception as e:
        logger.debug(f"⚠️ Не удалось отправить Telegram уведомление: {e}")
    
    logger.info("🚀 Запуск многопоточной проверки...\n")
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_wallet = {
            executor.submit(
                check_balance_with_retry,
                wallet,
                idx,
                total_wallets,
                proxies
            ): (wallet, idx)
            for idx, wallet in enumerate(wallets)
        }
        
        for future in as_completed(future_to_wallet):
            wallet, idx = future_to_wallet[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"❌ Критическая ошибка для {wallet[:8]}...: {e}")
                results.append({
                    'wallet': wallet,
                    'balance': 0,
                    'status': 'critical_error',
                    'error': str(e)[:200],
                    'attempts': 0
                })
    
    elapsed_time = time.time() - start_time
    minutes = int(elapsed_time // 60)
    seconds = int(elapsed_time % 60)
    time_str = f"{minutes}м {seconds}с" if minutes > 0 else f"{seconds}с"
    
    total_balance = sum(r.get('balance', 0) for r in results)
    
    print("\n" + "="*70)
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print("="*70)
    print(f"✅ Успешно проверено:  {successful_checks} кошельков")
    print(f"❌ Ошибок:             {failed_checks} кошельков")
    print(f"📝 Всего:              {total_wallets} кошельков")
    print(f"💰 Суммарный баланс:   {total_balance:.6f} SOL")
    print(f"⏱️  Время выполнения:   {time_str}")
    print("="*70 + "\n")
    
    logger.info("💾 Сохранение результатов в CSV...")
    csv_file = save_results_to_csv(results)
    
    try:
        send_telegram_notification(
            notif_type="success",
            title="Solana Balance Check Completed",
            message=f"✅ Успешно: {successful_checks}\n❌ Ошибок: {failed_checks}\n💰 Баланс: {total_balance:.6f} SOL\n⏱️ Время: {time_str}",
            main_title="Solana Balance Checker",
            file_path=csv_file if csv_file else None
        )
    except Exception as e:
        logger.debug(f"⚠️ Не удалось отправить финальное Telegram уведомление: {e}")
    
    logger.success("✅ Проверка балансов завершена!")


if __name__ == "__main__":
    solana_balance_checker()
