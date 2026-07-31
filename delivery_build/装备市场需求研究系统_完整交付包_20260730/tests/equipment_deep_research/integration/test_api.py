from pathlib import Path

from fastapi.testclient import TestClient

from equipment_deep_research.api.app import (
    _capability_api_view,
    _interaction_workflow_phases,
    _interaction_workflow_summary,
    _public_trace_interaction,
    create_app,
)
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunQueue, SqlRunRepository


def test_api_creates_and_queues_run() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v1/runs", json={"topic": "test", "research_route": "auto", "selected_agent_ids": [], "max_rounds": 5})
    assert created.status_code == 201
    started = client.post(f"/api/v1/runs/{created.json()['run_id']}/start", headers={"Idempotency-Key": "start-1"})
    assert started.json()["status"] == "queued"


def test_api_preserves_optional_supplemental_information() -> None:
    client = TestClient(create_app())
    supplement = "如果单发成本降至拦截弹的1/50，如何改变弹药基数与后勤理论？"

    created = client.post(
        "/api/v1/runs",
        json={"topic": "万枚级低成本远程弹药", "supplemental_information": supplement},
    )

    assert created.status_code == 201
    assert created.json()["supplemental_information"] == supplement
    loaded = client.get(f"/api/v1/runs/{created.json()['run_id']}")
    assert loaded.json()["supplemental_information"] == supplement


def test_api_list_reports_actual_baseline_agent_calls(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'application.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(
        CreateRunCommand(
            "局部战争装备需求",
            "war_case_learning",
            ["weapon_equipment", "operational_employment", "combat_scenario"],
            2,
            "analyst",
        )
    )
    actual_agents = [
        "case_research",
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
    ]
    for agent_id in actual_agents:
        repository.append_event(
            run.run_id,
            "baseline_model_call_started",
            {
                "source": "trace",
                "event": {
                    "actor": agent_id,
                    "event_type": "baseline_model_call_started",
                    "payload": {"agent_id": agent_id},
                },
            },
        )

    rows = TestClient(
        create_app(service, event_repository=repository)
    ).get("/api/v1/runs").json()
    listed = next(item for item in rows if item["run_id"] == run.run_id)

    assert listed["selected_agent_ids"] == [
        "weapon_equipment",
        "operational_employment",
        "combat_scenario",
    ]
    assert listed["actual_agent_ids"] == actual_agents
    assert listed["actual_agent_count"] == 4


