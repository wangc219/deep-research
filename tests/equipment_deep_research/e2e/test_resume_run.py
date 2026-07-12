from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable

import pytest

from equipment_deep_research.agents.provider import (
    AgentProvider,
    AgentRunRequest,
    AgentRunResult,
    FakeAgentProvider,
)
from equipment_deep_research.domain.store import SqliteRunStore
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.harness.recovery import RecoveryError
from equipment_deep_research.harness import recovery as recovery_module
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.orchestration.runner import DeepResearchRunner


ROOT = Path(__file__).resolve().parents[3]
AGENTS = ["international_situation", "combat_scenario", "weapon_equipment"]
FINALIZE_TASK = "finalize:winning-report"


class InjectedCrash(RuntimeError):
    pass


class RecordingProvider:
    def __init__(self, *, crash_on_call: int | None = None) -> None:
        self.delegate = FakeAgentProvider()
        self.crash_on_call = crash_on_call
        self.calls: list[str] = []

    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        self.calls.append(request.agent.agent_id)
        if self.crash_on_call == len(self.calls):
            raise InjectedCrash(f"crash on {request.agent.agent_id}")
        return self.delegate.run_baseline_agent(request)


class RejectingProvider:
    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        raise AssertionError(f"completed run repeated {request.agent.agent_id}")


class FailSavepointOnceSession(JsonlSessionStore):
    failed = False

    def append(self, record: dict[str, Any]) -> None:
        if record.get("event_type") == "savepoint" and not type(self).failed:
            type(self).failed = True
            raise OSError("injected savepoint append failure")
        super().append(record)


class SessionSymlinkProvider:
    def __init__(self, session_path: Path, external: Path) -> None:
        self.delegate = FakeAgentProvider()
        self.session_path = session_path
        self.external = external

    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        self.session_path.symlink_to(self.external)
        return self.delegate.run_baseline_agent(request)


class ArtifactDirectorySymlinkProvider:
    def __init__(self, artifacts_dir: Path, external: Path) -> None:
        self.delegate = FakeAgentProvider()
        self.artifacts_dir = artifacts_dir
        self.external = external

    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        self.artifacts_dir.rmdir()
        self.artifacts_dir.symlink_to(self.external, target_is_directory=True)
        return self.delegate.run_baseline_agent(request)


def build_runner(
    tmp_path: Path,
    *,
    provider: AgentProvider | None = None,
    preset_config_path: Path | None = None,
    run_hook: Callable[[str, RunWorkspace], None] | None = None,
    session_store_factory: Callable[[str, Path], Any] | None = None,
) -> DeepResearchRunner:
    return DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=ROOT / "configs" / "equipment_deep_research" / "agents.yaml",
        preset_config_path=preset_config_path
        or ROOT / "configs" / "equipment_deep_research" / "presets.yaml",
        provider=provider,
        run_hook=run_hook,
        session_store_factory=session_store_factory,
    )


def run_args(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "mode": "fake",
        "topic": "checkpoint resume test",
        "research_route": "new_winning_mechanism",
        "run_id": "resume-1",
        "agent_ids": list(AGENTS),
    }
    values.update(overrides)
    return values


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def session_bytes(run_dir: Path, agent_id: str) -> bytes:
    return (run_dir / "agent_sessions" / f"{agent_id}.jsonl").read_bytes()


