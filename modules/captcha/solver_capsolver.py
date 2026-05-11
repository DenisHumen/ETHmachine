"""
CapSolver - решение hCaptcha, Turnstile и reCAPTCHA через CapSolver API.
https://www.capsolver.com/
Docs: https://docs.capsolver.com/

Supported task types:
  - HCaptchaTaskProxyless        → hcaptcha
  - AntiTurnstileTaskProxyless   → turnstile
  - ReCaptchaV2TaskProxyless     → recaptcha_v2
  - ReCaptchaV3TaskProxyless     → recaptcha_v3
"""
import time
import requests
from typing import Optional, Dict
from modules.simple_logger import logger


SUPPORTED_CAPTCHA_TYPES = ['hcaptcha', 'turnstile', 'recaptcha_v2', 'recaptcha_v3']


class CapsolverSolver:

    def __init__(self, api_key: str, proxy: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://api.capsolver.com"
        self.proxy_url = proxy
        self._request_proxies: Optional[Dict[str, str]] = None
        if proxy:
            self._request_proxies = self._build_proxy_dict(proxy)
        self._solve_count = 0

    @staticmethod
    def _build_proxy_dict(proxy: str) -> Dict[str, str]:
        proxy = proxy.strip()
        if not proxy.startswith(('http://', 'https://', 'socks')):
            proxy = f"http://{proxy}"
        return {"http": proxy, "https": proxy}

    def _make_request(self, endpoint: str, payload: dict, timeout: int = 30) -> dict:
        resp = requests.post(
            f"{self.base_url}/{endpoint}",
            json=payload,
            proxies=self._request_proxies,
            timeout=timeout,
        )
        return resp.json()

    def _solve(self, task: dict, task_type: str, token_field: str = "token") -> Optional[str]:
        data = self._make_request("createTask", {"clientKey": self.api_key, "task": task})

        if data.get("errorId", 0) != 0:
            raise Exception(f"CapSolver error: {data.get('errorDescription', 'Unknown')}")

        task_id = data.get("taskId")
        if not task_id:
            raise Exception("CapSolver: no taskId returned")

        for _ in range(120):
            time.sleep(3)
            result = self._make_request("getTaskResult", {"clientKey": self.api_key, "taskId": task_id})
            if result.get("status") == "ready":
                solution = result.get("solution", {})
                token = solution.get(token_field) or solution.get("gRecaptchaResponse") or solution.get("token")
                if token:
                    self._solve_count += 1
                    return token
                raise Exception(f"No token in CapSolver solution: {solution}")
            if result.get("errorId", 0) != 0:
                raise Exception(f"CapSolver error: {result.get('errorDescription')}")

        raise Exception("CapSolver timeout waiting for solution")

    def solve_hcaptcha(self, sitekey: str, pageurl: str,
                       user_agent: Optional[str] = None,
                       is_invisible: bool = False) -> Optional[str]:
        task = {"type": "HCaptchaTaskProxyLess", "websiteURL": pageurl, "websiteKey": sitekey}
        if user_agent:
            task["userAgent"] = user_agent
        if is_invisible:
            task["isInvisible"] = True
        return self._solve(task, "hCaptcha", token_field="gRecaptchaResponse")

    def solve_turnstile(self, sitekey: str, pageurl: str,
                        action: Optional[str] = None,
                        user_agent: Optional[str] = None) -> Optional[str]:
        task = {"type": "AntiTurnstileTaskProxyLess", "websiteURL": pageurl, "websiteKey": sitekey}
        if action:
            task["metadata"] = {"action": action}
        return self._solve(task, "Turnstile", token_field="token")

    def solve_recaptcha_v2(self, sitekey: str, pageurl: str,
                           is_invisible: bool = False) -> Optional[str]:
        task = {"type": "ReCaptchaV2TaskProxyLess", "websiteURL": pageurl, "websiteKey": sitekey}
        if is_invisible:
            task["isInvisible"] = True
        return self._solve(task, "reCAPTCHA v2", token_field="gRecaptchaResponse")

    def solve_recaptcha_v3(self, sitekey: str, pageurl: str,
                           page_action: str = "",
                           min_score: float = 0.3) -> Optional[str]:
        task = {
            "type": "ReCaptchaV3TaskProxyLess",
            "websiteURL": pageurl,
            "websiteKey": sitekey,
            "pageAction": page_action,
            "minScore": min_score,
        }
        return self._solve(task, "reCAPTCHA v3", token_field="gRecaptchaResponse")

    @property
    def session_stats(self) -> dict:
        return {"solves": self._solve_count, "points_spent": 0, "usdt_spent": 0}
