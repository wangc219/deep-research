import json

from fastapi.testclient import TestClient
from sqlalchemy.exc import NoResultFound

from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService


def _write_artifact_run(root, run_id="swarm-gpt-history", created_at="2026-09-09T10:00:00+00:00"):
    run = root / run_id
    run.mkdir(parents=True)
    (run / "report.md").write_text("# 历史报告\n\n正文", encoding="utf-8")
    (run / "round_summary.json").write_text(
        json.dumps(
            {
                "problem": {
                    "topic": "历史 Query 研究",
                    "research_route": "new_winning_mechanism",
                    "discovery_branch": "G",
                    "interaction_mode": "autonomous",
                    "selected_agent_ids": ["combat_scenario"],
                    "created_at": created_at,
                },
                "provider": {"type": "codex_cli", "model": "gpt-5.5"},
                "agent_models": {
                    "reporter": {"provider": "codex", "model": "gpt-5.5"}
                },
                "mode": "real",
                "resolved_route": "new_winning_mechanism",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (run / "report_quality_gate.json").write_text(
        json.dumps({"overall_score": 0.91, "passed": True}), encoding="utf-8"
    )
    (run / "capability_images.json").write_text("[]", encoding="utf-8")
    (run / "domain.jsonl").write_text("", encoding="utf-8")
    (run / "trace.jsonl").write_text("", encoding="utf-8")
    (run / "branch_deliverables.json").write_text(
        json.dumps({"branch": "G", "products": {}}), encoding="utf-8"
    )


class _NoResultService(ResearchApplicationService):
    """Expose a repository-style missing-row error for API normalization tests."""

    def get_run(self, run_id):
        raise NoResultFound(run_id)


class _TelemetryFailureService(ResearchApplicationService):
    """A service whose diagnostic event sink is unavailable."""

    def get_run(self, run_id):
        # The artifact fallback in create_app supplies the historical view.
        raise NoResultFound(run_id)

    def publish_runtime_event(self, *args, **kwargs):
        raise RuntimeError("event store unavailable")


def test_artifact_only_history_is_listed_and_readable(tmp_path, monkeypatch):
    output_root = tmp_path / "runs"
    _write_artifact_run(output_root)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=ResearchApplicationService()))

    rows = client.get("/api/v1/runs").json()
    row = next(item for item in rows if item["run_id"] == "swarm-gpt-history")
    assert row["topic"] == "历史 Query 研究"
    assert row["execution"]["model"] == "gpt-5.5"
    assert row["execution"]["provider"] == "codex"
    assert row["result"]["historical_artifact"] is True
    assert row["result"]["report_available"] is True
    assert "artifact_root" not in row["result"]

    detail = client.get("/api/v1/runs/swarm-gpt-history/report")
    assert detail.status_code == 200
    assert "历史 Query 研究" in detail.text


def test_artifact_only_history_accepts_expert_feedback(tmp_path, monkeypatch):
    """Feedback must use the same artifact fallback as the read endpoints."""

    output_root = tmp_path / "runs"
    _write_artifact_run(output_root, run_id="artifact-feedback-run")
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=ResearchApplicationService()))

    response = client.post(
        "/api/v1/runs/artifact-feedback-run/expert-feedback",
        headers={"X-Role": "reviewer"},
        json={
            "capability_name": "历史能力画像",
            "comment": "请补充证据边界并明确验证方法。",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["feedback"]["run_id"] == "artifact-feedback-run"
    assert payload["feedback"]["learning_status"] == "processed"
    saved = json.loads(
        (output_root / "artifact-feedback-run" / "expert_feedback.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(saved) == 1

    listed = client.get(
        "/api/v1/runs/artifact-feedback-run/expert-feedback",
        headers={"X-Role": "analyst"},
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["feedback_id"] == payload["feedback"]["feedback_id"]


def test_punctuated_run_id_with_double_dot_is_supported(tmp_path, monkeypatch):
    """Opaque IDs may contain ``..`` without becoming traversal segments."""

    output_root = tmp_path / "runs"
    run_id = "release..1"
    _write_artifact_run(output_root, run_id=run_id)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=ResearchApplicationService()))

    response = client.get(f"/api/v1/runs/{run_id}/expert-feedback")

    assert response.status_code == 200
    assert response.json()["run_id"] == run_id


def test_compact_run_listing_has_artifact_counts_and_pagination(tmp_path, monkeypatch):
    output_root = tmp_path / "runs"
    for index in range(3):
        run_id = f"history-{index}"
        _write_artifact_run(
            output_root,
            run_id=run_id,
            created_at=f"2026-09-0{index + 1}T10:00:00+00:00",
        )
        (output_root / run_id / "capability_images.json").write_text(
            json.dumps([{"name": "能力一"}, {"name": "能力二"}]),
            encoding="utf-8",
        )
        (output_root / run_id / "domain.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {
                        "type": "EvidenceCard",
                        "payload": {"artifact_refs": [f"evidence-{item}" ]},
                    },
                    ensure_ascii=False,
                )
                for item in range(3)
            ),
            encoding="utf-8",
        )

    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=ResearchApplicationService()))

    compact = client.get("/api/v1/runs?compact=true&limit=2")
    assert compact.status_code == 200
    payload = compact.json()
    assert payload["total"] == 3
    assert payload["offset"] == 0
    assert payload["limit"] == 2
    assert payload["has_more"] is True
    assert payload["status_counts"]["completed"] == 3
    assert [item["run_id"] for item in payload["items"]] == ["history-2", "history-1"]
    assert payload["items"][0]["artifact_counts"] == {
        "sources": 0,
        "evidence": 3,
        "capabilities": 2,
        "winning_steps": 0,
        "reports": 1,
    }

    legacy = client.get("/api/v1/runs?compact=true")
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 3


