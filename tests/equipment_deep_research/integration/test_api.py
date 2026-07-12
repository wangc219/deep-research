from fastapi.testclient import TestClient

from equipment_deep_research.api.app import create_app


def test_api_creates_and_queues_run() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v1/runs", json={"topic": "test", "research_route": "auto", "selected_agent_ids": [], "max_rounds": 5})
    assert created.status_code == 201
    started = client.post(f"/api/v1/runs/{created.json()['run_id']}/start", headers={"Idempotency-Key": "start-1"})
    assert started.json()["status"] == "queued"
