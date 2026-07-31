from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import socket
from threading import BoundedSemaphore, RLock
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from equipment_deep_research.domain.models import EvidenceCard
from equipment_deep_research.tools.artifacts import SecureArtifactStore
from equipment_deep_research.tools.http_transport import (
    HTTPStatusError,
    HTTPTransport,
    PinnedHTTPTransport,
)
from equipment_deep_research.tools.simplify import simplify_html


@dataclass(frozen=True)
class MaterializedEvidence:
    evidence: EvidenceCard
    material: dict[str, Any]


@dataclass(frozen=True)
class _ResolvedTarget:
    hostname: str
    port: int
    connect_ip: str


@dataclass(frozen=True)
class _ParsedNetworkURL:
    scheme: str
    hostname: str
    port: int


@dataclass(frozen=True)
class _FetchedPublicPage:
    content: bytes
    content_type: str
    final_url: str
    connect_ip: str


class _NetworkSafetyError(OSError):
    def __init__(self, reason: str, rejected_url: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.rejected_url = rejected_url


_IPV4_SHARED_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_IPV4_BENCHMARK_DNS_PROXY = ipaddress.ip_network("198.18.0.0/15")
_IPV4_TRANSLATED_NETWORK = ipaddress.ip_network("::ffff:0:0:0/96")
_NAT64_WELL_KNOWN_NETWORK = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL_USE_NETWORK = ipaddress.ip_network("64:ff9b:1::/48")


class EvidenceMaterializer:
    def __init__(
        self,
        artifact_dir: str | Path | None = None,
        *,
        artifact_store: SecureArtifactStore | None = None,
        timeout_seconds: int = 8,
        max_redirects: int = 5,
        resolver: Callable[..., list[tuple[Any, ...]]] | None = None,
        transport: HTTPTransport | None = None,
        allow_benchmark_dns_proxy: bool | None = None,
        public_reader_base_url: str | None = None,
    ) -> None:
        if artifact_store is not None and artifact_dir is not None:
            raise ValueError("provide artifact_dir or artifact_store, not both")
        if artifact_store is None:
            if artifact_dir is None:
                raise ValueError("artifact_dir is required")
            artifact_store = SecureArtifactStore(artifact_dir)
        self.artifacts = artifact_store
        self.timeout_seconds = max(
            1,
            int(
                os.environ.get(
                    "EQUIPMENT_DR_EVIDENCE_FETCH_TIMEOUT_SECONDS",
                    timeout_seconds,
                )
            ),
        )
        self.public_reader_timeout_seconds = max(
            self.timeout_seconds,
            int(
                os.environ.get(
                    "EQUIPMENT_DR_PUBLIC_READER_TIMEOUT_SECONDS",
                    20,
                )
            ),
        )
        self.max_redirects = max_redirects
        self.resolver = resolver or socket.getaddrinfo
        self.transport = transport or PinnedHTTPTransport()
        self.allow_benchmark_dns_proxy = (
            os.environ.get("EQUIPMENT_DR_ALLOW_BENCHMARK_DNS_PROXY", "0") == "1"
            if allow_benchmark_dns_proxy is None
            else allow_benchmark_dns_proxy
        )
        self.public_reader_base_url = (
            os.environ.get("EQUIPMENT_DR_PUBLIC_READER_BASE_URL", "").strip()
            if public_reader_base_url is None
            else public_reader_base_url.strip()
        )
        self._fetch_slots = BoundedSemaphore(
            max(
                1,
                int(
                    os.environ.get(
                        "EQUIPMENT_DR_EVIDENCE_GLOBAL_CONCURRENCY",
                        "8",
                    )
                ),
            )
        )
        self._fetch_cache: dict[str, _FetchedPublicPage] = {}
        self._fetch_failure_cache: dict[str, str] = {}
        self._fetch_inflight: dict[str, Future[_FetchedPublicPage]] = {}
        self._fetch_cache_lock = RLock()
        self._reader_slots = BoundedSemaphore(
            max(
                1,
                int(
                    os.environ.get(
                        "EQUIPMENT_DR_PUBLIC_READER_CONCURRENCY",
                        "3",
                    )
                ),
            )
        )
        self._reader_failures: dict[str, str] = {}
        self._reader_origin_failures: dict[str, str] = {}
        self._reader_failure_lock = RLock()

    def close(self) -> None:
        self.artifacts.close()

    def __enter__(self) -> "EvidenceMaterializer":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def materialize(self, evidence: EvidenceCard, *, mode: str) -> MaterializedEvidence:
        parsed, rejection_reason = _parse_network_url(evidence.source_url)
        if rejection_reason:
            return self._reject_network_safety(
                evidence=evidence,
                mode=mode,
                reason=rejection_reason,
            )
        assert parsed is not None
        if parsed.hostname == "fixture.local":
            if mode == "fake":
                return self._materialize_fixture(evidence=evidence, mode=mode)
            return self._reject_network_safety(
                evidence=evidence,
                mode=mode,
                reason="fixture_only_allowed_in_fake_mode",
            )
        return self._materialize_public_url(evidence=evidence, mode=mode)

    def prefetch_url(self, source_url: str) -> dict[str, Any]:
        """Warm the safe origin cache while model analysis runs in parallel."""
        parsed, rejection_reason = _parse_network_url(source_url)
        if rejection_reason or parsed is None:
            return {"url": source_url, "status": "rejected"}
        try:
            _, cache_hit = self._fetch_public_page(source_url)
            return {
                "url": source_url,
                "status": "cached" if cache_hit else "fetched",
            }
        except Exception as exc:
            return {
                "url": source_url,
                "status": "fetch_blocked" if _is_hard_access_failure(exc) else "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _reject_network_safety(
        self,
        *,
        evidence: EvidenceCard,
        mode: str,
        reason: str,
        rejected_url: str | None = None,
    ) -> MaterializedEvidence:
        rejected_url = rejected_url or evidence.source_url
        diagnostic = (
            f"network_safety_rejected\nurl={evidence.source_url}\n"
            f"rejected_url={rejected_url}\n"
            f"reason={reason}\n"
            "该地址未通过网络安全校验，诊断材料不进入正式证据集。\n"
        )
        ref = self.artifacts.put(
            diagnostic,
            kind="text",
            meta={
                "url": evidence.source_url,
                "content_type": "text/plain",
                "materialization_status": "network_safety_rejected",
                "evidence_id": evidence.evidence_id,
                "mode": mode,
                "reason": reason,
                "rejected_url": rejected_url,
            },
        )
        updated = EvidenceCard(
            **{
                **evidence.__dict__,
                "artifact_refs": [*evidence.artifact_refs, ref],
                "quality_assessment": f"{evidence.quality_assessment}; network_safety_rejected",
            }
        )
        return MaterializedEvidence(
            evidence=updated,
            material={
                "evidence_id": evidence.evidence_id,
                "status": "network_safety_rejected",
                "artifact_refs": [ref],
                "url": evidence.source_url,
                "reason": reason,
                "rejected_url": rejected_url,
                "formal_evidence_allowed": False,
            },
        )

    def _materialize_fixture(self, *, evidence: EvidenceCard, mode: str) -> MaterializedEvidence:
        text = (
            f"来源：{evidence.source_title}\n"
            f"URL：{evidence.source_url}\n"
            f"claim：{evidence.claim}\n"
            f"excerpt：{evidence.excerpt}\n"
            f"mode：{mode}\n"
        )
        ref = self.artifacts.put(
            text,
            kind="text",
            meta={
                "url": evidence.source_url,
                "content_type": "text/plain",
                "materialization_status": "fixture_materialized",
                "evidence_id": evidence.evidence_id,
            },
        )
        updated = EvidenceCard(
            **{
                **evidence.__dict__,
                "artifact_refs": [*evidence.artifact_refs, ref],
                "quality_assessment": f"{evidence.quality_assessment}; materialized",
            }
        )
        return MaterializedEvidence(
            evidence=updated,
            material={
                "evidence_id": evidence.evidence_id,
                "status": "fixture_materialized",
                "artifact_refs": [ref],
                "url": evidence.source_url,
                "formal_evidence_allowed": True,
            },
        )

    def _materialize_public_url(self, *, evidence: EvidenceCard, mode: str) -> MaterializedEvidence:
        try:
            page, cache_hit = self._fetch_public_page(evidence.source_url)
            raw_ref = self.artifacts.put(
                page.content,
                kind=(
                    "html"
                    if "html" in page.content_type.lower()
                    else "raw"
                ),
                meta={
                    "url": evidence.source_url,
                    "content_type": page.content_type,
                    "materialization_status": "fetched",
                    "evidence_id": evidence.evidence_id,
                    "mode": mode,
                    "final_url": page.final_url,
                    "connect_ip": page.connect_ip,
                    "fetch_cache_hit": cache_hit,
                },
            )
            simplified_ref = ""
            paragraph_locations: list[str] = []
            extracted_excerpt = evidence.excerpt
            extracted_location = evidence.source_location
            extracted_title = evidence.source_title
            if "html" in page.content_type.lower():
                simplified = simplify_html(page.content, self.artifacts)
                simplified_ref = simplified.simplified_artifact_ref
                paragraph_locations = [
                    item.location for item in simplified.paragraphs
                ]
                if simplified.title and simplified.title != "未命名页面":
                    extracted_title = simplified.title
                if simplified.paragraphs:
                    paragraph = _best_supporting_paragraph(
                        simplified.paragraphs,
                        f"{evidence.claim} {evidence.source_title}",
                    )
                    if paragraph is None:
                        raise OSError("fetched_body_failed_quality_gate")
                    extracted_excerpt = paragraph.text
                    extracted_location = paragraph.location
            updated = EvidenceCard(
                **{
                    **evidence.__dict__,
                    "source_title": extracted_title,
                    "excerpt": extracted_excerpt,
                    "source_location": extracted_location,
                    "artifact_refs": [
                        *evidence.artifact_refs,
                        raw_ref,
                        *([simplified_ref] if simplified_ref else []),
                    ],
                    "quality_assessment": f"{evidence.quality_assessment}; fetched",
                }
            )
            return MaterializedEvidence(
                evidence=updated,
                material={
                    "evidence_id": evidence.evidence_id,
                    "status": "fetched",
                    "artifact_refs": [raw_ref],
                    "url": evidence.source_url,
                    "final_url": page.final_url,
                    "content_type": page.content_type,
                    "simplified_artifact_ref": simplified_ref,
                    "paragraph_locations": paragraph_locations,
                    "fetch_cache_hit": cache_hit,
                    "formal_evidence_allowed": True,
                },
            )
        except _NetworkSafetyError as exc:
            return self._reject_network_safety(
                evidence=evidence,
                mode=mode,
                reason=exc.reason,
                rejected_url=exc.rejected_url,
            )
        except Exception as exc:
            reader_result = self._materialize_via_public_reader(
                evidence=evidence,
                mode=mode,
                direct_error=exc,
            )
            if reader_result is not None:
                return reader_result
            hosted_result = self._materialize_hosted_search_citation(
                evidence=evidence,
                mode=mode,
                direct_error=exc,
            )
            if hosted_result is not None:
                return hosted_result
            with self._reader_failure_lock:
                reader_error = self._reader_failures.pop(
                    evidence.evidence_id,
                    "",
                )
            diagnostic = (
                f"fetch_failed\nurl={evidence.source_url}\n"
                f"error={type(exc).__name__}: {exc}\n"
                + (f"reader_error={reader_error}\n" if reader_error else "")
                + "该诊断用于保留真实联网smoke边界；正式结论不应仅依赖失败材料。\n"
            )
            diag_ref = self.artifacts.put(
                diagnostic,
                kind="text",
                meta={
                    "url": evidence.source_url,
                    "content_type": "text/plain",
                    "materialization_status": "fetch_failed",
                    "evidence_id": evidence.evidence_id,
                    "mode": mode,
                    "reader_error": reader_error,
                },
            )
            updated = EvidenceCard(
                **{
                    **evidence.__dict__,
                    "artifact_refs": [*evidence.artifact_refs, diag_ref],
                    "quality_assessment": f"{evidence.quality_assessment}; fetch_failed",
                }
            )
            return MaterializedEvidence(
                evidence=updated,
                material={
                    "evidence_id": evidence.evidence_id,
                    "status": "fetch_failed",
                    "artifact_refs": [diag_ref],
                    "url": evidence.source_url,
                    "error": f"{type(exc).__name__}: {exc}",
                    "reader_error": reader_error,
                    "formal_evidence_allowed": False,
                },
            )

    def _fetch_public_page(self, source_url: str) -> tuple[_FetchedPublicPage, bool]:
        cache_key = urlsplit(source_url)._replace(fragment="").geturl()
        with self._fetch_cache_lock:
            cached = self._fetch_cache.get(cache_key)
            if cached is not None:
                return cached, True
            cached_failure = self._fetch_failure_cache.get(cache_key)
            if cached_failure:
                raise HTTPStatusError(f"cached_origin_failure:{cached_failure}")
            future = self._fetch_inflight.get(cache_key)
            owner = future is None
            if future is None:
                future = Future()
                self._fetch_inflight[cache_key] = future
        if not owner:
            return future.result(), True
        try:
            with self._fetch_slots:
                fetched = self._download_public_page(source_url)
            with self._fetch_cache_lock:
                self._fetch_cache[cache_key] = fetched
            future.set_result(fetched)
            return fetched, False
        except BaseException as exc:
            if _is_hard_access_failure(exc):
                with self._fetch_cache_lock:
                    self._fetch_failure_cache[cache_key] = (
                        f"{type(exc).__name__}: {exc}"
                    )
            future.set_exception(exc)
            raise
        finally:
            with self._fetch_cache_lock:
                self._fetch_inflight.pop(cache_key, None)

    def _download_public_page(self, source_url: str) -> _FetchedPublicPage:
        current_url = source_url
        redirects_followed = 0
        while True:
            target, rejection_reason = self._resolve_public_target(current_url)
            if rejection_reason:
                raise _NetworkSafetyError(rejection_reason, current_url)
            assert target is not None
            response = self.transport.get(
                url=current_url,
                connect_ip=target.connect_ip,
                hostname=target.hostname,
                port=target.port,
                timeout_seconds=self.timeout_seconds,
                headers={"User-Agent": "equipment-deep-research/0.1"},
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = _response_header(response.headers, "location")
            if not location:
                raise OSError("redirect response missing Location header")
            if redirects_followed >= self.max_redirects:
                raise OSError(f"redirect limit exceeded: {self.max_redirects}")
            current_url = urljoin(current_url, location)
            redirects_followed += 1
        response.raise_for_status()
        return _FetchedPublicPage(
            content=response.content,
            content_type=_response_header(
                response.headers,
                "content-type",
                default="application/octet-stream",
            ),
            final_url=current_url,
            connect_ip=target.connect_ip,
        )

    def _materialize_via_public_reader(
        self,
        *,
        evidence: EvidenceCard,
        mode: str,
        direct_error: Exception,
    ) -> MaterializedEvidence | None:
        if mode != "real" or not self.public_reader_base_url:
            return None
        if not self.public_reader_base_url.startswith("https://"):
            return None
        source = evidence.source_url.removeprefix("https://")
        origin_host = (urlsplit(evidence.source_url).hostname or "").lower()
        with self._reader_failure_lock:
            cached_reader_failure = self._reader_origin_failures.get(origin_host)
        if cached_reader_failure:
            with self._reader_failure_lock:
                self._reader_failures[evidence.evidence_id] = (
                    f"cached_reader_failure:{cached_reader_failure}"
                )
            return None
        if self.public_reader_base_url.endswith(("http://", "https://")):
            reader_url = f"{self.public_reader_base_url}{source}"
        else:
            reader_url = f"{self.public_reader_base_url.rstrip('/')}/{source}"
        attempts = max(
            1,
            int(os.environ.get("EQUIPMENT_DR_PUBLIC_READER_ATTEMPTS", "2")),
        )
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                target, rejection_reason = self._resolve_public_target(reader_url)
                if rejection_reason or target is None:
                    last_error = rejection_reason or "reader_resolution_failed"
                    break
                with self._reader_slots:
                    response = self.transport.get(
                        url=reader_url,
                        connect_ip=target.connect_ip,
                        hostname=target.hostname,
                        port=target.port,
                        timeout_seconds=self.public_reader_timeout_seconds,
                        headers={"User-Agent": "equipment-deep-research/0.1"},
                    )
                response.raise_for_status()
                text = response.content.decode("utf-8", errors="replace").strip()
                if len(text) < 200:
                    last_error = f"reader_response_too_short:{len(text)}"
                    continue
                ref = self.artifacts.put(
                    text,
                    kind="text",
                    meta={
                        "url": evidence.source_url,
                        "reader_url": reader_url,
                        "content_type": _response_header(
                            response.headers,
                            "content-type",
                            default="text/plain",
                        ),
                        "materialization_status": "reader_fetched",
                        "evidence_id": evidence.evidence_id,
                        "mode": mode,
                        "reader_attempt": attempt,
                        "direct_error": (
                            f"{type(direct_error).__name__}: {direct_error}"
                        ),
                    },
                )
                selected_paragraph = _best_reader_paragraph(
                    text,
                    evidence.claim,
                )
                if selected_paragraph is None:
                    last_error = "reader_body_failed_quality_gate"
                    break
                excerpt, paragraph_index = selected_paragraph
                updated = EvidenceCard(
                    **{
                        **evidence.__dict__,
                        "excerpt": excerpt,
                        "source_location": f"{ref}#p{paragraph_index}",
                        "artifact_refs": [*evidence.artifact_refs, ref],
                        "quality_assessment": (
                            f"{evidence.quality_assessment}; reader_fetched"
                        ),
                    }
                )
                return MaterializedEvidence(
                    evidence=updated,
                    material={
                        "evidence_id": evidence.evidence_id,
                        "status": "reader_fetched",
                        "artifact_refs": [ref],
                        "url": evidence.source_url,
                        "reader_url": reader_url,
                        "reader_attempt": attempt,
                        "formal_evidence_allowed": True,
                    },
                )
            except Exception as exc:
                last_error = f"attempt_{attempt}:{type(exc).__name__}: {exc}"
                if origin_host and _is_hard_access_failure(exc):
                    with self._reader_failure_lock:
                        self._reader_origin_failures[origin_host] = last_error
        if last_error:
            with self._reader_failure_lock:
                self._reader_failures[evidence.evidence_id] = last_error
        return None

    def _materialize_hosted_search_citation(
        self,
        *,
        evidence: EvidenceCard,
        mode: str,
        direct_error: Exception,
    ) -> MaterializedEvidence | None:
        if (
            mode != "real"
            or not any(
                marker in evidence.quality_assessment
                for marker in (
                    "responses_web_search_source",
                    "codex_web_search_source",
                )
            )
            or not evidence.claim.strip()
        ):
            return None
        text = (
            "hosted_search_citation\n"
            f"source_title={evidence.source_title}\n"
            f"source_url={evidence.source_url}\n"
            f"claim={evidence.claim}\n"
            f"excerpt={evidence.excerpt}\n"
            "retrieval=Hosted web search citation metadata\n"
        )
        ref = self.artifacts.put(
            text,
            kind="text",
            meta={
                "url": evidence.source_url,
                "content_type": "text/plain",
                "materialization_status": "hosted_search_citation",
                "evidence_id": evidence.evidence_id,
                "mode": mode,
                "direct_error": f"{type(direct_error).__name__}: {direct_error}",
            },
        )
        updated = EvidenceCard(
            **{
                **evidence.__dict__,
                "source_location": f"{ref}#citation",
                "artifact_refs": [*evidence.artifact_refs, ref],
                "quality_assessment": (
                    f"{evidence.quality_assessment}; hosted_search_citation"
                ),
            }
        )
        return MaterializedEvidence(
            evidence=updated,
            material={
                "evidence_id": evidence.evidence_id,
                "status": "hosted_search_citation",
                "artifact_refs": [ref],
                "url": evidence.source_url,
                "formal_evidence_allowed": True,
            },
        )

    def _resolve_public_target(self, url: str) -> tuple[_ResolvedTarget | None, str]:
        parsed, rejection_reason = _parse_network_url(url)
        if rejection_reason:
            return None, rejection_reason
        assert parsed is not None
        host = parsed.hostname
        if host == "localhost" or host.endswith(".localhost"):
            return None, "private_network_denied"

        try:
            literal_address = ipaddress.ip_address(host)
        except ValueError:
            try:
                rows = self.resolver(host, parsed.port, type=socket.SOCK_STREAM)
            except OSError:
                return None, "host_resolution_failed"
            addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
            seen: set[str] = set()
            for row in rows:
                raw_address = row[4][0].split("%", 1)[0]
                try:
                    address = ipaddress.ip_address(raw_address)
                except ValueError:
                    return None, "host_resolution_failed"
                if str(address) not in seen:
                    seen.add(str(address))
                    addresses.append(address)
            if not addresses:
                return None, "host_resolution_failed"
            if any(
                not self._is_allowed_resolved_address(address, scheme=parsed.scheme)
                for address in addresses
            ):
                return None, "private_network_denied"
            connect_ip = str(addresses[0])
        else:
            if not _is_public_unicast_address(literal_address):
                return None, "private_network_denied"
            connect_ip = str(literal_address)

        return (
            _ResolvedTarget(
                hostname=host,
                port=parsed.port,
                connect_ip=connect_ip,
            ),
            "",
        )

    def _is_allowed_resolved_address(
        self,
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
        *,
        scheme: str,
    ) -> bool:
        if _is_public_unicast_address(address):
            return True
        return bool(
            self.allow_benchmark_dns_proxy
            and scheme == "https"
            and isinstance(address, ipaddress.IPv4Address)
            and address in _IPV4_BENCHMARK_DNS_PROXY
        )


def _best_supporting_paragraph(paragraphs: list[Any], query: str) -> Any | None:
    usable = [item for item in paragraphs if _is_usable_evidence_excerpt(item.text)]
    if not usable:
        return None
    terms = {item.lower() for item in query.replace("/", " ").split() if len(item) > 1}
    return max(
        usable,
        key=lambda item: (
            sum(1 for term in terms if term in item.text.lower()),
            min(len(item.text), 1200),
        ),
    )


def _response_header(
    headers: dict[str, str],
    name: str,
    *,
    default: str = "",
) -> str:
    wanted = name.lower()
    for header_name, value in headers.items():
        if header_name.lower() == wanted:
            return value
    return default


def _best_reader_paragraph(text: str, claim: str) -> tuple[str, int] | None:
    paragraphs = [
        " ".join(line.strip() for line in block.splitlines()).strip()
        for block in text.split("\n\n")
    ]
    candidates = [
        (index, paragraph)
        for index, paragraph in enumerate(paragraphs, start=1)
        if len(paragraph) >= 80
        and not paragraph.startswith(("Title:", "URL Source:"))
        and _is_usable_evidence_excerpt(paragraph)
    ]
    if not candidates:
        return None
    terms = {item.lower() for item in claim.split() if len(item) >= 3}
    index, paragraph = max(
        candidates,
        key=lambda item: (
            sum(term in item[1].lower() for term in terms),
            min(len(item[1]), 1200),
        ),
    )
    return paragraph[:1600], index


def _is_usable_evidence_excerpt(text: str) -> bool:
    """Reject error shells and navigation boilerplate before formal evidence use."""
    normalized = " ".join(str(text).split()).strip()
    lowered = normalized.lower()
    if len(normalized) < 60:
        return False
    error_markers = (
        "an error occurred in the application",
        "your page could not be served",
        "page not found",
        "404 not found",
        "access denied",
        "service unavailable",
        "enable javascript to continue",
        "checking your browser before accessing",
    )
    if any(marker in lowered for marker in error_markers):
        return False
    markdown_links = lowered.count("](") + lowered.count("* [")
    if markdown_links >= 4:
        return False
    navigation_terms = sum(
        marker in lowered
        for marker in (
            "available add-ons",
            "back button",
            "keyboard navigation",
            "page scroll",
            "searchfield",
            "sidebar",
            "site map",
        )
    )
    return navigation_terms < 3


def _is_hard_access_failure(exc: BaseException) -> bool:
    if isinstance(exc, HTTPStatusError):
        message = str(exc)
        return any(f"HTTP {status}" in message for status in (401, 403, 404, 410))
    return False


def _parse_network_url(url: str) -> tuple[_ParsedNetworkURL | None, str]:
    try:
        parsed = urlsplit(url)
    except (UnicodeError, ValueError):
        return None, "invalid_url"
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None, "scheme_not_allowed"
    try:
        hostname = parsed.hostname
    except (UnicodeError, ValueError):
        return None, "invalid_url"
    if not hostname:
        return None, "missing_host"
    try:
        explicit_port = parsed.port
    except ValueError:
        return None, "invalid_port"
    normalized_hostname = _normalize_hostname(hostname)
    if normalized_hostname is None:
        return None, "invalid_hostname"
    return (
        _ParsedNetworkURL(
            scheme=scheme,
            hostname=normalized_hostname,
            port=explicit_port or (443 if scheme == "https" else 80),
        ),
        "",
    )


def _normalize_hostname(hostname: str) -> str | None:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return None
        without_root_dot = ascii_hostname[:-1] if ascii_hostname.endswith(".") else ascii_hostname
        labels = without_root_dot.split(".")
        if (
            not without_root_dot
            or len(without_root_dot) > 253
            or any(not label or len(label) > 63 for label in labels)
        ):
            return None
        return ascii_hostname
    return str(address).lower()


def _is_public_unicast_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    if isinstance(address, ipaddress.IPv4Address):
        return _is_public_ipv4_address(address)

    if address.scope_id is not None:
        return False
    if address.ipv4_mapped is not None:
        return _is_public_ipv4_address(address.ipv4_mapped)
    if address in _IPV4_TRANSLATED_NETWORK:
        return _is_public_ipv4_address(_last_32_bits_as_ipv4(address))
    if address.sixtofour is not None:
        return _is_public_ipv4_address(address.sixtofour)
    if address.teredo is not None:
        server, client = address.teredo
        return _is_public_ipv4_address(server) and _is_public_ipv4_address(client)
    if address in _NAT64_WELL_KNOWN_NETWORK:
        return _is_public_ipv4_address(_last_32_bits_as_ipv4(address))
    if address in _NAT64_LOCAL_USE_NETWORK:
        return False

    isatap_address = _isatap_embedded_ipv4(address)
    if isatap_address is not None and not _is_public_ipv4_address(isatap_address):
        return False

    return not any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_unspecified,
            address.is_reserved,
            address.is_multicast,
            address.is_site_local,
        )
    )


def _is_public_ipv4_address(address: ipaddress.IPv4Address) -> bool:
    return not any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_unspecified,
            address.is_reserved,
            address.is_multicast,
            address in _IPV4_SHARED_NETWORK,
        )
    )


def _last_32_bits_as_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address:
    return ipaddress.IPv4Address(int(address) & 0xFFFF_FFFF)


def _isatap_embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    interface_identifier = int(address) & 0xFFFF_FFFF_FFFF_FFFF
    marker = interface_identifier >> 32
    if marker not in {0x0000_5EFE, 0x0200_5EFE}:
        return None
    return _last_32_bits_as_ipv4(address)
