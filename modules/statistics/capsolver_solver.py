import time
import requests
from typing import Optional, Dict
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from modules.proxy_manager import parse_proxy, get_proxy_dict


class CapsolverSolver:
    
    def __init__(self, api_key: str, proxy: Optional[str] = None):
        self.api_key = api_key
        self.proxy_url = proxy
        self.base_url = "https://api.capsolver.com"
        
        # Настраиваем прокси для requests если задан
        self._request_proxies: Optional[Dict[str, str]] = None
        if proxy:
            self._request_proxies = get_proxy_dict(proxy)
    
    def _make_request(self, endpoint: str, payload: dict, timeout: int = 30) -> dict:
        """Отправка запроса к API capsolver с учетом прокси"""
        resp = requests.post(
            f"{self.base_url}/{endpoint}",
            json=payload,
            proxies=self._request_proxies,
            timeout=timeout
        )
        return resp.json()
    
    def solve_turnstile(
        self,
        sitekey: str,
        pageurl: str,
        action: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Optional[str]:
        task_payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": pageurl,
                "websiteKey": sitekey,
            }
        }
        
        if action:
            task_payload["task"]["metadata"] = {"action": action}
        
        try:
            data = self._make_request("createTask", task_payload)
            
            if data.get("errorId") != 0:
                raise Exception(f"CAPSOLVER error: {data.get('errorDescription', 'Unknown')}")
            
            task_id = data.get("taskId")
            if not task_id:
                raise Exception("No taskId returned")
            
            for _ in range(120):
                time.sleep(3)
                result = self._make_request(
                    "getTaskResult",
                    {"clientKey": self.api_key, "taskId": task_id}
                )
                
                if result.get("status") == "ready":
                    token = result.get("solution", {}).get("token")
                    if token:
                        return token
                    raise Exception("No token in solution")
                
                if result.get("errorId") != 0:
                    raise Exception(f"CAPTCHA_UNSOLVABLE: {result.get('errorDescription')}")
            
            raise Exception("Timeout waiting for captcha solution")
            
        except requests.RequestException as e:
            raise Exception(f"Network error: {e}")
