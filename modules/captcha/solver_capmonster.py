"""
CapMonster Cloud Solver - решение hCaptcha, Turnstile и reCAPTCHA через CapMonster API.
https://capmonster.cloud/
Docs: https://docs.capmonster.cloud/

Supported task types:
  - HCaptchaTaskProxyless        → hcaptcha
  - TurnstileTask                → turnstile
  - RecaptchaV2TaskProxyless     → recaptcha_v2
  - RecaptchaV3TaskProxyless     → recaptcha_v3
"""
import time
import requests
from typing import Optional, Dict
from modules.simple_logger import logger


SUPPORTED_CAPTCHA_TYPES = ['hcaptcha', 'turnstile', 'recaptcha_v2', 'recaptcha_v3']


class CapMonsterSolver:

    def __init__(self, api_key: str, proxy: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://api.capmonster.cloud"
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

    def get_balance(self) -> float:
        data = self._make_request("getBalance", {"clientKey": self.api_key})
        if data.get("errorId", 1) != 0:
            raise Exception(f"CapMonster getBalance error: {data.get('errorDescription', 'Unknown')}")
        return data.get("balance", 0)

    def _solve(self, task: dict, task_type: str, token_field: str = "gRecaptchaResponse") -> Optional[str]:
        start_time = time.time()
        data = self._make_request("createTask", {"clientKey": self.api_key, "task": task})

        if data.get("errorId", 0) != 0:
            raise Exception(f"CapMonster error: {data.get('errorCode', '')} - {data.get('errorDescription', 'Unknown')}")

        task_id = data.get("taskId")
        if not task_id:
            raise Exception("CapMonster: no taskId returned")

        for _ in range(120):
            time.sleep(3)
            result = self._make_request("getTaskResult", {"clientKey": self.api_key, "taskId": task_id})
            if result.get("status") == "ready":
                solution = result.get("solution", {})
                token = solution.get(token_field) or solution.get("token")
                if token:
                    elapsed = time.time() - start_time
                    self._solve_count += 1
                    logger.info(f"[CapMonster] {task_type} solved in {elapsed:.1f}s | Solves: {self._solve_count}")
                    return token
                raise Exception(f"No token in CapMonster solution: {solution}")
            if result.get("errorId", 0) != 0:
                raise Exception(f"CapMonster error: {result.get('errorCode', '')} - {result.get('errorDescription', '')}")

        raise Exception("CapMonster timeout waiting for solution")

    def solve_hcaptcha(self, sitekey: str, pageurl: str,
                       user_agent: Optional[str] = None,
                       is_invisible: bool = False) -> Optional[str]:
        task = {"type": "HCaptchaTaskProxyless", "websiteURL": pageurl, "websiteKey": sitekey}
        if user_agent:
            task["userAgent"] = user_agent
        if is_invisible:
            task["isInvisible"] = True
        return self._solve(task, "hCaptcha", token_field="gRecaptchaResponse")

    def solve_turnstile(self, sitekey: str, pageurl: str,
                        action: Optional[str] = None,
                        user_agent: Optional[str] = None) -> Optional[str]:
        task = {"type": "TurnstileTaskProxyless", "websiteURL": pageurl, "websiteKey": sitekey}
        if action:
            task["metadata"] = {"action": action}
        return self._solve(task, "Turnstile", token_field="token")

    def solve_recaptcha_v2(self, sitekey: str, pageurl: str,
                           is_invisible: bool = False) -> Optional[str]:
        task = {"type": "NoCaptchaTaskProxyless", "websiteURL": pageurl, "websiteKey": sitekey}
        if is_invisible:
            task["isInvisible"] = True
        return self._solve(task, "reCAPTCHA v2", token_field="gRecaptchaResponse")

    def solve_recaptcha_v3(self, sitekey: str, pageurl: str,
                           page_action: str = "",
                           min_score: float = 0.3) -> Optional[str]:
        task = {
            "type": "RecaptchaV3TaskProxyless",
            "websiteURL": pageurl,
            "websiteKey": sitekey,
            "pageAction": page_action,
            "minScore": min_score,
        }
        return self._solve(task, "reCAPTCHA v3", token_field="gRecaptchaResponse")

    @property
    def session_stats(self) -> dict:
        return {"solves": self._solve_count, "points_spent": 0, "usdt_spent": 0}
