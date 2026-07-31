from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
import socket
from typing import Any

import pytest

from equipment_deep_research.domain.models import EvidenceCard
from equipment_deep_research.tools import http_transport
from equipment_deep_research.tools.http_transport import (
    HTTPStatusError,
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


class _ReaderFallbackTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise OSError("HTTP 403: Forbidden")
        return _Response(
            content=(
                b"Title: Public capability report\n\n"
                b"This public report provides independently retrievable source material "
                b"with enough detail to support the test claim and preserve provenance "
                b"when the origin server rejects automated retrieval. The material also "
                b"records the retrieval route, original URL, source identity, and a stable "
                b"paragraph location for later audit and independent verification."
            ),
            headers={"content-type": "text/plain; charset=utf-8"},
        )


class _ReaderRetryTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if len(self.calls) <= 2:
            raise OSError("transient reader failure")
        return _Response(
            content=(
                b"Title: Retry success\n\n"
                b"This retried public reader response contains enough independently "
                b"retrievable text to support evidence materialization and a stable "
                b"paragraph location after a transient upstream failure."
            ),
            headers={"content-type": "text/plain; charset=utf-8"},
        )


class _HardDeniedTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        raise HTTPStatusError("HTTP 403: Forbidden")


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


def test_benchmark_dns_proxy_requires_explicit_opt_in(tmp_path: Path) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.1.25", port))]

    blocked_transport = _RecordingTransport()
    blocked = EvidenceMaterializer(
        tmp_path / "blocked",
        resolver=resolver,
        transport=blocked_transport,
        allow_benchmark_dns_proxy=False,
    ).materialize(_evidence("https://public.example/report"), mode="real")
    assert blocked.material["status"] == "network_safety_rejected"
    assert blocked_transport.calls == []

    allowed_transport = _RecordingTransport(_Response())
    allowed = EvidenceMaterializer(
        tmp_path / "allowed",
        resolver=resolver,
        transport=allowed_transport,
        allow_benchmark_dns_proxy=True,
    ).materialize(_evidence("https://public.example/report"), mode="real")
    assert allowed.material["status"] == "fetched"
    assert allowed_transport.calls[0]["connect_ip"] == "198.18.1.25"
    assert allowed_transport.calls[0]["hostname"] == "public.example"


def test_benchmark_proxy_opt_in_never_allows_http_or_literal_ip(tmp_path: Path) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.1.25", port))]

    transport = _RecordingTransport()
    materializer = EvidenceMaterializer(
        tmp_path,
        resolver=resolver,
        transport=transport,
        allow_benchmark_dns_proxy=True,
    )
    http_result = materializer.materialize(
        _evidence("http://public.example/report"), mode="real"
    )
    literal_result = materializer.materialize(
        _evidence("https://198.18.1.25/report"), mode="real"
    )
    assert http_result.material["status"] == "network_safety_rejected"
    assert literal_result.material["status"] == "network_safety_rejected"
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


def test_html_materialization_replaces_search_snippet_with_located_page_excerpt(
    tmp_path: Path,
) -> None:
    html = b"""
    <html><head><title>Capability Report</title></head><body><main>
      <p>General introduction with enough words to remain in the simplified page.</p>
      <p>test claim describes the decisive capability constraint and verified parameter.</p>
    </main></body></html>
    """
    transport = _RecordingTransport(
        _Response(content=html, headers={"content-type": "text/html; charset=utf-8"})
    )
    materializer = EvidenceMaterializer(tmp_path, transport=transport)

    result = materializer.materialize(
        _evidence("https://93.184.216.34/report"), mode="real"
    )

    assert result.evidence.source_title == "Capability Report"
    assert "decisive capability constraint" in result.evidence.excerpt
    assert "#p2" in result.evidence.source_location
    assert result.material["simplified_artifact_ref"]


def test_materializer_deduplicates_same_url_across_concurrent_agents(
    tmp_path: Path,
) -> None:
    transport = _RecordingTransport(_Response())
    materializer = EvidenceMaterializer(tmp_path, transport=transport)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _: materializer.materialize(
                    _evidence("https://93.184.216.34/shared-report"),
                    mode="real",
                ),
                range(4),
            )
        )

    assert len(transport.calls) == 1
    assert sum(bool(item.material["fetch_cache_hit"]) for item in results) == 3


def test_public_reader_fallback_materializes_origin_that_rejects_direct_fetch(
    tmp_path: Path,
) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = _ReaderFallbackTransport()
    result = EvidenceMaterializer(
        tmp_path,
        resolver=resolver,
        transport=transport,
        public_reader_base_url="https://reader.example/http://",
    ).materialize(_evidence("https://blocked.example/report"), mode="real")

    assert result.material["status"] == "reader_fetched"
    assert result.material["formal_evidence_allowed"] is True
    assert result.evidence.source_url == "https://blocked.example/report"
    assert result.evidence.artifact_refs
    assert transport.calls[1]["url"] == (
        "https://reader.example/http://blocked.example/report"
    )


