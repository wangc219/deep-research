"""真实 PostgreSQL、HTTP 与 Task handler 验证 Query 完整性。"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from equipment_deep_research.query_library.generator import ModelQueryGenerator
from equipment_deep_research.query_library.models import GenerationValidationError
from equipment_deep_research.query_library.quality import coverage_plan
from platform_core.repositories import task_repository
from platform_core.services import equipment_model_adapter, equipment_query_task, equipment_research_service as svc
from platform_core.services.task_service import TaskContext
from platform_core.services.project_service import ensure_equipment_project_record
from platform_core.storage.postgres.manager import PostgresManager
from platform_core.storage.postgres.models_business import Base, OperationLog, Project, TaskRecord, User
from platform_core.storage.postgres.models_equipment import (
    EquipmentQuery,
    EquipmentQueryGeneration,
    EquipmentQueryRevision,
    EquipmentResearchRun,
    EquipmentResearchEvent,
)
from platform_core.utils.datetime_utils import utc_now_naive
from server.routers.equipment_router import equipment, get_db, get_required_user

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """使用隔离 Schema，无需修改运行实例。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """不创建运行实例中的知识库。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """不创建沙箱。"""
    yield


@pytest.fixture
async def query_db(monkeypatch):
    schema = "pytest_query_" + uuid4().hex[:16]
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    tables = set()

    def include(table):
        if table in tables:
            return
        tables.add(table)
        for fk in table.foreign_keys:
            include(fk.column.table)

    for model in (
        User,
        Project,
        TaskRecord,
        OperationLog,
        EquipmentQuery,
        EquipmentQueryRevision,
        EquipmentQueryGeneration,
        EquipmentResearchRun,
        EquipmentResearchEvent,
    ):
        include(model.__table__)
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=list(tables)))
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager.AsyncSession = async_sessionmaker(engine, expire_on_commit=False)
    manager._initialized = True
    monkeypatch.setattr(task_repository, "pg_manager", manager)
    async with manager.get_async_session_context() as db:
        users = [
            User(uid=f"query-user-{n}", username=f"query-user-{n}", password_hash="test-disabled", role="user")
            for n in (1, 2)
        ]
        db.add_all(users)
        await db.flush()
    try:
        yield manager, users
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.fixture
async def query_http(query_db):
    manager, users = query_db
    app = FastAPI()
    app.include_router(equipment, prefix="/api")

    async def database():
        async with manager.get_async_session_context() as db:
            yield db

    async def current_user(request: Request):
        return users[int(request.headers.get("x-test-user", "0"))]

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_required_user] = current_user
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    running = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{sock.getsockname()[1]}", timeout=10) as client:
            yield client
    finally:
        server.should_exit = True
        await running
        sock.close()


async def test_http_shared_history_version_conflicts_and_personal_isolation(query_db, query_http):
    manager, users = query_db
    client = query_http
    created = await client.post("/api/equipment/queries", json={"query": "历史通信终端及配套供电系统研究"})
    assert created.status_code == 200, created.text
    row = created.json()
    query_id = row["query_id"]
    async with manager.get_async_session_context() as db:
        stored = await db.get(EquipmentQuery, query_id)
        stored.legacy_source_id = "original-query"
        stored.import_batch_id = "workbench-sync"
    other = {"x-test-user": "1"}
    visible = await client.get(f"/api/equipment/queries/{query_id}", headers=other)
    assert visible.status_code == 200
    assert visible.json()["readonly"] is False
    first, second = await asyncio.gather(
        *[
            client.patch(
                f"/api/equipment/queries/{query_id}",
                headers=other,
                json={"expected_version": 1, "supplemental_information": value},
            )
            for value in ("并发修改甲", "并发修改乙")
        ]
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    detail = (await client.get(f"/api/equipment/queries/{query_id}", headers=other)).json()
    assert detail["owner_uid"] == users[0].uid
    assert detail["last_modified_by"] == users[1].uid
    assert detail["payload"]["original_snapshot"]["query"] == row["query"]
    assert detail["payload"]["original_snapshot"]["version"] == 1
    published = await client.post(
        f"/api/equipment/queries/{query_id}/publish", headers=other, json={"expected_version": 2}
    )
    assert published.status_code == 200
    assert (
        await client.delete(f"/api/equipment/queries/{query_id}?expected_version=2", headers=other)
    ).status_code == 409
    archived = await client.post(
        f"/api/equipment/queries/{query_id}/archive", headers=other, json={"expected_version": 3}
    )
    assert archived.status_code == 200
    assert (
        await client.delete(f"/api/equipment/queries/{query_id}?expected_version=4", headers=other)
    ).status_code == 200
    async with manager.get_async_session_context() as db:
        logs = list((await db.scalars(select(OperationLog))).all())
        assert len(logs) == 4
        assert all(users[1].uid in log.details and query_id in log.details for log in logs)
    private = (await client.post("/api/equipment/queries", json={"query": "个人独立研究问题"})).json()
    assert (await client.get(f"/api/equipment/queries/{private['query_id']}", headers=other)).status_code == 404
    assert (
        await client.patch(
            f"/api/equipment/queries/{private['query_id']}",
            headers=other,
            json={"expected_version": 1, "query": "越权修改"},
        )
    ).status_code == 404


async def test_http_projectless_creation_is_serialized_and_cross_project_lineage(query_db, query_http, monkeypatch):
    manager, users = query_db
    responses = await asyncio.gather(
        *[query_http.post("/api/equipment/queries", json={"query": f"零项目账号研究选题{n}"}) for n in (1, 2)]
    )
    assert all(item.status_code == 200 for item in responses)
    project_ids = {item.json()["project_id"] for item in responses}
    assert len(project_ids) == 1
    other = await query_http.post(
        "/api/equipment/queries", headers={"x-test-user": "1"}, json={"query": "第二用户的研究"}
    )
    assert other.json()["project_id"] not in project_ids
    query = responses[0].json()
    await query_http.post(f"/api/equipment/queries/{query['query_id']}/publish", json={"expected_version": 1})

    async def no_default(_db):
        return ""

    monkeypatch.setattr(equipment_model_adapter, "default_chat_model_spec", no_default)
    async with manager.get_async_session_context() as db:
        target = Project(
            id=str(uuid4()),
            uid=users[0].uid,
            name="另一个研究项目",
            directory_mode="managed",
            selection_status="selectable",
            workdir_path="projects/target",
            status="active",
        )
        db.add(target)
        await db.flush()
        result = await svc.create_run(
            db=db,
            user=users[0],
            project_id=target.id,
            topic=query["query"],
            source_query_id=query["query_id"],
            source_query_version=2,
        )
        assert result["project_id"] == target.id
        assert result["payload"]["query_library"]["snapshot"]["project_id"] == query["project_id"]
        assert result["source_query_id"] == query["query_id"]


def candidate_row(slot):
    index = coverage_plan(20).index(slot)
    titles = [
        "通信受扰条件下终端供电协同保障研究",
        "低温条件下自主通信电源技术验证研究",
        "自主通信网络感知与协同恢复体系研究",
        "低成本通信载荷集成与替换验证研究",
    ]
    query = titles[index]
    return {
        "coverage_slot": slot,
        "query": query,
        "supplemental_information": (
            "面向通信受扰与持续运行任务，分析智能自主通信终端的供电、接口、失效边界及可验证的装备需求。"
        ),
        "generation_rationale": "从公开任务约束反推通信终端与供电系统的具体研究问题。",
        "demand_chain": {
            "situation_signal": "公开任务环境中通信条件持续发生变化",
            "future_mission": "未来需要持续完成自主通信保障任务",
            "task_constraint": "低温环境与供电限制持续通信保障",
            "capability_gap": "现有终端难以持续进行自主协同通信",
            "weapon_requirement": "通信终端及配套供电系统",
            "evidence_status": "verified",
            "disconfirmation_condition": "若现有终端已满足代表性通信保障任务则本需求不成立",
        },
        "quality_review": dict.fromkeys(
            ["verdict", "causal_specificity", "differentiation", "researchability"], "pass"
        ),
    }


class ProbeGenerator(ModelQueryGenerator):
    ground_calls = 0
    divergence_calls = 0
    missing = True
    entered = None
    release = None

    async def _ground(self, **_kwargs):
        type(self).ground_calls += 1
        return {"summary": "通信任务研究", "sources": []}, {}

    async def _diverge_demand_hypotheses(self, **_kwargs):
        type(self).divergence_calls += 1
        return []

    async def _generate_candidates(self, **kwargs):
        if self.entered is not None:
            self.entered.set()
            await self.release.wait()
        rows = [
            candidate_row(slot) for slot in kwargs["remaining_slots"] if not self.missing or slot != coverage_plan(2)[1]
        ]
        return {"queries": rows}, {}


@pytest.fixture(autouse=True)
def isolate_generator_probe_events():
    """隔离并发探针事件，避免前序失败让后续测试永久等待。"""
    ProbeGenerator.entered = ProbeGenerator.release = None
    yield
    if ProbeGenerator.release is not None:
        ProbeGenerator.release.set()
    ProbeGenerator.entered = ProbeGenerator.release = None


async def make_generation(manager, user):
    generation_id, task_id = "qgen-" + uuid4().hex, uuid4().hex
    async with manager.get_async_session_context() as db:
        project = await ensure_equipment_project_record(db=db, uid=str(user.uid), username=user.username)
        db.add(
            EquipmentQueryGeneration(
                id=generation_id,
                project_id=project.id,
                owner_uid=user.uid,
                topic="通信终端研究",
                status="queued",
                payload={"count": 2, "model_spec": "test:model"},
            )
        )
        db.add(
            TaskRecord(
                id=task_id,
                name="Query test",
                type="equipment_query_generation",
                status="running",
                worker_id="owner",
                lease_expires_at=utc_now_naive() + timedelta(minutes=5),
                payload={"generation_id": generation_id},
            )
        )
    return generation_id, TaskContext(task_id, "owner", {"generation_id": generation_id})


def stub_model(monkeypatch):
    monkeypatch.setattr(
        equipment_model_adapter,
        "resolve_managed_equipment_model",
        lambda _spec: {"provider": "test", "model": "model", "model_spec": "test:model"},
    )
    monkeypatch.setattr(equipment_model_adapter, "create_equipment_provider", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("equipment_deep_research.query_library.generator.ModelQueryGenerator", ProbeGenerator)
    ProbeGenerator.ground_calls = ProbeGenerator.divergence_calls = 0
    ProbeGenerator.entered = ProbeGenerator.release = None
    ProbeGenerator.missing = True


async def test_handler_partial_failure_retry_reuses_saved_result_and_planning(query_db, monkeypatch):
    manager, users = query_db
    stub_model(monkeypatch)
    generation_id, context = await make_generation(manager, users[0])
    with pytest.raises(GenerationValidationError, match="仅 1/2"):
        await equipment_query_task.run_equipment_query_generation(context)
    async with manager.get_async_session_context() as db:
        job = await db.get(EquipmentQueryGeneration, generation_id)
        assert job.status == "failed"
        saved_id = job.payload["query_ids"][0]
        assert len(job.payload["query_ids"]) == 1
        assert "hypotheses" in job.payload["planning_checkpoint"]
        row = await db.get(EquipmentQuery, saved_id)
        assert row.payload["demand_chain"]["evidence_status"] == "inferred"
        task = await db.get(TaskRecord, context.task_id)
        task.status = "failed"

    async def no_publish(_task_id):
        return None

    monkeypatch.setattr(svc, "publish_task", no_publish)
    async with manager.get_async_session_context() as db:
        retry = await svc.retry_query_generation(db=db, user=users[0], generation_id=generation_id)
        assert retry["query_ids"] == [saved_id]
    repository = task_repository.TaskRepository()
    pending = await repository.find_latest_by_payload(
        task_type="equipment_query_generation", payload_match={"generation_id": generation_id}, statuses={"pending"}
    )
    _, claimed = await repository.claim(pending.id, worker_id="retry-owner", lease_seconds=300, max_running=4)
    assert claimed
    context = TaskContext(pending.id, "retry-owner", {"generation_id": generation_id})
    ProbeGenerator.missing = False
    result = await equipment_query_task.run_equipment_query_generation(context)
    assert result["status"] == "completed"
    assert len(result["query_ids"]) == 2 and saved_id in result["query_ids"]
    assert ProbeGenerator.ground_calls == 1
    assert ProbeGenerator.divergence_calls == 0
    replay = await equipment_query_task.run_equipment_query_generation(context)
    assert replay == result
    assert ProbeGenerator.ground_calls == 1


@pytest.mark.parametrize("control", ["cancel", "lease_lost"])
async def test_late_model_result_cannot_write_after_cancel_or_lease_loss(query_db, monkeypatch, control):
    manager, users = query_db
    stub_model(monkeypatch)
    ProbeGenerator.missing = False
    ProbeGenerator.entered, ProbeGenerator.release = asyncio.Event(), asyncio.Event()
    generation_id, context = await make_generation(manager, users[0])
    execution = asyncio.create_task(equipment_query_task.run_equipment_query_generation(context))
    await asyncio.wait_for(ProbeGenerator.entered.wait(), timeout=5)
    if control == "cancel":
        async with manager.get_async_session_context() as db:
            cancelled = await svc.cancel_query_generation(db=db, user=users[0], generation_id=generation_id)
            assert cancelled["status"] == "cancelled"
    else:
        async with manager.get_async_session_context() as db:
            task = await db.get(TaskRecord, context.task_id)
            task.worker_id = "replacement-worker"
    ProbeGenerator.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(execution, timeout=5)
    async with manager.get_async_session_context() as db:
        assert not list((await db.scalars(select(EquipmentQuery))).all())
        job = await db.get(EquipmentQueryGeneration, generation_id)
        assert job.status == ("cancelled" if control == "cancel" else "running")


async def test_generation_batches_have_bounded_parallelism_and_save_results_early():
    active = peak = 0
    saved = []

    class ConcurrentGenerator(ProbeGenerator):
        missing = False
        entered = release = None

        async def _generate_candidates(self, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return {"queries": [candidate_row(slot) for slot in kwargs["remaining_slots"]]}, {}

    async def save(candidate):
        saved.append(candidate)

    result = await ConcurrentGenerator(object()).generate(
        topic="通信终端研究",
        supplemental_information="",
        count=4,
        existing_queries=[],
        batch_size=1,
        max_parallel=2,
        on_candidate=save,
    )
    assert peak == 2
    assert len(result.candidates) == len(saved) == 4


async def test_invalid_or_all_duplicate_generation_fails_without_template_candidates():
    class InvalidGenerator(ProbeGenerator):
        async def _generate_candidates(self, **_kwargs):
            return {"queries": []}, {}

    for generator, existing in [
        (InvalidGenerator(object()), []),
        (ProbeGenerator(object()), [candidate_row(coverage_plan(1)[0])["query"]]),
    ]:
        with pytest.raises(GenerationValidationError, match="仅 0/1"):
            await generator.generate(
                topic="通信终端研究", supplemental_information="", count=1, existing_queries=existing
            )


async def test_model_urls_are_not_tool_evidence_and_generic_outcomes_still_fail():
    from equipment_deep_research.query_library.generator import _candidate_from_payload, _grounding_sources
    from equipment_deep_research.query_library.models import SourceReference
    from equipment_deep_research.query_library.quality import validate_generated_candidate

    claimed = {"sources": [{"title": "模型写出的来源", "url": "https://example.test/invented"}]}
    assert _grounding_sources(claimed, {}) == ()
    real = [{"title": "工具检索来源", "url": "https://example.test/retrieved"}]
    assert [item.url for item in _grounding_sources(claimed, {"web_sources": real})] == [real[0]["url"]]
    row = candidate_row(coverage_plan(1)[0])
    sources = (SourceReference(title="未获得网页证据的模型分析", source_kind="document"),)
    candidate = _candidate_from_payload(row, sources)
    assert not validate_generated_candidate(
        candidate, expected_slot=coverage_plan(1)[0], existing_queries=[], accepted_queries=[]
    )
    row["demand_chain"]["weapon_requirement"] = "仅需要能够满足未来任务"
    generic = _candidate_from_payload(row, sources)
    assert any(
        "weapon_requirement" in issue
        for issue in validate_generated_candidate(
            generic, expected_slot=coverage_plan(1)[0], existing_queries=[], accepted_queries=[]
        )
    )


async def test_http_generation_accepts_no_project_and_replays_idempotent_request(query_db, query_http, monkeypatch):
    async def model(_db, _model_spec):
        return {"model_spec": "test:model"}

    async def no_publish(_task_id):
        return None

    monkeypatch.setattr(svc, "_resolve_requested_model", model)
    monkeypatch.setattr(svc, "publish_task", no_publish)
    payload = {"topic": "通信终端研究", "count": 2}
    headers = {"Idempotency-Key": "projectless-query-test"}
    created = await query_http.post("/api/equipment/query-generations", json=payload, headers=headers)
    assert created.status_code == 200, created.text
    replay = await query_http.post("/api/equipment/query-generations", json=payload, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["generation_id"] == created.json()["generation_id"]
    manager, users = query_db
    async with manager.get_async_session_context() as db:
        project = await db.get(Project, created.json()["project_id"])
        assert project.uid == users[0].uid and project.name == f"装备深研工作台 · {users[0].username}"
        assert len(list((await db.scalars(select(TaskRecord))).all())) == 1


async def test_event_batches_commit_before_redis_and_serialize_concurrent_writers(query_db, monkeypatch):
    from platform_core.services import equipment_research_task
    from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository

    manager, users = query_db
    run_id = "event-batch-" + uuid4().hex
    async with manager.get_async_session_context() as db:
        project = await ensure_equipment_project_record(db=db, uid=str(users[0].uid), username=users[0].username)
        db.add(
            EquipmentResearchRun(
                id=run_id,
                owner_uid=users[0].uid,
                project_id=project.id,
                topic="事件批量写入验证",
                status="researching",
                payload={},
            )
        )
    publications = []

    class Pipeline:
        def __init__(self):
            self.messages = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def xadd(self, key, fields, **kwargs):
            self.messages.append(json.loads(fields["payload"]))

        async def execute(self):
            # 使用独立连接证明通知发出前事务已提交。
            async with manager.get_async_session_context() as db:
                for message in self.messages:
                    stored = await db.scalar(
                        select(EquipmentResearchEvent).where(
                            EquipmentResearchEvent.run_id == run_id,
                            EquipmentResearchEvent.sequence == message["sequence"],
                        )
                    )
                    assert stored is not None
                    assert stored.sequence == message["sequence"]
            publications.extend(self.messages)

    class Redis:
        def pipeline(self, **kwargs):
            return Pipeline()

    async def redis():
        return Redis()

    monkeypatch.setattr(equipment_research_task, "pg_manager", manager)
    monkeypatch.setattr(equipment_research_task, "get_async_redis_client", redis)
    await asyncio.gather(
        *[
            equipment_research_task._append_events(
                run_id, [("batch-event", {"writer": writer, "index": i}) for i in range(120)]
            )
            for writer in range(2)
        ]
    )
    async with manager.get_async_session_context() as db:
        rows = await EquipmentResearchRepository(db).list_events(run_id, limit=300)
    assert [row.sequence for row in rows] == list(range(1, 241))
    assert len(publications) == 240
    for writer in range(2):
        assert [row.payload["index"] for row in rows if row.payload["writer"] == writer] == list(range(120))

    await equipment_research_task._append_events(run_id, [("winning_swarm_started", {})])
    async with manager.get_async_session_context() as db:
        assert (await db.get(EquipmentResearchRun, run_id)).status == "synthesizing"
    await equipment_research_task._append_events(run_id, [("report_model_call_started", {})])
    await equipment_research_task._append_events(run_id, [("run_started", {})])
    async with manager.get_async_session_context() as db:
        assert (await db.get(EquipmentResearchRun, run_id)).status == "reporting"

    # 终态不可再被迟到事件修改。
    async with manager.get_async_session_context() as db:
        run = await db.get(EquipmentResearchRun, run_id)
        run.status = "cancelled"
    await equipment_research_task._append_events(run_id, [("late-event", {})])
    assert len(publications) == 243
