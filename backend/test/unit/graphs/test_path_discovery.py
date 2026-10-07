from __future__ import annotations

import pytest

from platform_core.knowledge.graphs.path_discovery import PathQueryOptions, discover_paths


def _node(node_id: str, name: str, node_type: str, *, relevance: float = 0.0, attributes=None) -> dict:
    return {
        "id": node_id,
        "name": name,
        "type": node_type,
        "properties": {
            "query_relevance": relevance,
            "attributes": attributes or [],
        },
    }


def _edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    relation_type: str = "SUPPORTS",
    *,
    chunks=None,
    files=None,
    evidence_count: int = 1,
    claim_level: str | None = None,
    confidence: float | None = None,
    military_value_dimensions=None,
    expected_capability_gain: str = "",
    application_direction: str = "",
    uncertainty: str = "",
    expert_review_required: bool = False,
) -> dict:
    properties = {
        "evidence_count": evidence_count,
        "evidence_chunk_ids": chunks or [],
        "evidence_file_ids": files or [],
    }
    if claim_level is not None:
        properties["claim_level"] = claim_level
    if confidence is not None:
        properties["confidence"] = confidence
    properties.update(
        {
            "military_value_dimensions": military_value_dimensions or [],
            "expected_capability_gain": expected_capability_gain,
            "application_direction": application_direction,
            "uncertainty": uncertainty,
            "expert_review_required": expert_review_required,
        }
    )
    return {
        "id": edge_id,
        "source_id": source_id,
        "target_id": target_id,
        "type": relation_type,
        "properties": properties,
    }


def _core_graph() -> dict:
    return {
        "nodes": [
            _node("concept", "复杂环境感知需求", "概念", relevance=1.0),
            _node("principle", "波束形成机理", "原理"),
            _node(
                "technology",
                "自适应波束形成",
                "技术",
                attributes=[{"label": "技术指标", "text": "原文给出了旁瓣抑制指标"}],
            ),
            _node("capability", "抗干扰能力", "能力"),
            _node("application", "复杂电磁环境感知", "应用"),
        ],
        "edges": [
            _edge("e1", "concept", "principle"),
            _edge("e2", "principle", "technology"),
            _edge("e3", "technology", "capability"),
            _edge("e4", "capability", "application"),
        ],
    }


def test_discovers_complete_five_role_chain_and_removes_short_prefixes():
    result = discover_paths(
        _core_graph(),
        "复杂环境感知需求",
        PathQueryOptions(max_hops=4, max_paths=10),
    )

    assert len(result["paths"]) == 1
    path = result["paths"][0]
    assert {node["semantic_role"] for node in path["nodes"]} == {
        "concept",
        "principle",
        "technology",
        "capability",
        "application",
    }
    assert path["semantic_coverage"] == 1.0
    assert path["relation_ids"] == ["e1", "e2", "e3", "e4"]
    assert path["research_inspiration"]["value_signals"] == [
        {
            "entity": "自适应波束形成",
            "label": "技术指标",
            "text": "原文给出了旁瓣抑制指标",
        }
    ]


def test_reverse_traversal_preserves_relation_direction():
    graph = _core_graph()
    for node in graph["nodes"]:
        node["properties"]["query_relevance"] = 1.0 if node["id"] == "application" else 0.0

    path = discover_paths(
        graph,
        "复杂电磁环境感知",
        PathQueryOptions(max_hops=4, max_paths=1),
    )["paths"][0]

    assert [node["id"] for node in path["nodes"]] == [
        "application",
        "capability",
        "technology",
        "principle",
        "concept",
    ]
    assert path["relations"][0]["source_id"] == "capability"
    assert path["relations"][0]["target_id"] == "application"
    assert path["relations"][0]["traversed_reverse"] is True


