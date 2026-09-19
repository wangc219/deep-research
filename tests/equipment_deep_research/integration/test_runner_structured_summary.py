from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from equipment_deep_research.agents.provider import FakeAgentProvider, ResponsesAgentProvider
from equipment_deep_research.domain.models import CapabilityImageItem, TraceEvent
from equipment_deep_research.domain.store import TraceStore
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.delivery.exporter import DeliveryExporter
from equipment_deep_research.orchestration.runner import (
    DeepResearchRunner,
    _clean_report_brief_text,
    _clean_report_capability_portrait,
    _codex_loops_recorded,
    _compact_winning_blueprint,
    _normalize_delivery_report_structure,
    _persisted_agent_model_call_count,
    _report_delivery_limit_payload,
    _report_decision_brief,
)
from equipment_deep_research.providers.base import ProviderFinalTurn, ProviderStreamEvent
from equipment_deep_research.providers.fake import ScriptedFakeProvider


ROOT = Path(__file__).parents[3]
CONFIG = ROOT / "configs/equipment_deep_research"


def test_report_brief_preserves_trusted_s6_portrait_verbatim() -> None:
    store = DomainStore()
    item = CapabilityImageItem(
        capability_id="cap-1",
        name="可信S6原创装备",
        equipment_category="具体武器",
        capability_type="new_capability",
        source_winning_logic="改变交战交换关系",
        related_scenario="受扰环境",
        priority="P1",
        capability_gap="外部更新中断",
        capability_image="原创画像-不含标准治理模块-保留原文",
        deep_capability_portrait="原创画像-不含标准治理模块-保留原文",
        portrait_authoring_status="s6_authored_semantically_consistent",
        evidence_ids=[],
        confidence=0.8,
    )
    store.capability_images[item.capability_id] = item

    brief = _report_decision_brief(store=store, branch_output={}, convergence={})

    assert brief["capability_decisions"][0]["capability_portrait"] == (
        "原创画像-不含标准治理模块-保留原文"
    )


def test_compact_winning_blueprint_keeps_enabled_swarm_policy() -> None:
    compact = _compact_winning_blueprint(
        {
            "primary_branch": "B",
            "execution_profile_id": "swarm_quality_v1",
            "winning_swarm_policy": {
                "policy_id": "winning_swarm_quality_v1",
                "enabled": True,
                "max_dynamic_instances": 12,
            },
            "unrelated_large_catalog": {"ignored": True},
        }
    )

    assert compact["winning_swarm_policy"]["enabled"] is True
    assert compact["winning_swarm_policy"]["max_dynamic_instances"] == 12
    assert "unrelated_large_catalog" not in compact


def test_dynamic_swarm_expert_sessions_satisfy_profile_equivalent_loop_audit() -> None:
    assert _codex_loops_recorded(
        mode="real",
        execution_profile_id="winning_swarm_dynamic_v2",
        event_types=set(),
        persisted_loop_kinds=set(),
        session_agents={
            "winning-agent-123",
            "winning-quality-judge-456",
        },
    )
    assert not _codex_loops_recorded(
        mode="real",
        execution_profile_id="swarm_quality_v1",
        event_types=set(),
        persisted_loop_kinds=set(),
        session_agents={
            "winning-agent-123",
            "winning-quality-judge-456",
        },
    )


def test_report_delivery_limit_payload_preserves_quality_project_contract() -> None:
    brief = {"branch": "B", "hard_max_chars": 12000}

    payload = _report_delivery_limit_payload(
        discovery_blueprint={"execution_profile_id": "swarm_quality_v1"},
        report_template_mode="project_argument_v1",
        branch_writer_brief=brief,
    )

    assert payload == {
        "execution_profile_id": "swarm_quality_v1",
        "report_template_mode": "project_argument_v1",
        "branch_writer_brief": brief,
    }


def test_performance_summary_counts_completed_dynamic_swarm_instances() -> None:
    trace = TraceStore()
    for index in range(3):
        trace.append(
            TraceEvent(
                event_id=f"swarm-{index}",
                event_type="winning_subagent_completed",
                actor=f"winning-agent-{index}",
                summary="completed",
                payload={
                    "event_type": "winning_agent_session_completed",
                    "elapsed_seconds": 1.0,
                },
            )
        )

    summary = DeepResearchRunner._performance_summary(
        trace=trace,
        selected_agent_ids=["weapon_equipment"],
        discovery_blueprint={"baseline_agent_plan": []},
    )

    assert summary["dynamic_agent_count"] == 3


