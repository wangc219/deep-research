"""Integration coverage for the single-equipment deep dialogue hand-off.

The reference-weapon action is intentionally tested with a deferred worker:
the HTTP contract and durable hand-off must be correct before a provider is
invoked, and these tests should not depend on provider latency.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import equipment_deep_research.api.app as app_module
from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.deep_conversation import branch_working_memory
from equipment_deep_research.deep_thinking import build_reference_capability
from equipment_deep_research.deep_runtime.loop import run_deep_research_turn
from equipment_deep_research.deep_runtime.mcp_transport import HostMCPMount, MCPTransportConfig
from equipment_deep_research.deep_runtime.workspace import DeepWorkspace
from equipment_deep_research.providers.fake import ScriptedFakeProvider
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


class _InlineThread(_DeferredThread):
    """Run a queued worker immediately for deterministic ledger tests."""

    def start(self) -> None:
        self.target()


def test_public_deep_event_preserves_handoff_contract_without_internal_payload() -> None:
    public = app_module._deep_public_event_payload(
        {
            "event_type": "deep_agent_handoff",
            "session_id": "session-1",
            "job_id": "job-1",
            "stage": "council_critique",
            "status": "running",
            "progress": 0.52,
            "delta": {
                "kind": "summary",
                "text": "三路候选已交给对抗裁决。",
                "from_agent_id": "deep_dialogue_council",
                "to_agent_id": "deep_dialogue_adversarial_judge",
                "handoff_kind": "proposal_review",
                "deliverable_refs": ["候选甲", "候选乙"],
                "tool_name": "research_council",
                "tool_call_id": "deep-turn-2",
                "turn_index": 2,
                "duration_ms": 37.5,
                "active_skill_ids": ["constraint_reversal", "x" * 200],
                "plugin_ids": ["deep-innovation-methods"],
                "hidden_reasoning": "must not leave the server",
            },
            "provider_session": "private-handle",
        },
        run_id="run-1",
        sequence=17,
        event_type="deep_agent_handoff",
    )

    assert public["event_type"] == "deep_agent_handoff"
    assert public["sequence"] == 17
    assert public["delta"]["from_agent_id"] == "deep_dialogue_council"
    assert public["delta"]["to_agent_id"] == "deep_dialogue_adversarial_judge"
    assert public["delta"]["deliverable_refs"] == ["候选甲", "候选乙"]
    assert public["delta"]["tool_name"] == "research_council"
    assert public["delta"]["tool_call_id"] == "deep-turn-2"
    assert public["delta"]["turn_index"] == 2
    assert public["delta"]["duration_ms"] == 37.5
    assert public["delta"]["active_skill_ids"] == [
        "constraint_reversal",
        "x" * 140,
    ]
    assert public["delta"]["plugin_ids"] == ["deep-innovation-methods"]
    assert "hidden_reasoning" not in public["delta"]
    assert "provider_session" not in public


def test_public_deep_event_preserves_context_compaction_counts() -> None:
    public = app_module._deep_public_event_payload(
        {
            "event_type": "deep_context_compacted",
            "session_id": "session-1",
            "job_id": "job-1",
            "stage": "context",
            "status": "completed",
            "progress": 0.12,
            "kind": "summary",
            "text": "已将前 3 轮研究压缩为决策记忆，当前窗口保留最近 2 轮。",
            "living_turns": 2,
            "archived_turns": 3,
        },
        run_id="run-1",
        sequence=4,
        event_type="deep_context_compacted",
    )

    assert public["event_type"] == "deep_context_compacted"
    assert public["delta"]["living_turns"] == 2
    assert public["delta"]["archived_turns"] == 3
    assert public["delta"]["text"].startswith("已将前 3 轮")


def test_session_tool_interaction_preserves_bounded_runtime_fields() -> None:
    interaction = app_module._public_session_interaction(
        {
            "event_type": "tool_call",
            "agent_id": "deep-runtime",
            "tool_name": "deepen",
            "call_id": "legacy-call-id",
            "tool_call_id": "deep-turn-3",
            "turn_index": 3,
            "duration_ms": 18.25,
            "active_skill_ids": ["skill-a", "x" * 200],
            "plugin_ids": ["deep-innovation-methods"],
            "provider_state": "must-not-escape",
        }
    )

    assert interaction is not None
    assert interaction["event_id"] == "legacy-call-id"
    assert interaction["details"]["call_id"] == "legacy-call-id"
    assert interaction["details"]["tool_call_id"] == "deep-turn-3"
    assert interaction["details"]["turn_index"] == 3
    assert interaction["details"]["duration_ms"] == 18.25
    assert interaction["details"]["active_skill_ids"] == ["skill-a", "x" * 140]
    assert interaction["details"]["plugin_ids"] == ["deep-innovation-methods"]
    assert "provider_state" not in interaction["details"]


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


def _wait_for_deep_job(repository: SqlRunRepository, job_id: str) -> dict:
    deadline = time.monotonic() + 5.0
    job = repository.get_deep_job(job_id)
    while job is not None and str(job.get("status", "")).lower() in {
        "queued",
        "running",
    } and time.monotonic() < deadline:
        time.sleep(0.02)
        job = repository.get_deep_job(job_id)
    assert job is not None
    return job


def test_two_web_jobs_reuse_one_app_owned_mcp_session_and_shutdown_reaps_it(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "wire-test"},
    )
    server = Path(__file__).parents[1] / "fixtures" / "mcp_loopback_server.py"
    mount = HostMCPMount(
        "host:echo",
        MCPTransportConfig(
            "stdio", command=sys.executable, args=(str(server),), timeout=5
        ),
        ("echo",),
    )
    app = create_app(service, event_repository=repository, mcp_mounts=(mount,))

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def create(self, *_args, **_kwargs):
            # /help is a core tool and needs no model completion. Returning a
            # real ModelProvider contract proves the Web wrapper selects the
            # shared deep runtime instead of a test-only high-level callback.
            return ScriptedFakeProvider([])

    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    with TestClient(app) as client:
        first = client.post(
            f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
            headers={"Idempotency-Key": "web-mcp-first"},
            json={"hypothesis_id": "hypothesis-reference", "question": "/help"},
        )
        assert first.status_code == 202
        first_job = _wait_for_deep_job(repository, first.json()["job"]["job_id"])
        assert first_job["status"] == "completed", first_job
        session_id = first.json()["session"]["session_id"]
        host = app.state.deep_mcp_host
        first_adapter = host._adapters["host:echo"]
        first_owner = first_adapter._owner
        assert first_owner is not None and not first_owner.done()

        second = client.post(
            f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
            headers={"Idempotency-Key": "web-mcp-second"},
            json={"content": "/help"},
        )
        assert second.status_code == 202
        second_job = _wait_for_deep_job(repository, second.json()["job"]["job_id"])
        assert second_job["status"] == "completed", second_job
        assert host._adapters["host:echo"] is first_adapter
        assert host._adapters["host:echo"]._owner is first_owner

    assert app.state.deep_mcp_host._closed is True
    assert app.state.deep_mcp_host._thread is not None
    assert not app.state.deep_mcp_host._thread.is_alive()


def test_plugin_state_is_admin_only_and_capability_catalog_is_redacted(
    tmp_path: Path, monkeypatch
) -> None:
    service, _, run, _ = _reference_fixture(tmp_path, monkeypatch)
    state_path = tmp_path / "runtime" / "deep-plugins.json"
    monkeypatch.setenv("EQUIPMENT_DR_DEEP_PLUGIN_STATE", str(state_path))
    client = TestClient(create_app(service))

    catalog_response = client.get("/api/v1/deep-thinking/capabilities")
    assert catalog_response.status_code == 200
    catalog = catalog_response.json()
    plugin = next(
        item
        for item in catalog["plugins"]
        if item["plugin_id"] == "deep-innovation-methods"
    )
    assert plugin["enabled"] is False
    serialized = json.dumps(catalog, ensure_ascii=False)
    assert str(state_path) not in serialized
    assert "fingerprint" not in serialized
    assert '"root"' not in serialized

    for role in ("analyst", "reviewer"):
        denied = client.patch(
            "/api/v1/deep-thinking/plugins/deep-innovation-methods",
            headers={"X-Role": role},
            json={"enabled": True},
        )
        assert denied.status_code == 403
        assert not state_path.exists()

    enabled = client.patch(
        "/api/v1/deep-thinking/plugins/deep-innovation-methods",
        headers={"X-Role": "admin"},
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["plugin"]["enabled"] is True

    disabled = client.patch(
        "/api/v1/deep-thinking/plugins/deep-innovation-methods",
        headers={"X-Role": "admin"},
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["plugin"]["enabled"] is False
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["plugins"]["deep-innovation-methods"]["enabled"] is False

    for skill_id in ("missing-skill", "constraint-reversal"):
        rejected = client.post(
            f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
            headers={"Idempotency-Key": f"rejected-{skill_id}"},
            json={
                "question": "分析当前装备方向",
                "active_skill_ids": [skill_id],
            },
        )
        assert rejected.status_code == 422


def test_same_message_text_with_distinct_parent_messages_keeps_separate_turns(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    client = TestClient(create_app(service, event_repository=repository))
    session_response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "parent-seed"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
            "question": "建立对话基线",
        },
    )
    assert session_response.status_code == 201
    session_id = session_response.json()["session"]["session_id"]
    root_message_id = session_response.json()["user_message"]["message_id"]
    first_parent = repository.append_deep_message(
        session_id=session_id,
        role="assistant",
        content="第一条父消息",
        parent_message_id=root_message_id,
    )
    second_parent = repository.append_deep_message(
        session_id=session_id,
        role="assistant",
        content="第二条父消息",
        parent_message_id=root_message_id,
    )

    common = {
        "content": "沿同一问题继续分析",
        "create_artifact": False,
    }
    first = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
        headers={"Idempotency-Key": "parent-turn-a"},
        json={**common, "parent_message_id": first_parent["message_id"]},
    )
    second = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
        headers={"Idempotency-Key": "parent-turn-b"},
        json={**common, "parent_message_id": second_parent["message_id"]},
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["user_message"]["message_id"] != second.json()["user_message"]["message_id"]
    assert first.json()["job"]["job_id"] != second.json()["job"]["job_id"]
    assert first.json()["user_message"]["parent_message_id"] == first_parent["message_id"]
    assert second.json()["user_message"]["parent_message_id"] == second_parent["message_id"]

    replay = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
        headers={"Idempotency-Key": "parent-turn-a"},
        json={**common, "parent_message_id": first_parent["message_id"]},
    )
    assert replay.status_code == 202
    assert replay.json()["job"]["job_id"] == first.json()["job"]["job_id"]
    assert replay.json()["user_message"]["message_id"] == first.json()["user_message"]["message_id"]
    messages = repository.list_deep_messages(session_id)
    same_text = [
        item
        for item in messages
        if item.get("role") == "user" and item.get("content") == common["content"]
    ]
    assert len(same_text) == 2
    assert {
        item["parent_message_id"] for item in same_text
    } == {first_parent["message_id"], second_parent["message_id"]}


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
    assert job["payload"]["create_artifact"] is False
    # The server-generated prompt must survive a restart/recovery; an empty
    # question in the durable row would make the recovered job partial.
    assert str(job["payload"]["question"]).strip()
    assert len(service.list_runs()) == 1
    assert forbidden_calls == []


def test_artifact_only_parent_is_materialized_before_deep_worker_execution(
    tmp_path: Path, monkeypatch
) -> None:
    """A CLI-produced artifact can safely become a durable dialogue parent."""

    service, repository, run, output_root = _reference_fixture(tmp_path, monkeypatch)
    run_root = output_root / run.run_id
    (run_root / "round_summary.json").write_text(
        json.dumps(
            {
                "mode": "fake",
                "resolved_route": "auto",
                "problem": {
                    "topic": run.topic,
                    "selected_agent_ids": [],
                    "max_rounds_hint": 1,
                },
                "provider": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # Remove the application row while retaining the completed artifact. The
    # API must read it as historical data, then materialize it for the worker.
    with repository.engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM runs WHERE run_id = ?", (run.run_id,)
        )
    monkeypatch.setattr(app_module, "Thread", _InlineThread)
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "artifact-only-materialize"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "question": "/help",
        },
    )

    assert response.status_code == 202, response.text
    job = repository.get_deep_job(response.json()["job"]["job_id"])
    assert job is not None
    assert job["status"] == "completed", job
    assert job["error"] == ""
    assert repository.get(run.run_id).run_id == run.run_id
    assert len(repository.list_deep_messages(response.json()["session"]["session_id"])) == 2


def test_completed_runtime_checkpoint_is_reconciled_without_provider_replay(
    tmp_path: Path, monkeypatch
) -> None:
    """A process exit after final response must not spend a second model turn."""

    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "must-not-be-called"},
    )
    session_id = "session-checkpoint-reconcile"
    job_id = "job-checkpoint-reconcile"
    repository.create_deep_session(
        session_id=session_id,
        parent_run_id=run.run_id,
        kind="reference-research",
        title="恢复 checkpoint",
        hypothesis_id="hypothesis-reference",
        query_snapshot={
            "query": run.topic,
            "context": {"candidate": {"hypothesis_id": "hypothesis-reference"}},
        },
    )
    repository.append_deep_message(
        session_id=session_id,
        role="user",
        content="已完成的真实问题",
        turn_id=job_id,
    )
    repository.append_deep_message(
        session_id=session_id,
        role="assistant",
        content="已持久化的最终答复",
        turn_id=job_id,
    )
    repository.create_or_get_deep_job(
        job_id=job_id,
        parent_run_id=run.run_id,
        session_id=session_id,
        kind="deep-dialogue-v1",
        idempotency_key="checkpoint-reconcile",
        payload={
            "session_id": session_id,
            "question": "已完成的真实问题",
            "dialogue_mode": "single_equipment_contextual_divergence",
        },
        checkpoint={
            "phase": "final_response",
            "status": "completed",
            "stop_reason": "policy_finished",
            "assistant_message": {"role": "assistant", "content": "已持久化的最终答复"},
        },
    )

    original_registry = app_module.ProviderRegistry

    class _Registry:
        @classmethod
        def load(cls, path):
            instance = cls()
            instance.path = path
            return instance

        def public_options(self):
            return original_registry.load(self.path).public_options()

        def __getattr__(self, name):
            return getattr(original_registry.load(self.path), name)

        def create(self, *_args, **_kwargs):
            raise AssertionError("provider replayed after final checkpoint")

    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    monkeypatch.setattr(app_module, "Thread", _InlineThread)
    TestClient(create_app(service, event_repository=repository))

    job = _wait_for_deep_job(repository, job_id)
    assert job["status"] == "completed", job
    assert job["stage"] == "publish"
    messages = repository.list_deep_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "assistant"]


def test_reference_research_binding_loss_does_not_leave_active_session(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)

    # Model the reservation disappearing before the bind completes.  The
    # endpoint must clean up the session it already persisted instead of
    # returning a 503 with an active transcript that no worker can advance.
    monkeypatch.setattr(
        repository,
        "bind_deep_job_session",
        lambda *_args, **_kwargs: None,
    )
    client = TestClient(create_app(service, event_repository=repository))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-binding-loss"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "focus": "检查绑定竞态后的会话清理",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "deep job/session binding unavailable"
    sessions = repository.list_deep_sessions(run.run_id)
    assert all(str(item.get("status", "")).lower() != "active" for item in sessions)


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


def test_deep_session_context_contains_bounded_server_result_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    """The dialogue prompt is grounded in server cards, not only browser context."""

    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    client = TestClient(create_app(service, event_repository=repository))
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "context-snapshot-1"},
        json={
            "kind": "reference-research",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {
                "name": "客户端伪造名称",
                "evidence_ids": ["ev-client"],
                "api_key": "must-not-survive",
            },
            "context_refs": {
                "current_result_context": {
                    "selected": {"name": "客户端伪造名称"},
                },
            },
        },
    )
    assert response.status_code == 201
    context = response.json()["session"]["context_refs"]
    cards = context["current_result_context"]["capability_cards"]
    # The fixture is explicitly a low-scoring reference row; it must not be
    # relabelled as a formal S6 card in the server snapshot.
    assert all(item.get("name") != "参考拦截无人机" for item in cards)
    assert context["current_result_context"]["selected"]["name"] == "参考拦截无人机"
    assert context["canonical_candidate"] is True
    assert "api_key" not in json.dumps(context, ensure_ascii=False)
    assert isinstance(context.get("recent_visible_history"), list)


def test_deep_session_can_be_permanently_deleted_without_removing_capability_output(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    client = TestClient(create_app(service, event_repository=repository))
    created = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "delete-dialogue-session"},
        json={
            "kind": "reference-research",
            "hypothesis_id": "hypothesis-reference",
        },
    )
    assert created.status_code == 201
    session_id = created.json()["session"]["session_id"]
    version = repository.save_capability_version(
        version_id="version-delete-dialogue",
        parent_run_id=run.run_id,
        card_binding_id="binding-reference",
        hypothesis_id="hypothesis-reference",
        diff={"overview": "refined"},
        snapshot={"name": "固定后的参考拦截无人机"},
        source="deep-thinking",
    )

    deleted = client.delete(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}"
    )

    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "session_id": session_id}
    assert client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}"
    ).status_code == 404
    listed = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions"
    )
    assert listed.status_code == 200
    assert all(
        item["session_id"] != session_id for item in listed.json()["items"]
    )
    assert repository.get_capability_version(version["version_id"]) is not None


def test_deep_session_delete_rejects_running_job(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    client = TestClient(create_app(service, event_repository=repository))
    started = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "delete-running-dialogue"},
        json={"hypothesis_id": "hypothesis-reference"},
    )
    assert started.status_code == 202
    session_id = started.json()["session"]["session_id"]

    response = client.delete(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}"
    )

    assert response.status_code == 409
    assert "仍有研究任务运行" in response.json()["detail"]
    assert repository.get_deep_session(session_id) is not None


def test_reference_dialogue_worker_waits_for_confirmation_without_child(
    tmp_path: Path, monkeypatch
) -> None:
    """The hand-off executes dialogue but does not author S6 on its first turn."""

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
    assert repository.list_capability_versions(run.run_id) == []
    messages = repository.list_deep_messages(job["session_id"])
    assert "### 是否形成能力卡" in str(messages[-1]["content"])
    events = repository.deep_events_after(
        f"deep-session:{run.run_id}:{job['session_id']}", 0
    )
    stages = {str(event.get("stage", "")) for event in events}
    assert {
        "context",
        "s3_divergence",
        "s4_mapping",
        "publish",
    } <= stages
    assert "s6_authoring" not in stages


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
    assert repository.list_capability_versions(run.run_id) == []
    session = repository.get_deep_session(response.json()["session"]["session_id"])
    assert session is not None
    assert session["status"] == "active"


def test_working_memory_persistence_failure_marks_turn_job_and_session_partial(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)

    def unavailable_memory(*_args, **_kwargs):
        raise OSError("working-memory database unavailable")

    monkeypatch.setattr(
        repository, "update_deep_branch_working_memory", unavailable_memory
    )
    client = TestClient(create_app(service, event_repository=repository))
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-memory-outage"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "question": "继续比较末段复核构型",
        },
    )
    assert response.status_code == 202
    job = _wait_for_deep_job(repository, response.json()["job"]["job_id"])

    assert job["status"] == "partial", job
    assert job["stage"] == "validation"
    assert "working memory ledger" in str(job.get("error", ""))
    session = repository.get_deep_session(job["session_id"])
    assert session is not None
    assert session["status"] == "partial"
    assert any(
        item.get("role") == "assistant"
        for item in repository.list_deep_messages(job["session_id"])
    )
    events = repository.deep_events_after(
        f"deep-session:{run.run_id}:{job['session_id']}", 0
    )
    assert any(
        item.get("event_type") == "deep_memory_persistence_warning"
        and item.get("status") == "partial"
        for item in events
    )


def test_explicit_retry_after_working_memory_failure_reuses_assistant_turn(
    tmp_path: Path, monkeypatch
) -> None:
    """Retrying a post-answer persistence failure must not duplicate the bubble."""

    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    original_update = repository.update_deep_branch_working_memory

    def unavailable_memory(*_args, **_kwargs):
        raise OSError("working-memory database unavailable")

    monkeypatch.setattr(
        repository, "update_deep_branch_working_memory", unavailable_memory
    )
    client = TestClient(create_app(service, event_repository=repository))
    initial = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-memory-retry-initial"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "question": "继续比较末段复核构型",
        },
    )
    assert initial.status_code == 202
    initial_job_id = initial.json()["job"]["job_id"]
    session_id = initial.json()["session"]["session_id"]
    failed_job = _wait_for_deep_job(repository, initial_job_id)
    assert failed_job["status"] == "partial", failed_job

    before_retry = [
        item
        for item in repository.list_deep_messages(session_id)
        if item.get("role") == "assistant"
    ]
    assert len(before_retry) == 1
    original_identity = (
        before_retry[0]["message_id"],
        before_retry[0]["sequence"],
    )

    # Restore the ledger dependency before explicitly reopening the same job.
    monkeypatch.setattr(
        repository, "update_deep_branch_working_memory", original_update
    )
    retry = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-memory-retry-explicit"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "question": "继续比较末段复核构型",
            "retry": True,
        },
    )
    assert retry.status_code == 202
    assert retry.json()["job"]["job_id"] == initial_job_id

    recovered_job = _wait_for_deep_job(repository, initial_job_id)
    assert recovered_job["status"] == "completed", recovered_job
    assert recovered_job["stage"] == "publish"
    after_retry = [
        item
        for item in repository.list_deep_messages(session_id)
        if item.get("role") == "assistant"
    ]
    assert len(after_retry) == 1
    assert (
        after_retry[0]["message_id"],
        after_retry[0]["sequence"],
    ) == original_identity


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
        def __init__(self) -> None:
            self.progress_callback = None

        def set_deep_dialogue_progress_callback(self, callback) -> None:
            self.progress_callback = callback

        def deep_contextual_dialogue(self, payload):
            assert payload["execution_profile_id"] == "deep_dialogue_v1"
            assert payload["stage_scope"] == [
                "context",
                "equipment_innovation",
                "portrait_revision",
            ]
            assert payload["workflow_dispatch"] == "none"
            assert payload["innovation_mode"] == "single_equipment_innovation_v1"
            assert payload["context_policy"] == "query_equipment_questions_only"
            model_context = payload["deep_parent_context"]
            assert "evidence_index" not in model_context
            assert "validation_plan" not in str(model_context)
            assert "failure_boundary" not in str(model_context)
            assert callable(self.progress_callback)
            self.progress_callback(
                {
                    "event_type": "deep_agent_started",
                    "stage": "s3_divergence",
                    "status": "running",
                    "progress": 0.24,
                    "kind": "summary",
                    "agent_id": "deep_dialogue_doctrine_breaker",
                    "role": "传统战法破局 Agent",
                    "summary_text": "开始形成竞争方向。",
                }
            )
            self.progress_callback(
                {
                    "event_type": "deep_agent_completed",
                    "stage": "s3_divergence",
                    "status": "completed",
                    "progress": 0.42,
                    "kind": "answer",
                    "agent_id": "deep_dialogue_doctrine_breaker",
                    "role": "传统战法破局 Agent",
                    "deliverable_refs": ["自主复核节点"],
                    "text": "已形成自主复核节点。",
                }
            )
            self.progress_callback(
                {
                    "event_type": "deep_agent_handoff",
                    "stage": "council_critique",
                    "status": "running",
                    "progress": 0.48,
                    "kind": "summary",
                    "from_agent_id": "deep_dialogue_council",
                    "to_agent_id": "deep_dialogue_adversarial_judge",
                    "handoff_kind": "proposal_review",
                    "deliverable_refs": ["自主复核节点"],
                    "summary_text": "竞争方向已交给对抗裁决。",
                }
            )
            result = {
                "visible_summary": ["围绕参考装备形成一个竞争方向"],
                "agent_dialogue": [
                    {
                        "agent_id": "deep_dialogue_doctrine_breaker",
                        "role": "传统战法破局 Agent",
                        "round": "divergence",
                        "summary": "推翻末段拦截必须持续依赖外部制导的假设",
                        "proposal_names": ["自主复核节点"],
                    },
                    {
                        "agent_id": "deep_dialogue_adversarial_judge",
                        "role": "对抗裁决 Agent",
                        "round": "critique",
                        "summary": "通过机理闭合与对手适应审查",
                        "proposal_names": ["自主复核节点"],
                    },
                ],
                "orchestration": {
                    "pattern": "internal_multidim_divergence_adversarial_review_synthesis",
                    "rounds": 3,
                    "requested_agents": 4,
                    "completed_divergence_agents": 2,
                    "degraded": False,
                    "quality_gate_passed": True,
                },
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
                        "innovation_thesis": "把末段拦截器改造成自主复核节点",
                        "changed_assumption": "末段拦截必须持续依赖外部制导",
                        "novelty": "由弹药转为自主任务节点",
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
            if payload.get("authoring_requested"):
                result["capability_card_draft"] = {
                    "overview": "完整概述",
                    "technology_implementation": "完整装备与技术实现",
                    "operational_process": "完整关键作战流程",
                    "capability_effects": "完整能力与作战效果",
                    "winning_logic": "完整制胜逻辑机理",
                }
                result["runtime"] = {
                    "engine": "equipment_deep_runtime_v2",
                    "tools": ["author_s6"],
                }
            else:
                result["runtime"] = {
                    "engine": "equipment_deep_runtime_v2",
                    "tools": ["research_council"],
                }
            return result

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def public_options(self):
            return {"providers": []}

        def profile_snapshot(self, _name):
            return {}

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
    assert repository.list_capability_versions(run.run_id) == []
    events = repository.deep_events_after(
        f"deep-session:{run.run_id}:{job['session_id']}", 0
    )
    event_types = {str(event.get("event_type", "")) for event in events}
    assert {"deep_agent_started", "deep_agent_handoff", "deep_agent_completed"} <= event_types
    handoff = next(
        event for event in events if event.get("event_type") == "deep_agent_handoff"
    )
    assert handoff["delta"]["from_agent_id"] == "deep_dialogue_council"
    assert handoff["delta"]["to_agent_id"] == "deep_dialogue_adversarial_judge"
    assert handoff["delta"]["deliverable_refs"] == ["自主复核节点"]
    first_messages = repository.list_deep_messages(response.json()["session"]["session_id"])
    assert "### 是否形成能力卡" in str(first_messages[-1]["content"])

    confirmed = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{job['session_id']}/messages",
        headers={"Idempotency-Key": "reference-dialogue-provider-confirm"},
        json={
            "content": "确认将当前已收敛方向形成五栏能力卡。",
            "create_artifact": True,
        },
    )
    assert confirmed.status_code == 202
    confirmed_job_id = confirmed.json()["job"]["job_id"]
    deadline = time.monotonic() + 5.0
    confirmed_job = repository.get_deep_job(confirmed_job_id)
    while confirmed_job is not None and str(confirmed_job.get("status", "")).lower() in {
        "queued",
        "running",
    } and time.monotonic() < deadline:
        time.sleep(0.02)
        confirmed_job = repository.get_deep_job(confirmed_job_id)

    assert confirmed_job is not None
    assert confirmed_job["status"] == "completed", confirmed_job
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
    # The innovation card may name and shape a new variant while retaining
    # the canonical source equipment and parent lineage.
    assert snapshot["name"] == "伪造坦克方向"
    assert snapshot["equipment_form"] == "主战坦克"
    assert snapshot["source_equipment_identity"] == "参考拦截无人机"
    assert snapshot["evidence_ids"] == []
    assert len(repository.list_deep_jobs(run.run_id)) == 2
    messages = repository.list_deep_messages(response.json()["session"]["session_id"])
    assistant_text = "\n".join(
        str(item.get("content", ""))
        for item in messages
        if item.get("role") == "assistant"
    )
    assert "### 多 Agent 交叉审议" in assistant_text
    assert "传统战法破局 Agent" in assistant_text
    assert "对抗裁决 Agent" in assistant_text


def test_http_runtime_binds_trusted_workspace_and_records_nanobot_state(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The HTTP worker opts into external state without accepting a path.

    The provider double runs the real bounded runtime so this covers the
    complete hand-off: canonical identity -> DeepWorkspace -> transcript and
    branch checkpoint. Each equipment has its own locked file workspace.
    """

    service, repository, run, output_root = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )
    captured: dict[str, object] = {}

    class _Provider:
        def deep_contextual_dialogue(self, payload):
            captured.update(payload)
            assert isinstance(payload.get("deep_workspace"), DeepWorkspace)
            assert payload.get("workspace_id").startswith(f"run:{run.run_id}:equipment:")
            assert payload.get("workspace_record_turn") is True
            assert payload.get("session_id")
            assert payload.get("branch_id") == "main"
            # The model-facing payload receives an in-process handle; the
            # request cannot choose an arbitrary filesystem location.
            assert "workspace_path" not in payload
            return run_deep_research_turn(self, payload)

        def _emit_deep_dialogue_progress(self, _row):
            return None

        async def _run_core_json(self, *_args, **_kwargs):
            return {}

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def public_options(self):
            return {"providers": []}

        def profile_snapshot(self, _name):
            return {}

        def create(self, *_args, **_kwargs):
            return _Provider()

    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "trusted-workspace-runtime"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
            "question": "/memory",
        },
    )
    assert response.status_code == 201, response.text
    assert str(output_root) not in response.text
    job_id = response.json()["job"]["job_id"]
    job = _wait_for_deep_job(repository, job_id)
    assert job["status"] == "completed", job
    assert captured["equipment_identity"]["hypothesis_id"] == "hypothesis-reference"
    assert captured["channel"] == "web"
    assert captured["chat_id"] == response.json()["session"]["session_id"]
    assert captured["inbound_message"].message_id == job_id

    run_root = output_root / run.run_id
    workspace = DeepWorkspace.open_equipment(
        run_root,
        workspace_id=f"run:{run.run_id}",
        identity={
            "hypothesis_id": "hypothesis-reference",
            "card_binding_id": "binding-reference",
            "capability_id": "cap-reference",
            "primary_equipment_identity": "参考拦截无人机",
            "equipment_form": "末段拦截无人机",
        },
    )
    saved = workspace.sessions.load(response.json()["session"]["session_id"])
    assert saved is not None
    assert [item["role"] for item in saved["messages"]] == ["user", "assistant"]
    assert saved["branches"]["main"]["branch_id"] == "main"
    assert workspace.memory.latest_cursor() >= 2

    workspace.write_resource("skill", "frontier/SKILL.md", """---
name: frontier
description: Explore alternative assumptions
procedure:
  steps: [Identify assumptions, Compare alternatives]
  required_artifacts: [AlternativeMap]
  quality_gates: [Distinct mechanisms]
  stop_conditions: [No new assumptions]
---
Keep competing assumptions visible.
""")
    session_id = response.json()["session"]["session_id"]
    scoped_catalog = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/capabilities"
    )
    assert scoped_catalog.status_code == 200, scoped_catalog.text
    assert "workspace:frontier" in [row["skill_id"] for row in scoped_catalog.json()["skills"]]
    assert str(output_root) not in scoped_catalog.text
    followup = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
        headers={"Idempotency-Key": "workspace-skill-followup"},
        json={
            "content": "/memory",
            "active_skill_ids": ["workspace:frontier"],
            "channel": "telegram",
        },
    )
    assert followup.status_code in {200, 202}, followup.text
    followup_job = _wait_for_deep_job(repository, followup.json()["job"]["job_id"])
    assert followup_job["status"] == "completed", followup_job
    assert "workspace:frontier" in captured["deep_parent_context"]["active_skill_ids"]
    assert captured["channel"] == "telegram"
    assert (
        repository.get_deep_job(followup_job["job_id"])["payload"]["channel"]
        == "telegram"
    )

    from equipment_deep_research.deep_runtime.capabilities import AGENT_PLUGIN_SCHEMA
    workspace.write_resource("plugin", "workspace-methods/plugin.json", json.dumps({
        "$schema": AGENT_PLUGIN_SCHEMA, "name": "workspace-methods",
        "description": "Equipment-local methods",
    }))
    workspace.write_resource("plugin", "workspace-methods/skills.yaml", """skills:
  - skill_id: compare
    steps: [Compare assumptions]
    required_artifacts: [AlternativeMap]
    quality_gates: [Distinct mechanisms]
    stop_conditions: [No new assumptions]
""")
    plugin_path = f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/plugins/workspace-methods"
    assert client.patch(plugin_path, json={"enabled": True}).status_code == 403
    enabled = client.patch(plugin_path, headers={"X-Role": "admin"}, json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["plugin"]["source"] == "workspace"
    assert "workspace-methods:compare" in [row["skill_id"] for row in enabled.json()["catalog"]["skills"]]
    assert str(output_root) not in enabled.text
    global_catalog = client.get("/api/v1/deep-thinking/capabilities").json()
    assert "workspace-methods:compare" not in [row["skill_id"] for row in global_catalog["skills"]]
    workspace.write_resource("plugin", "workspace-methods/skills.yaml", "skills: []")
    changed_catalog = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/capabilities"
    ).json()
    assert not next(row for row in changed_catalog["plugins"] if row["plugin_id"] == "workspace-methods")["enabled"]

    import io
    from urllib.error import HTTPError
    from equipment_deep_research.interfaces import dialogue_cli

    def local_urlopen(request, timeout):
        reply = client.request(request.get_method(), request.full_url,
                               headers=dict(request.header_items()), content=request.data)
        if reply.status_code >= 400:
            raise HTTPError(request.full_url, reply.status_code, "API error", {}, io.BytesIO(reply.content))
        return io.BytesIO(reply.content)

    monkeypatch.setattr(dialogue_cli, "urlopen", local_urlopen)
    assert dialogue_cli.main([
        "--api-base", "http://testserver/api/v1", "--run-id", run.run_id,
        "--session-id", session_id, "--message", "/help", "--wait",
    ]) == 0
    cli_output = capsys.readouterr().out
    cli_snapshot = json.loads(cli_output)
    assert cli_snapshot["session"]["session_id"] == session_id
    assert cli_snapshot["job"]["status"] == "completed"
    assert captured["channel"] == "cli"
    assert str(output_root) not in cli_output

    # A second equipment in this run receives isolated state, retaining both
    # manifests and the first equipment's transcript.
    from equipment_deep_research.api.app import (
        _deep_runtime_equipment_identity,
        _open_trusted_deep_runtime_workspace,
    )

    other_identity = _deep_runtime_equipment_identity(
        {
            "hypothesis_id": "different-hypothesis",
            "primary_equipment_identity": "另一件装备",
        }
    )
    other_workspace, handle = _open_trusted_deep_runtime_workspace(
        output_root,
        run.run_id,
        identity=other_identity,
    )
    try:
        assert other_workspace is not None
        assert other_workspace.state_dir != workspace.state_dir
        assert other_workspace.sessions.load(response.json()["session"]["session_id"]) is None
        assert workspace.sessions.load(response.json()["session"]["session_id"]) is not None
    finally:
        if handle is not None:
            handle.close()


