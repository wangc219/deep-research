from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from platform_core.services import scheduled_agent_service as service
from platform_core.services.scheduled_agent_service import next_run_at, validate_schedule


def test_next_run_at_uses_timezone_and_returns_utc_naive_datetime():
    result = next_run_at("0 9 * * *", "Asia/Shanghai", datetime(2026, 8, 26, 0, 0))

    assert result == datetime(2026, 8, 26, 1, 0)
    assert result.tzinfo is None


@pytest.mark.parametrize(
    ("expression", "timezone"),
    [("every day", "Asia/Shanghai"), ("0 9 * * * *", "Asia/Shanghai"), ("0 9 * * *", "Mars/Olympus")],
)
def test_validate_schedule_rejects_invalid_expression_or_timezone(expression, timezone):
    with pytest.raises(HTTPException) as exc_info:
        validate_schedule(expression, timezone)

    assert exc_info.value.status_code == 422


def test_validate_schedule_accepts_five_field_cron_and_iana_timezone():
    assert validate_schedule("*/15 * * * *", "UTC") == ("*/15 * * * *", "UTC")


def test_equipment_research_target_defaults_to_dynamic_swarm_and_latest_query():
    target_type, config, agent_slug, prompt = service._normalize_target_config(
        "equipment_research",
        {
            "target_config": {
                "topic": "复杂电磁环境下低空防护",
                "source_query_id": "query-1",
                "source_query_version": None,
            }
        },
    )

    assert target_type == "equipment_research"
    assert config["execution_profile_id"] == "winning_swarm_dynamic_v2"
    assert config["query_version_policy"] == "latest"
    assert config["source_query_version"] is None
    assert agent_slug == ""
    assert prompt == "复杂电磁环境下低空防护"


def test_equipment_research_target_rejects_invalid_round_count():
    with pytest.raises(HTTPException) as exc_info:
        service._normalize_target_config(
            "equipment_research",
            {"target_config": {"topic": "研究主题", "max_rounds": 0}},
        )

    assert exc_info.value.status_code == 422


def test_validate_schedule_rejects_expression_without_future_occurrence():
    with pytest.raises(HTTPException) as exc_info:
        validate_schedule("0 0 31 2 *", "UTC")

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_validate_project_rejects_project_owned_by_another_user(monkeypatch):
    class ProjectRepository:
        def __init__(self, db):
            del db

        async def lock_active_for_user(self, project_id, uid):
            assert (project_id, uid) == ("project-1", "user-2")
            return None

    monkeypatch.setattr(service, "ProjectRepository", ProjectRepository)

    with pytest.raises(HTTPException) as exc_info:
        await service._validate_project("project-1", SimpleNamespace(uid="user-2"), object())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_validate_agent_rejects_agent_outside_user_visibility(monkeypatch):
    class AgentRepository:
        def __init__(self, db):
            del db

        async def get_visible_by_slug(self, *, slug, user, kind):
            assert (slug, user.uid, kind) == ("private-agent", "user-2", "main")
            return None

    monkeypatch.setattr(service, "AgentRepository", AgentRepository)

    with pytest.raises(HTTPException) as exc_info:
        await service._validate_agent("private-agent", SimpleNamespace(uid="user-2"), object())

    assert exc_info.value.status_code == 404


def test_scheduled_run_model_owns_execution_configuration_snapshot():
    from platform_core.storage.postgres.models_business import ScheduledAgentRun

    assert {"project_id", "agent_slug", "conversation_title", "prompt", "tool_approval_mode", "model_spec"}.issubset(
        ScheduledAgentRun.__table__.c.keys()
    )


def test_scheduled_run_model_uses_unique_thread_per_execution_and_preserves_history():
    from platform_core.storage.postgres.models_business import ScheduledAgentJob, ScheduledAgentRun

    project_fk = next(
        constraint
        for constraint in ScheduledAgentJob.__table__.foreign_key_constraints
        if constraint.name == "fk_scheduled_agent_jobs_project_uid"
    )
    assert project_fk.ondelete == "CASCADE"
    foreign_key = next(iter(ScheduledAgentRun.__table__.c.job_id.foreign_keys))
    assert foreign_key.ondelete == "CASCADE"
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in ScheduledAgentRun.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("thread_id",) in unique_columns


