from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.agents.prompts import BaselinePromptBuilder
from equipment_deep_research.agents.workflows.runtime import runtime_messages
from equipment_deep_research.agents.runtime_profiles import build_codex_runtime_profile
from equipment_deep_research.domain.messages import TaskEnvelope
from equipment_deep_research.domain.models import BaselineFindingPacket, WorkingCheckpoint
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.harness.checkpoint import CheckpointManager
from equipment_deep_research.harness.compaction import ContextCompactor, estimate_tokens
from equipment_deep_research.harness.context import (
    ContextPack,
    ContextProjector,
    _dependency_handoff,
    compact_packet_handoff,
)
from equipment_deep_research.harness.optimizations import apply_quick_optimizations
from equipment_deep_research.harness.scheduler import DiscoveryScheduler
from equipment_deep_research.agents.provider import FakeAgentProvider
from equipment_deep_research.domain.store import TraceStore
from equipment_deep_research.tools.permissions import ToolAuthorizationPolicy


def _task() -> TaskEnvelope:
    return TaskEnvelope("task", "run", 1, None, "winning", [], "research", [], [], [], [], ["ResearchProblem", "BaselineFindingPacket"], [], {}, "stage", "L1")


def _agent() -> AgentDef:
    return AgentDef("winning", "Winning", "test", ["winning_mechanism"], [], {"visible_sections": ["baseline_packets"], "hide_other_agent_raw_sessions": True}, object_read_scopes=["ResearchProblem", "BaselineFindingPacket"])


def test_projector_only_exposes_structured_handoffs() -> None:
    store = DomainStore()
    # Empty storage still proves no raw-session section can enter the projection.
    pack = ContextProjector().project(_task(), _agent(), store)
    assert "raw_sessions" not in pack.sections
    assert set(pack.sections) == {"task", "baseline_packets"}


def test_checkpoint_merge_preserves_open_questions() -> None:
    checkpoint = WorkingCheckpoint("cp", "winning", 1, open_questions=["q1"])
    updated = CheckpointManager().update(checkpoint, status="active", open_questions=["q1", "q2"], next_actions=["search"])
    assert updated.open_questions == ["q1", "q2"]
    assert updated.status == "active"


def test_compaction_is_deterministic() -> None:
    pack = ContextPack("agent", {"task": {"id": "t"}, "findings": [{"evidence_ids": ["ev-1"], "open_questions": ["q1"]}] * 30})
    result_a, record_a = ContextCompactor().compact(pack, token_budget=120)
    result_b, record_b = ContextCompactor().compact(pack, token_budget=120)
    assert result_a.context_hash == result_b.context_hash
    assert record_a == record_b
    assert estimate_tokens(result_a) <= 120
    assert "ev-1" in str(result_a.sections)


def test_cross_agent_handoff_is_bounded_and_drops_excess_context() -> None:
    packet = BaselineFindingPacket(
        packet_id="packet-source",
        agent_id="international_situation",
        capability_tags=[f"tag-{index}" for index in range(20)],
        topic_focus="topic",
        findings=["f" * 600 for _ in range(12)],
        evidence_ids=[f"ev-{index}" for index in range(30)],
        confidence=0.82,
        coverage_notes=[],
        open_questions=["q" * 400 for _ in range(8)],
        handoff_summary="s" * 900,
        checkpoint="done",
        limitations=["l" * 400 for _ in range(8)],
        payload={
            f"field-{index}": ["v" * 700 for _ in range(12)]
            for index in range(20)
        },
    )

    handoff = compact_packet_handoff(packet)

    assert len(handoff["handoff_summary"]) <= 521
    assert len(handoff["key_findings"]) == 5
    assert all(len(item) <= 361 for item in handoff["key_findings"])
    assert len(handoff["payload"]) == 10
    assert all(len(items) == 6 for items in handoff["payload"].values())
    assert len(handoff["evidence_ids"]) == 14
    assert len(handoff["limitations"]) == 3
    assert len(handoff["open_questions"]) == 3


