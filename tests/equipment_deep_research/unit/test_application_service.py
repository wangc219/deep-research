from __future__ import annotations

import pytest
from equipment_deep_research.application.dto import CreateRunCommand, UpdateRunCommand
from equipment_deep_research.application.run_service import InvalidRunTransition, ResearchApplicationService


def test_create_and_start_are_separate_commands() -> None:
    service = ResearchApplicationService()
    created = service.create_run(CreateRunCommand("低空无人机探测预警能力", "new_winning_mechanism", ["international_situation"], 5, "analyst-1"))
    assert created.status == "draft"
    started = service.start_run(created.run_id, actor="analyst-1", idempotency_key="start-1")
    assert started.status == "queued"
    assert service.queue.pending_run_ids() == [created.run_id]


def test_invalid_transition_is_rejected() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("topic", "auto", [], 5, "analyst"))
    with pytest.raises(InvalidRunTransition, match="draft.*queued"):
        service.resume_run(run.run_id, actor="analyst", idempotency_key="resume")


def test_failed_run_can_resume_from_checkpoint_and_clears_error() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("topic", "auto", [], 3, "analyst"))
    service.set_status(run.run_id, "researching")
    service.set_error(run.run_id, "transient serialization failure")
    service.set_status(run.run_id, "failed")

    resumed = service.resume_run(
        run.run_id,
        actor="analyst",
        idempotency_key="resume-failed",
    )

    assert resumed.status == "queued"
    assert resumed.error == ""
    assert service.queue.pending_run_ids() == [run.run_id]


def test_execution_configuration_is_preserved_on_a_run() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
            "topic", "auto", [], 5, "analyst",
            {"mode": "real", "model": "gpt-5.5", "api_key_env": "MODEL_KEY"},
        )
    )
    assert run.execution["mode"] == "real"
    assert service.get_run(run.run_id).execution["api_key_env"] == "MODEL_KEY"


def test_supplemental_information_is_preserved_and_editable_on_draft() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
            "query",
            "auto",
            [],
            2,
            "analyst",
            supplemental_information="初始补充信息",
        )
    )

    updated = service.update_run(
        run.run_id,
        UpdateRunCommand(
            "query",
            "auto",
            [],
            2,
            supplemental_information="精简后的补充方向",
        ),
        actor="analyst",
    )

    assert updated.supplemental_information == "精简后的补充方向"

    preserved = service.update_run(
        run.run_id,
        UpdateRunCommand("query v2", "auto", [], 2),
        actor="analyst",
    )
    assert preserved.supplemental_information == "精简后的补充方向"


def test_draft_can_be_updated_and_terminal_run_can_be_archived() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("topic", "auto", [], 5, "analyst"))
    updated = service.update_run(
        run.run_id,
        UpdateRunCommand(
            "updated topic",
            "traditional_gap",
            ["weapon_equipment"],
            3,
            {"mode": "fake"},
        ),
        actor="analyst",
    )
    assert updated.topic == "updated topic"
    assert updated.research_route == "traditional_gap"
    assert updated.max_rounds == 3
    archived = service.archive_run(run.run_id, actor="analyst")
    assert archived.status == "archived"


def test_started_run_cannot_be_edited_or_archived() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("topic", "auto", [], 5, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start")
    with pytest.raises(InvalidRunTransition):
        service.update_run(
            run.run_id,
            UpdateRunCommand("changed", "auto", [], 5, {"mode": "fake"}),
            actor="analyst",
        )
    with pytest.raises(InvalidRunTransition):
        service.archive_run(run.run_id, actor="analyst")


def test_queued_run_can_be_permanently_deleted_but_active_run_cannot() -> None:
    service = ResearchApplicationService()
    queued = service.create_run(CreateRunCommand("queued", "auto", [], 5, "analyst"))
    service.start_run(queued.run_id, actor="analyst", idempotency_key="start-queued")

    deleted = service.delete_run(queued.run_id)

    assert deleted.status == "queued"
    assert service.queue.pending_run_ids() == []
    with pytest.raises(KeyError):
        service.get_run(queued.run_id)

    active = service.create_run(CreateRunCommand("active", "auto", [], 5, "analyst"))
    service.set_status(active.run_id, "researching")
    with pytest.raises(InvalidRunTransition, match="researching cannot be permanently deleted"):
        service.delete_run(active.run_id)


def test_orphaned_active_run_is_requeued_after_worker_restart() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    service.set_status(run.run_id, "researching")

    recovered = service.recover_orphaned_runs(stale_after_seconds=0)

    assert recovered == [run.run_id]
    assert service.get_run(run.run_id).status == "queued"
    assert service.queue.pending_run_ids() == [run.run_id]


def test_recently_claimed_run_is_not_recovered_by_another_starting_worker() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    service.set_status(run.run_id, "planning")

    recovered = service.recover_orphaned_runs(stale_after_seconds=15)

    assert recovered == []
    assert service.get_run(run.run_id).status == "planning"
    assert service.queue.pending_run_ids() == []


def test_runtime_health_tolerates_invalid_worker_concurrency(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY", "invalid")
    monkeypatch.setenv("EQUIPMENT_DR_WORKER_POOL_CONFIG", str(tmp_path / "worker-pool.json"))

    health = ResearchApplicationService().runtime_health()

    assert health["configured_worker_capacity"] == 1
    assert health["worker_capacity"] == 0
    assert health["available_slots"] == 0


def test_runtime_health_caps_configured_worker_concurrency_at_eight(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY", "99")
    monkeypatch.setenv("EQUIPMENT_DR_WORKER_POOL_CONFIG", str(tmp_path / "worker-pool.json"))

    health = ResearchApplicationService().runtime_health()

    assert health["configured_worker_capacity"] == 8
