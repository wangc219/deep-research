"""Pilot 金标选择清单校验与标注活动契约生成。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .annotation_workflow import AnnotationAssignmentSpec, AnnotationCampaignSpec, PILOT_SPLIT_COUNTS
from .pilot_coverage import pilot_coverage_blockers
from .pilot_coverage import normalize_acceptance_languages

PILOT_CAMPAIGN_PREFLIGHT_VERSION = "defense-kg-pilot-campaign-preflight-v1"


class PilotSelectionEntry(BaseModel):
    """从来源清单保留的最小、安全、可复现标注选择项。"""

    model_config = ConfigDict(extra="ignore")

    document_id: str = Field(min_length=1, max_length=128)
    split: Literal["train", "dev", "test"]
    source_type: Literal["paper", "patent"]
    language: str = Field(min_length=1, max_length=32)
    acceptance_languages: list[str] = Field(default_factory=lambda: ["en", "zh"], min_length=1, max_length=16)
    domain: str = Field(max_length=256)
    domain_annotation_kind: Literal["human"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def normalize_language_profile(self):
        self.acceptance_languages = sorted(normalize_acceptance_languages(self.acceptance_languages))
        return self


class PilotSelectionManifest(BaseModel):
    """固定 300 篇、按文档去重且严格 210/30/60 的选择清单。"""

    entries: list[PilotSelectionEntry]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_pilot_contract(self):
        expected_count = sum(PILOT_SPLIT_COUNTS.values())
        if len(self.entries) != expected_count:
            raise ValueError(f"Pilot 标注选择清单必须恰好包含 {expected_count} 篇文档")
        document_ids = [item.document_id for item in self.entries]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Pilot 标注选择清单存在重复 document_id")
        content_hashes = [item.content_sha256 for item in self.entries]
        if len(content_hashes) != len(set(content_hashes)):
            raise ValueError("Pilot 标注选择清单存在重复内容 SHA-256")
        split_counts = Counter(item.split for item in self.entries)
        actual = {split: split_counts.get(split, 0) for split in PILOT_SPLIT_COUNTS}
        if actual != PILOT_SPLIT_COUNTS:
            raise ValueError(f"Pilot 标注选择清单必须按 210/30/60 切分，实际为 {actual}")
        profiles = {tuple(item.acceptance_languages) for item in self.entries}
        if len(profiles) != 1:
            raise ValueError("Pilot 标注选择清单的验收语种声明必须一致")
        return self

    @property
    def acceptance_languages(self) -> list[str]:
        """返回选择清单唯一的验收语种范围。"""
        return list(self.entries[0].acceptance_languages)


class AuthoritativeDocumentBinding(BaseModel):
    """选择清单文档与 PostgreSQL 权威文档版本的内部映射。"""

    manifest_document_id: str
    authoritative_document_id: str = Field(min_length=1, max_length=64)
    document_version: int = Field(ge=1)


def load_pilot_selection_manifest(path: str | Path) -> PilotSelectionManifest:
    """读取 JSONL 并校验固定 Pilot 契约，不把标题或路径带入领域对象。"""
    manifest_path = Path(path).expanduser().resolve()
    raw = manifest_path.read_bytes()
    entries = []
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"选择清单第 {line_number} 行不是合法 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"选择清单第 {line_number} 行必须是 JSON 对象")
        entries.append(PilotSelectionEntry.model_validate(payload))
    return PilotSelectionManifest(entries=entries, manifest_sha256=hashlib.sha256(raw).hexdigest())


def build_annotation_campaign_spec(
    *,
    manifest: PilotSelectionManifest,
    bindings: list[AuthoritativeDocumentBinding],
    name: str,
    ontology_version: str,
    guideline_version: str,
    annotator_ids: list[str],
    arbitrator_id: str,
) -> AnnotationCampaignSpec:
    """仅在 300 篇均绑定权威版本后生成可直接提交的 campaign spec。"""
    coverage_blockers = pilot_manifest_coverage_blockers(manifest)
    if coverage_blockers:
        raise ValueError(f"Pilot 标注选择清单覆盖不足: {coverage_blockers}")
    by_manifest_id = {item.manifest_document_id: item for item in bindings}
    missing = [item.document_id for item in manifest.entries if item.document_id not in by_manifest_id]
    if missing:
        raise ValueError(f"仍有 {len(missing)} 篇选择文档未绑定权威文档版本")
    return AnnotationCampaignSpec(
        name=name,
        guideline_version=guideline_version,
        ontology_version=ontology_version,
        pilot_mode=True,
        acceptance_languages=manifest.acceptance_languages,
        assignments=[
            AnnotationAssignmentSpec(
                document_id=by_manifest_id[item.document_id].authoritative_document_id,
                document_version=by_manifest_id[item.document_id].document_version,
                split=item.split,
                annotator_ids=annotator_ids,
                arbitrator_id=arbitrator_id,
            )
            for item in manifest.entries
        ],
    )


def safe_manifest_summary(manifest: PilotSelectionManifest) -> dict[str, Any]:
    """生成不含标题、原文、本地路径和单篇哈希的选择清单摘要。"""
    return {
        "manifest_sha256": manifest.manifest_sha256,
        "document_count": len(manifest.entries),
        "split_counts": dict(sorted(Counter(item.split for item in manifest.entries).items())),
        "source_type_counts": dict(sorted(Counter(item.source_type for item in manifest.entries).items())),
        "language_counts": dict(sorted(Counter(item.language for item in manifest.entries).items())),
        "acceptance_languages": manifest.acceptance_languages,
        "domain_count": len({item.domain for item in manifest.entries if item.domain}),
    }


def pilot_manifest_coverage_blockers(manifest: PilotSelectionManifest) -> list[str]:
    """返回正式 Pilot 活动必须满足的来源、语言和领域覆盖缺口。"""
    return pilot_coverage_blockers(
        source_types={item.source_type for item in manifest.entries},
        languages={item.language for item in manifest.entries},
        domains={item.domain for item in manifest.entries if item.domain},
        acceptance_languages=manifest.acceptance_languages,
    )