def test_api_retries_failed_run_from_checkpoint() -> None:
    service = ResearchApplicationService()
    client = TestClient(create_app(service))
    created = client.post("/api/v1/runs", json={"topic": "retry"}).json()
    service.set_status(created["run_id"], "researching")
    service.set_error(created["run_id"], "provider metadata was not serializable")
    service.set_status(created["run_id"], "failed")

    response = client.post(
        f"/api/v1/runs/{created['run_id']}/resume",
        headers={"Idempotency-Key": "resume-failed"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["error"] == ""


def test_persisted_trace_wrapper_replays_original_step_details() -> None:
    public = _public_trace_interaction(
        {
            "event_type": "winning_subagent_completed",
            "actor": "winning_s3_breakthrough",
            "payload": {
                "event_id": "trace-winning-s3",
                "event_type": "winning_subagent_completed",
                "actor": "winning_s3_breakthrough",
                "summary": "S3 专用 Agent 完成",
                "created_at": "2026-07-20T00:00:00+00:00",
                "input_refs": [],
                "output_refs": [],
                "payload": {
                    "step": 3,
                    "status": "completed",
                    "middle_cycle": 1,
                    "execution_mode": "deep",
                },
            },
        }
    )

    assert public["event_id"] == "trace-winning-s3"
    assert public["details"]["step"] == 3
    assert public["details"]["status"] == "completed"


def test_reporter_failure_marks_report_phase_failed() -> None:
    class View:
        status = "failed"
        selected_agent_ids: list[str] = []

    phases = _interaction_workflow_phases(
        [
            {
                "event_type": "report_model_failed",
                "actor": "reporter",
                "details": {"status": "failed_no_fallback"},
            }
        ],
        view=View(),
        step_plan=[],
        dynamic_agents=[],
    )

    report_phase = next(item for item in phases if item["id"] == "report")
    assert report_phase["status"] == "failed"
    assert report_phase["event_count"] == 1
    assert "未使用降级模板" in report_phase["detail"]


def test_reporter_retry_activity_overrides_historical_failure() -> None:
    class View:
        status = "researching"
        selected_agent_ids: list[str] = []

    rows = [
        {
            "event_type": "report_model_failed",
            "actor": "reporter",
            "details": {
                "status": "failed_no_fallback",
                "detail": "first attempt failed",
            },
        },
        {
            "event_type": "run_resumed",
            "actor": "orchestrator",
            "details": {"resume_count": 1},
        },
        {
            "event_type": "tool_call",
            "actor": "reporter",
            "details": {"tool_name": "draft_report"},
        },
    ]

    phases = _interaction_workflow_phases(
        rows,
        view=View(),
        step_plan=[],
        dynamic_agents=[],
    )
    report_phase = next(item for item in phases if item["id"] == "report")
    assert report_phase["status"] == "running"
    assert report_phase["error"] == ""

    rows.append(
        {
            "event_type": "report_completed",
            "actor": "reporter",
            "details": {"status": "completed"},
        }
    )
    phases = _interaction_workflow_phases(
        rows,
        view=View(),
        step_plan=[],
        dynamic_agents=[],
    )
    report_phase = next(item for item in phases if item["id"] == "report")
    assert report_phase["status"] == "completed"


def test_failed_run_after_reporter_activity_projects_report_phase_failed() -> None:
    class View:
        status = "failed"
        selected_agent_ids: list[str] = []

    phases = _interaction_workflow_phases(
        [
            {
                "event_type": "tool_call",
                "actor": "reporter",
                "details": {"tool_name": "draft_report"},
            }
        ],
        view=View(),
        step_plan=[],
        dynamic_agents=[],
    )

    report_phase = next(item for item in phases if item["id"] == "report")
    assert report_phase["status"] == "failed"
    assert "未使用降级模板" in report_phase["detail"]


def test_workflow_projects_winning_and_reporter_live_elapsed_progress() -> None:
    class View:
        status = "researching"
        selected_agent_ids: list[str] = []
        discovery_branch = "C"
        research_route = "war_case_learning"
        execution: dict = {}

    rows = [
        {
            "event_type": "winning_model_call_progress",
            "actor": "winning_cohort-s3-s4-s5",
            "details": {
                "step": 3,
                "steps": [3, 4, 5],
                "current_step": "S3/S4/S5 联合推理",
                "elapsed_seconds": 45,
                "phase": "winning_cohort-s3-s4-s5",
            },
        },
        {
            "event_type": "report_model_call_progress",
            "actor": "reporter",
            "details": {
                "current_step": "三层九项报告撰写",
                "elapsed_seconds": 75,
                "phase": "report_generation",
            },
        },
    ]

    workflow = _interaction_workflow_summary(rows, View())
    step_three = next(item for item in workflow["step_plan"] if item["step"] == 3)
    report_phase = next(item for item in workflow["phases"] if item["id"] == "report")

    assert step_three["status"] == "running"
    assert step_three["current_step"] == "S3/S4/S5 联合推理"
    assert step_three["elapsed_seconds"] == 45
    assert report_phase["status"] == "running"
    assert report_phase["detail"] == "三层九项报告撰写 · 已耗时 75 秒"


def test_reasoning_projection_does_not_overwrite_branch_skip_or_middle_cycle() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
            "F branch replay",
            "auto",
            [],
            2,
            "analyst",
            discovery_branch="F",
        )
    )
    rows = [
        {
            "event_type": "run_started",
            "actor": "orchestrator",
            "details": {"discovery_blueprint": {"primary_branch": "F"}},
        },
        {
            "event_type": "winning_subagent_completed",
            "actor": "winning_s1_opponent",
            "summary": "S1 按分支蓝图跳过",
            "details": {
                "step": 1,
                "status": "skipped_by_branch_blueprint",
                "execution_mode": "skip",
                "middle_cycle": 1,
            },
        },
        {
            "event_type": "winning_reasoning_step_completed",
            "actor": "winning_mechanism",
            "summary": "不应显示的旧版S1推理正文",
            "details": {"step": 1},
        },
    ]

    summary = _interaction_workflow_summary(rows, run)

    assert summary["step_plan"][0]["status"] == "skipped"
    assert summary["step_plan"][0]["middle_cycle"] == 1
    assert summary["step_plan"][0]["result_summary"] == "S1 按分支蓝图跳过"


def test_s_agent_phase_waits_for_middle_loop_gate_after_first_pass() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
            "S-Agent middle-loop visualization",
            "auto",
            [],
            2,
            "analyst",
            discovery_branch="F",
        )
    )
    rows = [
        {
            "event_type": "run_started",
            "actor": "orchestrator",
            "details": {"discovery_blueprint": {"primary_branch": "F"}},
        },
        *[
            {
                "event_type": "winning_subagent_completed",
                "actor": f"winning_s{step}",
                "summary": f"S{step} complete",
                "details": {
                    "step": step,
                    "status": "completed",
                    "execution_mode": "deep",
                    "middle_cycle": 1,
                },
            }
            for step in (3, 4, 5, 6)
        ],
    ]

    first_pass = _interaction_workflow_summary(rows, run)
    first_phase = next(
        item for item in first_pass["phases"] if item["id"] == "s_agents"
    )
    assert first_phase["status"] == "running"

    rows.append(
        {
            "event_type": "winning_middle_loop_evaluated",
            "actor": "winning_round_critic",
            "details": {"passed": True, "cycle": 1},
        }
    )
    gated = _interaction_workflow_summary(rows, run)
    gated_phase = next(
        item for item in gated["phases"] if item["id"] == "s_agents"
    )
    assert gated_phase["status"] == "completed"


