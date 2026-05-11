"""
YesCaptcha Solver - решение hCaptcha, Turnstile и reCAPTCHA через YesCaptcha API.
https://yescaptcha.com/
Docs: https://yescaptcha.atlassian.net/wiki/spaces/YESCAPTCHA/overview

Курс: 100 RMB = 125,000 Points, 100 RMB ~ 13.7 USDT
=> 1 Point ~ 0.0001096 USDT

Supported task types:
  - HCaptchaTaskProxyless        → hcaptcha
  - TurnstileTaskProxyless       → turnstile
  - NoCaptchaTaskProxyless       → recaptcha_v2
  - RecaptchaV3TaskProxyless     → recaptcha_v3
"""
import time
import requests
from typing import Optional, Dict


SUPPORTED_CAPTCHA_TYPES = ['hcaptcha', 'turnstile', 'recaptcha_v2', 'recaptcha_v3']
from modules.simple_logger import logger


POINTS_PER_RMB_100 = 125_000
USDT_PER_RMB_100 = 13.7
USDT_PER_POINT = USDT_PER_RMB_100 / POINTS_PER_RMB_100


class YesCaptchaSolver:

    def __init__(self, api_key: str, proxy: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://api.yescaptcha.com"
        self.proxy_url = proxy
        self._request_proxies: Optional[Dict[str, str]] = None
        if proxy:
            self._request_proxies = self._build_proxy_dict(proxy)
        self._total_points_spent = 0
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

    def get_balance(self) -> int:
        data = self._make_request("getBalance", {"clientKey": self.api_key})
        if data.get("errorId", 1) != 0:
            raise Exception(f"YesCaptcha getBalance error: {data.get('errorDescription', 'Unknown')}")
        return data.get("balance", 0)

    def _log_cost(self, task_type: str, points_before: int, points_after: int, elapsed: float):
        spent = max(points_before - points_after, 0)
        self._total_points_spent += spent
        self._solve_count += 1
        usdt_spent = spent * USDT_PER_POINT
        usdt_total = self._total_points_spent * USDT_PER_POINT
        logger.info(
            f"[YesCaptcha] {task_type} solved in {elapsed:.1f}s | "
            f"Cost: {spent:,} pts (${usdt_spent:.4f}) | "
            f"Session total: {self._total_points_spent:,} pts (${usdt_total:.4f}) | "
            f"Balance: {points_after:,} pts | Solves: {self._solve_count}"
        )

    def _wait_for_result(self, task_id: str, token_field: str = "gRecaptchaResponse") -> Optional[str]:
        for _ in range(120):
            time.sleep(3)
            result = self._make_request("getTaskResult", {"clientKey": self.api_key, "taskId": task_id})
            if result.get("status") == "ready":
                solution = result.get("solution", {})
                token = solution.get(token_field) or solution.get("token")
                if token:
                    return token
                raise Exception(f"No token in YesCaptcha solution: {solution}")
            if result.get("errorId", 0) != 0:
                raise Exception(f"YesCaptcha error: {result.get('errorCode', '')} - {result.get('errorDescription', '')}")
        raise Exception("YesCaptcha timeout waiting for solution")

    def _solve(self, task: dict, task_type: str, token_field: str = "gRecaptchaResponse") -> Optional[str]:
        try:
            balance_before = self.get_balance()
        except Exception:
            balance_before = -1

        start_time = time.time()
        data = self._make_request("createTask", {"clientKey": self.api_key, "task": task})

        if data.get("errorId", 0) != 0:
            raise Exception(f"YesCaptcha createTask error: {data.get('errorCode', '')} - {data.get('errorDescription', 'Unknown')}")

        task_id = data.get("taskId")
        if not task_id:
            raise Exception("YesCaptcha: no taskId returned")

        token = self._wait_for_result(task_id, token_field)
        elapsed = time.time() - start_time

        try:
            balance_after = self.get_balance()
            self._log_cost(task_type, balance_before, balance_after, elapsed)
        except Exception:
            self._solve_count += 1
            logger.info(f"[YesCaptcha] {task_type} solved in {elapsed:.1f}s | Solves: {self._solve_count}")

        return token

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
        if user_agent:
            task["userAgent"] = user_agent
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
        return {
            "solves": self._solve_count,
            "points_spent": self._total_points_spent,
            "usdt_spent": round(self._total_points_spent * USDT_PER_POINT, 4),
        }