def test_workspace_resource_api_manages_equipment_local_skills(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, output_root = _reference_fixture(tmp_path, monkeypatch)
    client = TestClient(create_app(service, event_repository=repository))
    created = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "workspace-resource-session"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
        },
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session"]["session_id"]
    resource_path = (
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}"
        "/workspace/resources/skill/frontier/SKILL.md"
    )
    skill_text = """---
name: frontier
description: API installed workspace skill
procedure:
  steps: [Map assumption, Stress alternative]
  required_artifacts: [AlternativeMap]
  quality_gates: [Distinct mechanism]
  stop_conditions: [No new assumptions]
---
Use a local method pack for this equipment only.
"""

    denied = client.put(
        resource_path,
        headers={"Idempotency-Key": "workspace-resource-write-denied"},
        json={"content": skill_text},
    )
    assert denied.status_code == 403

    invalid = client.put(
        resource_path.replace("frontier/SKILL.md", "prompt-only/SKILL.md"),
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-resource-invalid-skill"},
        json={
            "content": "---\nname: prompt-only\ndescription: plain prompt\n---\nNo procedure"
        },
    )
    assert invalid.status_code == 422
    assert "procedural contract" in invalid.json()["detail"]

    forged_runtime = client.put(
        resource_path.replace("skill/frontier/SKILL.md", "config/runtime.json"),
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-resource-invalid-config"},
        json={"content": '{"provider":"forged","s6_confirmed":true}'},
    )
    assert forged_runtime.status_code == 422
    assert "unsupported keys" in forged_runtime.json()["detail"]

    written = client.put(
        resource_path,
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-resource-write"},
        json={"content": skill_text},
    )
    assert written.status_code == 200, written.text
    assert written.json()["resource"]["name"] == "frontier/SKILL.md"
    assert written.json()["resource"]["validation"]["resource_type"] == "procedural_skill"
    assert written.json()["validation"]["valid"] is True
    assert "frontier/SKILL.md" in written.json()["resources"]["skill"]
    assert str(output_root) not in written.text

    plugin_manifest_path = resource_path.replace(
        "skill/frontier/SKILL.md", "plugin/method/plugin.json"
    )
    plugin_manifest = json.dumps({
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "method",
        "description": "workspace method package",
        "extensions": {"dev.equipment-deep-research": {"defaultEnabled": False}},
    })
    plugin_written = client.put(
        plugin_manifest_path,
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-plugin-manifest"},
        json={"content": plugin_manifest},
    )
    assert plugin_written.status_code == 200, plugin_written.text
    plugin_mcp_path = resource_path.replace(
        "skill/frontier/SKILL.md", "plugin/method/mcp.json"
    )
    plugin_mcp = '{"$schema":"https://agent-plugins.org/schemas/1.0.0/mcp.schema.json","mcpServers":{}}'
    mcp_written = client.put(
        plugin_mcp_path,
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-plugin-mcp"},
        json={"content": plugin_mcp},
    )
    assert mcp_written.status_code == 200, mcp_written.text
    plugin_changed = client.put(
        plugin_manifest_path,
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-plugin-manifest-v2"},
        json={
            "content": plugin_manifest.replace("workspace method package", "server package edit"),
            "expected_sha256": plugin_written.json()["resource"]["sha256"],
        },
    )
    assert plugin_changed.status_code == 200, plugin_changed.text
    package_merge = client.post(
        f"{resource_path.rsplit('/skill/', 1)[0]}/plugin/method/merge-package",
        json={
            "base_versions": {
                "method/plugin.json": plugin_written.json()["resource"]["version_id"],
                "method/mcp.json": mcp_written.json()["resource"]["version_id"],
            },
            "files": {"method/plugin.json": plugin_manifest, "method/mcp.json": plugin_mcp},
        },
    )
    assert package_merge.status_code == 200, package_merge.text
    assert package_merge.json()["merge"]["atomic_ready"] is True
    package_applied = client.post(
        f"{resource_path.rsplit('/skill/', 1)[0]}/plugin/method/merge-package/apply",
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-plugin-package-apply"},
        json={
            "base_versions": {
                "method/plugin.json": plugin_written.json()["resource"]["version_id"],
                "method/mcp.json": mcp_written.json()["resource"]["version_id"],
            },
            "files": {"method/plugin.json": plugin_manifest, "method/mcp.json": plugin_mcp},
        },
    )
    assert package_applied.status_code == 200, package_applied.text
    assert package_applied.json()["merge"]["applied"] is True
    package_replay = client.post(
        f"{resource_path.rsplit('/skill/', 1)[0]}/plugin/method/merge-package/apply",
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-plugin-package-apply"},
        json={
            "base_versions": {
                "method/plugin.json": plugin_written.json()["resource"]["version_id"],
                "method/mcp.json": mcp_written.json()["resource"]["version_id"],
            },
            "files": {"method/plugin.json": plugin_manifest, "method/mcp.json": plugin_mcp},
        },
    )
    assert package_replay.status_code == 200, package_replay.text
    assert package_replay.json() == package_applied.json()
    analyst_apply = client.post(
        f"{resource_path.rsplit('/skill/', 1)[0]}/plugin/method/merge-package/apply",
        headers={"X-Role": "analyst", "Idempotency-Key": "workspace-plugin-package-analyst"},
        json={"base_versions": {}, "files": {}},
    )
    assert analyst_apply.status_code == 403, analyst_apply.text

    current_hash = written.json()["resource"]["sha256"]
    changed = client.put(
        resource_path,
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-resource-write-v2"},
        json={"content": skill_text + "\n追加一个反事实探针。", "expected_sha256": current_hash},
    )
    assert changed.status_code == 200, changed.text
    assert len(changed.json()["resource"]["versions"]) >= 2
    stale = client.put(
        resource_path,
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-resource-write-stale"},
        json={"content": "stale overwrite", "expected_sha256": current_hash},
    )
    assert stale.status_code == 409, stale.text
    assert stale.headers.get("etag") == changed.json()["resource"]["sha256"]

    first_version = next(
        item for item in changed.json()["resource"]["versions"]
        if item["sha256"] == current_hash and not item.get("deleted")
    )
    merged = client.post(
        f"{resource_path}/merge",
        json={
            "base_version_id": first_version["version_id"],
            "content": skill_text.replace("API installed", "本地草稿"),
        },
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["merge"]["conflicted"] is False
    assert "本地草稿" in merged.json()["merge"]["content"]
    assert "追加一个反事实探针" in merged.json()["merge"]["content"]
    assert merged.json()["resource"]["sha256"] == changed.json()["resource"]["sha256"]

    restored = client.post(
        f"{resource_path}/restore/{first_version['version_id']}",
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-resource-restore"},
        json={"expected_sha256": changed.json()["resource"]["sha256"]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored_version_id"] == first_version["version_id"]
    assert restored.json()["resource"]["sha256"] == current_hash

    replay = client.put(
        resource_path,
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-resource-write"},
        json={"content": skill_text},
    )
    assert replay.status_code == 200
    assert replay.json()["resource"]["sha256"] == written.json()["resource"]["sha256"]

    listed = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/workspace/resources"
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["resources"]["skill"] == ["frontier/SKILL.md"]
    assert str(output_root) not in listed.text

    loaded = client.get(resource_path)
    assert loaded.status_code == 200, loaded.text
    assert "API installed workspace skill" in loaded.json()["resource"]["content"]
    assert loaded.json()["resource"]["encoding"] == "utf-8"

    scoped_catalog = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/capabilities"
    )
    assert scoped_catalog.status_code == 200, scoped_catalog.text
    assert "workspace:frontier" in [row["skill_id"] for row in scoped_catalog.json()["skills"]]

    removed = client.delete(
        resource_path,
        headers={"X-Role": "admin", "Idempotency-Key": "workspace-resource-delete"},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["deleted"] is True
    assert removed.json()["resources"]["skill"] == []

    after_delete = client.get(resource_path)
    assert after_delete.status_code == 404


def test_dialogue_only_authors_card_after_explicit_user_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )
    authoring_requests: list[bool] = []

    class _Provider:
        def deep_contextual_dialogue(self, payload):
            authoring_requested = bool(payload.get("authoring_requested"))
            authoring_requests.append(authoring_requested)
            return {
                "visible_summary": ["已收敛出具有直接军事价值的新质装备方向"],
                "selection_rationale": "任务链反转、直接毁伤与制衡逻辑已经闭合",
                "concept_directions": [
                    {
                        "name": "尚未闭合的诱饵方向",
                        "equipment_form": "未闭合构型",
                        "operational_mechanism": "这条不稳定方向不得进入能力卡",
                        "direct_military_effects": "尚未形成可核验效果",
                        "stable": False,
                    },
                    {
                        "name": "潜伏断链攻击节点",
                        "innovation_thesis": "将即时攻击改为潜伏后择机断链",
                        "winning_angle": "杀伤链反转",
                        "changed_assumption": "进入目标区后必须立即攻击",
                        "equipment_form": "可贴附潜伏的自主攻击节点",
                        "operational_mechanism": "潜伏观测后在任务窗口内自主触发",
                        "decisive_target": "高价值机动平台的关键任务舱段",
                        "direct_damage_mechanism": "定向物理效应破坏任务舱段",
                        "mission_kill_criterion": "目标退出当前任务周期",
                        "direct_military_effects": "压缩目标机动窗口并直接造成任务失能",
                        "disruptive_difference": "从即时弹药变为潜伏任务节点",
                        "stable": True,
                    }
                ],
                "capability_card_draft": {
                    "overview": "完整概述",
                    "technology_implementation": "完整装备与技术实现",
                    "operational_process": "完整关键作战流程",
                    "capability_effects": "完整能力与作战效果",
                    "winning_logic": "完整制胜逻辑机理",
                },
                "quality_gate": {
                    "publishable": True,
                    "direction_ready": True,
                    "passed_directions": 1,
                    "block_reasons": [],
                },
                "finalization_status": "candidate_ready",
                "deep_divergence_status": "completed",
                "runtime": {
                    "engine": "equipment_deep_runtime_v2",
                    "tools": [
                        "author_s6" if authoring_requested else "research_council"
                    ],
                },
            }

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def create(self, *_args, **_kwargs):
            return _Provider()

    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    first = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "dialogue-before-confirmation"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
            "question": "请先判断这个方向是否值得继续深挖",
        },
    )
    assert first.status_code == 201
    session_id = first.json()["session"]["session_id"]
    first_job_id = first.json()["job"]["job_id"]

    deadline = time.monotonic() + 5.0
    first_job = repository.get_deep_job(first_job_id)
    while first_job is not None and str(first_job.get("status", "")).lower() in {
        "queued",
        "running",
    } and time.monotonic() < deadline:
        time.sleep(0.02)
        first_job = repository.get_deep_job(first_job_id)

    assert first_job is not None and first_job["status"] == "completed", first_job
    assert repository.list_capability_versions(run.run_id) == []
    first_messages = repository.list_deep_messages(session_id)
    assert "### 是否形成能力卡" in str(first_messages[-1]["content"])

    confirmed = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
        headers={"Idempotency-Key": "dialogue-card-confirmation"},
        json={
            # Direct API callers may use the governed command without the
            # WebUI transport hint. The server must still enter S6.
            "content": "/card",
            "create_artifact": False,
        },
    )
    assert confirmed.status_code == 202
    confirmed_job_id = confirmed.json()["job"]["job_id"]
    deadline = time.monotonic() + 5.0
    confirmed_job = repository.get_deep_job(confirmed_job_id)
    while confirmed_job is not None and str(confirmed_job.get("status", "")).lower() in {
        "queued",
        "running",
    } and time.monotonic() < deadline:
        time.sleep(0.02)
        confirmed_job = repository.get_deep_job(confirmed_job_id)

    assert confirmed_job is not None and confirmed_job["status"] == "completed", confirmed_job
    versions = repository.list_capability_versions(run.run_id)
    assert len(versions) == 1
    assert (
        versions[0]["snapshot"]["operational_mechanism"]
        == "潜伏观测后在任务窗口内自主触发"
    )
    assert "尚未闭合的诱饵方向" not in json.dumps(
        versions[0]["snapshot"], ensure_ascii=False
    )
    assert authoring_requests == [False, True]


