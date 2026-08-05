from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from equipment_deep_research.orchestration.stage_policy import (
    resolve_run_stage_policy,
)
from equipment_deep_research.orchestration.runner import (
    _baseline_only_capability_cues,
    _baseline_only_grounded_fallback_report,
    _baseline_only_report_violations,
)
from equipment_deep_research.agents.provider import (
    _report_target_chars,
    _reporter_output_token_budget,
    _report_writer_system_prompt,
)
from evals.ablation.reporting import effect_summary, write_ablation_report
from evals.ablation.validation import validate_variant_trace
from evals.ablation.web_api import create_ablation_router, _live_progress_snapshot
from evals.ablation import web_api as ablation_web_api
from evals.ablations import build_no_domain_agents_config
from equipment_deep_research.api.app import create_app


ROOT = Path(__file__).parents[2]


def test_stage_policy_matrix_preserves_full_method_defaults() -> None:
    full = resolve_run_stage_policy(None)
    assert full.winning_enabled
    assert full.feedback_loops_enabled
    assert full.meta_loop_enabled

    baseline = resolve_run_stage_policy("no_multisource_baseline")
    assert baseline.winning_enabled
    assert baseline.feedback_loops_enabled
    assert baseline.meta_loop_enabled
    assert baseline.evidence_closed

    winning = resolve_run_stage_policy("no_winning_mechanism")
    assert not winning.winning_enabled
    assert not winning.feedback_loops_enabled
    assert winning.baseline_report_only


def test_single_generic_registry_removes_domain_and_multi_lane_policy(tmp_path: Path) -> None:
    target = build_no_domain_agents_config(ROOT, tmp_path)
    import yaml

    payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    generic = next(row for row in payload["agents"] if row["agent_id"] == "generic_researcher")
    assert generic["skill_ids"] == []
    assert generic["knowledge_pack_ids"] == []
    assert generic["research_policy"]["search_tracks"] == ["通用公开资料"]
    assert generic["research_policy"]["min_source_families"] == 1
    assert generic["research_policy"]["require_counter_evidence"] is False
    assert generic["research_policy"]["target_source_count"] == 2
    assert generic["research_policy"]["evidence_accept_target"] == 2
    assert generic["research_policy"]["evidence_materialize_attempts"] == 2
    assert generic["research_policy"]["search_intensity"] == "light"
    assert generic["capability_tags"] == [
        "general_research",
        "open_source_retrieval",
    ]
    assert "capability_gaps" not in generic["output_contract"]["properties"]
    assert generic["model_profile"]["reasoning_effort"] == "medium"
    assert generic["model_profile"]["max_output_tokens"] == 1800
    assert generic["model_profile"]["search_context_size"] == "low"
    assert generic["context_policy"]["token_budget"] == 2800


