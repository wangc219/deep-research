from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from platform_core.repositories.knowledge_graph_projection_repository import (
    AuthoritativeProjectionSnapshot,
    KnowledgeGraphProjectionRepository,
)
from platform_core.services.knowledge_graph_projection_rebuild_service import (
    KnowledgeGraphProjectionRebuildService,
)


def test_authoritative_snapshot_preserves_review_and_relation_lifecycle():
    chunk = SimpleNamespace(
        id=7,
        chunk_id="chunk_1",
        file_id="file_1",
        chunk_index=0,
        content="相控阵雷达提升探测能力",
        start_char_pos=0,
        end_char_pos=12,
        document_version=2,
        page_number=3,
        block_type="paragraph",
        heading_path=["系统设计"],
        bbox=[0, 0, 100, 20],
        parser_name="paddlex",
        parser_version="3.0",
    )
    source = SimpleNamespace(
        entity_id="entity_source",
        kb_id="kb_test",
        normalized_name="相控阵雷达",
        label="KeyTechnology",
        name="相控阵雷达",
        attributes=[],
        lifecycle_status="active",
        superseded_by_entity_id=None,
        entity_version=1,
    )
    target = SimpleNamespace(
        entity_id="entity_target",
        kb_id="kb_test",
        normalized_name="探测能力",
        label="Capability",
        name="探测能力",
        attributes=[],
        lifecycle_status="active",
        superseded_by_entity_id=None,
        entity_version=1,
    )
    pending_mention = SimpleNamespace(
        id=1,
        chunk_id="chunk_1",
        entity_id="entity_source",
        mention_text="相控阵雷达",
        start_char=0,
        end_char=5,
        confidence=0.98,
        model_version="lightrag",
        ontology_version="defense-kg-1.0",
        review_status="pending",
    )
    accepted_mention = SimpleNamespace(
        id=2,
        chunk_id="chunk_1",
        entity_id="entity_source",
        mention_text="相控阵雷达",
        start_char=0,
        end_char=5,
        confidence=0.95,
        model_version="lightrag",
        ontology_version="defense-kg-1.0",
        review_status="accepted",
    )
    target_mention = SimpleNamespace(
        id=3,
        chunk_id="chunk_1",
        entity_id="entity_target",
        mention_text="探测能力",
        start_char=7,
        end_char=11,
        confidence=0.94,
        model_version="lightrag",
        ontology_version="defense-kg-1.0",
        review_status="accepted",
    )
    triple = SimpleNamespace(
        triple_id="triple_1",
        kb_id="kb_test",
        source_entity_id="entity_source",
        target_entity_id="entity_target",
        relation_type="ENABLES_CAPABILITY",
        content="相控阵雷达提升探测能力",
        lifecycle_status="superseded",
        superseded_by_triple_id="triple_2",
        relation_version=2,
    )
    triple_mention = SimpleNamespace(
        chunk_id="chunk_1",
        text="提升",
        extractor_type="lightrag",
        claim_level="Fact",
        confidence=0.91,
        evidence_quote="相控阵雷达提升探测能力",
        evidence_spans=[{"start": 0, "end": 11}],
        reasoning_basis="原文直接陈述",
        applicable_conditions=["远场条件"],
        uncertainty="",
        expert_review_required=False,
        review_status="accepted",
        model_version="lightrag",
        ontology_version="defense-kg-1.0",
        pipeline_revision="hybrid-v2-r1",
    )

    snapshot = KnowledgeGraphProjectionRepository._build_snapshot(
        chunk,
        [(pending_mention, source), (accepted_mention, source), (target_mention, target)],
        [(triple_mention, triple)],
        {"entity_source": source, "entity_target": target},
    )

    source_record = next(item for item in snapshot.entity_records if item["entity_id"] == "entity_source")
    assert source_record["review_status"] == "accepted"
    assert snapshot.triple_records[0]["lifecycle_status"] == "superseded"
    assert snapshot.triple_records[0]["superseded_by_triple_id"] == "triple_2"
    assert snapshot.graph_payload["relations"][0]["applicable_conditions"] == ["远场条件"]


