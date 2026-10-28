"""真实 PostgreSQL、文件读取与 MinIO 写入下的批量解析并发。"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from platform_core.knowledge.implementations.milvus import MilvusKB
from platform_core.services import knowledge_task_service
from platform_core.storage.minio import get_minio_client
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import KnowledgeBase, KnowledgeFile
from platform_core.storage.postgres.models_business import TaskRecord
from platform_core.utils.datetime_utils import utc_now_naive


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_parse_owns_each_file_and_persists_ordered_results(tmp_path, monkeypatch):
    pg_manager.initialize()
    suffix = uuid4().hex
    kb_id = f"pytest_parse_{suffix}"
    file_ids = [f"parse_{suffix}_{index}" for index in range(3)]
    backend = MilvusKB.__new__(MilvusKB)
    active = 0
    peak = 0
    both_started = asyncio.Event()
    progress = []
    result = {}

    async def parse_file(kb, file_id, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), 5)
        try:
            return await backend.parse_file(kb, file_id, additional_params={}, **kwargs)
        finally:
            active -= 1

    async def set_progress(value, message):
        progress.append(value)

    async def set_result(value):
        result.update(value)

    async def check_cancel():
        return None

    monkeypatch.setattr(knowledge_task_service, "knowledge_base", SimpleNamespace(parse_file=parse_file))
    context = SimpleNamespace(
        task_id=suffix,
        worker_id="pytest-parser",
        payload={
            "kb_id": kb_id,
            "file_ids": file_ids,
            "operator_id": "pytest",
        },
        set_progress=set_progress,
        set_result=set_result,
        raise_if_cancelled=check_cancel,
    )
    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(
                TaskRecord(
                    id=suffix,
                    name="pytest parse ownership",
                    type="knowledge_parse",
                    status="running",
                    worker_id="pytest-parser",
                    lease_expires_at=utc_now_naive() + timedelta(minutes=5),
                )
            )
            session.add(KnowledgeBase(kb_id=kb_id, name="pytest parallel parse", kb_type="milvus"))
            await session.flush()
            for index, file_id in enumerate(file_ids):
                source = tmp_path / f"{index}.txt"
                source.write_text(f"searchable document {index}", encoding="utf-8")
                session.add(
                    KnowledgeFile(
                        kb_id=kb_id,
                        file_id=file_id,
                        filename=source.name,
                        path=str(source),
                        status="uploaded",
                    )
                )
        await knowledge_task_service.run_knowledge_parse(context)
        assert peak == 2
        assert active == 0
        assert progress == sorted(progress)
        assert result["failed"] == 0, result
        assert [item["file_id"] for item in result["items"]] == file_ids
        async with pg_manager.get_async_session_context() as session:
            files = list(await session.scalars(select(KnowledgeFile).where(KnowledgeFile.kb_id == kb_id)))
        assert len(files) == 3
        assert all(file.status == "parsed" and file.processing_owner is None and file.markdown_file for file in files)
        client = get_minio_client()
        for index, file_id in enumerate(file_ids):
            saved = await client.adownload_file(client.KB_BUCKETS["parsed"], f"{kb_id}/parsed/{file_id}.md")
            assert saved.decode() == f"searchable document {index}"
    finally:
        client = get_minio_client()
        for file_id in file_ids:
            await client.adelete_file(client.KB_BUCKETS["parsed"], f"{kb_id}/parsed/{file_id}.md")
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)
            task = await session.get(TaskRecord, suffix)
            if task is not None:
                await session.delete(task)
        await pg_manager.close()
