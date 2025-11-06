import csv
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
from colorama import Fore, Style, init
from web3 import Web3
from loguru import logger

init()

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from config.config import NUM_THREADS, RETRY_COUNT

# Настройка логирования для модуля get_gas_price
def setup_gas_price_logging():
    """Настраивает логирование для модуля получения цены газа"""
    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f'gas_price_{timestamp}.log'
    
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

def load_proxies():
    """Загружает прокси из файла data/proxy.csv"""
    try:
        proxy_file = project_root / 'data' / 'proxy.csv'
        with open(proxy_file, 'r') as f:
            reader = csv.reader(f)
            proxies = [row[0] for row in reader if row]
        return proxies
    except FileNotFoundError:
        return []

def get_proxy_dict(proxy_string):
    """Преобразует строку прокси в формат для requests"""
    if not proxy_string:
        return None
    
    try:
        auth_part, address_part = proxy_string.split('@')
        login, password = auth_part.split(':')
        ip, port = address_part.split(':')
        
        proxy_url = f"http://{login}:{password}@{ip}:{port}"
        return {
            'http': proxy_url,
            'https': proxy_url
        }
    except:
        return None

def get_eth_price_usd():
    """Получает текущую цену ETH в USD"""
    try:
        response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd', timeout=10)
        data = response.json()
        return data['ethereum']['usd']
    except:
        return None

def get_token_price_usd(token_symbol):
    """Получает текущую цену токена в USD"""
    try:
        # Соответствие символов токенов их ID в CoinGecko
        token_ids = {
            'ETH': 'ethereum',
            'BNB': 'binancecoin', 
            'MATIC': 'matic-network',
            'AVAX': 'avalanche-2',
            'FTM': 'fantom',
            'G': 'gravity',
        }
        
        token_id = token_ids.get(token_symbol.upper())
        if not token_id:
            logger.warning(f"⚠️ Токен {token_symbol} не найден в списке поддерживаемых")
            return None
        
        url = f'https://api.coingecko.com/api/v3/simple/price?ids={token_id}&vs_currencies=usd'
        response = requests.get(url, timeout=15)
        
        if response.status_code != 200:
            logger.warning(f"⚠️ API ошибка для {token_symbol}: HTTP {response.status_code}")
            return None
            
        data = response.json()
        
        if token_id not in data:
            logger.warning(f"⚠️ Токен {token_symbol} ({token_id}) не найден в ответе API")
            return None
            
        if 'usd' not in data[token_id]:
            logger.warning(f"⚠️ USD цена не найдена для {token_symbol}")
            return None
            
        price = data[token_id]['usd']
        return float(price)
        
    except requests.exceptions.Timeout:
        logger.warning(f"⚠️ Таймаут при получении цены для {token_symbol}")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ Ошибка сети при получении цены для {token_symbol}: {e}")
        return None
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"⚠️ Ошибка парсинга данных для {token_symbol}: {e}")
        return None
    except Exception as e:
        logger.warning(f"⚠️ Неожиданная ошибка для {token_symbol}: {e}")
        return None

def is_testnet_network(network_name):
    """Проверяет, является ли сеть тестовой"""
    return any(testnet_keyword in network_name.lower() for testnet_keyword in ['testnet', 'test'])

