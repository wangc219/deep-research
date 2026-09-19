"""Focused authorization/idempotency regression checks for deep research."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

from fastapi.testclient import TestClient

from equipment_deep_research.api import app as app_module
from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunQueue, SqlRunRepository


def _fixture(tmp_path: Path, *, tenant_id: str = ""):
    repository = SqlRunRepository(
        create_database_engine(f"sqlite:///{tmp_path / 'deep-auth.db'}")
    )
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(repository.engine),
    )
    run = service.create_run(
        CreateRunCommand(
            "topic",
            "auto",
            [],
            1,
            "analyst",
            tenant_id=tenant_id,
        )
    )
    return service, repository, run


def test_deep_message_mutation_fails_closed_when_session_read_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_deep_session(
        session_id="session-message-outage",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    monkeypatch.setattr(
        repository,
        "get_deep_session",
        lambda _session_id: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-message-outage/messages",
        headers={"Idempotency-Key": "message-read-outage"},
        json={"content": "继续分析"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "deep session ledger unavailable"


def test_deep_merge_mutation_fails_closed_when_session_read_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_deep_session(
        session_id="session-merge-outage",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    monkeypatch.setattr(
        repository,
        "get_deep_session",
        lambda _session_id: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-merge-outage/merge",
        headers={"Idempotency-Key": "merge-read-outage"},
        json={"artifact_id": "artifact"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "deep session ledger unavailable"


def test_auditor_cannot_merge_deep_capability(tmp_path: Path) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_deep_session(
        session_id="session-auditor-read-only",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-auditor-read-only/merge",
        headers={"X-Role": "auditor", "Idempotency-Key": "auditor-merge"},
        json={"artifact_id": "artifact"},
    )

    assert response.status_code == 403


def test_session_management_mutations_map_ledger_read_outage_to_503(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_deep_session(
        session_id="session-management-outage",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    source = repository.append_deep_message(
        session_id="session-management-outage",
        role="user",
        content="fork source",
    )
    monkeypatch.setattr(
        repository,
        "get_deep_session",
        lambda _session_id: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))
    base = f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-management-outage"

    managed = client.patch(base, json={"title": "new title"})
    deleted = client.delete(base)
    forked = client.post(
        f"{base}/branches",
        headers={"Idempotency-Key": "fork-read-outage"},
        json={"from_message_id": source["message_id"]},
    )

    for response in (managed, deleted, forked):
        assert response.status_code == 503
        assert "ledger unavailable" in response.json()["detail"]


def test_session_manage_maps_ledger_write_outage_to_503(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_deep_session(
        session_id="session-manage-write-outage",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    monkeypatch.setattr(
        repository,
        "update_deep_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.patch(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-manage-write-outage",
        json={"title": "new title"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "deep session ledger unavailable"


def test_steer_maps_job_ledger_read_outage_to_503(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_or_get_deep_job(
        job_id="job-steer-read-outage",
        parent_run_id=run.run_id,
        session_id="session-steer-read-outage",
        fingerprint="fingerprint-steer-read-outage",
    )
    monkeypatch.setattr(
        repository,
        "get_deep_job",
        lambda _job_id: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/job-steer-read-outage/steers",
        json={
            "content": "change direction",
            "client_steer_id": "client-steer-read-outage",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "deep job ledger unavailable"


def test_branch_fork_is_idempotent_and_explicit_id_conflicts(
    tmp_path: Path,
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_deep_session(
        session_id="session-fork-idempotent",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    source = repository.append_deep_message(
        session_id="session-fork-idempotent",
        role="user",
        content="fork source",
    )
    client = TestClient(create_app(service, event_repository=repository))
    path = (
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/"
        "session-fork-idempotent/branches"
    )
    payload = {
        "from_message_id": source["message_id"],
        "branch_id": "explicit-branch",
        "title": "explicit branch",
    }

    first = client.post(
        path,
        headers={"Idempotency-Key": "fork-idempotent"},
        json=payload,
    )
    replay = client.post(
        path,
        headers={"Idempotency-Key": "fork-idempotent"},
        json=payload,
    )
    conflict = client.post(
        path,
        headers={"Idempotency-Key": "fork-different-request"},
        json=payload,
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert "already exists" in conflict.json()["detail"]


def test_global_session_history_filters_scope_before_limit(tmp_path: Path) -> None:
    service, repository, tenant_a_run = _fixture(tmp_path, tenant_id="tenant-a")
    tenant_b_run = service.create_run(
        CreateRunCommand(
            "tenant-b topic",
            "auto",
            [],
            1,
            "analyst",
            tenant_id="tenant-b",
        )
    )
    repository.create_deep_session(
        session_id="history-tenant-a",
        parent_run_id=tenant_a_run.run_id,
        kind="deep-thinking",
        scope={"tenant_id": "tenant-a"},
    )
    repository.create_deep_session(
        session_id="history-tenant-b",
        parent_run_id=tenant_b_run.run_id,
        kind="deep-thinking",
        scope={"tenant_id": "tenant-b"},
    )
    client = TestClient(create_app(service, event_repository=repository))

    scoped = client.get(
        "/api/v1/deep-thinking/sessions/history?limit=1",
        headers={"X-Tenant-ID": "tenant-a"},
    )
    unscoped = client.get("/api/v1/deep-thinking/sessions/history?limit=10")

    assert scoped.status_code == 200
    assert [item["session_id"] for item in scoped.json()["items"]] == [
        "history-tenant-a"
    ]
    assert unscoped.status_code == 200
    assert unscoped.json()["items"] == []


def test_trusted_identity_overrides_forged_reviewer_header_in_strict_mode(
    tmp_path: Path,
) -> None:
    """Strict mode must not let a browser's X-Role grant reviewer access."""

    service, repository, run = _fixture(tmp_path, tenant_id="tenant-a")
    repository.create_deep_session(
        session_id="session-verify",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    client = TestClient(create_app(service, event_repository=repository, strict_auth=True))

    # No gateway claim: caller-controlled X-Role is rejected before routing.
    denied = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"X-Role": "reviewer"},
    )
    assert denied.status_code == 401

    # A verified analyst claim is accepted but cannot perform reviewer-only
    # version verification.
    analyst_headers = {
        "X-Authenticated-Tenant-ID": "tenant-a",
        "X-Authenticated-Roles": "analyst",
    }
    analyst_forbidden = client.post(
        f"/api/v1/runs/{run.run_id}/capability-versions/missing/verify",
        headers={**analyst_headers, "Idempotency-Key": "verify-as-analyst"},
        json={"status": "verified"},
    )
    assert analyst_forbidden.status_code == 403

    # Supplying a browser-controlled reviewer role alongside the trusted
    # analyst claim is a conflict, never an elevation.
    forged = client.post(
        f"/api/v1/runs/{run.run_id}/capability-versions/missing/verify",
        headers={
            **analyst_headers,
            "X-Role": "reviewer",
            "Idempotency-Key": "verify-forged-reviewer",
        },
        json={"status": "verified"},
    )
    assert forged.status_code == 403
    assert "conflicts" in forged.json()["detail"]

    # The same route recognizes a gateway-asserted reviewer.  A missing
    # version reaches its ordinary 404 instead of the role gate.
    reviewer = client.post(
        f"/api/v1/runs/{run.run_id}/capability-versions/missing/verify",
        headers={
            "X-Authenticated-Tenant-ID": "tenant-a",
            "X-Authenticated-Roles": "reviewer",
            "Idempotency-Key": "verify-as-reviewer",
        },
        json={"status": "verified"},
    )
    assert reviewer.status_code == 404


