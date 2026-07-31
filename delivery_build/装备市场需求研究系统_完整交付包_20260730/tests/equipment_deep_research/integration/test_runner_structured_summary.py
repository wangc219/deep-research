from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from equipment_deep_research.agents.provider import FakeAgentProvider, ResponsesAgentProvider
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.delivery.exporter import DeliveryExporter
from equipment_deep_research.orchestration.runner import (
    DeepResearchRunner,
    _persisted_agent_model_call_count,
)
from equipment_deep_research.providers.base import ProviderFinalTurn, ProviderStreamEvent
from equipment_deep_research.providers.fake import ScriptedFakeProvider


ROOT = Path(__file__).parents[3]
CONFIG = ROOT / "configs/equipment_deep_research"


def test_persisted_agent_model_calls_survive_resume_trace_loss(
    tmp_path: Path,
) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "model-call-ledger")
    try:
        workspace.write_run_text(
            "agent_sessions/international_situation.jsonl",
            "\n".join(
                [
                    json.dumps(
                        {
                            "agent_id": "international_situation",
                            "event_type": "agent_model_call_completed",
                        }
                    ),
                    "{malformed",
                    json.dumps(
                        {
                            "agent_id": "another_agent",
                            "event_type": "agent_model_call_completed",
                        }
                    ),
                    json.dumps(
                        {
                            "agent_id": "international_situation",
                            "event_type": "tool_call",
                        }
                    ),
                ]
            ),
        )

        assert _persisted_agent_model_call_count(
            workspace=workspace,
            agent_id="international_situation",
        ) == 1
        assert _persisted_agent_model_call_count(
            workspace=workspace,
            agent_id="missing_agent",
        ) == 0
    finally:
        workspace.close()


class _WinningHarnessProbeProvider(FakeAgentProvider):
    def analyze_winning_mechanism(self, payload: dict) -> dict:
        assert payload["packets"]
        return {
            "defense_decomposition": ["防御链关键节点"],
            "winning_paths": ["以感知和协同压缩响应时间"],
            "effect_chain": ["发现-识别-决策-处置-评估"],
            "capability_mapping": ["多源感知与韧性协同"],
            "gap_assessment": ["复杂环境下识别稳定性不足"],
            "concept_directions": ["分布式感知与人机协同"],
            "assumptions": ["公开资料仅用于工程验证"],
            "open_questions": [],
            "confidence": 0.8,
        }

    def draft_report(self, payload: dict) -> str:
        assert payload["topic"]
        return """## 第一层：需求挖掘层——场景·战法/技术·装备能力特征

### ① 典型作战场景

围绕对手、地域、烈度、时间窗和强电磁约束构造任务链断点场景。

### ② 新战法或新概念技术及制胜机理

现有范式过度依赖集中链路而存在不足；新战法通过分布式感知和协同闭合任务链，因此形成制胜优势。

### ③ 装备能力特征清单

能力域覆盖感知、决策、抗毁和反制，指标方向包括射程、响应时间、自主等级、成本量级与规模量级。

## 第二层：技术攻关层——能力实现途径与核心技术

### ④ 能力实现途径

近期沿用改进，中期集成创新，远期评估原理突破，并映射现役升级与新研装备。

### ⑤ 核心技术清单与攻关优先级

核心技术点包括制导律、材料体系和协同算法，标注成熟度、瓶颈和P0/P1优先级。

### ⑥ 技术耦合与短板风险

感知、通信与制导存在依赖和耦合，链路卡脖子短板可能拖垮整体能力。

## 第三层：能力图像与效能贡献层

### ⑦ 装备能力图像

能力域、指标画像和装备谱系位置共同定义现有装备体系中的任务边界。

### ⑧ 效能贡献评估

通过补链恢复闭环、强链提高反制、开链形成远程精打路径，量化方向包括突防率、交换比和决策周期改善量级。

### ⑨ 发展优先级与近期抓手

P0启动演示验证项目，设置验收指标、通过条件和失败条件；公开资料仅支撑方向性判断，后续通过任务级仿真和对抗试验证伪。
"""


