"""在文档级关系补抽后治理同名实体的跨类型冲突。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from platform_core.knowledge.graphs.defense_ontology import canonical_entity_type, validate_relation_types

DOCUMENT_TYPE_GOVERNANCE_VERSION = "document-relation-type-governance-v1"
DEFAULT_MIN_SUPPORTING_RELATIONS = 2


@dataclass(frozen=True, slots=True)
class DocumentEntityTypeRedirect:
    """由同文档关系方向唯一支持的实体类型重定向。"""

    source_entity_id: str
    target_entity_id: str
    normalized_name: str
    source_label: str
    target_label: str
    supporting_relation_count: int
    score_margin: int
    relation_compatibility_scores: dict[str, int]
    reason: str
    version: str = DOCUMENT_TYPE_GOVERNANCE_VERSION


def propose_document_entity_type_redirects(
    *,
    document: dict[str, Any],
    relations: list[dict[str, Any]],
    min_supporting_relations: int = DEFAULT_MIN_SUPPORTING_RELATIONS,
) -> dict[str, Any]:
    """只在至少两条关系且唯一类型领先时生成保留谱系的 redirect 建议。"""

    if isinstance(min_supporting_relations, bool) or not isinstance(min_supporting_relations, int):
        raise ValueError("文档类型治理 min_supporting_relations 必须是整数")
    if not 1 <= min_supporting_relations <= 16:
        raise ValueError("文档类型治理 min_supporting_relations 必须在 1 到 16 之间")

    entities = [item for item in document.get("entities") or [] if isinstance(item, dict)]
    entity_by_id = {str(item.get("entity_id") or ""): item for item in entities}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        normalized_name = _normalized_name(entity)
        if normalized_name:
            grouped.setdefault(normalized_name, []).append(entity)

    decisions: list[DocumentEntityTypeRedirect] = []
    resolved_groups = []
    skipped_groups = []
    for normalized_name, candidates in grouped.items():
        labels = sorted({_entity_label(candidate) for candidate in candidates if _entity_label(candidate)})
        if len(labels) <= 1:
            continue
        if any(_has_human_review(candidate) for candidate in candidates):
            skipped_groups.append(
                {
                    "normalized_name": normalized_name,
                    "labels": labels,
                    "reason": "human_reviewed_mention_present",
                }
            )
            continue

        scores = _relation_compatibility_scores(
            candidate_entity_ids={str(candidate.get("entity_id") or "") for candidate in candidates},
            candidate_labels=labels,
            entity_by_id=entity_by_id,
            relations=relations,
        )
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        selected_label, selected_score = ranked[0]
        runner_up_score = ranked[1][1]
        if selected_score < min_supporting_relations or selected_score <= runner_up_score:
            skipped_groups.append(
                {
                    "normalized_name": normalized_name,
                    "labels": labels,
                    "relation_compatibility_scores": scores,
                    "reason": "insufficient_unique_relation_evidence",
                }
            )
            continue

        matching = [candidate for candidate in candidates if _entity_label(candidate) == selected_label]
        target = max(
            matching,
            key=lambda candidate: (
                len(candidate.get("mentions") or []),
                _average_mention_confidence(candidate),
                str(candidate.get("entity_id") or ""),
            ),
        )
        target_id = str(target["entity_id"])
        group_decisions = []
        for candidate in candidates:
            source_id = str(candidate.get("entity_id") or "")
            if not source_id or source_id == target_id:
                continue
            decision = DocumentEntityTypeRedirect(
                source_entity_id=source_id,
                target_entity_id=target_id,
                normalized_name=normalized_name,
                source_label=_entity_label(candidate),
                target_label=selected_label,
                supporting_relation_count=selected_score,
                score_margin=selected_score - runner_up_score,
                relation_compatibility_scores=scores,
                reason=("同一文档的已约束关系端点一致支持目标类型；保留源实体并建立可追溯 merge redirect"),
            )
            decisions.append(decision)
            group_decisions.append(asdict(decision))
        resolved_groups.append(
            {
                "normalized_name": normalized_name,
                "selected_entity_id": target_id,
                "selected_label": selected_label,
                "relation_compatibility_scores": scores,
                "supporting_relation_count": selected_score,
                "score_margin": selected_score - runner_up_score,
                "redirects": group_decisions,
            }
        )

    return {
        "version": DOCUMENT_TYPE_GOVERNANCE_VERSION,
        "minimum_supporting_relations": min_supporting_relations,
        "conflict_group_count": len(resolved_groups) + len(skipped_groups),
        "resolved_group_count": len(resolved_groups),
        "skipped_group_count": len(skipped_groups),
        "redirect_count": len(decisions),
        "decisions": decisions,
        "resolved_groups": resolved_groups,
        "skipped_groups": skipped_groups,
    }


def _relation_compatibility_scores(
    *,
    candidate_entity_ids: set[str],
    candidate_labels: list[str],
    entity_by_id: dict[str, dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, int]:
    compatible: dict[str, set[tuple[Any, ...]]] = {label: set() for label in candidate_labels}
    for index, relation in enumerate(relations):
        source_id = str(relation.get("source_entity_id") or "")
        target_id = str(relation.get("target_entity_id") or "")
        source = entity_by_id.get(source_id)
        target = entity_by_id.get(target_id)
        if source is None or target is None:
            continue
        source_matches = source_id in candidate_entity_ids
        target_matches = target_id in candidate_entity_ids
        if not source_matches and not target_matches:
            continue
        relation_type = str(relation.get("type") or relation.get("relation_type") or "")
        evidence_key = (index, source_id, relation_type, target_id)
        for candidate_label in candidate_labels:
            source_label = candidate_label if source_matches else _entity_label(source)
            target_label = candidate_label if target_matches else _entity_label(target)
            if validate_relation_types(source_label, relation_type, target_label):
                compatible[candidate_label].add(evidence_key)
    return {label: len(values) for label, values in sorted(compatible.items())}


def _normalized_name(entity: dict[str, Any]) -> str:
    projection = entity.get("projection_record") or {}
    return str(projection.get("normalized_name") or entity.get("canonical_name") or "").strip().casefold()


def _entity_label(entity: dict[str, Any]) -> str:
    return canonical_entity_type(str(entity.get("type") or (entity.get("projection_record") or {}).get("label") or ""))


def _has_human_review(entity: dict[str, Any]) -> bool:
    statuses = {str(value).casefold() for value in entity.get("mention_review_statuses") or []}
    if statuses & {"accepted", "rejected"}:
        return True
    sources = {str(value).casefold() for value in (entity.get("projection_record") or {}).get("model_sources") or []}
    return any("human" in source for source in sources)


def _average_mention_confidence(entity: dict[str, Any]) -> float:
    values = [float(item.get("confidence") or 0.0) for item in entity.get("mentions") or []]
    return sum(values) / len(values) if values else 0.0