def test_evidence_and_publish_advice_do_not_block_visible_divergence(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )

    class _Provider:
        def deep_contextual_dialogue(self, _payload):
            return {
                "visible_summary": ["已形成低证据条件下的三个探索假设"],
                "concept_directions": [
                    {
                        "name": "断链自主复核节点",
                        "innovation_thesis": "把持续外部制导改为任务区自主复核",
                        "equipment_form": "分布式末段复核节点",
                        "operational_mechanism": "进入任务区后独立识别并择机作用",
                        "direct_military_effects": "压缩低空目标的有效突防窗口",
                        "stable": False,
                    }
                ],
                "quality_gate": {
                    "publishable": False,
                    "direction_ready": False,
                    "passed_directions": 0,
                    "block_reasons": ["公开证据不足，仅能作为待探索假设"],
                },
                "research_strategy": {
                    "mode": "challenge",
                    "actions": ["challenge", "synthesize"],
                    "rationale": "先找最低成本反制，再综合仍成立的方向",
                    "fixed_pipeline": False,
                    "s6_requires_confirmation": True,
                },
                "research_assessment": {
                    "research_complete": True,
                    "candidate_count": 1,
                    "research_ready_count": 0,
                    "average_completeness": 0.56,
                },
                "research_gaps": [
                    {
                        "candidate_name": "断链自主复核节点",
                        "missing_dimensions": ["mission_kill_criterion"],
                        "suggested_question": "如何观察任务失能？",
                    }
                ],
                "finalization_status": "analysis_only",
                # Legacy providers used blocked for a failed publication
                # rubric. The API must preserve the research as completed.
                "deep_divergence_status": "blocked",
            }

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def create(self, *_args, **_kwargs):
            return _Provider()

    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "advisory-only-divergence"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
            "question": "在证据稀疏条件下继续做高差异度发散",
        },
    )
    assert response.status_code == 201
    session_id = response.json()["session"]["session_id"]
    job = _wait_for_deep_job(repository, response.json()["job"]["job_id"])

    assert job["status"] == "completed", job
    assert job["stage"] == "publish"
    stored_session = repository.get_deep_session(session_id)
    assert stored_session["status"] == "active"
    assert "公开证据不足" in json.dumps(
        stored_session["working_memory"], ensure_ascii=False
    )
    assert "如何观察任务失能" in json.dumps(
        stored_session["working_memory"], ensure_ascii=False
    )
    stored_branch_memory = branch_working_memory(
        stored_session["working_memory"], "main"
    )
    assert stored_branch_memory["last_research_strategy"]["mode"] == "challenge"
    assert repository.list_capability_versions(run.run_id) == []
    assistant = repository.list_deep_messages(session_id)[-1]
    assert "已形成低证据条件下的三个探索假设" in assistant["content"]
    assert "公开证据不足" in assistant["content"]
    assert "发布质量门" not in assistant["content"]
    events = repository.deep_events_after(
        f"deep-session:{run.run_id}:{session_id}", 0
    )
    assert not any(
        item.get("event_type") == "deep_research_blocked" for item in events
    )


