import random
import re
from typing import Optional, Dict, List
from modules.simple_logger import logger
from modules.data_manager import get_proxies

# Схемы, которые реально умеют проксировать requests/PySocks. Всё остальное
# отклоняем: лучше явно отказать, чем выпустить трафик со сломанной схемой.
_SUPPORTED_SCHEMES = {'http', 'https', 'socks4', 'socks4a', 'socks5', 'socks5h'}
_SCHEME_RE = re.compile(r'^([a-zA-Z][a-zA-Z0-9+.\-]*)://')


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
    """Нормализует строку прокси в URL scheme://[user:pass@]host:port.

    Это единственный разделяемый парсер прокси в проекте, поэтому важна
    корректность. Поддерживает host:port, user:pass@host:port,
    scheme://host:port и scheme://user:pass@host:port для http/https/
    socks4/socks5, а также пароли с символами ':' и '@'.

    Зачем переписано: старая версия срезала только http/https и жёстко
    навешивала обратно http://, из-за чего socks5://... превращался в
    мусор вида http://socks5://...; любая ошибка тихо возвращала None, и
    один битый прокси в data.csv молча уводил трафик через реальный IP.
    Теперь при неудаче пишем в лог, ЧТО и ПОЧЕМУ не разобралось.
    """
    if not proxy_string or not proxy_string.strip():
        # Пустое значение — это «прокси не задан», а не ошибка разбора.
        return None

    raw = proxy_string.strip()

    # 1. Схема опциональна. Если её нет — по умолчанию http (так исторически
    #    выглядели строки пользователей: host:port и user:pass@host:port).
    scheme = 'http'
    body = raw
    m = _SCHEME_RE.match(raw)
    if m:
        scheme = m.group(1).lower()
        body = raw[m.end():]
        if scheme not in _SUPPORTED_SCHEMES:
            logger.warning(
                f"Не удалось разобрать прокси {mask_proxy(raw)}: "
                f"неизвестная схема '{scheme}'"
            )
            return None

    # 2. Отделяем credentials от адреса. Пароль может содержать '@', поэтому
    #    режем по ПОСЛЕДНЕМУ '@' — адрес host:port всегда справа.
    auth = None
    addr = body
    if '@' in body:
        auth, addr = body.rsplit('@', 1)

    # 3. Адрес host:port. Порт — крайняя правая часть; host у наших прокси
    #    (IPv4/hostname) двоеточий не содержит, поэтому режем по последнему ':'.
    if ':' not in addr:
        logger.warning(
            f"Не удалось разобрать прокси {mask_proxy(raw)}: "
            f"не найден порт (ожидается host:port)"
        )
        return None
    host, port = addr.rsplit(':', 1)
    if not host or not port.isdigit():
        logger.warning(
            f"Не удалось разобрать прокси {mask_proxy(raw)}: "
            f"некорректный host:port"
        )
        return None

    # 4. Credentials login:password. Пароль может содержать ':', поэтому
    #    режем по ПЕРВОМУ ':'.
    if auth is not None:
        if ':' not in auth:
            logger.warning(
                f"Не удалось разобрать прокси {mask_proxy(raw)}: "
                f"ожидается login:password перед '@'"
            )
            return None
        login, password = auth.split(':', 1)
        if not login:
            logger.warning(
                f"Не удалось разобрать прокси {mask_proxy(raw)}: пустой логин"
            )
            return None
        return f"{scheme}://{login}:{password}@{host}:{port}"

    return f"{scheme}://{host}:{port}"


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
    """Прячет credentials, оставляя только host:port — для логов.

    Режем по ПОСЛЕДНЕМУ '@': пароль может содержать '@', и при split('@')[1]
    в лог утекал кусок пароля вместо адреса.
    """
    if not proxy_string:
        return "None"
    if '@' in proxy_string:
        return proxy_string.rsplit('@', 1)[1]
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
