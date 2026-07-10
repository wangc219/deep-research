from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from equipment_deep_research.domain.models import EvidenceCard
from equipment_deep_research.tools.source_policy import SourceWhitelist
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
        source_whitelist: SourceWhitelist | None = None,
    ) -> None:
        self.artifacts = ArtifactStore(artifact_dir)
        self.timeout_seconds = timeout_seconds
        self.source_whitelist = source_whitelist

    def materialize(self, evidence: EvidenceCard, *, mode: str) -> MaterializedEvidence:
        if self.source_whitelist and not self.source_whitelist.allows(evidence.source_url):
            return self._block_unapproved_source(evidence=evidence, mode=mode)
        if evidence.source_url.startswith("https://fixture.local") or evidence.source_url.startswith("http://fixture.local"):
            return self._materialize_fixture(evidence=evidence, mode=mode)
        return self._materialize_public_url(evidence=evidence, mode=mode)

    def _block_unapproved_source(self, *, evidence: EvidenceCard, mode: str) -> MaterializedEvidence:
        host = self.source_whitelist.host_for(evidence.source_url) if self.source_whitelist else ""
        diagnostic = (
            f"blocked_unapproved_source\nurl={evidence.source_url}\n"
            f"host={host or 'unknown'}\n"
            "该来源未进入首版白名单，只记录为建议新增信源，不进入正式证据集。\n"
        )
        ref = self.artifacts.put(
            diagnostic,
            kind="text",
            meta={
                "url": evidence.source_url,
                "content_type": "text/plain",
                "materialization_status": "blocked_unapproved_source",
                "evidence_id": evidence.evidence_id,
                "mode": mode,
                "suggested_source_domain": host,
            },
        )
        updated = EvidenceCard(
            **{
                **evidence.__dict__,
                "artifact_refs": [*evidence.artifact_refs, ref],
                "quality_assessment": f"{evidence.quality_assessment}; blocked_unapproved_source",
            }
        )
        return MaterializedEvidence(
            evidence=updated,
            material={
                "evidence_id": evidence.evidence_id,
                "status": "blocked_unapproved_source",
                "artifact_refs": [ref],
                "url": evidence.source_url,
                "suggested_source_domain": host,
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
