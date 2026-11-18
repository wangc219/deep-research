from __future__ import annotations

import pytest

from platform_core.knowledge.graphs.innovation_discovery import (
    INNOVATION_ALGORITHM_VERSION,
    build_innovation_feedback_loop,
    discover_innovation_hypotheses,
    innovation_response,
)


def _node(entity_id: str, name: str, entity_type: str, role: str) -> dict:
    return {
        "id": f"neo4j-{entity_id}",
        "name": name,
        "type": entity_type,
        "semantic_role": role,
        "properties": {"entity_id": entity_id},
    }


def _path_result() -> dict:
    return {
        "summary": {"retrieval_mode": "semantic"},
        "candidate_context": {"known_relations": []},
        "paths": [
            {
                "path_id": "path-1",
                "score": 4.8,
                "semantic_coverage": 0.8,
                "nodes": [
                    {
                        **_node("tech-1", "自适应波束形成", "KeyTechnology", "technology"),
                        "properties": {"entity_id": "tech-1", "query_relevance": 0.9},
                    },
                    _node("cap-1", "抗干扰能力", "Capability", "capability"),
                    _node("app-1", "复杂电磁环境感知", "ApplicationScenario", "application"),
                ],
                "relation_ids": ["r1", "r2"],
                "evidence": {
                    "mention_count": 4,
                    "chunk_ids": ["chunk-1", "chunk-2"],
                    "file_ids": ["file-1", "file-2"],
                    "support_level": "multi_source",
                },
                "evidence_gaps": ["缺少直接应用验证"],
                "research_inspiration": {
                    "research_threads": {
                        "main": ["自适应波束形成"],
                        "side": ["阵列校准"],
                        "parallel": ["稀疏阵列路线"],
                    },
                    "value_signals": [{"text": "旁瓣抑制指标已由试验记录支持"}],
                    "expected_capability_gains": ["提升复杂环境感知稳定性"],
                    "application_directions": ["系统级集成验证"],
                    "applicable_conditions": ["完成阵列校准", "满足实时处理时延约束"],
                    "uncertainties": ["跨平台泛化仍需验证"],
                },
            }
        ],
    }