def test_api_permanently_deletes_terminal_and_orphaned_active_runs() -> None:
    service = ResearchApplicationService()
    client = TestClient(create_app(service))
    draft = client.post("/api/v1/runs", json={"topic": "delete me"}).json()
    deleted = client.post(
        "/api/v1/runs/permanent-delete",
        json={"run_ids": [draft["run_id"]]},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": [draft["run_id"]], "rejected": []}
    assert client.get(f"/api/v1/runs/{draft['run_id']}").status_code == 404

    active = client.post("/api/v1/runs", json={"topic": "keep active"}).json()
    client.post(
        f"/api/v1/runs/{active['run_id']}/start",
        headers={"Idempotency-Key": "active-start"},
    )
    service.set_status(active["run_id"], "researching")
    orphan_deleted = client.post(
        "/api/v1/runs/permanent-delete",
        json={"run_ids": [active["run_id"]]},
    ).json()
    assert orphan_deleted == {"deleted": [active["run_id"]], "rejected": []}
    assert client.get(f"/api/v1/runs/{active['run_id']}").status_code == 404


def test_api_permanently_deletes_queued_run_queue_events_and_files(
    tmp_path: Path, monkeypatch,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'delete.db'}")
    repository = SqlRunRepository(engine)
    queue = SqlRunQueue(engine)
    service = ResearchApplicationService(repository=repository, queue=queue)
    output_root = tmp_path / "runs"
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service, event_repository=repository))
    created = client.post("/api/v1/runs", json={"topic": "delete queued"}).json()
    run_id = created["run_id"]
    client.post(
        f"/api/v1/runs/{run_id}/start",
        headers={"Idempotency-Key": "queue-delete"},
    )
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "generated.txt").write_text("generated", encoding="utf-8")

    response = client.delete(f"/api/v1/runs/{run_id}/permanent")

    assert response.status_code == 200
    assert response.json() == {"run_id": run_id, "deleted": True}
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert queue.pending_run_ids() == []
    assert repository.events_after(run_id, 0) == []
    assert repository.deletion_residue(run_id) == {
        "runs": 0,
        "runtime_events": 0,
        "run_queue": 0,
        "worker_heartbeats": 0,
    }
    assert not run_dir.exists()


def test_api_rejects_permanent_delete_while_online_worker_handles_run(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'active-delete.db'}")
    repository = SqlRunRepository(engine)
    queue = SqlRunQueue(engine)
    service = ResearchApplicationService(repository=repository, queue=queue)
    client = TestClient(create_app(service, event_repository=repository))
    created = client.post("/api/v1/runs", json={"topic": "actively handled"}).json()
    run_id = created["run_id"]
    service.set_status(run_id, "researching")
    service.touch_worker("worker-active", status="working", current_run_id=run_id)

    response = client.delete(f"/api/v1/runs/{run_id}/permanent")

    assert response.status_code == 409
    assert "online worker" in response.json()["detail"]
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 200


def test_catalog_is_loaded_from_registry_and_invalid_selection_is_rejected() -> None:
    client = TestClient(create_app())
    catalog = client.get("/api/v1/catalog").json()
    assert catalog["provider"]["model"] == "gpt-5.5"
    assert catalog["provider"]["default_codex_base_url"] == "https://api.openai.com/v1"
    assert catalog["provider"]["default_codex_api_key_env"] == "EQUIPMENT_DR_CODEX_API_KEY"
    assert [item["id"] for item in catalog["provider"]["provider_options"]] == [
        "codex",
        "responses",
    ]
    assert catalog["provider"]["execution_fields"] == [
        "provider",
        "model",
        "base_url",
        "api_key_env",
        "agent_models",
    ]
    assert [item["agent_id"] for item in catalog["agents"]] == [
        "international_situation",
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
        "opponent_monitoring",
        "system_confrontation",
    ]
    assert all(item["visible_sections"] for item in catalog["agents"])
    assert all(item["harness_profile"] for item in catalog["agents"])
    assert all(item["skill_ids"] for item in catalog["agents"])
    assert all(item["harness_profile_config"]["stop_conditions"] for item in catalog["agents"])
    assert catalog["provider"]["configurable_agent_ids"].count("orchestrator") == 1
    assert len(catalog["provider"]["configurable_agent_ids"]) == len(
        set(catalog["provider"]["configurable_agent_ids"])
    )
    assert [item["id"] for item in catalog["interaction_modes"]] == [
        "expert",
        "autonomous",
    ]
    defaults = [item["id"] for item in catalog["execution_profiles"] if item["default"]]
    assert defaults == ["optimized_v2"]
    assert [item["id"] for item in catalog["discovery_branches"]] == list(
        "ABCDEFGH"
    )
    assert all(
        item["step_modes"] == [
            {
                "step": step,
                "execution_mode": item["step_modes"][step - 1]["execution_mode"],
            }
            for step in range(1, 7)
        ]
        for item in catalog["discovery_branches"]
    )
    assert catalog["discovery_branches"][0]["step_modes"][0] == {
        "step": 1,
        "execution_mode": "light",
    }
    invalid = client.post(
        "/api/v1/runs",
        json={"topic": "test", "selected_agent_ids": ["unknown-agent"]},
    )
    assert invalid.status_code == 422


