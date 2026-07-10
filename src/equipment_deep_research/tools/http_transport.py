from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import socket
import ssl
from typing import Mapping, Protocol
from urllib.parse import urlsplit


class HTTPStatusError(OSError):
    pass


class HTTPResponseTooLarge(OSError):
    pass


@dataclass(frozen=True)
class PinnedHTTPResponse:
    content: bytes
    headers: dict[str, str]
    status_code: int
    reason: str

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPStatusError(f"HTTP {self.status_code}: {self.reason}")


class HTTPTransport(Protocol):
    def get(
        self,
        *,
        url: str,
        connect_ip: str,
        hostname: str,
        port: int,
        timeout_seconds: int,
        headers: Mapping[str, str],
    ) -> PinnedHTTPResponse:
        ...


class PinnedHTTPTransport:
    def __init__(
        self,
        *,
        max_response_bytes: int = 5_242_880,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        context = ssl_context or ssl.create_default_context()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("TLS context must verify certificate hostnames")
        self.max_response_bytes = max_response_bytes
        self.ssl_context = context

    def get(
        self,
        *,
        url: str,
        connect_ip: str,
        hostname: str,
        port: int,
        timeout_seconds: int,
        headers: Mapping[str, str],
    ) -> PinnedHTTPResponse:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError(f"unsupported URL scheme: {scheme}")

        request_headers = dict(headers)
        request_headers["Host"] = _host_header(hostname, port=port, scheme=scheme)
        connection = _PinnedHTTPConnection(
            connect_ip=connect_ip,
            port=port,
            timeout_seconds=timeout_seconds,
            tls_hostname=hostname if scheme == "https" else None,
            ssl_context=self.ssl_context,
        )
        try:
            connection.request("GET", _request_target(url), headers=request_headers)
            response = connection.getresponse()
            content = response.read(self.max_response_bytes + 1)
            if len(content) > self.max_response_bytes:
                raise HTTPResponseTooLarge(
                    f"response exceeded {self.max_response_bytes} bytes"
                )
            return PinnedHTTPResponse(
                content=content,
                headers={name.lower(): value for name, value in response.getheaders()},
                status_code=response.status,
                reason=response.reason,
            )
        finally:
            connection.close()


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        *,
        connect_ip: str,
        port: int,
        timeout_seconds: int,
        tls_hostname: str | None,
        ssl_context: ssl.SSLContext,
    ) -> None:
        super().__init__(host=connect_ip, port=port, timeout=timeout_seconds)
        self._connect_ip = connect_ip
        self._tls_hostname = tls_hostname
        self._ssl_context = ssl_context

    def connect(self) -> None:
        raw_socket = _connect_numeric_ip(
            self._connect_ip,
            port=self.port,
            timeout_seconds=self.timeout,
        )
        if self._tls_hostname is None:
            self.sock = raw_socket
            return
        try:
            self.sock = self._ssl_context.wrap_socket(
                raw_socket,
                server_hostname=self._tls_hostname,
            )
        except Exception:
            raw_socket.close()
            raise


def _connect_numeric_ip(
    connect_ip: str,
    *,
    port: int,
    timeout_seconds: float | object,
) -> socket.socket:
    address = ipaddress.ip_address(connect_ip)
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout_seconds)
        sock.connect((connect_ip, port))
        return sock
    except Exception:
        sock.close()
        raise


def _request_target(url: str) -> str:
    parsed = urlsplit(url)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return target


def _host_header(hostname: str, *, port: int, scheme: str) -> str:
    formatted_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    if port == default_port:
        return formatted_host
    return f"{formatted_host}:{port}"
