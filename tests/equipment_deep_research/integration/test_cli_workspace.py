from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.interfaces import cli
from equipment_deep_research.orchestration.runner import DeepResearchRunner


ROOT = Path(__file__).resolve().parents[3]


def _runner(tmp_path: Path, **overrides: Any) -> DeepResearchRunner:
    kwargs = {
        "project_root": ROOT,
        "output_root": tmp_path,
        "agent_config_path": ROOT / "configs" / "equipment_deep_research" / "agents.yaml",
        "preset_config_path": ROOT / "configs" / "equipment_deep_research" / "presets.yaml",
    }
    kwargs.update(overrides)
    return DeepResearchRunner(**kwargs)


def test_workspace_creates_required_paths(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")

    assert workspace.run_dir == tmp_path / "run-1"
    assert workspace.sessions_dir.is_dir()
    assert workspace.artifacts_dir.is_dir()
    assert workspace.checkpoints_dir.is_dir()
    assert workspace.database_path == workspace.run_dir / "run.db"


@pytest.mark.parametrize(
    "run_id",
    [
        "/tmp/equipment-dr-absolute-escape",
        "..",
        "../equipment-dr-parent-escape",
        "nested/run",
        r"nested\run",
    ],
)
def test_workspace_rejects_run_id_path_escape(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ValueError, match="run_id"):
        RunWorkspace.create(tmp_path, run_id)


def test_runner_uses_default_provider_and_evidence_configs(tmp_path: Path) -> None:
    runner = _runner(tmp_path)

    assert runner.provider_config_path == ROOT / "configs" / "equipment_deep_research" / "providers.yaml"
    assert runner.evidence_config_path == ROOT / "configs" / "equipment_deep_research" / "evidence.yaml"


@pytest.mark.parametrize("config_name", ["provider_config_path", "evidence_config_path"])
def test_runner_rejects_missing_new_config_paths(tmp_path: Path, config_name: str) -> None:
    missing_path = tmp_path / f"missing-{config_name}.yaml"

    with pytest.raises(FileNotFoundError, match=str(missing_path)):
        _runner(tmp_path, **{config_name: missing_path})


def test_runner_resume_is_explicitly_deferred(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError) as exc_info:
        _runner(tmp_path).run(
            mode="fake",
            topic="resume test",
            research_route="auto",
            run_id="resume-test",
            resume=True,
        )

    assert exc_info.value.args == ("resume is enabled in Phase 1",)
    assert not (tmp_path / "resume-test").exists()


def test_analyst_confirmation_is_recorded_in_trace_and_summary(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="analyst confirmation test",
        research_route="auto",
        run_id="analyst-confirmed",
        analyst_confirmed=True,
    )

    run_dir = Path(result["run_dir"])
    trace_rows = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    run_started = next(
        row["payload"] for row in trace_rows if row["payload"]["event_type"] == "run_started"
    )
    summary = json.loads((run_dir / "round_summary.json").read_text(encoding="utf-8"))
    assert run_started["payload"]["analyst_confirmed"] is True
    assert summary["analyst_confirmed"] is True


def test_runner_keeps_seven_artifact_names_and_adds_checkpoints(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="workspace artifact test",
        research_route="auto",
        run_id="artifact-contract",
    )

    run_dir = Path(result["run_dir"])
    expected = {
        "report.md",
        "capability_images.json",
        "round_summary.json",
        "domain.jsonl",
        "trace.jsonl",
        "agent_sessions",
        "artifacts",
        "checkpoints",
    }
    assert expected <= {path.name for path in run_dir.iterdir()}


def test_cli_passes_new_configuration_and_run_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_config = tmp_path / "providers.yaml"
    evidence_config = tmp_path / "evidence.yaml"
    provider_config.write_text("providers: {}\n", encoding="utf-8")
    evidence_config.write_text("acceptance: {}\n", encoding="utf-8")
    calls: dict[str, dict[str, Any]] = {}

    class RecordingRunner:
        def __init__(self, **kwargs: Any) -> None:
            calls["init"] = kwargs

        def run(self, **kwargs: Any) -> dict[str, Any]:
            calls["run"] = kwargs
            return {
                "run_dir": str(tmp_path / "cli-run"),
                "route": "traditional_gap",
                "audit_status": "passed",
                "report_path": str(tmp_path / "cli-run" / "report.md"),
                "capability_images_path": str(tmp_path / "cli-run" / "capability_images.json"),
                "summary_path": str(tmp_path / "cli-run" / "round_summary.json"),
            }

    monkeypatch.setattr(cli, "DeepResearchRunner", RecordingRunner)

    exit_code = cli.main(
        [
            "--mode",
            "fake",
            "--topic",
            "CLI test",
            "--provider-config",
            str(provider_config),
            "--evidence-config",
            str(evidence_config),
            "--resume",
            "--analyst-confirmed",
        ]
    )

    assert exit_code == 0
    assert calls["init"]["provider_config_path"] == provider_config
    assert calls["init"]["evidence_config_path"] == evidence_config
    assert calls["run"]["resume"] is True
    assert calls["run"]["analyst_confirmed"] is True


def test_cli_no_longer_exposes_source_whitelist() -> None:
    parser_text = (ROOT / "src" / "equipment_deep_research" / "interfaces" / "cli.py").read_text(
        encoding="utf-8"
    )

    assert "--source-whitelist" not in parser_text
    assert "--provider-config" in parser_text
    assert "--evidence-config" in parser_text
    assert "--resume" in parser_text
    assert "--analyst-confirmed" in parser_text
