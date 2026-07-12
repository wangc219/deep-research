from __future__ import annotations

import pytest
from equipment_deep_research.application.dto import CreateRunCommand
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
