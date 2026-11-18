"""以类型硬约束、语义分数和上下文分差完成保守实体对齐。"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol


class EntityCandidateSearcher(Protocol):
    """隔离 Milvus 等候选召回实现。"""

    async def search_entities(
        self,
        *,
        kb_id: str,
        query_text: str,
        embedding_model_spec: str,
        top_k: int,
    ) -> list[dict[str, Any]]: ...


class EntityProfileLoader(Protocol):
    """隔离 PostgreSQL 标准实体画像读取。"""

    async def load_entity_alignment_profiles(
        self,
        *,
        kb_id: str,
        entity_ids: list[str],
    ) -> dict[str, dict[str, Any]]: ...


@dataclass(frozen=True)
class EntityAlignmentPolicy:
    """实体语义对齐的版本化保守阈值。"""

    policy_version: str = "defense-entity-alignment-v1"
    top_k: int = 5
    candidate_floor: float = 0.75
    auto_link_min_score: float = 0.90
    auto_link_min_margin: float = 0.05
    context_weight: float = 0.03
    neighbor_weight: float = 0.02


@dataclass(frozen=True)
class EntityAlignmentDecision:
    """单个候选实体的对齐结论。"""

    incoming_entity_id: str
    status: str
    target_entity_id: str | None
    candidates: tuple[dict[str, Any], ...]
    reason: str
    policy_version: str
    source: str = "semantic"
    model_spec: str | None = None
    model_confidence: float | None = None
    recommended_target_entity_id: str | None = None


async def resolve_semantic_entity_alignments(
    *,
    kb_id: str,
    embedding_model_spec: str,
    entities: list[dict[str, Any]],
    triples: list[dict[str, Any]],
    unresolved_entity_ids: set[str],
    searcher: EntityCandidateSearcher,
    profile_loader: EntityProfileLoader,
    policy: EntityAlignmentPolicy | None = None,
) -> list[EntityAlignmentDecision]:
    """批量召回候选并返回可审计决策，不直接执行数据库写入。"""
    active_policy = policy or EntityAlignmentPolicy()
    incoming = [item for item in entities if str(item["entity_id"]) in unresolved_entity_ids]
    if not incoming or not embedding_model_spec:
        return []

    context_by_id = _incoming_contexts(entities, triples)
    hits_by_id = await _search_candidates(
        kb_id=kb_id,
        embedding_model_spec=embedding_model_spec,
        entities=incoming,
        contexts=context_by_id,
        searcher=searcher,
        policy=active_policy,
    )
    candidate_ids = list(dict.fromkeys(str(hit["id"]) for hits in hits_by_id.values() for hit in hits if hit.get("id")))
    profiles = await profile_loader.load_entity_alignment_profiles(
        kb_id=kb_id,
        entity_ids=candidate_ids,
    )
    return [
        decide_semantic_entity_alignment(
            entity=entity,
            context=context_by_id.get(str(entity["entity_id"]), {}),
            vector_hits=hits_by_id.get(str(entity["entity_id"]), []),
            profiles=profiles,
            policy=active_policy,
        )
        for entity in incoming
    ]


def decide_semantic_entity_alignment(
    *,
    entity: dict[str, Any],
    context: dict[str, set[str]],
    vector_hits: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
    policy: EntityAlignmentPolicy | None = None,
) -> EntityAlignmentDecision:
    """仅在类型一致、得分达标且领先分差足够时自动链接。"""
    active_policy = policy or EntityAlignmentPolicy()
    incoming_id = str(entity["entity_id"])
    incoming_label = str(entity["label"])
    scored = []
    for hit in vector_hits:
        candidate_id = str(hit.get("id") or "")
        profile = profiles.get(candidate_id)
        if not candidate_id or candidate_id == incoming_id or not profile:
            continue
        if str(profile.get("label") or "") != incoming_label:
            continue
        vector_score = max(0.0, min(float(hit.get("score") or 0.0), 1.0))
        if vector_score < active_policy.candidate_floor:
            continue
        profile_terms = _profile_terms(profile)
        context_overlap = _jaccard(context.get("terms", set()), profile_terms["terms"])
        neighbor_overlap = _jaccard(context.get("neighbors", set()), profile_terms["neighbors"])
        score = min(
            1.0,
            vector_score
            + active_policy.context_weight * context_overlap
            + active_policy.neighbor_weight * neighbor_overlap,
        )
        scored.append(
            {
                "entity_id": candidate_id,
                "name": profile.get("name"),
                "normalized_name": profile.get("normalized_name"),
                "label": profile.get("label"),
                "vector_score": round(vector_score, 4),
                "context_overlap": round(context_overlap, 4),
                "neighbor_overlap": round(neighbor_overlap, 4),
                "score": round(score, 4),
                "aliases": [str(item)[:256] for item in list(profile.get("aliases") or [])[:20]],
                "attributes": profile.get("attributes") or {},
                "neighbors": [str(item)[:256] for item in list(profile.get("neighbors") or [])[:20]],
            }
        )
    scored.sort(key=lambda item: (-item["score"], item["entity_id"]))
    if not scored:
        return EntityAlignmentDecision(
            incoming_entity_id=incoming_id,
            status="new",
            target_entity_id=None,
            candidates=(),
            reason="没有满足类型约束和候选下限的既有实体",
            policy_version=active_policy.policy_version,
        )

    top = scored[0]
    runner_up_score = scored[1]["score"] if len(scored) > 1 else 0.0
    margin = top["score"] - runner_up_score
    top["margin"] = round(margin, 4)
    if top["score"] >= active_policy.auto_link_min_score and margin >= active_policy.auto_link_min_margin:
        return EntityAlignmentDecision(
            incoming_entity_id=incoming_id,
            status="linked",
            target_entity_id=top["entity_id"],
            candidates=tuple(scored),
            reason="类型一致，语义得分和领先分差均达到自动链接阈值",
            policy_version=active_policy.policy_version,
        )
    return EntityAlignmentDecision(
        incoming_entity_id=incoming_id,
        status="ambiguous",
        target_entity_id=None,
        candidates=tuple(scored),
        reason="候选未同时满足自动链接得分和领先分差，转人工审核",
        policy_version=active_policy.policy_version,
    )


def apply_entity_alignment_decisions(
    *,
    entities: list[dict[str, Any]],
    triples: list[dict[str, Any]],
    decisions: list[EntityAlignmentDecision],
    exact_ambiguities: dict[str, list[str]] | None = None,
) -> None:
    """应用自动链接并把歧义候选写入待审核实体属性。"""
    by_id = {str(item["entity_id"]): item for item in entities}
    redirects = {}
    for incoming_id, candidate_ids in (exact_ambiguities or {}).items():
        entity = by_id.get(incoming_id)
        if entity is not None:
            _attach_alignment_metadata(
                entity,
                {
                    "status": "ambiguous",
                    "source": "exact_alias",
                    "candidate_entity_ids": candidate_ids,
                    "reason": "同一别名命中多个同类型标准实体",
                    "expert_review_required": True,
                },
            )

    for decision in decisions:
        entity = by_id.get(decision.incoming_entity_id)
        if entity is None:
            continue
        if decision.status == "linked" and decision.target_entity_id:
            if decision.source == "lightrag_llm_alignment":
                _attach_alignment_metadata(
                    entity,
                    {
                        "status": "linked",
                        "source": decision.source,
                        "policy_version": decision.policy_version,
                        "reason": decision.reason,
                        "target_entity_id": decision.target_entity_id,
                        "model_spec": decision.model_spec,
                        "model_confidence": decision.model_confidence,
                        "expert_review_required": False,
                    },
                )
            redirects[decision.incoming_entity_id] = decision.target_entity_id
            entity["entity_id"] = decision.target_entity_id
            target = decision.candidates[0]
            entity["name"] = target.get("name") or entity.get("name")
            entity["normalized_name"] = target.get("normalized_name") or entity.get("normalized_name")
            entity["label"] = target.get("label") or entity.get("label")
            continue
        if decision.status == "ambiguous":
            _attach_alignment_metadata(
                entity,
                {
                    "status": decision.status,
                    "source": decision.source,
                    "policy_version": decision.policy_version,
                    "reason": decision.reason,
                    "candidates": list(decision.candidates),
                    "model_spec": decision.model_spec,
                    "model_confidence": decision.model_confidence,
                    "recommended_target_entity_id": decision.recommended_target_entity_id,
                    "expert_review_required": True,
                },
            )
        elif decision.status == "new" and decision.source == "lightrag_llm_alignment":
            _attach_alignment_metadata(
                entity,
                {
                    "status": "new",
                    "source": decision.source,
                    "policy_version": decision.policy_version,
                    "reason": decision.reason,
                    "model_spec": decision.model_spec,
                    "model_confidence": decision.model_confidence,
                    "expert_review_required": True,
                },
            )
    for triple in triples:
        triple["source_entity_id"] = redirects.get(
            str(triple["source_entity_id"]),
            str(triple["source_entity_id"]),
        )
        triple["target_entity_id"] = redirects.get(
            str(triple["target_entity_id"]),
            str(triple["target_entity_id"]),
        )


async def _search_candidates(
    *,
    kb_id: str,
    embedding_model_spec: str,
    entities: list[dict[str, Any]],
    contexts: dict[str, dict[str, set[str]]],
    searcher: EntityCandidateSearcher,
    policy: EntityAlignmentPolicy,
) -> dict[str, list[dict[str, Any]]]:
    async def search(entity: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        entity_id = str(entity["entity_id"])
        context = contexts.get(entity_id, {})
        query_parts = [str(entity.get("normalized_name") or entity.get("name") or "")]
        query_parts.extend(sorted(context.get("neighbors", set())))
        hits = await searcher.search_entities(
            kb_id=kb_id,
            query_text=" ".join(query_parts)[:2000],
            embedding_model_spec=embedding_model_spec,
            top_k=policy.top_k,
        )
        return entity_id, hits

    return dict(await asyncio.gather(*(search(entity) for entity in entities)))


def _incoming_contexts(
    entities: list[dict[str, Any]],
    triples: list[dict[str, Any]],
) -> dict[str, dict[str, set[str]]]:
    by_id = {str(item["entity_id"]): item for item in entities}
    contexts = {
        entity_id: {
            "terms": _text_terms(json.dumps(item.get("attributes") or [], ensure_ascii=False)),
            "neighbors": set(),
        }
        for entity_id, item in by_id.items()
    }
    for triple in triples:
        source_id = str(triple["source_entity_id"])
        target_id = str(triple["target_entity_id"])
        if source_id in contexts and target_id in by_id:
            contexts[source_id]["neighbors"].update(_entity_terms(by_id[target_id]))
        if target_id in contexts and source_id in by_id:
            contexts[target_id]["neighbors"].update(_entity_terms(by_id[source_id]))
    return contexts


def _profile_terms(profile: dict[str, Any]) -> dict[str, set[str]]:
    texts = [profile.get("name"), profile.get("normalized_name"), *(profile.get("aliases") or [])]
    texts.append(json.dumps(profile.get("attributes") or {}, ensure_ascii=False))
    return {
        "terms": _text_terms(" ".join(str(item or "") for item in texts)),
        "neighbors": _text_terms(" ".join(str(item or "") for item in profile.get("neighbors") or [])),
    }


def _entity_terms(entity: dict[str, Any]) -> set[str]:
    return _text_terms(f"{entity.get('normalized_name') or ''} {entity.get('label') or ''}")


def _text_terms(value: str) -> set[str]:
    normalized = value.casefold()
    latin = set(re.findall(r"[a-z0-9][a-z0-9_.+-]*", normalized))
    chinese_sequences = re.findall(r"[\u4e00-\u9fff]+", normalized)
    chinese_bigrams = {
        sequence[index : index + 2] for sequence in chinese_sequences for index in range(max(len(sequence) - 1, 0))
    }
    return latin | chinese_bigrams


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _attach_alignment_metadata(entity: dict[str, Any], alignment: dict[str, Any]) -> None:
    attributes = entity.get("attributes")
    if isinstance(attributes, dict):
        normalized = dict(attributes)
    else:
        normalized = {"extracted": attributes or []}
    normalized["alignment"] = alignment
    entity["attributes"] = normalized


def decision_to_dict(decision: EntityAlignmentDecision) -> dict[str, Any]:
    """为日志、测试和审计输出稳定 JSON 结构。"""
    return asdict(decision)
