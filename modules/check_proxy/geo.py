"""Геолокация прокси с агрегированием нескольких провайдеров.

Стратегия:
    Поочерёдно опрашиваем 5+ провайдеров. Результаты *сливаем* — каждое поле
    заполняется первым непустым значением. После агрегата нормализуем страну
    (полное имя из ISO-кода, если провайдер вернул только код).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from modules.simple_logger import logger
from .country_codes import COUNTRY_NAMES


_HEADERS = {"User-Agent": "Mozilla/5.0 (ETHmachine ProxyChecker)"}

# (name, url, parser_key)
# parser_key вызывает _parse_<key> ниже.
_PROVIDERS: List[tuple] = [
    ("ip-api.com",  "http://ip-api.com/json/?fields=66846719",        "ipapi_com"),
    ("ipwho.is",    "https://ipwho.is/",                              "ipwho"),
    ("ipapi.co",    "https://ipapi.co/json/",                         "ipapi_co"),
    ("ipinfo.io",   "https://ipinfo.io/json",                         "ipinfo"),
    ("ip-api.io",   "https://api.iplocation.net/?ip=",                "iplocation"),
    ("ifconfig",    "https://ifconfig.co/json",                       "ifconfig"),
    ("ipify",       "https://api.ipify.org?format=json",              "ipify"),
]


def _proxies(proxy: str) -> Dict[str, str]:
    s = proxy.strip()
    if not (s.startswith("http://") or s.startswith("https://")
            or s.startswith("socks5://") or s.startswith("socks4://")):
        s = "http://" + s
    return {"http": s, "https": s}


def _empty() -> Dict[str, Any]:
    return {
        "ip": "", "country": "", "country_code": "", "region": "", "city": "",
        "asn": "", "timezone": "", "hostname": "", "geo_sources": [],
    }


def _merge(into: Dict[str, Any], extra: Dict[str, Any]) -> None:
    for k, v in extra.items():
        if k == "geo_sources":
            into.setdefault("geo_sources", [])
            for s in v:
                if s and s not in into["geo_sources"]:
                    into["geo_sources"].append(s)
            continue
        if v in (None, "", "None"):
            continue
        if not into.get(k):
            into[k] = v


# ───────────────────────────────────────────── parsers ──

def _parse_ipapi_com(d: dict, src: str) -> Dict[str, Any]:
    if d.get("status") != "success" and d.get("query") is None:
        return {}
    return {
        "ip": d.get("query"),
        "country": d.get("country"),                # full name
        "country_code": d.get("countryCode"),
        "region": d.get("regionName") or d.get("region"),
        "city": d.get("city"),
        "asn": " ".join(filter(None, [d.get("as"), d.get("org"), d.get("isp")])).strip(),
        "timezone": d.get("timezone"),
        "hostname": d.get("reverse"),
        "geo_sources": [src],
    }


def _parse_ipwho(d: dict, src: str) -> Dict[str, Any]:
    if not d.get("success", True) or not d.get("ip"):
        return {}
    conn = d.get("connection") or {}
    return {
        "ip": d.get("ip"),
        "country": d.get("country"),
        "country_code": d.get("country_code"),
        "region": d.get("region"),
        "city": d.get("city"),
        "asn": " ".join(filter(None, [
            f"AS{conn.get('asn')}" if conn.get("asn") else "",
            conn.get("org") or conn.get("isp") or "",
        ])).strip(),
        "timezone": (d.get("timezone") or {}).get("id") if isinstance(d.get("timezone"), dict) else d.get("timezone"),
        "hostname": "",
        "geo_sources": [src],
    }


def _parse_ipapi_co(d: dict, src: str) -> Dict[str, Any]:
    if d.get("error"):
        return {}
    return {
        "ip": d.get("ip"),
        "country": d.get("country_name"),
        "country_code": d.get("country_code") or d.get("country"),
        "region": d.get("region"),
        "city": d.get("city"),
        "asn": " ".join(filter(None, [d.get("asn"), d.get("org")])).strip(),
        "timezone": d.get("timezone"),
        "hostname": "",
        "geo_sources": [src],
    }


def _parse_ipinfo(d: dict, src: str) -> Dict[str, Any]:
    if d.get("error"):
        return {}
    return {
        "ip": d.get("ip"),
        "country": "",                       # 2-буквенный — оставим маппингу
        "country_code": d.get("country"),
        "region": d.get("region"),
        "city": d.get("city"),
        "asn": d.get("org") or "",
        "timezone": d.get("timezone"),
        "hostname": d.get("hostname"),
        "geo_sources": [src],
    }


def _parse_iplocation(d: dict, src: str) -> Dict[str, Any]:
    if not d.get("ip"):
        return {}
    return {
        "ip": d.get("ip"),
        "country": d.get("country_name"),
        "country_code": d.get("country_code2"),
        "asn": d.get("isp") or "",
        "geo_sources": [src],
    }


def _parse_ifconfig(d: dict, src: str) -> Dict[str, Any]:
    if not d.get("ip"):
        return {}
    return {
        "ip": d.get("ip"),
        "country": d.get("country"),
        "country_code": d.get("country_iso"),
        "region": d.get("region_name"),
        "city": d.get("city"),
        "asn": " ".join(filter(None, [
            f"AS{d.get('asn')}" if d.get("asn") else "",
            d.get("asn_org") or "",
        ])).strip(),
        "timezone": d.get("time_zone"),
        "hostname": d.get("hostname"),
        "geo_sources": [src],
    }


def _parse_ipify(d: dict, src: str) -> Dict[str, Any]:
    if not d.get("ip"):
        return {}
    return {"ip": d.get("ip"), "geo_sources": [src]}


_PARSERS = {
    "ipapi_com": _parse_ipapi_com,
    "ipwho":     _parse_ipwho,
    "ipapi_co":  _parse_ipapi_co,
    "ipinfo":    _parse_ipinfo,
    "iplocation": _parse_iplocation,
    "ifconfig":  _parse_ifconfig,
    "ipify":     _parse_ipify,
}


def _query(proxy_url: str, name: str, url: str, key: str,
           ip_hint: Optional[str], timeout: float) -> Dict[str, Any]:
    full_url = url + (ip_hint if (key == "iplocation" and ip_hint) else "")
    try:
        r = requests.get(full_url, proxies=_proxies(proxy_url), timeout=timeout, headers=_HEADERS)
        if r.status_code != 200:
            return {}
        try:
            data = r.json()
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return _PARSERS[key](data, name)
    except Exception:
        return {}


def lookup_geo(proxy: str, *, timeout: float = 8.0,
               full_when: int = 5,
               retries: int = 1) -> Dict[str, Any]:
    """Возвращает максимально полную сводку. Опрашивает провайдеров,
    пока не заполнятся все ключевые поля или не закончатся источники.

    Args:
        full_when: после N успешных провайдеров останавливаемся, если все
            ключевые поля (ip, country, city, asn) заполнены.
        retries: количество дополнительных проходов по упавшим провайдерам.
    """
    result = _empty()
    needed = ("ip", "country", "city", "asn")

    def _all_filled() -> bool:
        return all(result.get(k) for k in needed)

    failed: List[tuple] = []
    success_n = 0
    for name, url, key in _PROVIDERS:
        partial = _query(proxy, name, url, key,
                         ip_hint=result.get("ip"), timeout=timeout)
        if partial:
            _merge(result, partial)
            success_n += 1
            if success_n >= full_when and _all_filled():
                break
        else:
            failed.append((name, url, key))

    # Повторные попытки только для упавших источников (на случай транзиентной сети).
    for _ in range(max(0, retries)):
        if _all_filled():
            break
        next_failed: List[tuple] = []
        for name, url, key in failed:
            partial = _query(proxy, name, url, key,
                             ip_hint=result.get("ip"), timeout=timeout)
            if partial:
                _merge(result, partial)
            else:
                next_failed.append((name, url, key))
        failed = next_failed

    # Нормализация: если у нас есть code, но нет полного country — резолвим из таблицы.
    code = (result.get("country_code") or "").upper()
    country = (result.get("country") or "").strip()
    if code and (not country or len(country) == 2):
        full = COUNTRY_NAMES.get(code)
        if full:
            result["country"] = full
    elif country and not code:
        # обратный поиск по имени
        rev = {v.lower(): k for k, v in COUNTRY_NAMES.items()}
        result["country_code"] = rev.get(country.lower(), "")

    if not result.get("country") and not result.get("ip"):
        logger.warning(f"⚠️  Geo: не удалось определить локацию для {_mask(proxy)}")

    return result


def _mask(p: str) -> str:
    return p.split("@", 1)[1] if "@" in p else p
