from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import socket
from typing import Any

import pytest

from equipment_deep_research.domain.models import EvidenceCard
from equipment_deep_research.tools import http_transport
from equipment_deep_research.tools.http_transport import (
    HTTPResponseTooLarge,
    PinnedHTTPTransport,
)
from equipment_deep_research.tools.materialization import EvidenceMaterializer


@dataclass(frozen=True)
class _Response:
    content: bytes = b"ok"
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "text/plain"})
    status_code: int = 200
    reason: str = "OK"

    def raise_for_status(self) -> None:
        return None


class _RecordingTransport:
    def __init__(self, response: _Response | None = None) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if self.response is None:
            raise AssertionError("blocked address reached transport")
        return self.response


def _evidence(url: str) -> EvidenceCard:
    return EvidenceCard(
        evidence_id="ev-http-transport",
        source_title="HTTP transport test",
        source_url=url,
        source_tier="A",
        claim="test claim",
        excerpt="test excerpt",
        source_location="test:1",
        quality_assessment="test_quality",
        created_by="test_agent",
    )


@pytest.mark.parametrize(
    "address",
    [
        "fec0::1",
        "64:ff9b::7f00:1",
        "64:ff9b:1::7f00:1",
        "ff02::1",
        "::ffff:10.0.0.1",
        "::ffff:0:10.0.0.1",
        "2002:0a00:0001::",
        "2001:0000:4136:e378:8000:63bf:f5ff:fffe",
        "2001:4860::5efe:10.0.0.1",
        "2606:4700:4700::1111%25en0",
    ],
)
def test_special_ipv6_literal_is_rejected_before_transport(
    tmp_path: Path,
    address: str,
) -> None:
    transport = _RecordingTransport()
    materializer = EvidenceMaterializer(tmp_path, transport=transport)

    result = materializer.materialize(_evidence(f"http://[{address}]/"), mode="real")

    assert result.material["status"] == "network_safety_rejected"
    assert result.material["reason"] == "private_network_denied"
    assert transport.calls == []


@pytest.mark.parametrize(
    "address",
    [
        "fec0::1",
        "64:ff9b::7f00:1",
        "ff02::1",
        "::ffff:10.0.0.1",
        "::ffff:0:10.0.0.1",
        "2002:0a00:0001::",
    ],
)
def test_special_ipv6_dns_result_is_rejected_before_transport(
    tmp_path: Path,
    address: str,
) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, port, 0, 0))]

    transport = _RecordingTransport()
    materializer = EvidenceMaterializer(tmp_path, resolver=resolver, transport=transport)

    result = materializer.materialize(_evidence("https://blocked.example/"), mode="real")

    assert result.material["status"] == "network_safety_rejected"
    assert result.material["reason"] == "private_network_denied"
    assert transport.calls == []


@pytest.mark.parametrize(
    ("url", "connect_ip"),
    [
        ("https://93.184.216.34/", "93.184.216.34"),
        ("https://[2606:4700:4700::1111]/", "2606:4700:4700::1111"),
    ],
)
def test_public_unicast_literal_reaches_pinned_transport(
    tmp_path: Path,
    url: str,
    connect_ip: str,
) -> None:
    transport = _RecordingTransport(_Response())
    materializer = EvidenceMaterializer(tmp_path, transport=transport)

    result = materializer.materialize(_evidence(url), mode="real")

    assert result.material["status"] == "fetched"
    assert transport.calls[0]["connect_ip"] == connect_ip


def test_malformed_ipv6_url_is_isolated_as_one_diagnostic(tmp_path: Path) -> None:
    materializer = EvidenceMaterializer(tmp_path, transport=_RecordingTransport())

    result = materializer.materialize(_evidence("http://[2001:db8::1/"), mode="real")

    assert result.material["status"] == "network_safety_rejected"
    assert result.material["reason"] == "invalid_url"
    assert len(result.material["artifact_refs"]) == 1


def test_idna_hostname_is_normalized_for_resolver_and_transport(tmp_path: Path) -> None:
    resolver_hosts: list[tuple[str, int]] = []

    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        resolver_hosts.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = _RecordingTransport(_Response())
    materializer = EvidenceMaterializer(tmp_path, resolver=resolver, transport=transport)

    result = materializer.materialize(_evidence("https://täst.example/source"), mode="real")

    assert result.material["status"] == "fetched"
    assert resolver_hosts == [("xn--tst-qla.example", 443)]
    assert transport.calls[0]["hostname"] == "xn--tst-qla.example"


