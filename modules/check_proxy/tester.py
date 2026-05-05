"""Тестирование прокси на разных уровнях детализации."""

from __future__ import annotations

import json
import socket
import statistics
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .probe import staged_probe
from .services import (
    GEO_PROVIDERS, RpcEndpoint, SPEED_TEST, Service,
    rpcs_for_level, services_for_level,
)


# ──────────────────────────────────────────────────────────────────────────────
# Геолокация
# ──────────────────────────────────────────────────────────────────────────────

def _proxy_dict(proxy: str) -> Optional[Dict[str, str]]:
    if not proxy:
        return None
    s = proxy.strip()
    if not (s.startswith("http://") or s.startswith("https://")
            or s.startswith("socks5://") or s.startswith("socks4://")):
        s = "http://" + s
    return {"http": s, "https": s}


def get_geo(proxy: str, timeout: float = 10.0) -> Dict[str, Any]:
    pdict = _proxy_dict(proxy)
    if not pdict:
        return {}
    last_err = None
    for svc in GEO_PROVIDERS:
        try:
            r = requests.get(svc.url, proxies=pdict, timeout=timeout,
                             headers={"User-Agent": "Mozilla/5.0 (ETHmachine ProxyChecker)"})
            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    data = {}
                if not isinstance(data, dict):
                    continue
                # Унифицируем поля
                return {
                    "ip": data.get("ip") or data.get("query") or "",
                    "country": data.get("country_name") or data.get("country") or "",
                    "country_code": data.get("country_code") or data.get("countryCode") or "",
                    "region": data.get("region") or data.get("regionName") or "",
                    "city": data.get("city") or "",
                    "asn": data.get("asn") or data.get("org") or data.get("isp") or "",
                    "timezone": data.get("timezone") or "",
                    "hostname": data.get("hostname") or "",
                    "geo_source": svc.name,
                }
        except Exception as e:
            last_err = str(e)
            continue
    return {"geo_error": last_err or "all geo providers failed"}


# ──────────────────────────────────────────────────────────────────────────────
# Классификация HTTP-результата
# ──────────────────────────────────────────────────────────────────────────────

_BLOCKED_HINTS = (
    "access denied", "blocked", "forbidden", "geo", "region",
    "not available in your", "country", "restricted", "captcha",
)


def _classify(timings: Dict[str, Any], category: str) -> str:
    if timings.get("error"):
        e = (timings.get("error") or "").lower()
        if "timeout" in e:
            return "TIMEOUT"
        if "ssl" in e or "tls" in e or "certificate" in e:
            return "TLS_ERROR"
        if "refused" in e or "connect" in e and timings.get("failed_stage") in {"tcp_proxy", "dns"}:
            return "PROXY_DOWN"
        return "ERROR"
    code = timings.get("status_code") or 0
    preview = (timings.get("response_preview") or "").lower()
    if 200 <= code < 400:
        return "OK"
    if code in (403, 451):
        if any(h in preview for h in _BLOCKED_HINTS):
            return "BLOCKED"
        return "BLOCKED" if category in {"crypto_cex", "social"} else "HTTP_ERROR"
    if 400 <= code < 600:
        return "HTTP_ERROR"
    return "ERROR"


# ──────────────────────────────────────────────────────────────────────────────
# Тест отдельного сервиса
# ──────────────────────────────────────────────────────────────────────────────