def test_execution_projection_reads_terminal_status_from_agent_run():
    scheduled_run = SimpleNamespace(
        status="submitted",
        to_dict=lambda: {
            "status": "submitted",
            "run_id": None,
            "error_message": None,
            "completed_at": None,
        },
    )
    request = SimpleNamespace(status="dispatched", dispatched_run_id="run-1", error_message=None)
    run = SimpleNamespace(
        status="failed",
        error_message="模型不可用",
        finished_at=datetime(2026, 8, 27, 10, 0),
    )

    result = service._execution_to_dict(scheduled_run, request, run)

    assert result == {
        "status": "failed",
        "run_id": "run-1",
        "error_message": "模型不可用",
        "completed_at": "2026-08-27T10:00:00Z",
        "conversation_available": True,
    }


def test_execution_projection_does_not_offer_conversation_before_request_exists():
    scheduled_run = SimpleNamespace(
        status="failed",
        to_dict=lambda: {"status": "failed", "thread_id": "reserved-thread"},
    )

    result = service._execution_to_dict(scheduled_run, None, None)

    assert result["conversation_available"] is False


@pytest.mark.asyncio
async def test_enabling_paused_job_schedules_from_current_time(monkeypatch):
    now = datetime(2026, 8, 27, 10, 0)
    next_time = datetime(2026, 8, 28, 1, 0)
    job = SimpleNamespace(
        cron_expression="0 9 * * *",
        timezone="Asia/Shanghai",
        enabled=False,
        next_run_at=datetime(2026, 8, 20, 1, 0),
        updated_at=None,
        to_dict=lambda: {"enabled": job.enabled, "next_run_at": job.next_run_at},
    )

    class Repository:
        async def get_job(self, job_id, uid, *, lock):
            assert (job_id, uid, lock) == ("job-1", "user-1", True)
            return job

    class Db:
        async def commit(self):
            return None

    monkeypatch.setattr(service, "ScheduledAgentRepository", lambda _db: Repository())
    monkeypatch.setattr(service, "utc_now_naive", lambda: now)
    monkeypatch.setattr(service, "next_run_at", lambda expression, timezone, after: next_time)

    result = await service.update_scheduled_job(
        job_id="job-1",
        user=SimpleNamespace(uid="user-1"),
        db=Db(),
        data={"enabled": True},
    )

    assert result == {"enabled": True, "next_run_at": next_time}