def test_api_uses_server_execution_defaults_when_frontend_omits_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_MODE", "real")
    monkeypatch.setenv("EQUIPMENT_DR_PROVIDER", "codex")
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "server-model")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://agent.example/v1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", "SERVER_AGENT_API_KEY")
    monkeypatch.setenv("SERVER_AGENT_API_KEY", "test-secret")

    created = TestClient(create_app()).post(
        "/api/v1/runs",
        json={"topic": "server managed execution"},
    )

    assert created.status_code == 201
    assert created.json()["execution"] == {
        "mode": "real",
        "provider": "codex",
        "model": "server-model",
        "base_url": "https://agent.example/v1",
        "api_key_env": "SERVER_AGENT_API_KEY",
    }


def test_api_persists_interaction_mode_and_discovery_branch() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/v1/runs",
        json={
            "topic": "技术驱动需求发现",
            "research_route": "auto",
            "interaction_mode": "autonomous",
            "discovery_branch": "D",
        },
    )

    assert created.status_code == 201
    assert created.json()["interaction_mode"] == "autonomous"
    assert created.json()["discovery_branch"] == "D"


def test_api_persists_real_execution_metadata_without_api_key() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/v1/runs",
        json={
            "topic": "real model configuration",
            "research_route": "new_winning_mechanism",
            "execution": {
                "mode": "real",
                "provider": "responses",
                "model": "gpt-5.5",
                "base_url": "https://models.example.test/v1/responses",
                "api_key_env": "CLIENT_MODEL_KEY",
            },
        },
    )
    assert created.status_code == 201
    execution = created.json()["execution"]
    assert execution == {
        "mode": "real",
        "provider": "responses",
        "model": "gpt-5.5",
        "base_url": "https://models.example.test/v1/responses",
        "api_key_env": "CLIENT_MODEL_KEY",
    }
    assert "api_key" not in execution

    rejected = client.post(
        "/api/v1/runs",
        json={
            "topic": "invalid real endpoint",
            "execution": {"mode": "real", "base_url": "http://models.example.test/v1/responses"},
        },
    )
    assert rejected.status_code == 422
    assert "HTTPS" in rejected.json()["detail"]
    secret_url = client.post(
        "/api/v1/runs",
        json={
            "topic": "secret in URL",
            "execution": {
                "mode": "real",
                "base_url": "https://models.example.test/v1/responses?api_key=secret",
            },
        },
    )
    assert secret_url.status_code == 422
    assert "must not contain credentials" in secret_url.json()["detail"]


def test_api_accepts_and_persists_codex_api_configuration_without_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.api.app.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    client = TestClient(create_app())
    created = client.post(
        "/api/v1/runs",
        json={
            "topic": "codex multi-agent execution",
            "research_route": "traditional_gap",
            "execution": {
                "mode": "real",
                "provider": "codex",
                "model": "gpt-5.5",
                "base_url": "https://codex.example.test/v1",
                "api_key_env": "PROJECT_CODEX_KEY",
            },
        },
    )
    assert created.status_code == 201
    assert created.json()["execution"] == {
        "mode": "real",
        "provider": "codex",
        "model": "gpt-5.5",
        "base_url": "https://codex.example.test/v1",
        "api_key_env": "PROJECT_CODEX_KEY",
    }
    assert "api_key" not in created.json()["execution"]

    updated = client.patch(
        f"/api/v1/runs/{created.json()['run_id']}",
        json={
            "topic": "switch to custom Agent",
            "research_route": "traditional_gap",
            "selected_agent_ids": ["weapon_equipment"],
            "max_rounds": 3,
            "execution": {
                "mode": "real",
                "provider": "responses",
                "model": "custom-model",
                "base_url": "https://custom.example.test/v1/responses",
                "api_key_env": "CUSTOM_AGENT_KEY",
            },
        },
    )
    assert updated.status_code == 200
    assert updated.json()["execution"] == {
        "mode": "real",
        "provider": "responses",
        "model": "custom-model",
        "base_url": "https://custom.example.test/v1/responses",
        "api_key_env": "CUSTOM_AGENT_KEY",
    }

    invalid_update = client.patch(
        f"/api/v1/runs/{created.json()['run_id']}",
        json={
            "topic": "invalid update",
            "research_route": "traditional_gap",
            "selected_agent_ids": ["weapon_equipment"],
            "max_rounds": 3,
            "execution": {
                "mode": "real",
                "provider": "codex",
                "model": "gpt-5.5",
                "base_url": "http://unsafe.example.test/v1",
                "api_key_env": "PROJECT_CODEX_KEY",
            },
        },
    )
    assert invalid_update.status_code == 422


