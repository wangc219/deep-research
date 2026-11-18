from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from platform_core.knowledge.graphs.core_semantic_roles import RESEARCH_THREAD_TYPES, core_role_for_entity_type
from platform_core.knowledge.graphs.defense_ontology import DEFENSE_ONTOLOGY_V1, validate_relation_types
from platform_core.knowledge.graphs.graph_utils import normalize_entity_name
from platform_core.utils import hashstr

CORE_ROLE_ALIASES = {
    "concept": "concept",
    "概念": "concept",
    "requirement": "concept",
    "需求": "concept",
    "问题": "concept",
    "threat": "concept",
    "威胁": "concept",
    "constraint": "concept",
    "约束": "concept",
    "principle": "principle",
    "原理": "principle",
    "机理": "principle",
    "机制": "principle",
    "technology": "technology",
    "技术": "technology",
    "方法": "technology",
    "算法": "technology",
    "材料": "technology",
    "capability": "capability",
    "能力": "capability",
    "性能": "capability",
    "effect": "capability",
    "效能": "capability",
    "application": "application",
    "应用": "application",
    "场景": "application",
    "任务": "application",
    "装备": "application",
}
CORE_ROLE_ORDER = {"concept": 0, "principle": 1, "technology": 2, "capability": 3, "application": 4}
COMBINATION_RELATIONS = {
    "COMBINES_WITH",
    "COMPLEMENTS",
    "COMPLEMENTARY_TO",
    "TECHNOLOGY_CONVERGENCE",
    "组合",
    "互补",
    "融合",
}
SAME_LAYER_RELATIONS = {"SAME_LAYER_WITH", "ALTERNATIVE_TO", "ANALOGOUS_TO", "同层", "替代", "类似"}
HYPOTHESIS_RELATIONS = {"PREDICTED_LINK", "TRANSFERABLE_TO", "POTENTIAL_FOR", "预测", "潜在", "可迁移"}
VALUE_ATTRIBUTE_MARKERS = (
    "指标",
    "性能",
    "参数",
    "成熟度",
    "工程约束",
    "适用条件",
    "验证状态",
    "转化价值",
    "转化潜力",
    "研发价值",
    "technical_metric",
    "maturity",
    "constraint",
    "validation",
    "transfer_potential",
)


@dataclass(frozen=True)
class PathQueryOptions:
    mode: str = "auto"
    max_hops: int = 5
    max_paths: int = 10
    include_combinations: bool = True
    beam_width: int = 24
    branch_limit: int = 12


@dataclass(frozen=True)
class _TraversalStep:
    edge: dict[str, Any]
    neighbor_id: str
    traversed_reverse: bool


@dataclass(frozen=True)
class _CandidatePath:
    node_ids: tuple[str, ...]
    steps: tuple[_TraversalStep, ...]
    anchor_score: float


def discover_paths(
    graph: dict[str, Any],
    query: str,
    options: PathQueryOptions,
) -> dict[str, Any]:
    """在已召回子图中执行受限双向搜索并生成可追溯研发链路。"""
    nodes = [node for node in graph.get("nodes") or [] if node.get("id")]
    edges = [edge for edge in graph.get("edges") or [] if edge.get("id")]
    nodes_by_id = {str(node["id"]): node for node in nodes}
    adjacency = _build_adjacency(nodes_by_id, edges, include_combinations=options.include_combinations)
    anchors = _rank_anchors(nodes, adjacency, query, options.mode)
    candidates = _beam_expand(nodes_by_id, adjacency, anchors, options)
    ranked = sorted(candidates, key=lambda item: _path_score(item, nodes_by_id), reverse=True)
    maximal_paths = _maximal_non_contained_paths(ranked, options.max_paths)
    paths = [_serialize_path(path, nodes_by_id, query, options.mode) for path in maximal_paths]
    quality_summary = _path_quality_summary(paths)
    return {
        "query": query,
        "mode": _resolve_mode(query, options.mode),
        "paths": paths,
        "candidate_context": {
            "known_relations": _known_relations(nodes_by_id, edges),
        },
        "summary": {
            "anchor_count": len(anchors),
            "candidate_path_count": len(candidates),
            "returned_path_count": len(paths),
            "max_hops": options.max_hops,
            "combinations_enabled": options.include_combinations,
            "quality": quality_summary,
        },
    }


