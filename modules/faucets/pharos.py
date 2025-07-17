import json
import asyncio
import aiohttp
import csv
import sys
from typing import Optional, List, Tuple
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from eth_account import Account
from pathlib import Path
from colorama import Fore, Style, init

# Инициализируем colorama для Windows
init()

class StatusDisplay:
    """Класс для управления динамическим отображением статусов"""
    
    def __init__(self, wallet_address: str):
        self.wallet_address = wallet_address
        self.lines_printed = 0
        self.statuses = {
            'twitter': {'text': '💾 twitter', 'status': 'pending', 'details': ''},
            'pharos_login': {'text': '✅ Pharos login', 'status': 'pending', 'details': ''},
            'faucet': {'text': '🚰 Starting faucet request', 'status': 'pending', 'details': ''},
            'account': {'text': '🎉 account status', 'status': 'pending', 'details': ''}
        }
        self.printed_header = False
        
    def print_header(self):
        """Печатает заголовок один раз"""
        if not self.printed_header:
            print(f"{Fore.GREEN}🚀 Starting Pharos process for {self.wallet_address}{Style.RESET_ALL}")
            self.printed_header = True
            
    def print_initial_status(self):
        """Печатает начальные статусы всех строк с учетом предустановленных статусов"""
        self.print_header()
        for key in ['twitter', 'pharos_login', 'faucet', 'account']:
            status_info = self.statuses[key]
            
            # Определяем цвет и текст на основе текущего статуса
            if status_info['status'] == 'already_connected':
                color = Fore.GREEN
                status_text = 'already connected'
            elif status_info['status'] == 'already_requested':
                color = Fore.YELLOW
                status_text = 'already requested today'
            elif status_info['status'] == 'success':
                color = Fore.GREEN
                status_text = 'successful'
                if status_info['details']:
                    status_text += f" {status_info['details']}"
            else:
                color = Fore.YELLOW  # pending - желтый
                status_text = 'pending'
            
            print(f"    {status_info['text']} - {color}{status_text}{Style.RESET_ALL}")
            self.lines_printed += 1
            
    def update_status(self, key: str, status: str, details: str = ''):
        """Обновляет статус конкретной строки"""
        if key not in self.statuses:
            return
            
        self.statuses[key]['status'] = status
        self.statuses[key]['details'] = details
        
        # Определяем цвет по статусу
        color_map = {
            'pending': Fore.YELLOW,
            'success': Fore.GREEN,
            'error': Fore.RED,
            'already_connected': Fore.GREEN,
            'already_requested': Fore.YELLOW
        }
        color = color_map.get(status, Fore.YELLOW)
        
        # Формируем текст статуса
        status_text_map = {
            'pending': 'pending',
            'success': 'successful',
            'error': 'error',
            'already_connected': 'already connected',
            'already_requested': 'already requested today'
        }
        status_text = status_text_map.get(status, status)
        
        # Добавляем детали если есть
        full_text = f"{self.statuses[key]['text']} - {status_text}"
        if details:
            full_text += f" {details}"
            
        # Обновляем строку
        self._update_line(key, full_text, color)
        
    def _update_line(self, key: str, text: str, color: str):
        """Обновляет конкретную строку в терминале"""
        # Определяем позицию строки
        line_positions = {'twitter': 0, 'pharos_login': 1, 'faucet': 2, 'account': 3}
        line_pos = line_positions[key]
        
        # Перемещаемся к нужной строке
        lines_to_move_up = self.lines_printed - line_pos - 1
        if lines_to_move_up > 0:
            # Используем \033[F для перемещения к началу предыдущей строки
            for _ in range(lines_to_move_up):
                sys.stdout.write('\033[F')  # Курсор в начало предыдущей строки
            
        # Очищаем строку и пишем новый текст
        sys.stdout.write('\r\033[K')  # Очистить строку
        sys.stdout.write(f"    {color}{text}{Style.RESET_ALL}")
        
        # Возвращаемся в конец
        if lines_to_move_up > 0:
            # Перемещаемся обратно в конец
            for _ in range(lines_to_move_up):
                sys.stdout.write('\n')  # Переходим на следующую строку
                
        sys.stdout.flush()

