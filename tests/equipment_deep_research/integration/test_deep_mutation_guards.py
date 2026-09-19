"""Mutation fencing for deep research against immutable parent runs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunQueue, SqlRunRepository


@pytest.mark.parametrize(
    ("parent_status", "expected_status"),
    [("cancelled", 409), ("archived", 410)],
)
def test_deep_mutations_are_fenced_after_parent_terminal_state(
    tmp_path, parent_status: str, expected_status: int
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / (parent_status + '.db')}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(repository=repository, queue=SqlRunQueue(engine))
    run = service.create_run(CreateRunCommand("deep mutation guard", "auto", [], 1, "analyst"))
    service.set_status(run.run_id, parent_status)
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": f"create-{parent_status}"},
        json={"kind": "deep-thinking"},
    )

    assert response.status_code == expected_status
    assert "deep research" in response.json()["detail"]

    # Historical state remains readable; the mutation fence is not a data
    # deletion mechanism and must not hide the parent run's deep history.
    listed = client.get(f"/api/v1/runs/{run.run_id}/deep-thinking/sessions")
    assert listed.status_code == 200