def _path_quality_summary(paths: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总路径质量、证据覆盖和审核风险，供界面统一呈现。"""
    if not paths:
        return {
            "trusted_path_count": 0,
            "hypothesis_path_count": 0,
            "pending_review_count": 0,
            "cross_document_path_count": 0,
            "complete_semantic_chain_count": 0,
            "mechanism_chain_count": 0,
            "application_chain_count": 0,
            "requirement_chain_count": 0,
            "usable_semantic_closure_count": 0,
            "invalid_relation_signature_count": 0,
            "unique_source_count": 0,
            "unique_relation_count": 0,
            "average_semantic_coverage": 0.0,
            "average_score": 0.0,
        }

    unique_files: set[str] = set()
    unique_relations: set[str] = set()
    semantic_coverage = 0.0
    total_score = 0.0
    trusted_path_count = 0
    hypothesis_path_count = 0
    pending_review_count = 0
    cross_document_path_count = 0
    complete_semantic_chain_count = 0
    mechanism_chain_count = 0
    application_chain_count = 0
    requirement_chain_count = 0
    usable_semantic_closure_count = 0
    invalid_relation_signature_count = 0

    for path in paths:
        evidence = path.get("evidence") or {}
        file_ids = {str(item) for item in evidence.get("file_ids") or [] if str(item)}
        relation_ids = {str(item) for item in path.get("relation_ids") or [] if str(item)}
        unique_files.update(file_ids)
        unique_relations.update(relation_ids)

        coverage = float(path.get("semantic_coverage") or 0.0)
        semantic_coverage += coverage
        total_score += float(path.get("score") or 0.0)
        if coverage >= 1.0:
            complete_semantic_chain_count += 1
        closures = set(path.get("semantic_closures") or [])
        mechanism_chain_count += "mechanism_chain" in closures
        application_chain_count += "application_chain" in closures
        requirement_chain_count += "requirement_chain" in closures
        usable_semantic_closure_count += bool(closures)
        invalid_relation_signature_count += int((path.get("relation_signature") or {}).get("invalid_count") or 0)
        if len(file_ids) > 1:
            cross_document_path_count += 1
        if bool(path.get("pending_evidence")):
            pending_review_count += 1

        if str(path.get("claim_level") or "").strip().lower() == "hypothesis":
            hypothesis_path_count += 1
        elif not path.get("pending_evidence"):
            trusted_path_count += 1

    path_count = len(paths)
    return {
        "trusted_path_count": trusted_path_count,
        "hypothesis_path_count": hypothesis_path_count,
        "pending_review_count": pending_review_count,
        "cross_document_path_count": cross_document_path_count,
        "complete_semantic_chain_count": complete_semantic_chain_count,
        "mechanism_chain_count": mechanism_chain_count,
        "application_chain_count": application_chain_count,
        "requirement_chain_count": requirement_chain_count,
        "usable_semantic_closure_count": usable_semantic_closure_count,
        "invalid_relation_signature_count": invalid_relation_signature_count,
        "unique_source_count": len(unique_files),
        "unique_relation_count": len(unique_relations),
        "average_semantic_coverage": round(semantic_coverage / path_count, 3),
        "average_score": round(total_score / path_count, 4),
    }


def _known_relations(
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """为缺失边发现提供紧凑的既有关系索引，避免重复预测现有直接边。"""
    result: set[tuple[str, str, str]] = set()
    for edge in edges:
        source = nodes_by_id.get(str(edge.get("source_id") or ""))
        target = nodes_by_id.get(str(edge.get("target_id") or ""))
        source_id = _stable_entity_id(source)
        target_id = _stable_entity_id(target)
        relation_type = str(edge.get("type") or "").strip().upper()
        if source_id and target_id and relation_type:
            result.add((source_id, target_id, relation_type))
    return [
        {
            "source_entity_id": source_id,
            "target_entity_id": target_id,
            "relation_type": relation_type,
        }
        for source_id, target_id, relation_type in sorted(result)
    ]


def _stable_entity_id(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    properties = node.get("properties") or {}
    return str(properties.get("entity_id") or node.get("entity_id") or node.get("id") or "").strip()


def _build_adjacency(
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    include_combinations: bool,
) -> dict[str, list[_TraversalStep]]:
    adjacency = {node_id: [] for node_id in nodes_by_id}
    for edge in edges:
        source_id = str(edge.get("source_id") or "")
        target_id = str(edge.get("target_id") or "")
        if source_id not in nodes_by_id or target_id not in nodes_by_id or source_id == target_id:
            continue
        if not include_combinations and _is_exploratory_edge(edge):
            continue
        adjacency[source_id].append(_TraversalStep(edge=edge, neighbor_id=target_id, traversed_reverse=False))
        adjacency[target_id].append(_TraversalStep(edge=edge, neighbor_id=source_id, traversed_reverse=True))
    return adjacency


def _rank_anchors(
    nodes: list[dict[str, Any]],
    adjacency: dict[str, list[_TraversalStep]],
    query: str,
    mode: str,
) -> list[tuple[str, float]]:
    normalized_query = normalize_entity_name(query or "")
    resolved_mode = _resolve_mode(query, mode)
    ranked = []
    for node in nodes:
        node_id = str(node["id"])
        name = normalize_entity_name(str(node.get("name") or ""))
        node_type = normalize_entity_name(str(node.get("type") or ""))
        relevance = float((node.get("properties") or {}).get("query_relevance") or 0.0)
        if normalized_query and normalized_query != "*":
            if name == normalized_query:
                relevance = max(relevance, 1.0)
            elif normalized_query in name or name in normalized_query:
                relevance = max(relevance, 0.88)
            elif node_type and node_type in normalized_query:
                relevance = max(relevance, 0.45)
        elif normalized_query == "*" or not normalized_query:
            relevance = 0.35

        role = _semantic_role(node)
        if resolved_mode == "requirement_driven":
            relevance += {"concept": 0.22, "capability": 0.12, "application": 0.05}.get(role, 0.0)
        elif resolved_mode == "entity_expansion":
            relevance += {"technology": 0.12, "principle": 0.08}.get(role, 0.0)
        relevance += min(len(adjacency.get(node_id) or []), 8) * 0.01
        if relevance > 0:
            ranked.append((node_id, relevance))
    ranked.sort(key=lambda item: (item[1], len(adjacency.get(item[0]) or [])), reverse=True)
    return ranked[:6]


def _beam_expand(
    nodes_by_id: dict[str, dict[str, Any]],
    adjacency: dict[str, list[_TraversalStep]],
    anchors: list[tuple[str, float]],
    options: PathQueryOptions,
) -> list[_CandidatePath]:
    active = [_CandidatePath((node_id,), (), score) for node_id, score in anchors]
    candidates: list[_CandidatePath] = []
    for _ in range(max(1, min(options.max_hops, 6))):
        expanded = []
        for path in active:
            used_edges = {str(step.edge["id"]) for step in path.steps}
            next_steps = sorted(
                adjacency.get(path.node_ids[-1]) or [],
                key=lambda step: _step_priority(step, nodes_by_id),
                reverse=True,
            )[: max(1, options.branch_limit)]
            for step in next_steps:
                edge_id = str(step.edge["id"])
                if step.neighbor_id in path.node_ids or edge_id in used_edges:
                    continue
                if _is_exploratory_edge(step.edge) and any(
                    _is_exploratory_edge(existing.edge) for existing in path.steps
                ):
                    continue
                next_path = _CandidatePath(
                    node_ids=(*path.node_ids, step.neighbor_id),
                    steps=(*path.steps, step),
                    anchor_score=path.anchor_score,
                )
                expanded.append(next_path)
                candidates.append(next_path)
        if not expanded:
            break
        active = sorted(expanded, key=lambda item: _path_score(item, nodes_by_id), reverse=True)[
            : max(1, options.beam_width)
        ]
    return candidates


def _maximal_non_contained_paths(paths: list[_CandidatePath], limit: int) -> list[_CandidatePath]:
    unique_paths: list[_CandidatePath] = []
    seen_sequences: set[tuple[str, ...]] = set()
    for path in paths:
        relation_ids = tuple(str(step.edge["id"]) for step in path.steps)
        canonical_sequence = min(relation_ids, tuple(reversed(relation_ids)))
        if canonical_sequence in seen_sequences:
            continue
        unique_paths.append(path)
        seen_sequences.add(canonical_sequence)

    maximal_paths = []
    for path in unique_paths:
        relation_set = {str(step.edge["id"]) for step in path.steps}
        family = _path_route_kind(path)
        if any(
            relation_set < {str(step.edge["id"]) for step in other.steps} and family == _path_route_kind(other)
            for other in unique_paths
        ):
            continue
        maximal_paths.append(path)
    return maximal_paths[: max(1, min(limit, 30))]


def _serialize_path(
    path: _CandidatePath,
    nodes_by_id: dict[str, dict[str, Any]],
    query: str,
    mode: str,
) -> dict[str, Any]:
    nodes = []
    role_names: dict[str, list[str]] = {role: [] for role in CORE_ROLE_ORDER}
    for node_id in path.node_ids:
        node = nodes_by_id[node_id]
        role = _semantic_role(node)
        if role:
            role_names[role].append(str(node.get("name") or ""))
        nodes.append({**node, "semantic_role": role or "other"})

    relations = []
    chunk_ids: list[str] = []
    file_ids: list[str] = []
    mention_count = 0
    for step in path.steps:
        properties = dict(step.edge.get("properties") or {})
        evidence_count = int(properties.get("evidence_count") or 1)
        mention_count += evidence_count
        chunk_ids.extend(_evidence_values(properties, "evidence_chunk_ids", "chunk_id"))
        file_ids.extend(_evidence_values(properties, "evidence_file_ids", "file_id"))
        relations.append(
            {
                **step.edge,
                "traversed_reverse": step.traversed_reverse,
                "evidence_count": evidence_count,
            }
        )

    distinct_roles = {role for role, names in role_names.items() if names}
    semantic_coverage = len(distinct_roles) / len(CORE_ROLE_ORDER)
    semantic_closures = _semantic_closures(path, nodes_by_id)
    relation_signature = _relation_signature_summary(path, nodes_by_id)
    route_kind = _path_route_kind(path)
    claim_level = _path_claim_level(path)
    evidence_gaps = _evidence_gaps(role_names, route_kind, mention_count)
    if not semantic_closures:
        evidence_gaps.append("尚未形成原理—技术—能力、技术—能力—应用或需求—能力—应用语义闭环")
    if relation_signature["invalid_count"]:
        evidence_gaps.append("存在本体端点类型或关系方向不合法的已知关系，需要重新抽取或专家复核")
    military_value_dimensions = _collect_relation_list(path, "military_value_dimensions")
    expected_capability_gains = _collect_relation_text(path, "expected_capability_gain")
    relation_application_directions = _collect_relation_text(path, "application_direction")
    applicable_conditions = _collect_relation_list(path, "applicable_conditions")
    uncertainties = _collect_relation_text(path, "uncertainty")
    expert_review_required = claim_level == "Hypothesis" or any(
        bool(_edge_properties(step.edge).get("expert_review_required")) for step in path.steps
    )
    review_statuses = list(
        dict.fromkeys(
            str(_edge_properties(step.edge).get("review_status") or "pending").strip().lower() for step in path.steps
        )
    )
    pending_relation_count = sum(
        str(_edge_properties(step.edge).get("review_status") or "pending").strip().lower() != "accepted"
        for step in path.steps
    )
    pending_evidence = pending_relation_count > 0
    expert_review_required = expert_review_required or pending_evidence
    path_id = hashstr(
        ":".join(str(step.edge["id"]) for step in path.steps),
        length=20,
    )
    return {
        "path_id": path_id,
        "query": query,
        "mode": _resolve_mode(query, mode),
        "score": round(_path_score(path, nodes_by_id), 4),
        "semantic_coverage": round(semantic_coverage, 3),
        "semantic_closures": semantic_closures,
        "relation_signature": relation_signature,
        "route_kind": route_kind,
        "claim_level": claim_level,
        "pending_evidence": pending_evidence,
        "is_maximal": True,
        "nodes": nodes,
        "relations": relations,
        "relation_ids": [str(step.edge["id"]) for step in path.steps],
        "evidence": {
            "mention_count": mention_count,
            "chunk_ids": list(dict.fromkeys(chunk_ids)),
            "file_ids": list(dict.fromkeys(file_ids)),
            "support_level": "multi_source" if len(set(file_ids)) > 1 else "single_source",
            "review_statuses": review_statuses,
            "pending_relation_count": pending_relation_count,
            "pending_evidence": pending_evidence,
        },
        "evidence_gaps": evidence_gaps,
        "research_inspiration": {
            "concepts": role_names["concept"],
            "principles": role_names["principle"],
            "technologies": role_names["technology"],
            "capability_outcomes": role_names["capability"],
            "application_directions": list(
                dict.fromkeys([*role_names["application"], *relation_application_directions])
            ),
            "applicable_conditions": applicable_conditions,
            "combination_basis": _combination_basis(path, nodes_by_id),
            "research_threads": _collect_research_threads(nodes),
            "value_signals": _collect_value_signals(nodes),
            "military_value_dimensions": military_value_dimensions,
            "expected_capability_gains": expected_capability_gains,
            "uncertainties": uncertainties,
            "expert_review_required": expert_review_required,
            "review_questions": _review_questions(role_names, route_kind, evidence_gaps),
        },
    }


def _path_score(path: _CandidatePath, nodes_by_id: dict[str, dict[str, Any]]) -> float:
    roles = {_semantic_role(nodes_by_id[node_id]) for node_id in path.node_ids}
    roles.discard("")
    coverage = len(roles) / len(CORE_ROLE_ORDER)
    evidence = sum(min(int((step.edge.get("properties") or {}).get("evidence_count") or 1), 3) for step in path.steps)
    relation_quality = sum(_step_priority(step, nodes_by_id) for step in path.steps)
    value_signal_count = sum(len(_node_value_signals(nodes_by_id[node_id])) for node_id in path.node_ids)
    confidences = [_relation_confidence(step.edge) for step in path.steps]
    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    military_value_count = len(_collect_relation_list(path, "military_value_dimensions"))
    capability_gain_count = len(_collect_relation_text(path, "expected_capability_gain"))
    uncertainty_count = len(_collect_relation_text(path, "uncertainty"))
    hypothesis_penalty = 0.28 if _path_claim_level(path) == "Hypothesis" else 0.0
    closure_bonus = min(len(_semantic_closures(path, nodes_by_id)), 3) * 0.32
    relation_signature = _relation_signature_summary(path, nodes_by_id)
    signature_bonus = min(int(relation_signature["valid_count"]), 4) * 0.04
    signature_penalty = min(int(relation_signature["invalid_count"]), 3) * 0.45
    return (
        path.anchor_score * 1.5
        + coverage * 2.2
        + min(len(path.steps), 5) * 0.16
        + evidence * 0.06
        + relation_quality * 0.08
        + min(value_signal_count, 5) * 0.04
        + average_confidence * 0.25
        + min(military_value_count, 4) * 0.05
        + min(capability_gain_count, 2) * 0.08
        + closure_bonus
        + signature_bonus
        - min(uncertainty_count, 3) * 0.05
        - signature_penalty
        - hypothesis_penalty
    )


def _semantic_closures(path: _CandidatePath, nodes_by_id: dict[str, dict[str, Any]]) -> list[str]:
    """识别可用于检索和创新审核的局部语义闭环，不强求五类齐全。"""

    links: set[frozenset[str]] = set()
    for step in path.steps:
        source = nodes_by_id.get(str(step.edge.get("source_id") or ""))
        target = nodes_by_id.get(str(step.edge.get("target_id") or ""))
        source_role = _semantic_role(source or {})
        target_role = _semantic_role(target or {})
        if source_role and target_role:
            links.add(frozenset((source_role, target_role)))

    def linked(left: str, right: str) -> bool:
        return frozenset((left, right)) in links

    mechanism = linked("principle", "technology") and linked("technology", "capability")
    application = (linked("technology", "capability") or linked("principle", "capability")) and (
        linked("capability", "application") or linked("technology", "application")
    )
    requirement = any(linked("concept", role) for role in ("principle", "technology", "capability")) and any(
        linked(role, "application") for role in ("technology", "capability")
    )
    return [
        name
        for name, present in (
            ("mechanism_chain", mechanism),
            ("application_chain", application),
            ("requirement_chain", requirement),
        )
        if present
    ]


def _relation_signature_summary(
    path: _CandidatePath,
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """按版本化本体检查已知关系方向；未知扩展关系保持中性。"""

    valid_count = 0
    invalid_count = 0
    unknown_count = 0
    for step in path.steps:
        relation_type = str(step.edge.get("type") or "").strip().upper()
        relation = DEFENSE_ONTOLOGY_V1.relation_type_by_code.get(relation_type)
        if relation is None:
            unknown_count += 1
            continue
        source = nodes_by_id.get(str(step.edge.get("source_id") or ""), {})
        target = nodes_by_id.get(str(step.edge.get("target_id") or ""), {})
        if validate_relation_types(str(source.get("type") or ""), relation_type, str(target.get("type") or "")):
            valid_count += 1
        else:
            invalid_count += 1
    return {
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "unknown_count": unknown_count,
    }


def _step_priority(step: _TraversalStep, nodes_by_id: dict[str, dict[str, Any]]) -> float:
    family = _relation_family(str(step.edge.get("type") or ""))
    family_score = {"evidence_chain": 1.0, "same_layer": 0.8, "combined": 0.7, "predicted": 0.45}[family]
    evidence_count = int((step.edge.get("properties") or {}).get("evidence_count") or 1)
    role = _semantic_role(nodes_by_id[step.neighbor_id])
    confidence = _relation_confidence(step.edge)
    return family_score + min(evidence_count, 3) * 0.12 + confidence * 0.1 + (0.08 if role else 0.0)


def _semantic_role(node: dict[str, Any]) -> str:
    raw_type = str(node.get("type") or "")
    governed_role = core_role_for_entity_type(raw_type)
    if governed_role:
        return governed_role
    node_type = normalize_entity_name(raw_type)
    if node_type in CORE_ROLE_ALIASES:
        return CORE_ROLE_ALIASES[node_type]
    for alias, role in CORE_ROLE_ALIASES.items():
        if alias and alias in node_type:
            return role
    return ""


def _relation_family(relation_type: str) -> str:
    normalized = relation_type.strip().upper()
    if normalized in HYPOTHESIS_RELATIONS or any(marker in normalized for marker in ("PREDICT", "POTENTIAL")):
        return "predicted"
    if normalized in COMBINATION_RELATIONS or any(marker in normalized for marker in ("COMBINE", "COMPLEMENT")):
        return "combined"
    if normalized in SAME_LAYER_RELATIONS or any(marker in normalized for marker in ("SAME_LAYER", "ALTERNATIVE")):
        return "same_layer"
    return "evidence_chain"


def _path_route_kind(path: _CandidatePath) -> str:
    if any(
        str(_edge_properties(step.edge).get("claim_level") or "").strip().title() == "Hypothesis" for step in path.steps
    ):
        return "predicted"
    families = {_relation_family(str(step.edge.get("type") or "")) for step in path.steps}
    if "predicted" in families:
        return "predicted"
    if "combined" in families:
        return "combined"
    if "same_layer" in families:
        return "same_layer"
    return "evidence_chain"


def _path_claim_level(path: _CandidatePath) -> str:
    levels = {_edge_claim_level(step.edge) for step in path.steps}
    if "Hypothesis" in levels:
        return "Hypothesis"
    if levels == {"Fact"}:
        return "Fact"
    return "Inference"


def _edge_properties(edge: dict[str, Any]) -> dict[str, Any]:
    properties = edge.get("properties") or {}
    return properties if isinstance(properties, dict) else {}


def _edge_claim_level(edge: dict[str, Any]) -> str:
    raw_claim_level = _edge_properties(edge).get("claim_level")
    if not raw_claim_level and _relation_family(str(edge.get("type") or "")) != "evidence_chain":
        return "Hypothesis"
    claim_level = str(raw_claim_level or "Inference").strip().title()
    return claim_level if claim_level in {"Fact", "Inference", "Hypothesis"} else "Inference"


def _is_exploratory_edge(edge: dict[str, Any]) -> bool:
    return _edge_claim_level(edge) == "Hypothesis" or _relation_family(str(edge.get("type") or "")) != "evidence_chain"


def _relation_confidence(edge: dict[str, Any]) -> float:
    try:
        confidence = float(_edge_properties(edge).get("confidence", 0.5))
    except (TypeError, ValueError, OverflowError):
        confidence = 0.5
    return max(0.0, min(confidence, 1.0))


def _collect_relation_list(path: _CandidatePath, key: str) -> list[str]:
    values: list[str] = []
    for step in path.steps:
        raw_values = _edge_properties(step.edge).get(key) or []
        if not isinstance(raw_values, list):
            continue
        values.extend(str(value).strip() for value in raw_values if str(value).strip())
    return list(dict.fromkeys(values))


def _collect_relation_text(path: _CandidatePath, key: str) -> list[str]:
    values = []
    for step in path.steps:
        value = str(_edge_properties(step.edge).get(key) or "").strip()
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


def _resolve_mode(query: str, mode: str) -> str:
    if mode in {"requirement_driven", "entity_expansion"}:
        return mode
    requirement_markers = ("需求", "能力", "如何", "提升", "解决", "面向", "支撑")
    return (
        "requirement_driven" if any(marker in (query or "") for marker in requirement_markers) else "entity_expansion"
    )


def _evidence_values(properties: dict[str, Any], plural_key: str, singular_key: str) -> list[str]:
    values = [str(value) for value in properties.get(plural_key) or [] if value]
    singular = properties.get(singular_key)
    if singular:
        values.append(str(singular))
    return values


def _node_value_signals(node: dict[str, Any]) -> list[dict[str, str]]:
    signals = []
    for attribute in (node.get("properties") or {}).get("attributes") or []:
        if not isinstance(attribute, dict):
            continue
        label = str(attribute.get("label") or "").strip()
        text = str(attribute.get("text") or "").strip()
        normalized_label = label.lower()
        if text and any(marker in normalized_label for marker in VALUE_ATTRIBUTE_MARKERS):
            signals.append({"label": label, "text": text})
    return signals


def _collect_value_signals(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    signals = []
    seen = set()
    for node in nodes:
        for attribute in _node_value_signals(node):
            key = (str(node.get("id")), attribute["label"], attribute["text"])
            if key in seen:
                continue
            seen.add(key)
            signals.append(
                {
                    "entity": str(node.get("name") or ""),
                    "label": attribute["label"],
                    "text": attribute["text"],
                }
            )
    return signals


def _collect_research_threads(nodes: list[dict[str, Any]]) -> dict[str, list[str]]:
    """按文献主线、辅线和并行线聚合路径实体，不扩写事实。"""
    grouped: dict[str, list[str]] = {thread: [] for thread in RESEARCH_THREAD_TYPES}
    for node in nodes:
        name = str(node.get("name") or "").strip()
        if not name:
            continue
        for attribute in (node.get("properties") or {}).get("attributes") or []:
            if not isinstance(attribute, dict):
                continue
            if str(attribute.get("label") or "").strip().casefold() != "researchthread":
                continue
            thread = str(attribute.get("text") or "").strip().lower()
            if thread in grouped and name not in grouped[thread]:
                grouped[thread].append(name)
    return grouped


def _evidence_gaps(role_names: dict[str, list[str]], route_kind: str, mention_count: int) -> list[str]:
    gaps = []
    if not role_names["principle"]:
        gaps.append("缺少明确的作用原理或机理证据")
    if not role_names["capability"]:
        gaps.append("缺少可验证的能力收益节点")
    if not role_names["application"]:
        gaps.append("缺少应用、任务或场景落点")
    if mention_count <= 1:
        gaps.append("当前链路仅有单条抽取证据，需要交叉来源验证")
    if route_kind in {"combined", "predicted"}:
        gaps.append("组合桥属于探索性关联，尚不能视为已验证事实")
    return gaps


def _combination_basis(path: _CandidatePath, nodes_by_id: dict[str, dict[str, Any]]) -> list[str]:
    basis = []
    for index, step in enumerate(path.steps):
        family = _relation_family(str(step.edge.get("type") or ""))
        if family == "evidence_chain":
            continue
        source = nodes_by_id[path.node_ids[index]].get("name")
        target = nodes_by_id[path.node_ids[index + 1]].get("name")
        basis.append(f"{source} —{step.edge.get('type')}→ {target}")
    return basis


def _review_questions(
    role_names: dict[str, list[str]],
    route_kind: str,
    evidence_gaps: list[str],
) -> list[str]:
    questions = []
    if role_names["technology"] and role_names["capability"]:
        questions.append("该技术到能力收益之间是否有独立试验、指标或工程证据？")
    if len(role_names["technology"]) > 1 or route_kind in {"combined", "same_layer", "predicted"}:
        questions.append("不同技术路线的接口、互补条件、冲突约束和成熟度是否兼容？")
    if role_names["application"]:
        questions.append("该应用方向的边界条件能否迁移到目标业务场景？")
    if evidence_gaps:
        questions.append("哪些缺失证据应优先补充，才能把当前推断提升为可评审结论？")
    return questions
