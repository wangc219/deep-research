from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from platform_core.knowledge.graphs.entity_type_governance import (
    EntityTypeConflictDecision,
    apply_entity_type_conflict_decisions,
    decide_entity_type_conflict,
    resolve_entity_type_conflicts,
)
from platform_core.knowledge.graphs.lightrag_entity_alignment import LightRAGEntityAlignmentEnhancer


def _candidate(
    entity_id: str,
    label: str,
    *,
    name: str = "巡航导弹",
) -> dict:
    return {
        "entity_id": entity_id,
        "normalized_name": name.casefold(),
        "name": name,
        "label": label,
        "attributes": [],
        "mention_count": 3,
        "accepted_mention_count": 1,
        "source_file_count": 2,
        "average_confidence": 0.91,
        "model_versions": ["lightrag"],
    }


def _entity(*, label: str = "Component", name: str = "巡航导弹") -> dict:
    return {
        "entity_id": "incoming",
        "normalized_name": name.casefold(),
        "name": name,
        "label": label,
        "attributes": [],
    }


def test_unique_surface_hint_relabels_to_exact_name_existing_type_and_rewrites_relations():
    entity = _entity()
    decision = decide_entity_type_conflict(
        entity=entity,
        candidates=(_candidate("product", "ProductSystem"),),
    )
    triples = [
        {
            "source_entity_id": "incoming",
            "target_entity_id": "capability",
            "relation_type": "ENABLES_CAPABILITY",
        }
    ]

    applied = apply_entity_type_conflict_decisions(
        entities=[entity],
        triples=triples,
        decisions=[decision],
    )

    assert decision.status == "relabel"
    assert decision.auto_apply is True
    assert applied == {"incoming"}
    assert entity["entity_id"] == "product"
    assert entity["label"] == "ProductSystem"
    assert triples[0]["source_entity_id"] == "product"
    assert entity["attributes"]["type_governance"]["expert_review_required"] is False


def test_surface_hint_supporting_incoming_type_keeps_distinct_semantic_role():
    entity = _entity(label="ProductSystem")
    decision = decide_entity_type_conflict(
        entity=entity,
        candidates=(_candidate("component", "Component"),),
    )

    applied = apply_entity_type_conflict_decisions(
        entities=[entity],
        triples=[],
        decisions=[decision],
    )

    assert decision.status == "keep_separate"
    assert applied == set()
    assert entity["entity_id"] == "incoming"
    assert entity["attributes"]["type_governance"]["expert_review_required"] is True


@pytest.mark.asyncio
async def test_resolver_only_returns_exact_name_cross_type_conflicts():
    loader = AsyncMock()
    loader.load_entity_type_conflict_profiles.return_value = {
        "防空雷达": [
            _candidate("system", "ProductSystem", name="防空雷达"),
            _candidate("same-type", "ScientificPrinciple", name="防空雷达"),
        ]
    }
    entities = [
        {
            "entity_id": "incoming",
            "normalized_name": "防空雷达",
            "name": "防空雷达",
            "label": "ScientificPrinciple",
            "attributes": [],
        }
    ]

    decisions = await resolve_entity_type_conflicts(
        kb_id="kb-1",
        entities=entities,
        unresolved_entity_ids={"incoming"},
        profile_loader=loader,
    )

    assert len(decisions) == 1
    assert decisions[0].status == "ambiguous"
    assert [item["entity_id"] for item in decisions[0].candidates] == ["system"]


@pytest.mark.asyncio
async def test_lightrag_type_governance_recommends_but_does_not_apply_by_default():
    completion = AsyncMock(
        return_value={
            "decisions": [
                {
                    "incoming_entity_id": "incoming",
                    "action": "relabel",
                    "target_entity_id": "system",
                    "confidence": 0.98,
                    "reason_code": "same_real_world_entity_wrong_type",
                }
            ]
        }
    )
    enhancer = LightRAGEntityAlignmentEnhancer(
        {"model_spec": "siliconflow-cn:military-chat"},
        completion=completion,
    )
    decision = EntityTypeConflictDecision(
        incoming_entity_id="incoming",
        current_label="ScientificPrinciple",
        status="ambiguous",
        target_entity_id=None,
        recommended_label=None,
        candidates=(_candidate("system", "ProductSystem", name="防空雷达"),),
        reason_code="cross_type_exact_name_requires_context",
        reason="需要上下文",
    )

    enhanced = await enhancer.adjudicate_type_conflicts(
        entities=[
            {
                "entity_id": "incoming",
                "normalized_name": "防空雷达",
                "name": "防空雷达",
                "label": "ScientificPrinciple",
                "attributes": [],
            }
        ],
        triples=[],
        decisions=[decision],
    )

    assert enhanced[0].status == "relabel"
    assert enhanced[0].target_entity_id == "system"
    assert enhanced[0].recommended_label == "ProductSystem"
    assert enhanced[0].auto_apply is False
    assert "不得创造 ID" in completion.await_args.args[0]
    assert '"semantic_role":"principle"' in completion.await_args.args[0]
    assert '"semantic_role":"application"' in completion.await_args.args[0]
    assert "不得把技术、能力和应用压扁成同一实体" in completion.await_args.args[0]


@pytest.mark.asyncio
async def test_lightrag_type_governance_auto_apply_requires_explicit_enable_and_closed_target():
    for target_id, expected_status in (("system", "relabel"), ("invented", "ambiguous")):
        enhancer = LightRAGEntityAlignmentEnhancer(
            {
                "model_spec": "siliconflow-cn:military-chat",
                "auto_link_enabled": True,
            },
            completion=AsyncMock(
                return_value={
                    "decisions": [
                        {
                            "incoming_entity_id": "incoming",
                            "action": "relabel",
                            "target_entity_id": target_id,
                            "confidence": 0.99,
                            "reason_code": "same_real_world_entity_wrong_type",
                        }
                    ]
                }
            ),
        )
        original = EntityTypeConflictDecision(
            incoming_entity_id="incoming",
            current_label="ScientificPrinciple",
            status="ambiguous",
            target_entity_id=None,
            recommended_label=None,
            candidates=(_candidate("system", "ProductSystem", name="防空雷达"),),
            reason_code="cross_type_exact_name_requires_context",
            reason="需要上下文",
        )

        enhanced = await enhancer.adjudicate_type_conflicts(
            entities=[
                {
                    "entity_id": "incoming",
                    "normalized_name": "防空雷达",
                    "name": "防空雷达",
                    "label": "ScientificPrinciple",
                    "attributes": [],
                }
            ],
            triples=[],
            decisions=[original],
        )

        assert enhanced[0].status == expected_status
        assert enhanced[0].auto_apply is (target_id == "system")
