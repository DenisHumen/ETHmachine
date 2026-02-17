"""Адаптер прокси для Pharos — обёртка над modules.proxy_manager."""
import random
from modules.proxy_manager import ProxyManager as BaseProxyManager, parse_proxy


class PharosProxyManager:
    """Прокси-менеджер для Pharos с поддержкой 1:1 привязки и aiohttp."""

    def __init__(self):
        self.proxies: list[str] = []
        self.wallet_proxies: dict[str, str] = {}
        self._load_proxies()

    def _load_proxies(self):
        """Загрузить прокси через основной ProxyManager."""
        raw = BaseProxyManager.load_proxies(force_reload=True)
        self.proxies = [self._normalize_proxy(p) for p in raw if p.strip()]

    def get_proxy_for_wallet(self, address: str, index: int = 0) -> str | None:
        """Получить прокси для кошелька (1:1 по индексу)."""
        if not self.proxies:
            return None
        if address in self.wallet_proxies:
            return self.wallet_proxies[address]
        if index < len(self.proxies):
            proxy = self.proxies[index]
            self.wallet_proxies[address] = proxy
            return proxy
        return None

    def rotate_proxy(self, address: str) -> str | None:
        """Заменить прокси на случайную другую при ошибке."""
        if not self.proxies:
            return None
        current = self.wallet_proxies.get(address)
        available = [p for p in self.proxies if p != current]
        if not available:
            available = self.proxies
        new_proxy = random.choice(available)
        self.wallet_proxies[address] = new_proxy
        return new_proxy

    def _normalize_proxy(self, proxy: str) -> str:
        """Привести прокси к формату с протоколом."""
        proxy = proxy.strip()
        if not proxy:
            return proxy
        if "://" in proxy:
            return proxy

        # Формат user:pass@host:port
        if "@" in proxy:
            return f"http://{proxy}"

        # Формат ip:port:user:pass
        parts = proxy.split(":")
        if len(parts) == 4:
            ip, port, user, pwd = parts
            return f"http://{user}:{pwd}@{ip}:{port}"
        elif len(parts) == 2:
            return f"http://{proxy}"

        return f"http://{proxy}"

    def get_aiohttp_proxy_config(self, proxy: str | None) -> dict:
        """Получить конфиг прокси для aiohttp."""
        if not proxy:
            return {"socks_url": None, "proxy": None, "proxy_auth": None}

        from aiohttp import BasicAuth
        proxy = proxy.strip()

        if proxy.startswith("socks"):
            return {"socks_url": proxy, "proxy": None, "proxy_auth": None}

        # HTTP(S)
        if "@" in proxy:
            scheme_rest = proxy.split("://", 1)
            if len(scheme_rest) == 2:
                scheme, rest = scheme_rest
            else:
                scheme, rest = "http", scheme_rest[0]
            auth_part, host_part = rest.rsplit("@", 1)
            user, pwd = auth_part.split(":", 1)
            proxy_url = f"{scheme}://{host_part}"
            return {
                "socks_url": None,
                "proxy": proxy_url,
                "proxy_auth": BasicAuth(user, pwd),
            }

        return {"socks_url": None, "proxy": proxy, "proxy_auth": None}

    @property
    def count(self) -> int:
        return len(self.proxies)