def get_gas_price_for_network(network_name, rpc_urls, proxy=None):
    """Получает цену газа для указанной сети"""
    
    proxies_list = load_proxies()
    current_proxy = proxy
    
    # Получаем символ нативного токена для сети
    from config.networks import get_network_symbol
    native_token_symbol = get_network_symbol(network_name)
    
    # Перебираем все RPC URLs
    for rpc_attempt, rpc_url in enumerate(rpc_urls):
        # Для каждого RPC пробуем несколько раз с разными прокси
        for attempt in range(RETRY_COUNT + 1):
            session = requests.Session()
            try:
                if current_proxy:
                    proxy_dict = get_proxy_dict(current_proxy)
                    if proxy_dict:
                        session.proxies.update(proxy_dict)
                
                w3 = Web3(Web3.HTTPProvider(rpc_url, session=session))
                
                if not w3.is_connected():
                    raise ConnectionError(f"Не удалось подключиться к RPC")
                
                # Получаем цену газа
                gas_price_wei = w3.eth.gas_price
                gas_price_gwei = w3.from_wei(gas_price_wei, 'gwei')
                
                # Получаем последний блок для дополнительной информации
                latest_block = w3.eth.get_block('latest')
                block_number = latest_block.number
                
                # Стандартные лимиты газа для разных типов транзакций
                gas_limits = {
                    'simple_transfer': 21000,
                    'erc20_transfer': 65000,
                    'swap_uniswap': 150000,
                    'nft_mint': 200000,
                    'contract_interaction': 100000
                }
                
                # Рассчитываем стоимость транзакций
                tx_costs = {}
                for tx_type, gas_limit in gas_limits.items():
                    cost_wei = gas_price_wei * gas_limit
                    cost_native = w3.from_wei(cost_wei, 'ether')  # Переводим в нативную валюту сети
                    tx_costs[tx_type] = {
                        'gas_limit': gas_limit,
                        'cost_wei': cost_wei,
                        'cost_native': float(cost_native),
                        'native_symbol': native_token_symbol
                    }
                
                return {
                    'network_name': network_name,
                    'gas_price_gwei': float(gas_price_gwei),
                    'gas_price_wei': gas_price_wei,
                    'block_number': block_number,
                    'tx_costs': tx_costs,
                    'rpc_url': rpc_url,
                    'native_symbol': native_token_symbol,
                    'success': True,
                    'error': None
                }
                
            except Exception as e:
                error_msg = get_short_error_message(str(e))
                
                if attempt < RETRY_COUNT:
                    # Меняем прокси при ошибке
                    if proxies_list:
                        current_proxy = random.choice(proxies_list)
                    time.sleep(1)
                    continue
                else:
                    # Если все попытки для текущего RPC исчерпаны, переходим к следующему RPC
                    if rpc_attempt < len(rpc_urls) - 1:
                        # Меняем прокси для следующего RPC
                        if proxies_list:
                            current_proxy = random.choice(proxies_list)
                        break
                    else:
                        # Все RPC исчерпаны
                        return {
                            'network_name': network_name,
                            'gas_price_gwei': 0,
                            'gas_price_wei': 0,
                            'block_number': 0,
                            'tx_costs': {},
                            'rpc_url': None,
                            'native_symbol': native_token_symbol,
                            'success': False,
                            'error': error_msg
                        }
            finally:
                session.close()
    
    # Если дошли до сюда, значит все RPC не сработали
    return {
        'network_name': network_name,
        'gas_price_gwei': 0,
        'gas_price_wei': 0,
        'block_number': 0,
        'tx_costs': {},
        'rpc_url': None,
        'native_symbol': native_token_symbol,
        'success': False,
        'error': 'Все RPC недоступны'
    }

def get_short_error_message(error_str):
    """Преобразует длинные технические ошибки в короткие понятные сообщения"""
    error_lower = error_str.lower()
    
    if 'connection' in error_lower or 'timeout' in error_lower:
        return 'Ошибка подключения'
    elif 'poa chain' in error_lower or 'extradata' in error_lower:
        return 'Несовместимая сеть (POA)'
    elif 'too many requests' in error_lower or '429' in error_str:
        return 'Превышен лимит запросов'
    elif 'proxy' in error_lower:
        return 'Ошибка прокси'
    elif 'authentication' in error_lower:
        return 'Ошибка аутентификации'
    elif 'not found' in error_lower or '404' in error_str:
        return 'RPC не найден'
    elif 'internal server error' in error_lower or '500' in error_str:
        return 'Внутренняя ошибка сервера'
    elif 'bad gateway' in error_lower or '502' in error_str:
        return 'Плохой шлюз'
    elif 'service unavailable' in error_lower or '503' in error_str:
        return 'Сервис недоступен'
    elif 'gateway timeout' in error_lower or '504' in error_str:
        return 'Таймаут шлюза'
    elif 'json' in error_lower and 'decode' in error_lower:
        return 'Неверный ответ RPC'
    elif 'ssl' in error_lower or 'certificate' in error_lower:
        return 'Ошибка SSL сертификата'
    elif 'network is unreachable' in error_lower:
        return 'Сеть недоступна'
    elif 'name resolution failed' in error_lower or 'dns' in error_lower:
        return 'Ошибка DNS'
    else:
        # Возвращаем первые 50 символов оригинальной ошибки
        return error_str[:50] + '...' if len(error_str) > 50 else error_str

