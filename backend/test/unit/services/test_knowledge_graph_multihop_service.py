from __future__ import annotations

import pytest

from platform_core.services.knowledge_graph_multihop_service import KnowledgeGraphMultiHopService


class _GraphService:
    def __init__(self):
        self.call = None

    async def discover_paths(self, kb_id, **kwargs):
        self.call = {"kb_id": kb_id, **kwargs}
        return {
            "mode": kwargs["mode"],
            "paths": [{"path_id": "p-1"}],
            "summary": {},
            "query_plan": {},
            "query_analysis": {},
        }


class _Synthesizer:
    def __init__(self, options):
        self.options = options
        self.call = None

    async def synthesize(self, **kwargs):
        self.call = kwargs
        return {
            "narrative": {"executive_conclusion": "结论"},
            "provenance": {"status": "completed"},
        }

    async def aclose(self):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "internal", "resolved"),
    [("top_down", "requirement_driven", "top_down"), ("bottom_up", "entity_expansion", "bottom_up")],
)
async def test_multihop_service_exposes_parallel_feature_contract(requested, internal, resolved):
    graph = _GraphService()
    service = KnowledgeGraphMultiHopService(graph_service=graph, synthesizer_factory=_Synthesizer)

    result = await service.discover(
        kb_id="kb-1",
        query="任务输入",
        discovery_mode=requested,
        narrative={"enabled": True, "model_spec": "cloud:model"},
    )

    assert graph.call["mode"] == internal
    assert result["feature_kind"] == "multi_hop_retrieval"
    assert result["discovery_mode"] == resolved
    assert result["narrative"]["executive_conclusion"] == "结论"
    assert result["summary"]["narrative_status"] == "completed"