def load_twitter_tokens() -> List[Tuple[str, str]]:
    """Загружает Twitter токены и ct0 из файла data/twitter_tokens.csv"""
    try:
        project_root = Path(__file__).parent.parent.parent
        tokens_file = project_root / 'data' / 'twitter_tokens.csv'
        
        print(f"{Fore.CYAN}🔍 Looking for CSV file at: {tokens_file}{Style.RESET_ALL}")
        
        if not tokens_file.exists():
            print(f"{Fore.RED}❌ Файл {tokens_file} не найден!{Style.RESET_ALL}")
            return []
        
        tokens = []
        with open(tokens_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                print(f"{Fore.RED}❌ CSV файл пустой!{Style.RESET_ALL}")
                return []
            
            # Проверяем содержимое файла
            print(f"{Fore.CYAN}📄 First 200 chars of CSV: {content[:200]}{Style.RESET_ALL}")
            
            # Перематываем файл
            f.seek(0)
            reader = csv.DictReader(f)
            
            for row_num, row in enumerate(reader, 1):
                auth_token = row.get('auth_token', '').strip()
                ct0 = row.get('ct0', '').strip()
                
                if auth_token and ct0:
                    tokens.append((auth_token, ct0))
                    # Убираем debug сообщения для чистоты
                else:
                    print(f"{Fore.YELLOW}⚠️ Row {row_num} missing data: auth_token={bool(auth_token)}, ct0={bool(ct0)}{Style.RESET_ALL}")
        
        print(f"{Fore.GREEN}📱 Successfully loaded {len(tokens)} token pairs from CSV{Style.RESET_ALL}")
        return tokens
        
    except FileNotFoundError:
        print(f"{Fore.RED}❌ Файл data/twitter_tokens.csv не найден!{Style.RESET_ALL}")
        # Создаем пример файла
        try:
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / 'data'
            data_dir.mkdir(exist_ok=True)
            example_file = data_dir / 'twitter_tokens.csv'
            with open(example_file, 'w', encoding='utf-8') as f:
                f.write("auth_token,ct0\n")
                f.write("example_token_1,example_ct0_1\n")
                f.write("example_token_2,example_ct0_2\n")
            print(f"{Fore.GREEN}📝 Created example file at {example_file}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Failed to create example file: {e}{Style.RESET_ALL}")
        return []
    except Exception as e:
        print(f"{Fore.RED}❌ Ошибка при чтении CSV файла: {e}{Style.RESET_ALL}")
        return []

def load_wallet_data(wallet_address: str) -> dict:
    """Загружает данные кошелька из JSON файла"""
    try:
        project_root = Path(__file__).parent.parent.parent
        json_dir = project_root / 'result' / 'json' / 'pharos_faucet'
        json_dir.mkdir(parents=True, exist_ok=True)
        json_file = json_dir / f"{wallet_address}.json"
        
        if json_file.exists():
            with open(json_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    print(f"{Fore.YELLOW}JSON file for {wallet_address} is empty{Style.RESET_ALL}")
                    return {}
                return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"{Fore.RED}JSON decode error for {wallet_address}: {e}{Style.RESET_ALL}")
        # Удаляем поврежденный файл
        try:
            json_file.unlink()
            print(f"{Fore.GREEN}Removed corrupted JSON file for {wallet_address}{Style.RESET_ALL}")
        except:
            pass
    except Exception as e:
        print(f"{Fore.RED}Error loading wallet data: {e}{Style.RESET_ALL}")
    return {}

def save_wallet_data(wallet_address: str, data: dict):
    """Сохраняет данные кошелька в JSON файл"""
    try:
        project_root = Path(__file__).parent.parent.parent
        json_dir = project_root / 'result' / 'json' / 'pharos_faucet'
        json_dir.mkdir(parents=True, exist_ok=True)
        json_file = json_dir / f"{wallet_address}.json"
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"{Fore.RED}Error saving wallet data: {e}{Style.RESET_ALL}")