class _CodexMetaReplanProbeProvider(_WinningHarnessProbeProvider):
    provider_kind = "codex_cli"

    def review_discovery_meta_loop(self, payload: dict) -> dict:
        assert payload["convergence"]["clusters"]
        return {
            "replan_required": True,
            "added_secondary_branches": ["E", "invalid"],
            "step_mode_overrides": [
                {"step": 1, "mode": "deep", "reason": "补强对手动向分析"},
                {"step": 7, "mode": "deep", "reason": "越界项应被拒绝"},
            ],
            "dynamic_subagents": [
                {
                    "display_name": "对手变化复核 Agent",
                    "purpose": "补充新增参考分支的专业缺口",
                    "trigger_gap": "现有结果缺少对手能力形成节奏复核",
                    "skill_ids": ["codex_deep_search_shared", "unknown"],
                    "knowledge_pack_ids": ["equipment_ontology", "unknown"],
                    "methodology": ["复核公开线索", "合并到S1"],
                    "quality_gates": ["证据引用有效"],
                    "output_fields": ["findings"],
                    "merge_target": "S1",
                    "stop_conditions": ["缺口闭合"],
                    "max_output_tokens": 1200,
                }
            ],
            "focus_questions": ["对手变化是否反向触发需求"],
            "rationale": "收敛结果出现跨分支线索。",
            "stop_reason": "bounded_replan_complete",
        }


class _AuditTimeoutProvider(_WinningHarnessProbeProvider):
    def review_audit(self, payload: dict) -> dict:
        assert "coverage_summary" in payload
        assert "evidence_index" not in payload
        assert all("outputs" not in stage for stage in payload["stage_gate_summary"])
        raise TimeoutError("simulated audit timeout")


class _ReportTimeoutProvider(_WinningHarnessProbeProvider):
    def review_audit(self, payload: dict) -> dict:
        return {
            "risk_summary": "deterministic checks retained",
            "findings": [],
            "release_recommendation": "limited",
        }

    def draft_report(self, payload: dict) -> str:
        assert payload["report_context"]
        assert payload["synthesis_seed"]
        assert "evidence_catalog" in payload
        assert len(payload["evidence_catalog"]) <= 8
        assert "decision_brief" not in payload
        assert "accepted_claims" not in payload
        assert "branch_deliverables" not in payload
        assert "intermediate_agent_analysis" not in payload
        assert "intermediate_agent_packets" not in payload
        assert "winning_reasoning_nodes" not in payload
        serialized = json.dumps(payload["synthesis_seed"], ensure_ascii=False)
        assert len(serialized) < 6000
        assert "packet-" not in serialized
        assert "ev-" not in serialized
        assert "cap-" not in serialized
        raise TimeoutError("simulated report timeout")


class _MissingReportProvider(_WinningHarnessProbeProvider):
    draft_report = None  # type: ignore[assignment]


