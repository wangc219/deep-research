"""从已验证图路径推导待审核创新关联，不把预测边伪装成事实。"""

from __future__ import annotations

import math
from typing import Any

from platform_core.knowledge.graphs.innovation_value_profile import build_innovation_value_profile
from platform_core.utils import hashstr

INNOVATION_ALGORITHM_VERSION = "defense-graph-innovation-v5"
INNOVATION_FEEDBACK_CONTRACT_VERSION = "lightrag-defense-feedback-v1"


def discover_innovation_hypotheses(
    *,
    kb_id: str,
    path_result: dict[str, Any],
    discovery_mode: str,
    max_candidates: int = 10,
    evidence_scope: str = "any",
) -> list[dict[str, Any]]:
    """在非相邻路径节点之间发现缺失关联并形成可审核假设。"""
    normalized_mode = _normalize_mode(discovery_mode)
    normalized_scope = _normalize_evidence_scope(evidence_scope)
    known_relations = _known_relation_keys(path_result)
    retrieval_mode = str((path_result.get("summary") or {}).get("retrieval_mode") or "keyword")
    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in path_result.get("paths") or []:
        file_ids = {str(item) for item in (path.get("evidence") or {}).get("file_ids") or [] if str(item).strip()}
        if normalized_scope == "cross_document" and len(file_ids) < 2:
            continue
        nodes = path.get("nodes") or []
        if len(nodes) < 3:
            continue
        for left_index, left in enumerate(nodes[:-2]):
            for right_index, right in enumerate(nodes[left_index + 2 :], start=left_index + 2):
                critical_relation_ids = [
                    str(item) for item in (path.get("relation_ids") or [])[left_index:right_index] if str(item).strip()
                ]
                if len(critical_relation_ids) != right_index - left_index:
                    continue
                source, target, relation_type = _candidate_direction(left, right, normalized_mode)
                source_id = _entity_id(source)
                target_id = _entity_id(target)
                if not source_id or not target_id or source_id == target_id:
                    continue
                if relation_type == "COMBINES_WITH" and target_id < source_id:
                    source, target = target, source
                    source_id, target_id = target_id, source_id
                if _relation_exists(
                    known_relations,
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=relation_type,
                ):
                    continue
                key = (source_id, target_id, relation_type)
                candidate = _candidate_payload(
                    kb_id=kb_id,
                    source=source,
                    target=target,
                    relation_type=relation_type,
                    path=path,
                    critical_relation_ids=critical_relation_ids,
                    discovery_mode=normalized_mode,
                    retrieval_mode=retrieval_mode,
                    evidence_scope=normalized_scope,
                )
                current = candidates.get(key)
                if current is None or candidate["score"] > current["score"]:
                    candidates[key] = candidate

    anchor_candidate_keys: set[tuple[str, str, str]] = set()
    if normalized_mode == "bottom_up":
        anchor_candidate_keys = _add_query_anchor_candidates(
            kb_id=kb_id,
            path_result=path_result,
            candidates=candidates,
            known_relations=known_relations,
            retrieval_mode=retrieval_mode,
            evidence_scope=normalized_scope,
            max_candidates=max_candidates,
        )

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            _candidate_key(item) in anchor_candidate_keys,
            item["score"],
            item["hypothesis_id"],
        ),
        reverse=True,
    )
    return ranked[: max(1, min(int(max_candidates), 50))]


