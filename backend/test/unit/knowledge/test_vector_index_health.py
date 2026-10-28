from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from platform_core.knowledge.base import KBIndexNotReadyError
from platform_core.knowledge.manager import KnowledgeBaseManager
from platform_core.knowledge.read_models import KnowledgeBaseDetail


def _database(*, kb_type: str = "milvus", indexed_count: int = 1) -> KnowledgeBaseDetail:
    return KnowledgeBaseDetail(
        kb_id="kb_1",
        name="索引健康测试",
        description=None,
        kb_type=kb_type,
        embedding_model_spec="provider:embedding" if kb_type == "milvus" else None,
        llm_model_spec=None,
        query_params={},
        additional_params={},
        share_config={"version": 2, "read_scope": None, "manage_scope": None},
        created_by="owner",
        created_at=None,
        indexed_count=indexed_count,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("expected_count", "vector_count", "status", "searchable"),
    [
        (91, 91, "ready", True),
        (91, 0, "missing", False),
        (91, 80, "incomplete", False),
        (91, 100, "stale", False),
        (0, 0, "missing", False),
    ],
)
async def test_vector_index_health_compares_postgres_and_milvus(
    tmp_path,
    monkeypatch,
    expected_count,
    vector_count,
    status,
    searchable,
):
    manager = KnowledgeBaseManager(str(tmp_path))
    manager.get_database_info = AsyncMock(return_value=_database())
    manager.get_kb_executor = AsyncMock(
        return_value=SimpleNamespace(get_vector_index_count=AsyncMock(return_value=vector_count))
    )
    monkeypatch.setattr(
        "platform_core.repositories.knowledge_chunk_repository.KnowledgeChunkRepository.count_by_kb_id",
        AsyncMock(return_value=expected_count),
    )

    health = await manager.get_vector_index_health("kb_1")

    assert health["status"] == status
    assert health["searchable"] is searchable
    assert health["expected_chunk_count"] == expected_count
    assert health["vector_count"] == vector_count


@pytest.mark.asyncio
async def test_vector_index_health_treats_new_empty_database_as_consistent(tmp_path, monkeypatch):
    manager = KnowledgeBaseManager(str(tmp_path))
    manager.get_database_info = AsyncMock(return_value=_database(indexed_count=0))
    manager.get_kb_executor = AsyncMock(
        return_value=SimpleNamespace(get_vector_index_count=AsyncMock(return_value=0))
    )
    monkeypatch.setattr(
        "platform_core.repositories.knowledge_chunk_repository.KnowledgeChunkRepository.count_by_kb_id",
        AsyncMock(return_value=0),
    )

    health = await manager.get_vector_index_health("kb_1")

    assert health["status"] == "empty"
    assert health["consistent"] is True
    with pytest.raises(KBIndexNotReadyError):
        await manager.ensure_vector_index_searchable("kb_1")


@pytest.mark.asyncio
async def test_external_index_health_does_not_require_milvus(tmp_path):
    manager = KnowledgeBaseManager(str(tmp_path))
    manager.get_database_info = AsyncMock(return_value=_database(kb_type="dify"))
    manager.get_kb_executor = AsyncMock(side_effect=AssertionError("external index must not load Milvus"))

    health = await manager.ensure_vector_index_searchable("kb_1")

    assert health["status"] == "not_applicable"
    assert health["searchable"] is True
