from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.domain import workspace as workspace_module
from equipment_deep_research.domain.proposals import TraceProposal
from equipment_deep_research.domain.store import SqliteRunStore
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.interfaces import cli
from equipment_deep_research.orchestration.runner import DeepResearchRunner
from equipment_deep_research.tools.artifacts import SecureArtifactStore


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
    workspace.close()


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_workspace_handles_bind_original_run_and_subdirectories(
    tmp_path: Path,
    replacement: str,
) -> None:
    output_root = tmp_path / "runs"
    workspace = RunWorkspace.create(output_root, "run-1")
    original_run = output_root / "bound-run-1"
    workspace.run_dir.rename(original_run)
    attacker_root = tmp_path / "attacker-run"
    attacker_root.mkdir()
    if replacement == "symlink":
        workspace.run_dir.symlink_to(attacker_root, target_is_directory=True)
        replacement_run = attacker_root
    else:
        workspace.run_dir.mkdir()
        replacement_run = workspace.run_dir
    attack_location = replacement_run
    for name in ("agent_sessions", "artifacts", "checkpoints"):
        (replacement_run / name).mkdir()

    run_fd = workspace.dup_run_fd()
    sessions_fd = workspace.dup_sessions_fd()
    database_fd = workspace.dup_database_fd()
    try:
        assert (os.fstat(run_fd).st_dev, os.fstat(run_fd).st_ino) == workspace.run_identity
        workspace.write_run_text("report.md", "bound\n")
        workspace.write_checkpoint_text("latest.json", "{}")
        artifacts = SecureArtifactStore.for_workspace(workspace)
        artifacts.put("artifact", kind="text", meta={"content_type": "text/plain"})
        session = JsonlSessionStore("agent.jsonl", root_fd=sessions_fd)
        session.append({"event_type": "bound"})
        session.close()
        database = SqliteRunStore(
            workspace.database_path,
            run_id="run-1",
            database_fd=database_fd,
        )
        database.commit(
            (),
            (
                TraceProposal(
                    proposal_id="bound-trace",
                    event_type="bound",
                    actor="test",
                    payload={"bound": True},
                ),
            ),
        )
        database.close()
    finally:
        os.close(run_fd)
        os.close(sessions_fd)
        os.close(database_fd)
        workspace.close()

    assert (original_run / "report.md").read_text(encoding="utf-8") == "bound\n"
    assert (original_run / "checkpoints" / "latest.json").is_file()
    assert list((original_run / "artifacts").glob("*.meta.json"))
    assert (original_run / "agent_sessions" / "agent.jsonl").is_file()
    assert (original_run / "run.db").is_file()
    assert [path for path in attack_location.rglob("*") if path.is_file()] == []


def test_workspace_close_invalidates_handle_duplication(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    run_fd = workspace.dup_run_fd()

    workspace.close()

    with pytest.raises(RuntimeError, match="closed"):
        workspace.dup_run_fd()
    os.fstat(run_fd)
    os.close(run_fd)


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_workspace_subdirectory_handles_ignore_replacement_paths(
    tmp_path: Path,
    replacement: str,
) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "run-1")
    bound_directories: dict[str, Path] = {}
    attacker_directories: dict[str, Path] = {}
    for name in ("agent_sessions", "artifacts", "checkpoints"):
        current = workspace.run_dir / name
        bound = workspace.run_dir / f"bound-{name}"
        current.rename(bound)
        attacker = tmp_path / f"attacker-{name}"
        attacker.mkdir()
        if replacement == "symlink":
            current.symlink_to(attacker, target_is_directory=True)
        else:
            current.mkdir()
            attacker = current
        bound_directories[name] = bound
        attacker_directories[name] = attacker

    workspace.write_checkpoint_text("latest.json", "{}")
    SecureArtifactStore.for_workspace(workspace).put(
        "artifact",
        kind="text",
        meta={"content_type": "text/plain"},
    )
    sessions_fd = workspace.dup_sessions_fd()
    try:
        session = JsonlSessionStore("agent.jsonl", root_fd=sessions_fd)
    finally:
        os.close(sessions_fd)
    session.append({"event_type": "bound"})
    session.close()
    workspace.close()

    assert (bound_directories["checkpoints"] / "latest.json").is_file()
    assert list(bound_directories["artifacts"].glob("*.meta.json"))
    assert (bound_directories["agent_sessions"] / "agent.jsonl").is_file()
    for attacker in attacker_directories.values():
        assert [path for path in attacker.rglob("*") if path.is_file()] == []


