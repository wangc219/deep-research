from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from platform_core.knowledge.graphs.entity_alignment import (
    EntityAlignmentDecision,
    apply_entity_alignment_decisions,
)
from platform_core.knowledge.graphs.lightrag_entity_alignment import LightRAGEntityAlignmentEnhancer
from platform_core.knowledge.graphs.pipeline_config import normalize_pipeline_options


def _ambiguous_decision() -> EntityAlignmentDecision:
    return EntityAlignmentDecision(
        incoming_entity_id="incoming",
        status="ambiguous",
        target_entity_id=None,
        candidates=(
            {
                "entity_id": "radar-a",
                "name": "有源相控阵雷达",
                "normalized_name": "有源相控阵雷达",
                "label": "ProductSystem",
                "vector_score": 0.93,
                "context_overlap": 0.8,
                "neighbor_overlap": 0.7,
                "score": 0.95,
            },
            {
                "entity_id": "radar-b",
                "name": "无源相控阵雷达",
                "normalized_name": "无源相控阵雷达",
                "label": "ProductSystem",
                "vector_score": 0.92,
                "context_overlap": 0.7,
                "neighbor_overlap": 0.6,
                "score": 0.94,
            },
        ),
        reason="候选分差不足",
        policy_version="defense-entity-alignment-v1",
    )


def _entities():
    return [
        {
            "entity_id": "incoming",
            "name": "AESA雷达",
            "normalized_name": "aesa雷达",
            "label": "ProductSystem",
            "attributes": {"band": "X波段"},
        },
        {
            "entity_id": "capability",
            "name": "多目标跟踪能力",
            "normalized_name": "多目标跟踪能力",
            "label": "Capability",
            "attributes": {},
        },
    ]


def _pipeline_options(**alignment):
    return {
        "orchestration_mode": "lightrag_cascade",
        "primary": {"endpoint": "http://lightrag", "model_version": "lightrag"},
        "secondary": {"enabled": False},
        "llm_enhancement": {"enabled": True, "model_spec": "local:military-chat"},
        "entity_alignment": {
            "enabled": True,
            "model_spec": "local:military-chat",
            **alignment,
        },
    }


def test_alignment_configuration_is_versioned_and_auto_link_can_run_on_stable():
    recommendation = normalize_pipeline_options("lightrag_primary", _pipeline_options())

    assert recommendation["entity_alignment"] == {
        "enabled": True,
        "model_spec": "local:military-chat",
        "enable_thinking": False,
        "max_truncation_retries": 0,
        "strict": False,
        "auto_link_enabled": False,
        "min_confidence": 0.95,
        "min_vector_score": 0.9,
        "max_candidates": 5,
        "timeout_seconds": 60.0,
        "max_output_tokens": 4096,
    }

    normalized = normalize_pipeline_options(
        "lightrag_primary",
        _pipeline_options(auto_link_enabled=True),
    )
    assert normalized["orchestration_release_channel"] == "stable"
    assert normalized["entity_alignment"]["auto_link_enabled"] is True


def test_alignment_configuration_rejects_invalid_budget_and_thresholds():
    for field, value in (
        ("min_confidence", 1.1),
        ("min_vector_score", -0.1),
        ("max_candidates", 11),
        ("timeout_seconds", 0),
        ("max_output_tokens", 64),
        ("enable_thinking", "false"),
        ("max_truncation_retries", 3),
    ):
        with pytest.raises(ValueError, match=f"entity_alignment.{field}"):
            normalize_pipeline_options("lightrag_primary", _pipeline_options(**{field: value}))


@pytest.mark.asyncio
async def test_alignment_llm_recommends_candidate_but_default_does_not_auto_link():
    completion = AsyncMock(
        return_value={
            "decisions": [
                {
                    "incoming_entity_id": "incoming",
                    "action": "link",
                    "target_entity_id": "radar-a",
                    "confidence": 0.99,
                    "reason_code": "same_real_world_entity",
                }
            ]
        }
    )
    enhancer = LightRAGEntityAlignmentEnhancer(
        {"model_spec": "local:military-chat"},
        completion=completion,
    )

    decisions = await enhancer.adjudicate(
        entities=_entities(),
        triples=[
            {
                "source_entity_id": "incoming",
                "target_entity_id": "capability",
                "relation_type": "ENABLES_CAPABILITY",
            }
        ],
        decisions=[_ambiguous_decision()],
    )

    assert decisions[0].status == "ambiguous"
    assert decisions[0].recommended_target_entity_id == "radar-a"
    assert decisions[0].source == "lightrag_llm_alignment"
    assert "AESA雷达" in completion.await_args.args[0]
    assert "多目标跟踪能力" in completion.await_args.args[0]
    assert '"semantic_role":"application"' in completion.await_args.args[0]
    assert "领域限定词 + 核心对象 + 类型后缀" in completion.await_args.args[0]
    assert "defense-lightrag-entity-alignment-v4" in completion.await_args.args[0]
    assert '"confidence":0.95' in completion.await_args.args[0]