def test_runner_exposes_provider_plan_reasoning_and_evidence_governance(tmp_path: Path) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider_config_path=CONFIG / "providers.yaml",
        evidence_config_path=CONFIG / "evidence.yaml",
    ).run(
        mode="fake",
        topic="低空无人机探测预警能力",
        research_route="new_winning_mechanism",
        run_id="structured-summary",
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert Path(result["manifest_path"]).is_file()
    assert result["manifest_file_count"] > 0
    assert DeliveryExporter().verify(result["run_dir"]) is True
    assert summary["provider"]["type"] == "fake"
    selected_baseline_ids = {
        item["agent_id"] for item in summary["worker_reports"]
    }
    assert summary["plan_graph"]["baseline_map_count"] == len(selected_baseline_ids)
    assert 1 <= len(selected_baseline_ids) <= 3
    assert summary["six_step_reasoning"]["gap_matrix"]["input_refs"]
    assert summary["evidence_assessments"]
    assert all(item["decision"] in {"accepted", "rejected", "duplicate"} for item in summary["evidence_assessments"])
    reports = summary["worker_reports"]
    assert len({item["harness_profile"] for item in reports}) == len(reports)
    assert all(item["active_skill_ids"] for item in reports)
    assert all(item["active_tool_names"] for item in reports)
    assert all(item["stop_reason"] == "quality_gates_passed" for item in reports)
    harness_events = [
        item for item in summary["trace_summary"]
        if item["event_type"] == "agent_harness_completed"
    ]
    assert {item["actor"] for item in harness_events} == selected_baseline_ids
    assert summary["store_summary"]["scenario_model_count"] == 1
    assert summary["store_summary"]["equipment_observation_count"] == 1
    assert summary["store_summary"]["operational_synthesis_count"] == 1


def test_audit_timeout_falls_back_and_still_generates_report(tmp_path: Path) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=_AuditTimeoutProvider(),
    ).run(
        mode="real",
        topic="审计超时降级验证",
        research_route="new_winning_mechanism",
        run_id="audit-timeout-fallback",
        agent_ids=[
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        analyst_confirmed=True,
        max_rounds=1,
    )

    trace = [
        json.loads(line)["payload"]
        for line in (Path(result["run_dir"]) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event_types = {item["event_type"] for item in trace}
    assert "audit_model_fallback" in event_types
    assert "audit_completed" in event_types
    assert "report_completed" in event_types
    assert result["audit_status"] == "limited"


def test_report_timeout_fails_without_deterministic_delivery(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    run_id = "report-timeout-no-fallback"
    with pytest.raises(RuntimeError, match="禁止确定性降级报告"):
        DeepResearchRunner(
            project_root=ROOT,
            output_root=output_root,
            agent_config_path=CONFIG / "agents.yaml",
            preset_config_path=CONFIG / "presets.yaml",
            provider=_ReportTimeoutProvider(),
        ).run(
            mode="real",
            topic="报告超时不降级验证",
            research_route="traditional_gap",
            run_id=run_id,
            agent_ids=[
                "international_situation",
                "combat_scenario",
                "weapon_equipment",
                "operational_employment",
            ],
            analyst_confirmed=True,
            max_rounds=1,
        )

    run_dir = output_root / run_id
    assert not (run_dir / "report.md").exists()
    failure = json.loads(
        (run_dir / "report_failure.json").read_text(encoding="utf-8")
    )
    assert failure["status"] == "failed_no_fallback"
    assert failure["report_written"] is False
    assert failure["resumable"] is True
    checkpoint = json.loads(
        (run_dir / "checkpoints" / "latest.json").read_text(encoding="utf-8")
    )["checkpoint"]
    assert checkpoint["task_statuses"]["finalize:winning-report"] == "pending"
    assert "finalize:winning-report" in checkpoint["pending_task_ids"]
    with sqlite3.connect(run_dir / "run.db") as connection:
        event_types = {
            str(row[0])
            for row in connection.execute("SELECT event_type FROM trace_events")
        }
    assert "report_model_failed" in event_types
    assert "report_model_fallback" not in event_types
    assert "report_completed" not in event_types


def test_reporter_failure_can_resume_into_real_model_report(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    run_id = "report-failure-resume"
    run_kwargs = {
        "mode": "real",
        "topic": "报告失败后恢复验证",
        "research_route": "traditional_gap",
        "run_id": run_id,
        "agent_ids": [
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        "analyst_confirmed": True,
        "max_rounds": 1,
    }
    with pytest.raises(RuntimeError, match="禁止确定性降级报告"):
        DeepResearchRunner(
            project_root=ROOT,
            output_root=output_root,
            agent_config_path=CONFIG / "agents.yaml",
            preset_config_path=CONFIG / "presets.yaml",
            provider=_ReportTimeoutProvider(),
        ).run(**run_kwargs)

    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=output_root,
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=_WinningHarnessProbeProvider(),
    ).run(**run_kwargs, resume=True)

    run_dir = Path(result["run_dir"])
    assert result["status"] == "completed"
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "围绕对手、地域、烈度、时间窗和强电磁约束构造任务链断点场景" in report
    assert "当前按“传统能力缺口发现”分支撰写" not in report
    with sqlite3.connect(run_dir / "run.db") as connection:
        event_types = [
            str(row[0])
            for row in connection.execute(
                "SELECT event_type FROM trace_events ORDER BY rowid"
            )
    ]
    assert "report_model_failed" in event_types
    assert event_types[-1] == "report_completed"
    assert event_types.index("report_model_failed") < event_types.index(
        "report_completed"
    )


def test_missing_report_provider_uses_same_resumable_failure_path(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "runs"
    run_id = "report-provider-missing-no-fallback"
    with pytest.raises(RuntimeError, match="禁止确定性降级报告"):
        DeepResearchRunner(
            project_root=ROOT,
            output_root=output_root,
            agent_config_path=CONFIG / "agents.yaml",
            preset_config_path=CONFIG / "presets.yaml",
            provider=_MissingReportProvider(),
        ).run(
            mode="real",
            topic="报告Provider缺失不降级验证",
            research_route="traditional_gap",
            run_id=run_id,
            agent_ids=[
                "international_situation",
                "combat_scenario",
                "weapon_equipment",
                "operational_employment",
            ],
            analyst_confirmed=True,
            max_rounds=1,
        )

    run_dir = output_root / run_id
    assert not (run_dir / "report.md").exists()
    failure = json.loads(
        (run_dir / "report_failure.json").read_text(encoding="utf-8")
    )
    assert failure["status"] == "failed_no_fallback"
    assert failure["reason"] == "RuntimeError"
    assert failure["report_written"] is False
    with sqlite3.connect(run_dir / "run.db") as connection:
        event_types = {
            str(row[0])
            for row in connection.execute("SELECT event_type FROM trace_events")
        }
    assert "report_model_failed" in event_types
    assert "report_completed" not in event_types


def test_runner_executes_autonomous_technology_branch_and_convergence(
    tmp_path: Path,
) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
    ).run(
        mode="fake",
        topic="量子传感技术驱动装备需求",
        research_route="auto",
        interaction_mode="autonomous",
        discovery_branch="D",
        run_id="autonomous-technology-branch",
        max_rounds=1,
    )

    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["interaction_mode"] == "autonomous"
    assert summary["discovery_blueprint"]["primary_branch"] == "D"
    assert "scenario_divergence" in summary["selected_agent_ids"]
    assert "technology_radar" in summary["selected_agent_ids"]
    assert summary["discovery_convergence"]["clusters"]
    waves = summary["plan_graph"]["execution_waves"]
    assert waves[0]["agent_ids"] == ["scenario_divergence"]
    event_types = {item["event_type"] for item in summary["trace_summary"]}
    assert "discovery_convergence_completed" in event_types
    assert "discovery_meta_loop_evaluated" in event_types
    assert "winning_outer_loop_evaluated" in event_types
    performance = summary["performance_summary"]
    assert performance["wall_time_seconds"] >= 0
    assert performance["selected_agent_count"] == len(summary["selected_agent_ids"])
    assert performance["winning_step_call_counts"] == {
        str(step): 0 for step in range(1, 7)
    }


def test_codex_l4_meta_loop_replans_next_stage_and_persists_blueprint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_ENABLE_L4_MODEL_REPLAN", "1")
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=_CodexMetaReplanProbeProvider(),
    ).run(
        mode="real",
        topic="跨域线索触发对手动向复核",
        research_route="new_winning_mechanism",
        discovery_branch="G",
        run_id="codex-meta-replan",
        agent_ids=[
            "cross_domain_fusion",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        max_rounds=1,
    )

    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    blueprint = summary["discovery_blueprint"]
    assert blueprint["loop_policy"]["meta_max_cycles"] == 1
    assert blueprint["secondary_branches"] == ["E"]
    assert blueprint["adaptive_winning_step_modes"] == {"1": "deep"}
    assert blueprint["meta_review"]["step_mode_changes"] == [
        {
            "step": 1,
            "previous_mode": "skip",
            "mode": "deep",
            "reason": "补强对手动向分析",
        }
    ]
    assert blueprint["dynamic_subagents"][0]["merge_target"] == "S1"
    assert blueprint["dynamic_subagents"][0]["skill_ids"] == [
        "codex_deep_search_shared"
    ]
    assert summary["discovery_convergence"]["meta_review"]["replan_required"] is True
    meta_events = [
        item for item in summary["trace_summary"]
        if item["event_type"] == "discovery_meta_loop_evaluated"
    ]
    assert meta_events[-1]["summary"] == "L4元循环已完成有界重规划"
    trace_rows = [
        json.loads(line)["payload"]
        for line in (Path(result["run_dir"]) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    final_meta_event = next(
        item
        for item in reversed(trace_rows)
        if item["event_type"] == "discovery_meta_loop_evaluated"
    )
    assert final_meta_event["payload"]["step_mode_changes"] == [
        {
            "step": 1,
            "previous_mode": "skip",
            "mode": "deep",
            "reason": "补强对手动向分析",
        }
    ]


def test_real_winning_core_records_harness_profile_skills_and_tools(tmp_path: Path) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=_WinningHarnessProbeProvider(),
    ).run(
        mode="real",
        topic="低空无人机防御制胜机理",
        research_route="new_winning_mechanism",
        run_id="winning-core-harness-trace",
        agent_ids=[
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        analyst_confirmed=True,
    )
    trace = [
        json.loads(line)["payload"]
        for line in (Path(result["run_dir"]) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event = next(
        item
        for item in trace
        if item["event_type"] == "agent_harness_completed"
        and item["actor"] == "winning_mechanism"
    )

    assert event["payload"]["runtime_profile_id"] == "winning_core_v1"
    assert event["payload"]["active_skill_ids"]
    assert event["payload"]["active_tool_names"]
    assert event["payload"]["phase_id"] == "winning"
    reasoning_events = [
        item for item in trace
        if item["event_type"] == "winning_reasoning_step_completed"
    ]
    assert len(reasoning_events) >= 6
    assert len(reasoning_events) % 6 == 0
    assert all(item["payload"]["next_action"] for item in reasoning_events)


def test_optimized_winning_harness_uses_single_skill_and_minimal_tools(
    tmp_path: Path,
) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=_WinningHarnessProbeProvider(),
    ).run(
        mode="real",
        topic="体系对抗关键链路韧性",
        research_route="traditional_gap",
        run_id="optimized-winning-harness-trace",
        agent_ids=[
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        analyst_confirmed=True,
        execution_profile_id="optimized_v2",
    )
    trace = [
        json.loads(line)["payload"]
        for line in (Path(result["run_dir"]) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event = next(
        item
        for item in trace
        if item["event_type"] == "agent_harness_completed"
        and item["actor"] == "winning_mechanism"
    )

    assert len(event["payload"]["active_skill_ids"]) == 1
    assert event["payload"]["active_tool_names"] == [
        "write_reasoning_node",
        "write_stage_output",
        "create_capability_image",
    ]
    assert not any(item["event_type"] == "audit_model_fallback" for item in trace)
    assert not any(
        item["event_type"] == "tool_call"
        and item["actor"] == "auditor"
        and item.get("payload", {}).get("tool_name") == "review_audit"
        for item in trace
    )


def test_runner_materializes_responses_web_sources_before_formal_packet_linking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_PROMOTE_REQUIRED_BASELINE", "0")
    backend = ScriptedFakeProvider(
        [[
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=(
                        '{"findings":["威胁力量正在压缩预警时间"],"confidence":0.8,'
                        '"open_questions":[],"handoff_summary":"联网证据研判完成",'
                        '"source_claims":[{"url":"https://fixture.local/public-report",'
                        '"claim":"公开报告支撑预警时间压缩判断"}]}'
                    ),
                    metadata={
                        "search_queries": ["低空威胁 预警时间"],
                        "web_sources": [
                            {
                                "url": "https://fixture.local/public-report",
                                "title": "公开威胁报告",
                                "snippet": "公开资料摘要",
                            }
                        ],
                    },
                )
            )
        ]] * 6
    )
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=ResponsesAgentProvider(backend),
    ).run(
        mode="fake",
        topic="低空无人机探测预警能力",
        research_route="new_winning_mechanism",
        run_id="responses-web-source",
        agent_ids=["international_situation"],
        max_rounds=1,
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["store_summary"]["evidence_count"] == 1
    assert summary["source_materials"][0]["status"] == "fixture_materialized"
    packet = next(
        json.loads(line)["payload"]
        for line in (Path(result["run_dir"]) / "domain.jsonl").read_text(encoding="utf-8").splitlines()
        if json.loads(line)["type"] == "BaselineFindingPacket"
    )
    assert packet["evidence_ids"]
    assert packet["search_log"] == ["低空威胁 预警时间"]