def test_keeps_distinct_application_branches():
    graph = _core_graph()
    graph["nodes"].append(_node("application_2", "低可观测目标感知", "应用"))
    graph["edges"].append(_edge("e5", "capability", "application_2"))

    paths = discover_paths(graph, "复杂环境感知需求", PathQueryOptions(max_hops=4, max_paths=10))["paths"]

    terminal_names = {path["nodes"][-1]["name"] for path in paths}
    assert terminal_names == {"复杂电磁环境感知", "低可观测目标感知"}


def test_paths_never_repeat_nodes_or_relations_in_cycle():
    graph = _core_graph()
    graph["edges"].append(_edge("cycle", "capability", "principle"))

    paths = discover_paths(graph, "复杂环境感知需求", PathQueryOptions(max_hops=6, max_paths=10))["paths"]

    assert paths
    for path in paths:
        node_ids = [node["id"] for node in path["nodes"]]
        assert len(node_ids) == len(set(node_ids))
        assert len(path["relation_ids"]) == len(set(path["relation_ids"]))


@pytest.mark.parametrize(
    ("relation_type", "route_kind"),
    [("COMBINES_WITH", "combined"), ("PREDICTED_LINK", "predicted")],
)
def test_exploratory_bridge_is_explicit_hypothesis(relation_type: str, route_kind: str):
    graph = {
        "nodes": [
            _node("tech_a", "技术 A", "技术", relevance=1.0),
            _node("tech_b", "技术 B", "技术"),
            _node("capability", "能力 C", "能力"),
        ],
        "edges": [
            _edge("bridge", "tech_a", "tech_b", relation_type),
            _edge("evidence", "tech_b", "capability"),
        ],
    }

    path = discover_paths(graph, "技术 A", PathQueryOptions(max_hops=2, max_paths=3))["paths"][0]

    assert path["route_kind"] == route_kind
    assert path["claim_level"] == "Hypothesis"
    assert any("探索性关联" in gap for gap in path["evidence_gaps"])


def test_combination_relations_can_be_excluded():
    graph = {
        "nodes": [_node("a", "技术 A", "技术", relevance=1.0), _node("b", "技术 B", "技术")],
        "edges": [_edge("bridge", "a", "b", "COMBINES_WITH")],
    }

    result = discover_paths(
        graph,
        "技术 A",
        PathQueryOptions(max_hops=2, max_paths=3, include_combinations=False),
    )

    assert result["paths"] == []


def test_metadata_hypothesis_is_excluded_even_with_ordinary_relation_type():
    graph = {
        "nodes": [_node("a", "技术 A", "技术", relevance=1.0), _node("b", "能力 B", "能力")],
        "edges": [_edge("bridge", "a", "b", "SUPPORTS", claim_level="Hypothesis")],
    }

    included = discover_paths(graph, "技术 A", PathQueryOptions(max_hops=1, include_combinations=True))
    excluded = discover_paths(graph, "技术 A", PathQueryOptions(max_hops=1, include_combinations=False))

    assert included["paths"][0]["claim_level"] == "Hypothesis"
    assert included["paths"][0]["route_kind"] == "predicted"
    assert excluded["paths"] == []


def test_fact_only_path_is_fact_and_aggregates_research_value_metadata():
    graph = {
        "nodes": [
            _node("technology", "技术 A", "技术", relevance=1.0),
            _node("capability", "能力 B", "能力"),
            _node("application", "应用 C", "应用"),
        ],
        "edges": [
            _edge(
                "e1",
                "technology",
                "capability",
                claim_level="Fact",
                confidence=0.94,
                military_value_dimensions=["复杂对抗环境适应性"],
                expected_capability_gain="提升复杂环境适应能力",
            ),
            _edge(
                "e2",
                "capability",
                "application",
                claim_level="Fact",
                confidence=0.86,
                military_value_dimensions=["体系集成与互操作性", "复杂对抗环境适应性"],
                application_direction="系统级集成验证",
                uncertainty="仍需补充跨平台验证",
                expert_review_required=True,
            ),
        ],
    }

    path = discover_paths(graph, "技术 A", PathQueryOptions(max_hops=2, max_paths=1))["paths"][0]
    inspiration = path["research_inspiration"]

    assert path["claim_level"] == "Fact"
    assert inspiration["military_value_dimensions"] == ["复杂对抗环境适应性", "体系集成与互操作性"]
    assert inspiration["expected_capability_gains"] == ["提升复杂环境适应能力"]
    assert inspiration["application_directions"] == ["应用 C", "系统级集成验证"]
    assert inspiration["uncertainties"] == ["仍需补充跨平台验证"]
    assert inspiration["expert_review_required"] is True