def test_trace_validator_rejects_forbidden_loop_and_winning_events(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "\n".join(
            json.dumps(
                {
                    "type": "TraceEvent",
                    "payload": {"event_type": event_type},
                }
            )
            for event_type in ("run_started", "winning_outer_loop_evaluated")
        ),
        encoding="utf-8",
    )
    result = validate_variant_trace(
        "no_multisource_baseline",
        ["trace.jsonl"],
        tmp_path,
    )
    assert not result["valid"]
    assert "受限通用检索Agent" in result["reason"]

    trace.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "TraceEvent",
                        "payload": {
                            "event_type": "baseline_agent_completed",
                            "actor": "generic_researcher",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "TraceEvent",
                        "payload": {
                            "event_type": "winning_outer_loop_evaluated",
                            "actor": "winning_mechanism",
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    assert validate_variant_trace(
        "no_multisource_baseline",
        ["trace.jsonl"],
        tmp_path,
    )["valid"]

    trace.write_text(
        json.dumps(
            {
                "type": "TraceEvent",
                "payload": {"event_type": "winning_reasoning_step_completed"},
            }
        ),
        encoding="utf-8",
    )
    result = validate_variant_trace(
        "no_winning_mechanism",
        ["trace.jsonl"],
        tmp_path,
    )
    assert not result["valid"]


def test_baseline_only_report_gate_requires_known_markers_and_urls() -> None:
    seed = {
        "decisive_anchors": ["[B01] 已准入事实"],
        "counterevidence_and_limits": ["[B02] 已知限制"],
    }
    assert _baseline_only_report_violations(
        "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征\n"
        "### ① 典型作战场景\n- [B01] 已准入事实。\n"
        "### ② 新战法或新概念技术及制胜机理\n- [B02] 已知限制。",
        synthesis_seed=seed,
        allowed_urls=set(),
    ) == []


def test_baseline_only_reporter_keeps_full_budget_and_paragraph_citations() -> None:
    payload = {"ablation_scope": "baseline_only_no_winning_no_loops"}
    assert (
        _report_target_chars(payload)
        == "信息闭环优先、通常7000-10000字的核心正文"
    )
    assert _reporter_output_token_budget(payload, default=12000) == 12000
    prompt = _report_writer_system_prompt(payload)
    assert "正常完成完整的三层九项研究报告" in prompt
    seed = {"decisive_anchors": ["[B01] 已准入事实"]}
    report = (
        "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征\n"
        "### ① 典型作战场景\n"
        "[B01] 本段首先陈述准入事实。随后用多个完整句组织同一证据支持的分析，"
        "不要求每一行重复标记。\n"
        "这一行仍属于同一连续论证段。"
    )
    assert _baseline_only_report_violations(
        report,
        synthesis_seed=seed,
        allowed_urls=set(),
    ) == []


def test_restricted_generic_reporter_is_evidence_closed_but_complete() -> None:
    prompt = _report_writer_system_prompt(
        {"ablation_scope": "restricted_generic_baseline_evidence_closed"}
    )
    assert "必须正常完成完整的三层九项报告" in prompt
    assert "Query只定义范围，不是事实来源" in prompt
    assert "不得为了满足5至7项" in prompt


def test_baseline_only_grounded_fallback_is_provenance_closed() -> None:
    seed = {
        "decisive_anchors": ["[B01] 已准入事实"],
        "counterevidence_and_limits": ["[B02] 已知限制"],
        "priority_signals": [],
    }
    report = _baseline_only_grounded_fallback_report(
        "测试主题",
        synthesis_seed=seed,
        evidence=[],
    )
    assert "[B01] 已准入事实" in report
    assert "[B02] 已知限制" in report
    assert _baseline_only_report_violations(
        report,
        synthesis_seed=seed,
        allowed_urls=set(),
    ) == []


def test_no_winning_baseline_projects_concrete_capability_images() -> None:
    equipment = SimpleNamespace(
        agent_id="weapon_equipment",
        payload={
            "equipment_profiles": [
                "PrSM Increment 1：陆基远程精确火力升级。",
                "Tomahawk Block V：海基远程巡航导弹升级。",
                "JASSM-ER/LRASM：空射低可探测防区外弹药升级。",
                "Gray Eagle 25M/MQ-9A：远程无人打击平台升级。",
                "NGJ-MB/AARGM-ER/MALD-J：远域压制武器升级。",
            ],
            "new_equipment_requirements": [
                "需求卡1：低成本断链可执行远程效应器；支撑持续补伤。",
                "需求卡2：通用Launched Effects载荷族；支撑侦察与轻型毁伤。",
            ],
            "capability_gaps": ["现役高端导弹库存与成本约束。"],
            "technology_readiness": ["成熟度按公开交付与试验状态核验。"],
            "development_models": ["现役做优与新研拓新并行。"],
            "system_dependencies": ["依赖目标包、PNT、授权边界和BDA。"],
            "capability_constraints": ["强干扰和诱饵会削弱效果。"],
            "verification_plan": ["开展场景化仿真和半实物验证。"],
        },
    )
    operations = SimpleNamespace(
        agent_id="operational_employment",
        payload={
            "equipment_function_requirements": [
                "远程精确打击任务包与抗干扰PNT能力。",
                "可消耗边缘自治巡飞与补打能力。",
                "诱骗开窗与被动侦收接力能力。",
            ],
            "mission_chain": ["任务装订—进入—末段确认—效果续接。"],
            "failure_modes": ["目标包过期或识别置信不足时任务失败。"],
        },
    )
    marker = 0

    def tagged(value: object, *, max_chars: int) -> str:
        nonlocal marker
        marker += 1
        return f"[B{marker:02d}] {str(value)[:max_chars]}"

    cues = _baseline_only_capability_cues(
        [equipment, operations],
        tagged=tagged,
    )
    assert len(cues) == 7
    assert all(row["direction"].startswith("[B") for row in cues)
    assert any("Tomahawk Block V" in row["direction"] for row in cues)
    assert any("低成本断链可执行远程效应器" in row["direction"] for row in cues)
    report = _baseline_only_grounded_fallback_report(
        "测试主题",
        synthesis_seed={
            "decisive_anchors": ["[B08] 基线事实"],
            "counterevidence_and_limits": [],
            "priority_signals": [],
            "capability_cues": cues,
        },
        evidence=[],
    )
    assert "装备系统方向" in report
    assert "Tomahawk Block V" in report
    seed = {
        "decisive_anchors": ["[B01] 已准入事实"],
        "counterevidence_and_limits": ["[B02] 已知限制"],
    }
    violations = _baseline_only_report_violations(
        "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征\n"
        "### ① 典型作战场景\n- [B99] 新结论 https://unknown.invalid/source",
        synthesis_seed=seed,
        allowed_urls=set(),
    )
    assert any("未知基线标记" in item for item in violations)
    assert any("基线证据外URL" in item for item in violations)
    allowed_url = "https://example.invalid/source"
    assert _baseline_only_report_violations(
        f"## 第一层：需求挖掘层——场景·战法/技术·装备能力特征\n"
        f"### ① 典型作战场景\n- [B01] [{allowed_url}]({allowed_url})在输入中用于支撑已准入事实。",
        synthesis_seed=seed,
        allowed_urls={allowed_url},
    ) == []


def test_effect_classification_and_markdown_report(tmp_path: Path) -> None:
    comparison = {
        "systems": {
            "full_method": {"score_rate": 0.8, "bootstrap_95pct": [0.7, 0.9]},
            "no_winning_mechanism": {"score_rate": 0.2, "bootstrap_95pct": [0.1, 0.3]},
        },
        "query_outcomes": [
            {"query_id": f"Q-{index:02d}", "winner": "full_method"}
            for index in range(10)
        ],
        "dimension_votes": {},
    }
    effect = effect_summary(comparison, "no_winning_mechanism")
    assert effect["status"] == "supported"
    assert effect["paired_bootstrap_95pct"] == [1.0, 1.0]
    manifest = {
        "experiment_id": "exp-1",
        "dataset_id": "fixture-smoke",
        "query_count": 1,
        "control_source": "rerun",
        "mode": "fake",
        "exploratory_only": False,
        "validity": {"no_winning_mechanism": {"valid": True}},
    }
    path = write_ablation_report(
        tmp_path,
        manifest=manifest,
        summary={
            "comparisons": {"no_winning_mechanism": comparison},
            "effects": {"no_winning_mechanism": effect},
        },
    )
    assert "设计贡献得到支持" in path.read_text(encoding="utf-8")


def test_live_progress_reads_active_runner_stage_from_sqlite(tmp_path: Path) -> None:
    root = tmp_path / "experiment"
    root.mkdir()
    (root / "results.jsonl").write_text(
        json.dumps(
            {
                "eval_id": "exp-live",
                "query_id": "Q-0001",
                "system_id": "full_method",
                "status": "completed",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime = root / "systems" / "no_multisource_baseline" / "Q-0001" / "runtime" / "run-1"
    runtime.mkdir(parents=True)
    database = sqlite3.connect(runtime / "run.db")
    database.execute(
        "CREATE TABLE trace_events (run_sequence INTEGER, event_type TEXT, actor TEXT, payload_json TEXT, created_at TEXT)"
    )
    database.execute(
        "INSERT INTO trace_events VALUES (?, ?, ?, ?, ?)",
        (
            1,
            "packet_admission_evaluated",
            "packet_admission_gate",
            json.dumps({"summary": "generic packet accepted", "payload": {}}),
            "2026-07-26T06:52:17+00:00",
        ),
    )
    database.commit()
    database.close()
    snapshot = _live_progress_snapshot(
        root,
        {
            "query_ids": ["Q-0001"],
            "variants": ["full_method", "no_multisource_baseline"],
            "stage": "running_variants",
        },
    )
    assert snapshot["completed_tasks"] == 1
    assert snapshot["total_tasks"] == 2
    assert snapshot["percent"] > 0
    assert snapshot["current_stage_label"] == "基线准入，准备 S1–S6"


def test_ablation_overview_is_exposed_as_optional_router() -> None:
    app = FastAPI()
    app.include_router(create_ablation_router(ROOT, list_research_runs=lambda: []))
    response = TestClient(app).get("/api/v1/ablations/overview")
    assert response.status_code == 200
    assert [row["variant_id"] for row in response.json()["variants"]] == [
        "full_method",
        "no_multisource_baseline",
        "no_winning_mechanism",
    ]
    assert response.json()["defaults"]["control_source"] == "existing"


def test_ablation_api_lifecycle_manifest_hashes_and_secret_redaction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    fixture_dir = project / "evals" / "fixtures"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "smoke_queries.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "difficulty": "easy",
                    "domain": "低空",
                    "query": f"评估公开资料条件下低空无人系统探测预警能力需求{index}。",
                    "query_id": f"Q-{index:04d}",
                    "region": "台海",
                    "split": "pilot",
                },
                ensure_ascii=False,
            )
            for index in range(1, 5)
        )
        + "\n",
        encoding="utf-8",
    )
    (project / "evals" / "config.yaml").write_text("systems: {}\n", encoding="utf-8")
    (project / "evals" / "pairwise_prompt_v1.md").write_text(
        "{{QUERY}}\n{{ANSWER_A}}\n{{ANSWER_B}}\n{{PAIR_ID}}\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class DormantThread:
        def __init__(self, **kwargs):
            captured["thread"] = self
            self.kwargs = kwargs

        def start(self) -> None:
            captured["started"] = True

    monkeypatch.setattr(ablation_web_api, "Thread", DormantThread)
    app = FastAPI()
    app.include_router(
        create_ablation_router(
            project,
            list_research_runs=lambda: [
                {
                    "run_id": "run-existing-q1",
                    "topic": "评估公开资料条件下低空无人系统探测预警能力需求1。",
                    "updated_at": "2026-07-29T12:00:00+08:00",
                }
            ],
            load_research_report=lambda run_id: {
                "answer": f"# 已有完整方法报告 {run_id}",
                "citations": [],
                "sources": [],
                "model_snapshot": {"model": "test-model"},
            },
        )
    )
    client = TestClient(app)
    auto_bound_control = client.post(
        "/api/v1/ablations/runs",
        headers={"X-Role": "analyst"},
        json={
            "experiment_id": "invalid-existing-control",
            "dataset_id": "fixture-smoke",
            "query_ids": ["Q-0001"],
            "control_source": "existing",
            "mode": "real",
            "judge_mode": "fake",
            "confirm_external_data": True,
        },
    )
    assert auto_bound_control.status_code == 202
    auto_manifest = auto_bound_control.json()
    assert auto_manifest["project_runs"] == {"Q-0001": "run-existing-q1"}
    assert auto_manifest["exploratory_only"] is True
    assert auto_manifest["causal_comparison_valid"] is False
    insufficient_sample = client.post(
        "/api/v1/ablations/runs",
        headers={"X-Role": "analyst"},
        json={
            "experiment_id": "insufficient-sample",
            "dataset_id": "fixture-smoke",
            "query_ids": ["Q-0001"],
            "control_source": "rerun",
            "mode": "real",
            "judge_mode": "real",
            "confirm_external_data": True,
        },
    )
    assert insufficient_sample.status_code == 422
    assert "至少需要2条 Query" in insufficient_sample.json()["detail"]
    secret = "judge-secret-must-not-persist"
    response = client.post(
        "/api/v1/ablations/runs",
        headers={"X-Role": "analyst"},
        json={
            "experiment_id": "api-lifecycle",
            "dataset_id": "fixture-smoke",
            "query_ids": ["Q-0001", "Q-0002"],
            "control_source": "rerun",
            "mode": "real",
            "judge_mode": "real",
            "confirm_external_data": True,
            "judge_llm": {
                "credential_source": "manual",
                "api_protocol": "responses",
                "base_url": "https://example.invalid/v1",
                "api_key": secret,
                "model": "judge-test",
                "replicas": 2,
            },
        },
    )
    assert response.status_code == 202
    manifest_path = project / "outputs" / "evals" / "ablations" / "api-lifecycle" / "manifest.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert len(manifest["configuration_sha256"]) == 64
    assert len(manifest["dataset_sha256"]) == 64
    assert len(manifest["judge_prompt"]["sha256"]) == 64
    assert manifest["stage_policies"]["no_winning_mechanism"]["winning_enabled"] is False
    assert manifest["stage_policies"]["no_multisource_baseline"]["evidence_closed"] is True
    assert manifest["causal_comparison_valid"] is True
    assert manifest["minimum_sample_passed"] is True
    assert secret not in manifest_text
    assert captured["started"] is True
    assert captured["thread"].kwargs["kwargs"]["judge_configs"][0]["api_key"] == secret

    assert client.get(
        "/api/v1/ablations/runs/api-lifecycle",
        headers={"X-Role": "viewer"},
    ).status_code == 403
    assert client.get(
        "/api/v1/ablations/runs/%2E%2E",
        headers={"X-Role": "analyst"},
    ).status_code in {404, 422}

    (manifest_path.parent / "results.jsonl").write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in (
                {
                    "eval_id": "api-lifecycle",
                    "query_id": "Q-0001",
                    "system_id": "full_method",
                    "status": "completed",
                    "answer": "# 完整方法报告",
                },
                {
                    "eval_id": "api-lifecycle",
                    "query_id": "Q-0001",
                    "system_id": "no_winning_mechanism",
                    "status": "failed",
                    "error": "report gate failed",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    reports = client.get(
        "/api/v1/ablations/runs/api-lifecycle/reports",
        headers={"X-Role": "analyst"},
    )
    assert reports.status_code == 200
    report_rows = reports.json()["queries"][0]["reports"]
    assert report_rows["full_method"]["answer"] == "# 完整方法报告"
    assert report_rows["no_winning_mechanism"]["status"] == "failed"
    assert (
        manifest_path.parent / "reports" / "Q-0001" / "full_method" / "report.md"
    ).is_file()

    report_path = manifest_path.parent / "ablation-report.md"
    report_path.write_text("# 消融报告\n", encoding="utf-8")
    assert client.get(
        "/api/v1/ablations/runs/api-lifecycle/report",
        headers={"X-Role": "analyst"},
    ).status_code == 200
    assert client.get(
        "/api/v1/ablations/runs/api-lifecycle/bundle",
        headers={"X-Role": "analyst"},
    ).status_code == 200
    assert client.post(
        "/api/v1/ablations/runs/api-lifecycle/cancel",
        headers={"X-Role": "analyst"},
    ).status_code == 202
    cancelling = json.loads(manifest_path.read_text(encoding="utf-8"))
    cancelling["status"] = "completed"
    manifest_path.write_text(json.dumps(cancelling), encoding="utf-8")
    assert client.delete(
        "/api/v1/ablations/runs/api-lifecycle",
        headers={"X-Role": "analyst"},
    ).json() == {"experiment_id": "api-lifecycle", "deleted": True}
    assert not manifest_path.parent.exists()


def test_core_api_stays_available_when_ablation_extension_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_ENABLE_ABLATION", "0")
    client = TestClient(create_app())
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/ablations/overview").status_code == 404