def get_all_networks():
    """Получает все доступные сети автоматически из config/networks.py"""
    try:
        import config.networks as rpc_module
        
        mainnet_rpc_urls = {}
        testnet_rpc_urls = {}
        
        # Получаем все атрибуты из модуля networks
        for attr_name in dir(rpc_module):
            if not attr_name.startswith('_'):  # Исключаем служебные атрибуты
                attr_value = getattr(rpc_module, attr_name)
                if isinstance(attr_value, list) and attr_value:  # Проверяем что это список RPC URLs
                    # Определяем тип сети по названию
                    if any(testnet_keyword in attr_name.lower() for testnet_keyword in ['testnet', 'test']):
                        # Форматируем название для testnet сетей
                        if attr_name == 'mega_eth_testnet':
                            formatted_name = "🚀 Mega ETH"
                        elif attr_name == 'pharos_testnet':
                            formatted_name = "🚀 Pharos"
                        elif attr_name == 'kite_testnet':
                            formatted_name = "🚀 Kite Testnet"
                        else:
                            formatted_name = f"🚀 {attr_name.replace('_', ' ').title()}"
                        testnet_rpc_urls[formatted_name] = attr_value
                    else:
                        # Форматируем название для mainnet сетей
                        if attr_name == 'L1':
                            formatted_name = "🚀 Ethereum Mainnet"
                        elif attr_name == 'Binance_Smart_Chain':
                            formatted_name = "🚀 Binance Smart Chain"
                        elif attr_name == 'Gravity_Alpha_Mainnet':
                            formatted_name = "🚀 Gravity Alpha Mainnet (сеть Gravity )"
                        else:
                            formatted_name = f"🚀 {attr_name.replace('_', ' ').title()}"
                        mainnet_rpc_urls[formatted_name] = attr_value
        
        # Возвращаем mainnet и testnet сети отдельно для правильной сортировки
        return mainnet_rpc_urls, testnet_rpc_urls
        
    except ImportError:
        logger.error("❌ Не удалось импортировать config.networks")
        return {}, {}

