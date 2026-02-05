import csv
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
from web3 import Web3

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from modules.simple_logger import logger, setup_file_logging
from modules.proxy_manager import load_proxies, get_proxy_dict, mask_proxy
from config.modules.cfg_base import NUM_THREADS, RETRY_COUNT


def setup_proxy_checker_logging():
    log_dir = Path("log")
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f'proxy_checker_{timestamp}.log'
    setup_file_logging(str(log_file))
    logger.info(f"Логирование настроено. Файл: {log_file}")


def get_proxy_location(proxy_dict):
    session = None
    try:
        session = requests.Session()
        session.proxies.update(proxy_dict)
        
        response = session.get(
            'https://ipapi.co/json/',
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                'country': data.get('country_name', 'Unknown'),
                'city': data.get('city', 'Unknown'),
                'region': data.get('region', 'Unknown'),
                'org': data.get('org', 'Unknown'),
                'ip': data.get('ip', 'Unknown')
            }
    except Exception:
        pass
    finally:
        if session:
            session.close()
    
    return {
        'country': 'Unknown',
        'city': 'Unknown', 
        'region': 'Unknown',
        'org': 'Unknown',
        'ip': 'Unknown'
    }

def test_service_availability(proxy_dict, service_name, service_url, timeout=10):
    session = None
    try:
        start_time = time.time()
        
        session = requests.Session()
        session.proxies.update(proxy_dict)
        
        response = session.get(
            service_url,
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        
        response_time = round((time.time() - start_time) * 1000, 2)  # в миллисекундах
        
        return {
            'service': service_name,
            'status': 'SUCCESS',
            'status_code': response.status_code,
            'response_time_ms': response_time,
            'error': None
        }
        
    except requests.exceptions.Timeout:
        return {
            'service': service_name,
            'status': 'TIMEOUT',
            'status_code': 0,
            'response_time_ms': timeout * 1000,
            'error': 'Timeout'
        }
    except requests.exceptions.ProxyError as e:
        return {
            'service': service_name,
            'status': 'PROXY_ERROR',
            'status_code': 0,
            'response_time_ms': 0,
            'error': f'Proxy Error: {str(e)[:100]}'
        }
    except requests.exceptions.ConnectionError as e:
        return {
            'service': service_name,
            'status': 'CONNECTION_ERROR',
            'status_code': 0,
            'response_time_ms': 0,
            'error': f'Connection Error: {str(e)[:100]}'
        }
    except Exception as e:
        return {
            'service': service_name,
            'status': 'ERROR',
            'status_code': 0,
            'response_time_ms': 0,
            'error': f'Error: {str(e)[:100]}'
        }
    finally:
        if session:
            session.close()

def test_rpc_connection(proxy_dict, rpc_name, rpc_url, timeout=15):
    session = None
    try:
        start_time = time.time()
        
        session = requests.Session()
        session.proxies.update(proxy_dict)
        
        w3 = Web3(Web3.HTTPProvider(rpc_url, session=session))
        
        if not w3.is_connected():
            return {
                'rpc': rpc_name,
                'status': 'CONNECTION_FAILED',
                'block_height': 0,
                'response_time_ms': 0,
                'error': 'Failed to connect to RPC'
            }
        
        block_number = w3.eth.block_number
        response_time = round((time.time() - start_time) * 1000, 2)
        
        return {
            'rpc': rpc_name,
            'status': 'SUCCESS',
            'block_height': block_number,
            'response_time_ms': response_time,
            'error': None
        }
        
    except requests.exceptions.Timeout:
        return {
            'rpc': rpc_name,
            'status': 'TIMEOUT',
            'block_height': 0,
            'response_time_ms': timeout * 1000,
            'error': 'Timeout'
        }
    except Exception as e:
        return {
            'rpc': rpc_name,
            'status': 'ERROR',
            'block_height': 0,
            'response_time_ms': 0,
            'error': f'Error: {str(e)[:100]}'
        }
    finally:
        if session:
            session.close()

def comprehensive_proxy_test(proxy_string, proxy_index, total_proxies):
    
    test_services = {
        'Google': 'https://www.google.com',
        'GitHub': 'https://api.github.com',
        'CloudFlare': 'https://cloudflare.com',
        'JSONPlaceholder': 'https://jsonplaceholder.typicode.com/posts/1',
        'HTTPBin': 'https://httpbin.org/ip',
        'IPInfo': 'https://ipinfo.io/json',
        'CoinGecko': 'https://api.coingecko.com/api/v3/ping'
    }
    
    test_rpcs = {
        'ETH_Merkle': 'https://eth.merkle.io',
        'ETH_LlamaRPC': 'https://eth.llamarpc.com',
        'ETH_MEVBlocker': 'https://rpc.mevblocker.io',
        'ETH_DRPC': 'https://eth.drpc.org',
        'ETH_Blockrazor': 'https://eth.blockrazor.xyz'
    }
    
    logger.debug(f"🔍 Тестирование прокси {proxy_index}/{total_proxies}: {proxy_string[:20]}...")
    
    proxy_dict = get_proxy_dict(proxy_string)
    if not proxy_dict:
        return {
            'proxy': proxy_string,
            'status': 'INVALID_FORMAT',
            'location': {},
            'services': [],
            'rpcs': [],
            'total_response_time': 0,
            'success_rate': 0,
            'test_duration': 0,
            'successful_services': 0,
            'successful_rpcs': 0,
            'retry_attempt': 0
        }
    
    best_result = None
    
    for attempt in range(RETRY_COUNT + 1):
        start_time = time.time()
        
        logger.debug(f"Попытка {attempt + 1}/{RETRY_COUNT + 1} для прокси {proxy_string[:20]}...")
        
        if attempt == 0:
            logger.debug(f"Получаем геолокацию для {proxy_string[:20]}...")
            location = get_proxy_location(proxy_dict)
        else:
            location = best_result.get('location', {}) if best_result else {}
        
        logger.debug(f"Тестируем {len(test_services)} сервисов...")
        service_results = []
        for service_name, service_url in test_services.items():
            result = test_service_availability(proxy_dict, service_name, service_url)
            service_results.append(result)
            logger.debug(f"  {service_name}: {result['status']} ({result['response_time_ms']}ms)")
        
        logger.debug(f"Тестируем {len(test_rpcs)} RPC...")
        rpc_results = []
        for rpc_name, rpc_url in test_rpcs.items():
            result = test_rpc_connection(proxy_dict, rpc_name, rpc_url)
            rpc_results.append(result)
            logger.debug(f"  {rpc_name}: {result['status']} (блок: {result['block_height']})")
        
        successful_services = len([r for r in service_results if r['status'] == 'SUCCESS'])
        successful_rpcs = len([r for r in rpc_results if r['status'] == 'SUCCESS'])
        total_tests = len(service_results) + len(rpc_results)
        success_rate = ((successful_services + successful_rpcs) / total_tests * 100) if total_tests > 0 else 0
        
        total_response_time = sum([r['response_time_ms'] for r in service_results + rpc_results if r['response_time_ms'] > 0])
        
        test_duration = round((time.time() - start_time), 2)
        
        current_result = {
            'proxy': proxy_string,
            'status': 'WORKING' if success_rate > 50 else 'PARTIALLY_WORKING' if success_rate > 0 else 'NOT_WORKING',
            'location': location,
            'services': service_results,
            'rpcs': rpc_results,
            'total_response_time': total_response_time,
            'success_rate': round(success_rate, 2),
            'test_duration': test_duration,
            'successful_services': successful_services,
            'successful_rpcs': successful_rpcs,
            'retry_attempt': attempt + 1
        }
        
        if best_result is None or current_result['success_rate'] > best_result['success_rate']:
            best_result = current_result
        
        if success_rate > 50:
            logger.debug(f"✅ Прокси {proxy_index}: {proxy_string[:20]}... - Отлично работает ({success_rate:.1f}%) на попытке {attempt + 1}")
            break
        
        if success_rate > 0 and attempt < RETRY_COUNT:
            logger.debug(f"⚠️ Прокси {proxy_index}: {proxy_string[:20]}... - Частично работает ({success_rate:.1f}%), попытка {attempt + 1}")
            time.sleep(random.uniform(1, 3)) 
            continue
        
        if success_rate == 0 and attempt < RETRY_COUNT:
            logger.debug(f"❌ Прокси {proxy_index}: {proxy_string[:20]}... - Не работает ({success_rate:.1f}%), повтор {attempt + 1}/{RETRY_COUNT}")
            time.sleep(random.uniform(2, 5)) 
            continue
        
        if attempt == RETRY_COUNT:
            logger.debug(f"❌ Прокси {proxy_index}: {proxy_string[:20]}... - Финальный результат после {attempt + 1} попыток: ({success_rate:.1f}%)")
            break
    
    final_result = best_result if best_result else current_result
    
    if final_result['success_rate'] > 70:
        logger.debug(f"✅ Прокси {proxy_index}: {proxy_string[:20]}... - Итого: Отлично работает ({final_result['success_rate']:.1f}%)")
    elif final_result['success_rate'] > 30:
        logger.debug(f"⚠️ Прокси {proxy_index}: {proxy_string[:20]}... - Итого: Частично работает ({final_result['success_rate']:.1f}%)")
    else:
        logger.debug(f"❌ Прокси {proxy_index}: {proxy_string[:20]}... - Итого: Не работает ({final_result['success_rate']:.1f}%)")
    
    return final_result

def save_proxy_test_results(results):
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_dir = Path(f"result/proxy/{timestamp}")
    result_dir.mkdir(parents=True, exist_ok=True)
    
    main_file = result_dir / f"proxy_test_results.csv"
    
    services_file = result_dir / f"proxy_services_test.csv"
    
    rpcs_file = result_dir / f"proxy_rpcs_test.csv"
    
    working_file = result_dir / f"working_proxies.csv"
    
    total_stats_file = result_dir / f"total_statistics.csv"
    
    try:
        with open(main_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'proxy', 'status', 'success_rate', 'country', 'city', 'region', 'org', 'ip',
                'total_response_time', 'test_duration', 'successful_services', 'successful_rpcs'
            ])
            
            for result in results:
                location = result.get('location', {})
                writer.writerow([
                    result['proxy'],
                    result['status'],
                    result['success_rate'],
                    location.get('country', ''),
                    location.get('city', ''),
                    location.get('region', ''),
                    location.get('org', ''),
                    location.get('ip', ''),
                    result['total_response_time'],
                    result['test_duration'],
                    result['successful_services'],
                    result['successful_rpcs']
                ])
        
        logger.success(f"💾 Основные результаты сохранены в {main_file}")
        
        with open(services_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['proxy', 'service', 'status', 'status_code', 'response_time_ms', 'error'])
            
            for result in results:
                proxy = result['proxy']
                for service in result.get('services', []):
                    writer.writerow([
                        proxy,
                        service['service'],
                        service['status'],
                        service['status_code'],
                        service['response_time_ms'],
                        service.get('error', '')
                    ])
        
        logger.success(f"💾 Результаты по сервисам сохранены в {services_file}")
        
        with open(rpcs_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['proxy', 'rpc', 'status', 'block_height', 'response_time_ms', 'error'])
            
            for result in results:
                proxy = result['proxy']
                for rpc in result.get('rpcs', []):
                    writer.writerow([
                        proxy,
                        rpc['rpc'],
                        rpc['status'],
                        rpc['block_height'],
                        rpc['response_time_ms'],
                        rpc.get('error', '')
                    ])
        
        logger.success(f"💾 Результаты по RPC сохранены в {rpcs_file}")
        
        working_proxies = [r for r in results if r['success_rate'] > 50]
        
        with open(working_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['proxy'])
            
            for result in working_proxies:
                writer.writerow([result['proxy']])
        
        logger.success(f"💾 Работающие прокси сохранены в {working_file} ({len(working_proxies)} шт.)")
        
        save_total_statistics(results, total_stats_file)
        
        return {
            'main_file': str(main_file),
            'services_file': str(services_file),
            'rpcs_file': str(rpcs_file),
            'working_file': str(working_file),
            'total_stats_file': str(total_stats_file),
            'summary_stats_file': str(total_stats_file.parent / "summary_statistics.csv"),
            'result_dir': str(result_dir)
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения результатов: {e}")
        return None

def save_total_statistics(results, stats_file):
    
    try:
        with open(stats_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            writer.writerow([
                'proxy', 'success_rate_percent', 'avg_response_time_ms', 
                'error_code', 'country', 'city', 'status'
            ])
            
            for result in results:
                proxy = result['proxy']
                success_rate = result['success_rate']
                
                all_responses = []
                for service in result.get('services', []):
                    if service['status'] == 'SUCCESS' and service['response_time_ms'] > 0:
                        all_responses.append(service['response_time_ms'])
                
                for rpc in result.get('rpcs', []):
                    if rpc['status'] == 'SUCCESS' and rpc['response_time_ms'] > 0:
                        all_responses.append(rpc['response_time_ms'])
                
                avg_response_time = round(sum(all_responses) / len(all_responses), 2) if all_responses else 0
                
                error_code = 'OK' 
                
                if result['status'] == 'INVALID_FORMAT':
                    error_code = 'INVALID_FORMAT'
                elif result['status'] == 'EXCEPTION':
                    error_code = 'EXCEPTION'
                elif result['status'] == 'NOT_WORKING':
                    error_counts = {}
                    
                    for service in result.get('services', []):
                        if service['status'] != 'SUCCESS':
                            error_type = service['status']
                            error_counts[error_type] = error_counts.get(error_type, 0) + 1
                    
                    for rpc in result.get('rpcs', []):
                        if rpc['status'] != 'SUCCESS':
                            error_type = rpc['status']
                            error_counts[error_type] = error_counts.get(error_type, 0) + 1
                    
                    if error_counts:
                        error_code = max(error_counts, key=error_counts.get)
                    else:
                        error_code = 'UNKNOWN_ERROR'
                elif result['status'] == 'PARTIALLY_WORKING':
                    error_code = 'PARTIAL'
                
                location = result.get('location', {})
                country = location.get('country', 'Unknown')
                city = location.get('city', 'Unknown')
                status = result['status']
                
                writer.writerow([
                    proxy,
                    f"{success_rate:.1f}",
                    avg_response_time,
                    error_code,
                    country,
                    city,
                    status
                ])
        
        logger.success(f"💾 Общая статистика сохранена в {stats_file}")
        
        summary_file = stats_file.parent / "summary_statistics.csv"
        save_summary_statistics(results, summary_file)
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения общей статистики: {e}")

def save_summary_statistics(results, summary_file):
    
    try:
        total_proxies = len(results)
        working_proxies = len([r for r in results if r['status'] == 'WORKING'])
        partially_working = len([r for r in results if r['status'] == 'PARTIALLY_WORKING'])
        not_working = len([r for r in results if r['status'] == 'NOT_WORKING'])
        invalid_format = len([r for r in results if r['status'] == 'INVALID_FORMAT'])
        exceptions = len([r for r in results if r['status'] == 'EXCEPTION'])
        
        avg_success_rate = sum([r['success_rate'] for r in results]) / total_proxies if total_proxies > 0 else 0
        avg_response_time = sum([r['total_response_time'] for r in results]) / total_proxies if total_proxies > 0 else 0
        avg_test_duration = sum([r['test_duration'] for r in results]) / total_proxies if total_proxies > 0 else 0
        
        countries = {}
        for result in results:
            if result['success_rate'] > 50: 
                location = result.get('location', {})
                country = location.get('country', 'Unknown')
                countries[country] = countries.get(country, 0) + 1
        
        top_countries = sorted(countries.items(), key=lambda x: x[1], reverse=True)[:3]
        
        service_stats = {}
        for result in results:
            for service in result.get('services', []):
                service_name = service['service']
                if service_name not in service_stats:
                    service_stats[service_name] = {'success': 0, 'total': 0}
                service_stats[service_name]['total'] += 1
                if service['status'] == 'SUCCESS':
                    service_stats[service_name]['success'] += 1
        
        rpc_stats = {}
        for result in results:
            for rpc in result.get('rpcs', []):
                rpc_name = rpc['rpc']
                if rpc_name not in rpc_stats:
                    rpc_stats[rpc_name] = {'success': 0, 'total': 0}
                rpc_stats[rpc_name]['total'] += 1
                if rpc['status'] == 'SUCCESS':
                    rpc_stats[rpc_name]['success'] += 1
        
        with open(summary_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            writer.writerow(['Metric', 'Value'])
            
            writer.writerow(['Test Date', datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
            writer.writerow(['Total Proxies Tested', total_proxies])
            writer.writerow(['Working Proxies', working_proxies])
            writer.writerow(['Working Proxies %', f"{working_proxies/total_proxies*100:.1f}%" if total_proxies > 0 else "0%"])
            writer.writerow(['Partially Working', partially_working])
            writer.writerow(['Partially Working %', f"{partially_working/total_proxies*100:.1f}%" if total_proxies > 0 else "0%"])
            writer.writerow(['Not Working', not_working])
            writer.writerow(['Not Working %', f"{not_working/total_proxies*100:.1f}%" if total_proxies > 0 else "0%"])
            writer.writerow(['Invalid Format', invalid_format])
            writer.writerow(['Exceptions', exceptions])
            writer.writerow(['Average Success Rate %', f"{avg_success_rate:.2f}%"])
            writer.writerow(['Average Response Time ms', f"{avg_response_time:.2f}"])
            writer.writerow(['Average Test Duration sec', f"{avg_test_duration:.2f}"])
            
            writer.writerow(['', ''])
            
            writer.writerow(['Top Countries (Working Proxies)', ''])
            for i, (country, count) in enumerate(top_countries, 1):
                writer.writerow([f"{i}. {country}", count])
            
            writer.writerow(['', ''])
            
            writer.writerow(['Service Success Rates', ''])
            for service_name, stats in service_stats.items():
                success_rate = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
                writer.writerow([service_name, f"{success_rate:.1f}% ({stats['success']}/{stats['total']})"])
            
            writer.writerow(['', ''])
            
            writer.writerow(['RPC Success Rates', ''])
            for rpc_name, stats in rpc_stats.items():
                success_rate = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
                writer.writerow([rpc_name, f"{success_rate:.1f}% ({stats['success']}/{stats['total']})"])
        
        logger.success(f"💾 Сводная статистика сохранена в {summary_file}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения сводной статистики: {e}")

def print_test_statistics(results):
    
    if not results:
        logger.warning("⚠️ Нет результатов для анализа")
        return
    
    total_proxies = len(results)
    working_proxies = len([r for r in results if r['status'] == 'WORKING'])
    partially_working = len([r for r in results if r['status'] == 'PARTIALLY_WORKING'])
    not_working = len([r for r in results if r['status'] == 'NOT_WORKING'])
    invalid_format = len([r for r in results if r['status'] == 'INVALID_FORMAT'])
    
    logger.info("="*80)
    logger.info("📊 СТАТИСТИКА ТЕСТИРОВАНИЯ ПРОКСИ")
    logger.info("="*80)
    logger.info(f"📈 Всего прокси протестировано: {total_proxies}")
    logger.success(f"✅ Работающих прокси: {working_proxies} ({working_proxies/total_proxies*100:.1f}%)")
    logger.warning(f"⚠️ Частично работающих: {partially_working} ({partially_working/total_proxies*100:.1f}%)")
    logger.error(f"❌ Не работающих: {not_working} ({not_working/total_proxies*100:.1f}%)")
    
    if invalid_format > 0:
        logger.error(f"🔧 Неверный формат: {invalid_format} ({invalid_format/total_proxies*100:.1f}%)")
    
    working_results = [r for r in results if r['success_rate'] > 0]
    if working_results:
        working_results.sort(key=lambda x: x['success_rate'], reverse=True)
        
        logger.info("\n🏆 ТОП-5 ЛУЧШИХ ПРОКСИ:")
        logger.info("-" * 60)
        
        for i, result in enumerate(working_results[:5], 1):
            location = result.get('location', {})
            country = location.get('country', 'Unknown')
            city = location.get('city', 'Unknown')
            
            logger.info(f"{i}. {result['proxy'][:30]}...")
            logger.info(f"   📊 Успешность: {result['success_rate']:.1f}%")
            logger.info(f"   🌍 Локация: {city}, {country}")
            logger.info(f"   ⏱️ Время ответа: {result['total_response_time']:.0f}ms")
            logger.info("")
    
    countries = {}
    for result in results:
        if result['success_rate'] > 50:
            location = result.get('location', {})
            country = location.get('country', 'Unknown')
            countries[country] = countries.get(country, 0) + 1
    
    if countries:
        logger.info("🌍 РАБОТАЮЩИЕ ПРОКСИ ПО СТРАНАМ:")
        logger.info("-" * 40)
        
        sorted_countries = sorted(countries.items(), key=lambda x: x[1], reverse=True)
        for country, count in sorted_countries[:10]: 
            logger.info(f"   {country}: {count} прокси")
    
    logger.info("="*80)

def check_proxy_menu():
    
    setup_proxy_checker_logging()
    
    logger.info("🚀 Запуск модуля проверки прокси")
    logger.info("="*80)
    logger.info("🔍 ПРОДВИНУТАЯ ПРОВЕРКА ПРОКСИ")
    logger.info("="*80)
    
    proxies = load_proxies()
    
    if not proxies:
        logger.error("❌ Не найдено прокси для тестирования")
        return
    
    logger.info(f"📂 Загружено {len(proxies)} прокси для тестирования")
    logger.info(f"🧵 Потоков: {NUM_THREADS}")
    logger.info(f"🔄 Повторных попыток для неработающих прокси: {RETRY_COUNT}")
    logger.info("🔧 Тестируемые сервисы: Google, GitHub, CloudFlare, JSONPlaceholder, HTTPBin, IPInfo, CoinGecko")
    logger.info("⚡ Тестируемые RPC: ETH Merkle, LlamaRPC, MEVBlocker, DRPC, Payload, Blockrazor")
    
    try:
        max_proxies = input(f"\nВведите максимальное количество прокси для тестирования (Enter для всех {len(proxies)}): ").strip()
        if max_proxies:
            max_proxies = int(max_proxies)
            if max_proxies > 0 and max_proxies < len(proxies):
                proxies = proxies[:max_proxies]
                logger.info(f"🔧 Ограничиваем тестирование до {max_proxies} прокси")
    except ValueError:
        logger.warning("⚠️ Неверное число, используем все прокси")
    except KeyboardInterrupt:
        logger.info("👋 Выход по запросу пользователя")
        return
    
    logger.info(f"🔄 Начинаем многопоточное тестирование {len(proxies)} прокси...")
    logger.info(f"🧵 Используем {NUM_THREADS} потоков")
    logger.info("-" * 80)
    
    results = []
    start_time = time.time()
    completed_count = 0
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_proxy = {
            executor.submit(comprehensive_proxy_test, proxy, i + 1, len(proxies)): (proxy, i + 1)
            for i, proxy in enumerate(proxies)
        }
        
        for future in as_completed(future_to_proxy):
            proxy, proxy_index = future_to_proxy[future]
            completed_count += 1
            
            try:
                result = future.result(timeout=300) 
                results.append(result)
                
                if completed_count % 10 == 0 or completed_count == len(proxies):
                    progress_percent = (completed_count / len(proxies)) * 100
                    retry_info = f"(попытка {result.get('retry_attempt', 1)})" if result.get('retry_attempt', 1) > 1 else ""
                    logger.info(f"📊 Прогресс: {completed_count}/{len(proxies)} ({progress_percent:.1f}%) - Последний: {result['status']} ({result['success_rate']:.1f}%) {retry_info}")
                
            except Exception as e:
                logger.error(f"❌ Исключение при тестировании прокси {proxy_index}: {str(e)[:100]}...")
                results.append({
                    'proxy': proxy,
                    'status': 'EXCEPTION',
                    'location': {},
                    'services': [],
                    'rpcs': [],
                    'total_response_time': 0,
                    'success_rate': 0,
                    'test_duration': 0,
                    'successful_services': 0,
                    'successful_rpcs': 0,
                    'retry_attempt': 1
                })
    
    total_duration = round(time.time() - start_time, 2)
    
    logger.info("="*80)
    logger.success(f"✅ Многопоточное тестирование завершено за {total_duration} секунд")
    logger.info(f"⚡ Средняя скорость: {len(proxies)/total_duration:.2f} прокси/сек")
    
    print_test_statistics(results)
    
    logger.info("💾 Сохраняем результаты...")
    saved_files = save_proxy_test_results(results)
    
    if saved_files:
        logger.success("✅ Все результаты успешно сохранены!")
        logger.info(f"📁 Директория результатов: {saved_files['result_dir']}")
        logger.info("📄 Файлы результатов:")
        logger.info(f"   • Основные результаты: proxy_test_results.csv")
        logger.info(f"   • Детали по сервисам: proxy_services_test.csv")
        logger.info(f"   • Детали по RPC: proxy_rpcs_test.csv")
        logger.info(f"   • Работающие прокси: working_proxies.csv")
        logger.info(f"   • Статистика по прокси: total_statistics.csv")
        logger.info(f"   • Сводная статистика: summary_statistics.csv")
    
    logger.info("="*80)
    logger.info("🎉 Проверка прокси завершена!")
