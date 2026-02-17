import uuid
import random
import asyncio
import sys
import re
import json
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
neura_module_path = Path(__file__).parent
sys.path.append(str(project_root))

from modules.simple_logger import logger
from modules.proxy_manager import parse_proxy, get_proxy_dict
from curl_cffi.requests import AsyncSession, BrowserType
from eth_account import Account as EthAccount
from eth_account.messages import encode_defunct
from web3 import Web3
from web3.contract import AsyncContract

from config.modules.cfg_base import (
    RETRY_COUNT, SLEEP_BETWEEN_ACTIONS,
    astrum_CAPTCHA_API_KEY, CAPSOLVER_API_KEY, CAPTCHA_SERVICE, MAIN_PROXY
)
from config.modules.cfg_neura import (
    NEURA_MAX_RETRIES_PER_TASK, NEURA_FAUCET_TOKEN,
    NEURA_SWAP_COUNT, NEURA_SWAP_PERCENTAGE, NEURA_SWAP_SLIPPAGE,
    NEURA_SWAP_PAUSE_BETWEEN_SWAPS,
    NEURA_ROUTER_ADDRESS, NEURA_QUOTER_ADDRESS, NEURA_TOKENS,
    NEURA_SWAP_PAIRS, NEURA_RANDOM_SWAP_PAIR
)
from config.networks import NETWORKS
from modules.neura.types import UserData

try:
    from modules.statistics.astrum_captcha_solver import AstrumSolver
except ImportError:
    AstrumSolver = None

try:
    from modules.statistics.capsolver_solver import CapsolverSolver
except ImportError:
    CapsolverSolver = None


def get_captcha_solver(proxy_url=None):
    """
    Получить solver капчи с поддержкой прокси.
    Приоритет прокси: proxy_url (переданный) -> MAIN_PROXY (из конфига) -> без прокси
    """
    # Определяем прокси для отправки запросов к сервису капчи
    captcha_proxy = proxy_url or (MAIN_PROXY if MAIN_PROXY else None)
    
    if CAPTCHA_SERVICE == 'capsolver' and CAPSOLVER_API_KEY and CapsolverSolver:
        return CapsolverSolver(api_key=CAPSOLVER_API_KEY, proxy=captcha_proxy)
    elif astrum_CAPTCHA_API_KEY and AstrumSolver:
        return AstrumSolver(api_key=astrum_CAPTCHA_API_KEY, proxy=captcha_proxy)
    return None