def test_authoritative_snapshot_includes_relation_endpoint_without_fabricating_mention():
    chunk = SimpleNamespace(
        id=8,
        chunk_id="chunk_source",
        file_id="file_1",
        chunk_index=0,
        content="氮化镓组件用于雷达前端",
        start_char_pos=0,
        end_char_pos=11,
        document_version=1,
        page_number=1,
        block_type="paragraph",
        heading_path=[],
        bbox=None,
        parser_name="native",
        parser_version="1",
    )
    source = SimpleNamespace(
        entity_id="entity_source",
        kb_id="kb_test",
        normalized_name="氮化镓组件",
        label="Component",
        name="氮化镓组件",
        attributes=[],
        lifecycle_status="active",
        superseded_by_entity_id=None,
        entity_version=1,
    )
    target = SimpleNamespace(
        entity_id="entity_target",
        kb_id="kb_test",
        normalized_name="宽带感知",
        label="Capability",
        name="宽带感知",
        attributes=[],
        lifecycle_status="active",
        superseded_by_entity_id=None,
        entity_version=1,
    )
    source_mention = SimpleNamespace(
        id=4,
        chunk_id="chunk_source",
        entity_id="entity_source",
        mention_text="氮化镓组件",
        start_char=0,
        end_char=5,
        confidence=0.94,
        model_version="lightrag",
        ontology_version="defense-kg-1.0",
        review_status="accepted",
    )
    triple = SimpleNamespace(
        triple_id="triple_document",
        kb_id="kb_test",
        source_entity_id="entity_source",
        target_entity_id="entity_target",
        relation_type="ENABLES_CAPABILITY",
        content="氮化镓组件 → ENABLES_CAPABILITY → 宽带感知",
        lifecycle_status="active",
        superseded_by_triple_id=None,
        relation_version=1,
    )
    triple_mention = SimpleNamespace(
        chunk_id="chunk_source",
        text="氮化镓组件 → ENABLES_CAPABILITY → 宽带感知",
        extractor_type="lightrag_document_re",
        claim_level="Inference",
        confidence=1.0,
        evidence_quote="[chunk_source] 氮化镓组件\n[chunk_target] 宽带感知",
        evidence_spans=[
            {"block_id": "chunk_source", "start": 0, "end": 5},
            {"block_id": "chunk_target", "start": 0, "end": 4},
        ],
        reasoning_basis="LightRAG document RE",
        applicable_conditions=[],
        uncertainty="hard label",
        expert_review_required=True,
        review_status="pending",
        model_version="lightrag-doc-v1",
        ontology_version="defense-kg-1.0",
        pipeline_revision="hybrid-v2-r1",
    )

    snapshot = KnowledgeGraphProjectionRepository._build_snapshot(
        chunk,
        [(source_mention, source)],
        [(triple_mention, triple)],
        {"entity_source": source, "entity_target": target},
    )

    records = {record["entity_id"]: record for record in snapshot.entity_records}
    assert records["entity_source"]["has_mention"] is True
    assert records["entity_target"]["has_mention"] is False
    assert records["entity_target"]["start_char"] is None
    assert snapshot.graph_payload["relations"][0]["target"] in {
        entity["id"] for entity in snapshot.graph_payload["entities"]
    }


