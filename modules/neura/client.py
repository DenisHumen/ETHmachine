import uuid
import random
import asyncio
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

from loguru import logger
from colorama import Fore, Style, init as colorama_init
from curl_cffi.requests import AsyncSession, BrowserType
from eth_account import Account as EthAccount
from eth_account.messages import encode_defunct

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from config.config import (
    RETRY_COUNT, SLEEP_BETWEEN_ACTIONS, astrum_CAPTCHA_API_KEY,
    NEURA_MAX_RETRIES_PER_TASK
)
from modules.neura.types import UserData

try:
    from modules.statistics.astrum_captcha_solver import AstrumSolver  # type: ignore
except ImportError:
    AstrumSolver = None

colorama_init(autoreset=False)


def log_success(wallet: str, message: str):
    logger.opt(colors=False).success(f"{Fore.GREEN}[{wallet}] | {message}{Style.RESET_ALL}")


def log_warning(wallet: str, message: str):
    logger.opt(colors=False).warning(f"{Fore.YELLOW}[{wallet}] | {message}{Style.RESET_ALL}")


def log_error(wallet: str, message: str):
    logger.opt(colors=False).error(f"{Fore.RED}[{wallet}] | {message}{Style.RESET_ALL}")


def log_info(wallet: str, message: str):
    logger.opt(colors=False).info(f"[{wallet}] | {message}")


