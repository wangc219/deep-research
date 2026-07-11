from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from equipment_deep_research.agents.provider import (
    AgentProvider,
    AgentRunRequest,
    AgentRunResult,
    FakeAgentProvider,
)
from equipment_deep_research.domain.proposals import TraceProposal
from equipment_deep_research.domain.store import SqliteRunStore
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.harness.recovery import RecoveryError
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.orchestration.runner import DeepResearchRunner


ROOT = Path(__file__).resolve().parents[3]
AGENTS = ["international_situation", "combat_scenario", "weapon_equipment"]


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


def build_runner(
    tmp_path: Path,
    *,
    provider: AgentProvider | None = None,
    preset_config_path: Path | None = None,
) -> DeepResearchRunner:
    return DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=ROOT / "configs" / "equipment_deep_research" / "agents.yaml",
        preset_config_path=preset_config_path
        or ROOT / "configs" / "equipment_deep_research" / "presets.yaml",
        provider=provider,
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
        f"baseline:{agent_id}" for agent_id in AGENTS
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
    trace_before = (run_dir / "trace.jsonl").read_bytes()

    resumed = build_runner(tmp_path, provider=RejectingProvider()).run(
        **run_args(resume=True)
    )

    assert resumed["status"] == "completed"
    assert database.recover() == before
    assert (run_dir / "trace.jsonl").read_bytes() == trace_before
    assert {
        agent_id: session_bytes(run_dir, agent_id) for agent_id in AGENTS
    } == session_prefixes


def test_session_reconciliation_finishes_before_run_resumed(tmp_path: Path) -> None:
    with pytest.raises(InjectedCrash):
        build_runner(tmp_path, provider=RecordingProvider(crash_on_call=2)).run(
            **run_args()
        )

    run_dir = tmp_path / "runs" / "resume-1"
    store = SqliteRunStore(run_dir / "run.db", run_id="resume-1")
    session_ref = "reconcile-agent.jsonl"
    session = JsonlSessionStore(session_ref, root_dir=run_dir / "agent_sessions")
    session.append(
        {
            "event_type": "savepoint_pending",
            "execution_id": "execution-reconcile",
            "task_id": "task-reconcile",
            "agent_id": "reconcile-agent",
            "turn_index": 1,
            "batch_hash": "sha256:test",
            "created_at": "2026-07-11T00:00:00+00:00",
            "schema_version": "1.0",
        }
    )
    store.commit(
        (),
        (
            TraceProposal(
                "marker-reconcile",
                "session_write_failed",
                "reconcile-agent",
                {
                    "marker_id": "marker-reconcile",
                    "committed_checkpoint_id": "checkpoint-reconcile",
                    "batch_hash": "sha256:test",
                    "turn_index": 1,
                    "task_id": "task-reconcile",
                    "agent_id": "reconcile-agent",
                    "execution_id": "execution-reconcile",
                    "session_ref": session_ref,
                    "session_event": "savepoint",
                },
            ),
        ),
    )

    build_runner(tmp_path, provider=RecordingProvider()).run(
        **run_args(resume=True)
    )

    events = store.trace_events()
    event_types = [event["event_type"] for event in events]
    assert event_types.index("session_reconciled") < event_types.index("run_resumed")
    reconciled = session.read_all()
    assert [
        row["event_type"]
        for row in reconciled
        if row.get("reconciliation_marker_id") == "marker-reconcile"
    ] == ["savepoint", "session_reconciled"]
    assert store.recover()["unresolved_session_writes"] == []


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
    assert checkpoint["schema_version"] == "1.0"
    assert checkpoint["created_at"].endswith("+00:00")
