from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.routers.graph_router import InnovationDiscoveryRequest
from platform_core.services.knowledge_graph_innovation_service import KnowledgeGraphInnovationService


class _GraphService:
    def __init__(self):
        self.call = None

    async def discover_paths(self, kb_id, **kwargs):
        self.call = {"kb_id": kb_id, **kwargs}
        return {
            "paths": [
                {
                    "path_id": "path-1",
                    "score": 5.0,
                    "semantic_coverage": 0.8,
                    "nodes": [
                        {
                            "name": "技术 A",
                            "type": "KeyTechnology",
                            "semantic_role": "technology",
                            "properties": {"entity_id": "entity-a"},
                        },
                        {
                            "name": "能力 B",
                            "type": "Capability",
                            "semantic_role": "capability",
                            "properties": {"entity_id": "entity-b"},
                        },
                        {
                            "name": "应用 C",
                            "type": "ApplicationScenario",
                            "semantic_role": "application",
                            "properties": {"entity_id": "entity-c"},
                        },
                    ],
                    "relation_ids": ["r1", "r2"],
                    "evidence": {"mention_count": 2, "chunk_ids": ["c1"], "file_ids": ["f1"]},
                    "evidence_gaps": [],
                    "research_inspiration": {},
                }
            ],
            "summary": {"retrieval_mode": "semantic"},
            "path_reranking": {"status": "completed", "ranked_count": 1},
            "pipeline_trace": {
                "contract_version": "lightrag-query-trace-v1",
                "degraded": False,
                "stages": [{"key": "path_search", "status": "completed"}],
            },
        }


class _Repository:
    def __init__(self):
        self.saved = []

    async def save_hypotheses(self, kb_id, candidates):
        self.saved = candidates
        return candidates

    async def latest_revision(self, kb_id):
        return "revision-1"


@pytest.mark.asyncio
async def test_service_uses_fact_only_paths_and_persists_hypotheses():
    graph = _GraphService()
    repository = _Repository()
    service = KnowledgeGraphInnovationService(graph_service=graph, repository=repository)

    result = await service.discover(
        kb_id="kb-1",
        query="能力需求",
        discovery_mode="top_down",
        max_hops=4,
        max_candidates=5,
        evidence_scope="any",
        path_reranking={"enabled": True, "model_spec": "local:military-chat"},
    )

    assert graph.call["mode"] == "requirement_driven"
    assert graph.call["include_combinations"] is False
    assert graph.call["review_scope"] == "all"
    assert graph.call["path_reranking"] == {"enabled": True, "model_spec": "local:military-chat"}
    assert repository.saved[0]["claim_level"] == "Hypothesis"
    assert result["graph_revision"] == "revision-1"
    assert result["persisted"] is True
    assert result["retrieval_summary"]["retrieval_mode"] == "semantic"
    assert result["innovation_enhancement"]["status"] == "disabled"
    assert result["path_reranking"] == {"status": "completed", "ranked_count": 1}
    assert result["pipeline_trace"]["contract_version"] == "lightrag-query-trace-v1"
    assert result["feedback_loop"]["contract_version"] == "lightrag-defense-feedback-v1"
    assert result["feedback_loop"]["status"] == "ready"
    assert result["feedback_loop"]["automatic_graph_write"] is False
    assert result["evidence_scope"] == "any"
    assert result["cross_document_candidate_count"] == 0
    assert result["query_analysis"]["analysis_version"] == "defense-requirement-analysis-v2"
    assert result["feature_kind"] == "innovation_hypothesis_generation"
    assert result["discovery_mode"] == "top_down"
    assert {item["requirement_field"] for item in result["query_analysis"]["entity_mappings"]} == {
        "target_capabilities",
        "application_scenarios",
        "key_technical_elements",
    }


@pytest.mark.asyncio
async def test_read_only_preview_allows_pending_evidence_without_persisting():
    graph = _GraphService()
    graph_result = await graph.discover_paths("kb-1")
    graph_result["paths"][0].update(
        {
            "claim_level": "Inference",
            "pending_evidence": True,
            "evidence": {
                **graph_result["paths"][0]["evidence"],
                "review_statuses": ["pending"],
                "pending_relation_count": 2,
                "pending_evidence": True,
            },
        }
    )

    async def discover_paths(kb_id, **kwargs):
        graph.call = {"kb_id": kb_id, **kwargs}
        return graph_result

    graph.discover_paths = discover_paths
    repository = _Repository()
    service = KnowledgeGraphInnovationService(graph_service=graph, repository=repository)

    result = await service.discover(
        kb_id="kb-1",
        query="能力需求",
        discovery_mode="top_down",
        persist=False,
        retrieval_mode="mix",
        evidence_scope="any",
    )

    assert graph.call["review_scope"] == "all"
    assert repository.saved == []
    assert result["preview_mode"] is True
    assert result["persisted"] is False
    assert result["pending_evidence"] is True
    assert result["expert_review_required"] is True
    assert result["hypotheses"][0]["pending_evidence"] is True
    assert result["hypotheses"][0]["evidence_path"]["pending_relation_count"] == 2


def test_innovation_request_exposes_strict_cross_document_scope():
    request = InnovationDiscoveryRequest(
        query="跨文档技术迁移",
        discovery_mode="bottom_up",
        evidence_scope="cross_document",
    )

    assert request.evidence_scope == "cross_document"
    assert request.path_reranking_enabled is False
    assert request.innovation_llm_concurrency == 2
    with pytest.raises(ValidationError):
        InnovationDiscoveryRequest(
            query="跨文档技术迁移",
            discovery_mode="bottom_up",
            evidence_scope="unbounded",
        )
    with pytest.raises(ValidationError):
        InnovationDiscoveryRequest(
            query="跨文档技术迁移",
            discovery_mode="bottom_up",
            innovation_llm_concurrency=9,
        )
