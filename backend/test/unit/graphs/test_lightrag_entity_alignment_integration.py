from unittest.mock import AsyncMock

import pytest

import platform_core.knowledge.graphs.milvus_graph_service as graph_service_module
from platform_core.knowledge.graphs.entity_alignment import EntityAlignmentDecision
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService


@pytest.mark.asyncio
async def test_graph_write_alignment_runs_llm_after_vector_candidates_before_id_allocation(monkeypatch):
    graph_repo = AsyncMock()
    graph_repo.align_graph_records.side_effect = [
        {"unresolved_entity_ids": ["incoming"], "ambiguous_candidates": {}},
        {"unresolved_entity_ids": [], "ambiguous_candidates": {}},
    ]
    graph_repo.allocate_entity_ids = AsyncMock()
    vector_store = AsyncMock()
    semantic = EntityAlignmentDecision(
        incoming_entity_id="incoming",
        status="ambiguous",
        target_entity_id=None,
        candidates=(
            {
                "entity_id": "canonical",
                "name": "有源相控阵雷达",
                "normalized_name": "有源相控阵雷达",
                "label": "ProductSystem",
                "vector_score": 0.94,
                "score": 0.94,
            },
        ),
        reason="需要消歧",
        policy_version="defense-entity-alignment-v1",
    )
    monkeypatch.setattr(
        graph_service_module,
        "resolve_semantic_entity_alignments",
        AsyncMock(return_value=[semantic]),
    )
    llm_link = EntityAlignmentDecision(
        incoming_entity_id="incoming",
        status="linked",
        target_entity_id="canonical",
        candidates=semantic.candidates,
        reason="LLM 受约束确认",
        policy_version=semantic.policy_version,
        source="lightrag_llm_alignment",
        model_spec="local:military-chat",
        model_confidence=0.98,
        recommended_target_entity_id="canonical",
    )
    enhancer = AsyncMock()
    enhancer.adjudicate.return_value = [llm_link]
    service = MilvusGraphService(graph_repo=graph_repo, graph_vector_store=vector_store)
    entities = [
        {
            "entity_id": "incoming",
            "name": "AESA雷达",
            "normalized_name": "aesa雷达",
            "label": "ProductSystem",
            "attributes": {},
        }
    ]

    await service._align_entity_records(
        kb_id="kb-1",
        embedding_model_spec="local:embedding",
        entities=entities,
        triples=[],
        llm_enhancer=enhancer,
    )

    enhancer.adjudicate.assert_awaited_once()
    assert entities[0]["entity_id"] == "canonical"
    graph_repo.allocate_entity_ids.assert_not_awaited()
    assert graph_repo.align_graph_records.await_count == 2


@pytest.mark.asyncio
async def test_graph_write_resolves_exact_name_type_conflict_before_vector_search(monkeypatch):
    graph_repo = AsyncMock()
    graph_repo.align_graph_records.side_effect = [
        {"unresolved_entity_ids": ["incoming"], "ambiguous_candidates": {}},
        {"unresolved_entity_ids": [], "ambiguous_candidates": {}},
    ]
    graph_repo.load_entity_type_conflict_profiles.return_value = {
        "巡航导弹": [
            {
                "entity_id": "canonical-product",
                "normalized_name": "巡航导弹",
                "name": "巡航导弹",
                "label": "ProductSystem",
                "attributes": [],
                "mention_count": 2,
                "accepted_mention_count": 1,
                "source_file_count": 1,
                "average_confidence": 0.93,
                "model_versions": ["lightrag"],
            }
        ]
    }
    semantic_resolver = AsyncMock()
    monkeypatch.setattr(graph_service_module, "resolve_semantic_entity_alignments", semantic_resolver)
    service = MilvusGraphService(graph_repo=graph_repo, graph_vector_store=AsyncMock())
    entities = [
        {
            "entity_id": "incoming",
            "name": "巡航导弹",
            "normalized_name": "巡航导弹",
            "label": "Component",
            "attributes": [],
        }
    ]
    triples = [
        {
            "source_entity_id": "incoming",
            "target_entity_id": "capability",
            "relation_type": "ENABLES_CAPABILITY",
        }
    ]

    await service._align_entity_records(
        kb_id="kb-1",
        embedding_model_spec="local:embedding",
        entities=entities,
        triples=triples,
    )

    semantic_resolver.assert_not_awaited()
    graph_repo.allocate_entity_ids.assert_not_awaited()
    assert entities[0]["entity_id"] == "canonical-product"
    assert entities[0]["label"] == "ProductSystem"
    assert triples[0]["source_entity_id"] == "canonical-product"
    assert graph_repo.align_graph_records.await_count == 2
