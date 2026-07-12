from pathlib import Path

from fastapi.testclient import TestClient

from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunRepository
from equipment_deep_research.queue.worker import ResearchWorker


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


def test_sse_replay_and_rbac(tmp_path: Path) -> None:
    repository = SqlRunRepository(create_database_engine(f"sqlite:///{tmp_path / 'api.db'}"))
    repository.append_event("run-1", "stage_completed", {"layer": "L1"})
    client = TestClient(create_app(event_repository=repository))
    denied = client.post("/api/v1/runs", headers={"X-Role": "reviewer"}, json={"topic": "x"})
    assert denied.status_code == 403
    replay = client.get("/api/v1/runs/run-1/events", headers={"Last-Event-ID": "0"})
    assert "event: stage_completed" in replay.text