def test_confidence_and_uncertainty_affect_path_score():
    confident_graph = {
        "nodes": [_node("a", "技术 A", "技术", relevance=1.0), _node("b", "能力 B", "能力")],
        "edges": [_edge("e1", "a", "b", claim_level="Inference", confidence=0.95)],
    }
    uncertain_graph = {
        "nodes": [_node("a", "技术 A", "技术", relevance=1.0), _node("b", "能力 B", "能力")],
        "edges": [
            _edge(
                "e1",
                "a",
                "b",
                claim_level="Inference",
                confidence=0.2,
                uncertainty="样本规模有限",
            )
        ],
    }

    confident_score = discover_paths(confident_graph, "技术 A", PathQueryOptions(max_hops=1))["paths"][0]["score"]
    uncertain_score = discover_paths(uncertain_graph, "技术 A", PathQueryOptions(max_hops=1))["paths"][0]["score"]

    assert confident_score > uncertain_score


def test_allows_at_most_one_exploratory_bridge_per_path():
    graph = {
        "nodes": [
            _node("a", "技术 A", "技术", relevance=1.0),
            _node("b", "技术 B", "技术"),
            _node("c", "技术 C", "技术"),
        ],
        "edges": [
            _edge("bridge_1", "a", "b", "COMBINES_WITH"),
            _edge("bridge_2", "b", "c", "PREDICTED_LINK"),
        ],
    }

    paths = discover_paths(graph, "技术 A", PathQueryOptions(max_hops=4, max_paths=5))["paths"]

    assert paths
    assert all(len(path["relations"]) == 1 for path in paths)


def test_aggregates_chunk_and_file_evidence():
    graph = {
        "nodes": [_node("a", "技术 A", "技术", relevance=1.0), _node("b", "能力 B", "能力")],
        "edges": [
            _edge(
                "e1",
                "a",
                "b",
                chunks=["chunk_1", "chunk_2"],
                files=["file_1", "file_2"],
                evidence_count=2,
            )
        ],
    }

    evidence = discover_paths(graph, "技术 A", PathQueryOptions(max_hops=1, max_paths=1))["paths"][0]["evidence"]

    assert evidence == {
        "mention_count": 2,
        "chunk_ids": ["chunk_1", "chunk_2"],
        "file_ids": ["file_1", "file_2"],
        "support_level": "multi_source",
    }


def test_reports_missing_principle_capability_and_application_evidence():
    graph = {
        "nodes": [_node("concept", "需求", "概念", relevance=1.0), _node("technology", "技术", "技术")],
        "edges": [_edge("e1", "concept", "technology")],
    }

    gaps = discover_paths(graph, "需求", PathQueryOptions(max_hops=1, max_paths=1))["paths"][0]["evidence_gaps"]

    assert "缺少明确的作用原理或机理证据" in gaps
    assert "缺少可验证的能力收益节点" in gaps
    assert "缺少应用、任务或场景落点" in gaps


def test_respects_hop_and_path_limits():
    graph = _core_graph()
    graph["nodes"].append(_node("application_2", "应用 B", "应用"))
    graph["edges"].append(_edge("e5", "capability", "application_2"))

    result = discover_paths(graph, "复杂环境感知需求", PathQueryOptions(max_hops=2, max_paths=1))

    assert len(result["paths"]) == 1
    assert len(result["paths"][0]["relations"]) <= 2
