import json
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

from equipment_deep_research.api.app import (
    _capability_api_view,
    _interaction_workflow_phases,
    _interaction_workflow_summary,
    _preferred_report_path,
    _public_trace_interaction,
    _suppress_cross_card_capability_contamination,
    create_app,
)
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.domain.models import CapabilityImageItem, to_plain
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import (
    SqlRunQueue,
    SqlRunRepository,
)
from equipment_deep_research.deep_runtime.gateways import (
    GatewayIdentity,
    TelegramGatewayAdapter,
    VerifiedChannelGateway,
    WebhookSignaturePolicy,
)


def test_api_exposes_deployment_mcp_config_without_starting_transport(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp-host.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "deep-mcp-host-v1",
                "servers": [
                    {
                        "server_id": "host:echo",
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["missing-until-a-real-turn.py"],
                        "allowed_tools": ["echo"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    app = create_app(mcp_config_path=config_path)

    with TestClient(app) as client:
        response = client.get("/api/v1/deep-thinking/capabilities")
        assert response.status_code == 200
        host = response.json()["mcp_host"]
        assert host["status"] == "configured"
        assert host["reload"] == "per_turn"
        assert host["servers"] == [
            {
                "server_id": "host:echo",
                "transport": "stdio",
                "allowed_tools": ["echo"],
                "limits": {
                    "max_concurrent_calls": 4,
                    "max_calls_per_turn": 64,
                    "max_result_bytes": 262144,
                    "max_result_depth": 16,
                    "max_result_items": 4096,
                },
            }
        ]
        assert app.state.deep_mcp_host._current._thread is None
    assert app.state.deep_mcp_host._closed


def test_api_channel_webhook_uses_verified_gateway_and_redacts_result() -> None:
    policy = WebhookSignaturePolicy(secret="channel-test", tolerance_seconds=60)
    adapter = TelegramGatewayAdapter(allowed_senders=["17"], allowed_chats=["42"])
    calls = []

    def resolve_session(identity: GatewayIdentity, _payload: dict) -> str:
        assert identity.chat_id == "42"
        return "run-1:session-1"

    def execute(payload: dict) -> dict:
        calls.append(payload)
        assert payload["session_key"] == "run-1:session-1"
        return {
            "visible_summary": ["已完成深度发散"],
            "provider_metadata": {"api_key": "private"},
        }

    gateway = VerifiedChannelGateway(
        adapter=adapter,
        signature_policy=policy,
        session_resolver=resolve_session,
        execute=execute,
    )
    app = create_app(channel_gateways={"telegram": gateway})
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 9,
            "from": {"id": 17},
            "chat": {"id": 42},
            "text": "继续发散",
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "X-Deep-Gateway-Timestamp": "1000",
        "X-Deep-Gateway-Nonce": "api-webhook-1",
        "X-Deep-Gateway-Signature": policy.sign(
            body, timestamp="1000", nonce="api-webhook-1"
        ),
    }
    # The route uses wall clock time, so sign with a current timestamp for
    # the HTTP request while retaining deterministic replay coverage in the
    # gateway unit tests.
    import time
    timestamp = str(int(time.time()))
    headers["X-Deep-Gateway-Timestamp"] = timestamp
    headers["X-Deep-Gateway-Signature"] = policy.sign(
        body, timestamp=timestamp, nonce="api-webhook-1"
    )
    with TestClient(app) as client:
        response = client.post("/api/v1/channels/telegram/webhook", content=body, headers=headers)
        rejected_replay = client.post("/api/v1/channels/telegram/webhook", content=body, headers=headers)
        headers["X-Deep-Gateway-Nonce"] = "api-webhook-retry"
        headers["X-Deep-Gateway-Signature"] = policy.sign(
            body, timestamp=timestamp, nonce="api-webhook-retry"
        )
        retry = client.post("/api/v1/channels/telegram/webhook", content=body, headers=headers)
        oversized = client.post("/api/v1/channels/telegram/webhook", content=b"x" * (256 * 1024 + 1))
        unconfigured = client.post("/api/v1/channels/discord/webhook", content=body, headers=headers)
    assert response.status_code == 200
    assert rejected_replay.status_code == 403
    assert retry.status_code == 200
    assert retry.json() == response.json()
    assert len(calls) == 1
    assert oversized.status_code == 413
    assert unconfigured.status_code == 404
    result = response.json()
    assert result["session_key"] == "run-1:session-1"
    assert result["result"]["provider_metadata"] == "<redacted>"
    assert result["deliveries"][0]["chat_id"] == "42"


def test_api_creates_and_queues_run() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/v1/runs",
        json={
            "topic": "test",
            "research_route": "auto",
            "selected_agent_ids": [],
            "max_rounds": 5,
        },
    )
    assert created.status_code == 201
    assert created.json()["report_template_mode"] == "project_argument_v1"
    assert created.json()["execution_profile_id"] == "winning_swarm_dynamic_v2"
    started = client.post(
        f"/api/v1/runs/{created.json()['run_id']}/start",
        headers={"Idempotency-Key": "start-1"},
    )
    assert started.json()["status"] == "queued"


def test_deep_mutations_require_idempotency_key_even_without_sql_ledger() -> None:
    """Merge/review commands must fail closed before any compatibility path."""

    service = ResearchApplicationService()
    client = TestClient(create_app(service))
    created = client.post("/api/v1/runs", json={"topic": "deep key", "research_route": "auto"})
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    merge = client.post(
        f"/api/v1/runs/{run_id}/deep-thinking/sessions/missing/merge",
        json={"artifact_id": "artifact"},
    )
    assert merge.status_code == 400
    assert "Idempotency-Key" in merge.json()["detail"]

    verify = client.post(
        f"/api/v1/runs/{run_id}/capability-versions/version-missing/verify",
        headers={"X-Role": "reviewer"},
        json={"status": "verified"},
    )
    assert verify.status_code == 400
    assert "Idempotency-Key" in verify.json()["detail"]


def test_reference_research_rejects_formal_card_without_selection_status(
    tmp_path: Path, monkeypatch
) -> None:
    """A formal S6 projection remains fenced even without legacy selection fields."""

    output_root = tmp_path / "runs"
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("formal reference guard", "auto", [], 1, "analyst"))
    run_dir = output_root / run.run_id
    run_dir.mkdir(parents=True)
    (run_dir / "capability_images.json").write_text(
        json.dumps(
            [
                {
                    "capability_id": "formal-capability",
                    "card_binding_id": "formal-binding",
                    "hypothesis_id": "formal-hypothesis",
                    "name": "正式能力卡",
                    "mechanism_chain": "通过末段诱导压缩对手交战窗口",
                    "military_value": "直接压制目标并打开突防窗口",
                    "version_status": "formal",
                    "verification_status": "formal",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service.set_status(run.run_id, "completed")
    client = TestClient(create_app(service))

    response = client.post(
        f"/api/v1/runs/{run.run_id}/deep-thinking/reference-research",
        headers={"Idempotency-Key": "formal-reference-guard"},
        json={
            "hypothesis_id": "formal-hypothesis",
            "candidate": {"name": "正式能力卡"},
        },
    )

    assert response.status_code == 409
    assert "already passed" in response.json()["detail"]


def test_capability_api_suppresses_legacy_cross_card_portrait() -> None:
    rows = [
        {
            "name": "蜂群母弹式自寻的子弹药",
            "capability_image": "概述：浪面跳跃无人爆破艇实施近岸末段爆破。",
            "deep_capability_portrait": "概述：浪面跳跃无人爆破艇实施近岸末段爆破。",
        },
        {
            "name": "浪面跳跃无人爆破艇",
            "capability_image": "概述：浪面跳跃无人爆破艇实施近岸末段爆破。",
        },
    ]

    safe = _suppress_cross_card_capability_contamination(rows)

    assert safe[0]["verification_status"] == "pending"
    assert safe[0]["confidence_limited"] is True
    assert safe[0]["capability_image"] == ""
    assert safe[1]["capability_image"]


def test_capability_api_preserves_quality_limited_s6_provenance() -> None:
    payload = _capability_api_view(
        {
            "name": "断链复核巡猎弹",
            "capability_image": "概述：保留受限但可审阅的S6画像。",
            "capability_portrait_modules": {"overview": "保留受限画像。"},
            "portrait_authoring_status": "authored_quality_limited",
            "portrait_module_character_counts": {"overview": 8},
            "portrait_quality_warnings": ["概述低于380字增强触发线"],
            "portrait_quality_contract_version": (
                "s6-portrait-v3-target400x5-min380"
            ),
        }
    )

    assert payload["portrait_authoring_status"] == "authored_quality_limited"
    assert payload["analysis_provenance_status"] == "limited_quality"
    assert payload["portrait_quality_warnings"] == ["概述低于380字增强触发线"]


def test_capability_api_withholds_portrait_when_independent_s6_authoring_failed() -> None:
    payload = _capability_api_view(
        {
            "name": "崖影穿谷攻击无人机",
            "portrait_authoring_status": "limited_provider_failure",
            "capability_portrait_modules": {
                "overview": "不应继续展示的历史回退概述。",
            },
            "capability_image": "概述：不应继续展示的历史回退概述。",
            "deep_capability_portrait": "概述：不应继续展示的历史回退概述。",
        }
    )

    assert payload["capability_portrait_modules"] == {}
    assert payload["capability_image"] == ""
    assert payload["deep_capability_portrait"] == ""
    assert payload["analysis_provenance_status"] == "limited_failure"
    assert any("停用回退模板" in item for item in payload["portrait_quality_warnings"])


def test_quality_limited_status_survives_domain_to_api_projection() -> None:
    item = CapabilityImageItem(
        capability_id="s6-domain-limited",
        name="断链复核巡猎弹",
        equipment_category="远程精确打击弹药",
        capability_type="new_capability",
        source_winning_logic="把持续链路依赖改为弹上受控复核",
        related_scenario="强干扰时敏目标猎歼",
        priority="P1",
        capability_gap="断链后目标复核不足",
        capability_image="原创五栏画像",
        evidence_ids=["ev-s6"],
        confidence=0.68,
        portrait_authoring_status="authored_quality_limited",
        capability_portrait_modules={"overview": "受限画像"},
        portrait_module_character_counts={"overview": 4},
        portrait_quality_warnings=["overview低于380字增强触发线"],
        portrait_quality_contract_version="s6-portrait-v3-target400x5-min380",
    )

    projected = _capability_api_view(to_plain(item))

    assert projected["portrait_authoring_status"] == "authored_quality_limited"
    assert projected["analysis_provenance_status"] == "limited_quality"
    assert projected["portrait_module_character_counts"] == {"overview": 4}
    assert projected["portrait_quality_contract_version"] == (
        "s6-portrait-v3-target400x5-min380"
    )


def test_workflow_summary_prioritizes_limited_s6_release_status() -> None:
    workflow = _interaction_workflow_summary(
        [
            {
                "event_type": "winning_s6_release_gate_evaluated",
                "details": {
                    "passed": True,
                    "failed": False,
                    "limited": True,
                    "warnings": ["一张画像仍低于当前逐栏质量合同"],
                    "authored_cards": [],
                },
            }
        ],
        SimpleNamespace(
            status="researching",
            research_route="new_winning_mechanism",
            discovery_branch="A",
            execution_profile_id="winning_swarm_dynamic_v2",
            execution={},
            result={},
        ),
    )

    gate = workflow["swarm_cluster"]["s6_release_gate"]
    assert gate["passed"] is True
    assert gate["limited"] is True
    assert gate["status"] == "limited"
    assert workflow["swarm_cluster"]["s6_authoring"]["status"] == "limited"


def test_runtime_capacity_api_persists_capacity_and_updates_health(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_WORKER_POOL_CONFIG", str(tmp_path / "pool.json"))
    client = TestClient(create_app())

    updated = client.put(
        "/api/v1/runtime-capacity",
        headers={"X-Role": "analyst"},
        json={"capacity": 4},
    )

    assert updated.status_code == 200
    assert updated.json()["desired_capacity"] == 4
    health = client.get("/api/v1/runtime-health").json()
    assert health["configured_worker_capacity"] == 4
    assert health["capacity_limit"] == 8


def test_runtime_capacity_api_validates_range_and_role(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_WORKER_POOL_CONFIG", str(tmp_path / "pool.json"))
    client = TestClient(create_app())

    assert (
        client.put("/api/v1/runtime-capacity", json={"capacity": 0}).status_code == 422
    )
    assert (
        client.put("/api/v1/runtime-capacity", json={"capacity": 9}).status_code == 422
    )
    denied = client.put(
        "/api/v1/runtime-capacity",
        headers={"X-Role": "reviewer"},
        json={"capacity": 3},
    )
    assert denied.status_code == 403


def test_api_allows_duplicate_topics_without_reusing_run_identity() -> None:
    client = TestClient(create_app())
    payload = {
        "topic": "强电磁压制下精确打击任务续接装备研究",
        "research_route": "auto",
        "selected_agent_ids": [],
        "max_rounds": 2,
    }

    first = client.post("/api/v1/runs", json=payload)
    second = client.post("/api/v1/runs", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["topic"] == second.json()["topic"]
    assert first.json()["run_id"] != second.json()["run_id"]


def test_api_create_run_is_idempotent_when_key_is_supplied() -> None:
    client = TestClient(create_app())
    payload = {
        "topic": "启动按钮重复提交保护",
        "research_route": "auto",
        "selected_agent_ids": [],
        "max_rounds": 2,
    }
    headers = {"Idempotency-Key": "create-run-once"}

    first = client.post("/api/v1/runs", json=payload, headers=headers)
    second = client.post("/api/v1/runs", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["run_id"] == first.json()["run_id"]
    assert len(client.get("/api/v1/runs").json()) == 1


def test_api_rejects_reusing_create_idempotency_key_for_different_payload() -> None:
    client = TestClient(create_app())
    headers = {"Idempotency-Key": "create-run-conflict"}

    first = client.post(
        "/api/v1/runs", json={"topic": "第一个任务"}, headers=headers
    )
    conflict = client.post(
        "/api/v1/runs", json={"topic": "不同任务"}, headers=headers
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert "idempotency key" in conflict.json()["detail"]


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


def test_preferred_report_path_requires_a_passing_postfix_gate(tmp_path: Path) -> None:
    original = tmp_path / "report.md"
    postfix = tmp_path / "report-postfix.md"
    gate = tmp_path / "report-quality-gate-postfix.json"
    failure = tmp_path / "report_failure.json"
    original.write_text("original", encoding="utf-8")
    postfix.write_text("postfix", encoding="utf-8")

    failure.write_text(
        json.dumps(
            {
                "status": "limited_quality_gate",
                "report_written": False,
                "partial_report_path": "report-partial.md",
                "partial_report_available": True,
            }
        ),
        encoding="utf-8",
    )
    gate.write_text(json.dumps({"passed": False}), encoding="utf-8")
    assert _preferred_report_path(tmp_path) is None

    gate.write_text(json.dumps({"passed": True}), encoding="utf-8")
    assert _preferred_report_path(tmp_path) == postfix

    gate.write_text("not-json", encoding="utf-8")
    assert _preferred_report_path(tmp_path) is None


def test_preferred_report_path_exposes_completed_report_with_failed_quality_gate(
    tmp_path: Path,
) -> None:
    """A quality-gate failure is advisory for a completed run, not a deletion."""

    original = tmp_path / "report.md"
    original.write_text("completed but quality-limited report", encoding="utf-8")
    (tmp_path / "report_quality_gate.json").write_text(
        json.dumps({"passed": False}),
        encoding="utf-8",
    )

    assert _preferred_report_path(tmp_path) == original


def test_report_api_prefers_approved_postfix_without_overwriting_original(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'postfix-report.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(
        CreateRunCommand("postfix report", "auto", [], 2, "analyst")
    )
    run_dir = tmp_path / run.run_id
    run_dir.mkdir()
    original = run_dir / "report.md"
    original.write_text("original with internal marker", encoding="utf-8")
    (run_dir / "report-postfix.md").write_text("approved postfix", encoding="utf-8")
    (run_dir / "report-quality-gate-postfix.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )
    service.set_result(run.run_id, {"run_dir": str(run_dir)})
    service.set_status(run.run_id, "completed")

    response = TestClient(create_app(service)).get(
        f"/api/v1/runs/{run.run_id}/report",
        headers={"X-Role": "reviewer"},
    )

    assert response.status_code == 200
    assert response.text == "approved postfix"
    assert original.read_text(encoding="utf-8") == "original with internal marker"


def test_report_api_allows_analyst_read_for_report_workspace(tmp_path: Path) -> None:
    """The analyst-facing report workspace can read the immutable report."""

    engine = create_database_engine(f"sqlite:///{tmp_path / 'analyst-report.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(
        CreateRunCommand("analyst report", "auto", [], 2, "analyst")
    )
    run_dir = tmp_path / run.run_id
    run_dir.mkdir()
    (run_dir / "report.md").write_text("analyst-visible report", encoding="utf-8")
    service.set_result(run.run_id, {"run_dir": str(run_dir)})
    service.set_status(run.run_id, "completed")

    response = TestClient(create_app(service, event_repository=repository)).get(
        f"/api/v1/runs/{run.run_id}/report",
        headers={"X-Role": "analyst"},
    )

    assert response.status_code == 200
    assert response.text == "analyst-visible report"


def test_report_api_blocks_partial_quality_gate_download(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'partial-report.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(
        CreateRunCommand("partial report", "auto", [], 2, "analyst")
    )
    run_dir = tmp_path / run.run_id
    run_dir.mkdir()
    (run_dir / "report.md").write_text("draft report", encoding="utf-8")
    (run_dir / "report_failure.json").write_text(
        json.dumps(
            {
                "status": "limited_quality_gate",
                "report_written": False,
                "partial_report_path": "report-partial.md",
                "partial_report_available": True,
            }
        ),
        encoding="utf-8",
    )
    service.set_result(run.run_id, {"run_dir": str(run_dir)})
    service.set_status(run.run_id, "completed")

    response = TestClient(create_app(service)).get(
        f"/api/v1/runs/{run.run_id}/report",
        headers={"X-Role": "reviewer"},
    )

    assert response.status_code == 404


def test_api_prefers_current_output_root_and_strips_path_fields(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "runs"
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    engine = create_database_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    repository = SqlRunRepository(engine)
    service = ResearchApplicationService(
        repository=repository,
        queue=SqlRunQueue(engine),
    )
    run = service.create_run(
        CreateRunCommand("migrated paths", "auto", [], 2, "analyst")
    )

    legacy_root = tmp_path / "legacy" / run.run_id
    legacy_root.mkdir(parents=True)
    (legacy_root / "report.md").write_text("legacy report", encoding="utf-8")
    (legacy_root / "round_summary.json").write_text(
        json.dumps({"resolved_route": "legacy"}),
        encoding="utf-8",
    )

    current_root = output_root / run.run_id
    current_root.mkdir(parents=True)
    (current_root / "report.md").write_text("current report", encoding="utf-8")
    (current_root / "round_summary.json").write_text(
        json.dumps({"resolved_route": "current"}),
        encoding="utf-8",
    )
    (current_root / "capability_images.json").write_text(
        json.dumps(
            [
                {
                    "capability_id": "cap-new-001",
                    "name": "远海反分布式火力游荡攻击无人机",
                    "priority": "P1",
                    "confidence": 0.81,
                    "capability_gap": "旧目录应被忽略",
                    "equipment_category": "无人机",
                    "equipment_form": "远海反分布式火力游荡攻击无人机",
                }
            ]
        ),
        encoding="utf-8",
    )
    service.set_result(
        run.run_id,
        {
            "run_dir": str(legacy_root),
            "report_path": str(legacy_root / "report.md"),
            "summary_path": str(legacy_root / "round_summary.json"),
            "capability_images_path": str(legacy_root / "capability_images.json"),
            "manifest_path": str(legacy_root / "delivery-manifest.json"),
            "branch_deliverables_path": str(legacy_root / "branch_deliverables.json"),
            "capability_count": 1,
        },
    )
    service.set_status(run.run_id, "completed")

    client = TestClient(create_app(service, event_repository=repository))
    loaded = client.get(f"/api/v1/runs/{run.run_id}").json()

    assert loaded["result"]["report_available"] is True
    assert "run_dir" not in loaded["result"]
    assert "report_path" not in loaded["result"]
    assert "summary_path" not in loaded["result"]
    assert "capability_images_path" not in loaded["result"]
    assert (
        client.get(f"/api/v1/runs/{run.run_id}/summary").json()["resolved_route"]
        == "current"
    )
    assert (
        client.get(
            f"/api/v1/runs/{run.run_id}/report",
            headers={"X-Role": "reviewer"},
        ).text
        == "current report"
    )
    assert client.get("/api/v1/runs").json()[0]["result"]["report_available"] is True


def test_capability_api_view_projects_complete_process_and_verification() -> None:
    row = {
        "capability_id": "cap-upgrade-001",
        "name": "JASSM-ER空射巡航导弹抗扰突防升级",
        "capability_type": "upgrade",
        "equipment_category": "JASSM-ER空射低可探测防区外巡航导弹",
        "equipment_form": "JASSM-ER空射低可探测防区外巡航导弹",
        "source_winning_logic": "降低持续外部更新依赖",
        "related_scenario": "强电磁压制下精确打击任务续接",
        "priority": "P1",
        "capability_gap": "现役弹药不能证明强欺骗条件下的任务闭合质量；其他装备方向差距并",
        "capability_image": "旧画像",
        "evidence_ids": ["ev-1"],
        "confidence": 0.8,
        "operational_process": ["保留防区外投送", "验证导航可信度"],
        "verification_plan": ["开展接口联试"],
    }

    projected = _capability_api_view(row)

    assert projected["operational_process"] == [
        "保留防区外投送",
        "验证导航可信度",
    ]
    assert projected["verification_plan"] == ["开展接口联试"]
    assert projected["problem_statement"].endswith("任务闭合质量")
    assert projected["deep_capability_portrait"] == "旧画像"


def test_capability_api_view_removes_repeated_legacy_verification_fill() -> None:
    boilerplate = (
        "对测试巡飞弹的样机考核还应覆盖"
        "异常工况、授权撤销和失效后的安全处置。"
    )
    projected = _capability_api_view(
        {
            "name": "测试巡飞弹",
            "equipment_form": "测试巡飞弹",
            "capability_image": f"概述：保留原创判断。{boilerplate}",
            "deep_capability_portrait": f"概述：保留原创判断。{boilerplate}",
            "semantic_consistency_check": {"review": boilerplate},
        }
    )

    assert projected["capability_image"] == "概述：保留原创判断。"
    assert projected["deep_capability_portrait"] == "概述：保留原创判断。"
    assert projected["semantic_consistency_check"]["review"] == ""


def test_capability_api_view_preserves_current_v5_authored_overview() -> None:
    overview = (
        "敌方无人机群利用密集航路压缩末端拦截窗口；分布式裂群拦截弹在波前释放微型"
        "拦截单元，优先冲击领航机与中继机，使编队失去协同并直接降低有效突防数量。"
    )
    row = {
        "name": "分布式裂群拦截弹",
        "portrait_authoring_status": "s6_authored_semantically_consistent",
        "portrait_quality_contract_version": "s6-portrait-v5-target380x5-soft",
        "capability_portrait_modules": {
            "overview": overview,
            "technology_implementation": "弹体释放机构与微型单元导引头、飞控和碰撞载荷联锁。",
            "operational_process": "预警确认群体航迹后发射，母弹在波前裂群，子单元分区接敌。",
            "capability_effects": "形成对领航、中继和高价值载荷节点的并行拦截能力。",
            "winning_logic": "把逐架交换改为破坏编队结构，使密集队形转化为并行接敌机会。",
        },
    }

    projected = _capability_api_view(row)

    assert projected["capability_portrait_modules"]["overview"] == overview
    assert "把原本依赖固定节奏的处置过程" not in projected[
        "deep_capability_portrait"
    ]


def test_capability_api_view_preserves_complete_columns_over_400_characters() -> None:
    long_complete = (
        "敌方以持续机动隐藏目标，装备在有限窗口内完成复核并形成直接毁伤，"
        "迫使其改变部署并暴露新的防护节点。"
    ) * 10
    modules = {
        "overview": long_complete,
        "technology_implementation": long_complete,
        "operational_process": long_complete,
        "capability_effects": long_complete,
        "winning_logic": long_complete,
    }

    projected = _capability_api_view(
        {
            "name": "长栏完整性测试装备",
            "portrait_authoring_status": "s6_authored_semantically_consistent",
            "capability_portrait_modules": modules,
        }
    )

    assert len(projected["capability_portrait_modules"]["overview"]) > 400
    assert projected["capability_portrait_modules"] == modules
    for label in (
        "概述",
        "装备与技术实现",
        "关键作战流程",
        "形成能力与作战效果",
        "制胜逻辑机理",
    ):
        assert f"{label}：{long_complete}" in projected["deep_capability_portrait"]


def test_capability_api_confidence_varies_with_card_evidence_fit() -> None:
    common = {
        "confidence": 0.58,
        "equipment_form": "地形匹配末制导巡飞弹",
        "target_scenario": "强干扰山谷中断链逼近雷达车",
        "operational_mechanism": "惯导结合地形轮廓匹配并末段复核雷达车",
        "evidence_ids": ["ev-1", "ev-2"],
    }

    matched = _capability_api_view(
        {
            **common,
            "name": "断链地形匹配巡飞弹",
            "evidence_basis": ["强干扰山谷中以地形匹配维持航迹并复核雷达车。"],
            "direct_evidence_refs": ["ev-weapon-1", "ev-scene-1"],
        }
    )
    generic = _capability_api_view(
        {
            **common,
            "name": "通用保障巡飞弹",
            "evidence_basis": ["公开材料仅讨论后勤韧性与人才培养。"],
        }
    )

    assert 0.60 <= matched["confidence"] <= 0.80
    assert matched["confidence"] > generic["confidence"]
    assert matched["confidence_components"]["evidence_fit"] > generic[
        "confidence_components"
    ]["evidence_fit"]


def test_capabilities_api_does_not_expose_s5_portfolio_as_s6_portrait(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "runs"
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand("S6 画像实时展示", "auto", [], 2, "analyst")
    )
    (output_root / run.run_id).mkdir(parents=True)
    portfolio = {
        "hypothesis_id": "hypothesis-s6-1",
        "name": "远程网络断点压制巡航弹",
        "equipment_form": "远程空射或陆射网络断点压制巡航弹",
        "type": "new_capability",
        "priority": "P1",
        "confidence": 0.82,
        "function": "在弱网远海场景压制传感与通信节点，打开后续火力通路。",
        "operational_mechanism": "前出搜索节点，实施压制后触发主攻火力续接。",
        "military_value": "削弱拦截协同并缩短后续火力突防窗口。",
        "failure_boundary": "敌方多路径冗余未出现实质降级时判退。",
        "development_path": "以仿真靶网、接口联试和对抗试验逐步验证。",
        "deep_capability_portrait": (
            "面向弱网远海联合火力交战场景，该巡航弹以前出搜索和网络断点压制"
            "破坏敌方传感、通信与拦截协同，使主攻火力在对手恢复链路前完成突防。"
        ),
        "direct_evidence_refs": ["ev-s6-1", "ev-s6-2"],
    }

    class EventRepository:
        def events_after(self, run_id: str, sequence: int) -> list[dict]:
            if run_id != run.run_id or sequence >= 1:
                return []
            return [
                {
                    "run_id": run_id,
                    "sequence": 1,
                    "event_type": "winning_portfolio_merge_completed",
                    "payload": {
                        "source": "trace",
                        "event": {
                            "event_id": "trace-s6-portfolio",
                            "event_type": "winning_portfolio_merge_completed",
                            "actor": "winning_swarm_controller",
                            "summary": "S6 组合完成",
                            "created_at": "2026-08-07T12:00:00+00:00",
                            "input_refs": [],
                            "output_refs": ["hypothesis-s6-1"],
                            "payload": {
                                "selected_hypothesis_ids": ["hypothesis-s6-1"],
                                "final_equipment_portfolio": [portfolio],
                            },
                        },
                    },
                }
            ]

    response = TestClient(create_app(service, event_repository=EventRepository())).get(
        f"/api/v1/runs/{run.run_id}/capabilities"
    )

    assert response.status_code == 200
    assert response.json() == []


def test_capabilities_api_exposes_s6_authored_card_before_delivery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "runs"
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("S6 原创画像", "auto", [], 2, "analyst"))
    (output_root / run.run_id).mkdir(parents=True)
    direction = {
        "hypothesis_id": "hypothesis-s6-authored-1",
        "name": "“断潮”网络断点压制巡航弹",
        "equipment_form": "远程空射网络断点压制巡航弹",
        "type": "new_capability",
        "capability_portrait": "概述：在弱网远海压制传感与通信节点，打开后续火力通路。",
        "deep_capability_portrait": "概述：在弱网远海压制传感与通信节点，打开后续火力通路。",
        "capability_portrait_modules": {"overview": "在弱网远海压制传感与通信节点，打开后续火力通路。"},
        "semantic_consistency_check": {"consistent": True},
        "s6_authoring_status": "authored_semantically_consistent",
        "direct_evidence_refs": ["ev-authored-1"],
        "confidence": 0.84,
    }

    class EventRepository:
        def events_after(self, run_id: str, sequence: int) -> list[dict]:
            if run_id != run.run_id or sequence >= 1:
                return []
            return [
                {
                    "run_id": run_id,
                    "sequence": 1,
                    "event_type": "winning_s6_release_gate_evaluated",
                    "payload": {
                        "source": "trace",
                        "event": {
                            "event_id": "trace-s6-release",
                            "event_type": "winning_s6_release_gate_evaluated",
                            "actor": "winning_swarm_controller",
                            "summary": "S6 画像交付门通过",
                            "created_at": "2026-08-07T12:00:00+00:00",
                            "input_refs": [],
                            "output_refs": ["hypothesis-s6-authored-1"],
                            "payload": {
                                "passed": True,
                                "authored_cards": [direction],
                                "card_count": 1,
                            },
                        },
                    },
                }
            ]

    response = TestClient(create_app(service, event_repository=EventRepository())).get(
        f"/api/v1/runs/{run.run_id}/capabilities"
    )
    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["name"] == direction["name"]
    assert rows[0]["analysis_provenance_status"] == "s6_authored"
    assert rows[0]["portrait_authoring_status"] == "authored_semantically_consistent"


def test_capabilities_api_prefers_delivered_s6_portraits_over_stale_portfolio_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "runs"
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand("S6 最终画像优先", "auto", [], 2, "analyst")
    )
    run_dir = output_root / run.run_id
    run_dir.mkdir(parents=True)
    delivered = {
        "capability_id": "s6-final-1",
        "name": "“扰窗”末段诱压突防巡航弹",
        "capability_image": "自然撰写的最终能力画像",
        "deep_capability_portrait": "自然撰写的最终能力画像",
        "operational_process": ["末段释放诱压体", "主杀伤体利用拥塞窗口突防"],
        "evidence_ids": ["ev-final-1"],
        "confidence": 0.81,
    }
    (run_dir / "capability_images.json").write_text(
        json.dumps([delivered], ensure_ascii=False),
        encoding="utf-8",
    )
    service.set_status(run.run_id, "completed")

    class EventRepository:
        def events_after(self, run_id: str, sequence: int) -> list[dict]:
            if run_id != run.run_id or sequence >= 1:
                return []
            return [
                {
                    "run_id": run_id,
                    "sequence": 1,
                    "event_type": "winning_portfolio_merge_completed",
                    "payload": {
                        "source": "trace",
                        "event": {
                            "event_id": "trace-stale-s6-portfolio",
                            "event_type": "winning_portfolio_merge_completed",
                            "actor": "winning_swarm_controller",
                            "summary": "旧组合事件",
                            "created_at": "2026-08-07T12:00:00+00:00",
                            "input_refs": [],
                            "output_refs": ["hypothesis-s6-1"],
                            "payload": {
                                "final_equipment_portfolio": [
                                    {
                                        "hypothesis_id": "hypothesis-s6-1",
                                        "name": "形态：远程突防巡航弹及若干载荷",
                                        "equipment_form": "形态：远程突防巡航弹及若干载荷",
                                        "direct_combat_equipment": True,
                                    }
                                ],
                            },
                        },
                    },
                }
            ]

    response = TestClient(create_app(service, event_repository=EventRepository())).get(
        f"/api/v1/runs/{run.run_id}/capabilities"
    )

    assert response.status_code == 200
    rows = response.json()
    assert [item["name"] for item in rows] == [delivered["name"]]
    assert rows[0]["deep_capability_portrait"] == delivered["deep_capability_portrait"]


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

    rows = (
        TestClient(create_app(service, event_repository=repository))
        .get("/api/v1/runs")
        .json()
    )
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


def test_api_resume_refreshes_real_execution_from_current_server_config(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CURRENT_CODEX_KEY", "configured")
    monkeypatch.setenv("EQUIPMENT_DR_MODE", "real")
    monkeypatch.setenv("EQUIPMENT_DR_PROVIDER", "codex")
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "current-model")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://current.example.test/v1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", "CURRENT_CODEX_KEY")
    monkeypatch.setenv(
        "EQUIPMENT_DR_AGENT_MODELS_JSON",
        '{"reporter":{"model":"report-model"}}',
    )
    service = ResearchApplicationService()
    client = TestClient(create_app(service))
    created = client.post(
        "/api/v1/runs",
        json={
            "topic": "resume with a changed gateway",
            "execution": {
                "mode": "real",
                "provider": "codex",
                "model": "old-model",
                "base_url": "https://old.example.test/v1",
                "api_key_env": "CURRENT_CODEX_KEY",
            },
        },
    ).json()
    service.set_status(created["run_id"], "researching")
    service.set_status(created["run_id"], "failed")

    response = client.post(
        f"/api/v1/runs/{created['run_id']}/resume",
        headers={"Idempotency-Key": "resume-current-config"},
    )

    assert response.status_code == 200
    execution = response.json()["execution"]
    assert execution["model"] == "current-model"
    assert execution["base_url"] == "https://current.example.test/v1"
    assert execution["api_key_env"] == "CURRENT_CODEX_KEY"
    assert execution["agent_models"]["reporter"] == {
        "provider": "codex",
        "model": "report-model",
        "base_url": "https://current.example.test/v1",
        "api_key_env": "CURRENT_CODEX_KEY",
    }


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


def test_completed_approved_run_ignores_late_report_failure_in_replay() -> None:
    class View:
        status = "completed"
        result = {"audit_status": "approved", "report_available": True}
        selected_agent_ids: list[str] = []

    workflow = _interaction_workflow_summary(
        [
            {
                "event_type": "report_model_failed",
                "actor": "reporter",
                "details": {"detail": "stale duplicate worker failure"},
            }
        ],
        View(),
    )

    assert workflow["status"] == "completed"
    assert workflow["failure"] == {"phase": "", "detail": ""}
    assert (
        next(item for item in workflow["phases"] if item["id"] == "report")["status"]
        == "completed"
    )


def test_active_resumed_run_keeps_historical_failure_only_in_audit_timeline() -> None:
    class View:
        status = "researching"
        error = ""
        result = {}
        selected_agent_ids: list[str] = []

    workflow = _interaction_workflow_summary(
        [
            {
                "event_type": "run_failed",
                "actor": "orchestrator",
                "details": {"error": "historical worker interruption"},
            },
            {
                "event_type": "baseline_model_call_progress",
                "actor": "combat_scenario",
                "details": {"elapsed_seconds": 30},
            },
        ],
        View(),
    )

    assert workflow["status"] == "researching"
    assert workflow["failure"] == {"phase": "", "detail": ""}
    assert (
        next(item for item in workflow["phases"] if item["id"] == "baseline")["status"]
        == "running"
    )


def test_runtime_sequence_keeps_recovery_progress_after_historical_failure() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
            "resume event ordering",
            "auto",
            [],
            2,
            "analyst",
        )
    )
    service.set_status(run.run_id, "researching")

    class EventRepository:
        def events_after(self, run_id: str, sequence: int) -> list[dict]:
            if run_id != run.run_id or sequence > 0:
                return []
            return [
                {
                    "run_id": run_id,
                    "sequence": 1,
                    "event_type": "run_failed",
                    "payload": {"error": "historical failure"},
                },
                {
                    "run_id": run_id,
                    "sequence": 2,
                    "event_type": "run_started",
                    "payload": {
                        "source": "trace",
                        "event": {
                            "event_id": "trace-resumed-start",
                            "event_type": "run_started",
                            "actor": "orchestrator",
                            "summary": "resumed with current execution",
                            "created_at": "2020-01-01T00:00:00+00:00",
                            "input_refs": [],
                            "output_refs": [],
                            "payload": {},
                        },
                    },
                },
            ]

    payload = (
        TestClient(create_app(service, event_repository=EventRepository()))
        .get(f"/api/v1/runs/{run.run_id}/interactions?compact=true")
        .json()
    )

    assert [item["event_type"] for item in payload["events"]] == [
        "run_failed",
        "run_started",
    ]
    assert payload["workflow"]["failure"] == {"phase": "", "detail": ""}


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


def test_failed_run_replay_preserves_completed_baseline_before_s_agent_stop() -> None:
    class View:
        status = "failed"
        selected_agent_ids = ["international_situation", "weapon_equipment"]

    rows = [
        {"event_type": "baseline_result", "actor": "international_situation"},
        {"event_type": "baseline_result", "actor": "weapon_equipment"},
        {"event_type": "task_received", "actor": "winning_mechanism"},
    ]

    phases = {
        item["id"]: item
        for item in _interaction_workflow_phases(
            rows,
            view=View(),
            step_plan=[],
            dynamic_agents=[],
        )
    }

    assert phases["blueprint"]["status"] == "completed"
    assert phases["baseline"]["status"] == "completed"
    assert phases["convergence"]["status"] == "completed"
    assert phases["s_agents"]["status"] == "failed"
    assert phases["audit"]["status"] == "pending"


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
    gated_phase = next(item for item in gated["phases"] if item["id"] == "s_agents")
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
    tmp_path: Path,
    monkeypatch,
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
    legacy_run_dir = output_root.parent / run_id
    legacy_run_dir.mkdir(parents=True)
    (legacy_run_dir / "legacy-generated.txt").write_text("legacy", encoding="utf-8")
    sidecar_dir = output_root.parent / "deep-thinking" / run_id
    sidecar_dir.mkdir(parents=True)
    (sidecar_dir / "session.json").write_text("{}", encoding="utf-8")

    response = client.delete(f"/api/v1/runs/{run_id}/permanent")

    assert response.status_code == 200
    assert response.json() == {"run_id": run_id, "deleted": True}
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert client.get(f"/api/v1/runs/{run_id}/capabilities").status_code == 404
    assert client.get(f"/api/v1/runs/{run_id}/interactions").status_code == 404
    assert queue.pending_run_ids() == []
    assert repository.events_after(run_id, 0) == []
    assert repository.deletion_residue(run_id) == {
        "runs": 0,
        "runtime_events": 0,
        "run_queue": 0,
        "worker_heartbeats": 0,
    }
    assert not run_dir.exists()
    assert not legacy_run_dir.exists()
    assert not sidecar_dir.exists()


def test_api_permanent_delete_stops_online_worker_run_and_clears_ownership(
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

    assert response.status_code == 200
    assert response.json() == {"run_id": run_id, "deleted": True}
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert repository.deletion_residue(run_id) == {
        "runs": 0,
        "runtime_events": 0,
        "run_queue": 0,
        "worker_heartbeats": 0,
    }


def test_api_stops_running_task() -> None:
    service = ResearchApplicationService()
    client = TestClient(create_app(service))
    created = client.post("/api/v1/runs", json={"topic": "stop me"}).json()
    run_id = created["run_id"]
    client.post(
        f"/api/v1/runs/{run_id}/start",
        headers={"Idempotency-Key": "start-stop-test"},
    )
    service.set_status(run_id, "synthesizing")

    response = client.post(
        f"/api/v1/runs/{run_id}/stop",
        headers={"Idempotency-Key": "stop-test"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["process_cleanup"]["run_id"] == run_id


def test_catalog_is_loaded_from_registry_and_invalid_selection_is_rejected() -> None:
    client = TestClient(create_app())
    catalog = client.get("/api/v1/catalog").json()
    assert catalog["provider"]["model"] == "gpt-5.5"
    assert catalog["provider"]["default_codex_base_url"] == "https://api.openai.com/v1"
    assert (
        catalog["provider"]["default_codex_api_key_env"] == "EQUIPMENT_DR_CODEX_API_KEY"
    )
    assert [item["id"] for item in catalog["provider"]["provider_options"]] == [
        "codex",
        "responses",
        "deepseek",
        "codex_deepseek",
        "codex_queen",
        "claude",
        "generic_cli",
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
    assert all(
        item["harness_profile_config"]["stop_conditions"] for item in catalog["agents"]
    )
    assert catalog["provider"]["configurable_agent_ids"].count("orchestrator") == 1
    assert len(catalog["provider"]["configurable_agent_ids"]) == len(
        set(catalog["provider"]["configurable_agent_ids"])
    )
    assert [item["id"] for item in catalog["interaction_modes"]] == [
        "expert",
        "autonomous",
    ]
    assert [item["id"] for item in catalog["report_templates"]] == [
        "project_argument_v1",
        "three_layer_nine_item",
    ]
    assert [item["id"] for item in catalog["report_templates"] if item["default"]] == [
        "project_argument_v1"
    ]
    defaults = [item["id"] for item in catalog["execution_profiles"] if item["default"]]
    assert defaults == ["winning_swarm_dynamic_v2"]
    assert [item["id"] for item in catalog["execution_profiles"]] == [
        "legacy_v1",
        "optimized_v2",
        "swarm_quality_v1",
        "winning_swarm_dynamic_v2",
    ]
    assert [
        item["id"] for item in catalog["execution_profiles"] if item["recommended"]
    ] == ["optimized_v2"]
    assert all(item["selectable"] for item in catalog["execution_profiles"])
    assert [item["id"] for item in catalog["discovery_branches"]] == list("ABCDEFGH")
    assert all(
        item["step_modes"]
        == [
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


def test_api_persists_selected_report_template_mode() -> None:
    client = TestClient(create_app())
    three_layer = client.post(
        "/api/v1/runs",
        json={
            "topic": "三层九项研究报告",
            "research_route": "auto",
            "report_template_mode": "three_layer_nine_item",
        },
    )
    project = client.post(
        "/api/v1/runs",
        json={
            "topic": "项目论证五章研究报告",
            "research_route": "auto",
            "report_template_mode": "project_argument_v1",
        },
    )

    assert three_layer.status_code == 201
    assert three_layer.json()["report_template_mode"] == "three_layer_nine_item"
    assert project.status_code == 201
    assert project.json()["report_template_mode"] == "project_argument_v1"


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
            "execution": {
                "mode": "real",
                "base_url": "http://models.example.test/v1/responses",
            },
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


def test_api_accepts_and_persists_codex_api_configuration_without_secret(
    monkeypatch,
) -> None:
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
    created = client.post(
        "/api/v1/runs",
        json={
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
        },
    )
    assert created.status_code == 201
    profiles = created.json()["execution"]["agent_models"]
    assert profiles["orchestrator"]["model"] == "planner-model"
    assert (
        profiles["orchestrator"]["base_url"]
        == "https://models.example.test/v1/responses"
    )
    assert profiles["winning_mechanism"]["model"] == "winning-model"
    assert all("api_key" not in profile for profile in profiles.values())


def test_api_migrates_legacy_deepseek_profile_id_on_create_and_update(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_MODE", "real")
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured")
    client = TestClient(create_app())

    created = client.post(
        "/api/v1/runs",
        json={
            "topic": "legacy DeepSeek profile migration",
            "model_profile_id": "deepseek-openlux",
            "execution": {"mode": "real"},
        },
    )

    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["model_profile_id"] == "codex-deepseek"
    assert created_payload["execution"]["model_profile_id"] == "codex-deepseek"

    updated = client.patch(
        f"/api/v1/runs/{created_payload['run_id']}",
        json={
            "topic": "legacy DeepSeek profile migration updated",
            "research_route": "auto",
            "selected_agent_ids": [],
            "max_rounds": 2,
            "model_profile_id": "deepseek-openlux",
            "execution": {"mode": "real"},
        },
    )

    assert updated.status_code == 200
    assert updated.json()["model_profile_id"] == "codex-deepseek"
    assert updated.json()["execution"]["model_profile_id"] == "codex-deepseek"


def test_api_accepts_and_persists_queen_model_profile(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_MODE", "real")
    monkeypatch.setenv("EQUIPMENT_DR_QUEEN_MODEL", "qwen3.8-flash")
    monkeypatch.setenv(
        "EQUIPMENT_DR_QUEEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("QUEEN_API_KEY", "configured")
    client = TestClient(create_app())

    created = client.post(
        "/api/v1/runs",
        json={
            "topic": "Queen model profile persistence",
            "model_profile_id": "codex-queen",
            "execution": {"mode": "real"},
        },
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["model_profile_id"] == "codex-queen"
    assert payload["execution"]["model_profile_id"] == "codex-queen"


def test_interactions_are_visible_from_persistent_runtime_events_before_completion() -> (
    None
):
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
    assert payload["events"][1]["details"]["arguments"] == {"query": "公开威胁态势"}
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

    compact = client.get(f"/api/v1/runs/{run.run_id}/interactions?compact=true").json()
    assert compact["counts"]["events"] == 2
    assert compact["counts"]["visible_events"] == 1
    assert [item["event_type"] for item in compact["events"]] == [
        "agent_task_delegated"
    ]


def test_interactions_project_codex_workflow_step_modes_and_dynamic_agents() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
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
        )
    )
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
        captured.append(
            (
                event_type,
                {
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
                },
            )
        )

    add(
        "run_started",
        "orchestrator",
        {
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
        },
    )
    add(
        "discovery_meta_loop_evaluated",
        "orchestrator",
        {
            "cycle": 2,
            "primary_branch": "G",
            "secondary_branches": ["E"],
            "replan_required": True,
            "added_secondary_branches": ["E"],
            "step_mode_overrides": [
                {"step": 1, "mode": "deep"},
                {"step": 6, "mode": "deep"},
            ],
            "dynamic_subagents": [
                {
                    "agent_instance_id": "dynamic-opponent-review",
                    "display_name": "对手变化复核 Agent",
                    "merge_target": "S1",
                    "skill_ids": ["threat_forecasting"],
                    "knowledge_pack_ids": ["public_evidence_index"],
                }
            ],
            "stop_reason": "bounded_replan_complete",
        },
    )
    add(
        "winning_subagent_completed",
        "winning_s1_opponent",
        {
            "step": 1,
            "execution_mode": "deep",
            "middle_cycle": 2,
            "status": "completed",
        },
    )
    add(
        "winning_subagent_completed",
        "winning_s2_operations",
        {
            "step": 2,
            "execution_mode": "skip",
            "middle_cycle": 1,
            "status": "skipped_by_branch_blueprint",
        },
    )
    add(
        "winning_subagent_completed",
        "dynamic-opponent-review",
        {
            "step": 0,
            "execution_mode": "dynamic",
            "display_name": "对手变化复核 Agent",
            "merge_target": "S1",
            "skill_ids": ["threat_forecasting"],
            "knowledge_pack_ids": ["public_evidence_index"],
            "status": "completed",
        },
    )
    add(
        "winning_inner_loop_evaluated",
        "winning_step_critic",
        {
            "step": 1,
            "passed": False,
            "recommended_action": "retry",
        },
    )
    add(
        "winning_inner_loop_evaluated",
        "winning_step_critic",
        {
            "step": 1,
            "passed": True,
            "recommended_action": "retry",
        },
    )
    add(
        "winning_middle_loop_evaluated",
        "winning_round_critic",
        {
            "passed": False,
            "rerun_from_step": 3,
        },
    )
    add(
        "recall_requested",
        "winning_mechanism",
        {
            "source_layer": "L2",
            "return_node": "L2",
        },
    )
    add("winning_outer_loop_evaluated", "winning_round_critic", {})

    payload = (
        TestClient(create_app(service, event_repository=EventRepository()))
        .get(f"/api/v1/runs/{run.run_id}/interactions?compact=true")
        .json()
    )

    assert payload["workflow"]["execution"] == {
        "profile_id": "legacy_v1",
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
        1,
        0,
        1,
        1,
        0,
        0,
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
        item
        for item in payload["agents"]
        if item["agent_id"] == "dynamic-opponent-review"
    )
    assert dynamic["runtime_dynamic"] is True
    assert dynamic["skill_ids"] == ["threat_forecasting"]


def test_interactions_preserve_codex_swarm_recruitment_lifecycle_fields() -> None:
    def row(
        sequence: int,
        event_type: str,
        actor: str,
        details: dict,
    ) -> dict:
        return {
            "sequence": sequence,
            "event_id": f"event-{sequence}",
            "event_type": event_type,
            "actor": actor,
            "details": details,
        }

    common = {
        "display_name": "证据核验",
        "archetype": "evidence_verifier",
        "role_purpose": "核验公开基线、事实引用、反证和不确定性。",
        "trigger_residuals": ["evidence_insufficient"],
        "wave": 2,
        "hypothesis_id": "hypothesis-1",
        "merge_target": "S5",
        "provider_type": "codex_cli",
        "execution_backend": "independent_codex_cli",
        "context_isolation": "ephemeral",
        "process_isolation": "new_process_per_turn",
        "runtime_profile_id": "winning_swarm_evidence_verifier",
        "skill_ids": [
            "js-equipment-agent-runtime",
            "js-winning-shared-layer",
        ],
        "allow_child_spawn": False,
        "expected_quality_gain": 0.05,
    }
    rows = [
        row(1, "swarm_planned", "winning_swarm_controller", {"task_count": 2}),
        row(
            2,
            "specialist_recruitment_planned",
            "specialist-1",
            {
                **common,
                "task_id": "task-1",
                "agent_instance_id": "specialist-1",
                "session_ref": "cli-session-one",
                "status": "planned",
            },
        ),
        row(
            3,
            "specialist_session_started",
            "specialist-1",
            {
                "agent_instance_id": "specialist-1",
                "status": "running",
            },
        ),
        row(
            4,
            "specialist_completed",
            "specialist-1",
            {
                "agent_instance_id": "specialist-1",
                "status": "completed",
            },
        ),
        row(
            5,
            "specialist_recruitment_planned",
            "specialist-2",
            {
                **common,
                "task_id": "task-2",
                "agent_instance_id": "specialist-2",
                "session_ref": "cli-session-two",
                "status": "planned",
            },
        ),
        row(
            6,
            "specialist_pruned",
            "specialist-2",
            {
                "agent_instance_id": "specialist-2",
                "reason": "incremental_quality_below_threshold",
                "status": "pruned",
            },
        ),
    ]
    view = SimpleNamespace(
        status="researching",
        research_route="new_winning_mechanism",
        discovery_branch="D",
        execution_profile_id="winning_swarm_dynamic_v2",
        selected_agent_ids=[],
        execution={"mode": "real", "provider": "codex", "model": "gpt-test"},
    )

    workflow = _interaction_workflow_summary(rows, view)
    cluster = workflow["swarm_cluster"]

    assert cluster["enabled"] is True
    assert cluster["provider_type"] == "codex_cli"
    assert cluster["execution_backend"] == "independent_codex_cli"
    assert cluster["counts"] == {
        "total": 2,
        "planned": 2,
        "recruiting": 0,
        "running": 0,
        "completed": 1,
        "merged": 0,
        "pruned": 1,
        "failed": 0,
    }
    completed = next(
        item for item in cluster["members"] if item["agent_id"] == "specialist-1"
    )
    pruned = next(
        item for item in cluster["members"] if item["agent_id"] == "specialist-2"
    )
    assert completed["role_purpose"].startswith("核验公开基线")
    assert completed["provider_type"] == "codex_cli"
    assert completed["context_isolation"] == "ephemeral"
    assert completed["session_ref"] == "cli-session-one"
    assert completed["skill_ids"] == common["skill_ids"]
    assert completed["status"] == "completed"
    assert pruned["role_purpose"] == common["role_purpose"]
    assert pruned["status"] == "pruned"
    assert pruned["prune_reason"] == "incremental_quality_below_threshold"
    assert cluster["waves"] == [
        {
            "wave": 2,
            "label": "开放创作",
            "member_ids": ["specialist-1", "specialist-2"],
        }
    ]


def test_dynamic_v2_workbench_projects_graph_lineage_merge_and_portfolio() -> None:
    def row(sequence: int, event_type: str, actor: str, details: dict) -> dict:
        return {
            "sequence": sequence,
            "event_id": f"event-{sequence}",
            "event_type": event_type,
            "actor": actor,
            "details": details,
        }

    contract = {
        "role_contract_id": "role-s3",
        "archetype": "disruptive_mechanism_generator",
        "display_name": "颠覆机理生成",
        "purpose": "形成机制真正不同的候选。",
        "mission_node": "S3",
        "merge_targets": ["S3"],
        "trigger_residuals": ["causal_chain_broken"],
        "skill_ids": ["js-winning-shared-layer"],
        "allow_child_spawn": False,
        "schema_version": "2.0",
    }
    instance = {
        "instance_id": "agent-s3-1",
        "role_contract_id": "role-s3",
        "archetype": "disruptive_mechanism_generator",
        "display_name": "颠覆机理生成",
        "mission_node": "S3",
        "merge_target": "S3",
        "wave": 2,
        "depends_on": ["agent-s1-1", "agent-s2-1"],
    }
    inactive_capacity_instance = {
        **instance,
        "instance_id": "agent-s3-unused-capacity",
        "display_name": "未激活 S3 容量",
    }
    recruited_contract = {
        **contract,
        "role_contract_id": "role-evidence",
        "archetype": "evidence_verifier",
        "display_name": "证据核验",
        "purpose": "核验候选证据边界。",
        "mission_node": "S5",
        "merge_targets": ["S5"],
        "trigger_residuals": ["evidence_insufficient"],
    }
    recruited_instance = {
        **instance,
        "instance_id": "agent-evidence-1",
        "role_contract_id": "role-evidence",
        "archetype": "evidence_verifier",
        "display_name": "证据核验",
        "mission_node": "S5",
        "merge_target": "S5",
        "hypothesis_id": "hypothesis-1",
        "wave": 3,
        "depends_on": ["agent-s3-1"],
    }
    hypothesis = {
        "hypothesis_id": "hypothesis-1",
        "title": "分布式自主无人拦截装备",
        "equipment_forms": ["模块化自主无人拦截平台"],
        "changed_confrontation_variable": "低空来袭集群持续改变航迹并压缩拦截窗口",
        "mechanism_chain": ["前出待机", "协同探测", "末段自主拦截"],
        "direct_military_effects": ["阻断低空来袭集群持续突防"],
        "project_function": "在通信受扰条件下完成前沿拦截续接",
        "reference_overview": "低空集群突防进入前沿节点时，该装备以分布式感知和多目标拦截压缩来袭窗口，先在杂波背景中完成分类，再按威胁优先级分配拦截器并进行战果复核。",
        "novelty_delta": "将分布式协同探测与自主拦截闭环前移到前沿地域",
        "decisive_advantage_thesis": "把目标发现到拦截决策的时延压缩至敌方机动调整之前",
        "evidence_ids": ["ev-1"],
        "failure_boundaries": ["强干扰下局部感知完全失效"],
        "validation_plan": ["节点损耗条件下的对照试验"],
        "score": 0.82,
    }
    receipt = {
        "receipt_id": "receipt-1",
        "contribution_id": "contribution-1",
        "hypothesis_id": "hypothesis-1",
        "merge_target": "S5",
        "base_ledger_version": 1,
        "resulting_ledger_version": 2,
        "status": "merged",
        "changed_fields": ["evidence_boundary"],
        "conflicts": [],
        "quality_delta": 0.06,
        "rebase_required": False,
    }
    equipment = {
        "hypothesis_id": "hypothesis-1",
        "name": "分布式自主无人拦截装备",
        "type": "new",
        "equipment_forms": ["模块化自主无人拦截平台"],
        "mission_effects": ["提高区域拒止持续性"],
        "failure_boundaries": ["强干扰下局部感知完全失效"],
        "validation_plan": ["节点损耗条件下的对照试验"],
    }
    rows = [
        row(
            1,
            "winning_mission_graph_planned",
            "winning_swarm_controller",
            {
                "graph_id": "graph-1",
                "minimum_instances": 8,
                "maximum_instances": 16,
                "maximum_concurrency": 6,
                "graph": {
                    "graph_id": "graph-1",
                    "execution_profile_id": "winning_swarm_dynamic_v2",
                    "role_contracts": [contract],
                    "agent_instances": [instance, inactive_capacity_instance],
                    "waves": [["agent-s3-1", "agent-s3-unused-capacity"]],
                },
            },
        ),
        row(
            2,
            "winning_agent_instance_recruited",
            "agent-evidence-1",
            {
                "role_contract": recruited_contract,
                "instance": recruited_instance,
                "hypothesis_id": "hypothesis-1",
                "trigger_residual": "evidence_insufficient",
            },
        ),
        row(
            3,
            "winning_candidate_branch_created",
            "agent-s3-1",
            {
                "hypothesis_id": "hypothesis-1",
                "mission_node": "S3",
                "score": 0.82,
            },
        ),
        row(
            4,
            "winning_candidate_ledger_frozen",
            "winning_swarm_controller",
            {
                "ledger_id": "ledger-1",
                "ledger_version": 1,
                "candidate_count": 1,
                "incremental": True,
            },
        ),
        row(
            5,
            "winning_contribution_rebase_required",
            "agent-evidence-1",
            {
                "contribution_id": "contribution-1",
                "hypothesis_id": "hypothesis-1",
                "merge_target": "S5",
                "from_version": 1,
                "to_version": 2,
            },
        ),
        row(
            6,
            "winning_contribution_merged",
            "agent-evidence-1",
            {
                "contribution_id": "contribution-1",
                "hypothesis_id": "hypothesis-1",
                "merge_target": "S5",
                "status": "merged",
                "resulting_ledger_version": 2,
            },
        ),
        row(
            9,
            "winning_agent_session_completed",
            "agent-s3-1",
            {"agent_instance_id": "agent-s3-1", "mission_node": "S3"},
        ),
        row(
            7,
            "winning_portfolio_merge_completed",
            "winning_swarm_controller",
            {
                "ledger_id": "ledger-1",
                "ledger_version": 2,
                "selected_hypothesis_ids": ["hypothesis-1"],
                "rejected_hypothesis_ids": [],
                "final_equipment_portfolio": [equipment],
                "swarm_summary": {
                    "budget": {
                        "maximum_concurrency": 6,
                        "maximum_observed_concurrency": 5,
                    },
                    "hypothesis_ledger": {
                        "ledger_id": "ledger-1",
                        "version": 2,
                        "status": "active",
                        "hypotheses": [hypothesis],
                    },
                    "merge_receipts": [receipt],
                },
                "raw_prompt": "must-not-project",
                "stdout": "must-not-project",
            },
        ),
        row(
            8,
            "winning_s3_active_agents_materialized",
            "winning_swarm_controller",
            {
                "active_instance_ids": ["agent-s3-1"],
                "active_instance_count": 1,
                "unused_capacity_count": 1,
            },
        ),
        row(
            10,
            "winning_s6_release_gate_evaluated",
            "winning_swarm_controller",
            {
                "passed": True,
                "failed": False,
                "limited": False,
                "issues": [],
                "warnings": [],
                "card_count": 1,
                "maximum_concurrency": 6,
                "maximum_observed_concurrency": 5,
                "authored_cards": [
                    {
                        **equipment,
                        "capability_portrait": "原创 S6 五模块能力画像",
                        "s6_authoring_status": "authored_semantically_consistent",
                    }
                ],
            },
        ),
    ]
    view = SimpleNamespace(
        status="researching",
        research_route="new_winning_mechanism",
        discovery_branch="D",
        selected_agent_ids=[],
        execution={"mode": "real", "provider": "codex", "model": "gpt-test"},
    )

    cluster = _interaction_workflow_summary(rows, view)["swarm_cluster"]

    assert cluster["policy_id"] == "winning_swarm_dynamic_v2"
    assert cluster["mission_graph"]["maximum_concurrency"] == 6
    assert cluster["mission_graph"]["maximum_observed_concurrency"] == 5
    assert cluster["mission_graph"]["active_s3_instances"] == 1
    assert cluster["mission_graph"]["unused_s3_capacity"] == 1
    assert (
        next(item for item in cluster["role_pools"] if item["mission_node"] == "S3")[
            "count"
        ]
        == 1
    )
    assert cluster["dynamic_specialists"][0]["agent_id"] == "agent-evidence-1"
    assert cluster["candidate_lineage"][0]["status"] == "selected"
    assert cluster["candidate_lineage"][0]["mechanism_chain"] == [
        "前出待机",
        "协同探测",
        "末段自主拦截",
    ]
    assert cluster["candidate_lineage"][0]["direct_military_effects"] == [
        "阻断低空来袭集群持续突防"
    ]
    assert "分布式感知" in cluster["candidate_lineage"][0]["reference_overview"]
    assert cluster["hypothesis_ledger"]["version"] == 2
    assert any(item["status"] == "merged" for item in cluster["merge_receipts"])
    selected_members = [
        item
        for item in cluster["members"]
        if item.get("hypothesis_id") == "hypothesis-1"
    ]
    assert selected_members
    assert all(item["status"] == "merged" for item in selected_members)
    assert all(item["portfolio_status"] == "selected" for item in selected_members)
    assert all(item["merge_status"] == "accepted" for item in selected_members)
    assert cluster["final_equipment_portfolio"] == [equipment]
    assert cluster["s6_release_gate"]["passed"] is True
    assert cluster["s6_authored_cards"][0]["capability_portrait"] == (
        "原创 S6 五模块能力画像"
    )
    assert "must-not-project" not in json.dumps(cluster, ensure_ascii=False)
    workflow = _interaction_workflow_summary(rows, view)
    step_three = next(item for item in workflow["step_plan"] if item["step"] == 3)
    assert step_three["status"] == "completed"
    assert step_three["dynamic_instance_count"] == 1
    assert step_three["dynamic_completed_count"] == 1
    inactive_projection = next(
        item
        for item in workflow["dynamic_agents"]
        if item["agent_id"] == "agent-s3-unused-capacity"
    )
    assert inactive_projection["status"] == "skipped"
    assert inactive_projection["inactive_capacity"] is True


def test_dynamic_v2_projects_live_mission_members_onto_s1_s6_progress() -> None:
    def row(sequence: int, event_type: str, actor: str, details: dict) -> dict:
        return {
            "sequence": sequence,
            "event_id": f"event-{sequence}",
            "event_type": event_type,
            "actor": actor,
            "details": details,
        }

    instances = [
        {
            "instance_id": "agent-s1-a",
            "display_name": "S1 对手体系 A",
            "mission_node": "S1",
            "merge_target": "S1",
            "wave": 1,
        },
        {
            "instance_id": "agent-s1-b",
            "display_name": "S1 对手体系 B",
            "mission_node": "S1",
            "merge_target": "S1",
            "wave": 1,
        },
        {
            "instance_id": "agent-s2-a",
            "display_name": "S2 战法生成 A",
            "mission_node": "S2",
            "merge_target": "S2",
            "wave": 1,
        },
    ]
    rows = [
        row(
            1,
            "winning_mission_graph_planned",
            "winning_swarm_controller",
            {
                "graph_id": "graph-live-progress",
                "graph": {
                    "graph_id": "graph-live-progress",
                    "execution_profile_id": "winning_swarm_dynamic_v2",
                    "agent_instances": instances,
                },
            },
        ),
        row(
            2,
            "winning_agent_session_completed",
            "agent-s1-a",
            {"agent_instance_id": "agent-s1-a", "mission_node": "S1"},
        ),
        row(
            3,
            "winning_agent_session_started",
            "agent-s1-b",
            {"agent_instance_id": "agent-s1-b", "mission_node": "S1"},
        ),
        row(
            4,
            "winning_agent_session_completed",
            "agent-s2-a",
            {"agent_instance_id": "agent-s2-a", "mission_node": "S2"},
        ),
    ]
    view = SimpleNamespace(
        status="researching",
        research_route="new_winning_mechanism",
        discovery_branch="D",
        execution_profile_id="winning_swarm_dynamic_v2",
        selected_agent_ids=[],
        execution={"mode": "real", "provider": "codex", "model": "gpt-test"},
    )

    workflow = _interaction_workflow_summary(rows, view)
    steps = {item["step"]: item for item in workflow["step_plan"]}
    phases = {item["id"]: item for item in workflow["phases"]}

    assert steps[1]["execution_mode"] == "dynamic"
    assert steps[1]["status"] == "running"
    assert steps[1]["dynamic_completed_count"] == 1
    assert steps[1]["dynamic_instance_count"] == 2
    assert steps[2]["status"] == "completed"
    assert steps[2]["dynamic_completed_count"] == 1
    assert steps[2]["dynamic_instance_count"] == 1
    assert phases["s_agents"]["status"] == "running"

    rows.append(
        row(
            5,
            "winning_agent_session_completed",
            "agent-s1-b",
            {"agent_instance_id": "agent-s1-b", "mission_node": "S1"},
        )
    )
    completed_workflow = _interaction_workflow_summary(rows, view)
    completed_steps = {item["step"]: item for item in completed_workflow["step_plan"]}
    assert completed_steps[1]["status"] == "completed"
    assert completed_steps[1]["dynamic_completed_count"] == 2


def test_dynamic_v2_canonical_steps_do_not_regress_after_downstream_started() -> None:
    def row(sequence: int, event_type: str, actor: str, details: dict) -> dict:
        return {
            "sequence": sequence,
            "event_id": f"event-{sequence}",
            "event_type": event_type,
            "actor": actor,
            "details": details,
        }

    instances = [
        {
            "instance_id": "agent-s3-late",
            "mission_node": "S3",
            "merge_target": "S3",
            "wave": 5,
        },
        {
            "instance_id": "agent-s5-main",
            "mission_node": "S5",
            "merge_target": "S5",
            "wave": 4,
        },
    ]
    rows = [
        row(
            1,
            "winning_mission_graph_planned",
            "winning_swarm_controller",
            {
                "graph": {
                    "execution_profile_id": "winning_swarm_dynamic_v2",
                    "agent_instances": instances,
                }
            },
        ),
        row(
            2,
            "winning_agent_session_started",
            "agent-s5-main",
            {"agent_instance_id": "agent-s5-main", "mission_node": "S5"},
        ),
        row(
            3,
            "winning_agent_session_started",
            "agent-s3-late",
            {"agent_instance_id": "agent-s3-late", "mission_node": "S3"},
        ),
    ]
    view = SimpleNamespace(
        status="synthesizing",
        research_route="new_winning_mechanism",
        discovery_branch="D",
        execution_profile_id="winning_swarm_dynamic_v2",
        selected_agent_ids=[],
        execution={"mode": "real", "provider": "codex", "model": "gpt-test"},
    )

    steps = {
        item["step"]: item
        for item in _interaction_workflow_summary(rows, view)["step_plan"]
    }

    assert steps[3]["status"] == "completed"
    assert steps[4]["status"] == "completed"
    assert steps[5]["status"] == "running"


def test_dynamic_profile_does_not_prejudge_blueprint_skips_before_scheduling() -> None:
    rows = [
        {
            "sequence": 1,
            "event_id": "event-1",
            "event_type": "run_started",
            "actor": "orchestrator",
            "details": {
                "mode": "real",
                "provider": "codex",
                "model": "gpt-test",
                "discovery_blueprint": {
                    "primary_branch": "G",
                    "branch_name": "跨域融合发现",
                },
            },
        }
    ]
    view = SimpleNamespace(
        status="researching",
        research_route="new_winning_mechanism",
        discovery_branch="G",
        execution_profile_id="winning_swarm_dynamic_v2",
        selected_agent_ids=[],
        execution={"mode": "real", "provider": "codex", "model": "gpt-test"},
    )

    workflow = _interaction_workflow_summary(rows, view)

    assert workflow["execution"]["profile_id"] == "winning_swarm_dynamic_v2"
    assert {item["status"] for item in workflow["step_plan"]} == {"pending"}
    assert {item["execution_mode"] for item in workflow["step_plan"]} == {"dynamic"}
    assert all(item["decision_finalized"] is False for item in workflow["step_plan"])
    assert any(
        item["planned_execution_mode"] == "skip" for item in workflow["step_plan"]
    )


def test_swarm_instance_counts_exclude_read_only_quality_judge() -> None:
    rows = [
        {
            "sequence": 1,
            "event_id": "event-1",
            "event_type": "winning_agent_session_completed",
            "actor": "agent-s4-1",
            "details": {
                "agent_instance_id": "agent-s4-1",
                "archetype": "capability_mapper",
                "mission_node": "S4",
                "wave": 2,
            },
        },
        {
            "sequence": 2,
            "event_id": "event-2",
            "event_type": "winning_quality_judge_completed",
            "actor": "winning-quality-judge-1",
            "details": {"candidate_count": 5, "assessed_count": 5},
        },
    ]
    view = SimpleNamespace(
        status="researching",
        research_route="new_winning_mechanism",
        discovery_branch="D",
        selected_agent_ids=[],
        execution={"mode": "real", "provider": "codex", "model": "gpt-test"},
    )

    cluster = _interaction_workflow_summary(rows, view)["swarm_cluster"]

    assert len(cluster["members"]) == 2
    assert len(cluster["supervisors"]) == 1
    assert cluster["supervisors"][0]["archetype"] == "quality_expert_judge"
    assert cluster["counts"]["total"] == 1
    assert cluster["counts"]["completed"] == 1


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

    payload = (
        TestClient(create_app(service))
        .get(f"/api/v1/runs/{run.run_id}/interactions?compact=true")
        .json()
    )

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

    payload = (
        TestClient(create_app(service))
        .get(f"/api/v1/runs/{run.run_id}/interactions?compact=true")
        .json()
    )
    phases = {item["id"]: item for item in payload["workflow"]["phases"]}

    assert phases["blueprint"]["status"] == "running"
    assert phases["baseline"]["status"] == "pending"


def test_interaction_workflow_phases_use_full_rows_in_compact_mode() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
            "Compact workflow projection",
            "new_winning_mechanism",
            [],
            2,
            "analyst",
            discovery_branch="A",
        )
    )
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
        captured.append(
            (
                event_type,
                {
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
                },
            )
        )

    add(
        "run_started",
        "orchestrator",
        {
            "discovery_blueprint": {"primary_branch": "A"},
        },
    )
    for _ in range(18):
        add("winning_inner_loop_evaluated", "winning_step_critic")
    add("audit_completed", "auditor", {"status": "approved"})
    for _ in range(90):
        add("winning_middle_loop_evaluated", "winning_round_critic")

    payload = (
        TestClient(create_app(service, event_repository=EventRepository()))
        .get(f"/api/v1/runs/{run.run_id}/interactions?compact=true")
        .json()
    )

    assert payload["counts"]["events"] > payload["counts"]["visible_events"]
    assert "audit_completed" not in {item["event_type"] for item in payload["events"]}
    phases = {item["id"]: item for item in payload["workflow"]["phases"]}
    assert phases["audit"]["status"] == "completed"
    assert len(payload["workflow"]["step_plan"]) == 6


def test_compact_interactions_support_winning_agent_waiting_events() -> None:
    service = ResearchApplicationService()
    run = service.create_run(
        CreateRunCommand(
            "Dynamic swarm waiting heartbeat",
            "new_winning_mechanism",
            [],
            2,
            "analyst",
            discovery_branch="D",
        )
    )

    class EventRepository:
        def events_after(self, run_id: str, sequence: int) -> list[dict]:
            if sequence > 0:
                return []
            return [
                {
                    "run_id": run_id,
                    "sequence": 1,
                    "event_type": "winning_agent_waiting",
                    "payload": {
                        "source": "trace",
                        "event": {
                            "event_id": "trace-waiting-1",
                            "event_type": "winning_agent_waiting",
                            "actor": "winning_swarm_controller",
                            "summary": "S6 capability agents are still running",
                            "created_at": "2026-08-08T00:00:00+00:00",
                            "input_refs": [],
                            "output_refs": [],
                            "payload": {
                                "running_instances": [
                                    {
                                        "agent_instance_id": "agent-s6-1",
                                        "mission_node": "S6",
                                        "archetype": "capability_portrait_writer",
                                        "batch": 1,
                                        "elapsed_seconds": 225.1,
                                    }
                                ],
                            },
                        },
                    },
                }
            ]

    response = TestClient(create_app(service, event_repository=EventRepository())).get(
        f"/api/v1/runs/{run.run_id}/interactions?compact=true"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"][0]["event_type"] == "winning_agent_waiting"
    members = payload["workflow"]["swarm_cluster"]["members"]
    waiting = next(
        item for item in members if item["agent_instance_id"] == "agent-s6-1"
    )
    assert waiting["status"] == "running"
    assert waiting["mission_node"] == "S6"


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
    assert (
        client.get(f"/api/v1/runs/{created['run_id']}/history").json()[-1]["event_type"]
        == "run_archived"
    )


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
        "operational_employment",
        "weapon_equipment",
    ]
    assert len(payload["plan"]) == 4
    assert all(item["reason"] for item in payload["plan"])
    assert (
        next(
            item["mode"]
            for item in payload["plan"]
            if item["agent_id"] == "weapon_equipment"
        )
        == "reference"
    )


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


def test_capability_api_preserves_legacy_portrait_without_local_rewriting() -> None:
    legacy_portrait = (
        "形成低带宽可降级任务网络。"
        "军事价值：维持受扰条件下的任务连续性。"
        "深度机制：通过边缘缓存和多路径重构降低主链路依赖。"
        "前瞻判断：面向智能化干扰持续演化。"
        "新颖性：从单链路增强转向任务网络重构。"
        "证据约束：仅支持方向性判断。"
    )
    payload = _capability_api_view(
        {
            "capability_type": "upgrade",
            "equipment_category": "现役任务系统",
            "capability_image": legacy_portrait,
            "evidence_ids": ["ev-1"],
            "key_functions": ["旧功能字段"],
            "performance_indicators": ["旧指标字段"],
            "verification_methods": ["旧验证字段"],
        }
    )

    assert payload["deep_capability_portrait"] == legacy_portrait
    assert "主装备为" not in payload["deep_capability_portrait"]
    assert "Agent" not in payload["deep_capability_portrait"]
    assert "边缘缓存和多路径重构" in payload["operational_mechanism"]
    assert payload["equipment_form"] == "现役任务系统"
    assert "key_functions" not in payload
    assert "performance_indicators" not in payload
    assert "verification_methods" not in payload


def test_capability_api_preserves_codex_five_part_portrait_verbatim() -> None:
    portrait = (
        "概述：面向远海受拒止区域的短时辐射目标猎歼，事件触发反辐射巡飞弹以静默驻留压缩敌节点暴露收益。\n"
        "- 装备与技术实现：采用被动射频感知、低特征巡飞弹体和预授权交战边界。\n"
        "- 关键作战流程：火力单元装订目标与禁击边界，弹体静默进入伏击区，捕获短时开机事件后复核并交战。\n"
        "- 形成能力与作战效果：形成断链驻留猎歼能力，压制防空与电子战节点并为后续火力开辟窗口。\n"
        "- 制胜逻辑机理与对抗边界：把敌方短时开机优势转化为可伏击事件；无源接战或复杂友邻辐射条件下降级。"
    )

    payload = _capability_api_view(
        {
            "name": "静默伏击事件触发反辐射巡飞弹",
            "equipment_form": "车载发射反辐射巡飞弹",
            "capability_image": portrait,
        }
    )

    assert payload["deep_capability_portrait"] == portrait
    assert "主装备为" not in payload["deep_capability_portrait"]
    assert "S6 从非支配候选" not in payload["deep_capability_portrait"]


def test_capability_api_strips_structured_module_dict_dumps_from_portrait() -> None:
    nested = {
        "key_technologies": ["边缘在线强化学习与神经形态芯片"],
        "system_architecture": "三层架构：指控层规划，边缘层在线学习，通信层动态组网。",
        "implementation_path": "分三阶段完成实验室、对抗与集成验证。",
        "key_bottlenecks": {"latency_requirement": "在线学习需毫秒级反馈。"},
        "keyword_context": "在线学习指机载实时辨识并调整攻击参数。",
    }
    dump = str(nested)
    portrait = (
        "概述：敌方依托固定防御节奏消耗首波突防，本装备以代际经验继承改写蜂群交战窗口。\n"
        f"- 装备与技术实现：{dump}\n"
        "- 关键作战流程：装订任务后投放，机群在线学习并动态组网。\n"
        "- 形成能力与作战效果：形成多波次经验继承下的持续突防能力。\n"
        "- 制胜逻辑机理：传统蜂群依赖地面重规划，新构型把经验继承内化到机间交换。"
    )

    payload = _capability_api_view(
        {
            "name": "代际经验继承蜂群突防弹",
            "capability_image": portrait,
            "capability_portrait_modules": {
                "overview": "敌方依托固定防御节奏消耗首波突防。",
                "technology_implementation": nested,
                "operational_process": "装订任务后投放，机群在线学习并动态组网。",
                "capability_effects": "形成多波次经验继承下的持续突防能力。",
                "winning_logic": "传统蜂群依赖地面重规划，新构型把经验继承内化到机间交换。",
            },
        }
    )

    rendered = payload["deep_capability_portrait"]
    assert "key_technologies" not in rendered
    assert "system_architecture" not in rendered
    assert "keyword_context" not in rendered
    assert "边缘在线强化学习与神经形态芯片" in rendered
    assert "key_technologies" not in payload["capability_portrait_modules"][
        "technology_implementation"
    ]


def test_capability_api_promotes_legacy_portrait_classification_for_display() -> None:
    payload = _capability_api_view(
        {
            "name": "有限区巡猎弹",
            "capability_image": (
                "能力分类：主：毁伤维度；辅：突防维度、压制维度。\n"
                "概述：在断链条件下持续复获并毁伤授权目标。\n"
                "- 装备与技术实现：把搜索边界和识别门槛落实到弹上任务系统。\n"
                "- 关键作战流程：装订可信区域，复核目标后受控交战。\n"
                "- 形成能力与作战效果：形成断链复获与受控毁伤能力。\n"
                "- 制胜逻辑机理：压缩目标利用航迹过期脱离的时间收益。"
            ),
        }
    )

    assert payload["capability_classification"] == {
        "primary_dimension": "毁伤维度",
        "secondary_dimensions": ["突防维度", "压制维度"],
        "classification_basis": "由S6按该装备在当前任务场景中的主要战果与关键作战节点归类。",
    }


def test_capability_api_marks_complete_legacy_record_as_structured_migrated() -> None:
    payload = _capability_api_view(
        {
            "name": "历史反辐射弹",
            "portrait_authoring_status": "legacy_v1",
            "capability_image": (
                "概述：在断链条件下追踪并毁伤真实辐射源。\n"
                "- 装备与技术实现：弹载任务计算机融合被动射频导引头与位置历史。\n"
                "- 关键作战流程：装订目标区后发射，复核辐射行为并受控攻击。\n"
                "- 形成能力与作战效果：形成关机诱骗条件下的真实雷达猎歼能力。\n"
                "- 制胜逻辑机理：迫使雷达在开机暴露和关机失能之间选择。"
            ),
            "military_utility": "压制真实防空雷达。",
            "evidence_basis": ["公开反辐射导弹项目证据。"],
            "reasoning_refs": ["reason-1"],
        }
    )

    assert payload["analysis_provenance_status"] == "structured_migrated"


def test_capability_api_preserves_agent_authored_weapon_name() -> None:
    payload = _capability_api_view(
        {
            "name": "低空可消耗察打一体无人突击平台续接目标证据链",
            "capability_type": "new_capability",
            "equipment_category": "低空无人作战平台",
            "equipment_form": "车载箱式、舰载箱式或空投式发射的固定翼小型无人平台",
            "mission_effect": "对时敏目标实施侦察确认和精确打击",
        }
    )

    assert payload["name"] == "低空可消耗察打一体无人突击平台续接目标证据链"
    assert "source_name" not in payload


def test_capability_api_preserves_codex_title_without_dictionary_promotion() -> None:
    payload = _capability_api_view(
        {
            "name": "地射无人机",
            "capability_type": "new_capability",
            "equipment_form": "车载发射舱近程拦截无人机·接口形态：车载任务规划接口",
            "mission_effect": "对低空突防目标实施近程拦截与毁伤",
        }
    )

    assert payload["name"] == "地射无人机"
    assert "source_name" not in payload


def test_capability_api_does_not_replace_agent_anti_radiation_identity() -> None:
    payload = _capability_api_view(
        {
            "name": "长航时反辐射巡飞弹药再捕获",
            "capability_type": "upgrade",
            "equipment_form": "长航时反辐射巡飞弹药",
            "target_scenario": "强电磁压制下精确打击任务续接装备研究中的受扰交战阶段",
            "problem_statement": "现役反辐射弹药难以跨越关机窗口、排除诱饵辐射源并续接压制真实节点",
            "scientific_principle": "用关机前目标记忆与末端独立复核跨越失辐射窗口",
            "enabling_technologies": [
                "宽带被动射频侦测",
                "目标记忆区",
                "末端光电/红外多模复核",
            ],
            "operational_concept": "实施分散部署、任务装订、受控交战和效应评估",
            "operational_process": [
                "发射前装订授权辐射源类别和目标记忆区",
                "进入威胁区后被动搜索并保持关机前方位",
                "末段复核满足门槛时交战，否则拒打",
                "形成压制与毁伤摘要并组织补射",
            ],
            "capability_outcome": "对间歇辐射和关机转移的防空雷达持续猎歼压制",
            "strike_countermeasure_value": "直接摧毁敌预警雷达、火控雷达和电子战车辆，制造防空盲区",
            "winning_mechanism": "迫使对手在开机暴露与关机失去探测火控之间选择",
            "baseline_system": "AARGM-ER类反辐射导弹",
            "risk_boundaries": ["目标位移超过搜索区或无法区分诱饵时失效"],
            "development_path": "开展样机、联试和对抗验证",
            "deep_capability_portrait": (
                "概述：旧画像。\n"
                "- 装备与技术实现：旧技术说明。\n"
                "- 关键作战流程：旧流程说明。\n"
                "- 形成能力与作战效果：旧效果说明。\n"
                "- 制胜逻辑机理与对抗边界：旧边界说明。\n"
                "- 发展与验证路径：旧验证说明。"
            ),
        }
    )

    portrait = payload["deep_capability_portrait"]
    assert payload["name"] == "长航时反辐射巡飞弹药再捕获"
    assert portrait.startswith("概述：旧画像。")
    assert "主装备为" not in portrait


def test_capability_api_does_not_use_research_query_as_portrait_scene() -> None:
    raw_query = (
        "深度研究、理解并长期记忆复杂电磁环境和强对抗条件的突防抗扰设计不足和发展需求"
    )
    payload = _capability_api_view(
        {
            "name": "可消耗空射/地面助推无人僚机弹药",
            "capability_type": "new_capability",
            "equipment_form": "可消耗空射/地面助推无人僚机弹药",
            "target_scenario": raw_query,
            "problem_statement": "敌方机动防空节点利用电磁压制和诱饵压缩突防交战窗口",
            "deep_capability_portrait": (
                f"概述：面向{raw_query}，针对敌方机动防空节点，"
                "以可消耗空射/地面助推无人僚机弹药为主装备。"
            ),
        }
    )

    assert payload["name"] == "可消耗空射/地面助推无人僚机弹药"
    assert raw_query not in payload["deep_capability_portrait"].split("\n", 1)[0]
    assert "面向任务相关作战阶段" in payload["deep_capability_portrait"]


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
    assert (
        client.patch(f"/api/v1/runs/{created['run_id']}", json=body).status_code == 409
    )
    assert client.delete(f"/api/v1/runs/{created['run_id']}").status_code == 409


def test_interaction_candidate_board_omits_identityless_lineage_shells() -> None:
    def row(sequence: int, event_type: str, actor: str, details: dict) -> dict:
        return {
            "sequence": sequence,
            "event_id": f"event-{sequence}",
            "event_type": event_type,
            "actor": actor,
            "details": details,
        }

    rows = [
        row(
            1,
            "winning_candidate_branch_created",
            "agent-s3-1",
            {
                "hypothesis_id": "hypothesis-named",
                "mission_node": "S3",
                "score": 0.81,
                "title": "“游猎”自主远程效应器",
                "equipment_form": ["自主远程效应器"],
                "primary_equipment_identity": "自主远程效应器",
                "concise_winning_summary": "以持续搜索和自主追踪压缩机动目标脱离窗口。",
            },
        ),
        row(
            2,
            "winning_contribution_queued",
            "agent-s5-1",
            {
                "contribution_id": "contribution-shell",
                "hypothesis_id": "hypothesis-shell",
                "merge_target": "S5",
                "status": "queued",
            },
        ),
    ]
    view = SimpleNamespace(
        status="researching",
        research_route="new_winning_mechanism",
        discovery_branch="D",
        execution_profile_id="winning_swarm_dynamic_v2",
        selected_agent_ids=[],
        execution={"mode": "real", "provider": "codex", "model": "gpt-test"},
    )

    cluster = _interaction_workflow_summary(rows, view)["swarm_cluster"]

    assert [item["hypothesis_id"] for item in cluster["candidate_lineage"]] == [
        "hypothesis-named"
    ]
    assert cluster["candidate_lineage"][0]["title"] == (
        "“游猎”自主远程效应器"
    )
    assert cluster["candidate_lineage"][0]["reference_overview"].startswith(
        "以持续搜索"
    )
    assert any(
        item["hypothesis_id"] == "hypothesis-shell"
        for item in cluster["merge_receipts"]
    )