@pytest.mark.asyncio
async def test_run_now_rejects_request_id_reused_for_another_job(monkeypatch):
    job = SimpleNamespace(id="job-2")
    existing_run = SimpleNamespace(job_id="job-1")

    class Repository:
        async def get_job(self, job_id, uid, *, lock):
            assert (job_id, uid, lock) == ("job-2", "user-1", True)
            return job

        async def get_run(self, run_id):
            assert run_id == service.build_request_id("scheduled-run", "user-1:manual:manual-request-1")
            return existing_run

    monkeypatch.setattr(service, "ScheduledAgentRepository", lambda _db: Repository())

    with pytest.raises(HTTPException) as exc_info:
        await service.run_scheduled_job_now(
            job_id="job-2",
            request_id="manual-request-1",
            user=SimpleNamespace(uid="user-1"),
            db=object(),
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_recovery_continues_after_one_dispatch_fails(monkeypatch):
    records = [SimpleNamespace(id="run-failing"), SimpleNamespace(id="run-success")]
    dispatched = []

    class Repository:
        def __init__(self, db):
            del db

        async def list_dispatching_runs(self, *, before, limit):
            del before
            assert limit == 10
            return records

    @asynccontextmanager
    async def session_context():
        yield object()

    async def dispatch(*, scheduled_run_id):
        dispatched.append(scheduled_run_id)
        if scheduled_run_id == "run-failing":
            raise RuntimeError("持续失败")
        return {"status": "submitted"}

    monkeypatch.setattr(service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(service, "ScheduledAgentRepository", Repository)
    monkeypatch.setattr(service, "dispatch_scheduled_run", dispatch)

    assert await service.recover_scheduled_dispatches(limit=10) == 1
    assert dispatched == ["run-failing", "run-success"]


@pytest.mark.asyncio
async def test_due_job_claiming_continues_after_one_dispatch_fails(monkeypatch):
    runs = iter(
        [
            SimpleNamespace(id="run-failing", status="dispatching"),
            SimpleNamespace(id="run-success", status="dispatching"),
            None,
        ]
    )
    dispatched = []

    @asynccontextmanager
    async def session_context():
        yield object()

    async def claim(*, db, now):
        del db, now
        return next(runs)

    async def dispatch(*, scheduled_run_id):
        dispatched.append(scheduled_run_id)
        if scheduled_run_id == "run-failing":
            raise RuntimeError("持续失败")
        return {"status": "submitted"}

    monkeypatch.setattr(service.pg_manager, "get_async_session_context", session_context)
    monkeypatch.setattr(service, "_claim_due_run", claim)
    monkeypatch.setattr(service, "dispatch_scheduled_run", dispatch)

    assert await service.claim_and_dispatch_due_jobs(limit=3) == 2
    assert dispatched == ["run-failing", "run-success"]


@pytest.mark.asyncio
async def test_equipment_schedule_dispatches_idempotent_research_run(monkeypatch):
    from unittest.mock import ANY, AsyncMock

    from platform_core.services import equipment_research_service
    from platform_core.storage.postgres.models_equipment import EquipmentResearchRun

    create_run = AsyncMock(return_value={"run_id": "run-equipment-1", "status": "draft"})
    start_run = AsyncMock(return_value={"run_id": "run-equipment-1", "status": "queued"})
    monkeypatch.setattr(equipment_research_service, "create_run", create_run)
    monkeypatch.setattr(equipment_research_service, "start_run", start_run)
    equipment_run = SimpleNamespace(
        id="run-equipment-1",
        status="queued",
        error="",
        updated_at=datetime(2026, 8, 27, 10, 0),
    )

    class Db:
        commit = AsyncMock()

        async def get(self, model, run_id):
            assert (model, run_id) == (EquipmentResearchRun, "run-equipment-1")
            return equipment_run

    scheduled_run = SimpleNamespace(
        id="scheduled-run-1",
        project_id="project-1",
        target_config={
            "topic": "复杂电磁环境下低空防护",
            "source_query_id": "query-1",
            "source_query_version": None,
            "research_route": "auto",
            "execution_profile_id": "winning_swarm_dynamic_v2",
        },
        prompt="复杂电磁环境下低空防护",
        model_spec="provider:model",
        trigger="scheduled",
        equipment_run_id=None,
        target_type="equipment_research",
        status="dispatching",
        error_message=None,
        to_dict=lambda: {
            "status": scheduled_run.status,
            "target_type": scheduled_run.target_type,
            "equipment_run_id": scheduled_run.equipment_run_id,
        },
    )
    job = SimpleNamespace(id="job-1", updated_at=None)
    user = SimpleNamespace(uid="owner")

    result = await service._dispatch_equipment_research(
        db=Db(), scheduled_run=scheduled_run, job=job, user=user
    )

    assert result["status"] == "queued"
    assert result["result_available"] is True
    assert result["open_path"] == "/equipment/runs/run-equipment-1"
    create_run.assert_awaited_once()
    assert create_run.await_args.kwargs["idempotency_key"] == "scheduled:scheduled-run-1"
    assert create_run.await_args.kwargs["source_query_id"] == "query-1"
    start_run.assert_awaited_once_with(db=ANY, user=user, run_id="run-equipment-1")


@pytest.mark.asyncio
async def test_claim_disables_invalid_schedule_and_continues_to_next_job(monkeypatch):
    invalid = SimpleNamespace(
        id="job-invalid",
        cron_expression="0 9 * * *",
        timezone="Mars/Olympus",
        next_run_at=datetime(2026, 8, 27, 1, 0),
        enabled=True,
        updated_at=None,
    )
    valid = SimpleNamespace(
        id="job-valid",
        cron_expression="0 9 * * *",
        timezone="UTC",
        next_run_at=datetime(2026, 8, 27, 9, 0),
        enabled=True,
        updated_at=None,
    )
    jobs = iter([invalid, valid])
    commits = 0

    class Repository:
        async def claim_due_job(self, *, now):
            assert now == datetime(2026, 8, 27, 10, 0)
            return next(jobs)

    class Db:
        async def commit(self):
            nonlocal commits
            commits += 1

    run = SimpleNamespace(id="run-valid")

    async def create_run_record(**kwargs):
        assert kwargs["job"] is valid
        return run

    monkeypatch.setattr(service, "ScheduledAgentRepository", lambda _db: Repository())
    monkeypatch.setattr(service, "_create_run_record", create_run_record)

    result = await service._claim_due_run(db=Db(), now=datetime(2026, 8, 27, 10, 0))

    assert result is run
    assert invalid.enabled is False
    assert valid.next_run_at == datetime(2026, 8, 28, 9, 0)
    assert commits == 2
