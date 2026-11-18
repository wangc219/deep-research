"""治理跨 Chunk、跨文档同名实体的类型冲突。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Protocol

from platform_core.knowledge.graphs.lightrag_candidate_review import entity_type_surface_hints

TYPE_CONFLICT_POLICY_VERSION = "defense-cross-document-type-governance-v1"
TYPE_CONFLICT_STATUSES = frozenset({"relabel", "keep_separate", "ambiguous"})


class EntityTypeConflictProfileLoader(Protocol):
    """隔离 PostgreSQL 同名跨类型画像查询。"""

    async def load_entity_type_conflict_profiles(
        self,
        *,
        kb_id: str,
        normalized_names: list[str],
    ) -> dict[str, list[dict[str, Any]]]: ...


@dataclass(frozen=True)
class EntityTypeConflictDecision:
    """同名跨类型冲突的封闭决策。"""

    incoming_entity_id: str
    current_label: str
    status: str
    target_entity_id: str | None
    recommended_label: str | None
    candidates: tuple[dict[str, Any], ...]
    reason_code: str
    reason: str
    policy_version: str = TYPE_CONFLICT_POLICY_VERSION
    source: str = "deterministic_type_governance"
    confidence: float | None = None
    auto_apply: bool = False
    model_spec: str | None = None


async def resolve_entity_type_conflicts(
    *,
    kb_id: str,
    entities: list[dict[str, Any]],
    unresolved_entity_ids: set[str],
    profile_loader: EntityTypeConflictProfileLoader,
) -> list[EntityTypeConflictDecision]:
    """读取同名异型标准实体，先以高精度表面规则判定可安全纠偏项。"""

    incoming = [item for item in entities if str(item["entity_id"]) in unresolved_entity_ids]
    normalized_names = list(dict.fromkeys(str(item.get("normalized_name") or "").strip() for item in incoming))
    normalized_names = [item for item in normalized_names if item]
    if not normalized_names:
        return []

    profiles_by_name = await profile_loader.load_entity_type_conflict_profiles(
        kb_id=kb_id,
        normalized_names=normalized_names,
    )
    if not isinstance(profiles_by_name, dict):
        raise TypeError("实体类型冲突画像加载器必须返回字典")
    decisions = []
    for entity in incoming:
        normalized_name = str(entity.get("normalized_name") or "").strip()
        current_label = str(entity.get("label") or "").strip()
        candidates = tuple(
            profile
            for profile in profiles_by_name.get(normalized_name, [])
            if str(profile.get("entity_id") or "") != str(entity["entity_id"])
            and str(profile.get("label") or "") != current_label
        )
        if not candidates:
            continue
        decisions.append(
            decide_entity_type_conflict(
                entity=entity,
                candidates=candidates,
            )
        )
    return decisions


def decide_entity_type_conflict(
    *,
    entity: dict[str, Any],
    candidates: tuple[dict[str, Any], ...],
) -> EntityTypeConflictDecision:
    """只在唯一高精度术语提示命中唯一既有类型时自动纠偏。"""

    incoming_id = str(entity["entity_id"])
    current_label = str(entity.get("label") or "").strip()
    surface = str(entity.get("name") or entity.get("normalized_name") or "").strip()
    hinted_labels = {str(item["suggested_label"]) for item in entity_type_surface_hints(surface)}
    candidate_by_label: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        candidate_by_label.setdefault(str(candidate.get("label") or ""), []).append(candidate)

    if len(hinted_labels) == 1:
        hinted_label = next(iter(hinted_labels))
        matching = candidate_by_label.get(hinted_label, [])
        if hinted_label == current_label:
            return EntityTypeConflictDecision(
                incoming_entity_id=incoming_id,
                current_label=current_label,
                status="keep_separate",
                target_entity_id=None,
                recommended_label=current_label,
                candidates=candidates,
                reason_code="surface_hint_supports_incoming_type",
                reason="唯一高精度术语后缀支持当前类型；保留独立实体并记录既有跨类型冲突",
                confidence=1.0,
            )
        if len(matching) == 1:
            target = matching[0]
            return EntityTypeConflictDecision(
                incoming_entity_id=incoming_id,
                current_label=current_label,
                status="relabel",
                target_entity_id=str(target["entity_id"]),
                recommended_label=hinted_label,
                candidates=candidates,
                reason_code="unique_surface_hint_matches_existing_type",
                reason="唯一高精度术语后缀命中唯一同名既有类型，可在 UUID 分配前确定性纠偏",
                confidence=1.0,
                auto_apply=True,
            )

    return EntityTypeConflictDecision(
        incoming_entity_id=incoming_id,
        current_label=current_label,
        status="ambiguous",
        target_entity_id=None,
        recommended_label=None,
        candidates=candidates,
        reason_code="cross_type_exact_name_requires_context",
        reason="同一标准名已存在不同类型，表面规则不足以安全判定，进入封闭 LLM 判型",
    )


def apply_entity_type_conflict_decisions(
    *,
    entities: list[dict[str, Any]],
    triples: list[dict[str, Any]],
    decisions: list[EntityTypeConflictDecision],
) -> set[str]:
    """应用已获准的类型纠偏并保存其余建议，不改写未获准的权威类型。"""

    by_id = {str(item["entity_id"]): item for item in entities}
    redirects: dict[str, str] = {}
    applied_incoming_ids: set[str] = set()
    for decision in decisions:
        if decision.status not in TYPE_CONFLICT_STATUSES:
            continue
        entity = by_id.get(decision.incoming_entity_id)
        if entity is None:
            continue
        candidate_by_id = {str(item.get("entity_id") or ""): item for item in decision.candidates}
        target = candidate_by_id.get(str(decision.target_entity_id or ""))
        applied = bool(
            decision.status == "relabel"
            and decision.auto_apply
            and decision.target_entity_id
            and target is not None
            and str(target.get("normalized_name") or "") == str(entity.get("normalized_name") or "")
        )
        _attach_type_governance_metadata(entity, decision, applied=applied)
        if not applied or target is None:
            continue

        redirects[decision.incoming_entity_id] = str(target["entity_id"])
        applied_incoming_ids.add(decision.incoming_entity_id)
        entity["entity_id"] = str(target["entity_id"])
        entity["name"] = str(target.get("name") or entity.get("name") or "")
        entity["normalized_name"] = str(target.get("normalized_name") or entity.get("normalized_name") or "")
        entity["label"] = str(target.get("label") or entity.get("label") or "")

    for triple in triples:
        triple["source_entity_id"] = redirects.get(
            str(triple["source_entity_id"]),
            str(triple["source_entity_id"]),
        )
        triple["target_entity_id"] = redirects.get(
            str(triple["target_entity_id"]),
            str(triple["target_entity_id"]),
        )
    return applied_incoming_ids


def recommend_entity_type_conflict(
    decision: EntityTypeConflictDecision,
    *,
    status: str,
    target_entity_id: str | None,
    reason_code: str,
    reason: str,
    confidence: float,
    model_spec: str,
    auto_apply: bool,
) -> EntityTypeConflictDecision:
    """由 LightRAG 封闭判型器生成不可越权的增强决策。"""

    candidate_by_id = {str(item.get("entity_id") or ""): item for item in decision.candidates}
    target = candidate_by_id.get(str(target_entity_id or ""))
    if status == "relabel" and target is None:
        return decision
    recommended_label = str(target.get("label") or "") if target is not None else decision.current_label
    return replace(
        decision,
        status=status,
        target_entity_id=str(target_entity_id) if target is not None else None,
        recommended_label=recommended_label or None,
        reason_code=reason_code,
        reason=reason,
        source="lightrag_type_governance",
        confidence=confidence,
        auto_apply=bool(status == "relabel" and auto_apply and target is not None),
        model_spec=model_spec,
    )


def decision_to_dict(decision: EntityTypeConflictDecision) -> dict[str, Any]:
    """输出稳定审计结构。"""

    return asdict(decision)


def _attach_type_governance_metadata(
    entity: dict[str, Any],
    decision: EntityTypeConflictDecision,
    *,
    applied: bool,
) -> None:
    attributes = entity.get("attributes")
    normalized = dict(attributes) if isinstance(attributes, dict) else {"extracted": attributes or []}
    normalized["type_governance"] = {
        "status": "relabelled" if applied else decision.status,
        "source": decision.source,
        "policy_version": decision.policy_version,
        "current_label": decision.current_label,
        "recommended_label": decision.recommended_label,
        "target_entity_id": decision.target_entity_id,
        "reason_code": decision.reason_code,
        "reason": decision.reason,
        "confidence": decision.confidence,
        "model_spec": decision.model_spec,
        "candidate_types": sorted(
            {
                str(candidate.get("label") or "")
                for candidate in decision.candidates
                if str(candidate.get("label") or "")
            }
        ),
        "expert_review_required": not applied,
    }
    entity["attributes"] = normalized
