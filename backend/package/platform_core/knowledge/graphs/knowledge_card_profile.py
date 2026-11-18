"""从权威知识记录派生 KnowledgeCard 的 GraphRAG 与创新画像。"""

from __future__ import annotations

from typing import Any

KNOWLEDGE_CARD_PROFILE_VERSION = "defense-knowledge-card-profile-v1"

_SEED_PRIORITY = {
    "Capability": 0,
    "ApplicationScenario": 1,
    "ProductSystem": 2,
    "KeyTechnology": 3,
    "AlgorithmModel": 4,
    "Material": 5,
    "Component": 6,
    "ScientificPrinciple": 7,
    "Metric": 8,
    "Constraint": 9,
    "Domain": 10,
    "Achievement": 11,
}
_TRANSFER_RELATIONS = {"TRANSFERABLE_TO", "COMBINES_WITH", "APPLIED_TO", "SUPPORTS_APPLICATION"}
_EXPLORATORY_RELATIONS = {"POTENTIAL_FOR", "TRANSFERABLE_TO", "COMBINES_WITH", "PREDICTED_LINK"}
_TECHNOLOGY_TYPES = {"KeyTechnology", "AlgorithmModel", "Material", "Component", "ScientificPrinciple"}
_APPLICATION_TYPES = {"ApplicationScenario", "ProductSystem", "Domain"}


