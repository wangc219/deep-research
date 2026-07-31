"""Data models and JSONL helpers for extraction experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable

from .schema import (
    ASSERTION_STRENGTHS,
    CLAIM_TYPES,
    ENTITY_TYPES,
    MODALITIES,
    RELATION_INFERENCE_ELIGIBILITY,
    RELATION_TYPES,
)


@dataclass
class DocumentChunk:
    document_id: str
    chunk_id: str
    text: str
    source_path: str = ""
    page: int | None = None
    section_title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentChunk":
        return cls(
            document_id=str(data.get("document_id", "")),
            chunk_id=str(data.get("chunk_id", "")),
            text=str(data.get("text", "")),
            source_path=str(data.get("source_path", "")),
            page=data.get("page"),
            section_title=str(data.get("section_title", "")),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceSpan:
    evidence_id: str
    chunk_id: str
    quote: str
    start_char: int | None = None
    end_char: int | None = None
    page: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceSpan":
        return cls(
            evidence_id=str(data.get("evidence_id", "")),
            chunk_id=str(data.get("chunk_id", "")),
            quote=str(data.get("quote", "")),
            start_char=data.get("start_char"),
            end_char=data.get("end_char"),
            page=data.get("page"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedEntity:
    entity_id: str
    name: str
    entity_type: str
    evidence_span_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractedEntity":
        return cls(
            entity_id=str(data.get("entity_id", "")),
            name=str(data.get("name", "")),
            entity_type=str(data.get("entity_type", "")),
            evidence_span_ids=list(data.get("evidence_span_ids", [])),
            confidence=float(data.get("confidence", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedRelation:
    relation_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    evidence_span_ids: list[str] = field(default_factory=list)
    assertion_strength: str = "weak"
    confidence: float = 0.0
    inference_eligible: str = ""
    trigger_text: str = ""
    extraction_rule_version: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractedRelation":
        return cls(
            relation_id=str(data.get("relation_id", "")),
            source_entity_id=str(data.get("source_entity_id", "")),
            target_entity_id=str(data.get("target_entity_id", "")),
            relation_type=str(data.get("relation_type", "")),
            evidence_span_ids=list(data.get("evidence_span_ids", [])),
            assertion_strength=str(data.get("assertion_strength", "weak")),
            confidence=float(data.get("confidence", 0.0)),
            inference_eligible=str(data.get("inference_eligible", "")),
            trigger_text=str(data.get("trigger_text", "")),
            extraction_rule_version=str(data.get("extraction_rule_version", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceClaim:
    claim_id: str
    claim_type: str
    text: str
    modality: str
    evidence_span_ids: list[str] = field(default_factory=list)
    subject_entity_id: str = ""
    object_entity_id: str = ""
    predicate: str = ""
    confidence: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceClaim":
        return cls(
            claim_id=str(data.get("claim_id", "")),
            claim_type=str(data.get("claim_type", "")),
            text=str(data.get("text", "")),
            modality=str(data.get("modality", "")),
            evidence_span_ids=list(data.get("evidence_span_ids", [])),
            subject_entity_id=str(data.get("subject_entity_id", "")),
            object_entity_id=str(data.get("object_entity_id", "")),
            predicate=str(data.get("predicate", "")),
            confidence=float(data.get("confidence", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractionTrace:
    schema_version: str
    prompt_version: str
    model: str
    latency_ms: int = 0
    cost: float = 0.0
    retry_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractionTrace":
        return cls(
            schema_version=str(data.get("schema_version", "")),
            prompt_version=str(data.get("prompt_version", "")),
            model=str(data.get("model", "")),
            latency_ms=int(data.get("latency_ms", 0)),
            cost=float(data.get("cost", 0.0)),
            retry_count=int(data.get("retry_count", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractionResult:
    task_id: str
    adapter_name: str
    document_id: str
    chunk_id: str
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    claims: list[SourceClaim] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace: ExtractionTrace | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractionResult":
        return cls(
            task_id=str(data.get("task_id", "")),
            adapter_name=str(data.get("adapter_name", "")),
            document_id=str(data.get("document_id", "")),
            chunk_id=str(data.get("chunk_id", "")),
            entities=[ExtractedEntity.from_dict(item) for item in data.get("entities", [])],
            relations=[
                ExtractedRelation.from_dict(item) for item in data.get("relations", [])
            ],
            claims=[SourceClaim.from_dict(item) for item in data.get("claims", [])],
            metrics=list(data.get("metrics", [])),
            constraints=list(data.get("constraints", [])),
            evidence_spans=[
                EvidenceSpan.from_dict(item) for item in data.get("evidence_spans", [])
            ],
            warnings=list(data.get("warnings", [])),
            trace=ExtractionTrace.from_dict(data.get("trace", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trace"] = self.trace.to_dict() if self.trace else {}
        return payload

    def validate(self, chunk_text: str | None = None) -> list[str]:
        warnings: list[str] = []
        evidence_ids = {span.evidence_id for span in self.evidence_spans}
        entity_ids = {entity.entity_id for entity in self.entities}

        if not self.task_id:
            warnings.append("missing task_id")
        if not self.adapter_name:
            warnings.append("missing adapter_name")
        if not self.document_id:
            warnings.append("missing document_id")
        if not self.chunk_id:
            warnings.append("missing chunk_id")

        for entity in self.entities:
            if entity.entity_type not in ENTITY_TYPES:
                warnings.append(f"invalid entity_type:{entity.entity_type}")
            if not entity.name:
                warnings.append(f"empty entity_name:{entity.entity_id}")
            for evidence_id in entity.evidence_span_ids:
                if evidence_id not in evidence_ids:
                    warnings.append(f"entity_missing_evidence:{entity.entity_id}:{evidence_id}")

        for relation in self.relations:
            if relation.relation_type not in RELATION_TYPES:
                warnings.append(f"invalid relation_type:{relation.relation_type}")
            if (
                relation.inference_eligible
                and relation.inference_eligible not in RELATION_INFERENCE_ELIGIBILITY
            ):
                warnings.append(
                    f"invalid_inference_eligible:{relation.relation_id}:{relation.inference_eligible}"
                )
            if relation.assertion_strength not in ASSERTION_STRENGTHS:
                warnings.append(
                    f"invalid_assertion_strength:{relation.assertion_strength}"
                )
            if relation.source_entity_id not in entity_ids:
                warnings.append(f"relation_missing_source:{relation.relation_id}")
            if relation.target_entity_id not in entity_ids:
                warnings.append(f"relation_missing_target:{relation.relation_id}")
            if not relation.evidence_span_ids:
                warnings.append(f"relation_no_evidence:{relation.relation_id}")
            for evidence_id in relation.evidence_span_ids:
                if evidence_id not in evidence_ids:
                    warnings.append(
                        f"relation_missing_evidence:{relation.relation_id}:{evidence_id}"
                    )

        for claim in self.claims:
            if claim.claim_type not in CLAIM_TYPES:
                warnings.append(f"invalid_claim_type:{claim.claim_type}")
            if claim.modality not in MODALITIES:
                warnings.append(f"invalid_modality:{claim.modality}")
            if not claim.evidence_span_ids:
                warnings.append(f"claim_no_evidence:{claim.claim_id}")
            for evidence_id in claim.evidence_span_ids:
                if evidence_id not in evidence_ids:
                    warnings.append(f"claim_missing_evidence:{claim.claim_id}:{evidence_id}")

        if chunk_text is not None:
            for span in self.evidence_spans:
                if span.quote and span.quote not in chunk_text:
                    warnings.append(f"evidence_quote_not_found:{span.evidence_id}")

        if self.trace is None:
            warnings.append("missing_trace")
        else:
            if not self.trace.schema_version:
                warnings.append("missing_trace_schema_version")
            if not self.trace.model:
                warnings.append("missing_trace_model")

        return warnings


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_chunks(path: Path) -> list[DocumentChunk]:
    return [DocumentChunk.from_dict(row) for row in read_jsonl(path)]


def load_results(path: Path) -> list[ExtractionResult]:
    return [ExtractionResult.from_dict(row) for row in read_jsonl(path)]
