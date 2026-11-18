from __future__ import annotations

from platform_core.knowledge.graphs.requirement_analysis import (
    REQUIREMENT_ANALYSIS_VERSION,
    analyze_requirement_query,
    parse_requirement_query,
)


def test_parses_capability_scenario_constraint_and_technology_without_inventing_values():
    result = parse_requirement_query(
        "面向复杂电磁环境的无人机集群任务，采用自适应波束形成算法，提升多目标探测与抗干扰能力，端到端时延不超过20毫秒。"
    )

    assert result["analysis_version"] == REQUIREMENT_ANALYSIS_VERSION
    assert result["concept_targets"] == ["面向复杂电磁环境的无人机集群任务"]
    assert result["principle_terms"] == []
    assert result["target_capabilities"] == ["提升多目标探测与抗干扰能力"]
    assert "面向复杂电磁环境的无人机集群任务" in result["application_scenarios"]
    assert "采用自适应波束形成算法" in result["key_technical_elements"]
    assert result["constraints"] == ["端到端时延不超过20毫秒"]
    assert result["quantitative_constraints"] == ["不超过20毫秒"]
    assert result["ambiguous_clauses"] == []


def test_preserves_unclassified_clause_for_human_review():
    result = parse_requirement_query("蓝色方案优先")

    assert result["target_capabilities"] == []
    assert result["ambiguous_clauses"] == ["蓝色方案优先"]


def test_maps_path_entities_back_to_requirement_fields_with_traceable_path_ids():
    result = analyze_requirement_query(
        "面向复杂电磁环境，采用自适应波束形成技术提升抗干扰能力",
        {
            "paths": [
                {
                    "path_id": "path-1",
                    "score": 5.4,
                    "nodes": [
                        {
                            "name": "复杂电磁环境",
                            "type": "Concept",
                            "semantic_role": "concept",
                            "properties": {"entity_id": "concept-1", "query_relevance": 0.94},
                        },
                        {
                            "name": "自适应波束形成机理",
                            "type": "ScientificPrinciple",
                            "semantic_role": "principle",
                            "properties": {"entity_id": "principle-1", "query_relevance": 0.9},
                        },
                        {
                            "name": "自适应波束形成",
                            "type": "KeyTechnology",
                            "semantic_role": "technology",
                            "properties": {"entity_id": "tech-1", "query_relevance": 0.96},
                        },
                        {
                            "name": "抗干扰能力",
                            "type": "Capability",
                            "semantic_role": "capability",
                            "properties": {"entity_id": "cap-1", "query_relevance": 0.92},
                        },
                        {
                            "name": "复杂电磁环境",
                            "type": "ApplicationScenario",
                            "semantic_role": "application",
                            "properties": {"entity_id": "app-1"},
                        },
                    ],
                }
            ]
        },
        discovery_mode="top_down",
    )

    mappings = {(item["requirement_field"], item["entity_id"]): item for item in result["entity_mappings"]}
    assert mappings[("concept_targets", "concept-1")]["path_ids"] == ["path-1"]
    assert mappings[("principle_terms", "principle-1")]["mapping_score"] == 0.9
    assert mappings[("key_technical_elements", "tech-1")]["path_ids"] == ["path-1"]
    assert mappings[("target_capabilities", "cap-1")]["mapping_score"] == 0.92
    assert ("application_scenarios", "app-1") in mappings
    assert result["unmapped_fields"] == []
    assert result["needs_human_review"] is False