def test_confirmed_card_persists_despite_advisory_quality_gaps(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )
    authoring_requests: list[bool] = []

    class _Provider:
        def deep_contextual_dialogue(self, payload):
            authoring_requested = bool(payload.get("authoring_requested"))
            authoring_requests.append(authoring_requested)
            return {
                "visible_summary": ["保留一个仍需后续补证的颠覆方向"],
                "concept_directions": [
                    {
                        "name": "断链潜伏拦截节点",
                        "innovation_thesis": "把即时拦截改为潜伏观察后自主触发",
                        "equipment_form": "可潜伏部署的自主拦截节点",
                        "operational_mechanism": "潜伏观察后在短窗口内自主触发",
                        "direct_military_effects": "直接压缩低空目标突防窗口",
                        "stable": False,
                    }
                ],
                "capability_card_draft": {
                    "overview": "当前仅形成初步能力画像，后续继续补充工程边界。",
                },
                "quality_gate": {
                    "publishable": False,
                    "direction_ready": False,
                    "passed_directions": 0,
                    "missing_s6_columns": [
                        "technology_implementation",
                        "operational_process",
                    ],
                    "block_reasons": ["证据不足", "S6 五栏尚未全部补齐"],
                },
                "runtime": {
                    "engine": "equipment_deep_runtime_v2",
                    "tools": ["author_s6"] if authoring_requested else ["research_council"],
                },
                "finalization_status": "analysis_only",
                "deep_divergence_status": "blocked",
            }

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def create(self, *_args, **_kwargs):
            return _Provider()

    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    initial = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "advisory-card-before-confirmation"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "question": "先做发散，不要成卡",
        },
    )
    assert initial.status_code == 202
    session_id = initial.json()["session"]["session_id"]
    initial_job = _wait_for_deep_job(repository, initial.json()["job"]["job_id"])
    assert initial_job["status"] == "completed", initial_job
    assert repository.list_capability_versions(run.run_id) == []

    confirmed = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
        headers={"Idempotency-Key": "advisory-card-confirmed"},
        json={
            "content": "确认按当前方向形成能力卡，缺口作为后续研究问题保留。",
            "create_artifact": True,
        },
    )
    assert confirmed.status_code == 202
    confirmed_job = _wait_for_deep_job(
        repository, confirmed.json()["job"]["job_id"]
    )

    assert confirmed_job["status"] == "completed", confirmed_job
    versions = repository.list_capability_versions(run.run_id)
    assert len(versions) == 1
    assert versions[0]["status"] == "pending_verification"
    snapshot = versions[0]["snapshot"]
    assert snapshot["hypothesis_id"] == "hypothesis-reference"
    assert snapshot["card_binding_id"] == "binding-reference"
    assert snapshot["source_equipment_identity"] == "参考拦截无人机"
    assert snapshot["operational_mechanism"] == "潜伏观察后在短窗口内自主触发"
    assert authoring_requests == [False, True]
    assistant_text = "\n".join(
        str(item.get("content", ""))
        for item in repository.list_deep_messages(session_id)
        if item.get("role") == "assistant"
    )
    assert "发布质量门" not in assistant_text