def test_reader_skips_navigation_boilerplate_and_uses_article_paragraph(
    tmp_path: Path,
) -> None:
    class _NavigationReaderTransport:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, **kwargs: Any) -> _Response:
            del kwargs
            self.calls += 1
            if self.calls == 1:
                raise OSError("HTTP 403: Forbidden")
            return _Response(
                content=(
                    b"Title: Capability article\n\n"
                    b"* [Introduction](https://example.org/intro) * [Available add-ons]"
                    b"(https://example.org/addons) * [Back button](https://example.org/back) "
                    b"* [Keyboard navigation](https://example.org/keyboard) * [Sidebar]"
                    b"(https://example.org/sidebar)\n\n"
                    b"The verified capability article explains the operational constraint, "
                    b"the measured parameter, the test conditions, and the integration boundary "
                    b"needed to support the claim with a stable and auditable source paragraph."
                )
            )

    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        del host, kwargs
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    result = EvidenceMaterializer(
        tmp_path,
        resolver=resolver,
        transport=_NavigationReaderTransport(),
        public_reader_base_url="https://reader.example/http://",
    ).materialize(_evidence("https://blocked.example/report"), mode="real")

    assert result.material["status"] == "reader_fetched"
    assert result.evidence.excerpt.startswith("The verified capability article")
    assert "Available add-ons" not in result.evidence.excerpt


def test_http_200_error_shell_falls_back_to_hosted_search_citation(
    tmp_path: Path,
) -> None:
    html = b"""
    <html><head><title>Application error</title></head><body><main>
      <p>An error occurred in the application and your page could not be served.
      If you are the application owner, check your logs for details.</p>
    </main></body></html>
    """
    evidence = EvidenceCard(
        **{
            **_evidence("https://93.184.216.34/error").__dict__,
            "quality_assessment": "responses_web_search_source",
        }
    )
    result = EvidenceMaterializer(
        tmp_path,
        transport=_RecordingTransport(
            _Response(content=html, headers={"content-type": "text/html"})
        ),
        public_reader_base_url="",
    ).materialize(evidence, mode="real")

    assert result.material["status"] == "hosted_search_citation"
    assert result.material["formal_evidence_allowed"] is True
    assert result.evidence.excerpt == "test excerpt"


def test_public_reader_retries_one_transient_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_PUBLIC_READER_ATTEMPTS", "2")

    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = _ReaderRetryTransport()
    result = EvidenceMaterializer(
        tmp_path,
        resolver=resolver,
        transport=transport,
        public_reader_base_url="https://reader.example/http://",
    ).materialize(_evidence("https://blocked.example/report"), mode="real")

    assert result.material["status"] == "reader_fetched"
    assert result.material["reader_attempt"] == 2
    assert len(transport.calls) == 3


def test_failed_public_reader_returns_auditable_diagnostic_instead_of_none(
    tmp_path: Path,
) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    result = EvidenceMaterializer(
        tmp_path,
        resolver=resolver,
        transport=_RecordingTransport(),
        public_reader_base_url="https://reader.example/http://",
    ).materialize(_evidence("https://blocked.example/report"), mode="real")

    assert result.material["status"] == "fetch_failed"
    assert result.material["formal_evidence_allowed"] is False
    assert result.evidence.artifact_refs


@pytest.mark.parametrize(
    "quality_marker",
    ["responses_web_search_source", "codex_web_search_source"],
)
def test_hosted_search_citation_is_materialized_when_origin_and_reader_fail(
    tmp_path: Path,
    quality_marker: str,
) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    evidence = EvidenceCard(
        **{
            **_evidence("https://blocked.example/report").__dict__,
            "source_title": "Hosted Search Equipment Report",
            "quality_assessment": quality_marker,
        }
    )
    result = EvidenceMaterializer(
        tmp_path,
        resolver=resolver,
        transport=_RecordingTransport(),
        public_reader_base_url="https://reader.example/http://",
    ).materialize(evidence, mode="real")

    assert result.material["status"] == "hosted_search_citation"
    assert result.material["formal_evidence_allowed"] is True
    assert result.evidence.source_url == "https://blocked.example/report"
    assert result.evidence.source_location.endswith("#citation")


def test_hosted_codex_citation_allows_gateway_url_as_missing_title(
    tmp_path: Path,
) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    url = "https://blocked.example/report"
    evidence = EvidenceCard(
        **{
            **_evidence(url).__dict__,
            "source_title": url,
            "quality_assessment": "codex_web_search_source",
        }
    )
    result = EvidenceMaterializer(
        tmp_path,
        resolver=resolver,
        transport=_RecordingTransport(),
        public_reader_base_url="https://reader.example/http://",
    ).materialize(evidence, mode="real")

    assert result.material["status"] == "hosted_search_citation"
    assert result.material["formal_evidence_allowed"] is True


def test_prefetch_caches_hard_origin_denial_for_later_hosted_fallback(
    tmp_path: Path,
) -> None:
    def resolver(host: str, port: int, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    transport = _HardDeniedTransport()
    materializer = EvidenceMaterializer(
        tmp_path,
        resolver=resolver,
        transport=transport,
        public_reader_base_url="",
    )
    url = "https://blocked.example/report"

    warm = materializer.prefetch_url(url)
    evidence = EvidenceCard(
        **{
            **_evidence(url).__dict__,
            "source_title": "Blocked official report",
            "quality_assessment": "codex_web_search_source",
        }
    )
    result = materializer.materialize(evidence, mode="real")

    assert warm["status"] == "fetch_blocked"
    assert result.material["status"] == "hosted_search_citation"
    assert len(transport.calls) == 1


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
