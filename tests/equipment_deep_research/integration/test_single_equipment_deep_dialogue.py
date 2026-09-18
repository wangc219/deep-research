"""Integration coverage for the single-equipment deep dialogue hand-off.

The reference-weapon action is intentionally tested with a deferred worker:
the HTTP contract and durable hand-off must be correct before a provider is
invoked, and these tests should not depend on provider latency.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import equipment_deep_research.api.app as app_module
from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.deep_thinking import build_reference_capability
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunQueue, SqlRunRepository


class _DeferredThread:
    """Thread double that keeps a queued job durable without executing it."""

    def __init__(self, *, target, name: str, daemon: bool) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon

    def is_alive(self) -> bool:
        return False

    def start(self) -> None:
        return None


def _reference_fixture(tmp_path: Path, monkeypatch, *, execution: dict | None = None):
    output_root = tmp_path / "runs"
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    engine = create_database_engine(f"sqlite:///{tmp_path / 'deep-dialogue.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(
        CreateRunCommand(
            "低空目标拦截",
            "auto",
            [],
            1,
            "analyst",
            execution=dict(execution or {}),
        )
    )
    run_root = output_root / run.run_id
    run_root.mkdir(parents=True)
    # ``report.md`` is the completion marker required for an artifact-backed
    # capability projection on a manually prepared test run.
    (run_root / "report.md").write_text("# report\n", encoding="utf-8")
    (run_root / "capability_images.json").write_text(
        json.dumps(
            [
                {
                    "capability_id": "cap-reference",
                    "card_binding_id": "binding-reference",
                    "hypothesis_id": "hypothesis-reference",
                    "name": "参考拦截无人机",
                    "title": "参考拦截无人机",
                    "primary_equipment_identity": "参考拦截无人机",
                    "equipment_form": "末段拦截无人机",
                    "mechanism_chain": "通过弹上复核压缩末段交战窗口",
                    "military_value": "直接拦截低空目标",
                    "evidence_ids": ["ev-parent"],
                    "selection_status": "reference",
                    "s6_eligible": False,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service.set_status(run.run_id, "completed")
    return service, repository, run, output_root


def test_reference_research_is_single_dialogue_job_without_child_run(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    # A reference action must not invoke the normal run lifecycle.  The
    # deferred worker also makes the assertion deterministic at HTTP return.
    forbidden_calls: list[str] = []

    def forbidden_create(*_args, **_kwargs):
        forbidden_calls.append("create_run")
        raise AssertionError("reference research must not create a child run")

    def forbidden_start(*_args, **_kwargs):
        forbidden_calls.append("start_run")
        raise AssertionError("reference research must not start a child run")

    monkeypatch.setattr(service, "create_run", forbidden_create)
    monkeypatch.setattr(service, "start_run", forbidden_start)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-dialogue-1"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "focus": "补齐末段直接军事效果",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["child_run"] is None
    assert payload["job"]["kind"] == "reference-research"
    assert payload["job"]["child_run_id"] == ""
    assert payload["session"]["kind"] == "reference-research"
    assert payload["session"]["context_refs"]["deep_research_mode"] == (
        "single_equipment_contextual_divergence"
    )
    job = repository.get_deep_job(payload["job"]["job_id"])
    assert job is not None
    assert job["child_run_id"] == ""
    assert job["payload"]["dialogue_mode"] == (
        "single_equipment_contextual_divergence"
    )
    # The server-generated prompt must survive a restart/recovery; an empty
    # question in the durable row would make the recovered job partial.
    assert str(job["payload"]["question"]).strip()
    assert len(service.list_runs()) == 1
    assert forbidden_calls == []


def test_reference_research_fingerprint_replays_same_session_for_new_request_key(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    client = TestClient(create_app(service, event_repository=repository))
    common = {
        "hypothesis_id": "hypothesis-reference",
        "focus": "比较末段复核构型",
    }

    first = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-dialogue-a"},
        json={**common, "question": "先分析任务节点"},
    )
    second = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-dialogue-b"},
        json={**common, "question": "再分析失效边界"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    first_payload = first.json()
    second_payload = second.json()
    assert second_payload["idempotent_replay"] is True
    assert second_payload["job"]["job_id"] == first_payload["job"]["job_id"]
    # Fingerprint replay returns the canonical job projection (without
    # rebuilding the session envelope); its durable session id must still be
    # unchanged.
    assert second_payload["job"]["session_id"] == first_payload["job"]["session_id"]
    assert len(repository.list_deep_jobs(run.run_id)) == 1
    assert len(repository.list_deep_sessions(run.run_id)) == 1


def test_reference_research_uses_server_canonical_identity_and_avoids_empty_child_reads(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    client = TestClient(create_app(service, event_repository=repository))
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-dialogue-canonical"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "candidate": {
                "name": "客户端伪造装备",
                "equipment_form": "伪造构型",
                "evidence_ids": ["ev-client"],
            },
        },
    )
    assert response.status_code == 202
    payload = response.json()
    canonical = payload["session"]["context_refs"]["candidate"]
    assert canonical["name"] == "参考拦截无人机"
    assert canonical["equipment_form"] == "末段拦截无人机"
    assert canonical["evidence_ids"] == ["ev-parent"]

    job_id = payload["job"]["job_id"]
    listed = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research"
    )
    detail = client.get(
        f"/api/v1/runs/{run.run_id}/deep-research/{job_id}"
    )
    assert listed.status_code == 200
    assert detail.status_code == 200
    item = next(row for row in listed.json()["jobs"] if row["job_id"] == job_id)
    assert item["child_run_id"] == ""
    assert not item.get("error")
    assert detail.json()["job"]["child_run_id"] == ""
    assert not detail.json()["job"].get("error")


def test_reference_dialogue_worker_reaches_terminal_publish_without_child(
    tmp_path: Path, monkeypatch
) -> None:
    """The new hand-off must execute the contextual turn, not the old child flow."""

    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    client = TestClient(create_app(service, event_repository=repository))
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-dialogue-worker"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "question": "围绕已有装备成果形成稳定的能力画像补充",
        },
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["job_id"]

    deadline = time.monotonic() + 5.0
    job = repository.get_deep_job(job_id)
    while job is not None and str(job.get("status", "")).lower() in {
        "queued",
        "running",
    } and time.monotonic() < deadline:
        time.sleep(0.02)
        job = repository.get_deep_job(job_id)

    assert job is not None
    assert job["child_run_id"] == ""
    assert job["status"] == "completed", job
    assert job["stage"] == "publish"
    assert not job.get("error")
    versions = repository.list_capability_versions(run.run_id)
    assert versions
    assert all(row["hypothesis_id"] == "hypothesis-reference" for row in versions)
    events = repository.deep_events_after(
        f"deep-session:{run.run_id}:{job['session_id']}", 0
    )
    stages = {str(event.get("stage", "")) for event in events}
    assert {
        "context",
        "s3_divergence",
        "s4_mapping",
        "s6_authoring",
        "validation",
        "publish",
    } <= stages


def test_sql_ledger_success_is_not_downgraded_when_sidecar_projection_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """The optional JSON projection must not outrank the SQLite ledger."""

    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)

    def unavailable_projection(*_args, **_kwargs):
        raise OSError("compatibility sidecar is unavailable")

    monkeypatch.setattr(app_module, "update_deep_session", unavailable_projection)
    client = TestClient(create_app(service, event_repository=repository))
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-sidecar-outage"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "question": "在已有成果上固定单装备发散结果",
        },
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["job_id"]

    deadline = time.monotonic() + 5.0
    job = repository.get_deep_job(job_id)
    while job is not None and str(job.get("status", "")).lower() in {
        "queued",
        "running",
    } and time.monotonic() < deadline:
        time.sleep(0.02)
        job = repository.get_deep_job(job_id)

    assert job is not None
    assert job["status"] == "completed", job
    assert not job.get("error")
    versions = repository.list_capability_versions(run.run_id)
    assert len(versions) == 1
    assert versions[0]["status"] == "pending_verification"
    session = repository.get_deep_session(response.json()["session"]["session_id"])
    assert session is not None
    assert session["status"] == "active"


def test_provider_cannot_relabel_reference_equipment_or_hypothesis(
    tmp_path: Path, monkeypatch
) -> None:
    """Provider directions may enrich a card, but cannot move its lineage."""

    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )

    class _Provider:
        def deep_contextual_dialogue(self, payload):
            assert payload["execution_profile_id"] == "deep_dialogue_v1"
            assert payload["stage_scope"] == [
                "context",
                "divergence",
                "mapping",
                "authoring",
            ]
            assert payload["workflow_dispatch"] == "none"
            return {
                "visible_summary": ["围绕参考装备形成一个竞争方向"],
                "divergence_steps": [
                    {
                        "title": "机理比较",
                        "text": "比较末段复核与传统拦截路径",
                        "stage": "divergence",
                    }
                ],
                "concept_directions": [
                    {
                        # Deliberately attempt to switch to another weapon and
                        # hypothesis. The service must retain canonical values.
                        "name": "伪造坦克方向",
                        "hypothesis_id": "malicious-hypothesis",
                        "equipment_form": "主战坦克",
                        "operational_mechanism": "通过独立复核压缩坦克交战窗口",
                        "military_value": "直接打击目标",
                        "direct_military_effects": "形成直接拦截效果",
                        "related_scenario": "低空目标拦截",
                        "capability_gap": "末段识别不足",
                        "failure_boundary": "强干扰环境需验证",
                        "validation_plan": "开展仿真与实装复核",
                        "direct_evidence_refs": ["ev-parent"],
                        "stable": True,
                    }
                ],
                "deep_divergence_status": "completed",
            }

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def create(self, *_args, **_kwargs):
            return _Provider()

    # App construction needs the real registry to load the normal catalog;
    # swap it only while the deferred worker handles this request.
    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-dialogue-provider-lock"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "question": "请比较一个竞争方向并固定稳定结果",
        },
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["job_id"]

    deadline = time.monotonic() + 5.0
    job = repository.get_deep_job(job_id)
    while job is not None and str(job.get("status", "")).lower() in {
        "queued",
        "running",
    } and time.monotonic() < deadline:
        time.sleep(0.02)
        job = repository.get_deep_job(job_id)

    assert job is not None
    assert job["status"] == "completed", job
    versions = repository.list_capability_versions(run.run_id)
    assert versions
    pending = next(
        row
        for row in versions
        if row["status"] == "pending_verification"
    )
    snapshot = pending["snapshot"]
    assert snapshot["hypothesis_id"] == "hypothesis-reference"
    assert snapshot["card_binding_id"] == "binding-reference"
    assert snapshot["name"] == "参考拦截无人机"
    # Older capability snapshots do not expose ``equipment_form`` as a
    # top-level field.  In that shape the authored technology module is the
    # canonical identity projection; either representation must retain the
    # server-bound form and must not adopt the provider's relabeling.
    equipment_form = snapshot.get("equipment_form") or snapshot.get(
        "primary_equipment_identity"
    )
    if equipment_form:
        assert equipment_form == "末段拦截无人机"
    else:
        technology = snapshot["capability_portrait_modules"][
            "technology_implementation"
        ]
        assert "末段拦截无人机" in technology
        assert "主战坦克" not in technology
    assert snapshot["evidence_ids"] == ["ev-parent"]
    assert len(repository.list_deep_jobs(run.run_id)) == 1


def test_reference_retry_reprojects_existing_version_without_appending_duplicate(
    tmp_path: Path, monkeypatch
) -> None:
    """A retry repairs a projection using the same version row and job id."""

    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    client = TestClient(create_app(service, event_repository=repository))
    original_thread = app_module.Thread
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    first = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-retry-initial"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "focus": "重试投影",
            "question": "形成稳定能力画像",
        },
    )
    assert first.status_code == 202
    job_id = first.json()["job"]["job_id"]
    session_id = first.json()["session"]["session_id"]
    artifact = build_reference_capability(
        run_id=run.run_id,
        query=run.topic,
        candidate={
            "name": "参考拦截无人机",
            "card_binding_id": "binding-reference",
            "hypothesis_id": "hypothesis-reference",
            "equipment_form": "末段拦截无人机",
            "mechanism_chain": "通过弹上复核压缩末段交战窗口",
            "evidence_ids": ["ev-parent"],
        },
        focus="重试投影",
        source_session_id=session_id,
    )
    repository.save_capability_version(
        version_id="reference-retry-existing-version",
        parent_run_id=run.run_id,
        card_binding_id="binding-reference",
        hypothesis_id="hypothesis-reference",
        snapshot=artifact,
        status="pending_verification",
    )
    repository.update_deep_job(
        job_id,
        stage="validation",
        status="partial",
        error="projection unavailable",
    )
    before = repository.list_capability_versions(run.run_id)
    assert len(before) == 1

    # Let the retry's short projection worker execute. It should discover the
    # already committed version and never call save_capability_version again.
    monkeypatch.setattr(app_module, "Thread", original_thread)
    retry = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-retry-repair"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "focus": "重试投影",
            "question": "形成稳定能力画像",
            "retry": True,
        },
    )
    assert retry.status_code == 202
    assert retry.json()["job"]["job_id"] == job_id

    deadline = time.monotonic() + 5.0
    job = repository.get_deep_job(job_id)
    while job is not None and str(job.get("status", "")).lower() in {
        "queued",
        "running",
    } and time.monotonic() < deadline:
        time.sleep(0.02)
        job = repository.get_deep_job(job_id)
    assert job is not None
    assert job["status"] == "completed", job
    after = repository.list_capability_versions(run.run_id)
    assert len(after) == 1
    assert after[0]["version_id"] == before[0]["version_id"]