def format_gas_info(result, token_prices=None):
    """Форматирует информацию о газе для красивого вывода"""
    
    if not result['success']:
        return f"{Fore.RED}❌ {result['network_name'].replace('🚀 ', '')}: {result['error']}{Style.RESET_ALL}"
    
    network_name = result['network_name'].replace('🚀 ', '')
    gas_price = result['gas_price_gwei']
    block_number = result['block_number']
    native_symbol = result.get('native_symbol', 'ETH')
    
    # Определяем цвет для цены газа
    if gas_price < 5:
        gas_color = Fore.GREEN
        gas_status = "🟢 НИЗКИЙ"
    elif gas_price < 20:
        gas_color = Fore.YELLOW
        gas_status = "🟡 СРЕДНИЙ"
    elif gas_price < 50:
        gas_color = Fore.LIGHTRED_EX
        gas_status = "🟠 ВЫСОКИЙ"
    else:
        gas_color = Fore.RED
        gas_status = "🔴 ОЧЕНЬ ВЫСОКИЙ"
    
    output = []
    output.append(f"{Fore.CYAN}🌐 {network_name}{Style.RESET_ALL}")
    output.append(f"   ⛽ Газ: {gas_color}{gas_price:.2f} Gwei{Style.RESET_ALL} {gas_status}")
    output.append(f"   📦 Блок: {Fore.BLUE}#{block_number:,}{Style.RESET_ALL}")
    output.append(f"   💰 Нативный токен: {Fore.YELLOW}{native_symbol}{Style.RESET_ALL}")
    
    # Показываем стоимость основных транзакций
    tx_costs = result['tx_costs']
    if tx_costs:
        output.append(f"   💸 Стоимость транзакций:")
        
        tx_names = {
            'simple_transfer': 'Простой перевод',
            'erc20_transfer': 'Перевод ERC-20',
            'swap_uniswap': 'Swap на DEX',
            'contract_interaction': 'Взаимодействие с контрактом'
        }
        
        # Получаем цену токена для расчета в USD (только для mainnet)
        token_price_usd = None
        if not is_testnet_network(result['network_name']) and token_prices:
            token_price_usd = token_prices.get(native_symbol)
        
        for tx_type in ['simple_transfer', 'erc20_transfer', 'swap_uniswap', 'contract_interaction']:
            if tx_type in tx_costs:
                cost_native = tx_costs[tx_type]['cost_native']
                gas_limit = tx_costs[tx_type]['gas_limit']
                
                cost_info = f"{cost_native:.6f} {native_symbol}"
                
                # Добавляем USD только для mainnet сетей
                if token_price_usd and cost_native > 0 and not is_testnet_network(result['network_name']):
                    cost_usd = cost_native * token_price_usd
                    cost_info += f" (${cost_usd:.2f})"
                
                output.append(f"     • {tx_names[tx_type]}: {Fore.GREEN}{cost_info}{Style.RESET_ALL}")
    
    return "\n".join(output)

