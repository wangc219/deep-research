from __future__ import annotations

import asyncio
from pathlib import Path
import time
from types import SimpleNamespace

from equipment_deep_research.interfaces import worker as worker_interface
from equipment_deep_research.queue.worker import ResearchWorker, WorkerOutcome


def test_runtime_progress_events_update_user_facing_run_phase() -> None:
    assert worker_interface.runtime_status_for_event("baseline_agents_summarized") == "synthesizing"
    assert worker_interface.runtime_status_for_event("winning_model_call_started") == "synthesizing"
    assert worker_interface.runtime_status_for_event("audit_completed") == "reviewing"
    assert worker_interface.runtime_status_for_event("report_model_call_started") == "reporting"
    assert worker_interface.runtime_status_for_event("baseline_model_call_progress") == ""


def test_dynamic_swarm_internal_work_releases_outer_research_slot() -> None:
    assert worker_interface.releases_research_slot_for_event(
        "winning_mission_graph_planned"
    )
    assert worker_interface.releases_research_slot_for_event(
        "winning_s6_card_authoring_started"
    )
    assert not worker_interface.releases_research_slot_for_event(
        "baseline_model_call_started"
    )


def test_worker_survives_cancelled_run_and_releases_lease(tmp_path: Path) -> None:
    touches: list[tuple[str, str]] = []

    class Queue:
        def __init__(self) -> None:
            self.claimed = False
            self.acked: list[str] = []

        def claim(self):
            if self.claimed:
                return None
            self.claimed = True
            return "run-cancelled"

        def ack(self, run_id: str) -> None:
            self.acked.append(run_id)

    class Service:
        def __init__(self) -> None:
            self.queue = Queue()
            self.status = "queued"
            self.error = ""

        def touch_worker(self, worker_id, *, status, current_run_id=""):
            del worker_id
            touches.append((status, current_run_id))

        def get_run(self, run_id):
            del run_id
            return SimpleNamespace(status=self.status, result={})

        def runtime_health(self):
            return {"workers": []}

        def set_status(self, run_id, status):
            del run_id
            self.status = status

        def set_error(self, run_id, error):
            del run_id
            self.error = error

    service = Service()

    def cancelled(_run_id: str):
        raise asyncio.CancelledError("wall-clock budget expired")

    from equipment_deep_research.queue.worker import ResearchWorker

    outcome = ResearchWorker(
        service=service,
        execute=cancelled,
        worker_id="worker-1",
        heartbeat_interval_seconds=0.01,
    ).run_once()

    assert outcome == WorkerOutcome(
        "run-cancelled", "failed", "wall-clock budget expired"
    )
    assert service.status == "failed"
    assert service.queue.acked == ["run-cancelled"]
    assert touches[-1] == ("idle", "")


def test_worker_internal_lease_status_is_heartbeat_visible() -> None:
    touches: list[tuple[str, str]] = []

    class Service:
        def touch_worker(
            self,
            worker_id: str,
            *,
            status: str,
            current_run_id: str = "",
        ) -> None:
            del worker_id
            touches.append((status, current_run_id))

    worker = ResearchWorker(
        service=Service(),
        execute=lambda _: {},
        heartbeat_interval_seconds=0.01,
    )
    worker.set_lease_status("internal")
    with worker._heartbeat_during("run-s6"):
        time.sleep(0.03)

    assert ("internal", "run-s6") in touches


def test_worker_resumes_when_run_directory_already_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "runs"
    (output_root / "run-existing").mkdir(parents=True)
    recorded: dict[str, object] = {}

    class FakeService:
        def get_run(self, run_id: str):
            return SimpleNamespace(
                run_id=run_id,
                topic="topic",
                research_route="traditional_gap",
                selected_agent_ids=[],
                max_rounds=5,
                execution={
                    "mode": "real",
                    "provider": "codex",
                    "model": "gpt-5.5",
                    "base_url": "https://codex.example.test/v1",
                    "api_key_env": "PROJECT_CODEX_KEY",
                    "agent_models": {
                        "winning_s1_opponent": {
                            "provider": "responses",
                            "model": "custom-model",
                            "base_url": "https://custom.example.test/v1/responses",
                            "api_key_env": "CUSTOM_AGENT_KEY",
                        }
                    },
                },
                analyst_confirmed=False,
            )

    class RecordingRunner:
        def __init__(self, **kwargs) -> None:
            recorded["init"] = kwargs

        def run(self, **kwargs):
            recorded["run"] = kwargs
            return {}

    class OneShotWorker:
        def __init__(self, *, service, execute, worker_id, runtime_generation) -> None:
            del service, worker_id, runtime_generation
            self.execute = execute

        def run_once(self):
            self.execute("run-existing")
            return WorkerOutcome("run-existing", "completed")

    monkeypatch.setattr(worker_interface, "build_application_service", lambda _url: FakeService())
    monkeypatch.setattr(worker_interface, "DeepResearchRunner", RecordingRunner)
    monkeypatch.setattr(worker_interface, "ResearchWorker", OneShotWorker)

    exit_code = worker_interface.main(
        [
            "--project-root",
            str(tmp_path),
            "--output-root",
            str(output_root),
            "--once",
        ]
    )

    assert exit_code == 0
    assert recorded["run"]["resume"] is True
    assert recorded["run"]["provider_name"] == "codex"
    assert recorded["run"]["provider_model"] == "gpt-5.5"
    assert recorded["run"]["provider_base_url"] == "https://codex.example.test/v1"
    assert recorded["run"]["provider_api_key_env"] == "PROJECT_CODEX_KEY"
    assert recorded["run"]["agent_model_profiles"]["winning_s1_opponent"] == {
        "provider": "responses",
        "model": "custom-model",
        "base_url": "https://custom.example.test/v1/responses",
        "api_key_env": "CUSTOM_AGENT_KEY",
    }


def test_worker_refuses_to_overwrite_an_online_duplicate_identity(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    class FakeService:
        def runtime_health(self):
            return {
                "workers": [
                    {
                        "worker_id": worker_interface.versioned_worker_id(
                            "research-worker-1"
                        ),
                        "status": "working",
                        "current_run_id": "run-active",
                        "online": True,
                    }
                ]
            }

    monkeypatch.setattr(
        worker_interface,
        "build_application_service",
        lambda _url: FakeService(),
    )

    exit_code = worker_interface.main(
        [
            "--project-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "runs"),
            "--worker-id",
            "research-worker-1",
            "--once",
        ]
    )

    assert exit_code == 2
    assert "拒绝重复启动" in capsys.readouterr().err
