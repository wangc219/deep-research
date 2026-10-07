"""Concurrency and governance checks for the deep-research SQLite ledger."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunRepository
from equipment_deep_research.persistence.repositories import deep_jobs


def _repositories(tmp_path: Path, count: int = 4) -> list[SqlRunRepository]:
    url = f"sqlite:///{tmp_path / 'deep-ledger.db'}"
    return [SqlRunRepository(create_database_engine(url)) for _ in range(count)]


def test_reference_job_fingerprint_is_cross_worker_idempotent(tmp_path: Path) -> None:
    repositories = _repositories(tmp_path, 8)

    def create(index: int) -> dict:
        return repositories[index].create_or_get_deep_job(
            job_id=f"job-{index}",
            parent_run_id="parent-1",
            session_id="session-1",
            idempotency_key=f"request-{index}",
            fingerprint="parent-1:hypothesis-1:query-hash:focus-hash",
            payload={"hypothesis_id": "hypothesis-1"},
        )

    with ThreadPoolExecutor(max_workers=len(repositories)) as pool:
        rows = list(pool.map(create, range(len(repositories))))

    job_ids = {row["job_id"] for row in rows}
    assert len(job_ids) == 1
    assert len(repositories[0].list_deep_jobs("parent-1")) == 1
    canonical = repositories[0].get_deep_job_by_fingerprint(
        "parent-1", "parent-1:hypothesis-1:query-hash:focus-hash"
    )
    assert canonical is not None
    assert canonical["job_id"] in job_ids


def test_binding_cancelled_reservation_cancels_new_session_atomically(
    tmp_path: Path,
) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_or_get_deep_job(
        job_id="job-bind-cancelled",
        parent_run_id="parent-bind-cancelled",
        fingerprint="fingerprint-bind-cancelled",
    )
    repository.update_deep_job(
        "job-bind-cancelled",
        stage="publish",
        status="cancelled",
    )
    repository.create_deep_session(
        session_id="session-bind-cancelled",
        parent_run_id="parent-bind-cancelled",
        kind="reference-research",
    )

    bound = repository.bind_deep_job_session(
        "job-bind-cancelled",
        parent_run_id="parent-bind-cancelled",
        session_id="session-bind-cancelled",
    )

    assert bound["session_id"] == "session-bind-cancelled"
    assert bound["status"] == "cancelled"
    assert repository.get_deep_session("session-bind-cancelled")["status"] == "cancelled"


def test_retry_reopens_cancelled_job_and_session_in_one_transaction(
    tmp_path: Path,
) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-retry-cancelled",
        parent_run_id="parent-retry-cancelled",
        kind="reference-research",
    )
    repository.create_or_get_deep_job(
        job_id="job-retry-cancelled",
        parent_run_id="parent-retry-cancelled",
        session_id="session-retry-cancelled",
        fingerprint="fingerprint-retry-cancelled",
    )
    repository.update_deep_job(
        "job-retry-cancelled",
        stage="publish",
        status="cancelled",
    )
    repository.update_deep_session("session-retry-cancelled", status="cancelled")

    queued = repository.requeue_deep_job(
        "job-retry-cancelled",
        parent_run_id="parent-retry-cancelled",
    )

    assert queued["status"] == "queued"
    assert repository.get_deep_session("session-retry-cancelled")["status"] == "active"


def test_deep_job_claim_is_single_winner_and_reclaims_stale_rows(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_or_get_deep_job(
        job_id="job-claim",
        parent_run_id="parent-claim",
        session_id="session-claim",
        idempotency_key="claim-key",
        fingerprint="claim-fingerprint",
    )

    first = repository.claim_deep_job("job-claim")
    assert first is not None
    assert first["status"] == "running"
    # A second API worker cannot steal a fresh running lease.
    assert repository.claim_deep_job("job-claim", recover=True, stale_after_seconds=3600) is None

    # Simulate a process crash by aging the durable heartbeat. Recovery may
    # reclaim the row exactly once and clear the stale error marker.
    with repository.engine.begin() as connection:
        connection.execute(
            deep_jobs.update()
            .where(deep_jobs.c.job_id == "job-claim")
            .values(updated_at="2000-01-01T00:00:00+00:00", error="stale")
        )
    recovered = repository.claim_deep_job(
        "job-claim", recover=True, stale_after_seconds=1
    )
    assert recovered is not None
    assert recovered["status"] == "running"
    assert recovered["error"] == ""
    assert repository.claim_deep_job(
        "job-claim", recover=True, stale_after_seconds=3600
    ) is None


def test_deep_job_claim_serializes_turns_on_one_session_branch(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_or_get_deep_job(
        job_id="job-turn-1",
        parent_run_id="parent-turns",
        session_id="session-turns",
        branch_id="main",
        idempotency_key="turn-1",
        fingerprint="turn-fingerprint-1",
    )
    repository.create_or_get_deep_job(
        job_id="job-turn-2",
        parent_run_id="parent-turns",
        session_id="session-turns",
        branch_id="main",
        idempotency_key="turn-2",
        fingerprint="turn-fingerprint-2",
    )

    first = repository.claim_deep_job("job-turn-1")
    assert first is not None
    assert repository.claim_deep_job("job-turn-2") is None

    completed = repository.update_deep_job(
        "job-turn-1",
        stage="publish",
        status="completed",
        claim_token=first["claim_token"],
    )
    assert completed is not None
    second = repository.claim_deep_job("job-turn-2")
    assert second is not None
    assert second["status"] == "running"


def test_reclaimed_job_rejects_stale_worker_writes(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_or_get_deep_job(
        job_id="job-fenced",
        parent_run_id="parent-fenced",
        session_id="session-fenced",
        idempotency_key="fenced-key",
        fingerprint="fenced-fingerprint",
    )
    first = repository.claim_deep_job("job-fenced")
    assert first is not None
    first_token = first["claim_token"]

    with repository.engine.begin() as connection:
        connection.execute(
            deep_jobs.update()
            .where(deep_jobs.c.job_id == "job-fenced")
            .values(updated_at="2000-01-01T00:00:00+00:00")
        )
    recovered = repository.claim_deep_job(
        "job-fenced", recover=True, stale_after_seconds=1
    )
    assert recovered is not None
    recovered_token = recovered["claim_token"]
    assert recovered_token != first_token

    stale = repository.update_deep_job(
        "job-fenced",
        stage="s6_authoring",
        status="running",
        claim_token=first_token,
    )
    assert stale is not None
    assert stale["_claim_rejected"] is True
    assert stale["stage"] == recovered["stage"]

    current = repository.update_deep_job(
        "job-fenced",
        stage="s3_divergence",
        status="running",
        claim_token=recovered_token,
    )
    assert current is not None
    assert current["stage"] == "s3_divergence"


def test_stale_claim_cannot_consume_apply_or_park_steering(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-steer-fenced",
        parent_run_id="parent-steer-fenced",
        kind="deep-thinking",
    )
    repository.create_or_get_deep_job(
        job_id="job-steer-fenced",
        parent_run_id="parent-steer-fenced",
        session_id="session-steer-fenced",
        idempotency_key="steer-fenced-key",
        fingerprint="steer-fenced-fingerprint",
    )
    first = repository.claim_deep_job("job-steer-fenced")
    assert first is not None
    first_token = first["claim_token"]
    with repository.engine.begin() as connection:
        connection.execute(
            deep_jobs.update()
            .where(deep_jobs.c.job_id == "job-steer-fenced")
            .values(updated_at="2000-01-01T00:00:00+00:00")
        )
    recovered = repository.claim_deep_job(
        "job-steer-fenced", recover=True, stale_after_seconds=1
    )
    assert recovered is not None
    recovered_token = recovered["claim_token"]
    steer = repository.enqueue_deep_steer(
        job_id="job-steer-fenced",
        content="改从低成本饱和角度分析",
        mode="steer",
        client_steer_id="stale-steer",
    )

    assert repository.claim_deep_steers(
        "job-steer-fenced", claim_token=first_token
    ) == []
    claimed = repository.claim_deep_steers(
        "job-steer-fenced", claim_token=recovered_token
    )
    assert [row["steer_id"] for row in claimed] == [steer["steer_id"]]
    assert repository.mark_deep_steers_applied(
        [steer["steer_id"]], stage="s3_divergence", claim_token=first_token
    ) == []
    assert repository.close_and_park_deep_steers(
        "job-steer-fenced", claim_token=first_token
    ) == []
    assert repository.get_deep_job("job-steer-fenced")["steer_closed"] is False
    applied = repository.mark_deep_steers_applied(
        [steer["steer_id"]],
        stage="s3_divergence",
        claim_token=recovered_token,
    )
    assert [row["status"] for row in applied] == ["applied"]


def test_deep_job_state_version_advances_on_semantic_transitions(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    created = repository.create_or_get_deep_job(
        job_id="job-versioned",
        parent_run_id="parent-versioned",
        session_id="session-versioned",
        idempotency_key="versioned-key",
        fingerprint="versioned-fingerprint",
    )
    claimed = repository.claim_deep_job("job-versioned")
    assert claimed is not None
    updated = repository.update_deep_job(
        "job-versioned",
        stage="s3_divergence",
        status="running",
        claim_token=claimed["claim_token"],
    )
    assert updated is not None
    closed = repository.close_and_park_deep_steers(
        "job-versioned", claim_token=claimed["claim_token"]
    )
    assert closed == []
    final = repository.get_deep_job("job-versioned")
    assert final is not None
    assert [
        created["state_version"],
        claimed["state_version"],
        updated["state_version"],
        final["state_version"],
    ] == sorted(
        {
            created["state_version"],
            claimed["state_version"],
            updated["state_version"],
            final["state_version"],
        }
    )

def test_deep_job_stage_completion_is_not_global_terminal(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_or_get_deep_job(
        job_id="job-stage",
        parent_run_id="parent-stage",
        session_id="session-stage",
        idempotency_key="stage-key",
        fingerprint="stage-fingerprint",
    )
    repository.update_deep_job(
        "job-stage", stage="s4_mapping", status="completed"
    )
    # Stage-level ``completed`` is followed by retrieval/validation updates;
    # only a completed publish stage is terminal.
    updated = repository.update_deep_job(
        "job-stage", stage="retrieval", status="running"
    )
    assert updated is not None
    assert updated["stage"] == "retrieval"
    assert updated["status"] == "running"
    repository.update_deep_job("job-stage", stage="publish", status="completed")
    late = repository.update_deep_job(
        "job-stage", stage="retrieval", status="running"
    )
    assert late is not None
    assert late["stage"] == "publish"
    assert late["status"] == "completed"
    assert late["_already_terminal"] is True


@pytest.mark.parametrize("stage", ["council_critique", "s5_adjudication"])
def test_deep_job_accepts_adjudication_stages(tmp_path: Path, stage: str) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_or_get_deep_job(
        job_id=f"job-{stage}",
        parent_run_id=f"parent-{stage}",
        session_id=f"session-{stage}",
        idempotency_key=f"key-{stage}",
        fingerprint=f"fingerprint-{stage}",
    )

    updated = repository.update_deep_job(
        f"job-{stage}", stage=stage, status="running"
    )

    assert updated is not None
    assert updated["stage"] == stage
    assert updated["status"] == "running"


def test_explicit_deep_job_retry_requeues_partial_without_changing_lineage(
    tmp_path: Path,
) -> None:
    repository = _repositories(tmp_path, 1)[0]
    original = repository.create_or_get_deep_job(
        job_id="job-retry",
        parent_run_id="parent-retry",
        session_id="session-retry",
        child_run_id="child-retry",
        idempotency_key="retry-key",
        fingerprint="retry-fingerprint",
        payload={"hypothesis_id": "hypothesis-retry", "candidate": {"name": "候选"}},
    )
    repository.update_deep_job(
        "job-retry", stage="validation", status="partial", error="sidecar unavailable"
    )

    queued = repository.requeue_deep_job(
        "job-retry",
        parent_run_id="parent-retry",
        allowed_statuses=("partial",),
    )

    assert queued is not None
    assert queued["job_id"] == original["job_id"]
    assert queued["status"] == "queued"
    assert queued["stage"] == "queued"
    assert queued["child_run_id"] == "child-retry"
    assert queued["fingerprint"] == "retry-fingerprint"
    assert queued["payload"]["hypothesis_id"] == "hypothesis-retry"
    # A second retry after the worker has claimed the row is fenced and does
    # not reset the active lease.
    assert repository.claim_deep_job("job-retry") is not None
    assert repository.requeue_deep_job(
        "job-retry", parent_run_id="parent-retry", allowed_statuses=("partial",)
    ) is None


def test_explicit_retry_does_not_requeue_a_live_partial_stage(
    tmp_path: Path,
) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_or_get_deep_job(
        job_id="job-live-partial",
        parent_run_id="parent-live-partial",
        session_id="session-live-partial",
        idempotency_key="live-partial-key",
        fingerprint="live-partial-fingerprint",
    )
    claimed = repository.claim_deep_job("job-live-partial")
    assert claimed is not None
    live = repository.update_deep_job(
        "job-live-partial",
        stage="s6_authoring",
        status="partial",
        claim_token=claimed["claim_token"],
    )
    assert live is not None

    assert repository.requeue_deep_job(
        "job-live-partial", parent_run_id="parent-live-partial"
    ) is None

    current = repository.get_deep_job("job-live-partial")
    assert current is not None
    assert current["stage"] == "s6_authoring"
    assert current["status"] == "partial"
    assert current["claim_token"] == claimed["claim_token"]


def test_explicit_retry_can_resume_unclaimed_s6_partial_projection(
    tmp_path: Path,
) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_or_get_deep_job(
        job_id="job-unclaimed-s6-partial",
        parent_run_id="parent-unclaimed-s6-partial",
        session_id="session-unclaimed-s6-partial",
        child_run_id="child-unclaimed-s6-partial",
        idempotency_key="unclaimed-s6-partial-key",
        fingerprint="unclaimed-s6-partial-fingerprint",
    )
    updated = repository.update_deep_job(
        "job-unclaimed-s6-partial",
        stage="s6_authoring",
        status="partial",
    )
    assert updated is not None
    assert updated["claim_token"] == ""

    queued = repository.requeue_deep_job(
        "job-unclaimed-s6-partial",
        parent_run_id="parent-unclaimed-s6-partial",
    )

    assert queued is not None
    assert queued["stage"] == "queued"
    assert queued["status"] == "queued"
    assert queued["child_run_id"] == "child-unclaimed-s6-partial"


def test_deep_job_heartbeat_honours_expected_status_fence(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_or_get_deep_job(
        job_id="job-heartbeat",
        parent_run_id="parent-heartbeat",
        session_id="session-heartbeat",
        idempotency_key="heartbeat-key",
        fingerprint="heartbeat-fingerprint",
    )
    assert repository.claim_deep_job("job-heartbeat") is not None
    with repository.engine.begin() as connection:
        connection.execute(
            deep_jobs.update()
            .where(deep_jobs.c.job_id == "job-heartbeat")
            .values(updated_at="2000-01-01T00:00:00+00:00")
        )

    fenced = repository.touch_deep_job(
        "job-heartbeat", expected_statuses=("queued",)
    )
    assert fenced is not None
    assert fenced["updated_at"] == "2000-01-01T00:00:00+00:00"

    refreshed = repository.touch_deep_job(
        "job-heartbeat", expected_statuses=("running",)
    )
    assert refreshed is not None
    assert refreshed["updated_at"] != "2000-01-01T00:00:00+00:00"


def test_deep_event_sequences_are_monotonic_across_workers(tmp_path: Path) -> None:
    repositories = _repositories(tmp_path, 6)

    def append(index: int) -> dict:
        return repositories[index % len(repositories)].append_deep_event(
            stream_id="deep-session:parent:session",
            parent_run_id="parent",
            session_id="session",
            event_type="deep_stage",
            stage="s3_divergence",
            status="running",
            progress=index / 100,
            delta={"kind": "summary", "text": f"step {index}"},
        )

    with ThreadPoolExecutor(max_workers=24) as pool:
        rows = list(pool.map(append, range(24)))

    assert sorted(int(row["sequence"]) for row in rows) == list(range(1, 25))
    replay = repositories[0].deep_events_after("deep-session:parent:session", 0)
    assert [int(row["sequence"]) for row in replay] == list(range(1, 25))
    assert all("raw_message" not in str(row) for row in replay)


@pytest.mark.parametrize("progress", [float("nan"), float("inf"), "not-a-number"])
def test_deep_event_progress_is_finite_when_worker_reports_bad_value(
    tmp_path: Path, progress: object
) -> None:
    repository = _repositories(tmp_path, 1)[0]
    row = repository.append_deep_event(
        stream_id="deep-session:bad-progress:session",
        parent_run_id="bad-progress",
        session_id="session",
        event_type="deep_stage",
        progress=progress,
    )
    assert row["progress"] == 0.0
    replay = repository.deep_events_after("deep-session:bad-progress:session", 0)
    assert replay[0]["progress"] == 0.0


def test_deep_event_replay_preserves_job_state_version(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    written = repository.append_deep_event(
        stream_id="deep-session:versioned-event:session",
        parent_run_id="versioned-event",
        session_id="session",
        job_id="job",
        event_type="deep_stage",
        state_version=7,
        progress=0.5,
    )

    replay = repository.deep_events_after(
        "deep-session:versioned-event:session", 0
    )
    assert written["state_version"] == 7
    assert replay[0]["state_version"] == 7


def test_capability_version_chain_and_immutable_formal_baseline(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    baseline = repository.ensure_capability_baseline(
        parent_run_id="parent",
        card_binding_id="binding",
        hypothesis_id="hypothesis",
        snapshot={"name": "formal"},
    )
    deep_v2 = repository.save_capability_version(
        version_id="version-2",
        parent_run_id="parent",
        card_binding_id="binding",
        hypothesis_id="hypothesis",
        snapshot={"name": "deep"},
        diff={"overview": "changed"},
    )

    assert baseline["version_no"] == 1
    assert baseline["status"] == "formal"
    assert deep_v2["version_no"] == 2
    assert deep_v2["parent_version_id"] == baseline["version_id"]
    with pytest.raises(ValueError, match="immutable"):
        repository.verify_capability_version(
            baseline["version_id"], status="verified", parent_run_id="parent"
        )
    assert repository.get_capability_version(
        baseline["version_id"], parent_run_id="other-parent"
    ) is None


def test_capability_versions_are_numbered_per_hypothesis_and_emit_module_diff(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    baseline = repository.ensure_capability_baseline(
        parent_run_id="parent", card_binding_id="binding-a", hypothesis_id="h-a",
        snapshot={"identity": "A", "effect": "old"},
    )
    v2 = repository.save_capability_version(
        version_id="h-a-v2", parent_run_id="parent", card_binding_id="binding-a",
        hypothesis_id="h-a", snapshot={"identity": "A", "effect": "new"},
    )
    # A genuinely new hypothesis starts an independent v1 chain even when it
    # belongs to the same run and card family.
    h_b = repository.save_capability_version(
        version_id="h-b-v1", parent_run_id="parent", card_binding_id="binding-b",
        hypothesis_id="h-b", snapshot={"identity": "B"},
    )
    assert v2["version_no"] == 2
    assert v2["parent_version_id"]
    assert v2["base_version_id"]
    assert h_b["version_no"] == 1
    assert h_b["base_version_id"] == ""
    assert v2["diff"]["modules"]["effect"]["status"] == "changed"
    assert "effect" in v2["diff"]["changed_modules"]


def test_verify_version_is_scoped_to_parent_run(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    version = repository.save_capability_version(
        version_id="version-scoped",
        parent_run_id="parent-a",
        card_binding_id="binding",
        hypothesis_id="hypothesis",
        snapshot={"name": "candidate"},
    )

    assert repository.verify_capability_version(
        version["version_id"], status="verified", parent_run_id="parent-b"
    ) is None
    unchanged = repository.get_capability_version(version["version_id"])
    assert unchanged is not None
    assert unchanged["status"] == "pending_verification"
    updated = repository.verify_capability_version(
        version["version_id"], status="verified", parent_run_id="parent-a"
    )
    assert updated is not None
    assert updated["status"] == "verified"


def test_deep_session_status_and_result_hash_are_validated(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session",
        parent_run_id="parent",
        kind="deep-thinking",
    )
    updated = repository.update_deep_session(
        "session", status="partial", result_snapshot_hash="hash-1"
    )
    assert updated is not None
    assert updated["status"] == "partial"
    assert updated["result_snapshot_hash"] == "hash-1"
    with pytest.raises(ValueError, match="invalid deep session status"):
        repository.update_deep_session("session", status="published")


def test_cancelled_deep_session_cannot_be_resurrected_by_late_worker(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-terminal",
        parent_run_id="parent",
        kind="deep-thinking",
    )
    repository.update_deep_session("session-terminal", status="cancelled")

    late = repository.update_deep_session("session-terminal", status="completed")

    assert late is not None
    assert late["status"] == "cancelled"


def test_cancelled_deep_session_can_be_archived_and_archived_session_restored(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-managed",
        parent_run_id="parent",
        kind="deep-thinking",
    )
    repository.update_deep_session("session-managed", status="cancelled")

    archived = repository.update_deep_session("session-managed", status="archived")
    assert archived is not None
    assert archived["status"] == "archived"

    late = repository.update_deep_session("session-managed", status="completed")
    assert late is not None
    assert late["status"] == "archived"

    restored = repository.update_deep_session("session-managed", status="active")
    assert restored is not None
    assert restored["status"] == "active"


def test_delete_deep_session_removes_transient_ledger_but_keeps_capability_versions(
    tmp_path: Path,
) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-delete",
        parent_run_id="parent-delete",
        kind="deep-thinking",
        card_binding_id="binding-delete",
        hypothesis_id="hypothesis-delete",
    )
    repository.append_deep_message(
        session_id="session-delete", role="user", content="待删除问题"
    )
    repository.create_or_get_deep_job(
        job_id="job-delete",
        parent_run_id="parent-delete",
        session_id="session-delete",
        idempotency_key="job-delete-key",
        fingerprint="job-delete-fingerprint",
    )
    repository.update_deep_job(
        "job-delete", stage="publish", status="completed"
    )
    repository.append_deep_event(
        stream_id="deep-session:parent-delete:session-delete",
        parent_run_id="parent-delete",
        session_id="session-delete",
        job_id="job-delete",
        event_type="deep_session_message",
        stage="publish",
        status="completed",
    )
    version = repository.save_capability_version(
        version_id="version-delete",
        parent_run_id="parent-delete",
        card_binding_id="binding-delete",
        hypothesis_id="hypothesis-delete",
        diff={"overview": "updated"},
        snapshot={"name": "已固定能力画像"},
        source="deep-thinking",
    )

    deleted = repository.delete_deep_session(
        "session-delete", parent_run_id="parent-delete"
    )

    assert deleted is not None
    assert deleted["session_id"] == "session-delete"
    assert repository.get_deep_session("session-delete") is None
    assert repository.list_deep_messages("session-delete") == []
    assert repository.get_deep_job("job-delete") is None
    assert repository.deep_events_after(
        "deep-session:parent-delete:session-delete", 0
    ) == []
    assert repository.get_capability_version(version["version_id"]) is not None


def test_delete_deep_session_rejects_live_job(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-live",
        parent_run_id="parent-live",
        kind="deep-thinking",
    )
    repository.create_or_get_deep_job(
        job_id="job-live",
        parent_run_id="parent-live",
        session_id="session-live",
        idempotency_key="job-live-key",
        fingerprint="job-live-fingerprint",
    )

    with pytest.raises(ValueError, match="running job"):
        repository.delete_deep_session(
            "session-live", parent_run_id="parent-live"
        )

    assert repository.get_deep_session("session-live") is not None
    assert repository.get_deep_job("job-live") is not None


def test_capability_version_delete_and_restore_preserve_review_state(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    baseline = repository.ensure_capability_baseline(
        parent_run_id="parent-versions",
        card_binding_id="binding-versions",
        hypothesis_id="hypothesis-versions",
        snapshot={"name": "正式基线"},
    )
    deep = repository.save_capability_version(
        version_id="version-managed",
        parent_run_id="parent-versions",
        card_binding_id="binding-versions",
        hypothesis_id="hypothesis-versions",
        snapshot={"name": "深研版本"},
    )
    repository.verify_capability_version(
        deep["version_id"], status="verified", parent_run_id="parent-versions"
    )

    deleted = repository.delete_capability_version(
        deep["version_id"], parent_run_id="parent-versions"
    )
    assert deleted is not None
    assert deleted["status"] == "deleted"
    assert deleted["previous_status"] == "verified"

    restored = repository.restore_capability_version(
        deep["version_id"], parent_run_id="parent-versions"
    )
    assert restored is not None
    assert restored["status"] == "verified"
    assert restored["previous_status"] == ""

    with pytest.raises(ValueError, match="immutable"):
        repository.delete_capability_version(
            baseline["version_id"], parent_run_id="parent-versions"
        )


def test_capability_version_purge_removes_soft_deleted_row(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.ensure_capability_baseline(
        parent_run_id="parent-purge",
        card_binding_id="binding-purge",
        hypothesis_id="hypothesis-purge",
        snapshot={"name": "正式基线"},
    )
    deep = repository.save_capability_version(
        version_id="version-purge",
        parent_run_id="parent-purge",
        card_binding_id="binding-purge",
        hypothesis_id="hypothesis-purge",
        snapshot={"name": "待清除深研版本"},
    )

    with pytest.raises(ValueError, match="soft-deleted"):
        repository.purge_capability_version(
            deep["version_id"], parent_run_id="parent-purge"
        )

    deleted = repository.delete_capability_version(
        deep["version_id"], parent_run_id="parent-purge"
    )
    assert deleted is not None
    assert deleted["status"] == "deleted"

    purged = repository.purge_capability_version(
        deep["version_id"], parent_run_id="parent-purge"
    )
    assert purged is not None
    assert purged["version_id"] == deep["version_id"]
    assert repository.get_capability_version(
        deep["version_id"], parent_run_id="parent-purge"
    ) is None
    remaining = repository.list_capability_versions("parent-purge")
    assert all(row["version_id"] != deep["version_id"] for row in remaining)


def test_message_persists_artifact_and_version_references(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session",
        parent_run_id="parent",
        kind="deep-thinking",
    )
    message = repository.append_deep_message(
        session_id="session",
        role="assistant",
        content="可见分析",
        artifact_refs=["artifact-1"],
        version_refs=["version-2"],
    )
    assert message["artifact_refs"] == ["artifact-1"]
    assert message["version_refs"] == ["version-2"]
    restored = repository.list_deep_messages("session")
    assert restored[0]["artifact_refs"] == ["artifact-1"]
    assert restored[0]["version_refs"] == ["version-2"]


def test_message_turn_id_is_idempotent_across_retry(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-retry-message",
        parent_run_id="parent-retry-message",
        kind="deep-thinking",
    )

    first = repository.append_deep_message(
        session_id="session-retry-message",
        role="assistant",
        content="第一次答复",
        turn_id=" job-retry-message ",
        artifact_refs=["artifact-1"],
    )
    second = repository.append_deep_message(
        session_id="session-retry-message",
        role="assistant",
        content="重试后的答复",
        turn_id=" job-retry-message ",
        artifact_refs=["artifact-2"],
        version_refs=["version-1"],
    )

    assert second["message_id"] == first["message_id"]
    assert second["sequence"] == first["sequence"]
    assert second["content"] == "重试后的答复"
    assert second["artifact_refs"] == ["artifact-1", "artifact-2"]
    assert second["version_refs"] == ["version-1"]
    rows = repository.list_deep_messages("session-retry-message")
    assert len(rows) == 1
    assert rows[0]["turn_id"] == "job-retry-message"


def test_message_persists_bounded_runtime_metadata(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-runtime",
        parent_run_id="parent-runtime",
        kind="deep-thinking",
    )

    message = repository.append_deep_message(
        session_id="session-runtime",
        role="assistant",
        content="可见分析",
        metadata={
            "runtime": {
                "engine": "equipment_deep_runtime_v2",
                "active_skill_ids": ["counterfactual_triz_innovation"],
                "tools": ["deepen"],
            }
        },
    )

    assert message["metadata"]["runtime"]["tools"] == ["deepen"]
    restored = repository.list_deep_messages("session-runtime")
    assert restored[0]["metadata"] == message["metadata"]


def test_deep_job_checkpoint_can_advance_with_state(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-checkpoint",
        parent_run_id="parent-checkpoint",
        kind="deep-thinking",
    )
    repository.create_or_get_deep_job(
        job_id="job-checkpoint",
        parent_run_id="parent-checkpoint",
        session_id="session-checkpoint",
        checkpoint={"phase": "queued", "messages": []},
    )

    updated = repository.update_deep_job(
        "job-checkpoint",
        stage="s4_mapping",
        status="running",
        checkpoint={
            "phase": "tools_completed",
            "messages": [
                {"role": "assistant", "tool_calls": [{"name": "deepen"}]},
                {"role": "tool", "name": "deepen", "content": "ok"},
            ],
        },
    )

    assert updated is not None
    assert updated["checkpoint"]["phase"] == "tools_completed"
    assert updated["checkpoint"]["messages"][-1]["role"] == "tool"


def test_parent_cancellation_durably_cancels_deep_jobs_and_sessions(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-cancel",
        parent_run_id="parent",
        kind="reference-research",
    )
    repository.create_or_get_deep_job(
        job_id="job-cancel",
        parent_run_id="parent",
        session_id="session-cancel",
        child_run_id="child",
        idempotency_key="cancel-me",
        fingerprint="fingerprint-cancel",
    )

    cancelled = repository.cancel_deep_jobs("parent", reason="operator stop")

    assert [row["job_id"] for row in cancelled] == ["job-cancel"]
    job = repository.get_deep_job("job-cancel")
    assert job is not None
    assert job["status"] == "cancelled"
    assert job["stage"] == "publish"
    assert job["error"] == "operator stop"
    assert repository.get_deep_session("session-cancel")["status"] == "cancelled"
    # A second cancellation is idempotent and does not rewrite a terminal job.
    assert repository.cancel_deep_jobs("parent", reason="operator stop") == []


def test_deep_steering_is_idempotent_fifo_and_updates_message_status(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-steer",
        parent_run_id="parent-steer",
        kind="deep-thinking",
    )
    root = repository.append_deep_message(
        session_id="session-steer", role="user", content="初始问题"
    )
    repository.create_or_get_deep_job(
        job_id="job-steer",
        parent_run_id="parent-steer",
        session_id="session-steer",
        branch_id="main",
        root_message_id=root["message_id"],
        idempotency_key="job-steer",
    )

    first = repository.enqueue_deep_steer(
        job_id="job-steer",
        content="优先考虑低成本路线",
        mode="steer",
        client_steer_id="client-1",
    )
    duplicate = repository.enqueue_deep_steer(
        job_id="job-steer",
        content="这次内容应被幂等键忽略",
        mode="steer",
        client_steer_id="client-1",
    )
    repository.enqueue_deep_steer(
        job_id="job-steer",
        content="同时给出无人化路线",
        mode="interrupt_steer",
        client_steer_id="client-2",
    )

    assert duplicate["steer_id"] == first["steer_id"]
    claimed = repository.claim_deep_steers("job-steer")
    assert [row["client_steer_id"] for row in claimed] == ["client-1", "client-2"]
    assert repository.claim_deep_steers("job-steer") == []

    applied = repository.mark_deep_steers_applied(
        [row["steer_id"] for row in claimed], stage="council_critique"
    )
    assert [row["status"] for row in applied] == ["applied", "applied"]
    messages = repository.list_deep_messages("session-steer")
    steer_messages = [row for row in messages if row["message_kind"] == "steer"]
    assert [row["status"] for row in steer_messages] == ["applied", "applied"]


def test_deep_steering_queue_is_parked_and_terminal_intake_is_closed(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-queue",
        parent_run_id="parent-queue",
        kind="deep-thinking",
    )
    repository.create_or_get_deep_job(
        job_id="job-queue",
        parent_run_id="parent-queue",
        session_id="session-queue",
        idempotency_key="job-queue",
    )
    queued = repository.enqueue_deep_steer(
        job_id="job-queue",
        content="下一轮单独研究保障体系",
        mode="queue",
        client_steer_id="queued-1",
    )

    assert repository.claim_deep_steers("job-queue") == []
    parked = repository.close_and_park_deep_steers("job-queue")
    assert [row["steer_id"] for row in parked] == [queued["steer_id"]]
    assert parked[0]["status"] == "parked"
    assert repository.get_deep_job("job-queue")["steer_closed"] is True
    with pytest.raises(ValueError, match="no longer accepts"):
        repository.enqueue_deep_steer(
            job_id="job-queue",
            content="太晚到达的纠偏",
            mode="steer",
            client_steer_id="late-1",
        )


def test_deep_branch_path_and_working_memory_round_trip(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-branch",
        parent_run_id="parent-branch",
        kind="deep-thinking",
    )
    root = repository.append_deep_message(
        session_id="session-branch", role="user", content="主问题"
    )
    branch = repository.create_deep_branch(
        session_id="session-branch",
        branch_id="cost-route",
        forked_from_message_id=root["message_id"],
        title="低成本路线",
    )
    child = repository.append_deep_message(
        session_id="session-branch",
        role="user",
        content="只讨论低成本",
        branch_id=branch["branch_id"],
        parent_message_id=root["message_id"],
    )
    memory = {
        "schema_version": "deep-working-memory-v1",
        "branch_id": "cost-route",
        "current_objective": "低成本路线",
    }
    repository.update_deep_working_memory("session-branch", memory)

    assert child["branch_id"] == "cost-route"
    assert child["parent_message_id"] == root["message_id"]
    assert repository.list_deep_branches("session-branch")[-1]["branch_id"] == "cost-route"
    assert repository.get_deep_session("session-branch")["working_memory"] == memory


def test_branch_inherits_checkpoint_visible_at_fork_point(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-inherit",
        parent_run_id="parent-inherit",
        kind="deep-thinking",
    )
    repository.append_deep_message(
        session_id="session-inherit", role="user", content="主问题"
    )
    answer = repository.append_deep_message(
        session_id="session-inherit", role="assistant", content="保留潜伏节点"
    )
    repository.update_deep_branch_working_memory(
        "session-inherit",
        branch_id="main",
        checkpoint={
            "schema_version": "deep-working-memory-v1",
            "branch_id": "main",
            "current_objective": "验证潜伏节点",
            "candidate_directions": [{"name": "潜伏节点", "stable": True}],
            "source_checkpoint": {
                "assistant_message_id": answer["message_id"],
                "assistant_sequence": answer["sequence"],
            },
        },
    )

    repository.create_deep_branch(
        session_id="session-inherit",
        branch_id="countermeasure",
        forked_from_message_id=answer["message_id"],
        title="反制分支",
    )

    memory = repository.get_deep_session("session-inherit")["working_memory"]
    inherited = memory["branches"]["countermeasure"]
    assert inherited["candidate_directions"][0]["name"] == "潜伏节点"
    assert inherited["branch_id"] == "countermeasure"
    assert inherited["inherited_from"]["message_id"] == answer["message_id"]


def test_branch_does_not_inherit_checkpoint_newer_than_fork(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-old-fork",
        parent_run_id="parent-old-fork",
        kind="deep-thinking",
    )
    fork_point = repository.append_deep_message(
        session_id="session-old-fork", role="user", content="共同问题"
    )
    later_answer = repository.append_deep_message(
        session_id="session-old-fork", role="assistant", content="主线后续结论"
    )
    repository.update_deep_branch_working_memory(
        "session-old-fork",
        branch_id="main",
        checkpoint={
            "schema_version": "deep-working-memory-v1",
            "branch_id": "main",
            "current_objective": "主线后续目标",
            "candidate_directions": [{"name": "后来方向", "stable": True}],
            "source_checkpoint": {
                "assistant_message_id": later_answer["message_id"],
                "assistant_sequence": later_answer["sequence"],
            },
        },
    )

    repository.create_deep_branch(
        session_id="session-old-fork",
        branch_id="old-point",
        forked_from_message_id=fork_point["message_id"],
    )

    memory = repository.get_deep_session("session-old-fork")["working_memory"]
    assert "old-point" not in memory["branches"]


def test_branch_first_message_anchors_fork_and_rejects_hidden_parent(
    tmp_path: Path,
) -> None:
    repository = _repositories(tmp_path, 1)[0]
    repository.create_deep_session(
        session_id="session-anchor",
        parent_run_id="parent-anchor",
        kind="deep-thinking",
    )
    fork_point = repository.append_deep_message(
        session_id="session-anchor", role="user", content="共同问题"
    )
    hidden_main = repository.append_deep_message(
        session_id="session-anchor", role="assistant", content="主线后续"
    )
    repository.create_deep_branch(
        session_id="session-anchor",
        branch_id="branch-a",
        forked_from_message_id=fork_point["message_id"],
    )

    first = repository.append_deep_message(
        session_id="session-anchor",
        role="user",
        content="分支问题",
        branch_id="branch-a",
    )
    assert first["parent_message_id"] == fork_point["message_id"]
    with pytest.raises(ValueError, match="not visible"):
        repository.append_deep_message(
            session_id="session-anchor",
            role="user",
            content="错误挂接",
            branch_id="branch-a",
            parent_message_id=hidden_main["message_id"],
        )


def test_concurrent_branch_memory_updates_preserve_both_branches(
    tmp_path: Path,
) -> None:
    repositories = _repositories(tmp_path, 2)
    repositories[0].create_deep_session(
        session_id="session-memory",
        parent_run_id="parent-memory",
        kind="deep-thinking",
    )

    def update(index: int) -> None:
        repositories[index].update_deep_branch_working_memory(
            "session-memory",
            branch_id=f"branch-{index}",
            checkpoint={
                "schema_version": "deep-working-memory-v1",
                "branch_id": f"branch-{index}",
                "current_objective": f"objective-{index}",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update, range(2)))

    memory = repositories[0].get_deep_session("session-memory")["working_memory"]
    assert set(memory["branches"]) == {"branch-0", "branch-1"}
    assert memory["branches"]["branch-0"]["current_objective"] == "objective-0"
    assert memory["branches"]["branch-1"]["current_objective"] == "objective-1"


def test_delete_run_keeps_reviewed_versions_and_cleans_pending_versions(tmp_path: Path) -> None:
    repository = _repositories(tmp_path, 1)[0]
    baseline = repository.ensure_capability_baseline(
        parent_run_id="parent",
        card_binding_id="binding",
        hypothesis_id="hypothesis",
        snapshot={"name": "formal"},
    )
    pending_row = repository.save_capability_version(
        version_id="pending",
        parent_run_id="parent",
        card_binding_id="binding",
        hypothesis_id="hypothesis",
        snapshot={"name": "pending"},
    )
    reviewed_row = repository.save_capability_version(
        version_id="reviewed",
        parent_run_id="parent",
        card_binding_id="binding",
        hypothesis_id="hypothesis",
        snapshot={"name": "reviewed"},
    )
    repository.verify_capability_version(
        "reviewed", status="verified", parent_run_id="parent"
    )

    repository.delete_run("parent")

    versions = repository.list_capability_versions("parent")
    assert len(versions) == 2
    assert "reviewed" in {row["version_id"] for row in versions}
    assert {row["status"] for row in versions} == {"formal", "verified"}
    assert all(row["source_deleted"] is True for row in versions)
    assert all(row["source_status"] == "deleted" for row in versions)
    reviewed_after_delete = next(row for row in versions if row["version_id"] == "reviewed")
    assert reviewed_after_delete["parent_version_id"] == baseline["version_id"]
    assert reviewed_after_delete["base_version_id"] == baseline["version_id"]