def test_missing_feedback_run_returns_json_404_for_repository_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))
    client = TestClient(create_app(service=_NoResultService()))

    response = client.get("/api/v1/runs/missing/expert-feedback")

    assert response.status_code == 404
    assert response.json() == {"detail": "run not found"}


def test_feedback_remains_successful_when_runtime_event_sink_fails(tmp_path, monkeypatch):
    output_root = tmp_path / "runs"
    _write_artifact_run(output_root, run_id="legacy-feedback")
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=_TelemetryFailureService()))

    response = client.post(
        "/api/v1/runs/legacy-feedback/expert-feedback",
        json={"capability_name": "历史能力", "comment": "需要补充验证边界"},
    )

    assert response.status_code == 201
    assert response.json()["feedback"]["comment"] == "需要补充验证边界"
    rows = json.loads(
        (output_root / "legacy-feedback" / "expert_feedback.json")
        .read_text(encoding="utf-8")
    )
    assert len(rows) == 1


def test_legacy_flat_artifact_directory_is_discovered_without_quality_sidecar(
    tmp_path, monkeypatch
):
    output_root = tmp_path / "runs"
    legacy_root = tmp_path / "legacy-flat"
    _write_artifact_run(tmp_path, run_id="legacy-flat")
    # The helper above writes the report and summary directly below tmp_path;
    # no report-quality gate is present, matching older direct-run output.
    (tmp_path / "legacy-flat" / "report_quality_gate.json").unlink()
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=ResearchApplicationService()))

    rows = client.get("/api/v1/runs").json()

    row = next(item for item in rows if item["run_id"] == legacy_root.name)
    assert row["result"]["historical_artifact"] is True
    assert row["result"]["report_available"] is True


def test_summary_only_directory_is_not_treated_as_a_historical_run(tmp_path, monkeypatch):
    output_root = tmp_path / "runs"
    root = output_root / "incomplete"
    root.mkdir(parents=True)
    (root / "round_summary.json").write_text(
        json.dumps({"problem": {"topic": "未完成"}}), encoding="utf-8"
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=ResearchApplicationService()))

    rows = client.get("/api/v1/runs").json()

    assert all(item["run_id"] != "incomplete" for item in rows)


def test_symlinked_legacy_artifact_directory_is_not_discovered(tmp_path, monkeypatch):
    output_root = tmp_path / "runs"
    external_root = tmp_path / "external"
    _write_artifact_run(external_root, run_id="escaped")
    output_root.mkdir()
    (output_root / "escaped").symlink_to(
        external_root / "escaped", target_is_directory=True
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=ResearchApplicationService()))

    response = client.get("/api/v1/runs/escaped/expert-feedback")

    assert response.status_code == 404


def test_explicit_run_dir_cannot_bind_feedback_to_another_run(
    tmp_path, monkeypatch
):
    output_root = tmp_path / "runs"
    victim = output_root / "victim-run"
    victim.mkdir(parents=True)
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand("path binding", "auto", [], 1, "test")
    )
    service.set_result(run.run_id, {"run_dir": str(victim)})
    service.set_status(run.run_id, "completed")
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=service))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/expert-feedback",
        json={"comment": "不得写入其他任务"},
    )

    assert response.status_code == 404
    assert not (victim / "expert_feedback.json").exists()


def test_feedback_leaf_symlink_is_neither_read_nor_replaced(tmp_path, monkeypatch):
    output_root = tmp_path / "runs"
    run_id = "linked-feedback"
    _write_artifact_run(output_root, run_id=run_id)
    external = tmp_path / "external-feedback.json"
    external.write_text(
        json.dumps([{"feedback_id": "secret", "comment": "不得泄露"}]),
        encoding="utf-8",
    )
    feedback_link = output_root / run_id / "expert_feedback.json"
    feedback_link.symlink_to(external)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=ResearchApplicationService()))

    listed = client.get(f"/api/v1/runs/{run_id}/expert-feedback")
    submitted = client.post(
        f"/api/v1/runs/{run_id}/expert-feedback",
        json={"comment": "不得覆盖链接"},
    )

    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert submitted.status_code == 422
    assert feedback_link.is_symlink()
    assert json.loads(external.read_text(encoding="utf-8")) == [
        {"feedback_id": "secret", "comment": "不得泄露"}
    ]


def test_knowledge_index_leaf_symlink_is_neither_read_nor_written(
    tmp_path, monkeypatch
):
    output_root = tmp_path / "runs"
    run_id = "linked-knowledge"
    _write_artifact_run(output_root, run_id=run_id)
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    external = tmp_path / "external-knowledge.json"
    external.write_text(
        json.dumps([{"feedback_id": "secret", "comment": "不得泄露"}]),
        encoding="utf-8",
    )
    index_link = knowledge_root / "expert-review-feedback.json"
    index_link.symlink_to(external)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service=ResearchApplicationService()))

    listed = client.get("/api/v1/expert-feedback")
    submitted = client.post(
        f"/api/v1/runs/{run_id}/expert-feedback",
        json={"comment": "不得写入链接索引"},
    )

    assert listed.status_code == 200
    assert listed.json() == {"items": [], "count": 0}
    assert submitted.status_code == 422
    assert not (output_root / run_id / "expert_feedback.json").exists()
    assert index_link.is_symlink()
    assert json.loads(external.read_text(encoding="utf-8")) == [
        {"feedback_id": "secret", "comment": "不得泄露"}
    ]
