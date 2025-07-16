import json
import asyncio
import aiohttp
import csv
from typing import Optional, List, Tuple
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from loguru import logger
from eth_account import Account
from pathlib import Path

def load_twitter_tokens() -> List[Tuple[str, str]]:
    """Загружает Twitter токены и ct0 из файла data/twitter_tokens.csv"""
    try:
        project_root = Path(__file__).parent.parent.parent
        tokens_file = project_root / 'data' / 'twitter_tokens.csv'
        
        logger.info(f"🔍 Looking for CSV file at: {tokens_file}")
        
        if not tokens_file.exists():
            logger.error(f"❌ Файл {tokens_file} не найден!")
            return []
        
        tokens = []
        with open(tokens_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                logger.error("❌ CSV файл пустой!")
                return []
            
            # Проверяем содержимое файла
            logger.info(f"📄 First 200 chars of CSV: {content[:200]}")
            
            # Перематываем файл
            f.seek(0)
            reader = csv.DictReader(f)
            
            for row_num, row in enumerate(reader, 1):
                auth_token = row.get('auth_token', '').strip()
                ct0 = row.get('ct0', '').strip()
                
                if auth_token and ct0:
                    tokens.append((auth_token, ct0))
                    logger.debug(f"✅ Loaded token pair {row_num}: {auth_token[:5]}.../{ct0[:5]}...")
                else:
                    logger.warning(f"⚠️ Row {row_num} missing data: auth_token={bool(auth_token)}, ct0={bool(ct0)}")
        
        logger.info(f"📱 Successfully loaded {len(tokens)} token pairs from CSV")
        return tokens
        
    except FileNotFoundError:
        logger.error("❌ Файл data/twitter_tokens.csv не найден!")
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
            logger.info(f"📝 Created example file at {example_file}")
        except Exception as e:
            logger.error(f"Failed to create example file: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Ошибка при чтении CSV файла: {e}")
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
                    logger.warning(f"JSON file for {wallet_address} is empty")
                    return {}
                return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for {wallet_address}: {e}")
        # Удаляем поврежденный файл
        try:
            json_file.unlink()
            logger.info(f"Removed corrupted JSON file for {wallet_address}")
        except:
            pass
    except Exception as e:
        logger.error(f"Error loading wallet data: {e}")
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
        logger.error(f"Error saving wallet data: {e}")

async def pharos_faucet_complete(proxy: str, private_key: str, wallet_address: Optional[str] = None):
    """
    Функция для Pharos с CSV токенами:
    1. Авторизация кошелька через api.pharosnetwork.xyz
    2. Подключение Twitter через api.pharosnetwork.xyz  
    3. Запрос крана
    """
    
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
                            logger.warning(f'Twitter token invalid (403): {self.twitter_token[:5]}***')
                            return None
                        elif auth_response.status != 200:
                            logger.error(f'Auth response error: {auth_response.status}')
                            return None
                            
                        try:
                            auth_data = await auth_response.json()
                            auth_code = auth_data.get('auth_code')
                            if not auth_code:
                                logger.error('No auth_code in response')
                                return None
                        except Exception as e:
                            logger.error(f'Failed to parse auth response: {e}')
                            return None
                            
                    # Второй запрос - подтверждение  
                    async with session.post(
                        auth_url,
                        params={"approval": "true", "code": auth_code},
                        proxy=self.proxy if self.proxy else None
                    ) as approve_response:
                        if approve_response.status != 200:
                            logger.error(f'Approval response error: {approve_response.status}')
                            return None
                            
                        try:
                            approve_data = await approve_response.json()
                            redirect_uri = approve_data.get('redirect_uri')
                            if not redirect_uri:
                                logger.error('No redirect_uri in response')
                                return None
                            
                            final_code = self.extract_code_from_redirect(redirect_uri)
                            if final_code:
                                logger.success(f'✅ Successfully got Twitter auth code')
                                return final_code
                        except Exception as e:
                            logger.error(f'Failed to parse approval response: {e}')
                            return None

            except aiohttp.ClientError as error:
                logger.error(f'Twitter HTTP error: {error}')
            except Exception as error:
                logger.error(f'Twitter connection error: {str(error)}')
                
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
                'authority': 'api.pharosnetwork.xyz',  # Исправлено
                'accept': 'application/json',
                'content-type': 'application/json',
                'origin': 'https://testnet.pharosnetwork.xyz',  # Исправлено
                'referer': 'https://testnet.pharosnetwork.xyz/',  # Исправлено
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
                logger.error(f"Signature error: {e}")
                return "0x" + "a" * 130  # Fallback
            
        async def pharoshub_login(self):
            """Авторизация через api.pharosnetwork.xyz"""
            try:
                signature = await self.get_signature('pharos')
                
                # Используем правильный URL из оригинального кода
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
                            logger.success(f"✅ Pharos login successful for {self.wallet_address}")
                            return True
                            
                logger.error(f"Pharos login failed for {self.wallet_address}, status: {response.status}")
                return False
                
            except Exception as e:
                logger.error(f"Pharos login error: {e}")
                return False
                
        async def get_auth_link(self):
            """Получает параметры авторизации - точная копия из рабочего кода"""
            for attempt in range(3):  # config.ATTEMPTS_NUMBER_RESTORE
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
                    logger.error(f'Request failed: {str(e)}')
                    if attempt < 2:
                        await asyncio.sleep(1)  # config.DELAY_AFTER_ERROR
            return None, None

        async def connect_twitter(self):
            """Подключает Twitter"""
            logger.info(f'Trying to connect Twitter account...')
            
            code_challenge, state = await self.get_auth_link()
            if not (code_challenge and state):
                logger.error("Failed to get auth parameters from Pharos")
                return False

            code = await self.twitter_worker.connect_twitter(code_challenge, state)
            if not code:
                logger.warning("Failed to get Twitter authorization code - token may be invalid")
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
                            logger.success(f"✅ Successfully Bind Twitter")
                            return True
                        else:
                            msg = result.get("msg", "Unknown error")
                            logger.warning(f"Twitter binding failed: {msg}")
                            return False
                    else:
                        response_text = await response.text()
                        logger.error(f"Twitter binding request failed: {response.status}, response: {response_text[:200]}")
                        return False
                        
            except Exception as e:
                logger.error(f"twitter connect error: {e}")
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
                logger.error(f"Status faucet error: {e}")
                return None
                
        async def request_faucet(self):
            """Запрос фаусета"""
            try:
                logger.info(f'Starting faucet request...')

                # Проверяем статус фаусета
                status = await self.status_faucet()
                if status is not True:
                    logger.warning(f"Faucet already claimed today for {self.wallet_address}")
                    return True
                
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
                            logger.success(f"✅ Faucet successfully claimed for {self.wallet_address}")
                            return True
                        else:
                            msg = result.get("msg", "Unknown error")
                            logger.warning(f"Faucet request failed: {msg}")
                            return False
                    else:
                        response_text = await response.text()
                        logger.warning(f'Faucet request failed: {response.status} | {response_text[:200]}')
                            
                return False
                
            except Exception as e:
                logger.error(f"Faucet request error: {e}")
                return False

    # Основная логика
    try:
        # Извлекаем адрес кошелька из приватного ключа
        if not wallet_address:
            account = Account.from_key(private_key)
            wallet_address = account.address
            
        logger.info(f"🚀 Starting Pharos process for {wallet_address}")
        
        # Загружаем данные кошелька
        wallet_data = load_wallet_data(wallet_address)
        twitter_connected = wallet_data.get('twitter_connected', False)
        
        # Проверяем есть ли уже успешно подключенный Twitter
        if twitter_connected and wallet_data.get('successful_twitter_token') and wallet_data.get('successful_ct0_token'):
            logger.info(f"💾 Found successfully connected Twitter account for {wallet_address}")
            logger.info(f"🔄 Skipping Twitter connection, going directly to faucet claim")
            
            # Используем сохраненные токены из JSON файла
            saved_twitter_token = wallet_data.get('successful_twitter_token')
            saved_ct0_token = wallet_data.get('successful_ct0_token')
            
            client = PharosHubClient(wallet_address, private_key, saved_twitter_token, saved_ct0_token, proxy)
            await client.create_session()
            
            try:
                success_steps = ["twitter_already_connected"]
                
                # 1. Авторизация в Pharos
                if await client.pharoshub_login():
                    success_steps.append("pharos_login")
                    
                    # 2. Запрос фаусета напрямую (пропускаем подключение Twitter)
                    if await client.request_faucet():
                        success_steps.append("faucet_claimed")
                        
                        # Обновляем данные с новым timestamp
                        wallet_data.update({
                            "last_faucet_claim": datetime.now().isoformat(),
                            "completed_steps": success_steps,
                            "success": True
                        })
                        
                        save_wallet_data(wallet_address, wallet_data)
                        logger.success(f"🎉 Faucet claimed successfully using existing Twitter connection!")
                        return True
                    else:
                        logger.warning(f"⚠️ Faucet request failed even with existing Twitter connection")
                        return False
                else:
                    logger.error(f"❌ Pharos login failed")
                    return False
                    
            finally:
                await client.close_session()
        
        # Если Twitter не подключен, загружаем токены из CSV и выполняем полный процесс
        logger.info(f"🔗 No existing Twitter connection found, starting full process")
        
        # Загружаем Twitter токены из CSV
        twitter_tokens = load_twitter_tokens()
        if not twitter_tokens:
            logger.error("❌ No Twitter tokens available")
            return False
            
        logger.info(f"📱 Loaded {len(twitter_tokens)} Twitter token pairs")
        
        # Перебираем Twitter токены для подключения
        for token_index, (twitter_token, ct0_token) in enumerate(twitter_tokens, 1):
            logger.info(f"🔄 Trying Twitter token {token_index}/{len(twitter_tokens)}: {twitter_token[:10]}... | ct0: {ct0_token[:10]}...")
            
            # Создаем клиент
            client = PharosHubClient(wallet_address, private_key, twitter_token, ct0_token, proxy)
            await client.create_session()
            
            try:
                success_steps = []
                
                # 1. Авторизация в Pharos
                if await client.pharoshub_login():
                    success_steps.append("pharos_login")
                    
                    # 2. Подключение Twitter
                    if await client.connect_twitter():
                        success_steps.append("twitter_connected")
                        twitter_connected = True
                        logger.success(f"✅ Twitter connected with token {token_index}")
                        
                        # 3. Запрос фаусета
                        if await client.request_faucet():
                            success_steps.append("faucet_claimed")

                            # Сохраняем результат успешного выполнения
                            result_data = {
                                "wallet_address": wallet_address,
                                "proxy": proxy,
                                "successful_twitter_token": twitter_token,
                                "successful_ct0_token": ct0_token,
                                "twitter_connected": True,
                                "token_index": token_index,
                                "total_tokens_tried": token_index,
                                "completed_steps": success_steps,
                                "first_connection_timestamp": datetime.now().isoformat(),
                                "last_faucet_claim": datetime.now().isoformat(),
                                "success": True
                            }
                            
                            save_wallet_data(wallet_address, result_data)
                            logger.success(f"🎉 Process completed successfully! Used token {token_index}/{len(twitter_tokens)}")
                            return True
                        else:
                            logger.warning(f"⚠️ Faucet request failed with token {token_index}")
                    else:
                        logger.warning(f"⚠️ Twitter connection failed with token {token_index} - trying next token")
                        await client.close_session()
                        continue
                else:
                    logger.warning(f"⚠️ Pharos login failed with token {token_index}")

            finally:
                await client.close_session()
            
            # Пауза между токенами
            if token_index < len(twitter_tokens):
                logger.info(f"⏳ Waiting 1 second before trying next token...")
                await asyncio.sleep(1)

        # Если все токены не сработали
        logger.error(f"❌ All {len(twitter_tokens)} Twitter token pairs failed")
        
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
        logger.error(f"❌ Main process error: {e}")
        
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