"""Решение капчи через Capsolver (Turnstile / reCAPTCHA)."""
import time
import requests

from config.modules.cfg_base import CAPSOLVER_API_KEY

CAPSOLVER_CREATE = "https://api.capsolver.com/createTask"
CAPSOLVER_RESULT = "https://api.capsolver.com/getTaskResult"


def solve_turnstile(proxy: str = None, website_url: str = None, website_key: str = None) -> str | None:
    """Решить Turnstile капчу через Capsolver. Возвращает токен или None."""
    if not website_url or not website_key:
        return None

    try:
        task = {
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": website_url,
            "websiteKey": website_key,
        }

        if proxy:
            task["type"] = "AntiTurnstileTask"
            parsed = _parse_proxy_for_capsolver(proxy)
            if parsed:
                task.update(parsed)

        payload = {"clientKey": CAPSOLVER_API_KEY, "task": task}
        resp = requests.post(CAPSOLVER_CREATE, json=payload, timeout=30)
        data = resp.json()

        if data.get("errorId") and data.get("errorId") != 0:
            return None

        task_id = data.get("taskId")
        if not task_id:
            return None

        for _ in range(30):
            time.sleep(5)
            result_resp = requests.post(
                CAPSOLVER_RESULT,
                json={"clientKey": CAPSOLVER_API_KEY, "taskId": task_id},
                timeout=30,
            )
            result = result_resp.json()
            status = result.get("status")

            if status == "ready":
                token = result.get("solution", {}).get("token")
                if token:
                    return token
                break
            elif status == "processing":
                continue
            else:
                break

    except Exception:
        pass

    return None


def _parse_proxy_for_capsolver(proxy: str) -> dict | None:
    """Парсинг прокси в формат Capsolver."""
    try:
        proxy = proxy.strip()
        if "://" in proxy:
            scheme, rest = proxy.split("://", 1)
        else:
            scheme, rest = "http", proxy

        proxy_type = "http" if "http" in scheme.lower() else "socks5"

        if "@" in rest:
            auth, host_port = rest.rsplit("@", 1)
            username, password = auth.split(":", 1) if ":" in auth else (auth, "")
        else:
            host_port = rest
            username, password = "", ""

        host, port = host_port.rsplit(":", 1) if ":" in host_port else (host_port, "80")

        result = {"proxyType": proxy_type, "proxyAddress": host, "proxyPort": int(port)}
        if username:
            result["proxyLogin"] = username
            result["proxyPassword"] = password
        return result
    except Exception:
        return None
