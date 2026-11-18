from __future__ import annotations

from types import SimpleNamespace

import pytest

from platform_core.services.knowledge_graph_solution_service import KnowledgeGraphSolutionService


class _GraphService:
    def __init__(self, path):
        self.path = path
        self.call = None

    async def discover_paths(self, kb_id, **kwargs):
        self.call = {"kb_id": kb_id, **kwargs}
        return {
            "paths": [self.path],
            "query_analysis": {"target_capabilities": ["能力 C"]},
            "path_reranking": {"status": "completed", "ranked_count": 1},
        }


class _ChunkRepository:
    def __init__(self, chunks):
        self.chunks = chunks
        self.requested = None

    async def list_by_chunk_ids(self, chunk_ids):
        self.requested = chunk_ids
        return self.chunks


class _RevisionRepository:
    async def latest_revision(self, kb_id):
        return "revision-7"


class _Generator:
    def __init__(self):
        self.payload = None

    async def generate(self, payload):
        self.payload = payload
        return {
            "mechanism_hypothesis": "技术 A 可能支撑能力 C。",
            "feasibility_basis": ["原文记录了关联。"],
            "expected_effects": ["可能提升能力 C。"],
            "uncertainties": ["仍需试验。"],
            "citations": [
                {"claim_path": "mechanism_hypothesis", "evidence_ids": ["E001"]},
                {"claim_path": "feasibility_basis[0]", "evidence_ids": ["E001"]},
                {"claim_path": "expected_effects[0]", "evidence_ids": ["E001"]},
            ],
            "claim_level": "Hypothesis",
        }

    async def aclose(self):
        pass


def _path(*, accepted=True, claim_level="Fact", file_ids=None):
    return {
        "path_id": "path-1",
        "claim_level": claim_level,
        "route_kind": "evidence_chain",
        "nodes": [
            {
                "name": "技术 A",
                "type": "KeyTechnology",
                "semantic_role": "technology",
                "properties": {"entity_id": "entity-a"},
            },
            {
                "name": "能力 C",
                "type": "Capability",
                "semantic_role": "capability",
                "properties": {"entity_id": "entity-c"},
            },
        ],
        "relations": [
            {
                "id": "relation-1",
                "type": "ENABLES_CAPABILITY",
                "source_id": "entity-a",
                "target_id": "entity-c",
                "properties": {
                    "review_status": "accepted" if accepted else "pending",
                    "claim_level": claim_level,
                },
            }
        ],
        "evidence": {"chunk_ids": ["chunk-1"], "file_ids": file_ids or ["file-1"]},
        "evidence_gaps": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
async def test_generates_from_active_fact_path_and_postgres_chunk(accepted):
    graph = _GraphService(_path(accepted=accepted))
    chunks = [
        SimpleNamespace(
            kb_id="kb-1",
            chunk_id="chunk-1",
            file_id="file-1",
            content="技术 A 已在试验中表现出与能力 C 相关的作用。",
            page_number=3,
            heading_path=["试验结果"],
            start_char_pos=100,
            end_char_pos=130,
            parser_name="native-pdf",
            parser_version="1.0",
        )
    ]
    generator = _Generator()
    service = KnowledgeGraphSolutionService(
        graph_service=graph,
        chunk_repository=_ChunkRepository(chunks),
        revision_repository=_RevisionRepository(),
        generator_factory=lambda _: generator,
    )

    result = await service.generate(
        kb_id="kb-1",
        query="提升能力 C",
        discovery_mode="top_down",
        llm_enabled=True,
        model_spec="provider:model",
        path_reranking={"enabled": True, "model_spec": "local:military-chat"},
    )

    assert graph.call["include_combinations"] is False
    assert generator.payload["discovery_mode"] == "top_down"
    assert graph.call["path_reranking"] == {"enabled": True, "model_spec": "local:military-chat"}
    assert result["claim_level"] == "Hypothesis"
    assert result["evidence"][0]["chunk_id"] == "chunk-1"
    assert result["graph_revision"] == "revision-7"
    assert result["evidence_scope"] == "any"
    assert result["source_document_count"] == 1
    assert result["cross_document_path_count"] == 0
    assert result["path_reranking"] == {"status": "completed", "ranked_count": 1}
    assert result["confidence"]["algorithm_version"] == "defense-solution-assessment-v1"
    assert result["confidence"]["components"]["citation_coverage"] == 1
    assert result["innovation_brief"]["claim_level"] == "Hypothesis"
    assert result["innovation_brief"]["graph_revision"] == "revision-7"
    assert result["persisted"] is False
    assert result["expert_review_required"] is True


@pytest.mark.asyncio
async def test_llm_must_be_explicitly_enabled():
    service = KnowledgeGraphSolutionService(graph_service=_GraphService(_path()))

    with pytest.raises(ValueError, match="显式启用"):
        await service.generate(
            kb_id="kb-1",
            query="能力需求",
            discovery_mode="top_down",
            llm_enabled=False,
            model_spec="provider:model",
        )


@pytest.mark.asyncio
async def test_rejects_hypothesis_paths():
    path = _path(claim_level="Hypothesis")
    service = KnowledgeGraphSolutionService(graph_service=_GraphService(path))

    with pytest.raises(ValueError, match="没有可用"):
        await service.generate(
            kb_id="kb-1",
            query="能力需求",
            discovery_mode="top_down",
            llm_enabled=True,
            model_spec="provider:model",
        )


@pytest.mark.asyncio
async def test_rejects_chunk_from_another_knowledge_base():
    chunks = [SimpleNamespace(kb_id="kb-other", chunk_id="chunk-1", file_id="file-1", content="证据")]
    service = KnowledgeGraphSolutionService(
        graph_service=_GraphService(_path()),
        chunk_repository=_ChunkRepository(chunks),
    )

    with pytest.raises(ValueError, match="可回切"):
        await service.generate(
            kb_id="kb-1",
            query="能力需求",
            discovery_mode="top_down",
            llm_enabled=True,
            model_spec="provider:model",
        )


@pytest.mark.asyncio
async def test_cross_document_solution_requires_multi_source_path():
    chunks = [SimpleNamespace(kb_id="kb-1", chunk_id="chunk-1", file_id="file-1", content="跨文档证据")]
    graph = _GraphService(_path(file_ids=["file-1", "file-2"]))
    service = KnowledgeGraphSolutionService(
        graph_service=graph,
        chunk_repository=_ChunkRepository(chunks),
        revision_repository=_RevisionRepository(),
        generator_factory=lambda _: _Generator(),
    )

    result = await service.generate(
        kb_id="kb-1",
        query="跨来源技术牵引",
        discovery_mode="bottom_up",
        llm_enabled=True,
        model_spec="provider:model",
        max_paths=4,
        evidence_scope="cross_document",
    )

    assert graph.call["max_paths"] == 12
    assert result["evidence_scope"] == "cross_document"
    assert result["source_document_count"] == 2
    assert result["cross_document_path_count"] == 1

    single_source = KnowledgeGraphSolutionService(graph_service=_GraphService(_path()))
    with pytest.raises(ValueError, match="至少两个来源文件"):
        await single_source.generate(
            kb_id="kb-1",
            query="跨来源技术牵引",
            discovery_mode="bottom_up",
            llm_enabled=True,
            model_spec="provider:model",
            evidence_scope="cross_document",
        )