@pytest.mark.asyncio
async def test_alignment_llm_drops_decision_below_platform_confidence_gate():
    decision = _ambiguous_decision()
    enhancer = LightRAGEntityAlignmentEnhancer(
        {"model_spec": "local:military-chat", "min_confidence": 0.95},
        completion=AsyncMock(
            return_value={
                "decisions": [
                    {
                        "incoming_entity_id": "incoming",
                        "action": "link",
                        "target_entity_id": "radar-a",
                        "confidence": 0.94,
                        "reason_code": "same_real_world_entity",
                    }
                ]
            }
        ),
    )

    decisions = await enhancer.adjudicate(
        entities=_entities(),
        triples=[],
        decisions=[decision],
    )

    assert decisions == [decision]


@pytest.mark.asyncio
async def test_alignment_llm_experimental_auto_link_requires_top_candidate_and_both_thresholds():
    completion = AsyncMock(
        return_value={
            "decisions": [
                {
                    "incoming_entity_id": "incoming",
                    "action": "link",
                    "target_entity_id": "radar-a",
                    "confidence": 0.97,
                    "reason_code": "same_real_world_entity",
                }
            ]
        }
    )
    enhancer = LightRAGEntityAlignmentEnhancer(
        {
            "model_spec": "local:military-chat",
            "auto_link_enabled": True,
            "min_confidence": 0.95,
            "min_vector_score": 0.90,
        },
        completion=completion,
    )

    decisions = await enhancer.adjudicate(
        entities=_entities(),
        triples=[],
        decisions=[_ambiguous_decision()],
    )
    entities = _entities()
    triples = [
        {
            "source_entity_id": "incoming",
            "target_entity_id": "capability",
            "relation_type": "ENABLES_CAPABILITY",
        }
    ]
    apply_entity_alignment_decisions(entities=entities, triples=triples, decisions=decisions)

    assert decisions[0].status == "linked"
    assert entities[0]["entity_id"] == "radar-a"
    assert triples[0]["source_entity_id"] == "radar-a"
    assert entities[0]["attributes"]["alignment"]["source"] == "lightrag_llm_alignment"


@pytest.mark.asyncio
async def test_alignment_llm_cannot_link_invented_or_non_top_candidate():
    for target_id in ("invented", "radar-b"):
        enhancer = LightRAGEntityAlignmentEnhancer(
            {"model_spec": "local:test", "auto_link_enabled": True},
            completion=AsyncMock(
                return_value={
                    "decisions": [
                        {
                            "incoming_entity_id": "incoming",
                            "action": "link",
                            "target_entity_id": target_id,
                            "confidence": 1.0,
                            "reason_code": "same_real_world_entity",
                        }
                    ]
                }
            ),
        )

        decisions = await enhancer.adjudicate(
            entities=_entities(),
            triples=[],
            decisions=[_ambiguous_decision()],
        )

        assert decisions[0].status == "ambiguous"
        if target_id == "invented":
            assert decisions[0].source == "semantic"
        else:
            assert decisions[0].recommended_target_entity_id == "radar-b"


@pytest.mark.asyncio
async def test_alignment_llm_failure_degrades_to_original_decision_unless_strict():
    decision = _ambiguous_decision()
    enhancer = LightRAGEntityAlignmentEnhancer(
        {"model_spec": "local:test", "strict": False},
        completion=AsyncMock(side_effect=TimeoutError("secret endpoint timeout")),
    )

    assert await enhancer.adjudicate(entities=_entities(), triples=[], decisions=[decision]) == [decision]

    strict = LightRAGEntityAlignmentEnhancer(
        {"model_spec": "local:test", "strict": True},
        completion=AsyncMock(side_effect=TimeoutError("timeout")),
    )
    with pytest.raises(TimeoutError):
        await strict.adjudicate(entities=_entities(), triples=[], decisions=[decision])


@pytest.mark.asyncio
async def test_alignment_llm_new_decision_stays_review_required():
    enhancer = LightRAGEntityAlignmentEnhancer(
        {"model_spec": "local:test"},
        completion=AsyncMock(
            return_value={
                "decisions": [
                    {
                        "incoming_entity_id": "incoming",
                        "action": "new",
                        "target_entity_id": "",
                        "confidence": 0.98,
                        "reason_code": "different_real_world_entity",
                    }
                ]
            }
        ),
    )

    decisions = await enhancer.adjudicate(
        entities=_entities(),
        triples=[],
        decisions=[_ambiguous_decision()],
    )
    entities = _entities()
    apply_entity_alignment_decisions(entities=entities, triples=[], decisions=decisions)

    assert decisions[0].status == "new"
    assert entities[0]["attributes"]["alignment"]["expert_review_required"] is True