def test_service(proxy: str, svc: Service, *, timeout: float = 12.0,
                 measure_download: bool = False) -> Dict[str, Any]:
    t = staged_probe(svc.url, proxy, timeout=timeout, measure_download=measure_download)
    raw = t.as_dict()
    # очищаем preview из БД (хранится только в details)
    status = _classify({**raw, "response_preview": t.response_preview}, svc.category)
    return {
        "category": svc.category,
        "name": svc.name,
        "url": svc.url,
        "status": status,
        "status_code": t.status_code,
        "latency_ms": t.total_ms,
        "dns_ms": t.dns_ms,
        "tcp_proxy_ms": t.tcp_proxy_ms,
        "proxy_connect_ms": t.proxy_connect_ms,
        "tls_target_ms": t.tls_target_ms,
        "ttfb_ms": t.ttfb_ms,
        "download_ms": t.download_ms,
        "bytes_received": t.bytes_received,
        "failed_stage": t.failed_stage,
        "error": t.error,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Тест RPC (eth_blockNumber / getHealth)
# ──────────────────────────────────────────────────────────────────────────────

def test_rpc(proxy: str, rpc: RpcEndpoint, timeout: float = 12.0) -> Dict[str, Any]:
    pdict = _proxy_dict(proxy)
    payload = (
        {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
        if rpc.kind == "evm"
        else {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
    )
    start = time.perf_counter()
    try:
        r = requests.post(
            rpc.url, json=payload, proxies=pdict, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (ETHmachine ProxyChecker)",
                     "Content-Type": "application/json"},
        )
        latency = round((time.perf_counter() - start) * 1000, 2)
        status = "OK"
        block_or_health: Any = None
        try:
            data = r.json()
            block_or_health = data.get("result")
            if rpc.kind == "evm" and isinstance(block_or_health, str) and block_or_health.startswith("0x"):
                block_or_health = int(block_or_health, 16)
            if block_or_health is None and "error" in data:
                status = "RPC_ERROR"
        except Exception:
            status = "ERROR"
        if r.status_code >= 400:
            status = "HTTP_ERROR"
        return {
            "category": "rpc",
            "name": f"{rpc.name} [{rpc.chain}]",
            "url": rpc.url,
            "status": status,
            "status_code": r.status_code,
            "latency_ms": latency,
            "dns_ms": None, "tcp_proxy_ms": None, "proxy_connect_ms": None,
            "tls_target_ms": None, "ttfb_ms": None, "download_ms": None,
            "bytes_received": len(r.content),
            "failed_stage": None,
            "error": None,
            "extra": {"block_or_health": block_or_health},
        }
    except requests.exceptions.Timeout:
        return _rpc_err(rpc, "timeout", "TIMEOUT", start)
    except requests.exceptions.ProxyError as e:
        return _rpc_err(rpc, f"proxy: {e!s}"[:240], "PROXY_DOWN", start)
    except requests.exceptions.SSLError as e:
        return _rpc_err(rpc, f"ssl: {e!s}"[:240], "TLS_ERROR", start)
    except requests.exceptions.ConnectionError as e:
        return _rpc_err(rpc, f"conn: {e!s}"[:240], "ERROR", start)
    except Exception as e:
        return _rpc_err(rpc, f"{type(e).__name__}: {e!s}"[:240], "ERROR", start)


def _rpc_err(rpc: RpcEndpoint, msg: str, status: str, start: float) -> Dict[str, Any]:
    return {
        "category": "rpc",
        "name": f"{rpc.name} [{rpc.chain}]",
        "url": rpc.url,
        "status": status,
        "status_code": 0,
        "latency_ms": round((time.perf_counter() - start) * 1000, 2),
        "dns_ms": None, "tcp_proxy_ms": None, "proxy_connect_ms": None,
        "tls_target_ms": None, "ttfb_ms": None, "download_ms": None,
        "bytes_received": 0,
        "failed_stage": "request",
        "error": msg,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Speed-test и jitter (только L4)
# ──────────────────────────────────────────────────────────────────────────────

def speed_test(proxy: str, timeout: float = 30.0) -> Dict[str, Any]:
    t = staged_probe(SPEED_TEST.url, proxy, timeout=timeout, measure_download=True)
    if t.error or not t.bytes_received:
        return {"download_kbps": 0.0, "bytes": t.bytes_received, "error": t.error}
    elapsed = (t.download_ms or 1) / 1000.0
    kbps = (t.bytes_received * 8) / 1000.0 / max(elapsed, 0.001)
    return {"download_kbps": round(kbps, 2), "bytes": t.bytes_received, "error": None}


def jitter_test(proxy: str, samples: int = 3) -> Dict[str, Any]:
    times = []
    for _ in range(samples):
        t = staged_probe("https://www.cloudflare.com/cdn-cgi/trace", proxy, timeout=8.0)
        if t.total_ms is not None and not t.error:
            times.append(t.total_ms)
    if len(times) < 2:
        return {"jitter_ms": None, "samples": times}
    return {
        "jitter_ms": round(statistics.pstdev(times), 2),
        "min_ms": round(min(times), 2),
        "max_ms": round(max(times), 2),
        "avg_ms": round(statistics.mean(times), 2),
        "samples": times,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Главная функция проверки одного прокси
# ──────────────────────────────────────────────────────────────────────────────

def run_proxy_test(proxy: str, level: int) -> Dict[str, Any]:
    """Возвращает summary словарь, готовый для записи в БД."""
    summary: Dict[str, Any] = {
        "proxy": proxy,
        "level": level,
        "service_results": [],
        "details": {},
    }

    # 1. Уровень 1 — базовый: только geo + один alive-пробинг
    geo = get_geo(proxy)
    summary["ip"] = geo.get("ip", "")
    summary["country"] = geo.get("country", "")
    summary["city"] = geo.get("city", "")
    summary["asn"] = geo.get("asn", "")
    summary["details"]["geo"] = geo

    if level >= 1:
        # alive ping — Cloudflare trace (быстрый)
        alive = staged_probe("https://www.cloudflare.com/cdn-cgi/trace", proxy, timeout=10.0)
        summary["details"]["alive_probe"] = alive.as_dict()
        summary["alive"] = alive.status_code is not None and 200 <= (alive.status_code or 0) < 400
        if alive.error and alive.status_code is None:
            summary["alive"] = False
        summary["failed_stage"] = alive.failed_stage
        summary["error"] = alive.error

    # 2. Уровень 2-4 — сервисы
    services = services_for_level(level)
    for svc in services:
        res = test_service(proxy, svc, timeout=10.0)
        summary["service_results"].append(res)

    # 3. Уровень 3-4 — RPC
    for rpc in rpcs_for_level(level):
        res = test_rpc(proxy, rpc, timeout=12.0)
        summary["service_results"].append(res)

    # 4. Уровень 4 — speed + jitter
    if level >= 4:
        sp = speed_test(proxy, timeout=25.0)
        jt = jitter_test(proxy, samples=4)
        summary["download_kbps"] = sp.get("download_kbps")
        summary["jitter_ms"] = jt.get("jitter_ms")
        summary["details"]["speed_test"] = sp
        summary["details"]["jitter_test"] = jt

    # 5. Сводка
    ok = sum(1 for r in summary["service_results"] if r["status"] == "OK")
    blocked = sum(1 for r in summary["service_results"] if r["status"] == "BLOCKED")
    err = sum(1 for r in summary["service_results"] if r["status"] not in {"OK", "BLOCKED"})
    total = len(summary["service_results"]) or 1
    score = (ok / total) * 100 if summary["service_results"] else (100.0 if summary.get("alive") else 0.0)
    summary["score"] = round(score, 2)
    summary["ok_count"] = ok
    summary["blocked_count"] = blocked
    summary["error_count"] = err
    summary["total_count"] = total

    # Среднее latency только по OK
    lats = [r["latency_ms"] for r in summary["service_results"]
            if r.get("status") == "OK" and r.get("latency_ms")]
    if lats:
        summary["avg_latency"] = round(statistics.mean(lats), 2)
    elif summary.get("details", {}).get("alive_probe", {}).get("total_ms"):
        summary["avg_latency"] = summary["details"]["alive_probe"]["total_ms"]
    else:
        summary["avg_latency"] = None

    # Список заблокированных сервисов
    summary["blocked_list"] = [r["name"] for r in summary["service_results"] if r["status"] == "BLOCKED"]
    summary["failed_services"] = [r["name"] for r in summary["service_results"]
                                  if r["status"] not in {"OK", "BLOCKED"}]

    # Финальный статус
    if not summary.get("alive", True) and not summary["service_results"]:
        summary["overall"] = "BROKEN"
    elif score >= 70:
        summary["overall"] = "WORKING"
    elif score > 0 or summary.get("alive"):
        summary["overall"] = "PARTIAL"
    else:
        summary["overall"] = "BROKEN"

    return summary