async def pharos_faucet_complete(proxy: str, private_key: str, wallet_address: Optional[str] = None):
    """
    Функция для Pharos с динамическим отображением статуса
    """
    
    # Извлекаем адрес кошелька из приватного ключа
    if not wallet_address:
        account = Account.from_key(private_key)
        wallet_address = account.address
    
    # СНАЧАЛА загружаем данные кошелька
    wallet_data = load_wallet_data(wallet_address)
    twitter_connected = wallet_data.get('twitter_connected', False)
    
    # Создаем дисплей статуса
    status_display = StatusDisplay(wallet_address)
    
    # Определяем начальные статусы ДО печати
    if twitter_connected and wallet_data.get('successful_twitter_token') and wallet_data.get('successful_ct0_token'):
        # Если Twitter уже подключен, предустанавливаем все статусы
        status_display.statuses['twitter']['status'] = 'already_connected'
        
        # Предполагаем что если Twitter подключен, то Pharos login тоже будет успешным
        status_display.statuses['pharos_login']['status'] = 'success'
        status_display.statuses['pharos_login']['details'] = f'for {wallet_address}'
        
        # Предполагаем что faucet уже запрошен
        status_display.statuses['faucet']['status'] = 'already_requested'
        status_display.statuses['account']['status'] = 'already_requested'
    
    # Теперь печатаем статусы с правильными начальными состояниями
    status_display.print_initial_status()
    
    class TwitterAuthConfig:
        CLIENT_ID = "TGQwNktPQWlBQzNNd1hyVkFvZ2E6MTpjaQ"
        REDIRECT_URI = "https://testnet.pharosnetwork.xyz"
        BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
        API_DOMAIN = "twitter.com"
        OAUTH2_PATH = "/i/api/2/oauth2/authorize"
        REQUIRED_SCOPES = "users.read tweet.read follows.read"
    
    class TwitterClient:
        def __init__(self, twitter_token: str, ct0_token: str, proxy: str):
            self.twitter_token = twitter_token
            self.ct0_token = ct0_token
            self.proxy = proxy
            self.state = None
            self.code_challenge = None

        def build_headers(self) -> dict:
            return {
                'authority': TwitterAuthConfig.API_DOMAIN,
                'accept': '*/*',
                'accept-language': 'ru,en-US;q=0.9,en;q=0.8',
                'authorization': f'Bearer {TwitterAuthConfig.BEARER_TOKEN}',
                'cookie': f'auth_token={self.twitter_token}; ct0={self.ct0_token}',
                'x-csrf-token': self.ct0_token,
            }

        def build_auth_params(self, code_challenge, state) -> dict:
            self.code_challenge, self.state = code_challenge, state
            return {
                "code_challenge": self.code_challenge,
                "code_challenge_method": "S256",
                "client_id": TwitterAuthConfig.CLIENT_ID,
                "redirect_uri": TwitterAuthConfig.REDIRECT_URI,
                "response_type": "code",
                "scope": TwitterAuthConfig.REQUIRED_SCOPES,
                "state": self.state
            }

        @staticmethod
        def extract_code_from_redirect(redirect_uri: str) -> str:
            parsed = urlparse(redirect_uri)
            query_params = parse_qs(parsed.query)
            return query_params.get('code', [''])[0]

        async def connect_twitter(self, code_challenge, state) -> str | None:
            """Подключает Twitter используя переданные токены"""
            headers = self.build_headers()
            connector = aiohttp.TCPConnector()
            
            try:
                async with aiohttp.ClientSession(
                    headers=headers, 
                    connector=connector,
                    trust_env=True
                ) as session:
                    auth_url = f"https://{TwitterAuthConfig.API_DOMAIN}{TwitterAuthConfig.OAUTH2_PATH}"
                    
                    # Первый запрос - получение auth_code
                    async with session.get(
                        auth_url, 
                        params=self.build_auth_params(code_challenge, state),
                        proxy=self.proxy if self.proxy else None
                    ) as auth_response:
                        if auth_response.status == 403:
                            return None
                        elif auth_response.status != 200:
                            return None
                            
                        try:
                            auth_data = await auth_response.json()
                            auth_code = auth_data.get('auth_code')
                            if not auth_code:
                                return None
                        except Exception as e:
                            return None
                            
                    # Второй запрос - подтверждение  
                    async with session.post(
                        auth_url,
                        params={"approval": "true", "code": auth_code},
                        proxy=self.proxy if self.proxy else None
                    ) as approve_response:
                        if approve_response.status != 200:
                            return None
                            
                        try:
                            approve_data = await approve_response.json()
                            redirect_uri = approve_data.get('redirect_uri')
                            if not redirect_uri:
                                return None
                            
                            final_code = self.extract_code_from_redirect(redirect_uri)
                            if final_code:
                                return final_code
                        except Exception as e:
                            return None

            except Exception as error:
                pass
                
            return None

    class PharosHubClient:
        def __init__(self, wallet_address: str, private_key: str, twitter_token: str, ct0_token: str, proxy: str):
            self.wallet_address = wallet_address
            self.private_key = private_key
            self.twitter_token = twitter_token
            self.ct0_token = ct0_token
            self.proxy = proxy
            self.auth_token = None
            self.session = None
            self.account = Account.from_key(private_key)
            self.twitter_worker = TwitterClient(twitter_token, ct0_token, proxy)
            
        async def create_session(self):
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
            
        async def close_session(self):
            if self.session and not self.session.closed:
                await self.session.close()
                
        def get_headers(self, auth=True):
            headers = {
                'authority': 'api.pharosnetwork.xyz',
                'accept': 'application/json',
                'content-type': 'application/json',
                'origin': 'https://testnet.pharosnetwork.xyz',
                'referer': 'https://testnet.pharosnetwork.xyz/',
                'cache-control': 'no-cache',
                'pragma': 'no-cache',
                'priority': 'u=1, i',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin'
            }
            if auth and self.auth_token:
                headers['authorization'] = f'Bearer {self.auth_token}'
            return headers
            
        async def get_signature(self, text='pharos'):
            """Создает подпись для авторизации кошелька"""
            try:
                from eth_account.messages import encode_defunct
                message = encode_defunct(text=text)
                signed_message = self.account.sign_message(message)
                return signed_message.signature.hex()
            except Exception as e:
                print(f"{Fore.RED}Signature error: {e}{Style.RESET_ALL}")
                return "0x" + "a" * 130  # Fallback
            
        async def pharoshub_login(self):
            """Авторизация через api.pharosnetwork.xyz"""
            try:
                signature = await self.get_signature('pharos')
                
                url = f"https://api.pharosnetwork.xyz/user/login?address={self.wallet_address}&signature={signature}"
                json_data = {
                    'address': self.wallet_address,
                    'signature': signature,
                }
                
                async with self.session.post(
                    url, 
                    json=json_data, 
                    headers=self.get_headers(auth=False),
                    proxy=self.proxy if self.proxy else None
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        token = data.get("data", {}).get("jwt")
                        if token:
                            self.auth_token = token
                            return True
                            
                return False
                
            except Exception as e:
                return False

        async def get_auth_link(self):
            """Получает параметры авторизации"""
            for attempt in range(3):
                try:
                    base_url = "https://api.pharosnetwork.xyz/auth/twitter"
                    timeout = aiohttp.ClientTimeout(total=30)
                    connector = aiohttp.TCPConnector()
                    
                    async with aiohttp.ClientSession(
                        timeout=timeout, 
                        connector=connector
                    ) as session:
                        async with session.get(
                            base_url, 
                            headers=self.get_headers(), 
                            allow_redirects=False,
                            proxy=self.proxy if self.proxy else None
                        ) as response:
                            location = response.headers.get("Location")
                            if not location:
                                return None, None
                            parsed_url = urlparse(location)
                            query_params = parse_qs(parsed_url.query)
                            code_challenge = query_params.get("code_challenge", [""])[0]
                            state = query_params.get("state", [""])[0]
                            return code_challenge, state
                except aiohttp.ClientError as e:
                    print(f"{Fore.RED}Request failed: {str(e)}{Style.RESET_ALL}")
                    if attempt < 2:
                        await asyncio.sleep(1)
            return None, None

        async def connect_twitter(self):
            """Подключает Twitter"""
            code_challenge, state = await self.get_auth_link()
            if not (code_challenge and state):
                return False

            code = await self.twitter_worker.connect_twitter(code_challenge, state)
            if not code:
                return False

            # Привязываем аккаунт к Pharos
            url = "https://api.pharosnetwork.xyz/auth/bind/twitter"
            data = {'state': self.twitter_worker.state, 'code': code, 'address': self.wallet_address}
            
            try:
                async with self.session.post(
                    url, 
                    json=data, 
                    headers=self.get_headers(),
                    proxy=self.proxy if self.proxy else None
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        status = result.get("code")
                        if status == 0:
                            return True
                        else:
                            return False
                    else:
                        return False
                        
            except Exception as e:
                return False

        async def status_faucet(self):
            """Проверяет статус фаусета"""
            try:
                url = f"https://api.pharosnetwork.xyz/faucet/status?address={self.wallet_address}"
                data = {'address': self.wallet_address}

                async with self.session.get(
                    url,
                    params=data,
                    headers=self.get_headers(),
                    proxy=self.proxy if self.proxy else None
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        status = response_data.get("data", {}).get("is_able_to_faucet")
                        return status
                    return None

            except Exception as e:
                return None
                
        async def request_faucet(self):
            """Запрос фаусета"""
            try:
                # Проверяем статус фаусета
                status = await self.status_faucet()
                if status is not True:
                    return "already_claimed"  # Специальный статус для уже запрошенного
                
                # Запрашиваем фаусет
                url = f"https://api.pharosnetwork.xyz/faucet/daily?address={self.wallet_address}"
                data = {'address': self.wallet_address}
                
                async with self.session.post(
                    url, 
                    params=data, 
                    headers=self.get_headers(),
                    proxy=self.proxy if self.proxy else None
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        status = result.get("code")
                        if status == 0:
                            return True
                        else:
                            return False
                    else:
                        return False
                            
            except Exception as e:
                return False

    # Основная логика с обновлением статусов
    try:
        # Проверяем есть ли уже успешно подключенный Twitter
        if twitter_connected and wallet_data.get('successful_twitter_token') and wallet_data.get('successful_ct0_token'):
            # Twitter уже подключен, все статусы уже установлены при печати
            
            # Используем сохраненные токены из JSON файла
            saved_twitter_token = wallet_data.get('successful_twitter_token')
            saved_ct0_token = wallet_data.get('successful_ct0_token')
            
            client = PharosHubClient(wallet_address, private_key, saved_twitter_token, saved_ct0_token, proxy)
            await client.create_session()
            
            try:
                # 1. Авторизация в Pharos (НЕ обновляем статус - уже установлен)
                if await client.pharoshub_login():
                    # 2. Запрос фаусета напрямую
                    faucet_result = await client.request_faucet()
                    
                    # Обновляем статусы только если результат отличается от предполагаемого
                    if faucet_result == "already_claimed":
                        # Статусы уже правильные (already_requested)
                        pass
                    elif faucet_result:
                        # Неожиданный успех - обновляем статусы
                        status_display.update_status('faucet', 'success')
                        status_display.update_status('account', 'success')
                        
                        # Обновляем данные с новым timestamp
                        wallet_data.update({
                            "last_faucet_claim": datetime.now().isoformat(),
                            "success": True
                        })
                        save_wallet_data(wallet_address, wallet_data)
                    else:
                        # Ошибка - обновляем статусы
                        status_display.update_status('faucet', 'error')
                        status_display.update_status('account', 'error')
                        print()
                        return False
                    
                    print()
                    return True
                else:
                    # Ошибка login - обновляем статус
                    status_display.update_status('pharos_login', 'error')
                    print()
                    return False
                    
            finally:
                await client.close_session()
        else:
            # Если Twitter не подключен, загружаем токены из CSV и выполняем полный процесс
            print()
            
            # Загружаем Twitter токены из CSV только если Twitter не подключен
            twitter_tokens = load_twitter_tokens()
            if not twitter_tokens:
                status_display.update_status('twitter', 'error', '- no tokens available')
                status_display.update_status('account', 'error')
                print()
                return False
            
            # Перебираем Twitter токены для подключения
            for token_index, (twitter_token, ct0_token) in enumerate(twitter_tokens, 1):
                # Создаем клиент
                client = PharosHubClient(wallet_address, private_key, twitter_token, ct0_token, proxy)
                await client.create_session()
                
                try:
                    # 1. Авторизация в Pharos
                    if await client.pharoshub_login():
                        status_display.update_status('pharos_login', 'success', f'for {wallet_address}')
                        
                        # 2. Подключение Twitter
                        if await client.connect_twitter():
                            status_display.update_status('twitter', 'success', f'(token {token_index}/{len(twitter_tokens)})')
                            
                            # 3. Запрос фаусета
                            faucet_result = await client.request_faucet()
                            if faucet_result == "already_claimed":
                                status_display.update_status('faucet', 'already_requested')
                                status_display.update_status('account', 'already_requested')
                                
                                # Сохраняем результат с уже запрошенным статусом
                                result_data = {
                                    "wallet_address": wallet_address,
                                    "proxy": proxy,
                                    "successful_twitter_token": twitter_token,
                                    "successful_ct0_token": ct0_token,
                                    "twitter_connected": True,
                                    "token_index": token_index,
                                    "total_tokens_tried": token_index,
                                    "first_connection_timestamp": datetime.now().isoformat(),
                                    "last_faucet_claim": datetime.now().isoformat(),
                                    "success": True,
                                    "faucet_already_claimed": True
                                }
                                
                                save_wallet_data(wallet_address, result_data)
                                print()
                                return True
                            elif faucet_result:
                                status_display.update_status('faucet', 'success')
                                status_display.update_status('account', 'success')

                                # Сохраняем результат успешного выполнения
                                result_data = {
                                    "wallet_address": wallet_address,
                                    "proxy": proxy,
                                    "successful_twitter_token": twitter_token,
                                    "successful_ct0_token": ct0_token,
                                    "twitter_connected": True,
                                    "token_index": token_index,
                                    "total_tokens_tried": token_index,
                                    "first_connection_timestamp": datetime.now().isoformat(),
                                    "last_faucet_claim": datetime.now().isoformat(),
                                    "success": True
                                }
                                
                                save_wallet_data(wallet_address, result_data)
                                print()
                                return True
                            else:
                                status_display.update_status('faucet', 'error')
                                status_display.update_status('account', 'error')
                                print()
                                return False
                        else:
                            # Twitter connection failed, try next token
                            await client.close_session()
                            continue
                    else:
                        status_display.update_status('pharos_login', 'error')
                        print()
                        return False

                finally:
                    await client.close_session()
                
                # Пауза между токенами
                if token_index < len(twitter_tokens):
                    await asyncio.sleep(1)

            # Если все токены не сработали
            status_display.update_status('twitter', 'error', f'- all {len(twitter_tokens)} tokens failed')
            status_display.update_status('account', 'error')
            print()
            
            error_data = {
                "wallet_address": wallet_address,
                "proxy": proxy,
                "total_tokens_tried": len(twitter_tokens),
                "timestamp": datetime.now().isoformat(),
                "success": False,
                "error": f"All {len(twitter_tokens)} Twitter token pairs failed"
            }
            
            save_wallet_data(wallet_address, error_data)
            return False

    except Exception as e:
        status_display.update_status('account', 'error', f'- {str(e)[:30]}...')
        print()
        
        error_data = {
            "wallet_address": wallet_address or "unknown",
            "proxy": proxy,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "success": False
        }
        
        if wallet_address:
            save_wallet_data(wallet_address, error_data)
            
        return False

# Пример использования:
if __name__ == "__main__":
    asyncio.run(pharos_faucet_complete(
        proxy="",
        private_key="",
    ))