def install_output_root_replacement(
    output_root: Path,
    *,
    replacement: str,
    attacker_root: Path,
    bound_root: Path,
    run_id: str,
) -> None:
    output_root.rename(bound_root)
    attacker_root.mkdir()
    if replacement == "symlink":
        output_root.symlink_to(attacker_root, target_is_directory=True)
        replacement_root = attacker_root
    else:
        output_root.mkdir()
        replacement_root = output_root
    replacement_run = replacement_root / run_id
    replacement_run.mkdir()
    for name in ("agent_sessions", "artifacts", "checkpoints"):
        (replacement_run / name).mkdir()


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_fresh_run_stays_on_bound_output_root_after_path_replacement(
    tmp_path: Path,
    replacement: str,
) -> None:
    output_root = tmp_path / "runs"
    attacker_root = tmp_path / "attacker-output"
    bound_root = tmp_path / "bound-output"
    captured_identity: list[tuple[int, int]] = []

    def replace_root(event: str, workspace: RunWorkspace) -> None:
        if event != "after_workspace_created":
            return
        captured_identity.append(workspace.run_identity)
        install_output_root_replacement(
            output_root,
            replacement=replacement,
            attacker_root=attacker_root,
            bound_root=bound_root,
            run_id="resume-1",
        )
        run_fd = workspace.dup_run_fd()
        try:
            assert (os.fstat(run_fd).st_dev, os.fstat(run_fd).st_ino) == captured_identity[0]
        finally:
            os.close(run_fd)

    result = build_runner(
        tmp_path,
        provider=RecordingProvider(),
        run_hook=replace_root,
    ).run(**run_args(agent_ids=AGENTS[:1]))

    assert result["status"] == "completed"
    bound_run = bound_root / "resume-1"
    for leaf in (
        "report.md",
        "capability_images.json",
        "round_summary.json",
        "domain.jsonl",
        "trace.jsonl",
        "run.db",
    ):
        assert (bound_run / leaf).is_file()
    assert list((bound_run / "artifacts").glob("*.meta.json"))
    assert (bound_run / "agent_sessions" / f"{AGENTS[0]}.jsonl").is_file()
    assert (bound_run / "checkpoints" / "latest.json").is_file()
    assert not (bound_run / "run.db-wal").exists()
    assert not (bound_run / "run.db-shm").exists()
    attack_location = attacker_root if replacement == "symlink" else output_root
    assert [path for path in attack_location.rglob("*") if path.is_file()] == []