def test_runtime_council_cannot_persist_card_without_author_s6(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )

    class _Provider:
        def deep_contextual_dialogue(self, _payload):
            return {
                "visible_summary": ["成卡请求先退回研究议事并形成候选"],
                "selection_rationale": "候选仍需进入受控 S6 成卡动作",
                "concept_directions": [
                    {
                        "name": "潜伏断链攻击节点",
                        "winning_angle": "杀伤链反转",
                        "equipment_form": "可贴附潜伏的自主攻击节点",
                        "operational_mechanism": "潜伏观测后在任务窗口内自主触发",
                        "direct_military_effects": "直接造成关键任务舱段失能",
                        "stable": True,
                    }
                ],
                "quality_gate": {
                    "direction_ready": True,
                    "passed_directions": 1,
                    "block_reasons": [],
                },
                # A card-shaped draft alone must not bypass the explicit S6
                # authoring action.
                "capability_card_draft": {
                    "overview": "模型越权提供的草稿",
                    "technology_implementation": "模型越权提供的实现",
                },
                "runtime": {
                    "engine": "equipment_deep_runtime_v2",
                    "tools": ["research_council"],
                },
                "finalization_status": "awaiting_user_confirmation",
                "deep_divergence_status": "completed",
            }

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def create(self, *_args, **_kwargs):
            return _Provider()

    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "runtime-card-without-author-s6"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
            "question": "确认形成能力卡",
            "create_artifact": True,
        },
    )
    assert response.status_code == 201
    session_id = response.json()["session"]["session_id"]
    job = _wait_for_deep_job(repository, response.json()["job"]["job_id"])

    assert job["status"] == "completed", job
    assert repository.list_capability_versions(run.run_id) == []
    assistant = repository.list_deep_messages(session_id)[-1]
    assert "是否形成能力卡" in str(assistant.get("content", ""))
    stored_session = repository.get_deep_session(session_id)
    assert "尚未完成 S6 成卡动作" in json.dumps(
        stored_session["working_memory"], ensure_ascii=False
    )
    assert "candidate_ready" not in json.dumps(
        stored_session["working_memory"], ensure_ascii=False
    )


