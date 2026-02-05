import time
import requests
from typing import Optional


class CapsolverSolver:
    
    def __init__(self, api_key: str, proxy: Optional[str] = None):
        self.api_key = api_key
        self.proxy_url = proxy
        self.base_url = "https://api.capsolver.com"
    
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
            resp = requests.post(f"{self.base_url}/createTask", json=task_payload, timeout=30)
            data = resp.json()
            
            if data.get("errorId") != 0:
                raise Exception(f"CAPSOLVER error: {data.get('errorDescription', 'Unknown')}")
            
            task_id = data.get("taskId")
            if not task_id:
                raise Exception("No taskId returned")
            
            for _ in range(120):
                time.sleep(3)
                result_resp = requests.post(
                    f"{self.base_url}/getTaskResult",
                    json={"clientKey": self.api_key, "taskId": task_id},
                    timeout=30
                )
                result = result_resp.json()
                
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