def test_performance_summary_includes_reporter_model_calls() -> None:
    trace = TraceStore()
    for event_id, event_type, elapsed_seconds in (
        ("baseline", "agent_model_call_completed", 10.0),
        ("winning", "winning_model_call_completed", 20.0),
        ("reporter", "report_model_call_completed", 30.0),
    ):
        trace.append(
            TraceEvent(
                event_id=event_id,
                event_type=event_type,
                actor=event_id,
                summary="completed",
                payload={
                    "elapsed_seconds": elapsed_seconds,
                    "queue_wait_seconds": 0.0,
                },
            )
        )

    summary = DeepResearchRunner._performance_summary(
        trace=trace,
        selected_agent_ids=["weapon_equipment"],
        discovery_blueprint={"baseline_agent_plan": []},
    )

    assert summary["model_call_count"] == 3
    assert summary["model_elapsed_seconds_sum"] == 60.0
    assert summary["max_model_call_seconds"] == 30.0


def test_dynamic_swarm_progress_preserves_event_type_and_friendly_summary(
    tmp_path: Path,
) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "dynamic-events")
    trace = TraceStore()
    try:
        DeepResearchRunner._record_winning_progress_row(
            workspace,
            trace,
            {
                "event_type": "winning_agent_session_completed",
                "agent_id": "winning-agent-1",
                "mission_node": "S5",
                "elapsed_seconds": 12.5,
            },
            attempt=1,
            event_suffix="1",
        )
    finally:
        workspace.close()

    event = trace.snapshot()[0]
    assert event.event_type == "winning_agent_session_completed"
    assert event.actor == "winning-agent-1"
    assert "动态蜂群 Agent 独立模型会话已完成" in event.summary
    assert event.payload["mission_node"] == "S5"


@pytest.mark.parametrize(
    ("event_type", "summary_fragment"),
    [
        (
            "winning_specialized_seed_recovered",
            "恢复专用候选",
        ),
        (
            "winning_specialized_seed_empty",
            "未恢复额外种子",
        ),
        (
            "winning_contribution_hypothesis_remapped",
            "重映射到规范候选",
        ),
    ],
)
def test_dynamic_swarm_recovery_events_do_not_fall_back_to_snone(
    tmp_path: Path,
    event_type: str,
    summary_fragment: str,
) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", event_type)
    trace = TraceStore()
    try:
        DeepResearchRunner._record_winning_progress_row(
            workspace,
            trace,
            {
                "event_type": event_type,
                "agent_id": "winning-agent-recovery",
                "mission_node": "S3",
            },
            attempt=1,
            event_suffix="1",
        )
    finally:
        workspace.close()

    event = trace.snapshot()[0]
    assert event.event_type == event_type
    assert summary_fragment in event.summary
    assert "SNone" not in event.summary


def test_delivery_report_structure_repair_preserves_h1_and_restores_parent() -> None:
    report = "\n".join(
        (
            "# 项目研究报告",
            "## 二、项目画像",
            "### （四）主要战技指标",
            "指标正文。",
            "### （一）总体架构",
            "总体架构正文。",
            "### （二）子系统方案",
            "子系统正文。",
            "## 四、关键技术",
        )
    )

    normalized = _normalize_delivery_report_structure(report)

    assert normalized.startswith("# 项目研究报告\n\n")
    assert "## 三、总体方案" in normalized
    assert normalized.index("## 三、总体方案") < normalized.index(
        "### （一）总体架构"
    )


def test_delivery_report_structure_does_not_map_h1_topic_to_capability_section() -> None:
    report = "\n".join(
        (
            "# 无人远程火力装备能力画像研究报告",
            "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征",
            "### ① 典型作战场景",
            "场景正文。",
            "## 第三层：能力图像与效能贡献层",
            "### ⑦ 装备能力图像",
            "画像正文。",
        )
    )

    normalized = _normalize_delivery_report_structure(report)

    assert normalized.startswith("# 无人远程火力装备能力画像研究报告\n\n")
    assert normalized.count("### ⑦ 装备能力图像") == 1
    assert normalized.index("## 第三层：能力图像与效能贡献层") < normalized.index(
        "### ⑦ 装备能力图像"
    )


def test_report_brief_cleaner_preserves_evidence_in_equipment_name() -> None:
    name = "低空可消耗察打一体无人突击平台续接目标证据链"
    assert _clean_report_brief_text(name, max_chars=100) == name


def test_report_capability_portrait_cleaner_preserves_governed_bullets() -> None:
    portrait = "\n".join(
        (
            "概述：形成可验证的装备能力画像。",
            "- 装备与技术实现：箱式发射平台与多模载荷。",
            "* 关键作战流程：1.任务装订；2.平台进入；3.受控交战；4.毁伤评估。",
        )
    )

    cleaned = _clean_report_capability_portrait(portrait)

    assert "- 装备与技术实现：" in cleaned
    assert "* 关键作战流程：" in cleaned


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


