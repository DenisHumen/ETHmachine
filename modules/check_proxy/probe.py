"""Низкоуровневые сетевые пробы — определяют, на какой стадии падает прокси.

Этапы:
    1. parse        — разбор URL и строки прокси.
    2. dns          — резолв хоста прокси.
    3. tcp_proxy    — TCP-коннект к прокси.
    4. proxy_auth   — HTTP CONNECT-запрос (для https-таргета) либо HTTP-запрос напрямую.
    5. tls_target   — TLS-handshake до целевого хоста (только https).
    6. request      — отправка HTTP-запроса.
    7. ttfb         — приём первого байта ответа.
    8. download     — приём тела ответа целиком.
"""

from __future__ import annotations

import socket
import ssl
import time
from base64 import b64encode
from dataclasses import dataclass, field
from typing import Optional, Tuple
from urllib.parse import urlparse, urlsplit


@dataclass
class StageTimings:
    """Тайминги каждого этапа в миллисекундах. None — этап не достигнут."""
    dns_ms: Optional[float] = None
    tcp_proxy_ms: Optional[float] = None
    proxy_connect_ms: Optional[float] = None  # время CONNECT-handshake к прокси
    tls_target_ms: Optional[float] = None
    request_ms: Optional[float] = None
    ttfb_ms: Optional[float] = None
    download_ms: Optional[float] = None
    total_ms: Optional[float] = None

    failed_stage: Optional[str] = None  # имя этапа, на котором всё умерло
    error: Optional[str] = None
    status_code: Optional[int] = None
    bytes_received: int = 0
    response_preview: str = ""
    response_headers: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "dns_ms": self.dns_ms,
            "tcp_proxy_ms": self.tcp_proxy_ms,
            "proxy_connect_ms": self.proxy_connect_ms,
            "tls_target_ms": self.tls_target_ms,
            "request_ms": self.request_ms,
            "ttfb_ms": self.ttfb_ms,
            "download_ms": self.download_ms,
            "total_ms": self.total_ms,
            "failed_stage": self.failed_stage,
            "error": self.error,
            "status_code": self.status_code,
            "bytes_received": self.bytes_received,
        }


