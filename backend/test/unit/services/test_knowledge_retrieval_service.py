"""共享检索保持资源权限交集，拒绝请求不能触发模型费用。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from platform_core.services.knowledge_retrieval_service import (
    list_visible_knowledge_bases,
    retrieve_visible_knowledge,
    retrieve_visible_knowledge_batch,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def manager(monkeypatch):
    summaries = [SimpleNamespace(kb_id=key, name=key, description=None, kb_type="milvus") for key in ("a", "b")]
    manager = SimpleNamespace(get_databases_by_uid=AsyncMock(return_value=summaries), retrieve=AsyncMock())
    monkeypatch.setattr("platform_core.knowledge.runtime.knowledge_base", manager)
    return manager


async def test_anonymous_does_not_lookup_resources(manager):
    assert await list_visible_knowledge_bases(None) == []
    manager.get_databases_by_uid.assert_not_awaited()


@pytest.mark.parametrize("enabled, expected", [(None, ["a", "b"]), ([], []), (["b", "unauthorized"], ["b"])])
async def test_enabled_resources_intersect_permissions(manager, enabled, expected):
    result = await list_visible_knowledge_bases("owner", enabled_ids=enabled)
    assert [item["kb_id"] for item in result] == expected
    manager.get_databases_by_uid.assert_awaited_once_with("owner")


@pytest.mark.parametrize("visible", [[], [{"kb_id": "a"}]])
async def test_unauthorized_retrieval_never_calls_models(manager, visible):
    with pytest.raises(PermissionError):
        await retrieve_visible_knowledge(kb_id="denied", query_text="test", visible_kbs=visible)
    manager.retrieve.assert_not_awaited()


async def test_retrieval_preserves_citations_and_file_filter(manager):
    manager.retrieve.return_value = {"results": [{"content": "test", "file_id": "document", "chunk_id": "1"}]}
    result = await retrieve_visible_knowledge(
        kb_id="a", query_text="test", visible_kbs=[{"kb_id": "a"}], file_name="manual.pdf"
    )
    assert result is manager.retrieve.return_value
    manager.retrieve.assert_awaited_once_with("a", "test", file_name="manual.pdf")


async def test_provider_failure_is_not_an_empty_result(manager):
    manager.retrieve.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await retrieve_visible_knowledge(kb_id="a", query_text="test", visible_kbs=[{"kb_id": "a"}])


async def test_batch_retrieval_intersects_scope_and_isolates_provider_failure(manager):
    async def retrieve(kb_id, query_text, **kwargs):
        assert query_text == "enterprise maintenance"
        assert kwargs == {}
        if kb_id == "b":
            raise RuntimeError("temporary outage")
        return {"kb_id": kb_id, "results": [{"content": "manual", "file_id": "doc-1", "chunk_id": "c-1"}]}

    manager.retrieve.side_effect = retrieve
    result = await retrieve_visible_knowledge_batch(
        uid="owner",
        query_text="enterprise maintenance",
        enabled_ids=["a", "b", "unauthorized"],
    )

    assert result["selected_count"] == 2
    assert result["omitted_count"] == 0
    assert [item["kb_id"] for item in result["retrievals"]] == ["a"]
    assert result["retrievals"][0]["result"]["results"][0]["file_id"] == "doc-1"
    assert result["failures"] == [
        {
            "kb_id": "b",
            "name": "b",
            "error_type": "RuntimeError",
            "error": "temporary outage",
        }
    ]
    assert {call.args[0] for call in manager.retrieve.await_args_list} == {"a", "b"}


async def test_batch_retrieval_empty_scope_never_calls_models(manager):
    result = await retrieve_visible_knowledge_batch(uid="owner", query_text="test", enabled_ids=[])

    assert result["selected_count"] == 0
    assert result["retrievals"] == []
    assert result["failures"] == []
    manager.retrieve.assert_not_awaited()