def build_knowledge_card_profile(
    *,
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    triage: dict[str, Any],
    threads: list[dict[str, Any]],
    evidence_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    """生成不冒充事实的指标、迁移、GraphRAG 与叙事画像。"""
    entity_by_id = {str(item.get("entity_id") or ""): item for item in entities}
    key_metrics = _key_metrics(entities)
    transfer_potential = _transfer_potential(entities, relations)
    graph_rag_hints = _graph_rag_hints(entities, relations, entity_by_id, key_metrics)
    narrative_report = _narrative_report(
        triage=triage,
        threads=threads,
        evidence_refs=evidence_refs,
        key_metrics=key_metrics,
        transfer_potential=transfer_potential,
        graph_rag_hints=graph_rag_hints,
    )
    return {
        "key_metrics": key_metrics,
        "transfer_potential": transfer_potential,
        "graph_rag_hints": graph_rag_hints,
        "narrative_report": narrative_report,
    }


def _key_metrics(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for entity in entities:
        if _entity_type(entity) != "Metric":
            continue
        mentions = list(entity.get("mentions") or [])
        statuses = {str(item.get("review_status") or "pending") for item in mentions}
        result.append(
            {
                "entity_id": str(entity.get("entity_id") or ""),
                "name": _entity_name(entity),
                "evidence_count": len(mentions),
                "review_status": "accepted" if "accepted" in statuses else "pending",
            }
        )
    return [item for item in result if item["entity_id"] and item["name"]][:20]


def _transfer_potential(entities: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, Any]:
    relation_ids = [
        str(item.get("triple_id") or "")
        for item in relations
        if str(item.get("relation_type") or "") in _TRANSFER_RELATIONS
    ]
    applications = [_entity_name(item) for item in entities if _entity_type(item) in _APPLICATION_TYPES]
    applications = list(dict.fromkeys(item for item in applications if item))
    technology_count = sum(1 for item in entities if _entity_type(item) in _TECHNOLOGY_TYPES)
    score = min(1.0, len(relation_ids) * 0.12 + len(applications) * 0.04 + min(technology_count, 5) * 0.02)
    return {
        "score": round(score, 4),
        "supporting_relation_ids": [item for item in relation_ids if item][:30],
        "candidate_application_directions": applications[:12],
        "claim_level": "Inference",
        "expert_review_required": bool(score),
        "algorithm_version": KNOWLEDGE_CARD_PROFILE_VERSION,
    }


def _graph_rag_hints(
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    entity_by_id: dict[str, dict[str, Any]],
    key_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    seeds = []
    for entity in sorted(
        entities,
        key=lambda item: (_SEED_PRIORITY.get(_entity_type(item), 99), _entity_name(item)),
    ):
        entity_id = str(entity.get("entity_id") or "")
        name = _entity_name(entity)
        if not entity_id or not name:
            continue
        mentions = list(entity.get("mentions") or [])
        seeds.append(
            {
                "entity_id": entity_id,
                "name": name,
                "type": _entity_type(entity),
                "accepted_evidence": any(item.get("review_status") == "accepted" for item in mentions),
            }
        )
        if len(seeds) >= 12:
            break

    paths = []
    weak_signals = []
    edge_candidates = []
    for relation in relations:
        relation_id = str(relation.get("triple_id") or "")
        relation_type = str(relation.get("relation_type") or "")
        claim_level = str(relation.get("claim_level") or "Inference")
        review_status = str(relation.get("review_status") or "pending")
        evidence_spans = list(relation.get("evidence_spans") or [])
        source_id = str(relation.get("source_entity_id") or "")
        target_id = str(relation.get("target_entity_id") or "")
        path = {
            "relation_id": relation_id,
            "relation_type": relation_type,
            "source": _entity_summary(entity_by_id.get(source_id), source_id),
            "target": _entity_summary(entity_by_id.get(target_id), target_id),
            "claim_level": claim_level,
            "review_status": review_status,
            "evidence_count": len(evidence_spans),
            "eligible_for_trusted_query": bool(
                review_status == "accepted" and claim_level in {"Fact", "Inference"} and evidence_spans
            ),
        }
        if relation_id and source_id and target_id:
            paths.append(path)
        if claim_level in {"Hypothesis", "Predicted"} or relation_type in _EXPLORATORY_RELATIONS:
            edge_candidates.append(relation_id)
            weak_signals.append(
                {
                    "relation_id": relation_id,
                    "relation_type": relation_type,
                    "claim_level": claim_level,
                    "review_status": review_status,
                    "validation_needed": "复核原文证据、适用条件与跨场景可迁移性。",
                }
            )

    technologies = [item["name"] for item in seeds if item["type"] in _TECHNOLOGY_TYPES]
    capabilities = [item["name"] for item in seeds if item["type"] == "Capability"]
    applications = [item["name"] for item in seeds if item["type"] in _APPLICATION_TYPES]
    follow_up_queries = []
    if technologies and capabilities:
        follow_up_queries.append(f"验证{technologies[0]}对{capabilities[0]}的作用条件、指标收益与证据强度")
    if technologies and applications:
        follow_up_queries.append(f"评估{technologies[0]}迁移到{applications[0]}的工程约束与验证路径")
    if not key_metrics:
        follow_up_queries.append("补充检索可量化性能指标、测试条件和对照基线")

    return {
        "seed_entities": seeds,
        "recommended_paths": paths[:20],
        "weak_signals": weak_signals[:20],
        "edge_prediction_candidate_ids": [item for item in edge_candidates if item][:30],
        "follow_up_queries": follow_up_queries,
        "trusted_path_count": sum(1 for item in paths if item["eligible_for_trusted_query"]),
        "algorithm_version": KNOWLEDGE_CARD_PROFILE_VERSION,
    }


def _narrative_report(
    *,
    triage: dict[str, Any],
    threads: list[dict[str, Any]],
    evidence_refs: list[dict[str, Any]],
    key_metrics: list[dict[str, Any]],
    transfer_potential: dict[str, Any],
    graph_rag_hints: dict[str, Any],
) -> dict[str, str]:
    main_thread = next((item for item in threads if item.get("thread_type") == "main"), threads[0] if threads else {})
    technical_line = list(main_thread.get("technical_line") or [])
    capabilities = list(main_thread.get("capability_direction") or [])
    applications = list(main_thread.get("application_direction") or [])
    rebuildable = sum(1 for item in evidence_refs if item.get("rebuildable"))
    trusted_paths = int(graph_rag_hints.get("trusted_path_count") or 0)
    return {
        "military_value": str(triage.get("military_value_reason") or triage.get("reason") or "待人工研判"),
        "innovation_value": (
            f"当前迁移潜力评分为 {float(transfer_potential.get('score') or 0):.2f}，"
            f"识别 {len(graph_rag_hints.get('edge_prediction_candidate_ids') or [])} 条待验证创新关联。"
        ),
        "technical_chain": " → ".join([*technical_line[:4], *capabilities[:2]]) or "尚未形成可解释技术链。",
        "application_scenarios": "、".join(applications[:6]) or "尚未抽取明确应用场景。",
        "evidence_and_uncertainty": (
            f"当前有 {rebuildable}/{len(evidence_refs)} 条证据 Span 可由原文重建，"
            f"{trusted_paths} 条路径满足已接受且有证据的受信查询条件；其余结果需按审核状态复核。"
        ),
        "recommended_next_step": (
            "优先核验关键指标与受信路径，再开展跨场景迁移评估。"
            if key_metrics and trusted_paths
            else "优先补充指标、适用条件和独立证据，并完成人工审核后再用于方案生成。"
        ),
    }


def _entity_type(entity: dict[str, Any] | None) -> str:
    if not entity:
        return ""
    return str(entity.get("label") or entity.get("type") or "")


def _entity_name(entity: dict[str, Any] | None) -> str:
    if not entity:
        return ""
    return str(entity.get("name") or entity.get("canonical_name") or "").strip()


def _entity_summary(entity: dict[str, Any] | None, fallback_id: str) -> dict[str, str]:
    return {
        "entity_id": str((entity or {}).get("entity_id") or fallback_id),
        "name": _entity_name(entity),
        "type": _entity_type(entity),
    }