def test_api_rejects_unsafe_codex_url_and_invalid_key_environment(monkeypatch) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.api.app.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    client = TestClient(create_app())
    unsafe_url = client.post(
        "/api/v1/runs",
        json={
            "topic": "unsafe Codex endpoint",
            "execution": {
                "mode": "real",
                "provider": "codex",
                "model": "gpt-5.5",
                "base_url": "https://codex.example.test/v1?api_key=secret",
                "api_key_env": "PROJECT_CODEX_KEY",
            },
        },
    )
    assert unsafe_url.status_code == 422
    assert "must not contain credentials" in unsafe_url.json()["detail"]

    invalid_env = client.post(
        "/api/v1/runs",
        json={
            "topic": "invalid Codex key environment",
            "execution": {
                "mode": "real",
                "provider": "codex",
                "model": "gpt-5.5",
                "base_url": "https://codex.example.test/v1",
                "api_key_env": "NOT-AN-ENV",
            },
        },
    )
    assert invalid_env.status_code == 422
    assert "environment variable name is invalid" in invalid_env.json()["detail"]


def test_api_checks_codex_and_subagent_credentials_before_queueing(monkeypatch) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.api.app.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "configured-codex-key")
    monkeypatch.delenv("WINNING_CUSTOM_KEY", raising=False)
    client = TestClient(create_app())
    created = client.post(
        "/api/v1/runs",
        json={
            "topic": "credential preflight",
            "execution": {
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
                        "api_key_env": "WINNING_CUSTOM_KEY",
                    }
                },
            },
        },
    ).json()

    rejected = client.post(
        f"/api/v1/runs/{created['run_id']}/start",
        headers={"Idempotency-Key": "credential-check-1"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"].endswith("WINNING_CUSTOM_KEY")
    assert client.get(f"/api/v1/runs/{created['run_id']}").json()["status"] == "draft"

    monkeypatch.setenv("WINNING_CUSTOM_KEY", "configured-custom-key")
    started = client.post(
        f"/api/v1/runs/{created['run_id']}/start",
        headers={"Idempotency-Key": "credential-check-2"},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "queued"


def test_api_validates_and_persists_distinct_agent_model_profiles() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v1/runs", json={
        "topic": "multi model",
        "execution": {
            "mode": "real",
            "model": "default-model",
            "base_url": "https://models.example.test/v1/responses",
            "api_key_env": "DEFAULT_KEY",
            "agent_models": {
                "orchestrator": {"model": "planner-model"},
                "winning_mechanism": {
                    "model": "winning-model",
                    "base_url": "https://winning.example.test/v1/responses",
                    "api_key_env": "WINNING_KEY",
                },
            },
        },
    })
    assert created.status_code == 201
    profiles = created.json()["execution"]["agent_models"]
    assert profiles["orchestrator"]["model"] == "planner-model"
    assert profiles["orchestrator"]["base_url"] == "https://models.example.test/v1/responses"
    assert profiles["winning_mechanism"]["model"] == "winning-model"
    assert all("api_key" not in profile for profile in profiles.values())


def test_interactions_are_visible_from_persistent_runtime_events_before_completion() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("实时交互", "auto", [], 2, "analyst"))
    service.start_run(run.run_id, actor="analyst", idempotency_key="start-live")
    captured: list[tuple[str, dict]] = []

    class EventRepository:
        def append_event(self, run_id: str, event_type: str, payload: dict) -> int:
            captured.append((event_type, payload))
            return len(captured)

        def events_after(self, run_id: str, sequence: int) -> list[dict]:
            return [
                {
                    "run_id": run_id,
                    "sequence": index,
                    "event_type": event_type,
                    "payload": payload,
                }
                for index, (event_type, payload) in enumerate(captured, start=1)
                if index > sequence
            ]

    repository = EventRepository()
    repository.append_event(
        run.run_id,
        "agent_task_delegated",
        {
            "source": "trace",
            "event": {
                "event_id": "trace-live-1",
                "event_type": "agent_task_delegated",
                "actor": "orchestrator",
                "summary": "委派国际形势研判",
                "created_at": "2026-07-13T00:00:00+00:00",
                "input_refs": [],
                "output_refs": ["baseline:international_situation"],
                "payload": {"target_agent_id": "international_situation"},
            },
        },
    )
    repository.append_event(
        run.run_id,
        "tool_call",
        {
            "source": "session_projection",
            "event": {
                "event_type": "tool_call",
                "created_at": "2026-07-13T00:00:01+00:00",
                "agent_id": "international_situation",
                "tool_name": "search_sources",
                "call_id": "call-live-1",
                "arguments": {"query": "公开威胁态势"},
            },
        },
    )
    client = TestClient(create_app(service, event_repository=repository))

    payload = client.get(f"/api/v1/runs/{run.run_id}/interactions").json()

    assert [item["event_type"] for item in payload["events"]] == [
        "agent_task_delegated",
        "tool_call",
    ]
    assert payload["counts"]["tool_calls"] == 1
    assert payload["events"][1]["details"]["arguments"] == {
        "query": "公开威胁态势"
    }
    orchestrators = [
        item for item in payload["agents"] if item["agent_id"] == "orchestrator"
    ]
    assert len(orchestrators) == 1
    assert orchestrators[0]["skill_ids"] == [
        "requirement_semantics_analysis",
        "discovery_driver_recognition",
        "discovery_blueprint_generation",
        "dag_loop_orchestration",
    ]
    assert orchestrators[0]["harness_profile"] == "orchestration_v1"
    assert orchestrators[0]["harness_profile_config"]["stop_conditions"]
    assert "raw_message" not in str(payload)

    compact = client.get(
        f"/api/v1/runs/{run.run_id}/interactions?compact=true"
    ).json()
    assert compact["counts"]["events"] == 2
    assert compact["counts"]["visible_events"] == 1
    assert [item["event_type"] for item in compact["events"]] == [
        "agent_task_delegated"
    ]