def test_runner_closes_workspace_handles_when_hook_raises(tmp_path: Path) -> None:
    captured: list[RunWorkspace] = []

    def fail_after_create(event: str, workspace: RunWorkspace) -> None:
        if event == "after_workspace_created":
            captured.append(workspace)
            raise RuntimeError("stop after create")

    with pytest.raises(RuntimeError, match="stop after create"):
        _runner(tmp_path, run_hook=fail_after_create).run(
            mode="fake",
            topic="handle cleanup",
            research_route="auto",
            run_id="cleanup-run",
        )

    assert len(captured) == 1
    with pytest.raises(RuntimeError, match="closed"):
        captured[0].dup_run_fd()


@pytest.mark.parametrize(
    ("root_name", "leaf"),
    [
        ("run", "report.md"),
        ("run", "domain.jsonl"),
        ("checkpoints", "latest.json"),
    ],
)
def test_workspace_atomic_writer_rejects_leaf_symlink_without_touching_external(
    tmp_path: Path,
    root_name: str,
    leaf: str,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    external = tmp_path / f"external-{leaf}"
    external.write_text("external\n", encoding="utf-8")
    root = workspace.run_dir if root_name == "run" else workspace.checkpoints_dir
    (root / leaf).symlink_to(external)

    with pytest.raises(ValueError, match="symlink"):
        if root_name == "run":
            workspace.write_run_text(leaf, "replacement\n")
        else:
            workspace.write_checkpoint_text(leaf, "replacement\n")

    assert external.read_text(encoding="utf-8") == "external\n"


@pytest.mark.parametrize(
    ("root_name", "leaf"),
    [
        ("run", "report.md"),
        ("run", "domain.jsonl"),
        ("checkpoints", "latest.json"),
    ],
)
def test_workspace_atomic_writer_replaces_checked_leaf_without_following_race_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root_name: str,
    leaf: str,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    external = tmp_path / f"external-race-{leaf}"
    external.write_text("external\n", encoding="utf-8")
    root = workspace.run_dir if root_name == "run" else workspace.checkpoints_dir
    target = root / leaf
    target.write_text("old\n", encoding="utf-8")
    real_rename = os.rename

    def racing_rename(
        src: str,
        dst: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        assert dst == leaf
        target.unlink()
        target.symlink_to(external)
        real_rename(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(workspace_module.os, "rename", racing_rename)
    if root_name == "run":
        workspace.write_run_text(leaf, "replacement\n")
    else:
        workspace.write_checkpoint_text(leaf, "replacement\n")

    assert external.read_text(encoding="utf-8") == "external\n"
    assert target.read_text(encoding="utf-8") == "replacement\n"


def test_workspace_writer_fails_closed_without_secure_primitives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    monkeypatch.setattr(workspace_module.os, "supports_dir_fd", set())

    with pytest.raises(RuntimeError, match="secure workspace path operations"):
        workspace.write_run_text("report.md", "blocked\n")

    assert not (workspace.run_dir / "report.md").exists()


def test_workspace_create_fails_closed_before_creating_root_without_dirfd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "blocked-runs"
    monkeypatch.setattr(workspace_module.os, "supports_dir_fd", set())

    with pytest.raises(RuntimeError, match="secure workspace path operations"):
        RunWorkspace.create(output_root, "run-1")

    assert not output_root.exists()


def test_workspace_safe_stat_rejects_leaf_replaced_after_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    target = workspace.run_dir / "report.md"
    target.write_text("report\n", encoding="utf-8")
    external = tmp_path / "external-stat-report.md"
    external.write_text("external\n", encoding="utf-8")
    real_open_at = workspace_module._open_at

    def racing_open_at(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int,
    ) -> int:
        if path == "report.md":
            target.unlink()
            target.symlink_to(external)
        return real_open_at(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(workspace_module, "_open_at", racing_open_at)

    with pytest.raises(ValueError, match="symlink"):
        workspace.run_file_is_regular("report.md")

    assert external.read_text(encoding="utf-8") == "external\n"


@pytest.mark.parametrize(
    "run_id",
    [
        "/tmp/equipment-dr-absolute-escape",
        ".",
        "..",
        "../equipment-dr-parent-escape",
        "nested/run",
        r"nested\run",
    ],
)
def test_workspace_rejects_run_id_path_escape(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ValueError, match="run_id"):
        RunWorkspace.create(tmp_path, run_id)


def test_workspace_allows_double_dot_inside_run_id(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path, "release..1")

    assert workspace.run_dir == tmp_path / "release..1"
    assert workspace.run_dir.is_dir()


def test_workspace_rejects_preexisting_empty_run_directory(tmp_path: Path) -> None:
    (tmp_path / "existing-empty").mkdir()

    with pytest.raises(FileExistsError):
        RunWorkspace.create(tmp_path, "existing-empty")


def test_workspace_rejects_symlink_escape_without_modifying_target(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    output_root.mkdir()
    external_target = tmp_path / "external-target"
    external_target.mkdir()
    marker = external_target / "marker.txt"
    marker.write_text("unchanged\n", encoding="utf-8")
    (output_root / "escape").symlink_to(external_target, target_is_directory=True)

    with pytest.raises(FileExistsError):
        RunWorkspace.create(output_root, "escape")

    assert marker.read_text(encoding="utf-8") == "unchanged\n"
    assert {path.name for path in external_target.iterdir()} == {"marker.txt"}


def test_runner_rejects_reused_run_id_before_writing(tmp_path: Path) -> None:
    run_id = "reused-run"
    first = _runner(tmp_path).run(
        mode="fake",
        topic="first run",
        research_route="auto",
        run_id=run_id,
    )
    run_dir = Path(first["run_dir"])
    original_files = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    original_directories = {
        path.relative_to(run_dir)
        for path in run_dir.rglob("*")
        if path.is_dir()
    }

    with pytest.raises(FileExistsError):
        _runner(tmp_path).run(
            mode="fake",
            topic="second run",
            research_route="auto",
            run_id=run_id,
            agent_ids=["weapon_equipment"],
        )

    assert {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    } == original_files
    assert {
        path.relative_to(run_dir)
        for path in run_dir.rglob("*")
        if path.is_dir()
    } == original_directories
    assert {
        "report.md",
        "capability_images.json",
        "round_summary.json",
        "domain.jsonl",
        "trace.jsonl",
        "agent_sessions",
        "artifacts",
    } <= {path.name for path in run_dir.iterdir()}


def test_runner_uses_default_provider_and_evidence_configs(tmp_path: Path) -> None:
    runner = _runner(tmp_path)

    assert runner.provider_config_path == ROOT / "configs" / "equipment_deep_research" / "providers.yaml"
    assert runner.evidence_config_path == ROOT / "configs" / "equipment_deep_research" / "evidence.yaml"


def test_runner_allows_omitted_new_configs_for_custom_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "minimal-project"
    project_root.mkdir()

    runner = DeepResearchRunner(
        project_root=project_root,
        output_root=tmp_path / "runs",
        agent_config_path=ROOT / "configs" / "equipment_deep_research" / "agents.yaml",
        preset_config_path=ROOT / "configs" / "equipment_deep_research" / "presets.yaml",
    )

    assert runner.provider_config_path == (
        project_root / "configs" / "equipment_deep_research" / "providers.yaml"
    )
    assert runner.evidence_config_path == (
        project_root / "configs" / "equipment_deep_research" / "evidence.yaml"
    )


@pytest.mark.parametrize("config_name", ["provider_config_path", "evidence_config_path"])
def test_runner_rejects_missing_new_config_paths(tmp_path: Path, config_name: str) -> None:
    missing_path = tmp_path / f"missing-{config_name}.yaml"

    with pytest.raises(FileNotFoundError, match=str(missing_path)):
        _runner(tmp_path, **{config_name: missing_path})


def test_runner_resume_requires_an_existing_run(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="run directory does not exist"):
        _runner(tmp_path).run(
            mode="fake",
            topic="resume test",
            research_route="auto",
            run_id="resume-test",
            resume=True,
        )

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


def test_cli_exposes_provider_and_evidence_controls_without_domain_gate() -> None:
    parser_text = (ROOT / "src" / "equipment_deep_research" / "interfaces" / "cli.py").read_text(
        encoding="utf-8"
    )

    assert "--source-whitelist" not in parser_text
    assert "--provider-config" in parser_text
    assert "--evidence-config" in parser_text
    assert "--resume" in parser_text
    assert "--analyst-confirmed" in parser_text