def test_runtime_checkpoints_and_safe_metadata_round_trip_through_sql_and_api(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )
    checkpoint_phases: list[str] = []

    class _Provider:
        def deep_contextual_dialogue(self, payload):
            checkpoint_callback = payload.get("checkpoint_callback")
            assert callable(checkpoint_callback)
            checkpoints = [
                {
                    "schema_version": "deep-runtime-checkpoint-v1",
                    "phase": "awaiting_tools",
                    "status": "running",
                    "turn_count": 1,
                    "tool_call_count": 1,
                    "plan": ["deepen"],
                    "completed_tools": [],
                    "active_skill_ids": ["counterfactual_triz_innovation"],
                    "stop_reason": "",
                    "assistant_message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "tool_call_id": "deep-turn-1",
                                "tool_name": "deepen",
                                "turn_index": 1,
                            }
                        ],
                    },
                    "completed_tool_results": [],
                    "pending_tool_calls": [
                        {
                            "tool_call_id": "deep-turn-1",
                            "tool_name": "deepen",
                            "turn_index": 1,
                        }
                    ],
                },
                {
                    "schema_version": "deep-runtime-checkpoint-v1",
                    "phase": "tools_completed",
                    "status": "running",
                    "turn_count": 1,
                    "tool_call_count": 1,
                    "plan": ["deepen"],
                    "completed_tools": ["deepen"],
                    "active_skill_ids": ["counterfactual_triz_innovation"],
                    "stop_reason": "",
                    "assistant_message": {"role": "assistant", "content": ""},
                    "completed_tool_results": [
                        {
                            "kind": "tool_result",
                            "turn_index": 1,
                            "tool_name": "deepen",
                            "status": "completed",
                        }
                    ],
                    "pending_tool_calls": [],
                },
                {
                    "schema_version": "deep-runtime-checkpoint-v1",
                    "phase": "final_response",
                    "status": "completed",
                    "turn_count": 2,
                    "tool_call_count": 1,
                    "plan": ["deepen"],
                    "completed_tools": ["deepen"],
                    "active_skill_ids": ["counterfactual_triz_innovation"],
                    "stop_reason": "policy_finished",
                    "assistant_message": {
                        "role": "assistant",
                        "content": {"visible_summary": ["形成可见结论"]},
                    },
                    "completed_tool_results": [],
                    "pending_tool_calls": [],
                },
            ]
            for checkpoint in checkpoints:
                checkpoint_callback(checkpoint)
                checkpoint_phases.append(checkpoint["phase"])
            return {
                "visible_summary": ["形成可见结论"],
                "concept_directions": [],
                "quality_gate": {
                    "publishable": False,
                    "direction_ready": False,
                    "block_reasons": [],
                },
                "finalization_status": "analysis_only",
                "deep_divergence_status": "completed",
                "runtime": {
                    "engine": "equipment_deep_runtime_v2",
                    "tools": ["deepen"],
                    "plan": ["deepen", "finish"],
                    "active_skill_ids": [
                        "counterfactual_triz_innovation",
                        "constraint_reversal",
                    ],
                    "plugin_ids": ["deep-innovation-methods"],
                    "mcp_servers": ["deep-innovation-methods:analysis"],
                    "command": "/memory",
                    "conductor": {
                        "strategy": "bounded",
                        "api_key": "must-not-escape",
                    },
                    "status": "completed",
                    "turn_count": 2,
                    "tool_call_count": 1,
                    "stop_reason": "policy_finished",
                    "policy_trace": [{"hidden_reasoning": "must-not-escape"}],
                },
            }

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def create(self, *_args, **_kwargs):
            return _Provider()

    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "runtime-checkpoint-session"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
            "question": "继续比较这个装备方向",
        },
    )
    assert response.status_code == 201
    session_id = response.json()["session"]["session_id"]
    job = _wait_for_deep_job(repository, response.json()["job"]["job_id"])

    assert job["status"] == "completed", job
    assert checkpoint_phases == [
        "awaiting_tools",
        "tools_completed",
        "final_response",
    ]
    assert job["checkpoint"]["phase"] == "final_response"
    assert job["checkpoint"]["assistant_message"]["role"] == "assistant"

    messages = repository.list_deep_messages(session_id)
    runtime = messages[-1]["metadata"]["runtime"]
    assert runtime["engine"] == "equipment_deep_runtime_v2"
    assert runtime["tools"] == ["deepen"]
    assert runtime["plugin_ids"] == ["deep-innovation-methods"]
    assert runtime["conductor"]["api_key"] == "<redacted>"
    assert "policy_trace" not in runtime
    assert "must-not-escape" not in json.dumps(runtime, ensure_ascii=False)

    repository.append_deep_message(
        session_id=session_id,
        role="assistant",
        content="legacy metadata row",
        metadata={
            "runtime": {
                "engine": "legacy",
                "tools": ["inspect_memory"],
                "provider_secret": "must-not-escape",
            },
            "provider_state": {"token": "must-not-escape"},
        },
    )
    public_session = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}"
    )
    assert public_session.status_code == 200
    public_metadata = public_session.json()["session"]["messages"][-1]["metadata"]
    assert public_metadata == {
        "runtime": {"engine": "legacy", "tools": ["inspect_memory"]}
    }
    assert "must-not-escape" not in json.dumps(
        public_session.json(), ensure_ascii=False
    )