class _SwarmProgressProbeProvider(_WinningHarnessProbeProvider):
    def __init__(self) -> None:
        self._winning_progress_callback = None

    def set_winning_progress_callback(self, callback) -> None:
        self._winning_progress_callback = callback

    def analyze_winning_mechanism(self, payload: dict) -> dict:
        if self._winning_progress_callback is not None:
            self._winning_progress_callback(
                {
                    "event_type": "swarm_planned",
                    "agent_id": "winning_swarm_controller",
                    "wave_count": 3,
                    "dynamic_instance_budget": 12,
                }
            )
            self._winning_progress_callback(
                {
                    "event_type": "specialist_spawned",
                    "agent_id": "frontier_equipment_miner",
                    "wave": 1,
                    "hypothesis_id": "hypothesis-probe-1",
                    "merge_target": "S2",
                }
            )
            self._winning_progress_callback(
                {
                    "event_type": "swarm_gate_evaluated",
                    "agent_id": "winning_swarm_controller",
                    "swarm_summary": {
                        "policy_id": "winning_swarm_quality_v1",
                        "waves": [{"wave": 1, "status": "completed"}],
                        "candidate_count": 1,
                        "finalists": [
                            {
                                "hypothesis_id": "hypothesis-probe-1",
                                "status": "finalist",
                            }
                        ],
                    },
                }
            )
        return super().analyze_winning_mechanism(payload)