def test_resume_continues_after_last_committed_agent_savepoint(tmp_path: Path) -> None:
    crashing = RecordingProvider(crash_on_call=2)
    with pytest.raises(InjectedCrash, match="combat_scenario"):
        build_runner(tmp_path, provider=crashing).run(**run_args())

    run_dir = tmp_path / "runs" / "resume-1"
    database = SqliteRunStore(run_dir / "run.db", run_id="resume-1")
    assert database.count("EvidenceCard") == 1
    assert database.count("BaselineFindingPacket") == 1
    assert database.count("RunCheckpoint") == 1
    first_session_prefix = session_bytes(run_dir, AGENTS[0])

    completing = RecordingProvider()
    resumed = build_runner(tmp_path, provider=completing).run(
        **run_args(resume=True)
    )

    assert resumed["status"] == "completed"
    assert completing.calls == AGENTS[1:]
    assert session_bytes(run_dir, AGENTS[0]) == first_session_prefix
    domain_rows = jsonl_rows(run_dir / "domain.jsonl")
    evidence_ids = [
        row["payload"]["evidence_id"]
        for row in domain_rows
        if row["type"] == "EvidenceCard"
    ]
    assert len(evidence_ids) == len(AGENTS)
    assert len(set(evidence_ids)) == len(evidence_ids)
    trace_types = [
        row["payload"]["event_type"] for row in jsonl_rows(run_dir / "trace.jsonl")
    ]
    assert trace_types.count("run_resumed") == 1
    checkpoint = json.loads(
        (run_dir / "checkpoints" / "latest.json").read_text(encoding="utf-8")
    )["checkpoint"]
    assert checkpoint["status"] == "completed"
    assert checkpoint["pending_task_ids"] == []
    assert checkpoint["completed_task_ids"] == [
        *[f"baseline:{agent_id}" for agent_id in AGENTS],
        FINALIZE_TASK,
    ]
    assert checkpoint["round_index"] == 1
    assert checkpoint["budget_remaining"]["baseline_tasks"] == 0
    summary = json.loads((run_dir / "round_summary.json").read_text(encoding="utf-8"))
    assert len(summary["source_materials"]) == len(AGENTS)
    assert [row["agent_id"] for row in summary["worker_reports"]] == AGENTS


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"topic": "different topic"}, "topic"),
        ({"research_route": "traditional_gap"}, "route"),
        ({"agent_ids": AGENTS[:2]}, "agent"),
        ({"max_rounds": 99}, "configuration"),
    ],
)
def test_resume_rejects_run_identity_mismatch(
    tmp_path: Path,
    overrides: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(InjectedCrash):
        build_runner(tmp_path, provider=RecordingProvider(crash_on_call=2)).run(
            **run_args()
        )

    with pytest.raises(RecoveryError, match=message):
        build_runner(tmp_path, provider=RecordingProvider()).run(
            **run_args(resume=True, **overrides)
        )


def test_failed_recovery_closes_bound_workspace_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(InjectedCrash):
        build_runner(tmp_path, provider=RecordingProvider(crash_on_call=2)).run(
            **run_args()
        )
    captured: list[RunWorkspace] = []
    original_open_existing = RunWorkspace.open_existing

    def capture_open(
        cls: type[RunWorkspace],
        output_root: str | Path,
        run_id: str,
    ) -> RunWorkspace:
        workspace = original_open_existing(output_root, run_id)
        captured.append(workspace)
        return workspace

    monkeypatch.setattr(
        recovery_module.RunWorkspace,
        "open_existing",
        classmethod(capture_open),
    )

    with pytest.raises(RecoveryError, match="topic"):
        build_runner(tmp_path, provider=RecordingProvider()).run(
            **run_args(topic="different topic", resume=True)
        )

    assert len(captured) == 1
    with pytest.raises(RuntimeError, match="closed"):
        captured[0].dup_run_fd()


def test_resume_rejects_missing_and_corrupt_runs(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_runner(tmp_path).run(**run_args(run_id="missing", resume=True))

    workspace = RunWorkspace.create(tmp_path / "runs", "corrupt")
    workspace.database_path.write_bytes(b"not a sqlite database")

    with pytest.raises(RecoveryError, match="SQLite"):
        build_runner(tmp_path).run(**run_args(run_id="corrupt", resume=True))


def test_resume_rejects_internally_inconsistent_checkpoint(tmp_path: Path) -> None:
    with pytest.raises(InjectedCrash):
        build_runner(tmp_path, provider=RecordingProvider(crash_on_call=2)).run(
            **run_args()
        )

    database_path = tmp_path / "runs" / "resume-1" / "run.db"
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute(
            """
            SELECT payload_json
            FROM domain_objects
            WHERE run_id = ? AND object_type = 'RunCheckpoint'
            """,
            ("resume-1",),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["completed_task_ids"] = []
        connection.execute(
            """
            UPDATE domain_objects
            SET payload_json = ?
            WHERE run_id = ? AND object_type = 'RunCheckpoint'
            """,
            (json.dumps(payload), "resume-1"),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RecoveryError, match="RunCheckpoint"):
        build_runner(tmp_path, provider=RecordingProvider()).run(
            **run_args(resume=True)
        )


def test_open_existing_rejects_top_level_symlink_escape(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "unsafe")
    workspace.database_path.touch()
    external = tmp_path / "external"
    external.mkdir()
    workspace.artifacts_dir.rmdir()
    workspace.artifacts_dir.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        RunWorkspace.open_existing(tmp_path / "runs", "unsafe")


def test_completed_resume_is_idempotent_and_does_not_run_provider(tmp_path: Path) -> None:
    first = build_runner(tmp_path, provider=RecordingProvider()).run(**run_args())
    run_dir = Path(first["run_dir"])
    database = SqliteRunStore(run_dir / "run.db", run_id="resume-1")
    before = database.recover()
    session_prefixes = {agent_id: session_bytes(run_dir, agent_id) for agent_id in AGENTS}
    trace_before = database.trace_count()

    resumed = build_runner(tmp_path, provider=RejectingProvider()).run(
        **run_args(resume=True)
    )

    assert resumed["status"] == "completed"
    after = database.recover()
    assert after["trace_count"] == trace_before + 1
    assert after["last_checkpoint"] != before["last_checkpoint"]
    assert database.trace_events()[-1]["event_type"] == "run_resumed"
    assert {
        agent_id: session_bytes(run_dir, agent_id) for agent_id in AGENTS
    } == session_prefixes


def test_completed_resume_rewrites_stable_outputs_from_sqlite(tmp_path: Path) -> None:
    first = build_runner(tmp_path, provider=RecordingProvider()).run(
        **run_args(agent_ids=AGENTS[:1])
    )
    run_dir = Path(first["run_dir"])
    for leaf in (
        "report.md",
        "capability_images.json",
        "round_summary.json",
        "domain.jsonl",
        "trace.jsonl",
    ):
        (run_dir / leaf).write_text("stale\n", encoding="utf-8")

    resumed = build_runner(tmp_path, provider=RejectingProvider()).run(
        **run_args(agent_ids=AGENTS[:1], resume=True)
    )

    assert resumed["status"] == "completed"
    database = SqliteRunStore(run_dir / "run.db", run_id="resume-1")
    trace_payloads = [row["payload"] for row in jsonl_rows(run_dir / "trace.jsonl")]
    assert trace_payloads == [row["payload"] for row in database.trace_events()]
    assert trace_payloads[-1]["event_type"] == "run_resumed"
    summary = json.loads((run_dir / "round_summary.json").read_text(encoding="utf-8"))
    assert len(summary["trace_summary"]) == database.trace_count()
    assert summary["trace_summary"][-1]["event_type"] == "run_resumed"
    assert json.loads((run_dir / "capability_images.json").read_text(encoding="utf-8"))
    assert jsonl_rows(run_dir / "domain.jsonl")
    assert (run_dir / "report.md").read_text(encoding="utf-8") != "stale\n"


def test_real_session_savepoint_failure_is_reconciled_before_skipping_completed(
    tmp_path: Path,
) -> None:
    FailSavepointOnceSession.failed = False

    def session_factory(path: str, root_dir: Path) -> FailSavepointOnceSession:
        return FailSavepointOnceSession(path, root_dir=root_dir)

    with pytest.raises(OSError, match="savepoint append failure"):
        build_runner(
            tmp_path,
            provider=RecordingProvider(),
            session_store_factory=session_factory,
        ).run(**run_args(agent_ids=AGENTS[:1]))

    run_dir = tmp_path / "runs" / "resume-1"
    store = SqliteRunStore(run_dir / "run.db", run_id="resume-1")
    unresolved = store.recover()["unresolved_session_writes"]
    assert len(unresolved) == 1
    marker = unresolved[0]
    session = JsonlSessionStore(
        marker["session_ref"], root_dir=run_dir / "agent_sessions"
    )
    assert [row["event_type"] for row in session.read_all()] == ["baseline_result"]

    resumed = build_runner(tmp_path, provider=RejectingProvider()).run(
        **run_args(agent_ids=AGENTS[:1], resume=True)
    )

    assert resumed["status"] == "completed"
    events = store.trace_events()
    event_types = [event["event_type"] for event in events]
    assert event_types.index("session_reconciled") < event_types.index("run_resumed")
    reconciled = session.read_all()
    assert [
        row["event_type"]
        for row in reconciled
        if row.get("reconciliation_marker_id") == marker["marker_id"]
    ] == ["savepoint", "session_reconciled"]
    assert [row["payload"] for row in jsonl_rows(run_dir / "trace.jsonl")] == [
        row["payload"] for row in store.trace_events()
    ]
    assert store.recover()["unresolved_session_writes"] == []
    reconciled_line_count = len(reconciled)

    build_runner(tmp_path, provider=RejectingProvider()).run(
        **run_args(agent_ids=AGENTS[:1], resume=True)
    )

    assert len(session.read_all()) == reconciled_line_count
    assert len(
        [
            event
            for event in store.trace_events()
            if event["event_type"] == "session_reconciled"
        ]
    ) == 1


def test_reconciliation_fails_before_external_write_if_sessions_dir_changes_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FailSavepointOnceSession.failed = False

    def session_factory(path: str, root_dir: Path) -> FailSavepointOnceSession:
        return FailSavepointOnceSession(path, root_dir=root_dir)

    with pytest.raises(OSError, match="savepoint append failure"):
        build_runner(
            tmp_path,
            provider=RecordingProvider(),
            session_store_factory=session_factory,
        ).run(**run_args(agent_ids=AGENTS[:1]))

    run_dir = tmp_path / "runs" / "resume-1"
    sessions_dir = run_dir / "agent_sessions"
    external = tmp_path / "external-sessions"
    external.mkdir()
    original_open_existing = RunWorkspace.open_existing

    def replace_after_open(
        cls: type[RunWorkspace],
        output_root: str | Path,
        run_id: str,
    ) -> RunWorkspace:
        workspace = original_open_existing(output_root, run_id)
        for child in sessions_dir.iterdir():
            child.unlink()
        sessions_dir.rmdir()
        sessions_dir.symlink_to(external, target_is_directory=True)
        return workspace

    monkeypatch.setattr(
        recovery_module.RunWorkspace,
        "open_existing",
        classmethod(replace_after_open),
    )

    with pytest.raises(RecoveryError, match="reconciliation session"):
        build_runner(tmp_path, provider=RejectingProvider()).run(
            **run_args(agent_ids=AGENTS[:1], resume=True)
        )

    assert list(external.iterdir()) == []


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_resume_reconciliation_stays_on_bound_root_after_open_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    FailSavepointOnceSession.failed = False

    def session_factory(path: str, root_dir: Path) -> FailSavepointOnceSession:
        return FailSavepointOnceSession(path, root_dir=root_dir)

    with pytest.raises(OSError, match="savepoint append failure"):
        build_runner(
            tmp_path,
            provider=RecordingProvider(),
            session_store_factory=session_factory,
        ).run(**run_args(agent_ids=AGENTS[:1]))

    output_root = tmp_path / "runs"
    attacker_root = tmp_path / "attacker-resume"
    bound_root = tmp_path / "bound-resume"
    original_open_existing = RunWorkspace.open_existing

    def replace_after_open(
        cls: type[RunWorkspace],
        requested_root: str | Path,
        run_id: str,
    ) -> RunWorkspace:
        workspace = original_open_existing(requested_root, run_id)
        install_output_root_replacement(
            output_root,
            replacement=replacement,
            attacker_root=attacker_root,
            bound_root=bound_root,
            run_id=run_id,
        )
        return workspace

    monkeypatch.setattr(
        recovery_module.RunWorkspace,
        "open_existing",
        classmethod(replace_after_open),
    )

    resumed = build_runner(tmp_path, provider=RejectingProvider()).run(
        **run_args(agent_ids=AGENTS[:1], resume=True)
    )

    assert resumed["status"] == "completed"
    bound_run = bound_root / "resume-1"
    bound_store = SqliteRunStore(bound_run / "run.db", run_id="resume-1")
    assert bound_store.recover()["unresolved_session_writes"] == []
    bound_event_types = [event["event_type"] for event in bound_store.trace_events()]
    assert bound_event_types.index("session_reconciled") < bound_event_types.index(
        "run_resumed"
    )
    bound_store.close()
    assert (bound_run / "report.md").is_file()
    assert (bound_run / "checkpoints" / "latest.json").is_file()
    assert not (bound_run / "run.db-wal").exists()
    assert not (bound_run / "run.db-shm").exists()
    attack_location = attacker_root if replacement == "symlink" else output_root
    assert [path for path in attack_location.rglob("*") if path.is_file()] == []


def test_fresh_run_still_rejects_existing_run_name_without_mutation(tmp_path: Path) -> None:
    first = build_runner(tmp_path, provider=RecordingProvider()).run(**run_args())
    run_dir = Path(first["run_dir"])
    database_before = (run_dir / "run.db").read_bytes()

    with pytest.raises(FileExistsError):
        build_runner(tmp_path, provider=RecordingProvider()).run(**run_args())

    assert (run_dir / "run.db").read_bytes() == database_before


def test_run_database_contains_one_completed_checkpoint(tmp_path: Path) -> None:
    result = build_runner(tmp_path, provider=RecordingProvider()).run(**run_args())
    run_dir = Path(result["run_dir"])
    connection = sqlite3.connect(run_dir / "run.db")
    try:
        row = connection.execute(
            """
            SELECT payload_json
            FROM domain_objects
            WHERE run_id = ? AND object_type = 'RunCheckpoint'
            """,
            ("resume-1",),
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    checkpoint = json.loads(row[0])
    assert checkpoint["status"] == "completed"
    assert checkpoint["task_statuses"][FINALIZE_TASK] == "completed"
    assert checkpoint["schema_version"] == "1.0"
    assert checkpoint["created_at"].endswith("+00:00")


def test_finalize_remains_pending_after_last_baseline_crash(tmp_path: Path) -> None:
    def crash_after_baselines(event: str, workspace: RunWorkspace) -> None:
        del workspace
        if event == "after_baseline_agents":
            raise InjectedCrash(event)

    with pytest.raises(InjectedCrash, match="after_baseline_agents"):
        build_runner(
            tmp_path,
            provider=RecordingProvider(),
            run_hook=crash_after_baselines,
        ).run(**run_args())

    run_dir = tmp_path / "runs" / "resume-1"
    checkpoint = SqliteRunStore(run_dir / "run.db", run_id="resume-1").domain_objects(
        object_type="RunCheckpoint"
    )[0]["payload"]
    assert checkpoint["status"] == "running"
    assert checkpoint["task_statuses"][FINALIZE_TASK] == "pending"
    assert checkpoint["pending_task_ids"] == [FINALIZE_TASK]

    resumed = build_runner(tmp_path, provider=RejectingProvider()).run(
        **run_args(resume=True)
    )

    assert resumed["status"] == "completed"
    assert resumed["stage_count"] == 3


def test_finalize_running_is_retried_after_engine_crash_before_commit(
    tmp_path: Path,
) -> None:
    def crash_after_engine(event: str, workspace: RunWorkspace) -> None:
        del workspace
        if event == "after_finalize_engine":
            raise InjectedCrash(event)

    with pytest.raises(InjectedCrash, match="after_finalize_engine"):
        build_runner(
            tmp_path,
            provider=RecordingProvider(),
            run_hook=crash_after_engine,
        ).run(**run_args())

    run_dir = tmp_path / "runs" / "resume-1"
    store = SqliteRunStore(run_dir / "run.db", run_id="resume-1")
    checkpoint = store.domain_objects(object_type="RunCheckpoint")[0]["payload"]
    assert checkpoint["status"] == "running"
    assert checkpoint["task_statuses"][FINALIZE_TASK] == "running"
    assert store.count("WinningMechanismStageOutput") == 0
    assert store.count("ResearchReport") == 0

    resumed = build_runner(tmp_path, provider=RejectingProvider()).run(
        **run_args(resume=True)
    )

    assert resumed["status"] == "completed"
    assert store.count("WinningMechanismStageOutput") == 3
    assert store.count("CapabilityImageItem") == 2
    assert store.count("ResearchReport") == 1
    proposal_ids = [event["proposal_id"] for event in store.trace_events()]
    assert len(proposal_ids) == len(set(proposal_ids))


def test_initial_transaction_persists_research_problem_and_resume_validates_it(
    tmp_path: Path,
) -> None:
    with pytest.raises(InjectedCrash):
        build_runner(tmp_path, provider=RecordingProvider(crash_on_call=2)).run(
            **run_args()
        )

    run_dir = tmp_path / "runs" / "resume-1"
    store = SqliteRunStore(run_dir / "run.db", run_id="resume-1")
    problems = store.domain_objects(object_type="ResearchProblem")
    assert len(problems) == 1
    assert problems[0]["payload"]["selected_agent_ids"] == AGENTS

    connection = sqlite3.connect(run_dir / "run.db")
    try:
        row = connection.execute(
            """
            SELECT payload_json FROM domain_objects
            WHERE run_id = ? AND object_type = 'RunCheckpoint'
            """,
            ("resume-1",),
        ).fetchone()
        assert row is not None
        checkpoint = json.loads(row[0])
        checkpoint["topic"] = "different topic"
        connection.execute(
            """
            UPDATE domain_objects SET payload_json = ?
            WHERE run_id = ? AND object_type = 'RunCheckpoint'
            """,
            (json.dumps(checkpoint), "resume-1"),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RecoveryError, match="ResearchProblem"):
        build_runner(tmp_path, provider=RecordingProvider()).run(
            **run_args(topic="different topic", resume=True)
        )


def test_recovery_deduplicates_checkpoint_materials_and_worker_reports(
    tmp_path: Path,
) -> None:
    with pytest.raises(InjectedCrash):
        build_runner(tmp_path, provider=RecordingProvider(crash_on_call=2)).run(
            **run_args()
        )

    run_dir = tmp_path / "runs" / "resume-1"
    connection = sqlite3.connect(run_dir / "run.db")
    try:
        row = connection.execute(
            """
            SELECT payload_json FROM domain_objects
            WHERE run_id = ? AND object_type = 'RunCheckpoint'
            """,
            ("resume-1",),
        ).fetchone()
        assert row is not None
        checkpoint = json.loads(row[0])
        checkpoint["source_materials"] *= 2
        checkpoint["worker_reports"] *= 2
        connection.execute(
            """
            UPDATE domain_objects SET payload_json = ?
            WHERE run_id = ? AND object_type = 'RunCheckpoint'
            """,
            (json.dumps(checkpoint), "resume-1"),
        )
        connection.commit()
    finally:
        connection.close()

    resumed = build_runner(tmp_path, provider=RecordingProvider()).run(
        **run_args(resume=True)
    )
    summary = json.loads(Path(resumed["summary_path"]).read_text(encoding="utf-8"))
    assert len(summary["source_materials"]) == len(AGENTS)
    assert len(summary["worker_reports"]) == len(AGENTS)


def test_runner_session_append_rejects_leaf_replaced_by_symlink(tmp_path: Path) -> None:
    external = tmp_path / "external-session.jsonl"
    external.write_text("external\n", encoding="utf-8")
    session_path = (
        tmp_path
        / "runs"
        / "resume-1"
        / "agent_sessions"
        / f"{AGENTS[0]}.jsonl"
    )
    provider = SessionSymlinkProvider(session_path, external)

    with pytest.raises((OSError, ValueError)):
        build_runner(tmp_path, provider=provider).run(
            **run_args(agent_ids=AGENTS[:1])
        )

    assert external.read_text(encoding="utf-8") == "external\n"


def test_runner_artifact_write_rejects_directory_replaced_after_scheduler_init(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "runs" / "resume-1" / "artifacts"
    external = tmp_path / "external-artifacts"
    external.mkdir()
    provider = ArtifactDirectorySymlinkProvider(artifacts_dir, external)

    with pytest.raises((OSError, ValueError)):
        build_runner(tmp_path, provider=provider).run(
            **run_args(agent_ids=AGENTS[:1])
        )

    assert list(external.iterdir()) == []


@pytest.mark.parametrize("leaf", ["report.md", "domain.jsonl"])
def test_runner_final_outputs_reject_leaf_symlink(
    tmp_path: Path,
    leaf: str,
) -> None:
    external = tmp_path / f"external-{leaf}"
    external.write_text("external\n", encoding="utf-8")

    def install_symlink(event: str, workspace: RunWorkspace) -> None:
        if event == "before_outputs":
            (workspace.run_dir / leaf).symlink_to(external)

    with pytest.raises(ValueError, match="symlink"):
        build_runner(
            tmp_path,
            provider=RecordingProvider(),
            run_hook=install_symlink,
        ).run(**run_args(agent_ids=AGENTS[:1]))

    assert external.read_text(encoding="utf-8") == "external\n"


def test_runner_checkpoint_latest_rejects_leaf_symlink(tmp_path: Path) -> None:
    external = tmp_path / "external-checkpoint.json"
    external.write_text("external\n", encoding="utf-8")

    def install_symlink(event: str, workspace: RunWorkspace) -> None:
        if event == "after_final_commit":
            latest = workspace.checkpoints_dir / "latest.json"
            latest.unlink()
            latest.symlink_to(external)

    with pytest.raises(ValueError, match="symlink"):
        build_runner(
            tmp_path,
            provider=RecordingProvider(),
            run_hook=install_symlink,
        ).run(**run_args(agent_ids=AGENTS[:1]))

    assert external.read_text(encoding="utf-8") == "external\n"


def test_completed_resume_outputs_complete_rejects_report_symlink(
    tmp_path: Path,
) -> None:
    first = build_runner(tmp_path, provider=RecordingProvider()).run(
        **run_args(agent_ids=AGENTS[:1])
    )
    run_dir = Path(first["run_dir"])
    external = tmp_path / "external-completed-report.md"
    external.write_text("external\n", encoding="utf-8")
    report = run_dir / "report.md"
    report.unlink()
    report.symlink_to(external)

    with pytest.raises(ValueError, match="symlink"):
        build_runner(tmp_path, provider=RejectingProvider()).run(
            **run_args(agent_ids=AGENTS[:1], resume=True)
        )

    assert external.read_text(encoding="utf-8") == "external\n"
