from __future__ import annotations

from platform_core.knowledge.graphs.semantic_chain_completion import (
    analyze_five_role_recall,
    semantic_transition,
)


def _entities():
    return [
        {"entity_id": "c", "type": "Concept"},
        {"entity_id": "p", "type": "ScientificPrinciple"},
        {"entity_id": "t", "type": "KeyTechnology"},
        {"entity_id": "k", "type": "Capability"},
        {"entity_id": "a", "type": "ApplicationScenario"},
        {"entity_id": "m", "type": "Metric"},
    ]


def test_semantic_transition_prioritizes_adjacent_chain_without_changing_direction():
    reverse = semantic_transition("KeyTechnology", "ScientificPrinciple")
    bridge = semantic_transition("KeyTechnology", "ApplicationScenario")
    supporting = semantic_transition("Metric", "Capability")

    assert reverse == {
        "source_role": "technology",
        "target_role": "principle",
        "transition": "principle_to_technology",
        "priority": 1.0,
        "kind": "adjacent",
    }
    assert bridge["transition"] == "technology_to_application"
    assert bridge["priority"] == 0.65
    assert supporting["priority"] == 0.0


def test_gap_analysis_reports_only_missing_supported_transitions():
    relations = [
        {"source_entity_id": "t", "target_entity_id": "p", "type": "BASED_ON"},
        {"source_entity_id": "t", "target_entity_id": "k", "type": "ENABLES_CAPABILITY"},
        {"source_entity_id": "k", "target_entity_id": "a", "type": "SUPPORTS_APPLICATION"},
    ]

    report = analyze_five_role_recall(_entities(), relations)

    assert report["relations_provided"] is True
    assert report["missing_roles"] == []
    assert report["observed_transitions"] == [
        "principle_to_technology",
        "technology_to_capability",
        "capability_to_application",
    ]
    assert report["missing_transitions"] == ["concept_to_principle"]
    assert report["unavailable_transitions"] == []
    assert report["all_five_roles_observed"] is True
    assert report["all_adjacent_transitions_observed"] is False


def test_gap_analysis_does_not_claim_full_graph_gaps_without_relation_context():
    report = analyze_five_role_recall(_entities())

    assert report["relations_provided"] is False
    assert report["observed_transitions"] == []
    assert report["missing_transitions"] == [
        "concept_to_principle",
        "principle_to_technology",
        "technology_to_capability",
        "capability_to_application",
    ]
    assert report["all_five_roles_observed"] is True
    assert report["all_adjacent_transitions_observed"] is False


def test_gap_analysis_marks_transition_unavailable_when_role_is_absent():
    report = analyze_five_role_recall(
        [
            {"entity_id": "p", "type": "ScientificPrinciple"},
            {"entity_id": "t", "type": "KeyTechnology"},
            {"entity_id": "k", "type": "Capability"},
        ],
        [],
    )

    assert report["missing_roles"] == ["concept", "application"]
    assert report["missing_transitions"] == [
        "principle_to_technology",
        "technology_to_capability",
    ]
    assert report["unavailable_transitions"] == [
        "concept_to_principle",
        "capability_to_application",
    ]
