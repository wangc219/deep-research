"""真实 ARQ worker 恢复未发布 PostgreSQL Durable Task 的 assembled path。"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import delete

from platform_core.knowledge.eval.service import EvaluationService
from platform_core.repositories.evaluation_repository import EvaluationRepository
from platform_core.repositories.task_repository import TaskRepository
from platform_core.services import task_service
from platform_core.services import run_queue_service
from platform_core.services.run_queue_service import close_queue_clients
from platform_core.services.task_queue_service import reconcile_and_publish_tasks
from platform_core.storage.redis import manager as redis_manager
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import TaskRecord
from platform_core.storage.postgres.models_knowledge import KnowledgeBase

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """本文件直接使用 shipping PostgreSQL 与 worker，不依赖 HTTP API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    yield


@pytest_asyncio.fixture(autouse=True)
async def bind_pg_manager_to_test_loop():
    """Give every function-scoped asyncio loop its own PostgreSQL pools."""
    # A previous integration module may have left the singleton pointing at a
    # psycopg async pool whose owning pytest loop is already closed.  Awaiting
    # ``close()`` from this function's new loop raises ``CancelledError`` and
    # prevents the fixture from starting.  Detach that unusable state first;
    # pools created below are still closed normally in this fixture's loop.
    pg_manager.async_engine = None
    pg_manager.AsyncSession = None
    pg_manager.langgraph_pool = None
    pg_manager.langgraph_checkpointer = None
    pg_manager._langgraph_checkpointer_setup = False
    pg_manager._initialized = False
    run_queue_service._arq_pool = None
    redis_manager._async_redis_client = None
    redis_manager._async_redis_lock = None
    pg_manager.initialize()
    try:
        yield
    finally:
        await close_queue_clients()
        await pg_manager.close()


def _gate_identity(kind: str = "success") -> tuple[str, str]:
    suffix = os.getenv("DURABLE_TASK_GATE_ID", "local").replace("-", "_")[:24]
    return f"kb_task_worker_{suffix}_{kind}", f"durable-task-worker-{suffix}-{kind}"


async def _delete_gate_facts(kb_id: str) -> None:
    datasets = await EvaluationRepository().list_datasets(kb_id)
    task_ids = [str((dataset.build_metadata or {}).get("task_id") or "") for dataset in datasets]
    async with pg_manager.get_async_session_context() as session:
        if task_ids:
            await session.execute(delete(TaskRecord).where(TaskRecord.id.in_(task_ids)))
        await session.execute(delete(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))


async def test_prepare_task_with_failed_initial_arq_publication(monkeypatch) -> None:
    """在 worker 停止时留下已提交但尚未发布的 Task intent。"""
    kb_id, dataset_name = _gate_identity()
    await _delete_gate_facts(kb_id)
    async with pg_manager.get_async_session_context() as session:
        session.add(KnowledgeBase(kb_id=kb_id, name=dataset_name, kb_type="milvus"))

    async def fail_initial_publication(_task_id: str) -> None:
        raise ConnectionError("simulated Redis publication failure")

    monkeypatch.setattr(task_service, "publish_task", fail_initial_publication)
    submitted = await EvaluationService().generate_dataset(
        kb_id=kb_id,
        name=dataset_name,
        description="deterministic worker path",
        count=0,
        neighbors_count=1,
        concurrency_count=1,
        llm_model_spec="unused:model",
        created_by="integration",
    )

    task = await TaskRepository().get_by_id(submitted["task_id"])
    dataset = await EvaluationRepository().get_dataset(submitted["dataset_id"])
    assert task.status == "pending"
    assert (dataset.build_metadata or {}).get("status") == "pending"


async def test_shipping_worker_startup_recovers_pending_publication() -> None:
    """由真实 worker startup reconciliation 恢复遗留的 pending intent。"""
    kb_id, _dataset_name = _gate_identity()
    # Invoke the same production entrypoint used by ``_worker_startup``.  The
    # long-running worker may have started before this test created the intent,
    # so relying on its 30-second periodic reconciliation makes the integration
    # test timing-dependent and slower than its original 15-second deadline.
    await reconcile_and_publish_tasks()
    datasets = await EvaluationRepository().list_datasets(kb_id)
    assert len(datasets) == 1
    dataset = datasets[0]
    task_id = str((dataset.build_metadata or {}).get("task_id") or "")
    assert task_id

    try:
        for _attempt in range(150):
            task = await TaskRepository().get_by_id(task_id)
            dataset = await EvaluationRepository().get_dataset(dataset.dataset_id)
            if task and task.status == "success" and (dataset.build_metadata or {}).get("status") == "completed":
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("Durable Task did not converge through worker startup publication")

        assert task.attempt_count == 1
        assert task.worker_id is None
        assert (dataset.build_metadata or {}).get("task_id") == task_id
    finally:
        await _delete_gate_facts(kb_id)


async def test_shipping_worker_failure_runs_domain_hook() -> None:
    """真实 worker 失败必须在同一终态事务中收敛数据集领域状态。"""
    kb_id, dataset_name = _gate_identity("failure")
    await _delete_gate_facts(kb_id)
    async with pg_manager.get_async_session_context() as session:
        session.add(KnowledgeBase(kb_id=kb_id, name=dataset_name, kb_type="dify"))

    submitted = await EvaluationService().generate_dataset(
        kb_id=kb_id,
        name=dataset_name,
        description="deterministic failure-hook path",
        count=1,
        neighbors_count=1,
        concurrency_count=1,
        llm_model_spec="unused:model",
        created_by="integration",
    )

    try:
        for _attempt in range(150):
            task = await TaskRepository().get_by_id(submitted["task_id"])
            dataset = await EvaluationRepository().get_dataset(submitted["dataset_id"])
            metadata = dataset.build_metadata or {}
            if task and task.status == "failed" and metadata.get("status") == "failed":
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("Durable Task failure hook did not converge through the shipping worker")

        assert task.attempt_count == 1
        assert task.worker_id is None
        assert metadata.get("task_id") == task.id
        assert metadata.get("progress") == 100
        assert metadata.get("error_message")
    finally:
        await _delete_gate_facts(kb_id)