class NeuraClient:
    
    def __init__(self, private_key: str, proxy: Optional[str] = None):
        self.private_key = private_key
        self.proxy = proxy
        self.jwt_token = None
        self.user_data: Optional[UserData] = None
        
        self.account = EthAccount.from_key(private_key)
        self.wallet_address = self.account.address
        
        proxy_url = None
        proxy_dict = None
        if proxy:
            if not proxy.startswith('http'):
                proxy_url = f"http://{proxy}"
            else:
                proxy_url = proxy
            proxy_dict = {'http': proxy_url, 'https': proxy_url}
            proxy_ip = proxy.split('@')[-1] if '@' in proxy else proxy[:30]
            log_info(self.wallet_address, f"Using proxy: {proxy_ip}")
        else:
            log_warning(self.wallet_address, "No proxy configured!")
        
        self.session = AsyncSession(
            proxies=proxy_dict,  # type: ignore
            impersonate="chrome131"  # type: ignore
        )
        
        self._captcha_solver = None
        if astrum_CAPTCHA_API_KEY and AstrumSolver:
            try:
                self._captcha_solver = AstrumSolver(
                    api_key=astrum_CAPTCHA_API_KEY,
                    proxy=proxy_url
                )
            except Exception as e:
                log_warning(self.wallet_address, f"Failed to init AstrumSolver: {e}")
        
        self.auth_headers = {
            'accept': 'application/json',
            'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/json',
            'origin': 'https://neuraverse.neuraprotocol.io',
            'priority': 'u=1, i',
            'privy-app-id': 'cmbpempz2011ll10l7iucga14',
            'privy-ca-id': str(uuid.uuid4()),
            'privy-client': 'react-auth:2.25.0',
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
        return '0x' + signed_message.signature.hex()
    
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
            log_error(self.wallet_address, f"Request error: {e}")
            return None, 0
    
    async def _get_nonce(self) -> Optional[str]:
        if not self._captcha_solver:
            log_error(self.wallet_address, "Captcha solver not initialized!")
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
                    log_warning(self.wallet_address, f"Failed to solve captcha, attempt {attempt + 1}/{RETRY_COUNT}")
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
                    log_warning(self.wallet_address, f"Rate limited (429), waiting {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)
                    continue
                    
                log_warning(self.wallet_address, f"Failed to get nonce, status: {status}")
                
            except Exception as e:
                log_error(self.wallet_address, f"Error getting nonce: {e}")
            
            await asyncio.sleep(random.uniform(3, 7))
        
        log_warning(self.wallet_address, f"Failed to get nonce, attempt {attempt + 1}/{RETRY_COUNT}")
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
        
        return False
    
    async def authorize(self) -> bool:
        for attempt in range(RETRY_COUNT):
            nonce = await self._get_nonce()
            if not nonce:
                log_warning(self.wallet_address, f"Failed to get nonce, attempt {attempt + 1}/{RETRY_COUNT}")
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
                log_success(self.wallet_address, "Successfully authorized into Neuraverse!")
                return True
            
            log_warning(self.wallet_address, f"Authorization failed, attempt {attempt + 1}/{RETRY_COUNT}")
            await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
        
        log_error(self.wallet_address, "Failed to authorize after all attempts")
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
            log_success(self.wallet_address, f"Pulse {pulse_id} has been successfully collected!")
            return True
        
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
                log_warning(self.wallet_address, f"Failed to get user data, waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                continue
            
            consecutive_failures = 0 
            
            uncollected_pulses = [
                pulse for pulse in self.user_data.pulses.data
                if not pulse.is_collected
            ]
            
            if not uncollected_pulses:
                log_success(self.wallet_address, "All pulses have been already collected!")
                return True
            
            log_info(self.wallet_address, f"Found {len(uncollected_pulses)} uncollected pulses. Collecting...")
            
            for pulse_obj in uncollected_pulses:
                for attempt in range(NEURA_MAX_RETRIES_PER_TASK):
                    fresh_user = await self.get_user()
                    if fresh_user:
                        fresh_pulse = next(
                            (p for p in self.user_data.pulses.data if p.id == pulse_obj.id), 
                            None
                        )
                        if fresh_pulse and fresh_pulse.is_collected:
                            log_info(self.wallet_address, f"Pulse {pulse_obj.id} already collected, skipping...")
                            break
                    
                    if await self._collect_pulse(pulse_obj.id):
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                        break
                    else:
                        log_warning(
                            self.wallet_address, 
                            f"Failed to collect pulse {pulse_obj.id}, attempt {attempt + 1}/{NEURA_MAX_RETRIES_PER_TASK}"
                        )
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            
            await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            user_after = await self.get_user()
            
            if user_after:
                remaining = [p for p in self.user_data.pulses.data if not p.is_collected]
                if not remaining:
                    log_success(self.wallet_address, "Verified: All pulses successfully collected!")
                    return True
                else:
                    log_warning(
                        self.wallet_address, 
                        f"Still have {len(remaining)} uncollected pulses, cycle {cycle + 1}/{max_cycles}"
                    )
        
        log_error(self.wallet_address, "Failed to collect all pulses after max attempts")
        return False
    
    async def _get_tasks(self) -> Optional[list]:
        response_json, status = await self._make_request(
            method="GET",
            url='https://neuraverse-testnet.infra.neuraprotocol.io/api/tasks'
        )
        
        if status == 200 and response_json:
            return response_json.get('tasks', [])
        
        return None
    
    async def _claim_task(self, task_id: str) -> bool:
        response_json, status = await self._make_request(
            method="POST",
            url=f'https://neuraverse-testnet.infra.neuraprotocol.io/api/tasks/{task_id}/claim'
        )
        
        if status == 200 and response_json:
            points = response_json.get('points', 0)
            name = response_json.get('name', 'Unknown')
            log_success(
                self.wallet_address, 
                f"Successfully claimed {name} task and earned {points} points!"
            )
            return True
        
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
                log_warning(self.wallet_address, f"Failed to get tasks, waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                continue
            
            consecutive_failures = 0 
            
            claimable_tasks = [task for task in all_tasks if task.get('status') == 'claimable']
            
            if not claimable_tasks:
                log_success(self.wallet_address, "All tasks have been claimed!")
                return True
            
            log_info(self.wallet_address, f"Found {len(claimable_tasks)} claimable tasks. Claiming...")
            
            for task in claimable_tasks:
                task_id = task.get('id')
                task_name = task.get('name', 'Unknown')
                
                for attempt in range(NEURA_MAX_RETRIES_PER_TASK):
                    fresh_tasks = await self._get_tasks()
                    if fresh_tasks:
                        fresh_task = next((t for t in fresh_tasks if t.get('id') == task_id), None)
                        if fresh_task and fresh_task.get('status') != 'claimable':
                            log_info(self.wallet_address, f"Task {task_name} already claimed, skipping...")
                            break
                    
                    if await self._claim_task(task_id):
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
                        break
                    else:
                        log_warning(
                            self.wallet_address, 
                            f"Failed to claim task {task_name}, attempt {attempt + 1}/{NEURA_MAX_RETRIES_PER_TASK}"
                        )
                        await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            
            await asyncio.sleep(random.uniform(*SLEEP_BETWEEN_ACTIONS))
            all_tasks_after = await self._get_tasks()
            
            if all_tasks_after:
                remaining = [t for t in all_tasks_after if t.get('status') == 'claimable']
                if not remaining:
                    log_success(self.wallet_address, "Verified: All tasks successfully claimed!")
                    return True
                else:
                    log_warning(
                        self.wallet_address, 
                        f"Still have {len(remaining)} claimable tasks, cycle {cycle + 1}/{max_cycles}"
                    )
        
        log_error(self.wallet_address, "Failed to claim all tasks after max attempts")
        return False
