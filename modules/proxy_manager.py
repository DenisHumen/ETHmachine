import random
from typing import Optional, Dict, List
from modules.simple_logger import logger
from modules.data_manager import get_proxies, get_reserve_proxies


class ProxyManager:
    _proxies: List[str] = []
    _loaded: bool = False

    @classmethod
    def load_proxies(cls, force_reload: bool = False) -> List[str]:
        if cls._loaded and not force_reload:
            return cls._proxies

        cls._proxies = get_proxies()
        cls._loaded = True
        if cls._proxies:
            logger.info(f"Загружено {len(cls._proxies)} прокси из data.csv")
        return cls._proxies

    @classmethod
    def get_all(cls) -> List[str]:
        return cls.load_proxies()

    @classmethod
    def get_random(cls) -> Optional[str]:
        proxies = cls.load_proxies()
        return random.choice(proxies) if proxies else None

    @classmethod
    def count(cls) -> int:
        return len(cls.load_proxies())


def parse_proxy(proxy_string: Optional[str]) -> Optional[str]:
    if not proxy_string:
        return None

    proxy_string = proxy_string.strip()
    if proxy_string.startswith('http://'):
        proxy_string = proxy_string[7:]
    elif proxy_string.startswith('https://'):
        proxy_string = proxy_string[8:]

    try:
        if '@' in proxy_string:
            auth, addr = proxy_string.split('@', 1)
            login, password = auth.split(':', 1)
            ip, port = addr.split(':', 1)
            return f"http://{login}:{password}@{ip}:{port}"
        else:
            ip, port = proxy_string.split(':', 1)
            return f"http://{ip}:{port}"
    except Exception:
        return None


def get_proxy_dict(proxy_string: Optional[str]) -> Optional[Dict[str, str]]:
    url = parse_proxy(proxy_string)
    if url:
        return {'http': url, 'https': url}
    return None


def get_random_proxy(proxies: Optional[List[str]] = None) -> Optional[str]:
    if proxies:
        proxy = random.choice(proxies) if proxies else None
        return parse_proxy(proxy)
    return parse_proxy(ProxyManager.get_random())


def get_random_proxy_dict(proxies: Optional[List[str]] = None) -> Optional[Dict[str, str]]:
    proxy = get_random_proxy(proxies)
    return get_proxy_dict(proxy) if proxy else None


def load_proxies() -> List[str]:
    return ProxyManager.load_proxies()


def mask_proxy(proxy_string: Optional[str]) -> str:
    if not proxy_string:
        return "None"
    if '@' in proxy_string:
        return proxy_string.split('@')[1]
    return proxy_string


__all__ = [
    'ProxyManager',
    'parse_proxy',
    'get_proxy_dict',
    'get_random_proxy',
    'get_random_proxy_dict',
    'load_proxies',
    'mask_proxy'
]
