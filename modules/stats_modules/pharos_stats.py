import requests
import random
import time
import json
from fake_useragent import UserAgent
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import cycle
from colorama import Fore, Style
from pathlib import Path
from config.config import NUM_THREADS, RETRY_COUNT, SLEEP_BETWEEN_ACTIONS

proxies_list = []
wallets = []

print(Fore.GREEN + "Загрузка прокси из data/proxy.csv...")
with open("data/proxy.csv", "r") as f:
    proxies_list = [line.strip() for line in f.readlines()]
print(Fore.GREEN + f"Загружено {len(proxies_list)} прокси.")

print(Fore.GREEN + "Загрузка кошельков из data/walletss.txt...")
with open("data/walletss.txt", "r") as f:
    wallets = [line.strip() for line in f.readlines()]
print(Fore.GREEN + f"Загружено {len(wallets)} кошельков.")

platforms = ["\"Windows\"", "\"Linux\"", "\"macOS\""]
ua = UserAgent()

def generate_headers():
    user_agent = ua.chrome
    print(Fore.GREEN + f"Сгенерированы заголовки с User-Agent: {user_agent}")
    return {
        "accept": "*/*",
        "accept-language": "ru,en-US;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "priority": "u=1, i",
        "sec-ch-ua": "\"Google Chrome\";v=\"135\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"135\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": random.choice(platforms),
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": user_agent,
        "referer": "https://pharoshub.xyz/",
        "referrer": "https://pharoshub.xyz/"
    }

def send_request(wallet_address, proxy=None, retries=RETRY_COUNT):
    headers = generate_headers()
    
    for attempt in range(retries):
        proxy_dict = {
            "http": f"http://{proxy}",
            "https": f"http://{proxy}"
        } if proxy else None

        print(Fore.GREEN + f"Попытка {attempt + 1}/{retries} для кошелька {wallet_address} с использованием прокси {proxy}...")
        try:
            response = requests.post(
                "https://pharoshub.xyz/api/check-wallet",
                headers=headers,
                data=json.dumps({"wallet_address": wallet_address}),
                proxies=proxy_dict,
                timeout=15
            )
            print(Fore.GREEN + f"Успешный запрос для кошелька {wallet_address}. Код состояния: {response.status_code}")
            print(Fore.CYAN + f"Содержимое ответа: {response.text[:200]}...")
            
            if response.status_code == 200 and response.content.strip():
                return response.json()
            else:
                raise ValueError(f"Неверный ответ - Статус: {response.status_code}, Содержимое: {response.text}")
        except ValueError as ve:
            print(Fore.RED + f"Ошибка валидации для кошелька {wallet_address}: {ve}")
            if attempt < retries - 1:
                proxy = random.choice(proxies_list)  
                print(Fore.YELLOW + f"Замена прокси. Новый прокси: {proxy}")
            else:
                raise Exception(f"Ошибка запроса для кошелька {wallet_address}: {ve}")
        except Exception as e:
            print(Fore.RED + f"Неудачный запрос для кошелька {wallet_address}: {e}")
            if attempt < retries - 1:
                proxy = random.choice(proxies_list) 
                print(Fore.YELLOW + f"Замена прокси. Новый прокси: {proxy}")
            else:
                raise Exception(f"Ошибка запроса для кошелька {wallet_address}: {e}")

def pharos_wallet_stats():
    results_dir = Path("result/json")
    results_dir.mkdir(parents=True, exist_ok=True)
    print(Fore.GREEN + f"Каталог результатов создан в {results_dir}.")

    spinner_cycle = cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    bar_length = 40
    total_wallets = len(wallets)
    completed_wallets = 0

    def process_wallet_task(wallet_address, proxy):
        print(Fore.GREEN + f"Обработка кошелька {wallet_address} с прокси {proxy}...")
        try:
            result = send_request(wallet_address, proxy)
            print(result)
            print(Fore.GREEN + f"Результат для кошелька {wallet_address}: {result}")
            time.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            print(Fore.GREEN + f"Ожидание {random.uniform(*SLEEP_BETWEEN_ACTIONS)} секунд.")
            result_path = results_dir / f"{wallet_address}.json"
            with open(result_path, "w") as f:
                json.dump(result, f, indent=4)
            print(Fore.GREEN + f"Результат сохранен в {result_path}.")
            return wallet_address, True
        except Exception as e:
            print(Fore.RED + f"Ошибка при обработке кошелька {wallet_address}: {e}")
            return wallet_address, False

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        future_to_wallet = {
            executor.submit(
                process_wallet_task, wallet, proxies_list[i] if i < len(proxies_list) else random.choice(proxies_list)
            ): wallet
            for i, wallet in enumerate(wallets)
        }
        for future in as_completed(future_to_wallet):
            wallet = future_to_wallet[future]
            try:
                _, success = future.result(timeout=10)
                status_color = Fore.GREEN if success else Fore.RED
                print(Fore.GREEN + f"Завершена обработка кошелька {wallet}. Успешно: {success}")
            except Exception as e:
                status_color = Fore.RED
                print(Fore.RED + f"Необработанное исключение для кошелька {wallet}: {e}")
            finally:
                completed_wallets += 1
                progress = int((completed_wallets / total_wallets) * bar_length)
                bar = "█" * progress + "░" * (bar_length - progress)
                spinner_frame = next(spinner_cycle)
                print(
                    f"\r[{bar}] {completed_wallets}/{total_wallets} | {spinner_frame} | {status_color}Кошелек: {wallet}{Style.RESET_ALL}",
                    end="",
                    flush=True,
                )

    print(Fore.GREEN + "Обработка завершена.")