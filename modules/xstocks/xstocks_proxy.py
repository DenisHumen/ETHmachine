"""Адаптер прокси для xStocks — обёртка над modules.proxy_manager."""
import random
from modules.data_manager import load_data


class XStocksProxyManager:
    """Прокси-менеджер для xStocks с поддержкой 1:1 привязки, резерва и aiohttp."""

    def __init__(self):
        self.proxies: list[str] = []
        self.wallet_proxies: dict[str, str] = {}
        self.reserve_proxies: dict[str, str] = {}
        self._load_proxies()

    def _load_proxies(self):
        """Загрузить прокси и резервные прокси из data.csv."""
        rows = load_data()
        for row in rows:
            pk = row.get('private_key', '').strip()
            proxy = row.get('proxy', '').strip()
            reserve = row.get('reserve_proxy', '').strip()
            if pk and proxy:
                normalized = self._normalize_proxy(proxy)
                self.proxies.append(normalized)
                self.wallet_proxies[pk] = normalized
            if pk and reserve:
                self.reserve_proxies[pk] = self._normalize_proxy(reserve)

    def get_proxy_for_wallet(self, private_key: str, address: str = "", index: int = 0) -> str | None:
        """Получить прокси для кошелька (по приватному ключу)."""
        proxy = self.wallet_proxies.get(private_key)
        if proxy:
            return proxy
        if index < len(self.proxies):
            return self.proxies[index]
        return None

    def rotate_proxy(self, private_key: str, address: str = "") -> str | None:
        """Заменить прокси на резервную при ошибке."""
        reserve = self.reserve_proxies.get(private_key)
        if reserve:
            self.wallet_proxies[private_key] = reserve
            return reserve
        if not self.proxies:
            return None
        current = self.wallet_proxies.get(private_key)
        available = [p for p in self.proxies if p != current]
        if not available:
            available = self.proxies
        new_proxy = random.choice(available)
        self.wallet_proxies[private_key] = new_proxy
        return new_proxy

    def _normalize_proxy(self, proxy: str) -> str:
        """Привести прокси к формату с протоколом."""
        proxy = proxy.strip()
        if not proxy:
            return proxy
        if "://" in proxy:
            return proxy
        if "@" in proxy:
            return f"http://{proxy}"
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