def test_recovered_dialogue_without_create_artifact_stays_analysis_only(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )
    authoring_requests: list[bool] = []
    provider_registry_type = app_module.ProviderRegistry

    class _Provider:
        def deep_contextual_dialogue(self, payload):
            authoring_requests.append(bool(payload.get("authoring_requested")))
            return {
                "visible_summary": ["恢复任务只形成分析结论"],
                "concept_directions": [
                    {
                        "name": "恢复候选",
                        "equipment_form": "可部署任务节点",
                        "operational_mechanism": "通过任务窗口自主触发直接作用",
                        "direct_military_effects": "使目标退出当前任务周期",
                        "innovation_thesis": "改变即时作用假设",
                        "stable": True,
                    }
                ],
                "capability_card_draft": {
                    "overview": "完整概述",
                    "technology_implementation": "完整装备与技术实现",
                    "operational_process": "完整关键作战流程",
                    "capability_effects": "完整能力与作战效果",
                    "winning_logic": "完整制胜逻辑机理",
                },
                "quality_gate": {
                    "publishable": True,
                    "direction_ready": True,
                    "passed_directions": 1,
                    "block_reasons": [],
                },
                "finalization_status": "candidate_ready",
                "deep_divergence_status": "completed",
                "runtime": {
                    "engine": "equipment_deep_runtime_v2",
                    "tools": ["research_council"],
                },
            }

    class _Registry:
        load_count = 0

        @classmethod
        def load(cls, path):
            cls.load_count += 1
            if cls.load_count == 1:
                return provider_registry_type.load(path)
            return cls()

        def create(self, *_args, **_kwargs):
            return _Provider()

    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    candidate = {
        "capability_id": "cap-reference",
        "card_binding_id": "binding-reference",
        "hypothesis_id": "hypothesis-reference",
        "name": "参考拦截无人机",
        "equipment_form": "末段拦截无人机",
        "mechanism_chain": "通过弹上复核压缩末段交战窗口",
        "military_value": "直接拦截低空目标",
        "evidence_ids": ["ev-parent"],
    }
    repository.create_deep_session(
        session_id="session-recovery-no-authoring",
        parent_run_id=run.run_id,
        kind="deep-thinking",
        title="恢复对话",
        card_binding_id="binding-reference",
        hypothesis_id="hypothesis-reference",
        query_snapshot={
            "query": "低空目标拦截",
            "context": {"query": "低空目标拦截", "candidate": candidate},
        },
    )
    repository.create_or_get_deep_job(
        job_id="job-recovery-no-authoring",
        parent_run_id=run.run_id,
        session_id="session-recovery-no-authoring",
        kind="deep-dialogue-v1",
        payload={
            "session_id": "session-recovery-no-authoring",
            "question": "恢复后继续分析当前方向",
            "dialogue_mode": "single_equipment_contextual_divergence",
        },
    )

    TestClient(create_app(service, event_repository=repository))
    job = _wait_for_deep_job(repository, "job-recovery-no-authoring")

    assert job["status"] == "completed", job
    assert authoring_requests == [False]
    assert repository.list_capability_versions(run.run_id) == []


def test_generic_deep_dialogue_keeps_canonical_equipment_when_provider_renames_it(
    tmp_path: Path, monkeypatch
) -> None:
    """A new hypothesis may diverge, but it stays on the selected equipment."""

    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )

    class _Provider:
        def deep_contextual_dialogue(self, _payload):
            return {
                "visible_summary": ["围绕已选装备形成新的发散假设"],
                "concept_directions": [
                    {
                        "name": "伪造主战坦克方向",
                        "innovation_thesis": "把末段拦截器改造成自主复核节点",
                        "changed_assumption": "末段拦截必须持续依赖外部制导",
                        "novelty": "由弹药转为自主任务节点",
                        "hypothesis_id": "malicious-hypothesis",
                        "equipment_form": "主战坦克",
                        "operational_mechanism": "通过独立复核压缩末段交战窗口",
                        "military_value": "直接拦截低空目标",
                        "direct_military_effects": "压缩目标反应时间",
                        "failure_boundary": "强干扰环境需验证",
                        "validation_plan": "开展仿真与实装复核",
                        "direct_evidence_refs": ["ev-parent"],
                        "stable": True,
                    }
                ],
                "capability_card_draft": {
                    "overview": "完整概述",
                    "technology_implementation": "完整装备与技术实现",
                    "operational_process": "完整关键作战流程",
                    "capability_effects": "完整能力与作战效果",
                    "winning_logic": "完整制胜逻辑机理",
                },
                "runtime": {
                    "engine": "equipment_deep_runtime_v2",
                    "tools": ["author_s6"],
                },
                "deep_divergence_status": "completed",
            }

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def create(self, *_args, **_kwargs):
            return _Provider()

    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "generic-dialogue-equipment-lock"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
            "question": "请围绕选定装备继续发散一个新的能力假设",
            "create_artifact": True,
        },
    )
    assert response.status_code == 201
    job_id = response.json()["job"]["job_id"]

    deadline = time.monotonic() + 5.0
    job = repository.get_deep_job(job_id)
    while job is not None and str(job.get("status", "")).lower() in {
        "queued",
        "running",
    } and time.monotonic() < deadline:
        time.sleep(0.02)
        job = repository.get_deep_job(job_id)

    assert job is not None and job["status"] == "completed", job
    versions = repository.list_capability_versions(run.run_id)
    assert len(versions) == 1
    snapshot = versions[0]["snapshot"]
    assert snapshot["name"] == "伪造主战坦克方向"
    assert snapshot["title"] == "伪造主战坦克方向"
    assert snapshot["primary_equipment_identity"] == "伪造主战坦克方向"
    assert snapshot["equipment_form"] == "主战坦克"
    assert snapshot["source_equipment_identity"] == "参考拦截无人机"
    # Generic deep-thinking may fork a genuinely new hypothesis; only the
    # selected equipment identity is immutable in this mode.
    assert snapshot["hypothesis_id"] == "malicious-hypothesis"


def test_unbound_global_dialogue_can_show_analysis_but_cannot_author_card(
    tmp_path: Path, monkeypatch
) -> None:
    """Single-equipment mode must not mint a card from arbitrary global IDs."""

    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "test-dialogue"},
    )

    class _Provider:
        def deep_contextual_dialogue(self, _payload):
            return {
                "visible_summary": ["全局分析可见，但没有绑定装备"],
                "concept_directions": [
                    {
                        "name": "伪造全局方向",
                        "hypothesis_id": "attacker-hypothesis",
                        "equipment_form": "伪造构型",
                        "operational_mechanism": "通过独立机理压缩交战窗口",
                        "direct_military_effects": "直接压制目标",
                        "failure_boundary": "强干扰时失效",
                        "validation_plan": "开展仿真验证",
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

    # Build the app against the normal provider catalog, then replace only
    # the worker-time registry used by the contextual dialogue adapter.
    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "unbound-global"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "attacker-hypothesis",
            "capability_id": "attacker-capability",
            "question": "请分析一个全局方向",
        },
    )
    assert response.status_code == 201
    job_id = response.json()["job"]["job_id"]
    deadline = time.monotonic() + 5.0
    job = repository.get_deep_job(job_id)
    while job is not None and str(job.get("status", "")).lower() in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.02)
        job = repository.get_deep_job(job_id)
    assert job is not None and job["status"] == "completed", job
    assert repository.list_capability_versions(run.run_id) == []


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


def test_reference_retry_does_not_requeue_live_authoring_partial(
    tmp_path: Path, monkeypatch
) -> None:
    """A live S6 hand-off is not an explicit retry boundary."""

    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    client = TestClient(create_app(service, event_repository=repository))

    first = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-live-partial-initial"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "focus": "保持当前子运行",
            "question": "继续等待受治理证据",
        },
    )
    assert first.status_code == 202
    job_id = first.json()["job"]["job_id"]
    claimed = repository.claim_deep_job(job_id)
    assert claimed is not None
    live = repository.update_deep_job(
        job_id,
        stage="s6_authoring",
        status="partial",
        claim_token=claimed["claim_token"],
    )
    assert live is not None

    retry = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "reference-live-partial-retry"},
        json={
            "hypothesis_id": "hypothesis-reference",
            "focus": "保持当前子运行",
            "question": "继续等待受治理证据",
            "retry": True,
        },
    )

    assert retry.status_code == 202
    payload = retry.json()
    assert payload["idempotent_replay"] is True
    assert payload["job"]["job_id"] == job_id
    current = repository.get_deep_job(job_id)
    assert current is not None
    assert current["stage"] == "s6_authoring"
    assert current["status"] == "partial"
    assert current["claim_token"] == claimed["claim_token"]