@pytest.mark.asyncio
async def test_projection_rebuild_only_drops_projections_and_reconciles_vectors():
    snapshot = AuthoritativeProjectionSnapshot(
        chunk={
            "id": 1,
            "chunk_id": "chunk_1",
            "file_id": "file_1",
            "chunk_index": 0,
            "content_preview": "text",
            "start_char_pos": 0,
            "end_char_pos": 4,
            "document_version": 1,
            "page_number": 1,
            "block_type": "paragraph",
            "heading_path": [],
            "bbox": None,
            "parser_name": "native",
            "parser_version": "1",
        },
        graph_payload={"entities": [], "relations": [], "metadata": {}},
        entity_records=[],
        triple_records=[],
    )
    repository = SimpleNamespace(
        latest_revision=AsyncMock(side_effect=["revision_1", "revision_1"]),
        count_projectable_chunks=AsyncMock(return_value=1),
        list_chunk_snapshots=AsyncMock(side_effect=[[snapshot], []]),
    )
    graph_service = SimpleNamespace(
        ensure_projection_target=AsyncMock(),
        delete_graph=MagicMock(),
        project_chunk_graph=MagicMock(),
        reconcile_vectors=AsyncMock(return_value={"mode": "all_vectors", "reset_records": 3}),
        drain_pending_graph_vectors=AsyncMock(return_value={"entity": {"indexed": 2}, "triple": {"indexed": 1}}),
    )
    service = KnowledgeGraphProjectionRebuildService(
        graph_service=graph_service,
        repository=repository,
        batch_size=50,
    )

    result = await service.rebuild(kb_id="kb_test")

    assert result["graph_revision"] == "revision_1"
    assert result["projected_chunks"] == 1
    graph_service.delete_graph.assert_called_once_with("kb_test")
    graph_service.project_chunk_graph.assert_called_once()
    graph_service.reconcile_vectors.assert_awaited_once_with("kb_test", all_vectors=True)
    graph_service.drain_pending_graph_vectors.assert_awaited_once_with("kb_test", context=None)


@pytest.mark.asyncio
async def test_projection_rebuild_counts_only_real_entity_mentions():
    snapshot = AuthoritativeProjectionSnapshot(
        chunk={
            "id": 2,
            "chunk_id": "chunk_source",
            "file_id": "file_1",
            "chunk_index": 0,
            "content_preview": "text",
            "start_char_pos": 0,
            "end_char_pos": 4,
            "document_version": 1,
            "page_number": 1,
            "block_type": "paragraph",
            "heading_path": [],
            "bbox": None,
            "parser_name": "native",
            "parser_version": "1",
        },
        graph_payload={
            "entities": [
                {"id": "source", "text": "source", "label": "Component", "attributes": []},
                {"id": "target", "text": "target", "label": "Capability", "attributes": []},
            ],
            "relations": [],
            "metadata": {},
        },
        entity_records=[
            {"entity_id": "source", "has_mention": True},
            {"entity_id": "target", "has_mention": False},
        ],
        triple_records=[],
    )
    repository = SimpleNamespace(
        latest_revision=AsyncMock(side_effect=["revision_1", "revision_1"]),
        count_projectable_chunks=AsyncMock(return_value=1),
        list_chunk_snapshots=AsyncMock(side_effect=[[snapshot], []]),
    )
    graph_service = SimpleNamespace(
        ensure_projection_target=AsyncMock(),
        delete_graph=MagicMock(),
        project_chunk_graph=MagicMock(),
        reconcile_vectors=AsyncMock(return_value={"mode": "all_vectors", "reset_records": 0}),
        drain_pending_graph_vectors=AsyncMock(return_value={"entity": {"indexed": 1}, "triple": {"indexed": 0}}),
    )

    result = await KnowledgeGraphProjectionRebuildService(
        graph_service=graph_service,
        repository=repository,
    ).rebuild(kb_id="kb_test")

    assert result["projected_entity_mentions"] == 1


@pytest.mark.asyncio
async def test_projection_rebuild_fails_closed_when_revision_changes():
    repository = SimpleNamespace(
        latest_revision=AsyncMock(side_effect=["revision_1", "revision_2"]),
        count_projectable_chunks=AsyncMock(return_value=0),
        list_chunk_snapshots=AsyncMock(return_value=[]),
    )
    graph_service = SimpleNamespace(
        ensure_projection_target=AsyncMock(),
        delete_graph=MagicMock(),
        project_chunk_graph=MagicMock(),
        reconcile_vectors=AsyncMock(),
    )
    service = KnowledgeGraphProjectionRebuildService(
        graph_service=graph_service,
        repository=repository,
    )

    with pytest.raises(RuntimeError, match="graph revision 发生变化"):
        await service.rebuild(kb_id="kb_test")

    graph_service.reconcile_vectors.assert_not_awaited()
