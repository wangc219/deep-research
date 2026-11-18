"""LightRAG 增强与基础流水线的成对质量代理评测。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from platform_core.knowledge.graphs.defense_ontology import (
    DEFENSE_ONTOLOGY_V1,
    canonical_entity_type,
    validate_relation_types,
)
from platform_core.knowledge.graphs.extractors.lightrag_enhancement import detect_ocr_damage


@dataclass(frozen=True, slots=True)
class AblationInput:
    """不在报告中泄露原文的一个成对抽取输入。"""

    document_id: str
    block_id: str
    text: str


def build_lightrag_ablation_report(
    inputs: list[AblationInput],
    baseline_results: list[dict[str, Any]],
    enhanced_results: list[dict[str, Any]],
    *,
    baseline_runtime: dict[str, Any],
    enhanced_runtime: dict[str, Any],
    pipeline_revision: str,
) -> dict[str, Any]:
    """比较同一输入上的基础与增强结果，并明确质量增益是否已被证明。"""

    if not inputs:
        raise ValueError("LightRAG 消融评测输入不能为空")
    if len(inputs) != len(baseline_results) or len(inputs) != len(enhanced_results):
        raise ValueError("LightRAG 消融评测的输入与两组结果数量必须一致")

    baseline = _aggregate_quality(inputs, baseline_results)
    enhanced = _aggregate_quality(inputs, enhanced_results)
    paired = _paired_changes(inputs, baseline_results, enhanced_results)
    structural_regressions = _structural_regressions(baseline, enhanced)

    return {
        "contract": "defense-kg-lightrag-ablation-v1",
        "evaluation_scope": "development_quality_proxy",
        "pipeline_revision": pipeline_revision,
        "sample": {
            "document_count": len({item.document_id for item in inputs}),
            "block_count": len(inputs),
            "input_fingerprint_sha256": _input_fingerprint(inputs),
            "contains_source_text": False,
        },
        "baseline": {"quality": baseline, "runtime": baseline_runtime},
        "enhanced": {"quality": enhanced, "runtime": enhanced_runtime},
        "paired_changes": paired,
        "structural_regressions": structural_regressions,
        "quality_gain_proven": False,
        "quality_gain_reason": (
            "该报告只证明结构合法性、候选增量和效率变化；缺少独立人工 Gold，"
            "不能据此宣称实体或关系 Precision/Recall/F1 提升。"
        ),
    }


def _aggregate_quality(inputs: list[AblationInput], results: list[dict[str, Any]]) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    enhancement_statuses: Counter[str] = Counter()
    initial_statuses: Counter[str] = Counter()
    gleaning_statuses: Counter[str] = Counter()
    ocr_repair_statuses: Counter[str] = Counter()
    enhancement_revisions: Counter[str] = Counter()
    enhancement_observability: Counter[str] = Counter()

    for item, result in zip(inputs, results, strict=True):
        quality = _result_quality(item.text, result)
        counters.update(quality)
        for candidate in [*(result.get("entities") or []), *(result.get("relations") or [])]:
            sources.update(str(source) for source in candidate.get("model_sources") or [])
        enhancement = (result.get("metadata") or {}).get("llm_enhancement") or {}
        if enhancement:
            enhancement_statuses[str(enhancement.get("status") or "unknown")] += 1
            initial_statuses[str(enhancement.get("initial_status") or "unknown")] += 1
            gleaning_statuses[str(enhancement.get("gleaning_status") or "unknown")] += 1
            enhancement_revisions[str(enhancement.get("enhancement_revision") or "unknown")] += 1
            enhancement_observability["gleaning_calls"] += int(enhancement.get("gleaning_calls") or 0)
            gleaning_mode = str(enhancement.get("gleaning_mode") or "")
            if gleaning_mode:
                enhancement_observability[f"gleaning_mode_{gleaning_mode}"] += 1
            relation_completion = enhancement.get("relation_completion") or {}
            if isinstance(relation_completion, dict) and relation_completion.get("revision"):
                enhancement_observability["relation_completion_blocks"] += 1
                for source_field, metric_name in (
                    ("candidate_pair_count", "relation_completion_candidate_pairs"),
                    ("eligible_entity_count", "relation_completion_eligible_entities"),
                    ("accepted_relation_count", "relation_completion_accepted_relations"),
                ):
                    enhancement_observability[metric_name] += int(relation_completion.get(source_field) or 0)
                for reason, count in (relation_completion.get("entity_rejection_counts") or {}).items():
                    enhancement_observability[f"relation_completion_entity_rejected_{reason}"] += int(count or 0)
            routing = enhancement.get("adaptive_routing") or {}
            if isinstance(routing, dict) and routing:
                decision = str(routing.get("decision") or "unknown")
                enhancement_observability[f"adaptive_routing_{decision}_blocks"] += 1
                for reason in routing.get("trigger_reasons") or []:
                    enhancement_observability[f"adaptive_trigger_{str(reason)}"] += 1
            ocr_repair = enhancement.get("ocr_repair_extraction") or {}
            if isinstance(ocr_repair, dict) and ocr_repair:
                ocr_repair_statuses[str(ocr_repair.get("status") or "unknown")] += 1
                for source_field, metric_name in (
                    ("llm_calls", "ocr_repair_llm_calls"),
                    ("proposal_count", "ocr_repair_proposals"),
                    ("applied_to_temporary_view_count", "ocr_repair_temporary_patches"),
                    ("rejected_proposal_count", "ocr_repair_rejected_proposals"),
                    ("regular_entity_count", "ocr_repair_regular_entities"),
                    ("regular_relation_count", "ocr_repair_regular_relations"),
                    ("repair_dependent_entity_count", "ocr_repair_dependent_entities"),
                    ("repair_dependent_relation_count", "ocr_repair_dependent_relations"),
                ):
                    enhancement_observability[metric_name] += int(ocr_repair.get(source_field) or 0)
            entity_review = enhancement.get("entity_review") or {}
            if isinstance(entity_review, dict):
                enhancement_observability["entity_review_proposals"] += int(entity_review.get("proposal_count") or 0)
                enhancement_observability["entity_review_applied"] += int(entity_review.get("applied_count") or 0)
                for source_field, metric_name in (
                    ("relabel_applied_count", "entity_review_relabel_applied"),
                    ("reject_applied_count", "entity_review_reject_applied"),
                    ("blocked_count", "entity_review_blocked"),
                    ("below_threshold_count", "entity_review_below_threshold"),
                    ("raw_decision_count", "entity_review_raw_decisions"),
                    ("unknown_review_ref_count", "entity_review_unknown_refs"),
                    ("valid_decision_count", "entity_review_valid_decisions"),
                ):
                    enhancement_observability[metric_name] += int(entity_review.get(source_field) or 0)
                enhancement_observability["relations_dropped_after_review"] += int(
                    entity_review.get("relations_dropped_after_review") or 0
                )
            if enhancement.get("initial_status") == "skipped_budget":
                enhancement_observability["initial_budget_skips"] += 1
            if enhancement.get("gleaning_status") == "skipped_budget":
                enhancement_observability["gleaning_budget_skips"] += 1
            for stage, token_field, limit_field in (
                ("initial", "initial_prompt_estimated_tokens", "initial_prompt_limit_tokens"),
                ("gleaning", "gleaning_prompt_estimated_tokens", "gleaning_input_limit_tokens"),
            ):
                token_value = enhancement.get(token_field)
                limit_value = enhancement.get(limit_field)
                if isinstance(token_value, int) and not isinstance(token_value, bool):
                    enhancement_observability[f"{stage}_prompt_estimated_tokens_total"] += token_value
                    enhancement_observability[f"{stage}_prompt_estimated_tokens_max"] = max(
                        enhancement_observability[f"{stage}_prompt_estimated_tokens_max"],
                        token_value,
                    )
                if isinstance(limit_value, int) and not isinstance(limit_value, bool):
                    enhancement_observability[f"{stage}_prompt_limit_tokens"] = limit_value
            for stage in ("initial", "gleaning"):
                budget = enhancement.get(f"{stage}_output_budget") or {}
                if not isinstance(budget, dict):
                    continue
                for reason, count in (budget.get("relation_rejection_counts") or {}).items():
                    enhancement_observability[f"{stage}_relation_rejected_{reason}"] += int(count or 0)
                enhancement_observability[f"{stage}_truncated_entities"] += int(budget.get("truncated_entities") or 0)
                enhancement_observability[f"{stage}_truncated_relations"] += int(budget.get("truncated_relations") or 0)
                enhancement_observability[f"{stage}_dangling_relations_removed"] += int(
                    budget.get("relations_dropped_with_truncated_endpoint") or 0
                )
                if budget.get("deterministic_truncation_applied") is True:
                    enhancement_observability[f"blocks_with_{stage}_truncation"] += 1

    entity_total = counters["entities"]
    relation_total = counters["relations"]
    entity_span_valid = counters["entity_span_valid"]
    evidence_span_total = counters["evidence_span_total"]
    evidence_span_valid = counters["evidence_span_valid"]
    return {
        **dict(sorted(counters.items())),
        "entity_span_valid_rate": _ratio(entity_span_valid, entity_total),
        "relation_evidence_span_valid_rate": _ratio(evidence_span_valid, evidence_span_total),
        "ontology_valid_relation_rate": _ratio(
            relation_total - counters["ontology_invalid_relations"],
            relation_total,
        ),
        "model_source_counts": dict(sorted(sources.items())),
        "llm_enhancement_status_counts": dict(sorted(enhancement_statuses.items())),
        "llm_initial_status_counts": dict(sorted(initial_statuses.items())),
        "llm_gleaning_status_counts": dict(sorted(gleaning_statuses.items())),
        "llm_ocr_repair_status_counts": dict(sorted(ocr_repair_statuses.items())),
        "llm_enhancement_revision_counts": dict(sorted(enhancement_revisions.items())),
        "llm_enhancement_observability": dict(sorted(enhancement_observability.items())),
    }


def _result_quality(text: str, result: dict[str, Any]) -> Counter[str]:
    counters: Counter[str] = Counter()
    entities = result.get("entities") or []
    relations = result.get("relations") or []
    counters["entities"] = len(entities)
    counters["relations"] = len(relations)

    damage_spans = detect_ocr_damage(text)
    counters["ocr_damage_spans"] = len(damage_spans)
    entity_refs: dict[str, dict[str, Any]] = {}
    for entity in entities:
        start = entity.get("start")
        end = entity.get("end")
        valid = (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and 0 <= start < end <= len(text)
            and text[start:end] == str(entity.get("text") or "")
        )
        counters["entity_span_valid" if valid else "entity_span_invalid"] += 1
        if valid and any(start < damage.end and end > damage.start for damage in damage_spans):
            counters["entities_overlapping_ocr_damage"] += 1
        entity_type = canonical_entity_type(str(entity.get("label") or ""))
        if entity_type not in DEFENSE_ONTOLOGY_V1.entity_type_by_code:
            counters["ontology_invalid_entities"] += 1
        for reference in (entity.get("id"), entity.get("text")):
            if reference is not None:
                entity_refs[str(reference)] = entity

    for relation in relations:
        source = _resolve_endpoint(relation.get("source"), entity_refs)
        target = _resolve_endpoint(relation.get("target"), entity_refs)
        if source is None or target is None:
            counters["dangling_relations"] += 1
        elif not validate_relation_types(
            str(source.get("label") or ""),
            str(relation.get("label") or ""),
            str(target.get("label") or ""),
        ):
            counters["ontology_invalid_relations"] += 1

        spans = relation.get("evidence_spans") or []
        if not spans:
            counters["relations_without_evidence_span"] += 1
        for span in spans:
            counters["evidence_span_total"] += 1
            start = span.get("start") if isinstance(span, dict) else None
            end = span.get("end") if isinstance(span, dict) else None
            valid = (
                isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
                and 0 <= start < end <= len(text)
            )
            counters["evidence_span_valid" if valid else "evidence_span_invalid"] += 1

    return counters


def _paired_changes(
    inputs: list[AblationInput],
    baseline_results: list[dict[str, Any]],
    enhanced_results: list[dict[str, Any]],
) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    per_block = []
    for item, baseline, enhanced in zip(inputs, baseline_results, enhanced_results, strict=True):
        baseline_entities = _entity_keys(baseline)
        enhanced_entities = _entity_keys(enhanced)
        baseline_relations = _relation_keys(baseline)
        enhanced_relations = _relation_keys(enhanced)
        added_entities = enhanced_entities - baseline_entities
        removed_entities = baseline_entities - enhanced_entities
        added_relations = enhanced_relations - baseline_relations
        removed_relations = baseline_relations - enhanced_relations
        counters.update(
            {
                "added_entities": len(added_entities),
                "removed_entities": len(removed_entities),
                "added_relations": len(added_relations),
                "removed_relations": len(removed_relations),
                "blocks_with_entity_changes": bool(added_entities or removed_entities),
                "blocks_with_relation_changes": bool(added_relations or removed_relations),
            }
        )
        per_block.append(
            {
                "document_id_sha256": hashlib.sha256(item.document_id.encode()).hexdigest(),
                "block_id_sha256": hashlib.sha256(item.block_id.encode()).hexdigest(),
                "added_entities": len(added_entities),
                "removed_entities": len(removed_entities),
                "added_relations": len(added_relations),
                "removed_relations": len(removed_relations),
            }
        )
    return {**dict(sorted(counters.items())), "per_block": per_block}


def _entity_keys(result: dict[str, Any]) -> set[tuple[str, int | None, int | None, str]]:
    return {
        (
            canonical_entity_type(str(entity.get("label") or "")),
            entity.get("start"),
            entity.get("end"),
            str(entity.get("text") or ""),
        )
        for entity in result.get("entities") or []
    }


def _relation_keys(result: dict[str, Any]) -> set[tuple[Any, ...]]:
    refs: dict[str, tuple[Any, ...]] = {}
    for entity in result.get("entities") or []:
        key = (
            canonical_entity_type(str(entity.get("label") or "")),
            entity.get("start"),
            entity.get("end"),
            str(entity.get("text") or ""),
        )
        for reference in (entity.get("id"), entity.get("text")):
            if reference is not None:
                refs[str(reference)] = key
    relations = set()
    for relation in result.get("relations") or []:
        source = _endpoint_key(relation.get("source"), refs)
        target = _endpoint_key(relation.get("target"), refs)
        relations.add((str(relation.get("label") or ""), source, target))
    return relations


def _resolve_endpoint(value: Any, refs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return refs.get(str(value or ""))


def _endpoint_key(value: Any, refs: dict[str, tuple[Any, ...]]) -> tuple[Any, ...]:
    if isinstance(value, dict):
        return (
            canonical_entity_type(str(value.get("label") or "")),
            value.get("start"),
            value.get("end"),
            str(value.get("text") or ""),
        )
    return refs.get(str(value or ""), ("unresolved", str(value or "")))


def _structural_regressions(baseline: dict[str, Any], enhanced: dict[str, Any]) -> list[str]:
    regressions = []
    for field in (
        "entity_span_invalid",
        "evidence_span_invalid",
        "ontology_invalid_entities",
        "ontology_invalid_relations",
        "dangling_relations",
        "entities_overlapping_ocr_damage",
    ):
        if int(enhanced.get(field, 0)) > int(baseline.get(field, 0)):
            regressions.append(field)
    return regressions


def _input_fingerprint(inputs: list[AblationInput]) -> str:
    rows = [
        {
            "document_id": item.document_id,
            "block_id": item.block_id,
            "text_sha256": hashlib.sha256(item.text.encode()).hexdigest(),
        }
        for item in inputs
    ]
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None