def test_interactions_project_codex_workflow_step_modes_and_dynamic_agents() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand(
        "Codex workflow projection",
        "auto",
        [],
        2,
        "analyst",
        execution={
            "mode": "real",
            "provider": "codex",
            "model": "gpt-test",
        },
    ))
    captured: list[tuple[str, dict]] = []

    class EventRepository:
        def events_after(self, run_id: str, sequence: int) -> list[dict]:
            return [
                {
                    "run_id": run_id,
                    "sequence": index,
                    "event_type": event_type,
                    "payload": payload,
                }
                for index, (event_type, payload) in enumerate(captured, start=1)
                if index > sequence
            ]

    def add(event_type: str, actor: str, details: dict) -> None:
        captured.append((event_type, {
            "source": "trace",
            "event": {
                "event_id": f"trace-{len(captured) + 1}",
                "event_type": event_type,
                "actor": actor,
                "summary": event_type,
                "created_at": f"2026-07-17T00:00:0{len(captured)}+00:00",
                "input_refs": [],
                "output_refs": [],
                "payload": details,
            },
        }))

    add("run_started", "orchestrator", {
        "mode": "real",
        "provider": "codex",
        "model": "gpt-test",
        "agent_ids": [
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        "discovery_blueprint": {
            "primary_branch": "G",
            "branch_name": "跨域融合发现",
            "secondary_branches": [],
            "blueprint_mode": "catalog",
            "generated_by": "codex_orchestrator",
            "adaptive_winning_step_modes": {"6": "standard"},
        },
    })
    add("discovery_meta_loop_evaluated", "orchestrator", {
        "cycle": 2,
        "primary_branch": "G",
        "secondary_branches": ["E"],
        "replan_required": True,
        "added_secondary_branches": ["E"],
        "step_mode_overrides": [
            {"step": 1, "mode": "deep"},
            {"step": 6, "mode": "deep"},
        ],
        "dynamic_subagents": [{
            "agent_instance_id": "dynamic-opponent-review",
            "display_name": "对手变化复核 Agent",
            "merge_target": "S1",
            "skill_ids": ["threat_forecasting"],
            "knowledge_pack_ids": ["public_evidence_index"],
        }],
        "stop_reason": "bounded_replan_complete",
    })
    add("winning_subagent_completed", "winning_s1_opponent", {
        "step": 1,
        "execution_mode": "deep",
        "middle_cycle": 2,
        "status": "completed",
    })
    add("winning_subagent_completed", "winning_s2_operations", {
        "step": 2,
        "execution_mode": "skip",
        "middle_cycle": 1,
        "status": "skipped_by_branch_blueprint",
    })
    add("winning_subagent_completed", "dynamic-opponent-review", {
        "step": 0,
        "execution_mode": "dynamic",
        "display_name": "对手变化复核 Agent",
        "merge_target": "S1",
        "skill_ids": ["threat_forecasting"],
        "knowledge_pack_ids": ["public_evidence_index"],
        "status": "completed",
    })
    add("winning_inner_loop_evaluated", "winning_step_critic", {
        "step": 1,
        "passed": False,
        "recommended_action": "retry",
    })
    add("winning_inner_loop_evaluated", "winning_step_critic", {
        "step": 1,
        "passed": True,
        "recommended_action": "retry",
    })
    add("winning_middle_loop_evaluated", "winning_round_critic", {
        "passed": False,
        "rerun_from_step": 3,
    })
    add("recall_requested", "winning_mechanism", {
        "source_layer": "L2",
        "return_node": "L2",
    })
    add("winning_outer_loop_evaluated", "winning_round_critic", {})

    payload = TestClient(
        create_app(service, event_repository=EventRepository())
    ).get(f"/api/v1/runs/{run.run_id}/interactions?compact=true").json()

    assert payload["workflow"]["execution"] == {
        "mode": "real",
        "provider": "codex",
        "model": "gpt-test",
        "base_url_host": "",
    }
    assert payload["workflow"]["discovery"]["primary_branch"] == "G"
    assert payload["workflow"]["l4"]["replan_required"] is True
    assert payload["workflow"]["l4"]["step_mode_changes"] == [
        {"step": 1, "previous_mode": "skip", "mode": "deep"},
        {"step": 6, "previous_mode": "standard", "mode": "deep"},
    ]
    assert [item["execution_mode"] for item in payload["workflow"]["step_plan"]] == [
        "deep",
        "skip",
        "deep",
        "deep",
        "skip",
        "deep",
    ]
    assert [item["agent_id"] for item in payload["workflow"]["step_plan"]] == [
        "winning_s1_opponent",
        "winning_s2_operations",
        "winning_s3_breakthrough",
        "winning_s4_capability",
        "winning_s5_gap",
        "winning_s6_image",
    ]
    assert [item["status"] for item in payload["workflow"]["step_plan"]] == [
        "completed",
        "skipped",
        "running",
        "pending",
        "skipped",
        "pending",
    ]
    assert payload["workflow"]["step_plan"][0]["middle_cycle"] == 2
    assert [item["backtrack_count"] for item in payload["workflow"]["step_plan"]] == [
        1, 0, 1, 1, 0, 0,
    ]
    assert [item["id"] for item in payload["workflow"]["phases"]] == [
        "blueprint",
        "baseline",
        "convergence",
        "s_agents",
        "audit",
        "report",
    ]
    baseline_phase = next(
        item for item in payload["workflow"]["phases"] if item["id"] == "baseline"
    )
    assert baseline_phase["agent_ids"] == [
        "international_situation",
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
    ]
    assert payload["workflow"]["loops"] == {
        "inner": 2,
        "middle": 1,
        "outer": 1,
        "meta": 1,
    }
    assert "dynamic-opponent-review" in payload["workflow"]["active_agent_ids"]
    assert "winning_s2_operations" not in payload["workflow"]["active_agent_ids"]
    assert "winning_s5_gap" not in payload["workflow"]["active_agent_ids"]
    dynamic = next(
        item for item in payload["agents"]
        if item["agent_id"] == "dynamic-opponent-review"
    )
    assert dynamic["runtime_dynamic"] is True
    assert dynamic["skill_ids"] == ["threat_forecasting"]


def test_auto_branch_is_pending_before_orchestrator_returns_blueprint() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
            "探索无人智能集群条件下的新作战战法及装备需求",
            "auto",
            [],
            2,
            "analyst",
            discovery_branch="auto",
        )
    )

    payload = TestClient(create_app(service)).get(
        f"/api/v1/runs/{run.run_id}/interactions?compact=true"
    ).json()

    assert payload["workflow"]["discovery"]["primary_branch"] == ""
    assert payload["workflow"]["discovery"]["branch_name"] == "Agent 正在分析主分支"


