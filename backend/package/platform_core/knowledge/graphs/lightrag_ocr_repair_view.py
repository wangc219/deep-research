"""为 OCR 修复建议构造不改写原文、可回切 Span 的临时视图。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OCRRepairPatch:
    """一处通过校验、仅作用于临时视图的 OCR 修复。"""

    original_start: int
    original_end: int
    original_text: str
    suggested_text: str
    confidence: float
    reason: str
    repaired_start: int
    repaired_end: int


@dataclass(frozen=True, slots=True)
class MappedSpan:
    """视图 Span 回切原文后的结果。"""

    start: int
    end: int
    repair_dependent: bool


@dataclass(frozen=True, slots=True)
class OCRRepairedTextView:
    """原文派生的非持久化修复视图及双向边界映射。"""

    original_text: str
    repaired_text: str
    patches: tuple[OCRRepairPatch, ...]
    rejected_proposals: tuple[dict[str, Any], ...]

    def repaired_span_to_original(self, start: int, end: int) -> MappedSpan | None:
        """将修复视图 Span 精确回切到原文；模糊边界返回 ``None``。"""
        if not _valid_span(start, end, len(self.repaired_text)):
            return None
        original_start = self._repaired_boundary_to_original(start)
        original_end = self._repaired_boundary_to_original(end)
        if original_start is None or original_end is None or original_end <= original_start:
            return None
        dependent = any(start < patch.repaired_end and end > patch.repaired_start for patch in self.patches)
        return MappedSpan(original_start, original_end, dependent)

    def original_span_to_repaired(self, start: int, end: int) -> MappedSpan | None:
        """将原文 Span 映射到修复视图；模糊边界返回 ``None``。"""
        if not _valid_span(start, end, len(self.original_text)):
            return None
        repaired_start = self._original_boundary_to_repaired(start)
        repaired_end = self._original_boundary_to_repaired(end)
        if repaired_start is None or repaired_end is None or repaired_end <= repaired_start:
            return None
        dependent = any(start < patch.original_end and end > patch.original_start for patch in self.patches)
        return MappedSpan(repaired_start, repaired_end, dependent)

    def patch_manifest(self) -> list[dict[str, Any]]:
        """返回不含整段原文的可审计修复清单。"""
        return [
            {
                "original_start": patch.original_start,
                "original_end": patch.original_end,
                "original_text": patch.original_text,
                "suggested_text": patch.suggested_text,
                "confidence": patch.confidence,
                "reason": patch.reason,
                "repaired_start": patch.repaired_start,
                "repaired_end": patch.repaired_end,
                "applied_to_temporary_view_only": True,
            }
            for patch in self.patches
        ]

    def _repaired_boundary_to_original(self, position: int) -> int | None:
        delta = 0
        for patch in self.patches:
            if position < patch.repaired_start:
                return position - delta
            if position == patch.repaired_start:
                return patch.original_start
            if position == patch.repaired_end:
                return patch.original_end
            if patch.repaired_start < position < patch.repaired_end:
                if len(patch.suggested_text) != len(patch.original_text):
                    return None
                return patch.original_start + position - patch.repaired_start
            delta += len(patch.suggested_text) - len(patch.original_text)
        return position - delta

    def _original_boundary_to_repaired(self, position: int) -> int | None:
        delta = 0
        for patch in self.patches:
            if position < patch.original_start:
                return position + delta
            if position == patch.original_start:
                return patch.repaired_start
            if position == patch.original_end:
                return patch.repaired_end
            if patch.original_start < position < patch.original_end:
                if len(patch.suggested_text) != len(patch.original_text):
                    return None
                return patch.repaired_start + position - patch.original_start
            delta += len(patch.suggested_text) - len(patch.original_text)
        return position + delta


def build_ocr_repaired_text_view(
    source_text: str,
    proposals: list[dict[str, Any]],
    *,
    min_confidence: float,
    max_proposals: int,
) -> OCRRepairedTextView:
    """校验建议并构造临时视图；重叠、低置信度和错误 Span 均拒绝。"""
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence 必须在 0 到 1 之间")
    if isinstance(max_proposals, bool) or not isinstance(max_proposals, int) or not 1 <= max_proposals <= 64:
        raise ValueError("max_proposals 必须在 1 到 64 之间")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    normalized = [_normalize_proposal(item, source_text) for item in proposals]
    normalized = [item for item in normalized if item is not None]
    eligible: list[dict[str, Any]] = []
    for proposal in normalized:
        if proposal["confidence"] < min_confidence:
            rejected.append(_rejected(proposal, "below_min_confidence"))
            continue
        if not proposal["suggested_text"] or proposal["suggested_text"] == proposal["original_text"]:
            rejected.append(_rejected(proposal, "empty_or_unchanged_suggestion"))
            continue
        eligible.append(proposal)

    eligible.sort(
        key=lambda item: (
            -item["confidence"],
            item["original_end"] - item["original_start"],
            item["original_start"],
            item["original_end"],
        )
    )
    for proposal in eligible:
        if any(
            proposal["original_start"] < existing["original_end"]
            and proposal["original_end"] > existing["original_start"]
            for existing in accepted
        ):
            rejected.append(_rejected(proposal, "overlapping_proposal"))
            continue
        if len(accepted) >= max_proposals:
            rejected.append(_rejected(proposal, "max_proposals_exceeded"))
            continue
        accepted.append(proposal)
    accepted.sort(key=lambda item: (item["original_start"], item["original_end"]))

    parts: list[str] = []
    patches: list[OCRRepairPatch] = []
    original_cursor = 0
    repaired_cursor = 0
    for proposal in accepted:
        unchanged = source_text[original_cursor : proposal["original_start"]]
        parts.append(unchanged)
        repaired_cursor += len(unchanged)
        repaired_start = repaired_cursor
        parts.append(proposal["suggested_text"])
        repaired_cursor += len(proposal["suggested_text"])
        patches.append(
            OCRRepairPatch(
                **proposal,
                repaired_start=repaired_start,
                repaired_end=repaired_cursor,
            )
        )
        original_cursor = proposal["original_end"]
    parts.append(source_text[original_cursor:])

    return OCRRepairedTextView(
        original_text=source_text,
        repaired_text="".join(parts),
        patches=tuple(patches),
        rejected_proposals=tuple(rejected),
    )


def candidates_for_repaired_view(
    result: dict[str, Any],
    view: OCRRepairedTextView,
) -> dict[str, Any]:
    """只把不依赖修复内容的既有候选映射进临时视图。"""
    entities = []
    entity_by_ref: dict[str, dict[str, Any]] = {}
    for raw in result.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        mapped = view.original_span_to_repaired(raw.get("start"), raw.get("end"))
        if mapped is None or mapped.repair_dependent:
            continue
        entity = {**raw, "start": mapped.start, "end": mapped.end}
        if view.repaired_text[mapped.start : mapped.end] != str(entity.get("text") or ""):
            continue
        entities.append(entity)
        for ref in _entity_refs(entity):
            entity_by_ref[ref] = entity

    relations = []
    for raw in result.get("relations") or []:
        if not isinstance(raw, dict):
            continue
        source = _resolve_endpoint(raw.get("source"), entity_by_ref)
        target = _resolve_endpoint(raw.get("target"), entity_by_ref)
        if source is None or target is None:
            continue
        spans = []
        for span in raw.get("evidence_spans") or []:
            if not isinstance(span, dict):
                spans = []
                break
            mapped = view.original_span_to_repaired(span.get("start"), span.get("end"))
            if mapped is None or mapped.repair_dependent:
                spans = []
                break
            spans.append({"start": mapped.start, "end": mapped.end})
        relation = {**raw, "source": source, "target": target}
        if raw.get("evidence_spans"):
            if not spans:
                continue
            relation["evidence_spans"] = spans
        relations.append(relation)
    return {"entities": entities, "relations": relations, "metadata": {}}


def partition_repaired_view_candidates(
    prepared: dict[str, Any],
    view: OCRRepairedTextView,
    *,
    original_known_entities: list[dict[str, Any]],
) -> dict[str, Any]:
    """回切修复视图候选，并隔离所有依赖修复文本的候选。"""
    original_by_id = {
        str(entity.get("id") or ""): entity
        for entity in original_known_entities
        if isinstance(entity, dict) and str(entity.get("id") or "")
    }
    regular_entities: list[dict[str, Any]] = []
    regular_by_id = dict(original_by_id)
    dependent_entities: list[dict[str, Any]] = []
    dependent_ids: set[str] = set()

    for raw in prepared.get("entities") or []:
        if not isinstance(raw, dict):
            continue
        entity_id = str(raw.get("id") or "")
        mapped = view.repaired_span_to_original(raw.get("start"), raw.get("end"))
        repaired_text = str(raw.get("text") or "")
        if mapped is None or mapped.repair_dependent:
            dependent_ids.add(entity_id)
            dependent_entities.append(_dependent_entity(raw, view, mapped, "span_depends_on_repair"))
            continue
        original_text = view.original_text[mapped.start : mapped.end]
        if repaired_text != original_text:
            dependent_ids.add(entity_id)
            dependent_entities.append(_dependent_entity(raw, view, mapped, "text_differs_from_original"))
            continue
        entity = {
            **raw,
            "start": mapped.start,
            "end": mapped.end,
            "text": original_text,
            "review_status": "pending",
            "expert_review_required": True,
            "model_sources": ["lightrag_llm_ocr_repair_context"],
            "ocr_repair_context_used": True,
        }
        regular_entities.append(entity)
        if entity_id:
            regular_by_id[entity_id] = entity

    regular_relations: list[dict[str, Any]] = []
    dependent_relations: list[dict[str, Any]] = []
    for raw in prepared.get("relations") or []:
        if not isinstance(raw, dict):
            continue
        source_id = _endpoint_id(raw.get("source"))
        target_id = _endpoint_id(raw.get("target"))
        source = regular_by_id.get(source_id)
        target = regular_by_id.get(target_id)
        mapped_spans: list[dict[str, int]] = []
        evidence_dependent = False
        for span in raw.get("evidence_spans") or []:
            if not isinstance(span, dict):
                evidence_dependent = True
                break
            mapped = view.repaired_span_to_original(span.get("start"), span.get("end"))
            if mapped is None or mapped.repair_dependent:
                evidence_dependent = True
                break
            mapped_spans.append({"start": mapped.start, "end": mapped.end})
        if (
            not source_id
            or not target_id
            or source_id in dependent_ids
            or target_id in dependent_ids
            or source is None
            or target is None
            or evidence_dependent
        ):
            dependent_relations.append(_dependent_relation(raw, source_id, target_id, evidence_dependent))
            continue
        regular_relations.append(
            {
                **raw,
                "source": source,
                "target": target,
                "evidence_quote": "",
                "evidence_spans": mapped_spans,
                "review_status": "pending",
                "expert_review_required": True,
                "model_sources": ["lightrag_llm_ocr_repair_context"],
                "ocr_repair_context_used": True,
            }
        )

    metadata = dict(prepared.get("metadata") or {})
    metadata.update(
        {
            "stage": "ocr_repair_extraction",
            "original_text_preserved": True,
            "temporary_repaired_view": True,
            "repair_patches": view.patch_manifest(),
            "rejected_repair_proposals": list(view.rejected_proposals),
            "repair_dependent_candidates": {
                "entities": dependent_entities,
                "relations": dependent_relations,
                "authority_eligible": False,
                "review_candidate_eligible": False,
            },
            "repair_dependent_entity_count": len(dependent_entities),
            "repair_dependent_relation_count": len(dependent_relations),
        }
    )
    return {"entities": regular_entities, "relations": regular_relations, "metadata": metadata}


def _normalize_proposal(item: Any, source_text: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    start, end = item.get("original_start"), item.get("original_end")
    original_text = str(item.get("original_text") or "")
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or not 0 <= start < end <= len(source_text)
        or source_text[start:end] != original_text
    ):
        return None
    try:
        confidence = float(item.get("confidence", 0.0))
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(confidence):
        return None
    return {
        "original_start": start,
        "original_end": end,
        "original_text": original_text,
        "suggested_text": str(item.get("suggested_text") or "")[:500],
        "confidence": max(0.0, min(confidence, 1.0)),
        "reason": str(item.get("reason") or "")[:1000],
    }


def _valid_span(start: Any, end: Any, text_length: int) -> bool:
    return (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and 0 <= start < end <= text_length
    )


def _rejected(proposal: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "original_start": proposal["original_start"],
        "original_end": proposal["original_end"],
        "confidence": proposal["confidence"],
        "rejection_reason": reason,
    }


def _entity_refs(entity: dict[str, Any]) -> set[str]:
    return {value for value in (str(entity.get("id") or ""), str(entity.get("text") or "")) if value}


def _endpoint_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or "")
    return str(value or "")


def _resolve_endpoint(value: Any, entity_by_ref: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if isinstance(value, dict):
        for ref in _entity_refs(value):
            if ref in entity_by_ref:
                return entity_by_ref[ref]
        return None
    return entity_by_ref.get(str(value or ""))


def _dependent_entity(
    raw: dict[str, Any],
    view: OCRRepairedTextView,
    mapped: MappedSpan | None,
    reason: str,
) -> dict[str, Any]:
    original_span = {"start": mapped.start, "end": mapped.end} if mapped is not None else None
    original_text = view.original_text[mapped.start : mapped.end] if mapped is not None else ""
    return {
        "id": str(raw.get("id") or ""),
        "label": str(raw.get("label") or ""),
        "suggested_text": str(raw.get("text") or ""),
        "repaired_span": {"start": raw.get("start"), "end": raw.get("end")},
        "original_span": original_span,
        "original_text": original_text,
        "confidence": raw.get("confidence"),
        "isolation_reason": reason,
        "review_status": "repair_dependent_candidate",
    }


def _dependent_relation(
    raw: dict[str, Any],
    source_id: str,
    target_id: str,
    evidence_dependent: bool,
) -> dict[str, Any]:
    return {
        "source": source_id,
        "target": target_id,
        "label": str(raw.get("label") or ""),
        "confidence": raw.get("confidence"),
        "claim_level": str(raw.get("claim_level") or "Inference"),
        "repaired_evidence_spans": raw.get("evidence_spans") or [],
        "isolation_reason": "evidence_depends_on_repair" if evidence_dependent else "endpoint_depends_on_repair",
        "review_status": "repair_dependent_candidate",
    }
