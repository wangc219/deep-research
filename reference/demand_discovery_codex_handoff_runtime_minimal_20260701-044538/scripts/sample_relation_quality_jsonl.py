"""Build a relation-quality review sample from ExtractionResult JSONL outputs."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = PROJECT_ROOT / "scripts" / "extraction_experiment"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(EXPERIMENT_ROOT))

from migrate_phase3_sqlite import classify_content_type  # noqa: E402
from models import DocumentChunk, ExtractionResult, load_chunks, load_results  # noqa: E402
from sample_relation_quality_ab import (  # noqa: E402
    balanced_pick,
    confidence_bin,
    round_robin_relation_pick,
    table,
)
from schema import RELATION_TYPES  # noqa: E402


DEFAULT_RESULTS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_full_ocr_llm_v3_all_chunks"
    / "group_a_schema_guided"
    / "extraction_results.jsonl"
)
DEFAULT_CHUNKS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_full_ocr"
    / "chunks.jsonl"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "relation_quality_ab_v3" / "sample_manifest.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "manual-review" / "relation_quality_v3_sample_plan.md"


@dataclass(frozen=True)
class CandidateRow:
    assertion_id: str
    relation_type: str
    confidence: float
    confidence_bin: str
    content_type: str
    document_title: str
    chunk_id: str
    source: str
    source_type: str
    target: str
    target_type: str
    claim_text: str
    evidence_quote: str
    inference_eligible: str
    trigger_text: str
    extraction_rule_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def main() -> int:
    args = parse_args()
    results_path = Path(args.results).expanduser().resolve()
    chunks_path = Path(args.chunks).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    relation_types = parse_relation_types(args.relation_types)

    if not results_path.exists():
        raise FileNotFoundError(f"ExtractionResult JSONL not found: {results_path}")
    if not chunks_path.exists():
        raise FileNotFoundError(f"chunks JSONL not found: {chunks_path}")

    results = load_results(results_path)
    chunks_by_id = {chunk.chunk_id: chunk for chunk in load_chunks(chunks_path)}
    candidates = build_candidates_from_results(results, chunks_by_id, relation_types=relation_types)
    sample = stratified_sample(
        candidates,
        sample_size=args.sample_size,
        min_per_relation=args.min_per_relation,
    )

    write_jsonl(output_path, (row.to_dict() for row in sample))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        build_report(
            sample=sample,
            candidates=candidates,
            results_path=results_path,
            chunks_path=chunks_path,
            output_path=output_path,
            relation_types=relation_types,
        ),
        encoding="utf-8",
    )
    print(f"wrote {output_path}")
    print(f"wrote {report_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a v3 relation quality sample manifest from ExtractionResult JSONL.",
    )
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--min-per-relation", type=int, default=8)
    parser.add_argument(
        "--relation-types",
        default="all",
        help="Comma-separated relation types to sample. Use 'all' for all schema relation types.",
    )
    return parser.parse_args()


def parse_relation_types(value: str) -> list[str]:
    if value.strip().lower() == "all":
        return sorted(RELATION_TYPES)
    return [item.strip() for item in value.split(",") if item.strip()]


def build_candidates_from_results(
    results: list[ExtractionResult],
    chunks_by_id: dict[str, DocumentChunk],
    relation_types: list[str] | None = None,
) -> list[CandidateRow]:
    allowed_relation_types = set(relation_types or RELATION_TYPES)
    candidates: list[CandidateRow] = []

    for result in results:
        chunk = chunks_by_id.get(result.chunk_id)
        entities_by_id = {entity.entity_id: entity for entity in result.entities}
        claims_by_signature = _claims_by_signature(result)
        evidence_by_id = {span.evidence_id: span for span in result.evidence_spans}

        for index, relation in enumerate(result.relations, start=1):
            if relation.relation_type not in allowed_relation_types:
                continue
            source = entities_by_id.get(relation.source_entity_id)
            target = entities_by_id.get(relation.target_entity_id)
            if source is None or target is None:
                continue
            matched_claims = claims_by_signature.get(
                (relation.source_entity_id, relation.target_entity_id, relation.relation_type),
                [],
            )
            if not matched_claims:
                matched_claims = _claims_sharing_evidence(result, relation.evidence_span_ids)
            evidence_ids = _ordered_unique(
                [
                    *relation.evidence_span_ids,
                    *[
                        evidence_id
                        for claim in matched_claims
                        for evidence_id in claim.evidence_span_ids
                    ],
                ]
            )
            relation_id = relation.relation_id or f"rel-{index:03d}"
            candidates.append(
                CandidateRow(
                    assertion_id=f"{result.chunk_id}::{relation_id}",
                    relation_type=relation.relation_type,
                    confidence=relation.confidence,
                    confidence_bin=confidence_bin(relation.confidence),
                    content_type=_content_type(chunk),
                    document_title=_document_title(chunk, result.document_id),
                    chunk_id=result.chunk_id,
                    source=source.name,
                    source_type=source.entity_type,
                    target=target.name,
                    target_type=target.entity_type,
                    claim_text=_join_unique(claim.text for claim in matched_claims),
                    evidence_quote=_join_unique(
                        evidence_by_id[evidence_id].quote
                        for evidence_id in evidence_ids
                        if evidence_id in evidence_by_id
                    ),
                    inference_eligible=relation.inference_eligible,
                    trigger_text=relation.trigger_text,
                    extraction_rule_version=relation.extraction_rule_version,
                )
            )
    return sorted(
        candidates,
        key=lambda row: (
            row.relation_type,
            -row.confidence,
            row.document_title,
            row.chunk_id,
            row.assertion_id,
        ),
    )


def stratified_sample(
    candidates: list[CandidateRow],
    sample_size: int,
    min_per_relation: int,
) -> list[CandidateRow]:
    picked: list[CandidateRow] = []
    picked_ids: set[str] = set()
    relation_types = sorted({row.relation_type for row in candidates})
    for relation_type in relation_types:
        relation_rows = [row for row in candidates if row.relation_type == relation_type]
        target = min(min_per_relation, len(relation_rows), max(0, sample_size - len(picked)))
        for row in balanced_pick(
            relation_rows,
            target,
            key_fields=("confidence_bin", "content_type", "document_title"),
        ):
            if row.assertion_id not in picked_ids:
                picked.append(row)
                picked_ids.add(row.assertion_id)
    if len(picked) >= sample_size:
        return picked[:sample_size]

    remaining = [row for row in candidates if row.assertion_id not in picked_ids]
    for row in round_robin_relation_pick(remaining, sample_size - len(picked)):
        if row.assertion_id not in picked_ids:
            picked.append(row)
            picked_ids.add(row.assertion_id)
    return picked


def build_report(
    sample: list[CandidateRow],
    candidates: list[CandidateRow],
    results_path: Path,
    chunks_path: Path,
    output_path: Path,
    relation_types: list[str],
) -> str:
    lines = [
        "# Relation Quality v3 Sample Plan",
        "",
        "日期：2026-05-25",
        "",
        "## 范围",
        "",
        f"- 结果 JSONL：`{results_path}`",
        f"- chunks JSONL：`{chunks_path}`",
        f"- 样本清单：`{output_path}`",
        f"- relation_types：`{relation_types}`",
        f"- 候选数：`{len(candidates)}`",
        f"- 样本数：`{len(sample)}`",
        "",
        "该清单来自 v3 prompt/schema 的标准 `ExtractionResult` JSONL，用于人工方向、类型和 path-safe 审核；它不调用 LLM、不写数据库、不自动判断语义正确性。",
        "",
        "## 样本分布",
        "",
        table(["dimension", "value", "count"], distribution_rows(sample)),
        "",
        "## v3 审核字段",
        "",
        "- `trigger_text`：抽取器给出的关系触发片段，辅助判断方向和关系类型。",
        "- `inference_eligible`：抽取器/validator 给出的 path-safe 初判，不等于人工标签。",
        "- `extraction_rule_version`：关系质量规则版本，用于追踪 schema/prompt 演进。",
        "",
    ]
    return "\n".join(lines)


def distribution_rows(rows: list[CandidateRow]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for dimension in [
        "relation_type",
        "confidence_bin",
        "content_type",
        "document_title",
        "inference_eligible",
    ]:
        counts: dict[str, int] = {}
        for row in rows:
            value = str(getattr(row, dimension))
            counts[value] = counts.get(value, 0) + 1
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            output.append({"dimension": dimension, "value": value, "count": count})
    return output


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _claims_by_signature(result: ExtractionResult) -> dict[tuple[str, str, str], list[Any]]:
    by_signature: dict[tuple[str, str, str], list[Any]] = {}
    for claim in result.claims:
        key = (claim.subject_entity_id, claim.object_entity_id, claim.predicate)
        by_signature.setdefault(key, []).append(claim)
    return by_signature


def _claims_sharing_evidence(result: ExtractionResult, evidence_span_ids: list[str]) -> list[Any]:
    relation_evidence = set(evidence_span_ids)
    if not relation_evidence:
        return []
    return [
        claim
        for claim in result.claims
        if relation_evidence.intersection(claim.evidence_span_ids)
    ]


def _content_type(chunk: DocumentChunk | None) -> str:
    if chunk is None:
        return ""
    return classify_content_type(chunk.text, chunk.section_title)


def _document_title(chunk: DocumentChunk | None, fallback_document_id: str) -> str:
    if chunk is None:
        return fallback_document_id
    metadata_title = str(chunk.metadata.get("title") or "").strip()
    if metadata_title:
        return metadata_title
    if chunk.source_path:
        return Path(chunk.source_path).stem
    return chunk.document_id


def _join_unique(values: Iterable[str]) -> str:
    return " | ".join(_ordered_unique([str(value).strip() for value in values if str(value).strip()]))


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


if __name__ == "__main__":
    raise SystemExit(main())