def test_researching_run_shows_blueprint_running_before_first_trace_event() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
            "首个蓝图模型调用期间的流程可视化",
            "auto",
            [],
            2,
            "analyst",
            discovery_branch="auto",
        )
    )
    service.set_status(run.run_id, "researching")

    payload = TestClient(create_app(service)).get(
        f"/api/v1/runs/{run.run_id}/interactions?compact=true"
    ).json()
    phases = {item["id"]: item for item in payload["workflow"]["phases"]}

    assert phases["blueprint"]["status"] == "running"
    assert phases["baseline"]["status"] == "pending"


def test_interaction_workflow_phases_use_full_rows_in_compact_mode() -> None:
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand(
        "Compact workflow projection",
        "new_winning_mechanism",
        [],
        2,
        "analyst",
        discovery_branch="A",
    ))
    captured: list[tuple[str, dict]] = []

    class EventRepository:
        def events_after(self, run_id: str, sequence: int) -> list[dict]:
            return [
                {
                    "run_id": run_id,
                    "sequence": index,
                    "event_type": event_type,
                    "payload": payload,
                }
                for index, (event_type, payload) in enumerate(captured, start=1)
                if index > sequence
            ]

    def add(event_type: str, actor: str, details: dict | None = None) -> None:
        captured.append((event_type, {
            "source": "trace",
            "event": {
                "event_id": f"trace-{len(captured) + 1}",
                "event_type": event_type,
                "actor": actor,
                "summary": event_type,
                "created_at": (
                    f"2026-07-17T00:01:00.{len(captured):06d}+00:00"
                ),
                "input_refs": [],
                "output_refs": [],
                "payload": details or {},
            },
        }))

    add("run_started", "orchestrator", {
        "discovery_blueprint": {"primary_branch": "A"},
    })
    for _ in range(18):
        add("winning_inner_loop_evaluated", "winning_step_critic")
    add("audit_completed", "auditor", {"status": "approved"})
    for _ in range(90):
        add("winning_middle_loop_evaluated", "winning_round_critic")

    payload = TestClient(
        create_app(service, event_repository=EventRepository())
    ).get(f"/api/v1/runs/{run.run_id}/interactions?compact=true").json()

    assert payload["counts"]["events"] > payload["counts"]["visible_events"]
    assert "audit_completed" not in {
        item["event_type"] for item in payload["events"]
    }
    phases = {item["id"]: item for item in payload["workflow"]["phases"]}
    assert phases["audit"]["status"] == "completed"
    assert len(payload["workflow"]["step_plan"]) == 6