class _ConvergenceProbeProvider(_SwarmProgressProbeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.convergence_calls = 0

    def converge_discovery_outputs(self, payload: dict) -> dict:
        self.convergence_calls += 1
        result = super().converge_discovery_outputs(payload)
        result["probe_model_convergence"] = True
        return result


class _FailedSwarmGateProbeProvider(_SwarmProgressProbeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.draft_report_calls = 0

    def analyze_winning_mechanism(self, payload: dict) -> dict:
        if self._winning_progress_callback is not None:
            self._winning_progress_callback(
                {
                    "event_type": "swarm_gate_evaluated",
                    "agent_id": "winning_swarm_controller",
                    "swarm_summary": {
                        "policy_id": "winning_swarm_dynamic_v2",
                        "candidate_count": 2,
                        "finalists": [],
                        "portfolio_quality_gate": {
                            "passed": False,
                            "direction_count": 2,
                            "direct_combat_equipment_count": 2,
                            "distinct_direct_equipment_family_count": 2,
                            "preferred_distinct_direct_equipment": 5,
                            "issues": [
                                "only 2 distinct direct equipment families"
                            ],
                        },
                    },
                }
            )
        return _WinningHarnessProbeProvider.analyze_winning_mechanism(
            self, payload
        )

    def draft_report(self, payload: dict) -> str:
        self.draft_report_calls += 1
        return super().draft_report(payload)


class _CodexMetaReplanProbeProvider(_WinningHarnessProbeProvider):
    provider_kind = "codex_cli"

    def __init__(self) -> None:
        self.blueprint_payloads: list[dict] = []

    def design_discovery_blueprint(self, payload: dict) -> dict:
        self.blueprint_payloads.append(dict(payload))
        return {}

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


class _WeaponBaselineTimeoutProvider(_WinningHarnessProbeProvider):
    def run_baseline_agent(self, request):
        if request.agent.agent_id == "weapon_equipment":
            raise RuntimeError("Codex CLI timed out after external interruption")
        return super().run_baseline_agent(request)


class _AllBaselineTimeoutProvider(_WinningHarnessProbeProvider):
    def run_baseline_agent(self, request):
        raise RuntimeError(
            f"{request.agent.agent_id} Codex CLI timed out after external interruption"
        )


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


def test_single_weapon_baseline_timeout_does_not_fail_the_research_run(
    tmp_path: Path,
) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=_WeaponBaselineTimeoutProvider(),
    ).run(
        mode="real",
        topic="不完备与不确定战场信息条件下精确打击研究",
        research_route="traditional_gap",
        run_id="weapon-baseline-soft-degradation",
        agent_ids=[
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        analyst_confirmed=True,
        max_rounds=1,
    )

    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    weapon_report = next(
        item
        for item in summary["worker_reports"]
        if item["agent_id"] == "weapon_equipment"
    )
    with sqlite3.connect(Path(result["run_dir"]) / "run.db") as connection:
        packet = json.loads(
            connection.execute(
                "SELECT payload_json FROM domain_objects "
                "WHERE object_type = 'BaselineFindingPacket' "
                "AND object_id = 'packet-weapon_equipment'"
            ).fetchone()[0]
        )
    event_types = {item["event_type"] for item in summary["trace_summary"]}

    assert result["status"] == "completed"
    assert weapon_report["status"] == "limited"
    assert weapon_report["stop_reason"] == "recoverable_baseline_unavailable"
    assert packet["payload_type"] == "baseline_availability_boundary_v1"
    assert packet["findings"] == []
    assert packet["evidence_ids"] == []
    assert packet["admission_status"] == "limited"
    assert "baseline_agent_limited" in event_types
    assert "agent_failure_handoff_ready" not in event_types


def test_all_baseline_timeouts_remain_a_hard_safety_failure(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="all baseline agents were unavailable"):
        DeepResearchRunner(
            project_root=ROOT,
            output_root=tmp_path / "runs",
            agent_config_path=CONFIG / "agents.yaml",
            preset_config_path=CONFIG / "presets.yaml",
            provider=_AllBaselineTimeoutProvider(),
        ).run(
            mode="real",
            topic="全体基线不可用边界验证",
            research_route="traditional_gap",
            run_id="all-baseline-hard-failure",
            agent_ids=[
                "combat_scenario",
                "weapon_equipment",
                "operational_employment",
            ],
            analyst_confirmed=True,
            max_rounds=1,
        )


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
    provider = _CodexMetaReplanProbeProvider()
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=provider,
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
    assert len(provider.blueprint_payloads) == 1
    assert provider.blueprint_payloads[0]["topic"] == "跨域线索触发对手动向复核"
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


def test_swarm_progress_events_are_persisted_into_round_summary(
    tmp_path: Path,
) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=_SwarmProgressProbeProvider(),
    ).run(
        mode="real",
        topic="弹性制胜机理 Agent 群持久化验证",
        research_route="new_winning_mechanism",
        run_id="swarm-progress-summary",
        agent_ids=[
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        analyst_confirmed=True,
        max_rounds=1,
        execution_profile_id="swarm_quality_v1",
    )

    run_dir = Path(result["run_dir"])
    summary = json.loads((run_dir / "round_summary.json").read_text(encoding="utf-8"))
    assert summary["winning_swarm"]["policy_id"] == "winning_swarm_quality_v1"
    assert summary["winning_swarm"]["candidate_count"] == 1
    assert summary["winning_swarm"]["finalists"] == [
        {
            "hypothesis_id": "hypothesis-probe-1",
            "status": "finalist",
        }
    ]
    event_types = [item["event_type"] for item in summary["trace_summary"]]
    assert "swarm_planned" in event_types
    assert "specialist_spawned" in event_types
    assert "swarm_gate_evaluated" in event_types
    trace_rows = [
        json.loads(line)["payload"]
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    winning_harness_event = next(
        item
        for item in trace_rows
        if item["event_type"] == "agent_harness_completed"
        and item["actor"] == "winning_mechanism"
    )
    assert len(winning_harness_event["payload"]["active_skill_ids"]) > 1
    session_rows = [
        json.loads(line)
        for line in (
            run_dir / "agent_sessions" / "winning_swarm_controller.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert any(row["event_type"] == "swarm_gate_evaluated" for row in session_rows)


def test_quality_swarm_uses_provider_convergence_instead_of_local_skip(
    tmp_path: Path,
) -> None:
    provider = _ConvergenceProbeProvider()
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=provider,
    ).run(
        mode="real",
        topic="质量蜂群跨分支收敛模型调用验证",
        research_route="new_winning_mechanism",
        run_id="quality-swarm-model-convergence",
        agent_ids=[
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
        analyst_confirmed=True,
        max_rounds=1,
        execution_profile_id="swarm_quality_v1",
    )

    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert provider.convergence_calls == 1
    assert summary["discovery_convergence"]["probe_model_convergence"] is True
    assert summary["discovery_convergence"].get("model_call_skipped") is not True


def test_dynamic_swarm_portfolio_gate_is_advisory_before_reporter_model_call(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "runs"
    run_id = "dynamic-swarm-gate-blocks-reporter"
    provider = _FailedSwarmGateProbeProvider()

    result = DeepResearchRunner(
            project_root=ROOT,
            output_root=output_root,
            agent_config_path=CONFIG / "agents.yaml",
            preset_config_path=CONFIG / "presets.yaml",
            provider=provider,
        ).run(
            mode="real",
            topic="动态制胜组合门失败时不得启动报告模型",
            research_route="new_winning_mechanism",
            run_id=run_id,
            agent_ids=[
                "international_situation",
                "combat_scenario",
                "weapon_equipment",
                "operational_employment",
            ],
            analyst_confirmed=True,
            max_rounds=1,
            execution_profile_id="winning_swarm_dynamic_v2",
        )

    assert provider.draft_report_calls == 1
    run_dir = output_root / run_id
    assert result["status"] == "completed"
    assert (run_dir / "report.md").exists()
    with sqlite3.connect(run_dir / "run.db") as connection:
        trace = [
            {
                "event_type": str(row[0]),
                "actor": str(row[1]),
                "payload": json.loads(str(row[2]) or "{}"),
            }
            for row in connection.execute(
                "SELECT event_type, actor, payload_json FROM trace_events"
            )
        ]
    assert any(item["event_type"] == "winning_portfolio_quality_advisory" for item in trace)


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