def test_discovers_non_adjacent_transfer_as_hypothesis_with_evidence_path():
    candidates = discover_innovation_hypotheses(
        kb_id="kb-1",
        path_result=_path_result(),
        discovery_mode="top_down",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["source"]["entity_id"] == "tech-1"
    assert candidate["target"]["entity_id"] == "app-1"
    assert candidate["relation_type"] == "TRANSFERABLE_TO"
    assert candidate["claim_level"] == "Hypothesis"
    assert candidate["review_status"] == "pending"
    assert candidate["algorithm_version"] == INNOVATION_ALGORITHM_VERSION
    assert candidate["score_components"]["retrieval_mode"] == "semantic"
    assert candidate["score_components"]["semantic_similarity"] == 0.9
    assert candidate["score_components"]["strategic_value"] == candidate["innovation_profile"]["strategic_score"]
    assert candidate["innovation_profile"]["mode"] == "top_down"
    assert set(candidate["innovation_profile"]["dimensions"]) == {
        "military_value",
        "novelty",
        "feasibility",
        "transferability",
        "evidence_strength",
        "weak_signal_potential",
    }
    assert candidate["innovation_profile"]["advisory_only"] is True
    assert candidate["evidence_path"]["relation_ids"] == ["r1", "r2"]
    assert candidate["evidence_path"]["boundary_relation_ids"] == ["r1", "r2"]
    assert candidate["evidence_path"]["minimum_support_count"] == 2
    assert candidate["evidence_path"]["evidence_gaps"] == ["缺少直接应用验证"]
    assert candidate["evidence_path"]["research_threads"] == {
        "main": ["自适应波束形成"],
        "side": ["阵列校准"],
        "parallel": ["稀疏阵列路线"],
    }
    assert candidate["expert_review_required"] is True
    assert candidate["applicable_conditions"] == ["完成阵列校准", "满足实时处理时延约束"]
    assert "该关联尚未由原始证据直接支持" in candidate["uncertainties"]
    assert candidate["validation_requirements"]
    assert candidate["falsification_criteria"]


def test_symmetric_technology_combinations_are_canonicalized_and_deduplicated():
    result = _path_result()
    result["paths"] = []
    for index, (left, right) in enumerate((("tech-b", "tech-a"), ("tech-a", "tech-b")), start=1):
        result["paths"].append(
            {
                "path_id": f"path-{index}",
                "score": 4.0,
                "semantic_coverage": 0.8,
                "nodes": [
                    _node(left, f"技术-{left}", "KeyTechnology", "technology"),
                    _node(f"cap-{index}", "协同能力", "Capability", "capability"),
                    _node(right, f"技术-{right}", "KeyTechnology", "technology"),
                ],
                "relation_ids": [f"r{index}-1", f"r{index}-2"],
                "evidence": {
                    "mention_count": 2,
                    "chunk_ids": [f"chunk-{index}"],
                    "file_ids": [f"file-{index}"],
                    "support_level": "single_source",
                },
            }
        )

    candidates = discover_innovation_hypotheses(
        kb_id="kb-1",
        path_result=result,
        discovery_mode="top_down",
    )

    assert len(candidates) == 1
    assert candidates[0]["relation_type"] == "COMBINES_WITH"
    assert candidates[0]["source"]["entity_id"] == "tech-a"
    assert candidates[0]["target"]["entity_id"] == "tech-b"


def test_candidate_uses_only_relation_segment_between_non_adjacent_endpoints():
    result = _path_result()
    result["paths"][0]["nodes"].append(_node("concept-1", "新体制雷达", "ResearchConcept", "concept"))
    result["paths"][0]["relation_ids"].append("r3")

    candidates = discover_innovation_hypotheses(
        kb_id="kb-1",
        path_result=result,
        discovery_mode="top_down",
    )

    tech_to_application = next(
        candidate
        for candidate in candidates
        if candidate["source"]["entity_id"] == "tech-1" and candidate["target"]["entity_id"] == "app-1"
    )
    assert tech_to_application["evidence_path"]["relation_ids"] == ["r1", "r2"]
    assert tech_to_application["evidence_path"]["full_path_relation_ids"] == ["r1", "r2", "r3"]


def test_response_exposes_fixed_innovation_contract_and_revision():
    candidates = discover_innovation_hypotheses(
        kb_id="kb-1",
        path_result=_path_result(),
        discovery_mode="bottom_up",
    )
    response = innovation_response(
        query="自适应波束形成",
        discovery_mode="bottom_up",
        candidates=candidates,
        graph_revision="rev-7",
        query_analysis={"analysis_version": "test-v1"},
    )

    assert response["claim_level"] == "Hypothesis"
    assert response["graph_revision"] == "rev-7"
    assert response["entities"]
    assert response["path"][0]["path_id"] == "path-1"
    assert response["evidence"][0]["file_ids"] == ["file-1", "file-2"]
    assert response["mechanism_hypothesis"]
    assert response["feasibility_basis"]
    assert response["expected_effects"]
    assert response["uncertainties"]
    assert response["query_analysis"]["analysis_version"] == "test-v1"


def test_feedback_loop_uses_existing_evidence_targets_and_never_writes_graph():
    path_result = _path_result()
    path_result["query_plan"] = {
        "low_level_keywords": ["自适应波束形成", "阵列校准"],
        "high_level_keywords": ["抗干扰机理"],
        "weak_signal_terms": ["稀疏阵列"],
    }
    candidates = discover_innovation_hypotheses(
        kb_id="kb-1",
        path_result=path_result,
        discovery_mode="top_down",
    )

    feedback = build_innovation_feedback_loop(path_result, candidates)

    assert feedback["contract_version"] == "lightrag-defense-feedback-v1"
    assert feedback["status"] == "requires_evidence"
    assert feedback["automatic_graph_write"] is False
    assert "抗干扰机理" in feedback["requery_terms"]
    assert feedback["evidence_gaps"] == ["缺少直接应用验证"]
    assert feedback["validation_tasks"]
    assert feedback["reextraction"] == {
        "recommended": True,
        "file_ids": ["file-1", "file-2"],
        "chunk_ids": ["chunk-1", "chunk-2"],
        "reasons": ["缺少直接应用验证"],
    }


def test_feedback_loop_has_bounded_no_candidate_contract_without_invented_targets():
    path_result = _path_result()
    path_result["paths"][0]["evidence"] = {"file_ids": [], "chunk_ids": []}
    path_result["query_plan"] = {"low_level_keywords": [f"检索词-{index}" for index in range(30)]}

    feedback = build_innovation_feedback_loop(path_result, [])

    assert feedback["status"] == "no_candidate"
    assert len(feedback["requery_terms"]) == 12
    assert feedback["reextraction"]["recommended"] is False
    assert feedback["reextraction"]["file_ids"] == []
    assert feedback["reextraction"]["chunk_ids"] == []


def test_cross_document_scope_rejects_single_source_paths_and_marks_multi_source_candidates():
    candidates = discover_innovation_hypotheses(
        kb_id="kb-1",
        path_result=_path_result(),
        discovery_mode="top_down",
        evidence_scope="cross_document",
    )

    assert len(candidates) == 1
    assert candidates[0]["evidence_scope"] == "cross_document"
    assert candidates[0]["evidence_path"]["cross_document"] is True
    assert candidates[0]["evidence_path"]["document_count"] == 2

    single_source = _path_result()
    single_source["paths"][0]["evidence"]["file_ids"] = ["file-1"]
    assert (
        discover_innovation_hypotheses(
            kb_id="kb-1",
            path_result=single_source,
            discovery_mode="top_down",
            evidence_scope="cross_document",
        )
        == []
    )


def test_rejects_unknown_evidence_scope():
    with pytest.raises(ValueError, match="evidence_scope"):
        discover_innovation_hypotheses(
            kb_id="kb-1",
            path_result=_path_result(),
            discovery_mode="top_down",
            evidence_scope="unknown",
        )


def test_skips_nodes_without_stable_entity_ids():
    result = _path_result()
    result["paths"][0]["nodes"][2]["properties"] = {}

    assert (
        discover_innovation_hypotheses(
            kb_id="kb-1",
            path_result=result,
            discovery_mode="top_down",
        )
        == []
    )


def test_rejects_unknown_discovery_mode():
    with pytest.raises(ValueError, match="top_down"):
        discover_innovation_hypotheses(
            kb_id="kb-1",
            path_result=_path_result(),
            discovery_mode="unsupported",
        )


def test_skips_candidate_when_same_direct_relation_already_exists():
    result = _path_result()
    result["candidate_context"]["known_relations"] = [
        {
            "source_entity_id": "tech-1",
            "target_entity_id": "app-1",
            "relation_type": "TRANSFERABLE_TO",
        }
    ]

    assert (
        discover_innovation_hypotheses(
            kb_id="kb-1",
            path_result=result,
            discovery_mode="top_down",
        )
        == []
    )


def test_semantic_relevance_increases_candidate_score_with_same_path_evidence():
    low = _path_result()
    high = _path_result()
    low["paths"][0]["nodes"][0]["properties"]["query_relevance"] = 0.1
    high["paths"][0]["nodes"][0]["properties"]["query_relevance"] = 0.95

    low_score = discover_innovation_hypotheses(kb_id="kb-1", path_result=low, discovery_mode="top_down")[0]["score"]
    high_score = discover_innovation_hypotheses(kb_id="kb-1", path_result=high, discovery_mode="top_down")[0]["score"]

    assert high_score > low_score


def test_bottom_up_profile_gives_more_weight_to_novelty_and_weak_signals():
    path_result = _path_result()
    path_result["paths"][0]["route_kind"] = "combined"
    path_result["paths"][0]["research_inspiration"]["military_value_dimensions"] = ["体系协同"]
    path_result["paths"][0]["research_inspiration"]["value_signals"] = [
        {"label": "新质技术", "text": "跨域融合的新型射频机理"}
    ]

    top_down = discover_innovation_hypotheses(
        kb_id="kb-1",
        path_result=path_result,
        discovery_mode="top_down",
    )[0]
    bottom_up = discover_innovation_hypotheses(
        kb_id="kb-1",
        path_result=path_result,
        discovery_mode="bottom_up",
    )[0]

    assert bottom_up["innovation_profile"]["weights"]["novelty"] > top_down["innovation_profile"]["weights"]["novelty"]
    assert (
        bottom_up["innovation_profile"]["weights"]["weak_signal_potential"]
        > top_down["innovation_profile"]["weights"]["weak_signal_potential"]
    )
    assert bottom_up["innovation_profile"]["dimensions"]["novelty"] >= 0.5


def test_bottom_up_prioritizes_exact_query_anchor_hypotheses_without_claiming_direct_evidence():
    path_result = _path_result()
    path_result["query_anchors"] = [
        {
            **_node("anchor-tech", "分布式自适应规划控制", "KeyTechnology", "technology"),
            "matched_keyword": "分布式自适应规划控制",
        }
    ]

    candidates = discover_innovation_hypotheses(
        kb_id="kb-1",
        path_result=path_result,
        discovery_mode="bottom_up",
        max_candidates=3,
    )

    assert len(candidates) == 3
    assert all(candidate["query_anchor_match"] is True for candidate in candidates)
    assert all(
        "anchor-tech"
        in {
            candidate["source"]["entity_id"],
            candidate["target"]["entity_id"],
        }
        for candidate in candidates
    )
    assert all(candidate["evidence_path"]["anchor_context_only"] is True for candidate in candidates)
    assert all(candidate["evidence_path"]["anchor_entity_id"] == "anchor-tech" for candidate in candidates)
    assert all(candidate["evidence_path"]["relation_ids"] == ["r1", "r2"] for candidate in candidates)
    assert all(
        any("查询锚点目前是图中的孤立或弱连接实体" in item for item in candidate["uncertainties"])
        for candidate in candidates
    )