def save_gas_results(results, token_prices=None):
    """Сохраняет результаты в CSV файл"""
    result_dir = project_root / 'result'
    result_dir.mkdir(exist_ok=True)
    
    result_file = result_dir / 'gas_prices.csv'
    
    with open(result_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        header = ['network', 'native_symbol', 'gas_price_gwei', 'block_number', 
                 'simple_transfer_native', 'simple_transfer_usd', 
                 'erc20_transfer_native', 'erc20_transfer_usd', 
                 'swap_native', 'swap_usd', 'status', 'error'
        ]
        writer.writerow(header)
        
        for result in results:
            network_name = result['network_name'].replace('🚀 ', '')
            native_symbol = result.get('native_symbol', 'ETH')
            
            if result['success']:
                tx_costs = result['tx_costs']
                
                simple_cost_native = tx_costs.get('simple_transfer', {}).get('cost_native', 0)
                erc20_cost_native = tx_costs.get('erc20_transfer', {}).get('cost_native', 0)
                swap_cost_native = tx_costs.get('swap_uniswap', {}).get('cost_native', 0)
                
                # Рассчитываем USD только для mainnet сетей
                token_price_usd = None
                if not is_testnet_network(result['network_name']) and token_prices:
                    token_price_usd = token_prices.get(native_symbol)
                
                simple_cost_usd = simple_cost_native * token_price_usd if token_price_usd else 0
                erc20_cost_usd = erc20_cost_native * token_price_usd if token_price_usd else 0
                swap_cost_usd = swap_cost_native * token_price_usd if token_price_usd else 0
                
                writer.writerow([
                    network_name,
                    native_symbol,
                    result['gas_price_gwei'],
                    result['block_number'],
                    simple_cost_native,
                    simple_cost_usd,
                    erc20_cost_native,
                    erc20_cost_usd,
                    swap_cost_native,
                    swap_cost_usd,
                    'SUCCESS',
                    ''
                ])
            else:
                writer.writerow([
                    network_name, native_symbol, 0, 0, 0, 0, 0, 0, 0, 0, 'ERROR', result['error']
                ])

def check_all_gas_prices():
    """Главная функция для проверки цен газа во всех сетях"""
    
    logger.info("\n" + "="*80)
    logger.info("⛽ МОНИТОРИНГ ЦЕН ГАЗА ВО ВСЕХ СЕТЯХ")
    logger.info("="*80)
    
    # Получаем все сети автоматически
    mainnet_networks, testnet_networks = get_all_networks()
    
    if not mainnet_networks and not testnet_networks:
        logger.error("❌ Не найдено ни одной сети в config/rpc.py")
        return
    
    # Объединяем сети с сохранением порядка: сначала mainnet, потом testnet
    all_networks = {}
    all_networks.update(mainnet_networks)
    all_networks.update(testnet_networks)
    
    proxies_list = load_proxies()
    
    logger.info(f"🌐 Mainnet сетей: {len(mainnet_networks)}")
    logger.info(f"🌐 Testnet сетей: {len(testnet_networks)}")
    logger.info(f"🌐 Всего сетей: {len(all_networks)}")
    logger.info(f"🔗 Прокси загружено: {len(proxies_list)}")
    logger.info(f"🧵 Потоков: {NUM_THREADS}")
    
    # Получаем цены токенов для mainnet сетей
    logger.info("💰 Получаем актуальные цены токенов...")
    token_prices = {}
    
    # Получаем уникальные символы токенов из mainnet сетей через config/networks.py
    from config.networks import get_network_symbol, get_all_networks as get_explorer_networks
    unique_tokens = set()
    
    # Получаем все сети из networks для сопоставления
    explorer_networks = get_explorer_networks()
    
    for network_name in mainnet_networks.keys():
        # Ищем соответствующую сеть в explorer_url
        matching_network = None
        for explorer_network in explorer_networks:
            if network_name == explorer_network or network_name.replace('🚀 ', '') == explorer_network.replace('🚀 ', ''):
                matching_network = explorer_network
                break
        
        if matching_network:
            token_symbol = get_network_symbol(matching_network)
            unique_tokens.add(token_symbol)
        else:
            # Fallback - используем ETH по умолчанию
            unique_tokens.add('ETH')
    
    logger.info(f"🔍 Найдено уникальных токенов: {list(unique_tokens)}")
    
    # Загружаем цены для каждого уникального токена
    success_count = 0
    for token_symbol in unique_tokens:
        logger.info(f"📡 Запрашиваем цену для {token_symbol}...")
        price = get_token_price_usd(token_symbol)
        if price:
            token_prices[token_symbol] = price
            success_count += 1
            logger.success(f"💰 {token_symbol}: ${price:,.2f}")
        else:
            logger.warning(f"⚠️ Не удалось получить цену для {token_symbol}")
    
    logger.info(f"📊 Успешно получено цен: {success_count}/{len(unique_tokens)}")

    results = []
    successful_count = 0
    failed_count = 0

    logger.info("-" * 80)
    logger.info("🔄 Проверяем цены газа...")
    logger.info("-" * 80)
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_network = {
            executor.submit(
                get_gas_price_for_network,
                network_name,
                rpc_urls,
                proxies_list[i % len(proxies_list)] if proxies_list else None
            ): network_name
            for i, (network_name, rpc_urls) in enumerate(all_networks.items())
        }
        
        for future in as_completed(future_to_network):
            network_name = future_to_network[future]
            try:
                result = future.result(timeout=60)
                results.append(result)
                
                if result['success']:
                    successful_count += 1
                    native_symbol = result.get('native_symbol', 'ETH')
                    logger.info(f"✅ {result['network_name'].replace('🚀 ', '')}: {result['gas_price_gwei']:.2f} Gwei ({native_symbol})")
                else:
                    failed_count += 1
                    logger.error(f"❌ {result['network_name'].replace('🚀 ', '')}: {result['error']}")
                    
            except Exception as e:
                failed_count += 1
                error_msg = get_short_error_message(str(e))
                results.append({
                    '\nnetwork_name': network_name,
                    'gas_price_gwei': 0,
                    'gas_price_wei': 0,
                    'block_number': 0,
                    'tx_costs': {},
                    'rpc_url': None,
                    'native_symbol': 'ETH',
                    'success': False,
                    'error': error_msg,
                })
                logger.error(f"❌ {network_name.replace('🚀 ', '')}: {error_msg}")
    
    # Сортируем результаты: сначала mainnet (успешные, потом с ошибками), потом testnet (успешные, потом с ошибками)
    def sort_key(result):
        network_name = result['network_name']
        is_testnet = any(testnet_keyword in network_name.lower() for testnet_keyword in ['testnet', 'test'])
        return (is_testnet, not result['success'], network_name)
    
    results.sort(key=sort_key)
    
    logger.info("\n" + "="*80)
    logger.info("📊 ДЕТАЛЬНЫЕ РЕЗУЛЬТАТЫ:")
    logger.info("="*80)
    
    # Выводим детальную информацию с разделением на mainnet и testnet
    mainnet_results = [r for r in results if not any(testnet_keyword in r['network_name'].lower() for testnet_keyword in ['testnet', 'test'])]
    testnet_results = [r for r in results if any(testnet_keyword in r['network_name'].lower() for testnet_keyword in ['testnet', 'test'])]
    
    if mainnet_results:
        logger.info("🌐 MAINNET СЕТИ:")
        logger.info("-" * 40)
        for result in mainnet_results:
            if result['success']:
                logger.info(format_gas_info(result, token_prices))
                logger.info("")
    
    if testnet_results:
        logger.info("🔧 TESTNET СЕТИ:")
        logger.info("-" * 40)
        for result in testnet_results:
            if result['success']:
                logger.info(format_gas_info(result))  # Без цен для testnet
                logger.info("")
    
    # Выводим ошибки отдельно с разделением
    failed_mainnet = [r for r in mainnet_results if not r['success']]
    failed_testnet = [r for r in testnet_results if not r['success']]
    
    if failed_mainnet or failed_testnet:
        logger.info("-"*80)
        logger.info("❌ ОШИБКИ ПОДКЛЮЧЕНИЯ:")
        logger.info("-"*80)
        
        if failed_mainnet:
            logger.info("🌐 MAINNET:")
            for result in failed_mainnet:
                logger.info(format_gas_info(result, token_prices))
        
        if failed_testnet:
            logger.info("🔧 TESTNET:")
            for result in failed_testnet:
                logger.info(format_gas_info(result))
    
    logger.info("="*80)
    logger.info("📈 ИТОГОВАЯ СТАТИСТИКА:")
    logger.info(f"✅ Успешно проверено сетей: {successful_count}")
    logger.info(f"   • Mainnet: {len([r for r in mainnet_results if r['success']])}/{len(mainnet_results)}")
    logger.info(f"   • Testnet: {len([r for r in testnet_results if r['success']])}/{len(testnet_results)}")
    logger.info(f"❌ Ошибок: {failed_count}")
    logger.info(f"📊 Общий процент успеха: {(successful_count/len(all_networks))*100:.1f}%")
    
    # Находим самый дешевый и дорогой газ среди успешных
    successful_results = [r for r in results if r['success']]
    if successful_results:
        cheapest = min(successful_results, key=lambda x: x['gas_price_gwei'])
        most_expensive = max(successful_results, key=lambda x: x['gas_price_gwei'])
        
        logger.info(f"💚 Самый дешевый газ: {cheapest['network_name'].replace('🚀 ', '')} - {cheapest['gas_price_gwei']:.2f} Gwei")
        logger.info(f"💸 Самый дорогой газ: {most_expensive['network_name'].replace('🚀 ', '')} - {most_expensive['gas_price_gwei']:.2f} Gwei")
    
    logger.info("💾 Сохраняем результаты...")
    save_gas_results(results, token_prices)
    logger.success("✅ Результаты сохранены в result/gas_prices.csv")
    logger.info("="*80 + "\n")

# Добавляем алиас для совместимости с именованием других модулей
def check_gas_price_menu():
    """Алиас для основной функции - для консистентности с другими модулями"""
    check_all_gas_prices()

def get_gas_price_from_rpc(rpc_url):
    """Получает цену газа напрямую из RPC"""
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        if not w3.is_connected():
            logger.error(f"❌ Не удалось подключиться к RPC: {rpc_url}")
            return None
        
        gas_price_wei = w3.eth.gas_price
        gas_price_gwei = w3.from_wei(gas_price_wei, 'gwei')
        
        logger.success(f"✅ Цена газа получена из RPC: {gas_price_gwei:.2f} Gwei")
        return {
            'source': 'RPC',
            'gas_price_wei': gas_price_wei,
            'gas_price_gwei': float(gas_price_gwei),
            'rpc_url': rpc_url
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения цены газа из RPC: {e}")
        return None

def get_gas_price_from_etherscan(api_key=None):
    """Получает цену газа из Etherscan API"""
    try:
        base_url = "https://api.etherscan.io/api"
        params = {
            'module': 'gastracker',
            'action': 'gasoracle'
        }
        
        if api_key:
            params['apikey'] = api_key
        
        response = requests.get(base_url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('status') == '1':
                result = data.get('result', {})
                
                gas_info = {
                    'source': 'Etherscan',
                    'safe_gas_price': float(result.get('SafeGasPrice', 0)),
                    'standard_gas_price': float(result.get('ProposeGasPrice', 0)),
                    'fast_gas_price': float(result.get('FastGasPrice', 0))
                }
                
                logger.success(f"✅ Цена газа получена из Etherscan:")
                logger.info(f"   🟢 Безопасная: {gas_info['safe_gas_price']} Gwei")
                logger.info(f"   🟡 Стандартная: {gas_info['standard_gas_price']} Gwei")
                logger.info(f"   🔴 Быстрая: {gas_info['fast_gas_price']} Gwei")
                
                return gas_info
            else:
                logger.error(f"❌ Ошибка API Etherscan: {data.get('message', 'Unknown error')}")
                
        else:
            logger.error(f"❌ HTTP ошибка при запросе к Etherscan: {response.status_code}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения цены газа из Etherscan: {e}")
    
    return None

def get_gas_price_from_gasstation():
    """Получает цену газа из ETH Gas Station"""
    try:
        url = "https://ethgasstation.info/api/ethgasAPI.json"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            gas_info = {
                'source': 'ETH Gas Station',
                'safe_gas_price': data.get('safeLow', 0) / 10,  # Конвертируем в Gwei
                'standard_gas_price': data.get('average', 0) / 10,
                'fast_gas_price': data.get('fast', 0) / 10,
                'fastest_gas_price': data.get('fastest', 0) / 10
            }
            
            logger.success(f"✅ Цена газа получена из ETH Gas Station:")
            logger.info(f"   🟢 Безопасная: {gas_info['safe_gas_price']} Gwei")
            logger.info(f"   🟡 Стандартная: {gas_info['standard_gas_price']} Gwei")
            logger.info(f"   🟠 Быстрая: {gas_info['fast_gas_price']} Gwei")
            logger.info(f"   🔴 Самая быстрая: {gas_info['fastest_gas_price']} Gwei")
            
            return gas_info
        else:
            logger.error(f"❌ HTTP ошибка при запросе к ETH Gas Station: {response.status_code}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения цены газа из ETH Gas Station: {e}")
    
    return None

def save_gas_price_data(gas_data):
    """Сохраняет данные о цене газа в JSON файл"""
    try:
        result_dir = Path("result")
        result_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().isoformat()
        gas_data['timestamp'] = timestamp
        
        result_file = result_dir / "gas_prices.json"
        
        # Загружаем существующие данные или создаем новый список
        if result_file.exists():
            with open(result_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        else:
            existing_data = []
        
        # Добавляем новые данные
        existing_data.append(gas_data)
        
        # Оставляем только последние 100 записей
        if len(existing_data) > 100:
            existing_data = existing_data[-100:]
        
        # Сохраняем обновленные данные
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)
        
        logger.success(f"💾 Данные о цене газа сохранены в {result_file}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения данных о цене газа: {e}")

def get_gas_price_menu():
    """Главное меню модуля получения цены газа"""
    setup_gas_price_logging()
    
    try:
        logger.info("🚀 Запуск модуля получения цены газа")
        
        while True:
            logger.info("\n" + "="*50)
            logger.info("⛽ МЕНЮ ПОЛУЧЕНИЯ ЦЕНЫ ГАЗА")
            logger.info("="*50)
            logger.info("1. 🌐 Получить цену газа из RPC")
            logger.info("2. 📊 Получить цену газа из Etherscan")
            logger.info("3. ⛽ Получить цену газа из ETH Gas Station")
            logger.info("4. 🔄 Получить из всех источников")
            logger.info("5. 📈 Показать историю цен")
            logger.info("6. 🚪 Выход")
            
            choice = input("\nВыберите действие (1-6): ").strip()
            
            if choice == '1':
                rpc_url = input("Введите RPC URL: ").strip()
                if rpc_url:
                    gas_data = get_gas_price_from_rpc(rpc_url)
                    if gas_data:
                        save_gas_price_data(gas_data)
                else:
                    logger.warning("⚠️ RPC URL не может быть пустым")
                    
            elif choice == '2':
                api_key = input("Введите Etherscan API key (опционально): ").strip()
                gas_data = get_gas_price_from_etherscan(api_key if api_key else None)
                if gas_data:
                    save_gas_price_data(gas_data)
                    
            elif choice == '3':
                gas_data = get_gas_price_from_gasstation()
                if gas_data:
                    save_gas_price_data(gas_data)
                    
            elif choice == '4':
                logger.info("🔄 Получаем цену газа из всех источников...")
                
                # RPC (нужен URL)
                rpc_url = input("Введите RPC URL для прямого запроса: ").strip()
                if rpc_url:
                    rpc_data = get_gas_price_from_rpc(rpc_url)
                    if rpc_data:
                        save_gas_price_data(rpc_data)
                
                # Etherscan
                api_key = input("Введите Etherscan API key (опционально): ").strip()
                etherscan_data = get_gas_price_from_etherscan(api_key if api_key else None)
                if etherscan_data:
                    save_gas_price_data(etherscan_data)
                
                # ETH Gas Station
                gasstation_data = get_gas_price_from_gasstation()
                if gasstation_data:
                    save_gas_price_data(gasstation_data)
                
                logger.success("✅ Получение данных из всех источников завершено")
                
            elif choice == '5':
                show_gas_price_history()
                
            elif choice == '6':
                logger.info("👋 Выход из модуля получения цены газа")
                break
                
            else:
                logger.warning("⚠️ Неверный выбор. Попробуйте снова.")
                
    except KeyboardInterrupt:
        logger.info("\n👋 Выход из программы по запросу пользователя")
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}")

def show_gas_price_history():
    """Показывает историю цен на газ"""
    try:
        result_file = Path("result/gas_prices.json")
        
        if not result_file.exists():
            logger.warning("⚠️ Файл с историей цен не найден")
            return
        
        with open(result_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
        
        if not history_data:
            logger.warning("⚠️ История цен пуста")
            return
        
        logger.info(f"\n📈 История цен на газ (последние {len(history_data)} записей)")
        logger.info("-" * 60)
        
        for i, entry in enumerate(reversed(history_data[-10:]), 1):  # Показываем последние 10
            timestamp = entry.get('timestamp', 'Неизвестно')
            source = entry.get('source', 'Неизвестно')
            
            logger.info(f"{i}. 🕐 {timestamp}")
            logger.info(f"   📊 Источник: {source}")
            
            if 'gas_price_gwei' in entry:
                logger.info(f"   ⛽ Цена газа: {entry['gas_price_gwei']} Gwei")
            else:
                if 'safe_gas_price' in entry:
                    logger.info(f"   🟢 Безопасная: {entry['safe_gas_price']} Gwei")
                if 'standard_gas_price' in entry:
                    logger.info(f"   🟡 Стандартная: {entry['standard_gas_price']} Gwei")
                if 'fast_gas_price' in entry:
                    logger.info(f"   🔴 Быстрая: {entry['fast_gas_price']} Gwei")
            
            logger.info("")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при показе истории цен: {e}")