def test_sql_restart_recovers_new_hypothesis_artifact_from_source_session(
    tmp_path: Path, monkeypatch
) -> None:
    """A contextual turn may fork a hypothesis without losing its artifact on restart."""

    service, repository, run, output_root = _reference_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    client = TestClient(create_app(service, event_repository=repository))
    created = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "restart-new-hypothesis-session"},
        json={
            "kind": "deep-thinking",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
        },
    )
    assert created.status_code == 201
    session_id = created.json()["session"]["session_id"]

    # Keep the original formal lineage present, then append a genuinely new
    # hypothesis produced by this same contextual session.  The latter has a
    # different card binding by design, and is recoverable only via its
    # server-stamped source_session_id.
    repository.ensure_capability_baseline(
        parent_run_id=run.run_id,
        card_binding_id="binding-reference",
        hypothesis_id="hypothesis-reference",
        snapshot={
            "capability_id": "cap-reference",
            "card_binding_id": "binding-reference",
            "hypothesis_id": "hypothesis-reference",
            "name": "参考拦截无人机",
            "equipment_form": "末段拦截无人机",
        },
    )
    forked = build_reference_capability(
        run_id=run.run_id,
        query=run.topic,
        candidate={
            "name": "参考拦截无人机",
            "hypothesis_id": "hypothesis-forked",
            "equipment_form": "末段拦截无人机",
            "operational_mechanism": "在末段复核窗口压缩目标反应时间",
            "direct_military_effects": "直接拦截低空目标",
            "failure_boundary": "强干扰环境需验证",
            "validation_plan": "开展仿真与实装复核",
            "evidence_ids": ["ev-parent"],
        },
        focus="验证新假设",
        source_session_id=session_id,
    )
    repository.save_capability_version(
        version_id="forked-hypothesis-version",
        parent_run_id=run.run_id,
        card_binding_id=str(forked["card_binding_id"]),
        hypothesis_id="hypothesis-forked",
        snapshot=forked,
        source="deep-thinking",
        evidence_refs=["ev-parent"],
    )
    unrelated = build_reference_capability(
        run_id=run.run_id,
        query=run.topic,
        candidate={
            "name": "其他装备方向",
            "hypothesis_id": "hypothesis-other",
            "equipment_form": "其他构型",
            "operational_mechanism": "不应出现在本会话",
            "direct_military_effects": "不应出现在本会话",
            "evidence_ids": ["ev-parent"],
        },
        source_session_id="another-session",
    )
    repository.save_capability_version(
        version_id="other-session-version",
        parent_run_id=run.run_id,
        card_binding_id=str(unrelated["card_binding_id"]),
        hypothesis_id="hypothesis-other",
        snapshot=unrelated,
        source="deep-thinking",
        evidence_refs=["ev-parent"],
    )

    # Rebuild the app/repository to model a worker/API process restart.  No
    # sidecar session read is involved in this assertion.
    database_url = f"sqlite:///{tmp_path / 'deep-dialogue.db'}"
    restarted_repository = SqlRunRepository(create_database_engine(database_url))
    restarted_service = ResearchApplicationService(
        repository=restarted_repository,
        queue=SqlRunQueue(create_database_engine(database_url)),
    )
    restarted = TestClient(
        create_app(restarted_service, event_repository=restarted_repository)
    )
    recovered = restarted.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}"
    )
    assert recovered.status_code == 200
    artifacts = recovered.json()["session"]["artifacts"]
    assert any(item.get("hypothesis_id") == "hypothesis-forked" for item in artifacts)
    assert all(item.get("hypothesis_id") != "hypothesis-other" for item in artifacts)


def test_round_summary_context_is_compact_and_excludes_raw_swarm_payload(
    tmp_path: Path, monkeypatch
) -> None:
    """Deep prompts receive visible status/logic, never the full audit artifact."""

    service, _repository, run, output_root = _reference_fixture(tmp_path, monkeypatch)
    run_root = output_root / run.run_id
    long_payload = "provider-secret-trace " * 20_000
    (run_root / "round_summary.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "audit_status": "passed",
                "report_available": True,
                "usage": {"raw_metadata": long_payload},
                "performance_summary": {
                    "model_call_count": 12,
                    "selected_agent_count": 3,
                    "wall_time_seconds": 4.56789,
                    "raw_provider_blob": long_payload,
                },
                "winning_mechanism": {
                    "winning_logic": "以本地闭环压缩对手反应窗口",
                    "reasoning_nodes": [{"summary": long_payload}],
                },
                "winning_swarm": {
                    "provider_metadata": {"api_key": "must-not-survive"},
                    "hypothesis_ledger": {
                        "hypotheses": [
                            {
                                "title": "本地末段复核",
                                "changed_confrontation_variable": "把持续链路依赖改为末段自主复核",
                                "mechanism_chain": "在末段窗口完成识别到作用闭环",
                                "direct_military_effects": ["压缩目标反应时间"],
                            }
                        ]
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(service, event_repository=_repository))
    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "compact-round-summary"},
        json={
            "kind": "reference-research",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
        },
    )
    assert response.status_code == 201
    summary = response.json()["session"]["context_refs"]["round_summary"]
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)

    assert summary["status"] == "completed"
    assert summary["audit_status"] == "passed"
    assert summary["report_available"] is True
    assert summary["performance_summary"]["model_call_count"] == 12
    assert summary["performance_summary"]["wall_time_seconds"] == 4.568
    assert "usage" not in summary
    assert "winning_swarm" not in summary
    assert "winning_mechanism" not in summary
    assert "winning_logic_summary" in summary
    assert "本地末段复核" in summary["winning_logic_summary"]
    assert "provider-secret-trace" not in encoded
    assert "api_key" not in encoded
    assert len(encoded) <= 4200


def test_running_dialogue_accepts_durable_steers_and_branch_forks(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, _ = _reference_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "Thread", _DeferredThread)
    client = TestClient(create_app(service, event_repository=repository))
    created = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": "steer-session"},
        json={"title": "可纠偏深研"},
    )
    assert created.status_code == 201
    session_id = created.json()["session"]["session_id"]
    turn = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
        headers={"Idempotency-Key": "steer-turn"},
        json={"content": "研究低成本颠覆路线", "create_artifact": False},
    )
    assert turn.status_code == 202
    job_id = turn.json()["job"]["job_id"]
    root_message_id = turn.json()["user_message"]["message_id"]

    steer_payload = {
        "content": "把快速部署作为优先约束",
        "mode": "steer",
        "client_steer_id": "client-steer-1",
        "branch_id": "main",
    }
    first = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/{job_id}/steers",
        json=steer_payload,
    )
    replay = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/{job_id}/steers",
        json=steer_payload,
    )
    assert first.status_code == 202
    assert replay.status_code == 202
    assert first.json()["steer"]["steer_id"] == replay.json()["steer"]["steer_id"]
    assert repository.list_deep_steers(job_id)[0]["status"] == "pending"

    fork = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/branches",
        headers={"Idempotency-Key": "fork-rapid-route"},
        json={
            "from_message_id": root_message_id,
            "branch_id": "rapid-route",
            "title": "快速部署路线",
        },
    )
    assert fork.status_code == 201
    assert fork.json()["branch"]["branch_id"] == "rapid-route"
    branch_turn = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
        headers={"Idempotency-Key": "branch-turn"},
        json={
            "content": "在该分支仅比较快速部署构型",
            "branch_id": "rapid-route",
            "parent_message_id": root_message_id,
        },
    )
    assert branch_turn.status_code == 202
    assert branch_turn.json()["job"]["branch_id"] == "rapid-route"
    session = client.get(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}"
    ).json()["session"]
    assert {item["branch_id"] for item in session["branches"]} >= {
        "main",
        "rapid-route",
    }
    branch_messages = [
        item for item in session["messages"] if item["branch_id"] == "rapid-route"
    ]
    assert branch_messages[0]["parent_message_id"] == root_message_id


@pytest.mark.parametrize(
    ("mode", "parent_status", "steer_status"),
    [
        ("queue", "completed", "parked"),
        ("interrupt_send", "cancelled", "applied"),
    ],
)
def test_parked_and_interrupt_send_steers_start_one_serial_followup(
    tmp_path: Path,
    monkeypatch,
    mode: str,
    parent_status: str,
    steer_status: str,
) -> None:
    service, repository, run, _ = _reference_fixture(
        tmp_path,
        monkeypatch,
        execution={"mode": "real", "provider": "steer-aware"},
    )

    class _Provider:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.steer_callback = None
            self.questions: list[str] = []

        def set_deep_dialogue_progress_callback(self, _callback) -> None:
            return None

        def set_deep_dialogue_steer_callback(self, callback) -> None:
            self.steer_callback = callback

        def deep_contextual_dialogue(self, payload):
            self.questions.append(str(payload.get("question", "")))
            if len(self.questions) == 1:
                self.started.set()
                assert self.release.wait(3.0)
            if callable(self.steer_callback):
                self.steer_callback("before_synthesis")
            return {
                "visible_summary": ["已完成当前装备方向分析"],
                "concept_directions": [],
                "deep_divergence_status": "completed",
            }

    provider = _Provider()

    class _Registry:
        @classmethod
        def load(cls, _path):
            return cls()

        def create(self, *_args, **_kwargs):
            return provider

    client = TestClient(create_app(service, event_repository=repository))
    monkeypatch.setattr(app_module, "ProviderRegistry", _Registry)
    created = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions",
        headers={"Idempotency-Key": f"serial-{mode}-session"},
        json={
            "kind": "reference-research",
            "hypothesis_id": "hypothesis-reference",
            "candidate": {"hypothesis_id": "hypothesis-reference"},
        },
    )
    session_id = created.json()["session"]["session_id"]
    turn = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/sessions/{session_id}/messages",
        headers={"Idempotency-Key": f"serial-{mode}-turn"},
        json={"content": "先完成当前方向分析", "create_artifact": False},
    )
    parent_job_id = turn.json()["job"]["job_id"]
    assert provider.started.wait(3.0)

    followup = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/jobs/{parent_job_id}/steers",
        json={
            "content": "转向验证低成本快速部署构型",
            "mode": mode,
            "client_steer_id": f"client-{mode}",
            "branch_id": "main",
        },
    )
    assert followup.status_code == 202
    provider.release.set()

    deadline = time.monotonic() + 6.0
    jobs = repository.list_deep_jobs(run.run_id)
    while time.monotonic() < deadline:
        children = [item for item in jobs if item.get("parent_job_id") == parent_job_id]
        if len(children) == 1 and children[0]["status"] == "completed":
            break
        time.sleep(0.02)
        jobs = repository.list_deep_jobs(run.run_id)

    parent = repository.get_deep_job(parent_job_id)
    children = [item for item in jobs if item.get("parent_job_id") == parent_job_id]
    assert parent is not None and parent["status"] == parent_status
    assert parent["steer_closed"] is True
    assert len(children) == 1, jobs
    assert children[0]["status"] == "completed", children[0]
    assert repository.list_deep_steers(parent_job_id)[0]["status"] == steer_status
    assert provider.questions == [
        "先完成当前方向分析",
        "转向验证低成本快速部署构型",
    ]
    steer_message_id = followup.json()["steer"]["message_id"]
    assert sum(
        item["message_id"] == steer_message_id
        for item in repository.list_deep_messages(session_id)
    ) == 1