def test_analyst_can_delete_and_restore_deep_version_but_not_formal_baseline(
    tmp_path: Path,
) -> None:
    service, repository, run = _fixture(tmp_path)
    baseline = repository.ensure_capability_baseline(
        parent_run_id=run.run_id,
        card_binding_id="binding-managed",
        hypothesis_id="hypothesis-managed",
        snapshot={"name": "正式 S6 基线"},
    )
    version = repository.save_capability_version(
        version_id="version-managed",
        parent_run_id=run.run_id,
        card_binding_id="binding-managed",
        hypothesis_id="hypothesis-managed",
        snapshot={"name": "A-O 命名深研版本"},
    )
    client = TestClient(create_app(service, event_repository=repository))

    deleted = client.delete(
        f"/api/v1/runs/{run.run_id}/capability-versions/{version['version_id']}",
        headers={"X-Role": "analyst", "Idempotency-Key": "delete-version-managed"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["version"]["status"] == "deleted"
    assert deleted.json()["version"]["previous_status"] == "pending_verification"

    restored = client.post(
        f"/api/v1/runs/{run.run_id}/capability-versions/{version['version_id']}/restore",
        headers={"X-Role": "analyst", "Idempotency-Key": "restore-version-managed"},
    )
    assert restored.status_code == 200
    assert restored.json()["version"]["status"] == "pending_verification"
    assert restored.json()["version"]["previous_status"] == ""

    protected = client.delete(
        f"/api/v1/runs/{run.run_id}/capability-versions/{baseline['version_id']}",
        headers={"X-Role": "analyst", "Idempotency-Key": "delete-formal-baseline"},
    )
    assert protected.status_code == 422
    assert "immutable" in protected.json()["detail"]


def test_analyst_can_purge_soft_deleted_deep_version(
    tmp_path: Path,
) -> None:
    service, repository, run = _fixture(tmp_path)
    version = repository.save_capability_version(
        version_id="version-purge-api",
        parent_run_id=run.run_id,
        card_binding_id="binding-purge",
        hypothesis_id="hypothesis-purge",
        snapshot={"name": "待永久删除版本"},
    )
    client = TestClient(create_app(service, event_repository=repository))

    live_purge = client.delete(
        f"/api/v1/runs/{run.run_id}/capability-versions/{version['version_id']}/permanent",
        headers={"X-Role": "analyst", "Idempotency-Key": "purge-live-version"},
    )
    assert live_purge.status_code == 422
    assert "soft-deleted" in live_purge.json()["detail"]

    deleted = client.delete(
        f"/api/v1/runs/{run.run_id}/capability-versions/{version['version_id']}",
        headers={"X-Role": "analyst", "Idempotency-Key": "soft-delete-before-purge"},
    )
    assert deleted.status_code == 200

    purged = client.delete(
        f"/api/v1/runs/{run.run_id}/capability-versions/{version['version_id']}/permanent",
        headers={"X-Role": "analyst", "Idempotency-Key": "purge-deleted-version"},
    )
    assert purged.status_code == 200
    body = purged.json()
    assert body["purged"] is True
    assert body["version_id"] == version["version_id"]
    assert repository.get_capability_version(
        version["version_id"], parent_run_id=run.run_id
    ) is None


def test_deep_sse_is_scoped_to_the_authenticated_parent_run(
    tmp_path: Path,
) -> None:
    service, repository, run = _fixture(tmp_path, tenant_id="tenant-b")
    repository.create_deep_session(
        session_id="session-scope",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    repository.append_deep_event(
        stream_id=f"deep-session:{run.run_id}:session-scope",
        parent_run_id=run.run_id,
        session_id="session-scope",
        event_type="deep_stage",
        stage="publish",
        status="completed",
        progress=1.0,
        delta={"kind": "summary", "text": "tenant-b only"},
    )
    repository.update_deep_session("session-scope", status="failed")
    client = TestClient(create_app(service, event_repository=repository, strict_auth=True))
    path = f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/session-scope/events"

    denied = client.get(
        path,
        headers={
            "X-Authenticated-Tenant-ID": "tenant-a",
            "X-Authenticated-Roles": "analyst",
        },
    )
    assert denied.status_code == 403
    assert "tenant-b only" not in denied.text

    allowed = client.get(
        path,
        headers={
            "X-Authenticated-Tenant-ID": "tenant-b",
            "X-Authenticated-Roles": "analyst",
            "Last-Event-ID": "0",
        },
    )
    assert allowed.status_code == 200
    assert "tenant-b only" in allowed.text


def test_deep_write_requires_idempotency_key_even_for_legacy_adapter(
    tmp_path: Path,
) -> None:
    service, repository, run = _fixture(tmp_path)
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        json={"kind": "deep-thinking"},
    )

    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]


def test_cancel_update_outage_releases_claim_for_retry(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_or_get_deep_job(
        job_id="job-cancel-retry",
        parent_run_id=run.run_id,
        session_id="session-cancel-retry",
        idempotency_key="seed-cancel",
        fingerprint="seed-cancel-fingerprint",
    )
    original_update = repository.update_deep_job
    monkeypatch.setattr(
        repository,
        "update_deep_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))
    first = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/job-cancel-retry/cancel",
        headers={"Idempotency-Key": "cancel-retry-key"},
    )
    assert first.status_code == 503

    # Restore the writer and retry with the same key.  A released claim must
    # permit the operation to reach the durable cancellation transition.
    monkeypatch.setattr(repository, "update_deep_job", original_update)
    second = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/job-cancel-retry/cancel",
        headers={"Idempotency-Key": "cancel-retry-key"},
    )
    assert second.status_code == 200
    assert second.json()["status"] == "cancelled"


def test_cancel_uses_session_bound_after_initial_job_read(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run = _fixture(tmp_path)
    client = TestClient(create_app(service, event_repository=repository))
    repository.create_deep_session(
        session_id="session-bound-during-cancel",
        parent_run_id=run.run_id,
        kind="reference-research",
    )
    repository.create_or_get_deep_job(
        job_id="job-bound-during-cancel",
        parent_run_id=run.run_id,
        session_id="",
        idempotency_key="seed-bind-during-cancel",
        fingerprint="fingerprint-bind-during-cancel",
    )
    original_update = repository.update_deep_job

    def bind_then_cancel(job_id: str, **values):
        repository.bind_deep_job_session(
            job_id,
            parent_run_id=run.run_id,
            session_id="session-bound-during-cancel",
        )
        return original_update(job_id, **values)

    monkeypatch.setattr(repository, "update_deep_job", bind_then_cancel)

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/job-bound-during-cancel/cancel",
        headers={"Idempotency-Key": "cancel-after-bind"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert repository.get_deep_job("job-bound-during-cancel")["session_id"] == (
        "session-bound-during-cancel"
    )
    assert repository.get_deep_session("session-bound-during-cancel")["status"] == (
        "cancelled"
    )


def test_cancel_completed_deep_job_preserves_terminal_projection(
    tmp_path: Path,
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_deep_session(
        session_id="session-completed-cancel",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    repository.create_or_get_deep_job(
        job_id="job-completed-cancel",
        parent_run_id=run.run_id,
        session_id="session-completed-cancel",
        idempotency_key="completed-cancel-seed",
        fingerprint="completed-cancel-fingerprint",
    )
    repository.update_deep_job(
        "job-completed-cancel",
        stage="publish",
        status="completed",
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/job-completed-cancel/cancel",
        headers={"Idempotency-Key": "completed-cancel-request"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["already_terminal"] is True
    assert payload["job"]["status"] == "completed"
    assert repository.get_deep_job("job-completed-cancel")["status"] == "completed"
    assert not [
        event
        for event in repository.events_after(run.run_id, 0)
        if event["event_type"] == "deep_job_cancelled"
    ]


def test_concurrent_cancel_only_emits_one_terminal_transition(
    tmp_path: Path, monkeypatch
) -> None:
    """A second cancellation replay must not repeat terminal side effects."""

    service, repository, run = _fixture(tmp_path)
    child = service.create_run(
        CreateRunCommand("deep child", "auto", [], 1, "analyst")
    )
    service.set_status(child.run_id, "researching")
    repository.create_deep_session(
        session_id="session-concurrent-cancel",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    repository.create_or_get_deep_job(
        job_id="job-concurrent-cancel",
        parent_run_id=run.run_id,
        session_id="session-concurrent-cancel",
        child_run_id=child.run_id,
        idempotency_key="concurrent-cancel-seed",
        fingerprint="concurrent-cancel-fingerprint",
    )
    # Keep the fixture outside the dispatcher recovery queue while the two
    # HTTP callers are synchronized at the cancellation write.
    repository.update_deep_job(
        "job-concurrent-cancel", stage="context", status="running"
    )

    update_barrier = Barrier(2)
    original_update = repository.update_deep_job

    def synchronized_update(*args, **kwargs):
        if kwargs.get("status") == "cancelled":
            update_barrier.wait(timeout=10)
        return original_update(*args, **kwargs)

    monkeypatch.setattr(repository, "update_deep_job", synchronized_update)
    session_updates: list[tuple[str, str]] = []
    cleanup_calls: list[str] = []

    original_session_update = repository.update_deep_session

    def record_session_update(session_id: str, *, status=None, **kwargs):
        session_updates.append((session_id, str(status or "")))
        return original_session_update(session_id, status=status, **kwargs)

    def record_cleanup(run_id: str):
        cleanup_calls.append(run_id)
        return SimpleNamespace(run_id=run_id, terminated=True)

    monkeypatch.setattr(repository, "update_deep_session", record_session_update)
    monkeypatch.setattr(app_module, "terminate_run_process_groups", record_cleanup)
    application = create_app(service, event_repository=repository)

    def cancel(key: str):
        with TestClient(application) as client:
            return client.post(
                f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/job-concurrent-cancel/cancel",
                headers={"Idempotency-Key": key},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(cancel, ("cancel-a", "cancel-b")))

    assert [response.status_code for response in responses] == [200, 200]
    payloads = [response.json() for response in responses]
    assert {payload["status"] for payload in payloads} == {"cancelled"}
    assert sorted(payload["already_terminal"] for payload in payloads) == [False, True]
    assert len(cleanup_calls) == 1
    assert session_updates == [("session-concurrent-cancel", "cancelled")]
    cancel_events = [
        event
        for event in repository.events_after(run.run_id, 0)
        if event["event_type"] == "deep_job_cancelled"
    ]
    assert len(cancel_events) == 1


def test_cancel_retries_when_state_version_changes_before_write(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_deep_session(
        session_id="session-cancel-state-race",
        parent_run_id=run.run_id,
        kind="deep-thinking",
    )
    repository.create_or_get_deep_job(
        job_id="job-cancel-state-race",
        parent_run_id=run.run_id,
        session_id="session-cancel-state-race",
        idempotency_key="cancel-state-race-seed",
        fingerprint="cancel-state-race-fingerprint",
    )
    repository.update_deep_job(
        # Stage-level completed is deliberately non-terminal until publish,
        # while keeping the fixture out of restart recovery.
        "job-cancel-state-race", stage="context", status="completed"
    )
    original_update = repository.update_deep_job
    calls = 0

    def race_once(*args, **kwargs):
        nonlocal calls
        if kwargs.get("status") == "cancelled" and calls == 0:
            calls += 1
            # Simulate a concurrent non-terminal stage write losing the
            # repository's state-version compare-and-swap on the first try.
            return repository.get_deep_job("job-cancel-state-race")
        calls += 1
        return original_update(*args, **kwargs)

    monkeypatch.setattr(repository, "update_deep_job", race_once)
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/job-cancel-state-race/cancel",
        headers={"Idempotency-Key": "cancel-state-race-request"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert calls == 2
    assert repository.get_deep_job("job-cancel-state-race")["status"] == "cancelled"


def test_reference_job_detail_fails_closed_when_link_projection_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run = _fixture(tmp_path)
    repository.create_or_get_deep_job(
        job_id="job-link-outage",
        parent_run_id=run.run_id,
        kind="reference-research",
        idempotency_key="link-outage-seed",
        fingerprint="link-outage-fingerprint",
    )
    monkeypatch.setattr(
        repository,
        "list_deep_run_links",
        lambda _run_id: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.get(
        f"/api/v1/runs/{run.run_id}/deep-research/job-link-outage"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "deep job ledger unavailable"
