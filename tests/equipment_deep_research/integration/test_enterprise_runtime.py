from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Lock
import time

from fastapi.testclient import TestClient

from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunQueue, SqlRunRepository
from equipment_deep_research.queue.worker import ResearchWorker, WorkerOutcome
from equipment_deep_research.orchestration.runner import DeepResearchRunner


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
        "queued",
        "upstream stream disconnected before completion",
    )
    assert service.get_run(run.run_id).status == "queued"
    assert service.get_run(run.run_id).error == ""
    assert service.queue.pending_run_ids() == [run.run_id]
    retry_events = [
        event
        for event in repository.events_after(run.run_id, 0)
        if event["event_type"] == "run_transient_resume_scheduled"
    ]
    assert len(retry_events) == 1
    assert retry_events[0]["payload"]["attempt"] == 1

    second = worker.run_once()

    assert second == WorkerOutcome(run.run_id, "completed")
    assert calls == 2


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

    assert worker.run_once().status == "queued"
    second = worker.run_once()

    assert second == WorkerOutcome(
        run.run_id,
        "failed",
        "upstream stream disconnected before completion",
    )
    assert service.get_run(run.run_id).status == "failed"
    assert service.queue.pending_run_ids() == []
    retry_events = [
        event
        for event in repository.events_after(run.run_id, 0)
        if event["event_type"] == "run_transient_resume_scheduled"
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


def test_sse_replay_and_rbac(tmp_path: Path) -> None:
    repository = SqlRunRepository(create_database_engine(f"sqlite:///{tmp_path / 'api.db'}"))
    repository.append_event("run-1", "stage_completed", {"layer": "L1"})
    client = TestClient(create_app(event_repository=repository))
    denied = client.post("/api/v1/runs", headers={"X-Role": "reviewer"}, json={"topic": "x"})
    assert denied.status_code == 403
    replay = client.get("/api/v1/runs/run-1/events", headers={"Last-Event-ID": "0"})
    assert "event: stage_completed" in replay.text


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
    assert client.get(f"/api/v1/runs/{created['run_id']}/capabilities").json()
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
    assert {"write_stage_output", "create_capability_image", "write_audit", "write_report"} <= called_tools
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
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/capabilities").json()
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/domain/EvidenceCard").json()
    assert len(restarted.get(f"/api/v1/runs/{created['run_id']}/domain/WinningMechanismStageOutput").json()) == 3
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/report", headers={"X-Role": "reviewer"}).status_code == 200
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/trace", headers={"X-Role": "analyst"}).status_code == 403
    assert restarted.get(f"/api/v1/runs/{created['run_id']}/manifest", headers={"X-Role": "auditor"}).json()["file_count"] >= 5