def test_api_supports_draft_update_archive_and_history() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/v1/runs",
        json={"topic": "初始主题", "research_route": "auto", "selected_agent_ids": []},
    ).json()
    updated = client.patch(
        f"/api/v1/runs/{created['run_id']}",
        json={
            "topic": "传统场景装备能力缺口",
            "research_route": "traditional_gap",
            "selected_agent_ids": ["weapon_equipment", "operational_employment"],
            "max_rounds": 3,
            "execution": {"mode": "fake"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["topic"] == "传统场景装备能力缺口"
    history = client.get(f"/api/v1/runs/{created['run_id']}/history")
    assert [row["event_type"] for row in history.json()] == [
        "run_created",
        "run_updated",
    ]
    archived = client.delete(f"/api/v1/runs/{created['run_id']}")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get(f"/api/v1/runs/{created['run_id']}/history").json()[-1][
        "event_type"
    ] == "run_archived"


def test_api_previews_bounded_semantic_agent_selection() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/agent-selection-preview",
        json={
            "topic": "西太反介入体系下现役装备作战运用与升级方向",
            "research_route": "auto",
            "discovery_branch": "B",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_agent_ids"] == [
        "international_situation",
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
    ]
    assert len(payload["plan"]) == 4
    assert all(item["reason"] for item in payload["plan"])


def test_api_preview_returns_structured_supplement_handoff() -> None:
    supplement = (
        "如果单发成本降至拦截弹的1/50以下，精确是否还需要高价值目标为前提？"
        "万枚级量产需要哪些能力？火力配系、弹药基数与后勤理论如何变化？"
    )
    response = TestClient(create_app()).post(
        "/api/v1/agent-selection-preview",
        json={
            "topic": "西太高强度对抗中的低成本远程弹药",
            "supplemental_information": supplement,
        },
    )

    assert response.status_code == 200
    brief = response.json()["structured_query_brief"]
    assert brief["supplement_present"] is True
    assert len(brief["supplement_summary"]) <= 1200
    assert "成本交换与效费比" in brief["expansion_dimensions"]
    assert "规模化生产与工业动员" in brief["expansion_dimensions"]
    assert brief["focus_questions"]


def test_capability_api_turns_legacy_labeled_sections_into_primary_portrait() -> None:
    payload = _capability_api_view(
        {
            "capability_type": "upgrade",
            "equipment_category": "现役任务系统",
            "capability_image": (
                "形成低带宽可降级任务网络。"
                "军事价值：维持受扰条件下的任务连续性。"
                "深度机制：通过边缘缓存和多路径重构降低主链路依赖。"
                "前瞻判断：面向智能化干扰持续演化。"
                "新颖性：从单链路增强转向任务网络重构。"
                "证据约束：仅支持方向性判断。"
            ),
            "evidence_ids": ["ev-1"],
            "key_functions": ["旧功能字段"],
            "performance_indicators": ["旧指标字段"],
            "verification_methods": ["旧验证字段"],
        }
    )

    assert payload["deep_capability_portrait"].startswith("形成低带宽可降级任务网络")
    assert "核心不是孤立增加单项性能" in payload["deep_capability_portrait"]
    assert "边缘缓存和多路径重构" in payload["operational_mechanism"]
    assert payload["equipment_form"] == "现役任务系统"
    assert "key_functions" not in payload
    assert "performance_indicators" not in payload
    assert "verification_methods" not in payload


def test_api_rejects_edit_and_archive_after_start() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v1/runs", json={"topic": "已启动任务"}).json()
    client.post(
        f"/api/v1/runs/{created['run_id']}/start",
        headers={"Idempotency-Key": "start-edit-lock"},
    )
    body = {
        "topic": "不允许修改",
        "research_route": "auto",
        "selected_agent_ids": [],
        "max_rounds": 5,
        "execution": {"mode": "fake"},
    }
    assert client.patch(f"/api/v1/runs/{created['run_id']}", json=body).status_code == 409
    assert client.delete(f"/api/v1/runs/{created['run_id']}").status_code == 409
