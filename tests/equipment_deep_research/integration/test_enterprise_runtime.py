from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
import json
import os
import signal
import subprocess
from threading import Barrier, Lock
import time

from fastapi.testclient import TestClient

from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import InvalidRunTransition, ResearchApplicationService
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunQueue, SqlRunRepository
from equipment_deep_research.deep_thinking import create_session, save_research_link
from equipment_deep_research.queue.worker import ResearchWorker, WorkerOutcome
from equipment_deep_research.orchestration.runner import DeepResearchRunner
from equipment_deep_research.runtime_process_registry import register_process_group


ROOT = Path(__file__).resolve().parents[3]


def test_run_and_events_survive_repository_restart(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'app.db'}"
    first = SqlRunRepository(create_database_engine(url))
    service = ResearchApplicationService(repository=first)
    run = service.create_run(CreateRunCommand("topic", "auto", [], 5, "analyst"))
    first.append_event(run.run_id, "run_created", {"status": "draft"})
    second = SqlRunRepository(create_database_engine(url))
    assert second.get(run.run_id).status == "draft"
    assert second.events_after(run.run_id, 0)[0]["sequence"] == 1


def test_worker_executes_queued_run() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("topic", "auto", [], 5, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start")
    executed = []
    outcome = ResearchWorker(service=service, execute=executed.append).run_once()
    assert outcome and outcome.status == "completed"
    assert executed == [run.run_id]


def test_worker_does_not_overwrite_user_stop_with_completed_status() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start")

    def execute(run_id: str) -> dict:
        service.cancel_run(run_id, actor="analyst", idempotency_key="stop")
        return {}

    outcome = ResearchWorker(service=service, execute=execute).run_once()

    assert outcome == WorkerOutcome(run.run_id, "cancelled")
    assert service.get_run(run.run_id).status == "cancelled"


def test_failed_worker_run_is_persisted_and_removed_from_pending_queue(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'failed.db'}")
    service = ResearchApplicationService(repository=SqlRunRepository(engine), queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 5, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start")

    def fail(_: str) -> dict:
        raise RuntimeError("provider unavailable")

    outcome = ResearchWorker(service=service, execute=fail).run_once()
    assert outcome and outcome.status == "failed"
    assert service.get_run(run.run_id).error == "provider unavailable"
    assert service.queue.pending_run_ids() == []


def test_worker_releases_registered_process_groups_before_completed_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "EQUIPMENT_DR_PROCESS_REGISTRY_ROOT",
        str(tmp_path / "process-registry"),
    )
    engine = create_database_engine(f"sqlite:///{tmp_path / 'cleanup.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start")
    children: list[subprocess.Popen] = []

    def execute(_: str) -> dict:
        child = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
        children.append(child)
        register_process_group(child.pid, command_hint="sleep")
        return {}

    try:
        outcome = ResearchWorker(service=service, execute=execute).run_once()

        assert outcome == WorkerOutcome(run.run_id, "completed")
        children[0].wait(timeout=3)
        events = repository.events_after(run.run_id, 0)
        cleanup_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "run_orphan_process_cleanup"
        )
        completed_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "run_status_changed"
            and event["payload"].get("status") == "completed"
        )
        assert cleanup_index < completed_index
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=3)


def test_worker_releases_registered_process_groups_before_failed_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "EQUIPMENT_DR_PROCESS_REGISTRY_ROOT",
        str(tmp_path / "process-registry"),
    )
    engine = create_database_engine(f"sqlite:///{tmp_path / 'cleanup-failed.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start")
    children: list[subprocess.Popen] = []

    def execute(_: str) -> dict:
        child = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
        children.append(child)
        register_process_group(child.pid, command_hint="sleep")
        raise RuntimeError("research task failed")

    try:
        outcome = ResearchWorker(service=service, execute=execute).run_once()

        assert outcome == WorkerOutcome(
            run.run_id,
            "failed",
            "research task failed",
        )
        children[0].wait(timeout=3)
        events = repository.events_after(run.run_id, 0)
        cleanup_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "run_orphan_process_cleanup"
        )
        failed_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "run_status_changed"
            and event["payload"].get("status") == "failed"
        )
        assert cleanup_index < failed_index
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=3)