def _parse_proxy_string(proxy: str) -> Optional[Tuple[str, int, Optional[str], Optional[str]]]:
    """user:pass@host:port или host:port → (host, port, user, pass)."""
    if not proxy:
        return None
    s = proxy.strip()
    for prefix in ("http://", "https://", "socks5://", "socks4://"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    user = pwd = None
    if "@" in s:
        auth, addr = s.rsplit("@", 1)
        if ":" in auth:
            user, pwd = auth.split(":", 1)
    else:
        addr = s
    if ":" not in addr:
        return None
    host, port_s = addr.rsplit(":", 1)
    try:
        port = int(port_s)
    except ValueError:
        return None
    return host, port, user, pwd


def _read_http_response(sock: socket.socket, max_bytes: int = 4096) -> Tuple[int, dict, bytes]:
    """Читает HTTP/1.1 заголовки. Возвращает (status, headers, body_chunk)."""
    buf = b""
    while b"\r\n\r\n" not in buf and len(buf) < 16384:
        chunk = sock.recv(2048)
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    if not lines:
        return 0, {}, b""
    try:
        status = int(lines[0].split(b" ", 2)[1])
    except Exception:
        status = 0
    headers = {}
    for ln in lines[1:]:
        if b":" in ln:
            k, _, v = ln.partition(b":")
            headers[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
    # читаем дальше до max_bytes для preview
    body = rest
    while len(body) < max_bytes:
        try:
            chunk = sock.recv(min(2048, max_bytes - len(body)))
        except socket.timeout:
            break
        if not chunk:
            break
        body += chunk
    return status, headers, body


def staged_probe(target_url: str, proxy: str, *, timeout: float = 12.0,
                 measure_download: bool = False) -> StageTimings:
    """Поэтапное измерение запроса через HTTP-прокси с CONNECT для HTTPS.

    Делает реальный поход к ``target_url`` через ``proxy`` и собирает тайминги
    каждой стадии плюс место поломки. Для http-целей CONNECT не используется.
    """
    t = StageTimings()
    overall_start = time.perf_counter()

    parsed = urlsplit(target_url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    proxy_parts = _parse_proxy_string(proxy)
    if not proxy_parts:
        t.failed_stage = "parse"
        t.error = "invalid proxy format"
        t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
        return t
    p_host, p_port, p_user, p_pwd = proxy_parts

    # 1. DNS
    try:
        dns_start = time.perf_counter()
        socket.getaddrinfo(p_host, p_port, proto=socket.IPPROTO_TCP)
        t.dns_ms = round((time.perf_counter() - dns_start) * 1000, 2)
    except Exception as e:
        t.failed_stage = "dns"
        t.error = f"DNS: {e!s}"[:240]
        t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
        return t

    sock: Optional[socket.socket] = None
    try:
        # 2. TCP до прокси
        tcp_start = time.perf_counter()
        sock = socket.create_connection((p_host, p_port), timeout=timeout)
        sock.settimeout(timeout)
        t.tcp_proxy_ms = round((time.perf_counter() - tcp_start) * 1000, 2)

        if scheme == "https":
            # 3. CONNECT к прокси
            connect_line = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            if p_user is not None:
                creds = b64encode(f"{p_user}:{p_pwd or ''}".encode()).decode()
                connect_line += f"Proxy-Authorization: Basic {creds}\r\n"
            connect_line += "\r\n"
            connect_start = time.perf_counter()
            sock.sendall(connect_line.encode("latin-1"))
            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 8192:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                buf += chunk
            t.proxy_connect_ms = round((time.perf_counter() - connect_start) * 1000, 2)
            try:
                status_line = buf.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
                code = int(status_line.split(" ", 2)[1])
            except Exception:
                code = 0
            if code != 200:
                t.failed_stage = "proxy_connect"
                t.status_code = code
                t.error = f"CONNECT failed: {status_line if buf else 'no response'}"[:240]
                t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
                return t

            # 4. TLS handshake
            tls_start = time.perf_counter()
            ctx = ssl.create_default_context()
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            sock = ctx.wrap_socket(sock, server_hostname=host)
            t.tls_target_ms = round((time.perf_counter() - tls_start) * 1000, 2)

            # 5. Отправка запроса
            req = (
                f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                "User-Agent: Mozilla/5.0 (ETHmachine ProxyChecker)\r\n"
                "Accept: */*\r\nConnection: close\r\n\r\n"
            )
        else:
            # HTTP без CONNECT — отправляем абсолютный URL
            abs_url = f"http://{host}:{port}{path}"
            req = (
                f"GET {abs_url} HTTP/1.1\r\nHost: {host}\r\n"
                "User-Agent: Mozilla/5.0 (ETHmachine ProxyChecker)\r\n"
                "Accept: */*\r\nConnection: close\r\n"
            )
            if p_user is not None:
                creds = b64encode(f"{p_user}:{p_pwd or ''}".encode()).decode()
                req += f"Proxy-Authorization: Basic {creds}\r\n"
            req += "\r\n"

        req_start = time.perf_counter()
        sock.sendall(req.encode("latin-1"))
        t.request_ms = round((time.perf_counter() - req_start) * 1000, 2)

        # 6. TTFB
        ttfb_start = time.perf_counter()
        first = sock.recv(2048)
        t.ttfb_ms = round((time.perf_counter() - ttfb_start) * 1000, 2)
        if not first:
            t.failed_stage = "ttfb"
            t.error = "empty response"
            t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
            return t

        # 7. Парсим заголовки + читаем тело
        head, _, rest = first.partition(b"\r\n\r\n")
        body = rest
        while b"\r\n\r\n" not in head and len(head) < 16384:
            more = sock.recv(2048)
            if not more:
                break
            head += more
        if b"\r\n\r\n" in head:
            head, _, rest = head.partition(b"\r\n\r\n")
            body += rest

        lines = head.split(b"\r\n")
        try:
            t.status_code = int(lines[0].split(b" ", 2)[1])
        except Exception:
            t.status_code = 0
        for ln in lines[1:]:
            if b":" in ln:
                k, _, v = ln.partition(b":")
                t.response_headers[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()

        if measure_download:
            dl_start = time.perf_counter()
            total = len(body)
            while True:
                try:
                    chunk = sock.recv(8192)
                except socket.timeout:
                    break
                if not chunk:
                    break
                total += len(chunk)
                if total >= 2 * 1024 * 1024:  # safety cap 2 МБ
                    break
            t.download_ms = round((time.perf_counter() - dl_start) * 1000, 2)
            t.bytes_received = total
        else:
            t.bytes_received = len(body)

        t.response_preview = body[:200].decode("latin-1", errors="replace")
        t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
        return t

    except socket.timeout:
        t.failed_stage = t.failed_stage or ("tcp_proxy" if t.tcp_proxy_ms is None else "request")
        t.error = "timeout"
        t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
        return t
    except ssl.SSLError as e:
        t.failed_stage = "tls_target"
        t.error = f"SSL: {e!s}"[:240]
        t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
        return t
    except ConnectionRefusedError:
        t.failed_stage = "tcp_proxy"
        t.error = "connection refused"
        t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
        return t
    except OSError as e:
        t.failed_stage = t.failed_stage or "tcp_proxy"
        t.error = f"OS: {e!s}"[:240]
        t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
        return t
    except Exception as e:
        t.failed_stage = t.failed_stage or "unknown"
        t.error = f"{type(e).__name__}: {e!s}"[:240]
        t.total_ms = round((time.perf_counter() - overall_start) * 1000, 2)
        return t
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