def _add_query_anchor_candidates(
    *,
    kb_id: str,
    path_result: dict[str, Any],
    candidates: dict[tuple[str, str, str], dict[str, Any]],
    known_relations: set[tuple[str, str, str]],
    retrieval_mode: str,
    evidence_scope: str,
    max_candidates: int,
) -> set[tuple[str, str, str]]:
    """用图中精确查询实体形成上下文假设，避免自下而上结果偏离输入技术。"""
    anchor_candidate_keys: set[tuple[str, str, str]] = set()
    anchors = [item for item in path_result.get("query_anchors") or [] if _entity_id(item)]
    paths = path_result.get("paths") or []
    candidate_limit = max(2, min(int(max_candidates) * 2, 20))
    role_priority = {"technology": 0, "capability": 1, "application": 2, "principle": 3, "concept": 4}
    for anchor in anchors[:6]:
        anchor_id = _entity_id(anchor)
        for path in paths:
            file_ids = {str(item) for item in (path.get("evidence") or {}).get("file_ids") or [] if str(item).strip()}
            if evidence_scope == "cross_document" and len(file_ids) < 2:
                continue
            relation_ids = [str(item) for item in path.get("relation_ids") or [] if str(item).strip()]
            if len(relation_ids) < 2:
                continue
            targets = sorted(
                (node for node in path.get("nodes") or [] if _entity_id(node) != anchor_id),
                key=lambda node: (
                    role_priority.get(str(node.get("semantic_role") or "other"), 5),
                    -float((node.get("properties") or {}).get("query_relevance") or 0.0),
                ),
            )
            for target in targets[:3]:
                source, resolved_target, relation_type = _candidate_direction(anchor, target, "bottom_up")
                source_id = _entity_id(source)
                target_id = _entity_id(resolved_target)
                if not source_id or not target_id or source_id == target_id:
                    continue
                if relation_type == "COMBINES_WITH" and target_id < source_id:
                    source, resolved_target = resolved_target, source
                    source_id, target_id = target_id, source_id
                if _relation_exists(
                    known_relations,
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=relation_type,
                ):
                    continue
                key = (source_id, target_id, relation_type)
                existing = candidates.get(key)
                if existing is not None:
                    existing["query_anchor_match"] = True
                    anchor_candidate_keys.add(key)
                    continue
                contextual_path = {
                    **path,
                    "evidence_gaps": list(
                        dict.fromkeys(
                            [
                                *(path.get("evidence_gaps") or []),
                                "查询锚点与证据路径之间缺少已验证直接关系",
                            ]
                        )
                    ),
                }
                candidate = _candidate_payload(
                    kb_id=kb_id,
                    source=source,
                    target=resolved_target,
                    relation_type=relation_type,
                    path=contextual_path,
                    critical_relation_ids=relation_ids,
                    discovery_mode="bottom_up",
                    retrieval_mode=retrieval_mode,
                    evidence_scope=evidence_scope,
                )
                candidate["query_anchor_match"] = True
                candidate["evidence_path"]["anchor_context_only"] = True
                candidate["evidence_path"]["anchor_entity_id"] = anchor_id
                candidate["mechanism_hypothesis"] = (
                    f"{candidate['source']['name']}与{candidate['target']['name']}可能形成新的技术、能力或应用关联；"
                    "当前多跳关系仅提供上下文证据，不直接证明该候选边"
                )
                candidate["uncertainties"] = list(
                    dict.fromkeys(
                        [
                            "查询锚点目前是图中的孤立或弱连接实体，候选关联需要独立验证",
                            *(candidate.get("uncertainties") or []),
                        ]
                    )
                )
                score_components = dict(candidate.get("score_components") or {})
                score_components["query_anchor_match"] = 1.0
                candidate["score"] = round(min(float(candidate.get("score") or 0.0) + 0.06, 1.0), 4)
                score_components["score"] = candidate["score"]
                candidate["score_components"] = score_components
                candidates[key] = candidate
                anchor_candidate_keys.add(key)
                if len(anchor_candidate_keys) >= candidate_limit:
                    return anchor_candidate_keys
    return anchor_candidate_keys


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str((candidate.get("source") or {}).get("entity_id") or ""),
        str((candidate.get("target") or {}).get("entity_id") or ""),
        str(candidate.get("relation_type") or ""),
    )