def test_minimal_dependency_handoff_keeps_explicit_lineage_fields() -> None:
    packet = BaselineFindingPacket(
        packet_id="packet-source",
        agent_id="combat_scenario",
        capability_tags=["scenario"],
        topic_focus="topic",
        findings=["任务链受压后打击闭环延迟"],
        evidence_ids=["ev-1"],
        confidence=0.8,
        coverage_notes=[],
        open_questions=[],
        handoff_summary="场景结论",
        checkpoint="done",
    )

    handoff = _dependency_handoff(
        packet,
        target_agent_id="weapon_equipment",
        minimal=True,
    )

    assert handoff["agent_id"] == "combat_scenario"
    assert handoff["packet_id"] == "packet-source"
    assert handoff["source"] == "combat_scenario"
    assert handoff["handoff_version"] == "2.0"
    assert set(handoff) >= {
        "decisions",
        "context_delta",
        "evidence_refs",
        "uncertainties",
    }
    assert "requested_next_action" not in handoff


def test_minimal_dependency_handoff_prefers_consumer_fields() -> None:
    projected = _dependency_handoff(
        BaselineFindingPacket(
            packet_id="packet-source",
            agent_id="combat_scenario",
            capability_tags=["scenario"],
            topic_focus="topic",
            findings=["场景判断"],
            evidence_ids=["ev-1"],
            confidence=0.8,
            coverage_notes=[],
            open_questions=[],
            handoff_summary="场景摘要",
            checkpoint="done",
            payload={
                "historical_background": "低优先级背景",
                "scenario_breakpoint": "任务断点",
                "phase_constraint": "阶段约束",
                "unrelated_catalog": "不应优先传递",
                "risk_boundary": "风险边界",
                "evidence_boundary": "证据边界",
            },
        ),
        target_agent_id="weapon_equipment",
        minimal=True,
    )

    keys = set(projected["context_delta"])
    assert "scenario_breakpoint" in keys
    assert "phase_constraint" in keys
    assert len(keys) <= 5


def test_non_s1_s6_runtime_card_drops_registry_prose() -> None:
    agent = AgentDef(
        "weapon_equipment",
        "武器装备",
        "装备基线与能力差距",
        ["equipment"],
        ["search_sources", "create_evidence_card", "compare_equipment_capability"],
        {},
        skills=[
            {
                "name": "装备分析",
                "steps": ["长步骤"],
                "allowed_tools": ["search_sources"],
                "quality_gates": ["证据可追溯"],
            }
        ],
        research_policy={"required_outputs": ["完整基线"], "internal_rule": "不要重复"},
        output_contract={"name": "baseline_finding_packet", "properties": ["payload"]},
    )
    runtime = build_codex_runtime_profile(
        "weapon_equipment",
        agent=agent,
        payload={
            "execution_profile_id": "swarm_quality_v1",
            "discovery_blueprint": {
                "primary_branch": "B",
                "secondary_branches": ["F"],
            },
        },
        phase="evidence_analysis",
        compact=True,
    )

    assert "research_policy" not in runtime
    assert "output_contract" not in runtime
    assert runtime["skill"] == "装备分析"
    assert runtime["discovery_branches"][0]["code"] == "B"
    assert "methodology" not in runtime
    assert "quality_gates" in runtime


def test_cross_agent_handoff_drops_prescriptive_follow_up_language() -> None:
    packet = BaselineFindingPacket(
        packet_id="packet-source",
        agent_id="combat_scenario",
        capability_tags=["scenario"],
        topic_focus="topic",
        findings=["决定性边界是目标同一性与任务更新链闭合。"],
        evidence_ids=["ev-1"],
        confidence=0.8,
        coverage_notes=[],
        open_questions=[
            "后续应重点补充数据链资料。",
            "公开材料是否能够证明断续链路下的重关联精度？",
        ],
        handoff_summary=(
            "决定性边界是目标同一性与任务更新链闭合。"
            "装备与技术优先级应围绕跨域状态接口和降级C2展开。"
            "下一步应把证据重点放在数据链公开材料上。"
        ),
        checkpoint="done",
        payload={
            "assessment": "公开资料仅证明体系概念，未证明闭环指标。",
            "next_action": "后置Agent必须继续核验更新时间窗。",
        },
    )

    handoff = _dependency_handoff(
        packet,
        target_agent_id="weapon_equipment",
        minimal=True,
    )
    serialized = str(handoff)

    assert handoff["summary"] == "决定性边界是目标同一性与任务更新链闭合。"
    assert handoff["uncertainties"] == [
        "公开材料是否能够证明断续链路下的重关联精度？"
    ]
    assert "下一步应" not in serialized
    assert "优先级应" not in serialized
    assert "后置Agent必须" not in serialized
    assert "requested_next_action" not in handoff


