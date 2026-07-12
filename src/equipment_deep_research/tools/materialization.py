from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
import socket
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from equipment_deep_research.domain.models import EvidenceCard
from equipment_deep_research.tools.artifacts import SecureArtifactStore
from equipment_deep_research.tools.http_transport import HTTPTransport, PinnedHTTPTransport


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


_IPV4_SHARED_NETWORK = ipaddress.ip_network("100.64.0.0/10")
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
    ) -> None:
        if artifact_store is not None and artifact_dir is not None:
            raise ValueError("provide artifact_dir or artifact_store, not both")
        if artifact_store is None:
            if artifact_dir is None:
                raise ValueError("artifact_dir is required")
            artifact_store = SecureArtifactStore(artifact_dir)
        self.artifacts = artifact_store
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.resolver = resolver or socket.getaddrinfo
        self.transport = transport or PinnedHTTPTransport()

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
            current_url = evidence.source_url
            redirects_followed = 0
            while True:
                target, rejection_reason = self._resolve_public_target(current_url)
                if rejection_reason:
                    return self._reject_network_safety(
                        evidence=evidence,
                        mode=mode,
                        reason=rejection_reason,
                        rejected_url=current_url,
                    )
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
            content_type = _response_header(
                response.headers,
                "content-type",
                default="application/octet-stream",
            )
            raw_ref = self.artifacts.put(
                response.content,
                kind="html" if "html" in content_type.lower() else "raw",
                meta={
                    "url": evidence.source_url,
                    "content_type": content_type,
                    "materialization_status": "fetched",
                    "evidence_id": evidence.evidence_id,
                    "mode": mode,
                    "final_url": current_url,
                    "connect_ip": target.connect_ip,
                },
            )
            updated = EvidenceCard(
                **{
                    **evidence.__dict__,
                    "artifact_refs": [*evidence.artifact_refs, raw_ref],
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
                    "final_url": current_url,
                    "content_type": content_type,
                    "formal_evidence_allowed": True,
                },
            )
        except Exception as exc:
            diagnostic = (
                f"fetch_failed\nurl={evidence.source_url}\n"
                f"error={type(exc).__name__}: {exc}\n"
                "该诊断用于保留真实联网smoke边界；正式结论不应仅依赖失败材料。\n"
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
                    "formal_evidence_allowed": False,
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
            if any(not _is_public_unicast_address(address) for address in addresses):
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