def innovation_response(
    *,
    query: str,
    discovery_mode: str,
    candidates: list[dict[str, Any]],
    graph_revision: str | None,
    query_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成平台创新模块使用的固定、可追溯响应契约。"""
    return {
        "query": query,
        "mode": _normalize_mode(discovery_mode),
        "query_analysis": query_analysis or {},
        "entities": _unique_entities(candidates),
        "path": [candidate["evidence_path"] for candidate in candidates],
        "evidence": [
            {
                "hypothesis_id": candidate["hypothesis_id"],
                "chunk_ids": candidate["evidence_path"]["chunk_ids"],
                "file_ids": candidate["evidence_path"]["file_ids"],
                "relation_ids": candidate["evidence_path"]["relation_ids"],
            }
            for candidate in candidates
        ],
        "hypotheses": candidates,
        "mechanism_hypothesis": candidates[0]["mechanism_hypothesis"] if candidates else "",
        "feasibility_basis": _unique_text(candidates, "feasibility_basis"),
        "expected_effects": _unique_text(candidates, "expected_effects"),
        "applicable_conditions": _unique_text(candidates, "applicable_conditions"),
        "uncertainties": _unique_text(candidates, "uncertainties"),
        "claim_level": "Hypothesis",
        "graph_revision": graph_revision,
    }


def build_innovation_feedback_loop(
    path_result: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """从既有路径与候选生成再检索/复抽建议，不调用模型或写入事实图谱。"""
    query_plan = path_result.get("query_plan") or {}
    query_analysis = path_result.get("query_analysis") or {}
    requery_terms = _bounded_unique_text(
        [
            *(query_plan.get("low_level_keywords") or []),
            *(query_plan.get("high_level_keywords") or []),
            *(query_plan.get("capability_targets") or []),
            *(query_plan.get("constraints") or []),
            *(query_plan.get("military_value_dimensions") or []),
            *(query_plan.get("weak_signal_terms") or []),
            *(query_analysis.get("target_capabilities") or []),
            *(query_analysis.get("application_scenarios") or []),
            *(query_analysis.get("key_technical_elements") or []),
            *[str((item.get("source") or {}).get("name") or "") for item in candidates],
            *[str((item.get("target") or {}).get("name") or "") for item in candidates],
        ],
        limit=12,
        max_chars=120,
    )
    evidence_gaps = _bounded_unique_text(
        [
            *[str(gap) for path in path_result.get("paths") or [] for gap in path.get("evidence_gaps") or []],
            *[
                str(gap)
                for candidate in candidates
                for gap in (candidate.get("evidence_path") or {}).get("evidence_gaps") or []
            ],
        ],
        limit=12,
        max_chars=240,
    )
    validation_tasks = _bounded_unique_text(
        [
            str(requirement)
            for candidate in candidates
            for requirement in candidate.get("validation_requirements") or []
        ],
        limit=12,
        max_chars=240,
    )

    reextraction_file_ids: list[str] = []
    reextraction_chunk_ids: list[str] = []
    for path in path_result.get("paths") or []:
        if not path.get("evidence_gaps"):
            continue
        evidence = path.get("evidence") or {}
        reextraction_file_ids.extend(str(item) for item in evidence.get("file_ids") or [])
        reextraction_chunk_ids.extend(str(item) for item in evidence.get("chunk_ids") or [])
    for candidate in candidates:
        evidence_path = candidate.get("evidence_path") or {}
        if not evidence_path.get("evidence_gaps"):
            continue
        reextraction_file_ids.extend(str(item) for item in evidence_path.get("file_ids") or [])
        reextraction_chunk_ids.extend(str(item) for item in evidence_path.get("chunk_ids") or [])

    file_ids = _bounded_unique_text(reextraction_file_ids, limit=50, max_chars=128)
    chunk_ids = _bounded_unique_text(reextraction_chunk_ids, limit=100, max_chars=128)
    reextraction_recommended = bool(evidence_gaps and (file_ids or chunk_ids))
    if not candidates:
        status = "no_candidate"
    elif evidence_gaps:
        status = "requires_evidence"
    else:
        status = "ready"
    return {
        "contract_version": INNOVATION_FEEDBACK_CONTRACT_VERSION,
        "status": status,
        "automatic_graph_write": False,
        "requery_terms": requery_terms,
        "evidence_gaps": evidence_gaps,
        "validation_tasks": validation_tasks,
        "reextraction": {
            "recommended": reextraction_recommended,
            "file_ids": file_ids,
            "chunk_ids": chunk_ids,
            "reasons": evidence_gaps if reextraction_recommended else [],
        },
    }


def _bounded_unique_text(values: list[Any], *, limit: int, max_chars: int) -> list[str]:
    """对回环建议去重并施加协议边界。"""
    output = []
    seen = set()
    for value in values:
        normalized = " ".join(str(value or "").split())[:max_chars]
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
        if len(output) >= limit:
            break
    return output


def _candidate_payload(
    *,
    kb_id: str,
    source: dict[str, Any],
    target: dict[str, Any],
    relation_type: str,
    path: dict[str, Any],
    critical_relation_ids: list[str],
    discovery_mode: str,
    retrieval_mode: str,
    evidence_scope: str,
) -> dict[str, Any]:
    source_id = _entity_id(source)
    target_id = _entity_id(target)
    evidence = path.get("evidence") or {}
    inspiration = path.get("research_inspiration") or {}
    gaps = [str(item) for item in path.get("evidence_gaps") or [] if str(item).strip()]
    uncertainties = [str(item) for item in inspiration.get("uncertainties") or [] if str(item).strip()]
    uncertainties.extend(gaps)
    if "该关联尚未由原始证据直接支持" not in uncertainties:
        uncertainties.insert(0, "该关联尚未由原始证据直接支持")
    innovation_profile = build_innovation_value_profile(
        path,
        discovery_mode=discovery_mode,
        relation_type=relation_type,
    )
    score_components = _candidate_score_components(
        path,
        retrieval_mode=retrieval_mode,
        innovation_profile=innovation_profile,
    )
    score = score_components["score"]
    source_name = str(source.get("name") or source_id)
    target_name = str(target.get("name") or target_id)
    hypothesis_id = hashstr(
        f"{kb_id}:{source_id}:{relation_type}:{target_id}:{INNOVATION_ALGORITHM_VERSION}",
        length=32,
    )
    evidence_file_ids = list(dict.fromkeys(str(item) for item in evidence.get("file_ids") or [] if item))
    pending_evidence = bool(path.get("pending_evidence") or evidence.get("pending_evidence"))
    boundary_relation_ids = list(dict.fromkeys((critical_relation_ids[0], critical_relation_ids[-1])))
    minimum_support_count = max(1, math.ceil(len(critical_relation_ids) * 2 / 3))
    return {
        "hypothesis_id": hypothesis_id,
        "kb_id": kb_id,
        "source": _entity_summary(source),
        "target": _entity_summary(target),
        "relation_type": relation_type,
        "discovery_mode": discovery_mode,
        "evidence_scope": evidence_scope,
        "claim_level": "Hypothesis",
        "pending_evidence": pending_evidence,
        "score": score,
        "score_components": score_components,
        "innovation_profile": innovation_profile,
        "evidence_path": {
            "path_id": path.get("path_id"),
            "relation_ids": critical_relation_ids,
            "full_path_relation_ids": list(path.get("relation_ids") or []),
            "boundary_relation_ids": boundary_relation_ids,
            "minimum_support_count": minimum_support_count,
            "chunk_ids": list(evidence.get("chunk_ids") or []),
            "file_ids": evidence_file_ids,
            "document_count": len(evidence_file_ids),
            "cross_document": len(evidence_file_ids) >= 2,
            "support_level": "multi_source" if len(evidence_file_ids) >= 2 else "single_source",
            "review_statuses": list(evidence.get("review_statuses") or []),
            "pending_relation_count": int(evidence.get("pending_relation_count") or 0),
            "pending_evidence": pending_evidence,
            "evidence_gaps": gaps,
            "research_threads": _research_threads(inspiration),
            "semantic_closures": list(path.get("semantic_closures") or []),
            "relation_signature": dict(path.get("relation_signature") or {}),
        },
        "mechanism_hypothesis": f"{source_name}可能通过现有证据路径中的中间机理或技术环节关联到{target_name}",
        "feasibility_basis": _feasibility_basis(path),
        "expected_effects": list(
            dict.fromkeys(
                [
                    *[str(item) for item in inspiration.get("expected_capability_gains") or []],
                    *[str(item) for item in inspiration.get("application_directions") or []],
                ]
            )
        ),
        "applicable_conditions": list(
            dict.fromkeys(str(item) for item in inspiration.get("applicable_conditions") or [] if str(item).strip())
        ),
        "validation_requirements": _validation_requirements(path, source_name=source_name, target_name=target_name),
        "falsification_criteria": [
            f"在声明的适用条件和对照条件下，{source_name}未对{target_name}产生可重复、可测量的预期影响",
        ],
        "constraint_conflicts": [],
        "uncertainties": list(dict.fromkeys(uncertainties)),
        "algorithm_version": INNOVATION_ALGORITHM_VERSION,
        "review_status": "pending",
        "expert_review_required": True,
    }


def _candidate_direction(
    left: dict[str, Any],
    right: dict[str, Any],
    discovery_mode: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    left_role = str(left.get("semantic_role") or "other")
    right_role = str(right.get("semantic_role") or "other")
    pair = {left_role, right_role}
    if pair == {"technology", "capability"}:
        return (*_ordered(left, right, "technology"), "POTENTIAL_FOR")
    if "technology" in pair and "application" in pair:
        return (*_ordered(left, right, "technology"), "TRANSFERABLE_TO")
    if "principle" in pair and ("capability" in pair or "application" in pair):
        return (*_ordered(left, right, "principle"), "POTENTIAL_FOR")
    if left_role == right_role == "technology":
        return left, right, "COMBINES_WITH"
    if discovery_mode == "bottom_up":
        order = {"principle": 0, "technology": 1, "capability": 2, "application": 3, "concept": 4, "other": 5}
    else:
        order = {"technology": 0, "principle": 1, "capability": 2, "application": 3, "concept": 4, "other": 5}
    return (
        (left, right, "PREDICTED_LINK")
        if order.get(left_role, 5) <= order.get(right_role, 5)
        else (
            right,
            left,
            "PREDICTED_LINK",
        )
    )


def _ordered(left: dict[str, Any], right: dict[str, Any], source_role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return (left, right) if left.get("semantic_role") == source_role else (right, left)


def _candidate_score_components(
    path: dict[str, Any],
    *,
    retrieval_mode: str,
    innovation_profile: dict[str, Any],
) -> dict[str, Any]:
    path_score = min(max(float(path.get("score") or 0.0) / 6.0, 0.0), 1.0)
    coverage = min(max(float(path.get("semantic_coverage") or 0.0), 0.0), 1.0)
    evidence = path.get("evidence") or {}
    mention_score = min(int(evidence.get("mention_count") or 0) / 6.0, 1.0)
    source_score = 1.0 if evidence.get("support_level") == "multi_source" else 0.5
    semantic_score = _semantic_relevance(path, retrieval_mode=retrieval_mode)
    semantic_closures = list(path.get("semantic_closures") or [])
    closure_score = min(len(semantic_closures) / 2.0, 1.0)
    invalid_signature_count = int((path.get("relation_signature") or {}).get("invalid_count") or 0)
    gap_penalty = min(len(path.get("evidence_gaps") or []) * 0.04, 0.2)
    signature_penalty = min(invalid_signature_count * 0.12, 0.36)
    weighted_score = (
        path_score * 0.32
        + coverage * 0.14
        + mention_score * 0.14
        + source_score * 0.1
        + semantic_score * 0.15
        + closure_score * 0.15
    )
    evidence_score = max(0.0, min(weighted_score - gap_penalty - signature_penalty, 1.0))
    strategic_score = float(innovation_profile.get("strategic_score") or 0.0)
    score = evidence_score * 0.72 + strategic_score * 0.28
    return {
        "score": round(max(0.0, min(score, 1.0)), 4),
        "evidence_score": round(evidence_score, 4),
        "strategic_value": round(strategic_score, 4),
        "path_structure": round(path_score, 4),
        "role_coverage": round(coverage, 4),
        "evidence_mentions": round(mention_score, 4),
        "source_diversity": round(source_score, 4),
        "semantic_similarity": round(semantic_score, 4),
        "semantic_closure": round(closure_score, 4),
        "gap_penalty": round(gap_penalty, 4),
        "relation_signature_penalty": round(signature_penalty, 4),
        "retrieval_mode": retrieval_mode,
    }


def _semantic_relevance(path: dict[str, Any], *, retrieval_mode: str) -> float:
    """汇总路径节点的语义召回相关度；关键词回退使用中性分，避免伪造语义值。"""
    if retrieval_mode not in {"semantic", "local", "global", "hybrid", "mix"}:
        return 0.5
    values = []
    for node in path.get("nodes") or []:
        properties = node.get("properties") or {}
        if properties.get("query_relevance") is not None:
            values.append(max(0.0, min(float(properties["query_relevance"]), 1.0)))
    return sum(values) / len(values) if values else 0.0


def _known_relation_keys(path_result: dict[str, Any]) -> set[tuple[str, str, str]]:
    rows = (path_result.get("candidate_context") or {}).get("known_relations") or []
    return {
        (
            str(item.get("source_entity_id") or "").strip(),
            str(item.get("target_entity_id") or "").strip(),
            str(item.get("relation_type") or "").strip().upper(),
        )
        for item in rows
        if item.get("source_entity_id") and item.get("target_entity_id") and item.get("relation_type")
    }


def _relation_exists(
    known_relations: set[tuple[str, str, str]],
    *,
    source_id: str,
    target_id: str,
    relation_type: str,
) -> bool:
    key = (source_id, target_id, relation_type.upper())
    if key in known_relations:
        return True
    return relation_type == "COMBINES_WITH" and (target_id, source_id, relation_type) in known_relations


def _feasibility_basis(path: dict[str, Any]) -> list[str]:
    inspiration = path.get("research_inspiration") or {}
    values = []
    for item in inspiration.get("value_signals") or []:
        if isinstance(item, dict) and item.get("text"):
            values.append(str(item["text"]))
    if path.get("relation_ids"):
        values.append(f"已有证据路径包含 {len(path['relation_ids'])} 条已记录关系")
    return list(dict.fromkeys(values))


def _research_threads(inspiration: dict[str, Any]) -> dict[str, list[str]]:
    """把研究线索随证据路径传给创新结果，不把线索升级为事实。"""
    source = inspiration.get("research_threads") or {}
    if not isinstance(source, dict):
        return {thread: [] for thread in ("main", "side", "parallel")}
    return {
        thread: list(dict.fromkeys(str(item).strip() for item in source.get(thread) or [] if str(item).strip()))[:12]
        for thread in ("main", "side", "parallel")
    }


def _validation_requirements(path: dict[str, Any], *, source_name: str, target_name: str) -> list[str]:
    inspiration = path.get("research_inspiration") or {}
    values = [str(item) for item in inspiration.get("review_questions") or [] if str(item).strip()]
    values.append(f"使用独立数据或受控试验验证{source_name}到{target_name}的增量作用与边界条件")
    return list(dict.fromkeys(values))


def _entity_id(node: dict[str, Any]) -> str:
    properties = node.get("properties") or {}
    return str(properties.get("entity_id") or node.get("entity_id") or "").strip()


def _entity_summary(node: dict[str, Any]) -> dict[str, str]:
    return {
        "entity_id": _entity_id(node),
        "name": str(node.get("name") or ""),
        "type": str(node.get("type") or ""),
        "semantic_role": str(node.get("semantic_role") or "other"),
    }


def _unique_entities(candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        for key in ("source", "target"):
            entity = candidate[key]
            result.setdefault(entity["entity_id"], entity)
    return list(result.values())


def _unique_text(candidates: list[dict[str, Any]], field: str) -> list[str]:
    return list(
        dict.fromkeys(str(item) for candidate in candidates for item in candidate.get(field) or [] if str(item).strip())
    )


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "top_down").strip().lower()
    aliases = {
        "requirement_driven": "top_down",
        "top_down": "top_down",
        "entity_expansion": "bottom_up",
        "bottom_up": "bottom_up",
    }
    if normalized not in aliases:
        raise ValueError("discovery_mode 必须是 top_down 或 bottom_up")
    return aliases[normalized]


def _normalize_evidence_scope(value: str) -> str:
    normalized = str(value or "any").strip().lower()
    if normalized not in {"any", "cross_document"}:
        raise ValueError("evidence_scope 必须是 any 或 cross_document")
    return normalized