def test_worker_automatically_resumes_one_transient_failure_from_checkpoint(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'transient-resume.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(CreateRunCommand("topic", "auto", [], 5, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start")
    calls = 0

    def transient_then_complete(_: str) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("upstream stream disconnected before completion")
        return {}

    worker = ResearchWorker(service=service, execute=transient_then_complete)

    first = worker.run_once()

    assert first == WorkerOutcome(
        run.run_id,
        "failed",
        "upstream stream disconnected before completion",
    )
    assert service.get_run(run.run_id).status == "failed"
    assert "upstream stream disconnected" in service.get_run(run.run_id).error
    assert service.queue.pending_run_ids() == []
    retry_events = [
        event
        for event in repository.events_after(run.run_id, 0)
        if event["event_type"] == "run_manual_resume_required"
    ]
    assert len(retry_events) == 1
    assert calls == 1


def test_worker_transient_resume_is_bounded(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'bounded-resume.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(CreateRunCommand("topic", "auto", [], 5, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start")

    def fail(_: str) -> dict:
        raise RuntimeError("upstream stream disconnected before completion")

    worker = ResearchWorker(service=service, execute=fail)

    first = worker.run_once()

    assert first == WorkerOutcome(
        run.run_id,
        "failed",
        "upstream stream disconnected before completion",
    )
    assert service.get_run(run.run_id).status == "failed"
    assert service.queue.pending_run_ids() == []
    retry_events = [
        event
        for event in repository.events_after(run.run_id, 0)
        if event["event_type"] == "run_manual_resume_required"
    ]
    assert len(retry_events) == 1


def test_worker_persists_exception_type_when_message_is_empty() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start")

    def fail(_: str) -> dict:
        raise TimeoutError()

    outcome = ResearchWorker(service=service, execute=fail).run_once()

    assert outcome == WorkerOutcome(run.run_id, "failed", "TimeoutError")
    assert service.get_run(run.run_id).error == "TimeoutError"


def test_worker_heartbeat_continues_after_transient_persistence_error() -> None:
    class HeartbeatService:
        def __init__(self) -> None:
            self.calls = 0

        def touch_worker(self, worker_id: str, *, status: str, current_run_id: str = "") -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("database is locked")

    service = HeartbeatService()
    worker = ResearchWorker(
        service=service,
        execute=lambda _: {},
        heartbeat_interval_seconds=0.01,
    )

    with worker._heartbeat_during("run-1"):
        time.sleep(0.05)

    assert service.calls >= 2


def test_worker_acks_duplicate_queue_item_for_completed_run_without_reexecution(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'completed-duplicate.db'}")
    service = ResearchApplicationService(repository=SqlRunRepository(engine), queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    report_path = tmp_path / "report.md"
    report_path.write_text("# complete", encoding="utf-8")
    service.set_result(
        run.run_id,
        {
            "status": "completed",
            "audit_status": "approved",
            "report_path": str(report_path),
        },
    )
    service.set_status(run.run_id, "completed")
    service.queue.enqueue(run.run_id)
    executed: list[str] = []

    outcome = ResearchWorker(service=service, execute=executed.append).run_once()

    assert outcome == WorkerOutcome(run.run_id, "completed")
    assert executed == []
    assert service.queue.pending_run_ids() == []


def test_worker_reconciles_failed_status_when_completed_delivery_exists(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'late-error.db'}")
    service = ResearchApplicationService(repository=SqlRunRepository(engine), queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    report_path = tmp_path / "report.md"
    report_path.write_text("# complete", encoding="utf-8")
    service.set_result(
        run.run_id,
        {
            "status": "completed",
            "audit_status": "approved",
            "report_path": str(report_path),
        },
    )
    service.set_status(run.run_id, "failed")
    service.queue.enqueue(run.run_id)

    executed: list[str] = []

    outcome = ResearchWorker(service=service, execute=executed.append).run_once()

    assert outcome == WorkerOutcome(run.run_id, "completed")
    assert executed == []
    assert service.get_run(run.run_id).status == "completed"
    assert service.get_run(run.run_id).error == ""


def test_worker_keeps_deep_child_job_recoverable_until_version_publish(tmp_path: Path) -> None:
    """Child completion must not hide a pending capability-version write.

    The child run worker and the API deep-job monitor are independent
    processes.  The worker therefore records only a validation hand-off;
    the monitor owns the terminal publish transition after the SQLite
    capability version has been committed.
    """

    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-child-handoff.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    parent = service.create_run(CreateRunCommand("parent", "auto", [], 2, "analyst"))
    child = service.create_run(
        CreateRunCommand(
            "child",
            "auto",
            [],
            2,
            "deep-thinking-agent",
            execution={"parent_run_id": parent.run_id, "deep_job_id": "job-handoff"},
        )
    )
    repository.create_or_get_deep_job(
        job_id="job-handoff",
        parent_run_id=parent.run_id,
        session_id="session-handoff",
        child_run_id=child.run_id,
        idempotency_key="handoff-request",
        fingerprint="handoff-fingerprint",
    )

    worker = ResearchWorker(service=service, execute=lambda _: {})
    worker._reconcile_deep_child_completion(child.run_id, {"status": "completed"})

    job = repository.get_deep_job("job-handoff")
    assert job is not None
    assert job["stage"] == "validation"
    assert job["status"] == "running"
    events = repository.events_after(parent.run_id, 0)
    handoff = [event for event in events if event["event_type"] == "deep_child_completed"]
    assert handoff
    assert handoff[-1]["payload"]["status"] == "running"
    assert handoff[-1]["payload"]["stage"] == "validation"


def test_worker_does_not_resurrect_terminal_deep_child_job(tmp_path: Path) -> None:
    """A late child completion cannot overwrite cancellation/publication."""

    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-child-terminal.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    parent = service.create_run(CreateRunCommand("parent", "auto", [], 2, "analyst"))
    child = service.create_run(
        CreateRunCommand(
            "child",
            "auto",
            [],
            2,
            "deep-thinking-agent",
            execution={"parent_run_id": parent.run_id, "deep_job_id": "job-terminal"},
        )
    )
    repository.create_or_get_deep_job(
        job_id="job-terminal",
        parent_run_id=parent.run_id,
        session_id="session-terminal",
        child_run_id=child.run_id,
        idempotency_key="terminal-request",
        fingerprint="terminal-fingerprint",
    )
    repository.update_deep_job("job-terminal", stage="publish", status="cancelled")

    worker = ResearchWorker(service=service, execute=lambda _: {})
    worker._reconcile_deep_child_completion(child.run_id, {"status": "completed"})

    job = repository.get_deep_job("job-terminal")
    assert job is not None
    assert job["stage"] == "publish"
    assert job["status"] == "cancelled"
    assert not [
        event
        for event in repository.events_after(parent.run_id, 0)
        if event["event_type"] == "deep_child_completed"
    ]


def test_terminal_deep_job_rejects_same_status_stale_checkpoint(tmp_path: Path) -> None:
    repository = SqlRunRepository(
        create_database_engine(f"sqlite:///{tmp_path / 'deep-terminal-checkpoint.db'}")
    )
    repository.create_or_get_deep_job(
        job_id="job-terminal-checkpoint",
        parent_run_id="run-terminal-checkpoint",
        session_id="session-terminal-checkpoint",
    )
    final_checkpoint = {"phase": "final_response", "tool_call_count": 1}
    final = repository.update_deep_job(
        "job-terminal-checkpoint",
        stage="publish",
        status="completed",
        checkpoint=final_checkpoint,
    )
    assert final is not None
    final_version = final["state_version"]

    stale = repository.update_deep_job(
        "job-terminal-checkpoint",
        stage="s4_mapping",
        status="completed",
        checkpoint={"phase": "tools_completed", "tool_call_count": 1},
    )

    assert stale is not None
    assert stale["stage"] == "publish"
    assert stale["status"] == "completed"
    assert stale["checkpoint"] == final_checkpoint
    assert stale["state_version"] == final_version


@pytest.mark.parametrize("terminal_status", ["partial", "failed", "blocked"])
def test_validation_terminal_deep_job_rejects_late_running_checkpoint(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    repository = SqlRunRepository(
        create_database_engine(
            f"sqlite:///{tmp_path / f'deep-validation-{terminal_status}.db'}"
        )
    )
    job_id = f"job-validation-{terminal_status}"
    repository.create_or_get_deep_job(
        job_id=job_id,
        parent_run_id="run-validation-terminal",
        session_id="session-validation-terminal",
    )
    final_checkpoint = {"phase": "final_response", "status": terminal_status}
    final = repository.update_deep_job(
        job_id,
        stage="validation",
        status=terminal_status,
        checkpoint=final_checkpoint,
    )
    assert final is not None
    final_version = final["state_version"]

    stale = repository.update_deep_job(
        job_id,
        stage="s4_mapping",
        status="running",
        checkpoint={"phase": "tools_completed", "status": "running"},
    )

    assert stale is not None
    assert stale["stage"] == "validation"
    assert stale["status"] == terminal_status
    assert stale["checkpoint"] == final_checkpoint
    assert stale["state_version"] == final_version


def test_nonterminal_authoring_partial_can_advance_to_validation(tmp_path: Path) -> None:
    repository = SqlRunRepository(
        create_database_engine(f"sqlite:///{tmp_path / 'deep-authoring-partial.db'}")
    )
    repository.create_or_get_deep_job(
        job_id="job-authoring-partial",
        parent_run_id="run-authoring-partial",
        session_id="session-authoring-partial",
    )
    partial = repository.update_deep_job(
        "job-authoring-partial",
        stage="s6_authoring",
        status="partial",
        checkpoint={"phase": "tools_completed"},
    )
    assert partial is not None

    advanced = repository.update_deep_job(
        "job-authoring-partial",
        stage="validation",
        status="running",
        checkpoint={"phase": "awaiting_validation"},
    )

    assert advanced is not None
    assert advanced["stage"] == "validation"
    assert advanced["status"] == "running"
    assert advanced["checkpoint"] == {"phase": "awaiting_validation"}
    assert advanced["state_version"] == partial["state_version"] + 1


def test_worker_survives_queued_run_deleted_after_claim() -> None:
    class ClaimedQueue:
        def __init__(self) -> None:
            self.acked: list[str] = []

        def claim(self) -> str:
            return "run-deleted"

        def ack(self, run_id: str) -> None:
            self.acked.append(run_id)

    class DeletedRunService:
        def __init__(self) -> None:
            self.queue = ClaimedQueue()
            self.worker_states: list[tuple[str, str]] = []

        def touch_worker(self, worker_id: str, *, status: str, current_run_id: str = "") -> None:
            self.worker_states.append((status, current_run_id))

        def set_status(self, run_id: str, status: str) -> None:
            raise KeyError(run_id)

    service = DeletedRunService()
    outcome = ResearchWorker(service=service, execute=lambda _: {}).run_once()

    assert outcome == WorkerOutcome("run-deleted", "deleted")
    assert service.queue.acked == ["run-deleted"]
    assert service.worker_states[-1] == ("idle", "")


def test_sql_queue_is_shared_across_service_instances(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'shared.db'}")
    first = ResearchApplicationService(repository=SqlRunRepository(engine), queue=SqlRunQueue(engine))
    run = first.create_run(CreateRunCommand("topic", "auto", [], 5, "analyst"))
    first.start_run(run.run_id, actor="analyst", idempotency_key="start")
    second = ResearchApplicationService(repository=SqlRunRepository(engine), queue=SqlRunQueue(engine))
    assert second.queue.claim() == run.run_id


def test_sql_queue_requeues_an_acked_run_for_checkpoint_resume(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'resume-queue.db'}")
    queue = SqlRunQueue(engine)
    queue.enqueue("run-1")
    assert queue.claim() == "run-1"
    queue.ack("run-1")

    queue.enqueue("run-1")

    assert queue.pending_run_ids() == ["run-1"]
    assert queue.claim() == "run-1"


def test_resume_does_not_enqueue_when_online_worker_owns_run(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'resume-live.db'}")
    service = ResearchApplicationService(
        repository=SqlRunRepository(engine), queue=SqlRunQueue(engine)
    )
    run = service.create_run(CreateRunCommand("topic", "auto", [], 3, "analyst"))
    service.set_status(run.run_id, "failed")
    service.touch_worker("research-worker-1", status="working", current_run_id=run.run_id)

    with pytest.raises(InvalidRunTransition, match="already executing"):
        service.resume_run(run.run_id, actor="analyst", idempotency_key="resume-live")


def test_sql_queue_does_not_requeue_a_live_claimed_run(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'claimed-resume.db'}")
    queue = SqlRunQueue(engine)
    queue.enqueue("run-live")
    assert queue.claim() == "run-live"

    # A duplicate Resume request must not create a second execution lease.
    queue.enqueue("run-live")
    assert queue.pending_run_ids() == []
    assert queue.claim() is None

    # Once the service has established that the original owner is gone, it
    # may explicitly reopen the stale claim for checkpoint recovery.
    queue.enqueue("run-live", allow_claimed=True)
    assert queue.pending_run_ids() == ["run-live"]


def test_sql_queue_claim_is_atomic_across_worker_connections(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'parallel-claim.db'}"
    first = SqlRunQueue(create_database_engine(url))
    second = SqlRunQueue(create_database_engine(url))
    first.enqueue("run-1")
    first.enqueue("run-2")
    ready = Barrier(2)

    def claim(queue: SqlRunQueue) -> str | None:
        ready.wait(timeout=5)
        return queue.claim()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(claim, (first, second)))

    assert set(claimed) == {"run-1", "run-2"}
    assert len(claimed) == len(set(claimed))
    assert first.pending_run_ids() == []


def test_sql_queue_build_generation_fences_old_workers(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'generation-fence.db'}"
    new_queue = SqlRunQueue(create_database_engine(url), generation="new-build")
    old_queue = SqlRunQueue(create_database_engine(url), generation="old-build")

    new_queue.enqueue("run-new")

    assert old_queue.claim(generation="old-build") is None
    assert old_queue.pending_run_ids() == []
    assert new_queue.pending_run_ids() == ["run-new"]
    assert new_queue.claim(generation="new-build") == "run-new"


def test_same_topic_runs_enqueue_concurrently_without_blocking(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'duplicate-topic-enqueue.db'}"
    services = [
        ResearchApplicationService(
            repository=SqlRunRepository(create_database_engine(url)),
            queue=SqlRunQueue(create_database_engine(url)),
        )
        for _ in range(2)
    ]
    runs = [
        service.create_run(
            CreateRunCommand(
                "强电磁压制下精确打击任务续接装备研究",
                "auto",
                [],
                2,
                "analyst",
            )
        )
        for service in services
    ]
    ready = Barrier(2)

    def start(index: int) -> str:
        ready.wait(timeout=5)
        return services[index].start_run(
            runs[index].run_id,
            actor="analyst",
            idempotency_key=f"start-{index}",
        ).run_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        started = list(pool.map(start, (0, 1)))

    pending = SqlRunQueue(create_database_engine(url)).pending_run_ids()
    assert set(started) == {run.run_id for run in runs}
    assert set(pending) == {run.run_id for run in runs}
    assert len(pending) == 2


def test_two_workers_execute_distinct_runs_concurrently(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'parallel-workers.db'}"
    api_service = ResearchApplicationService(
        repository=SqlRunRepository(create_database_engine(url)),
        queue=SqlRunQueue(create_database_engine(url)),
    )
    runs = [
        api_service.create_run(
            CreateRunCommand(
                "强电磁压制下精确打击任务续接装备研究",
                "auto",
                [],
                2,
                "analyst",
            )
        )
        for _ in (1, 2)
    ]
    assert runs[0].topic == runs[1].topic
    assert runs[0].run_id != runs[1].run_id
    for index, run in enumerate(runs, start=1):
        api_service.start_run(run.run_id, actor="analyst", idempotency_key=f"start-{index}")

    overlap = Barrier(2)
    entered: list[str] = []
    entered_lock = Lock()

    def execute(run_id: str) -> dict:
        with entered_lock:
            entered.append(run_id)
        overlap.wait(timeout=5)
        return {"worker_completed": run_id}

    workers = [
        ResearchWorker(
            service=ResearchApplicationService(
                repository=SqlRunRepository(create_database_engine(url)),
                queue=SqlRunQueue(create_database_engine(url)),
            ),
            execute=execute,
            worker_id=f"research-worker-{index}",
        )
        for index in (1, 2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda worker: worker.run_once(), workers))

    assert set(entered) == {run.run_id for run in runs}
    assert {outcome.run_id for outcome in outcomes if outcome} == {run.run_id for run in runs}
    assert {outcome.status for outcome in outcomes if outcome} == {"completed"}
    assert {api_service.get_run(run.run_id).status for run in runs} == {"completed"}


def test_runtime_health_reports_parallel_slots_and_active_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("EQUIPMENT_DR_WORKER_POOL_CONFIG", str(tmp_path / "worker-pool.json"))
    engine = create_database_engine(f"sqlite:///{tmp_path / 'runtime-health.db'}")
    service = ResearchApplicationService(
        repository=SqlRunRepository(engine),
        queue=SqlRunQueue(engine),
    )
    service.touch_worker("research-worker-1", status="working", current_run_id="run-1")
    service.touch_worker("research-worker-2", status="idle")

    health = service.runtime_health()

    assert health["configured_worker_capacity"] == 2
    assert health["worker_capacity"] == 2
    assert health["online_worker_count"] == 2
    assert health["active_count"] == 1
    assert health["idle_count"] == 1
    assert health["available_slots"] == 1
    assert health["parallel_enabled"] is True
    assert health["active_run_ids"] == ["run-1"]
    assert health["utilization_percent"] == 50.0
    assert [worker["slot_index"] for worker in health["workers"] if worker["online"]] == [1, 2]


def test_runtime_health_excludes_internal_s6_from_research_capacity(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("EQUIPMENT_DR_WORKER_POOL_CONFIG", str(tmp_path / "worker-pool.json"))
    engine = create_database_engine(f"sqlite:///{tmp_path / 'runtime-health-internal.db'}")
    service = ResearchApplicationService(
        repository=SqlRunRepository(engine),
        queue=SqlRunQueue(engine),
    )
    service.touch_worker("research-worker-1", status="internal", current_run_id="run-s6")
    service.touch_worker("research-worker-2", status="working", current_run_id="run-active")
    service.touch_worker("research-worker-3", status="idle")

    health = service.runtime_health()

    assert health["worker_capacity"] == 2
    assert health["active_count"] == 1
    assert health["internal_count"] == 1
    assert health["available_slots"] == 1
    assert health["active_run_ids"] == ["run-active", "run-s6"]
    assert [
        worker.get("slot_index")
        for worker in health["workers"]
        if worker["online"] and worker.get("status") != "internal"
    ] == [1, 2]
    assert all(
        "slot_index" not in worker
        for worker in health["workers"]
        if worker["online"] and worker.get("status") == "internal"
    )


def test_sse_replay_and_rbac(tmp_path: Path) -> None:
    repository = SqlRunRepository(create_database_engine(f"sqlite:///{tmp_path / 'api.db'}"))
    repository.append_event("run-1", "stage_completed", {"layer": "L1"})
    client = TestClient(create_app(event_repository=repository))
    denied = client.post("/api/v1/runs", headers={"X-Role": "reviewer"}, json={"topic": "x"})
    assert denied.status_code == 403
    replay = client.get("/api/v1/runs/run-1/events", headers={"Last-Event-ID": "0"})
    assert "event: stage_completed" in replay.text


def test_deep_sse_contract_redacts_legacy_delta_and_clamps_progress(tmp_path: Path, monkeypatch) -> None:
    """Deep SSE must expose only the fixed public event shape."""

    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))
    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-sse.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(repository=repository, queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    repository.create_deep_session(
        session_id="session-sse",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    repository.append_deep_event(
        stream_id=f"deep-session:{run.run_id}:session-sse",
        parent_run_id=run.run_id,
        session_id="session-sse",
        event_type="deep_stage",
        stage="s3_divergence",
        status="running",
        progress=150,
        delta={
            "kind": "answer",
            "text": "visible",
            "provider_metadata": {"raw_session": "must-not-escape"},
            "unexpected": "must-not-escape",
        },
    )
    # End the bounded stream after replaying the event rather than waiting for
    # its idle timeout.
    repository.update_deep_session("session-sse", status="failed")
    client = TestClient(create_app(service, event_repository=repository))

    response = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-sse/events",
        headers={"Last-Event-ID": "0"},
    )

    assert response.status_code == 200
    payload = response.text
    assert '"progress": 1.0' in payload
    assert '"delta": {"kind": "answer", "text": "visible"}' in payload
    assert "provider_metadata" not in payload
    assert "unexpected" not in payload
    assert "id: 1" in payload


def test_deep_session_reads_fail_closed_when_durable_ledger_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    """Modern SQL session reads must not degrade to an empty/404 projection."""

    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-read-outage.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(repository=repository, queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    repository.create_deep_session(
        session_id="session-outage",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    monkeypatch.setattr(
        repository,
        "get_deep_session",
        lambda _session_id: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-outage"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "deep session ledger unavailable"


def test_deep_session_list_fails_closed_when_durable_listing_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-list-outage.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(repository=repository, queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    monkeypatch.setattr(
        repository,
        "list_deep_sessions",
        lambda _run_id: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.get(f"/api/v1/runs/{run.run_id}/deep-thinking/sessions")

    assert response.status_code == 503
    assert response.json()["detail"] == "deep session ledger unavailable"


def test_reference_research_list_fails_closed_when_durable_job_listing_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-reference-outage.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(repository=repository, queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    monkeypatch.setattr(
        repository,
        "list_deep_jobs",
        lambda _run_id: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "deep job ledger unavailable"


def test_deep_job_cancel_returns_503_when_durable_update_fails(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-cancel-outage.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(repository=repository, queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    repository.create_or_get_deep_job(
        job_id="cancel-outage",
        parent_run_id=run.run_id,
        session_id="session-cancel-outage",
        idempotency_key="cancel-request",
        fingerprint="cancel-fingerprint",
    )
    monkeypatch.setattr(
        repository,
        "update_deep_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/cancel-outage/cancel",
        headers={"Idempotency-Key": "cancel-api-request"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "deep job ledger unavailable"


def test_deep_sse_replay_sanitizes_legacy_event_name_refs_and_opaque_cursor(
    tmp_path: Path, monkeypatch
) -> None:
    """Legacy ledger rows cannot inject SSE frames or provider metadata."""

    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))
    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-sse-legacy.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(repository=repository, queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    repository.create_deep_session(
        session_id="session-legacy-sse",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    first = repository.append_deep_event(
        stream_id=f"deep-session:{run.run_id}:session-legacy-sse",
        parent_run_id=run.run_id,
        session_id="session-legacy-sse",
        event_type="deep_stage\ninjected",
        stage="not-a-stage",
        status="not-a-status",
        progress=float("nan"),
        delta={
            "kind": "not-a-kind",
            "text": "visible",
            "provider_metadata": {"raw_session": "must-not-escape"},
        },
        evidence_refs=[{"provider_metadata": "must-not-escape"}, "ev-1"],
    )
    repository.append_deep_event(
        stream_id=f"deep-session:{run.run_id}:session-legacy-sse",
        parent_run_id=run.run_id,
        session_id="session-legacy-sse",
        event_type="deep_stage",
        stage="publish",
        status="completed",
        progress=1.0,
        delta={"kind": "summary", "text": "done"},
    )
    repository.update_deep_session("session-legacy-sse", status="failed")
    client = TestClient(create_app(service, event_repository=repository))

    response = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-legacy-sse/events",
        headers={"Last-Event-ID": "0"},
    )
    assert response.status_code == 200
    payload = response.text
    assert "event: deep_stage_injected" in payload
    assert "event: deep_stage\ninjected" not in payload
    assert '"progress": 0.0' in payload
    assert '"stage": "context"' in payload
    assert '"status": "partial"' in payload
    assert '"evidence_refs": ["ev-1"]' in payload
    assert "provider_metadata" not in payload
    assert "must-not-escape" not in payload

    # Older clients persisted the opaque event_id rather than the numeric
    # sequence.  Replaying from that cursor must return only the suffix.
    suffix = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-legacy-sse/events",
        headers={"Last-Event-ID": first["event_id"]},
    )
    assert suffix.status_code == 200
    assert "done" in suffix.text
    assert "visible" not in suffix.text


def test_generic_runtime_history_and_sse_project_deep_events(tmp_path: Path) -> None:
    """The legacy run stream must use the same deep-event redaction contract."""

    engine = create_database_engine(f"sqlite:///{tmp_path / 'runtime-deep.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(repository=repository, queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    service.set_error(run.run_id, "stopped")
    service.set_status(run.run_id, "failed")
    repository.append_event(
        run.run_id,
        "deep_stage\ninjected",
        {
            "schema_version": "deep-events-v1",
            "event_type": "deep_stage\ninjected",
            "stage": "retrieval",
            "status": "running",
            "progress": float("inf"),
            "delta": {
                "kind": "answer",
                "text": "visible",
                "provider_metadata": {"raw_session": "must-not-escape"},
            },
            "evidence_refs": [{"raw_session": "must-not-escape"}, "ev-2"],
        },
    )
    client = TestClient(create_app(service, event_repository=repository))

    history = client.get(f"/api/v1/runs/{run.run_id}/history").json()
    deep_history = history[-1]
    assert deep_history["event_type"] == "deep_stage_injected"
    assert deep_history["payload"]["progress"] == 0.0
    assert deep_history["payload"]["evidence_refs"] == ["ev-2"]
    assert "provider_metadata" not in json.dumps(deep_history, ensure_ascii=False)
    assert "must-not-escape" not in json.dumps(deep_history, ensure_ascii=False)

    replay = client.get(f"/api/v1/runs/{run.run_id}/events")
    assert replay.status_code == 200
    assert "event: deep_stage_injected" in replay.text
    assert "event: deep_stage\ninjected" not in replay.text
    assert "provider_metadata" not in replay.text
    assert "must-not-escape" not in replay.text


def test_deep_job_polling_does_not_expose_internal_payload_or_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))
    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-job-public.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(repository=repository, queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    repository.create_or_get_deep_job(
        job_id="job-public",
        parent_run_id=run.run_id,
        session_id="session-public",
        idempotency_key="request-public",
        fingerprint="fingerprint-public",
        payload={
            "query": "server query",
            "active_skill_ids": [
                "skill-0",
                "skill-1",
                "skill-2",
                "skill-3",
                "skill-4",
                "x" * 200,
                "skill-ignored",
            ],
            "candidate": {
                "name": "参考方向",
                "mechanism_chain": "visible mechanism",
                "api_key": "do-not-return",
            },
            "provider_metadata": {"raw_session": "do-not-return"},
        },
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.get(f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/job-public")

    assert response.status_code == 200
    payload = response.json()["job"]
    assert payload["candidate"]["name"] == "参考方向"
    assert payload["candidate"]["mechanism_chain"] == "visible mechanism"
    assert payload["payload"]["active_skill_ids"] == [
        "skill-0",
        "skill-1",
        "skill-2",
        "skill-3",
        "skill-4",
        "x" * 140,
    ]
    assert set(payload["payload"]) == {"active_skill_ids", "candidate"}
    assert "api_key" not in json.dumps(payload, ensure_ascii=False)
    assert "provider_metadata" not in json.dumps(payload, ensure_ascii=False)
    assert "idempotency_key" not in payload
    assert "fingerprint" not in payload


def test_durable_deep_job_miss_does_not_resurrect_legacy_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    """A configured SQLite ledger is authoritative for job polling."""

    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))
    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-authority.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository, queue=SqlRunQueue(engine)
    )
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    save_research_link(
        tmp_path / "runs",
        {
            "job_id": "stale-job",
            "parent_run_id": run.run_id,
            "child_run_id": "stale-child",
            "capability_name": "过期 sidecar 方向",
        },
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/stale-job"
    )

    assert response.status_code == 404


def test_durable_session_miss_does_not_resurrect_legacy_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    """A missing SQL session must not be recovered from JSON."""

    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))
    engine = create_database_engine(f"sqlite:///{tmp_path / 'session-authority.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository, queue=SqlRunQueue(engine)
    )
    run = service.create_run(CreateRunCommand("topic", "auto", [], 2, "analyst"))
    sidecar = create_session(
        tmp_path / "runs",
        run_id=run.run_id,
        kind="deep-thinking",
        title="stale session",
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{sidecar['session_id']}"
    )

    assert response.status_code == 404


def test_runtime_event_sequence_is_safe_across_repository_instances(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'event-sequence.db'}"
    repositories = [
        SqlRunRepository(create_database_engine(database_url)) for _ in range(4)
    ]

    def append(index: int) -> int:
        return repositories[index % len(repositories)].append_event(
            "run-shared",
            "worker_event",
            {"index": index},
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        sequences = list(pool.map(append, range(24)))

    assert sorted(sequences) == list(range(1, 25))
    events = repositories[0].events_after("run-shared", 0)
    assert [item["sequence"] for item in events] == list(range(1, 25))


def test_api_queue_worker_outputs_survive_process_boundaries(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'enterprise.db'}"
    api_service = ResearchApplicationService(
        repository=SqlRunRepository(create_database_engine(url)),
        queue=SqlRunQueue(create_database_engine(url)),
    )
    client = TestClient(create_app(api_service))
    created = client.post(
        "/api/v1/runs",
        json={"topic": "低空无人机探测预警能力缺口", "research_route": "traditional_gap", "selected_agent_ids": ["combat_scenario", "weapon_equipment"], "max_rounds": 2},
    ).json()
    client.post(f"/api/v1/runs/{created['run_id']}/start", headers={"Idempotency-Key": "start-e2e"})

    worker_service = ResearchApplicationService(
        repository=SqlRunRepository(create_database_engine(url)),
        queue=SqlRunQueue(create_database_engine(url)),
    )
    runner = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=ROOT / "configs/equipment_deep_research/agents.yaml",
        preset_config_path=ROOT / "configs/equipment_deep_research/presets.yaml",
        event_sink=lambda event_type, payload: worker_service.publish_runtime_event(
            created["run_id"], event_type, payload
        ),
    )

    def execute(run_id: str) -> dict:
        view = worker_service.get_run(run_id)
        return runner.run(mode="fake", topic=view.topic, research_route=view.research_route, run_id=run_id, agent_ids=view.selected_agent_ids, max_rounds=view.max_rounds)

    outcome = ResearchWorker(service=worker_service, execute=execute).run_once()
    assert outcome and outcome.status == "completed"
    live_events = worker_service.repository.events_after(created["run_id"], 0)
    assert {item["event_type"] for item in live_events} >= {
        "agent_task_delegated",
        "tool_call",
        "tool_result",
        "winning_reasoning_step_completed",
    }
    assert all("raw_message" not in json.dumps(item, ensure_ascii=False) for item in live_events)

    live_api_run = client.get(f"/api/v1/runs/{created['run_id']}").json()
    assert live_api_run["status"] == "completed"
    assert live_api_run["result"]["manifest_file_count"] >= 5
    runtime_health = client.get("/api/v1/runtime-health").json()
    assert runtime_health["worker_online"] is True
    assert runtime_health["pending_count"] == 0
    assert runtime_health["worker_capacity"] == 1
    assert runtime_health["active_count"] == 0
    assert runtime_health["available_slots"] == 1
    assert runtime_health["active_run_ids"] == []
    assert client.get(
        f"/api/v1/runs/{created['run_id']}/capabilities"
    ).json() == []
    winning = client.get(
        f"/api/v1/runs/{created['run_id']}/winning-mechanism"
    ).json()
    assert len(winning["inputs"]) == 1
    assert len(winning["resources"]) == 1
    assert len(winning["reasoning_nodes"]) == 6
    assert len(winning["stages"]) == 3
    assert len(winning["workflow"]["step_plan"]) == 6
    assert all(
        "backtrack_count" in item
        for item in winning["workflow"]["step_plan"]
    )
    interactions = client.get(f"/api/v1/runs/{created['run_id']}/interactions").json()
    assert interactions["counts"]["tool_calls"] >= 4
    assert {event["event_type"] for event in interactions["events"]} >= {
        "agent_task_delegated",
        "task_received",
        "tool_call",
        "tool_result",
        "savepoint",
        "winning_reasoning_step_completed",
    }
    assert {event["actor"] for event in interactions["events"]} >= {
        "orchestrator",
        "winning_mechanism",
        "auditor",
        "reporter",
    }
    called_tools = {
        event["details"].get("tool_name")
        for event in interactions["events"]
        if event["event_type"] == "tool_call"
    }
    assert {"write_stage_output", "write_audit", "write_report"} <= called_tools
    assert "create_capability_image" not in called_tools
    assert "raw_message" not in json.dumps(interactions, ensure_ascii=False)
    packet = client.get(
        f"/api/v1/runs/{created['run_id']}/domain/BaselineFindingPacket"
    ).json()[0]
    assert packet["analysis_sections"]

    restarted = TestClient(create_app(ResearchApplicationService(repository=SqlRunRepository(create_database_engine(url)), queue=SqlRunQueue(create_database_engine(url)))))
    run = restarted.get(f"/api/v1/runs/{created['run_id']}").json()
    assert run["status"] == "completed"
    assert run["result"]["manifest_file_count"] >= 5
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/summary").json()["resolved_route"] == "traditional_gap"
    assert restarted.get(
        f"/api/v1/runs/{created['run_id']}/capabilities"
    ).json() == []
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/domain/EvidenceCard").json()
    assert len(restarted.get(f"/api/v1/runs/{created['run_id']}/domain/WinningMechanismStageOutput").json()) == 3
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/report", headers={"X-Role": "reviewer"}).status_code == 200
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/trace", headers={"X-Role": "analyst"}).status_code == 403
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/manifest", headers={"X-Role": "auditor"}).json()["file_count"] >= 5