def test_invalid_idna_hostname_is_isolated_before_resolution(tmp_path: Path) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        raise AssertionError("invalid IDNA hostname must not be resolved")

    materializer = EvidenceMaterializer(
        tmp_path,
        resolver=resolver,
        transport=_RecordingTransport(),
    )

    result = materializer.materialize(
        _evidence(f"https://{'a' * 64}.example/source"),
        mode="real",
    )

    assert result.material["status"] == "network_safety_rejected"
    assert result.material["reason"] == "invalid_hostname"
    assert len(result.material["artifact_refs"]) == 1


def test_invalid_port_is_isolated_before_resolution(tmp_path: Path) -> None:
    materializer = EvidenceMaterializer(tmp_path, transport=_RecordingTransport())

    result = materializer.materialize(_evidence("https://example.com:not-a-port/"), mode="real")

    assert result.material["status"] == "network_safety_rejected"
    assert result.material["reason"] == "invalid_port"
    assert len(result.material["artifact_refs"]) == 1


@pytest.mark.parametrize(
    ("connect_ip", "expected_family"),
    [
        ("93.184.216.34", socket.AF_INET),
        ("2606:4700:4700::1111", socket.AF_INET6),
    ],
)
def test_numeric_connect_selects_address_family(
    monkeypatch: pytest.MonkeyPatch,
    connect_ip: str,
    expected_family: socket.AddressFamily,
) -> None:
    opened: list[tuple[int, int]] = []
    connected: list[tuple[str, int]] = []

    class FakeSocket:
        def settimeout(self, timeout: object) -> None:
            return None

        def connect(self, target: tuple[str, int]) -> None:
            connected.append(target)

        def close(self) -> None:
            return None

    def socket_factory(family: int, kind: int) -> FakeSocket:
        opened.append((family, kind))
        return FakeSocket()

    monkeypatch.setattr(http_transport.socket, "socket", socket_factory)

    result = http_transport._connect_numeric_ip(
        connect_ip,
        port=443,
        timeout_seconds=8,
    )

    assert isinstance(result, FakeSocket)
    assert opened == [(expected_family, socket.SOCK_STREAM)]
    assert connected == [(connect_ip, 443)]


def test_transport_sets_normalized_host_header_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str, dict[str, str]]] = []

    class FakeRawResponse:
        status = 200
        reason = "OK"

        def read(self, size: int) -> bytes:
            return b"ok"

        def getheaders(self) -> list[tuple[str, str]]:
            return [("Content-Type", "text/plain")]

    class FakeConnection:
        closed = False

        def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
            requests.append((method, target, headers))

        def getresponse(self) -> FakeRawResponse:
            return FakeRawResponse()

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(http_transport, "_PinnedHTTPConnection", lambda **kwargs: connection)

    response = PinnedHTTPTransport().get(
        url="https://xn--tst-qla.example:8443/path?q=1",
        connect_ip="93.184.216.34",
        hostname="xn--tst-qla.example",
        port=8443,
        timeout_seconds=8,
        headers={"User-Agent": "test"},
    )

    assert response.content == b"ok"
    assert requests == [
        (
            "GET",
            "/path?q=1",
            {"User-Agent": "test", "Host": "xn--tst-qla.example:8443"},
        )
    ]
    assert connection.closed is True


def test_ipv6_host_header_uses_brackets() -> None:
    assert http_transport._host_header(
        "2606:4700:4700::1111",
        port=8443,
        scheme="https",
    ) == "[2606:4700:4700::1111]:8443"


def test_oversized_response_raises_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRawResponse:
        status = 200
        reason = "OK"

        def read(self, size: int) -> bytes:
            return b"1234"

        def getheaders(self) -> list[tuple[str, str]]:
            return []

    class FakeConnection:
        closed = False

        def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
            return None

        def getresponse(self) -> FakeRawResponse:
            return FakeRawResponse()

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(http_transport, "_PinnedHTTPConnection", lambda **kwargs: connection)
    transport = PinnedHTTPTransport(max_response_bytes=3)

    with pytest.raises(HTTPResponseTooLarge, match="exceeded 3 bytes"):
        transport.get(
            url="https://example.com/large",
            connect_ip="93.184.216.34",
            hostname="example.com",
            port=443,
            timeout_seconds=8,
            headers={},
        )

    assert connection.closed is True
