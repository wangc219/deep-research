"""动态资源预算的竞争、过期和内存边界验证。"""

import json
import time
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from platform_core.services import resource_budget as policy
from platform_core.services import task_service


def test_idle_asr_borrows_all_cores_and_busy_interaction_has_priority():
    idle = policy.plan_budget(cores=4, available_mib=10000, other_cpu=0.05, interactive=0, research=0)
    busy = policy.plan_budget(cores=4, available_mib=10000, other_cpu=0.85, interactive=12, research=2)
    assert idle["asr_threads"] == 4 and idle["research_slots"] == 8
    assert busy["asr_threads"] == 1 and busy["research_slots"] == 2
    assert idle["subagent_slots"] > busy["subagent_slots"] >= 1


def test_subagent_capacity_scales_with_host_instead_of_plateauing_at_four():
    small = policy.plan_budget(cores=2, available_mib=6000, other_cpu=0.1, interactive=0, research=0)
    large = policy.plan_budget(cores=8, available_mib=30000, other_cpu=0.1, interactive=0, research=0)

    assert small["subagent_slots"] > 4
    assert large["subagent_slots"] > small["subagent_slots"]
    assert policy.adaptive_worker_max_jobs(cores=8, total_mib=30000) > policy.adaptive_worker_max_jobs(
        cores=2, total_mib=6000
    )


def test_critical_memory_holds_new_heavy_tasks():
    budget = policy.plan_budget(cores=4, available_mib=1800, other_cpu=0.05, interactive=0, research=0)
    assert budget["research_slots"] == budget["bulk_slots"] == 0
    assert budget["asr_threads"] == 1 and budget["memory_pressure"]


def test_snapshot_expires_and_rejects_invalid_thread_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("RESOURCE_GOVERNOR_ENABLED", "true")
    path = tmp_path / "budget.json"
    monkeypatch.setenv("RESOURCE_BUDGET_PATH", str(path))
    value = {
        "observed_at": time.time() - 20,
        "asr_threads": 1,
        "research_slots": 0,
        "bulk_slots": 0,
        "subagent_slots": 0,
        "memory_pressure": True,
    }
    path.write_text(json.dumps(value))
    assert policy.read_budget()["stale"]
    value.update(observed_at=time.time(), asr_threads=-1)
    path.write_text(json.dumps(value))
    assert policy.read_budget()["stale"]
    value.update(asr_threads=1)
    path.write_text(json.dumps(value))
    assert policy.read_budget()["research_slots"] == 0


@pytest.mark.asyncio
async def test_admission_respects_budget_and_operator_research_limit(monkeypatch):
    monkeypatch.setattr(policy, "read_budget", lambda: {"research_slots": 2, "bulk_slots": 4, "memory_pressure": False})
    monkeypatch.setattr(
        task_service,
        "system_options",
        SimpleNamespace(get=AsyncMock(return_value={"equipment_research_max_running": 4})),
    )
    assert await task_service.resolve_task_capacity("equipment_research") == 2
    assert await task_service.resolve_task_capacity("knowledge_ingest") <= 4
    monkeypatch.setattr(policy, "read_budget", lambda: {"research_slots": 0, "bulk_slots": 0, "memory_pressure": True})
    assert await task_service.resolve_task_capacity("equipment_research") == 0
    assert await task_service.resolve_task_capacity("wxchannels_transcribe") == 0


@pytest.mark.asyncio
async def test_pressure_deferred_task_stays_pending_without_claim(monkeypatch):
    repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(
                status="pending", type="wxchannels_transcribe", handler_version=1, cancel_requested=False
            )
        ),
        claim=AsyncMock(),
    )
    monkeypatch.setattr(task_service, "TaskRepository", lambda: repo)
    monkeypatch.setattr(task_service, "get_task_definition", lambda *args: object())
    monkeypatch.setattr(task_service, "resolve_task_capacity", AsyncMock(return_value=0))
    await task_service.process_task({}, "pending-video")
    repo.claim.assert_not_called()