def test_scheduler_rejects_undeclared_shared_and_incremental_context(
    tmp_path: Path,
) -> None:
    agent = AgentDef(
        "isolated",
        "Isolated",
        "test",
        ["equipment"],
        [],
        {"visible_sections": [], "token_budget": 2000},
    )
    scheduler = DiscoveryScheduler(
        run_id="run",
        run_dir=tmp_path / "run",
        provider=FakeAgentProvider(),
        store=DomainStore(),
        trace=TraceStore(),
        shared_context={
            "discovery_blueprint": {"primary_branch": "B"},
            "structured_query_brief": {"mission": "bounded"},
            "raw_sessions": ["must-not-leak"],
            "_pipeline_agent_ids": ["other-agent"],
        },
    )
    scheduler.source_index.recommend = lambda *_: []
    scheduler.source_index.recommend_shared = lambda *_: []
    scheduler.knowledge_index.recommend = lambda *_: [
        {"summary": "must-not-leak-without-policy"}
    ]
    try:
        context, _, _ = scheduler._build_agent_context(
            agent=agent,
            topic="topic",
            research_route="traditional_gap",
            recall_request=None,
        )
    finally:
        scheduler.close()

    assert context.sections["discovery_blueprint"]["primary_branch"] == "B"
    assert context.sections["structured_query_brief"]["mission"] == "bounded"
    assert "raw_sessions" not in context.sections
    assert "_pipeline_agent_ids" not in context.sections
    assert "incremental_knowledge" not in context.sections


def test_compact_assignment_drops_framework_and_unknown_context() -> None:
    agent = AgentDef(
        "isolated",
        "Isolated",
        "test",
        ["equipment"],
        ["search_sources"],
        {"visible_sections": []},
        research_policy={"internal_rule": "must-not-repeat"},
    )

    prompt = BaselinePromptBuilder().build(
        agent=agent,
        route="traditional_gap",
        task={"topic": "topic"},
        context={
            "task": {"topic": "topic"},
            "structured_query_brief": {"mission": "bounded"},
            "raw_sessions": ["must-not-leak"],
            "_execution_priority": "critical",
        },
        compact_runtime=True,
    )

    assert prompt["context"] == {
        "task": {"topic": "topic"},
        "structured_query_brief": {"mission": "bounded"},
    }
    assert "research_policy" not in prompt
    assert "allowed_tools" not in prompt


def test_non_codex_runtime_has_no_codex_skill_instruction() -> None:
    messages = runtime_messages(
        SimpleNamespace(provider_kind="responses"),
        "isolated",
        "只输出严格JSON。",
        {"topic": "topic"},
        phase="analysis",
    )

    assert "$js-" not in str(messages[0].content)
    assert "没有可继承的其他Agent会话" in str(messages[0].content)
    assert set(messages[1].content) == {"agent_runtime", "task_input"}


def test_runtime_defaults_are_idempotent_and_do_not_patch_authorization(
    monkeypatch,
) -> None:
    for key in (
        "EQUIPMENT_DR_MAXIMIZE_AGENT_PARALLELISM",
        "EQUIPMENT_DR_EVIDENCE_MATERIALIZE_CONCURRENCY",
        "EQUIPMENT_DR_EVIDENCE_PREWARM_CONCURRENCY",
        "EQUIPMENT_DR_BASELINE_PREFETCH_WORKERS",
    ):
        monkeypatch.delenv(key, raising=False)
    authorize = ToolAuthorizationPolicy.authorize

    first = apply_quick_optimizations(verbose=False)
    second = apply_quick_optimizations(verbose=False)

    assert first["applied_defaults"]
    assert second["applied_defaults"] == []
    assert first["authorization_cache"] is False
    assert ToolAuthorizationPolicy.authorize is authorize
