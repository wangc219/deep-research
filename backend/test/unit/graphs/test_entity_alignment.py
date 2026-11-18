from __future__ import annotations

from platform_core.knowledge.graphs.entity_alignment import (
    apply_entity_alignment_decisions,
    decide_semantic_entity_alignment,
)


def _profile(entity_id: str, *, label: str = "KeyTechnology", name: str = "相控阵雷达") -> dict:
    return {
        "entity_id": entity_id,
        "normalized_name": name,
        "name": name,
        "label": label,
        "attributes": {"domain": "雷达探测"},
        "aliases": ["phased array radar"],
        "neighbors": ["探测能力 [Capability]"],
    }


def test_semantic_alignment_enforces_type_score_and_margin():
    entity = {
        "entity_id": "incoming",
        "normalized_name": "有源相控阵",
        "name": "有源相控阵",
        "label": "KeyTechnology",
    }
    context = {"terms": {"雷达", "探测"}, "neighbors": {"探测", "能力"}}
    decision = decide_semantic_entity_alignment(
        entity=entity,
        context=context,
        vector_hits=[
            {"id": "wrong-type", "score": 0.99},
            {"id": "correct", "score": 0.93},
            {"id": "runner-up", "score": 0.81},
        ],
        profiles={
            "wrong-type": _profile("wrong-type", label="ProductSystem"),
            "correct": _profile("correct"),
            "runner-up": _profile("runner-up", name="机械扫描雷达"),
        },
    )

    assert decision.status == "linked"
    assert decision.target_entity_id == "correct"
    assert all(candidate["label"] == "KeyTechnology" for candidate in decision.candidates)


def test_close_semantic_candidates_remain_ambiguous_for_review():
    entity = {
        "entity_id": "incoming",
        "normalized_name": "宽带接收机",
        "name": "宽带接收机",
        "label": "Component",
        "attributes": [],
    }
    decision = decide_semantic_entity_alignment(
        entity=entity,
        context={"terms": set(), "neighbors": set()},
        vector_hits=[{"id": "candidate-a", "score": 0.93}, {"id": "candidate-b", "score": 0.91}],
        profiles={
            "candidate-a": _profile("candidate-a", label="Component", name="射频接收机"),
            "candidate-b": _profile("candidate-b", label="Component", name="数字接收机"),
        },
    )

    assert decision.status == "ambiguous"
    assert decision.target_entity_id is None
    entities = [entity]
    apply_entity_alignment_decisions(entities=entities, triples=[], decisions=[decision])
    alignment = entities[0]["attributes"]["alignment"]
    assert alignment["status"] == "ambiguous"
    assert alignment["expert_review_required"] is True
    assert [item["entity_id"] for item in alignment["candidates"]] == ["candidate-a", "candidate-b"]


def test_link_decision_rewrites_relation_endpoints():
    entity = {
        "entity_id": "incoming",
        "normalized_name": "相控阵",
        "name": "相控阵",
        "label": "KeyTechnology",
    }
    decision = decide_semantic_entity_alignment(
        entity=entity,
        context={"terms": set(), "neighbors": set()},
        vector_hits=[{"id": "canonical", "score": 0.95}],
        profiles={"canonical": _profile("canonical")},
    )
    triples = [
        {
            "source_entity_id": "incoming",
            "target_entity_id": "capability",
            "relation_type": "ENABLES_CAPABILITY",
        }
    ]

    apply_entity_alignment_decisions(entities=[entity], triples=triples, decisions=[decision])

    assert entity["entity_id"] == "canonical"
    assert triples[0]["source_entity_id"] == "canonical"