class NeuraClient:
    
    def __init__(self, private_key: str, proxy: Optional[str] = None):
        self.private_key = private_key
        self.proxy = proxy
        self.jwt_token = None
        self.user_data: Optional[UserData] = None
        
        self.account = EthAccount.from_key(private_key)
        self.wallet_address = self.account.address
        
        proxy_url = parse_proxy(proxy) if proxy else None
        proxy_dict = get_proxy_dict(proxy) if proxy else None
        
        self.session = AsyncSession(
            proxies=proxy_dict,  # type: ignore
            impersonate="chrome131"  # type: ignore
        )
        
        self._captcha_solver = None
        self._last_error = ""  # Последняя ошибка для вывода в лог
        try:
            self._captcha_solver = get_captcha_solver(proxy_url)
        except Exception as e:
            logger.warning(f"[{self.wallet_address}] Failed to init captcha solver: {e}")
        
        self.auth_headers = {
            'accept': 'application/json',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/json',
            'origin': 'https://neuraverse.neuraprotocol.io',
            'priority': 'u=1, i',
            'privy-app-id': 'cmbpempz2011ll10l7iucga14',
            'privy-ca-id': str(uuid.uuid4()),
            'privy-client': 'react-auth:3.12.0',
            'referer': 'https://neuraverse.neuraprotocol.io/',
            'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        }
        
        self.headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'origin': 'https://neuraverse.neuraprotocol.io',
            'priority': 'u=1, i',
            'referer': 'https://neuraverse.neuraprotocol.io/',
            'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        }
    
    async def close(self):
        if self.session:
            await self.session.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    def _get_signature(self, message: str) -> str:
        signed_message = EthAccount.sign_message(
            encode_defunct(text=message), 
            private_key=self.private_key
        )
        sig_hex = signed_message.signature.hex()
        return sig_hex if sig_hex.startswith('0x') else '0x' + sig_hex
    
    async def _make_request(
        self, 
        method: str, 
        url: str, 
        headers: Optional[Dict[str, Any]] = None, 
        json: Optional[Dict[str, Any]] = None,
        data: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        try:
            response = await self.session.request(
                method=method,  # type: ignore
                url=url,
                headers=headers or self.headers,
                json=json,
                data=data,
                params=params,
                verify=False
            )
            
            status = response.status_code
            
            if status in [200, 201]:
                try:
                    return response.json(), status
                except:
                    return response.text, status
            else:
                return response.text, status
                
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"[{self.wallet_address}] Request error: {e}")
            return None, 0
    
    async def _get_nonce(self) -> Optional[str]:
        if not self._captcha_solver:
            logger.error(f"[{self.wallet_address}] Captcha solver not initialized!")
            return None
            
        for attempt in range(RETRY_COUNT):
            try:
                turnstile_token = self._captcha_solver.solve_turnstile(
                    sitekey='0x4AAAAAAAM8ceq5KhP1uJBt',
                    pageurl='https://neuraverse.neuraprotocol.io/',
                    action='cmbpempz2011ll10l7iucga14',
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
                )
                
                if not turnstile_token:
                    self._last_error = "Captcha solver returned empty token"
                    logger.warning(f"[{self.wallet_address}] Failed to solve captcha: {self._last_error}, attempt {attempt + 1}/{RETRY_COUNT}")
                    await asyncio.sleep(random.uniform(3, 7))
                    continue
                
                json_data = {
                    'address': self.wallet_address,
                    'token': turnstile_token
                }
                
                response_json, status = await self._make_request(
                    method="POST",
                    url='https://privy.neuraverse.neuraprotocol.io/api/v1/siwe/init',
                    json=json_data,
                    headers=self.auth_headers
                )
                
                if status == 200 and response_json:
                    return response_json.get('nonce')
                
                if status == 429:
                    wait_time = random.uniform(10, 20)
                    self._last_error = f"Rate limited (429)"
                    logger.warning(f"[{self.wallet_address}] Rate limited (429), waiting {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)
                    continue
                    
                self._last_error = f"nonce request failed, status={status}, response={response_json}"
                logger.warning(f"[{self.wallet_address}] Failed to get nonce: {self._last_error}")
                
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"[{self.wallet_address}] Error getting nonce: {e}")
            
            await asyncio.sleep(random.uniform(3, 7))
        
        logger.warning(f"[{self.wallet_address}] Failed to get nonce after all attempts: {self._last_error}")
        return None
    
    async def _send_auth_request(self, message: str, signature: str) -> bool:
        json_data = {
            'message': message,
            'signature': signature,
            'chainId': 'eip155:267',
            'walletClientType': 'rabby_wallet',
            'connectorType': 'injected',
            'mode': 'login-or-sign-up',
        }
        
        response_json, status = await self._make_request(
            method="POST",
            url='https://privy.neuraverse.neuraprotocol.io/api/v1/siwe/authenticate',
            headers=self.auth_headers,
            json=json_data
        )
        
        if status == 200 and response_json:
            token = response_json.get('identity_token')
            if token:
                self.jwt_token = token
                self.headers['authorization'] = f'Bearer {token}'
                return True
            self._last_error = f"No identity_token in response: {response_json}"
        else:
            self._last_error = f"auth request failed, status={status}, response={response_json}"
        
        return False
    
    async def authorize(self) -> bool:
        for attempt in range(RETRY_COUNT):
            nonce = await self._get_nonce()
            if not nonce:
                logger.warning(f"[{self.wallet_address}] Failed to get nonce: {self._last_error}, attempt {attempt + 1}/{RETRY_COUNT}")
                await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                continue
            
            iso_time = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            msg = (
                f'neuraverse.neuraprotocol.io wants you to sign in with your Ethereum account:\n'
                f'{self.wallet_address}\n\n'
                f'By signing, you are proving you own this wallet and logging in. '
                f'This does not initiate a transaction or cost any fees.\n\n'
                f'URI: https://neuraverse.neuraprotocol.io\n'
                f'Version: 1\n'
                f'Chain ID: 267\n'
                f'Nonce: {nonce}\n'
                f'Issued At: {iso_time}\n'
                f'Resources:\n- https://privy.io'
            )
            
            signature = self._get_signature(msg)
            
            if await self._send_auth_request(msg, signature):
                logger.success(f"[{self.wallet_address}] Successfully authorized into Neuraverse!")
                return True
            
            logger.warning(f"[{self.wallet_address}] Authorization failed: {self._last_error}, attempt {attempt + 1}/{RETRY_COUNT}")
            await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
        
        logger.error(f"[{self.wallet_address}] Failed to authorize after all attempts: {self._last_error}")
        return False
    
    async def _process_action(self, action_type: str) -> bool:
        json_data = {'type': action_type}
        response_json, status = await self._make_request(
            method="POST",
            url='https://neuraverse-testnet.infra.neuraprotocol.io/api/events',
            json=json_data
        )
        return status == 200
    
    async def get_user(self) -> Optional[UserData]:
        response_json, status = await self._make_request(
            method="GET",
            url='https://neuraverse-testnet.infra.neuraprotocol.io/api/account'
        )
        
        if status == 200 and response_json:
            self.user_data = UserData.from_dict(response_json)
            return self.user_data
        
        self._last_error = f"status={status}, response={response_json}"
        return None
    
    async def _collect_pulse(self, pulse_id: str) -> bool:
        json_data = {
            'type': 'pulse:collectPulse',
            'payload': {'id': pulse_id}
        }
        
        response_json, status = await self._make_request(
            method="POST",
            url='https://neuraverse-testnet.infra.neuraprotocol.io/api/events',
            json=json_data
        )
        
        if status == 200:
            logger.success(f"[{self.wallet_address}] Pulse {pulse_id} has been successfully collected!")
            return True
        
        self._last_error = f"collect_pulse failed, status={status}, response={response_json}"
        return False
    
    async def collect_pulses(self) -> bool:
        max_cycles = NEURA_MAX_RETRIES_PER_TASK
        consecutive_failures = 0
        
        for cycle in range(max_cycles):
            await self._process_action(action_type='game:visitFountain')
            
            user = await self.get_user()
            if not user:
                consecutive_failures += 1
                wait_time = min(5 + consecutive_failures * 3, 30)
                logger.warning(f"[{self.wallet_address}] Failed to get user data: {self._last_error}, waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                continue
            
            consecutive_failures = 0 
            
            uncollected_pulses = [
                pulse for pulse in self.user_data.pulses.data
                if not pulse.is_collected
            ]
            
            if not uncollected_pulses:
                logger.success(f"[{self.wallet_address}] All pulses have been already collected!")
                return True
            
            logger.info(f"[{self.wallet_address}] Found {len(uncollected_pulses)} uncollected pulses. Collecting...")
            
            for pulse_obj in uncollected_pulses:
                for attempt in range(NEURA_MAX_RETRIES_PER_TASK):
                    fresh_user = await self.get_user()
                    if fresh_user:
                        fresh_pulse = next(
                            (p for p in self.user_data.pulses.data if p.id == pulse_obj.id), 
                            None
                        )
                        if fresh_pulse and fresh_pulse.is_collected:
                            logger.info(f"[{self.wallet_address}] Pulse {pulse_obj.id} already collected, skipping...")
                            break
                    
                    if await self._collect_pulse(pulse_obj.id):
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                        break
                    else:
                        logger.warning(f"[{self.wallet_address}] Failed to collect pulse {pulse_obj.id}: {self._last_error}, attempt {attempt + 1}/{NEURA_MAX_RETRIES_PER_TASK}")
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            
            await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            user_after = await self.get_user()
            
            if user_after:
                remaining = [p for p in self.user_data.pulses.data if not p.is_collected]
                if not remaining:
                    logger.success(f"[{self.wallet_address}] Verified: All pulses successfully collected!")
                    return True
                else:
                    logger.warning(f"[{self.wallet_address}] Still have {len(remaining)} uncollected pulses, cycle {cycle + 1}/{max_cycles}")
        
        logger.error(f"[{self.wallet_address}] Failed to collect all pulses after max attempts: {self._last_error}")
        return False
    
    async def _get_tasks(self) -> Optional[list]:
        response_json, status = await self._make_request(
            method="GET",
            url='https://neuraverse-testnet.infra.neuraprotocol.io/api/tasks'
        )
        
        if status == 200 and response_json:
            return response_json.get('tasks', [])
        
        self._last_error = f"get_tasks status={status}, response={response_json}"
        return None
    
    async def _claim_task(self, task_id: str) -> bool:
        response_json, status = await self._make_request(
            method="POST",
            url=f'https://neuraverse-testnet.infra.neuraprotocol.io/api/tasks/{task_id}/claim'
        )
        
        if status == 200 and response_json:
            points = response_json.get('points', 0)
            name = response_json.get('name', 'Unknown')
            logger.success(f"[{self.wallet_address}] Successfully claimed {name} task and earned {points} points!")
            return True
        
        self._last_error = f"claim_task failed, status={status}, response={response_json}"
        return False
    
    async def claim_tasks(self) -> bool:
        max_cycles = NEURA_MAX_RETRIES_PER_TASK
        consecutive_failures = 0
        
        for cycle in range(max_cycles):
            await self._process_action(action_type='game:visitFountain')
            
            all_tasks = await self._get_tasks()
            if not all_tasks:
                consecutive_failures += 1
                wait_time = min(5 + consecutive_failures * 3, 30)
                logger.warning(f"[{self.wallet_address}] Failed to get tasks: {self._last_error}, waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                continue
            
            consecutive_failures = 0 
            
            claimable_tasks = [task for task in all_tasks if task.get('status') == 'claimable']
            
            if not claimable_tasks:
                logger.success(f"[{self.wallet_address}] All tasks have been claimed!")
                return True
            
            logger.info(f"[{self.wallet_address}] Found {len(claimable_tasks)} claimable tasks. Claiming...")
            
            for task in claimable_tasks:
                task_id = task.get('id')
                task_name = task.get('name', 'Unknown')
                
                for attempt in range(NEURA_MAX_RETRIES_PER_TASK):
                    fresh_tasks = await self._get_tasks()
                    if fresh_tasks:
                        fresh_task = next((t for t in fresh_tasks if t.get('id') == task_id), None)
                        if fresh_task and fresh_task.get('status') != 'claimable':
                            logger.info(f"[{self.wallet_address}] Task {task_name} already claimed, skipping...")
                            break
                    
                    if await self._claim_task(task_id):
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                        break
                    else:
                        logger.warning(f"[{self.wallet_address}] Failed to claim task {task_name}: {self._last_error}, attempt {attempt + 1}/{NEURA_MAX_RETRIES_PER_TASK}")
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            
            await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            all_tasks_after = await self._get_tasks()
            
            if all_tasks_after:
                remaining = [t for t in all_tasks_after if t.get('status') == 'claimable']
                if not remaining:
                    logger.success(f"[{self.wallet_address}] Verified: All tasks successfully claimed!")
                    return True
                else:
                    logger.warning(f"[{self.wallet_address}] Still have {len(remaining)} claimable tasks, cycle {cycle + 1}/{max_cycles}")
        
        logger.error(f"[{self.wallet_address}] Failed to claim all tasks after max attempts: {self._last_error}")
        return False

    # ==================== FAUCET METHODS ====================
    
    async def _extract_request_uuid(self) -> Optional[str]:
        """Извлечь UUID из HTML страницы faucet"""
        uuid4_regex = re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
            re.IGNORECASE,
        )
        
        try:
            response = await self.session.get(
                'https://neuraverse.neuraprotocol.io/?section=faucet',
                headers=self.headers,
                verify=False
            )
            html = response.text
            
            match = uuid4_regex.search(html)
            if not match:
                logger.warning(f"[{self.wallet_address}] Failed to extract request UUID from faucet page")
                return None
            
            return match.group(0)
        except Exception as e:
            logger.error(f"[{self.wallet_address}] Error extracting faucet UUID: {e}")
            return None
    
    async def _send_faucet_request(self) -> bool:
        """Отправить запрос на получение токенов из faucet"""
        if not self._captcha_solver:
            logger.error(f"[{self.wallet_address}] Captcha solver not initialized!")
            return False
        
        logger.info(f"[{self.wallet_address}] Requesting tokens from faucet...")
        logger.info(f"[{self.wallet_address}] Solving Turnstile captcha for faucet...")
        
        # Решаем Turnstile капчу (без action, как в рабочем примере)
        try:
            turnstile_token = self._captcha_solver.solve_turnstile(
                sitekey='0x4AAAAAACFWAVaa_Rh1pBFY',
                pageurl='https://neuraverse.neuraprotocol.io/?section=faucet'
            )
        except Exception as e:
            import traceback
            self._last_error = f"Captcha solver error: {e}"
            logger.error(f"[{self.wallet_address}] Captcha solver error: {e}")
            logger.error(f"[{self.wallet_address}] Full captcha error:\n{traceback.format_exc()}")
            return False
        
        if not turnstile_token:
            self._last_error = "Faucet captcha solver returned empty token"
            logger.warning(f"[{self.wallet_address}] Failed to solve faucet captcha - no token returned")
            return False
        
        logger.info(f"[{self.wallet_address}] Turnstile solved, extracting UUID...")
        
        # Получаем UUID
        uuid_request_token = await self._extract_request_uuid()
        if not uuid_request_token:
            self._last_error = "Failed to extract UUID from faucet page"
            logger.warning(f"[{self.wallet_address}] Failed to extract UUID from faucet page")
            return False
        
        logger.info(f"[{self.wallet_address}] UUID extracted: {uuid_request_token[:8]}...")
        
        # Отправляем запрос
        headers = self.headers.copy()
        headers['accept'] = 'text/x-component'
        headers['next-action'] = NEURA_FAUCET_TOKEN
        
        params = {'section': 'faucet'}
        data = f'["{self.wallet_address}",267,"{self.jwt_token}",true,"{turnstile_token}","{uuid_request_token}"]'
        
        try:
            response = await self.session.request(
                method="POST",
                url='https://neuraverse.neuraprotocol.io/',
                headers=headers,
                data=data,
                params=params,
                verify=False
            )
            
            logger.info(f"[{self.wallet_address}] Faucet response status: {response.status_code}")
            
            if response.status_code == 200:
                response_text = response.text.strip()
                lines = response_text.split('\n')
                
                for line in lines:
                    if line.startswith("1:"):
                        try:
                            response_json = json.loads(line[2:])
                            status = response_json.get('status', '')
                            
                            if status not in ['error', 'failure']:
                                logger.success(f"[{self.wallet_address}] Successfully requested tokens from faucet!")
                                return True
                            else:
                                error_msg = response_json.get('message', 'Unknown error')
                                self._last_error = f"Faucet status={status}, message={error_msg}"
                                logger.error(f"[{self.wallet_address}] Faucet failed | Status: {status} | Message: {error_msg}")
                                logger.error(f"[{self.wallet_address}] Full response: {response_json}")
                                return False
                        except json.JSONDecodeError as e:
                            logger.warning(f"[{self.wallet_address}] Failed to parse response line: {line[:100]}")
                            continue
                
                # Если не нашли формат 1:, логируем полный ответ
                self._last_error = f"Unexpected response format: {response_text[:200]}"
                logger.warning(f"[{self.wallet_address}] Unexpected response format. Full response: {response_text[:500]}")
                return False
            else:
                self._last_error = f"Faucet HTTP error: {response.status_code}, response={response.text[:200]}"
                logger.error(f"[{self.wallet_address}] Faucet HTTP error: {response.status_code}")
                logger.error(f"[{self.wallet_address}] Response: {response.text[:500]}")
                return False
                
        except Exception as e:
            import traceback
            self._last_error = str(e)
            logger.error(f"[{self.wallet_address}] Faucet request error: {e}")
            logger.error(f"[{self.wallet_address}] Full faucet error:\n{traceback.format_exc()}")
            return False
    
    async def request_tokens(self) -> bool:
        """Запросить токены из faucet с retry логикой"""
        max_attempts = NEURA_MAX_RETRIES_PER_TASK
        
        # Показываем текущий баланс перед запросом faucet
        try:
            web3 = self._get_web3()
            balance = web3.eth.get_balance(self.wallet_address)
            balance_ankr = balance / 10**18
            symbol = NETWORKS.get('🚀 Neura Testnet', {}).get('symbol', 'ANKR')
            logger.info(f"[{self.wallet_address}] Текущий баланс: {balance_ankr:.6f} {symbol}")
        except Exception as e:
            logger.warning(f"[{self.wallet_address}] Не удалось получить баланс: {e}")
        
        for attempt in range(max_attempts):
            try:
                # Регистрируем посещение faucet
                await self._process_action(action_type='faucet:visit')
                await self._process_action(action_type='game:visitFountain')
                
                # Отправляем запрос на faucet
                if await self._send_faucet_request():
                    # Регистрируем успешный claim
                    await self._process_action(action_type='faucet:claimTokens')
                    
                    # Показываем новый баланс после получения токенов
                    try:
                        await asyncio.sleep(2)  # Ждем обновления баланса
                        new_balance = web3.eth.get_balance(self.wallet_address)
                        new_balance_ankr = new_balance / 10**18
                        logger.info(f"[{self.wallet_address}] Новый баланс: {new_balance_ankr:.6f} {symbol}")
                    except Exception:
                        pass
                    
                    return True
                
                logger.warning(f"[{self.wallet_address}] Faucet attempt {attempt + 1}/{max_attempts} failed: {self._last_error}, retrying...")
                await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"[{self.wallet_address}] Faucet error: {e}")
                await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
        
        logger.error(f"[{self.wallet_address}] Failed to request faucet tokens after {max_attempts} attempts: {self._last_error}")
        return False

    # ==================== SWAP METHODS ====================
    
    def _load_contract_abi(self, abi_name: str) -> list:
        """Загрузить ABI контракта из modules/neura/abi"""
        abi_path = neura_module_path / 'abi' / f'{abi_name}.json'
        try:
            with open(abi_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[{self.wallet_address}] Failed to load ABI {abi_name}: {e}")
            return []
    
    def _get_web3(self) -> Web3:
        """Получить Web3 instance для Neura"""
        return Web3(Web3.HTTPProvider('https://testnet.rpc.neuraprotocol.io'))
    
    def _normalize_addr(self, addr: str) -> str:
        """Нормализовать адрес для path encoding"""
        if not (isinstance(addr, str) and addr.startswith("0x") and len(addr) == 42):
            raise ValueError(f"Invalid address: {addr}")
        return addr[2:].lower()
    
    def _encode_path(self, token_in: str, token_out: str) -> str:
        """Кодировать path для quoter"""
        a = self._normalize_addr(token_in)
        b = self._normalize_addr(token_out)
        zeros20 = "00" * 20
        return "0x" + a + zeros20 + b
    
    async def _get_wallet_balance(self, web3: Web3, is_native: bool = True, token_address: Optional[str] = None) -> int:
        """Получить баланс кошелька"""
        try:
            if is_native or not token_address:
                balance = web3.eth.get_balance(self.wallet_address)
                return balance
            else:
                erc20_abi = self._load_contract_abi('erc20')
                contract = web3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=erc20_abi
                )
                balance = contract.functions.balanceOf(self.wallet_address).call()
                return balance
        except Exception as e:
            logger.error(f"[{self.wallet_address}] Failed to get balance: {e}")
            return 0
    
    async def _get_min_amount_out(self, web3: Web3, from_token_address: str, to_token_address: str, amount: int) -> int:
        """Получить минимальное количество токенов на выходе через quoter"""
        try:
            quoter_abi = self._load_contract_abi('quoter')
            quoter = web3.eth.contract(
                address=Web3.to_checksum_address(NEURA_QUOTER_ADDRESS),
                abi=quoter_abi
            )
            
            path = self._encode_path(from_token_address, to_token_address)
            
            result = quoter.functions.quoteExactInput(path, amount).call()
            min_amount_out = result[0][0] if isinstance(result[0], (list, tuple)) else result[0]
            
            logger.info(f"[{self.wallet_address}] Quote received: {min_amount_out / 10**18:.6f}")
            
            # Применяем slippage (уменьшаем ожидаемую сумму)
            slippage_amount = int(min_amount_out * (100 - NEURA_SWAP_SLIPPAGE) / 100)
            return slippage_amount
            
        except Exception as e:
            logger.warning(f"[{self.wallet_address}] Quoter call failed: {e}")
            # Fallback для тестнета - принимаем любой результат > 0
            # Установим 0 чтобы swap прошел с любым выходом
            return 0
    
    async def _approve_token(self, web3: Web3, token_address: str, spender: str, amount: int) -> bool:
        """Approve токена для swaps"""
        try:
            erc20_abi = self._load_contract_abi('erc20')
            contract = web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=erc20_abi
            )
            
            # Проверяем текущий allowance
            current_allowance = contract.functions.allowance(
                self.wallet_address,
                Web3.to_checksum_address(spender)
            ).call()
            
            if current_allowance >= amount:
                logger.info(f"[{self.wallet_address}] Token already approved")
                return True
            
            # Создаем транзакцию approve
            tx = contract.functions.approve(
                Web3.to_checksum_address(spender),
                amount
            ).build_transaction({
                'from': self.wallet_address,
                'nonce': web3.eth.get_transaction_count(self.wallet_address),
                'gasPrice': int(web3.eth.gas_price * 1.2),
                'gas': 100000
            })
            
            # Подписываем и отправляем
            signed_tx = web3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # Ждем подтверждения
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                logger.success(f"[{self.wallet_address}] Token approved! TX: {tx_hash.hex()}")
                return True
            else:
                logger.error(f"[{self.wallet_address}] Token approval failed")
                return False
                
        except Exception as e:
            logger.error(f"[{self.wallet_address}] Approve error: {e}")
            return False
    
    async def swap(self, from_token: str = None, to_token: str = None) -> Tuple[bool, Optional[str]]:
        """Выполнить swap токенов. Возвращает (success, tx_hash)"""
        web3 = self._get_web3()
        
        # Выбираем пару для свапа
        if from_token is None or to_token is None:
            if NEURA_RANDOM_SWAP_PAIR:
                from_token, to_token = random.choice(NEURA_SWAP_PAIRS)
            else:
                from_token, to_token = NEURA_SWAP_PAIRS[0]
        
        logger.info(f"[{self.wallet_address}] Starting swap: {from_token} -> {to_token}")
        
        try:
            await self._process_action(action_type='game:visitFountain')
            
            # Определяем адреса токенов
            is_native = from_token == 'ANKR'
            from_token_address = NEURA_TOKENS.get(from_token if not is_native else 'WANKR')
            to_token_address = NEURA_TOKENS.get(to_token if to_token != 'ANKR' else 'WANKR')
            
            if not from_token_address and not is_native:
                logger.error(f"[{self.wallet_address}] Unknown from token: {from_token}")
                return False, None
            if not to_token_address:
                logger.error(f"[{self.wallet_address}] Unknown to token: {to_token}")
                return False, None
            
            # Получаем баланс
            token_addr_for_balance = None if is_native else NEURA_TOKENS.get(from_token)
            balance = await self._get_wallet_balance(web3, is_native=is_native, token_address=token_addr_for_balance)
            
            if balance == 0:
                logger.warning(f"[{self.wallet_address}] Zero balance for {from_token}")
                return False, None
            
            # Определяем сумму для свапа
            swap_percentage = random.uniform(*NEURA_SWAP_PERCENTAGE)
            amount = int(balance * swap_percentage)
            
            if amount == 0:
                logger.warning(f"[{self.wallet_address}] Calculated swap amount is 0")
                return False, None
            
            logger.info(f"[{self.wallet_address}] Swapping {amount / 10**18:.6f} {from_token} ({swap_percentage*100:.1f}% of balance)")
            
            # Approve если не нативный токен
            if not is_native:
                if not await self._approve_token(web3, NEURA_TOKENS.get(from_token), NEURA_ROUTER_ADDRESS, amount):
                    return False, None
            
            # Загружаем ABI роутера
            router_abi = self._load_contract_abi('router')
            router_contract = web3.eth.contract(
                address=Web3.to_checksum_address(NEURA_ROUTER_ADDRESS),
                abi=router_abi
            )
            
            # Получаем min amount out
            min_amount_out = await self._get_min_amount_out(
                web3,
                from_token_address if not is_native else NEURA_TOKENS['WANKR'],
                to_token_address,
                amount
            )
            
            # Строим swap транзакцию
            deadline = int(time.time() * 1000 + 1800000)  # 30 минут
            
            swap_params = (
                Web3.to_checksum_address(from_token_address if not is_native else NEURA_TOKENS['WANKR']),
                Web3.to_checksum_address(to_token_address),
                Web3.to_checksum_address('0x0000000000000000000000000000000000000000'),
                self.wallet_address if from_token == 'ANKR' else Web3.to_checksum_address('0x0000000000000000000000000000000000000000'),
                deadline,
                amount,
                min_amount_out,
                0
            )
            
            transaction_data = router_contract.encode_abi(
                abi_element_identifier="exactInputSingle",
                args=[swap_params]
            )
            
            multicall_data = [transaction_data]
            
            # Если свапаем в ANKR, добавляем unwrap
            if to_token == 'ANKR':
                unwrap_data = router_contract.encode_abi(
                    abi_element_identifier="unwrapWNativeToken",
                    args=[min_amount_out, self.wallet_address]
                )
                multicall_data.append(unwrap_data)
            
            # Оцениваем gas
            try:
                gas_estimate = router_contract.functions.multicall(multicall_data).estimate_gas({
                    'from': self.wallet_address,
                    'value': amount if is_native else 0
                })
                gas_limit = int(gas_estimate * 1.15)
            except Exception as e:
                logger.warning(f"[{self.wallet_address}] Gas estimation failed, using default: {e}")
                gas_limit = 300000
            
            # Строим транзакцию
            tx = router_contract.functions.multicall(multicall_data).build_transaction({
                'value': amount if is_native else 0,
                'nonce': web3.eth.get_transaction_count(self.wallet_address),
                'from': self.wallet_address,
                'gasPrice': int(web3.eth.gas_price * 1.2),
                'gas': gas_limit
            })
            
            # Подписываем и отправляем
            signed_tx = web3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            logger.info(f"[{self.wallet_address}] Swap TX sent: {tx_hash.hex()}")
            
            # Ждем подтверждения
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                tx_hash_hex = tx_hash.hex()
                explorer_url = NETWORKS.get('🚀 Neura Testnet', {}).get('tx_url', 'https://testnet-blockscout.infra.neuraprotocol.io/tx/')
                logger.success(f"[{self.wallet_address}] Successfully swapped {from_token} -> {to_token} | TX: {explorer_url}{tx_hash_hex}")
                return True, tx_hash_hex
            else:
                self._last_error = f"Swap transaction failed, receipt status={receipt.status}"
                logger.error(f"[{self.wallet_address}] Swap transaction failed")
                return False, None
                
        except Exception as e:
            import traceback
            self._last_error = str(e)
            logger.error(f"[{self.wallet_address}] Swap error: {e}")
            logger.error(f"[{self.wallet_address}] Full swap error:\n{traceback.format_exc()}")
            return False, None
    
    async def execute_swap(self) -> Tuple[bool, List[str]]:
        """Выполнить swap с retry логикой. Возвращает (success, list_of_tx_hashes)"""
        max_attempts = NEURA_MAX_RETRIES_PER_TASK
        
        swap_count = random.randint(NEURA_SWAP_COUNT[0], NEURA_SWAP_COUNT[1])
        logger.info(f"[{self.wallet_address}] Запланировано {swap_count} swap транзакций")
        
        successful_swaps = 0
        tx_hashes = []
        
        for swap_num in range(swap_count):
            logger.info(f"[{self.wallet_address}] Swap {swap_num + 1}/{swap_count}")
            
            for attempt in range(max_attempts):
                try:
                    success, tx_hash = await self.swap()
                    if success:
                        successful_swaps += 1
                        if tx_hash:
                            tx_hashes.append(tx_hash)
                        break
                    
                    logger.warning(f"[{self.wallet_address}] Swap {swap_num + 1} attempt {attempt + 1}/{max_attempts} failed: {self._last_error}, retrying...")
                    await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                    
                except Exception as e:
                    self._last_error = str(e)
                    logger.error(f"[{self.wallet_address}] Swap error: {e}")
                    await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            
            if swap_num < swap_count - 1:
                pause = random.uniform(*NEURA_SWAP_PAUSE_BETWEEN_SWAPS)
                logger.info(f"[{self.wallet_address}] Пауза {pause:.1f}с перед следующим свапом...")
                await asyncio.sleep(pause)
        
        if successful_swaps > 0:
            logger.success(f"[{self.wallet_address}] Выполнено {successful_swaps}/{swap_count} свапов")
            return True, tx_hashes
        
        logger.error(f"[{self.wallet_address}] Failed to execute any swaps after all attempts: {self._last_error}")
        return False, tx_hashes
