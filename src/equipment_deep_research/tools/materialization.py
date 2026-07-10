from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
import socket
from typing import Any
from urllib.parse import urlparse

import requests

from equipment_deep_research.domain.models import EvidenceCard
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore


@dataclass(frozen=True)
class MaterializedEvidence:
    evidence: EvidenceCard
    material: dict[str, Any]


class EvidenceMaterializer:
    def __init__(
        self,
        artifact_dir: str | Path,
        *,
        timeout_seconds: int = 8,
    ) -> None:
        self.artifacts = ArtifactStore(artifact_dir)
        self.timeout_seconds = timeout_seconds

    def materialize(self, evidence: EvidenceCard, *, mode: str) -> MaterializedEvidence:
        rejection_reason = _network_safety_rejection(evidence.source_url)
        if rejection_reason:
            return self._reject_network_safety(evidence=evidence, mode=mode, reason=rejection_reason)
        if evidence.source_url.startswith("https://fixture.local") or evidence.source_url.startswith("http://fixture.local"):
            return self._materialize_fixture(evidence=evidence, mode=mode)
        return self._materialize_public_url(evidence=evidence, mode=mode)

    def _reject_network_safety(
        self,
        *,
        evidence: EvidenceCard,
        mode: str,
        reason: str,
    ) -> MaterializedEvidence:
        diagnostic = (
            f"network_safety_rejected\nurl={evidence.source_url}\n"
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
            response = requests.get(
                evidence.source_url,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "equipment-deep-research/0.1"},
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "application/octet-stream")
            raw_ref = self.artifacts.put(
                response.content,
                kind="html" if "html" in content_type.lower() else "raw",
                meta={
                    "url": evidence.source_url,
                    "content_type": content_type,
                    "materialization_status": "fetched",
                    "evidence_id": evidence.evidence_id,
                    "mode": mode,
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


def _network_safety_rejection(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return "scheme_not_allowed"
    host = (parsed.hostname or "").lower()
    if not host:
        return "missing_host"
    if host == "fixture.local":
        return ""
    if host == "localhost" or host.endswith(".localhost"):
        return "private_network_denied"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = {
                row[4][0].split("%", 1)[0]
                for row in socket.getaddrinfo(
                    host,
                    parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        except OSError:
            return "host_resolution_failed"
        if not addresses:
            return "host_resolution_failed"
        if any(not ipaddress.ip_address(item).is_global for item in addresses):
            return "private_network_denied"
        return ""
    if not address.is_global:
        return "private_network_denied"
    return ""
