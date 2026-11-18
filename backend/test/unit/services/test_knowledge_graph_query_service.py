from __future__ import annotations

import pytest

from platform_core.services.knowledge_graph_query_service import KnowledgeGraphQueryService

pytestmark = pytest.mark.asyncio


class _Repository:
    def __init__(self):
        self.calls = []

    async def get_entity_detail(self, **kwargs):
        self.calls.append(("entity", kwargs))
        return {"entity": {"entity_id": kwargs["entity_id"]}}

    async def get_relation_detail(self, **kwargs):
        self.calls.append(("relation", kwargs))
        return {"relation": {"triple_id": kwargs["triple_id"]}}

    async def list_revisions(self, **kwargs):
        self.calls.append(("revisions", kwargs))
        return {"items": [], "count": 0}

    async def list_changes(self, **kwargs):
        self.calls.append(("changes", kwargs))
        return {"items": [], "count": 0}


async def test_query_service_delegates_authoritative_entity_and_relation_reads():
    repository = _Repository()
    service = KnowledgeGraphQueryService(repository=repository)

    entity = await service.get_entity_detail(kb_id="kb", entity_id="entity", evidence_limit=25)
    relation = await service.get_relation_detail(kb_id="kb", triple_id="triple", evidence_limit=30)

    assert entity["entity"]["entity_id"] == "entity"
    assert relation["relation"]["triple_id"] == "triple"
    assert repository.calls == [
        ("entity", {"kb_id": "kb", "entity_id": "entity", "evidence_limit": 25}),
        ("relation", {"kb_id": "kb", "triple_id": "triple", "evidence_limit": 30}),
    ]


async def test_query_service_preserves_revision_and_change_filters():
    repository = _Repository()
    service = KnowledgeGraphQueryService(repository=repository)

    await service.list_revisions(kb_id="kb", limit=20, offset=5)
    await service.list_changes(
        kb_id="kb",
        graph_revision="revision",
        target_type="relation",
        target_id="triple",
        limit=40,
        offset=10,
    )

    assert repository.calls == [
        ("revisions", {"kb_id": "kb", "limit": 20, "offset": 5}),
        (
            "changes",
            {
                "kb_id": "kb",
                "graph_revision": "revision",
                "target_type": "relation",
                "target_id": "triple",
                "limit": 40,
                "offset": 10,
            },
        ),
    ]
