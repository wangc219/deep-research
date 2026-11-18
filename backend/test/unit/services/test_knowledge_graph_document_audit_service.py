from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from platform_core.services.knowledge_graph_document_audit_service import KnowledgeGraphDocumentAuditService


class FakeValueRouter:
    def __init__(self) -> None:
        self.closed = False

    async def assess(self, document, triage):
        del triage
        return {
            "status": "completed",
            "model_spec": "project:model",
            "priority": "high",
            "focused_reextraction_recommended": document["document_id"] == "doc-high",
        }

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_document_audit_routes_high_value_research_to_focused_reextraction():
    repository = AsyncMock()
    repository.load_documents.return_value = [
        {
            "document_id": "doc-high",
            "document_version": 1,
            "title": "雷达装备抗干扰新架构",
            "blocks": [
                {
                    "block_id": "b1",
                    "page": 1,
                    "text": "摘要 本文提出雷达装备抗干扰新架构并提升复杂环境探测能力。" + "实验结果有效。" * 120,
                }
            ],
        }
    ]
    router = FakeValueRouter()
    service = KnowledgeGraphDocumentAuditService(
        repository=repository,
        value_router_factory=lambda _: router,
    )

    result = await service.triage(
        kb_id="kb-1",
        document_ids=["doc-high"],
        options={
            "enabled": True,
            "filter_non_research": True,
            "value_routing": {
                "enabled": True,
                "model_spec": "project:model",
                "concurrency_count": 2,
            },
        },
    )

    assert result["focused_reextraction_documents"] == 1
    assert result["value_routing_enabled"] is True
    assert result["results"][0]["focused_reextraction_recommended"] is True
    persisted = repository.persist_triage.await_args.kwargs["results"][0]
    assert persisted["signals"]["lightrag_value_routing"]["priority"] == "high"
    assert router.closed is True
