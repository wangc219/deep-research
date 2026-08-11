from __future__ import annotations

import json

import pytest

from equipment_deep_research.agents.registry import AgentDef, AgentRegistry
from equipment_deep_research.domain.models import AuditResult, ResearchProblem
from equipment_deep_research.domain.messages import FINALIZE_TASK_ID, RunCheckpoint
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.orchestration.communication import AgentMessageEnvelope, OrchestrationMessageBus
from equipment_deep_research.orchestration.coverage import PresetPolicy
from equipment_deep_research.orchestration.planning import ResearchPlanner
from equipment_deep_research.orchestration.runner import (
    CLAIM_SOURCE_BINDING_MINIMUM,
    DeepResearchRunner,
    _claim_source_binding_summary,
    _is_report_delivery_only_resume,
    _promote_required_callbacks,
    _reconcile_final_audit_status,
    _winning_analysis_can_resume_s6_only,
    _winning_analysis_reusable_for_profile,
)
from equipment_deep_research.orchestration.subagents import SubagentPolicy, SubtaskCandidate


def _agent(agent_id: str, tags: list[str]) -> AgentDef:
    return AgentDef(agent_id, agent_id, "test", tags, [], {})


def test_planner_builds_map_reduce_nodes_for_selected_agents() -> None:
    policy = PresetPolicy({"new_winning_mechanism": ["threat", "scenario"]}, {}, {})
    graph = ResearchPlanner(policy).build(ResearchProblem("test"), [_agent("a", ["threat"]), _agent("b", ["scenario"])])
    maps = [item for item in graph.nodes if item.node_type == "baseline_map"]
    assert {item.target_agent_id for item in maps} == {"a", "b"}
    assert set(next(item for item in graph.nodes if item.node_type == "baseline_reduce").depends_on) == {item.node_id for item in maps}


def test_model_preference_is_reconciled_without_forcing_situation_agent() -> None:
    policy = PresetPolicy(
        {"traditional_gap": ["scenario", "equipment", "operation"]},
        {},
        {},
    )
    planner = ResearchPlanner(policy)
    candidates = [
        _agent("international_situation", ["situation", "threat"]),
        _agent("combat_scenario", ["scenario"]),
        _agent("weapon_equipment", ["equipment"]),
        _agent("operational_employment", ["operation"]),
    ]
    selected = planner.select_for_problem(
        ResearchProblem("传统装备差距评估", "traditional_gap"),
        candidates,
        preferred_agent_ids=["weapon_equipment", "operational_employment"],
    )
    assert {agent.agent_id for agent in selected} == {
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
    }


def test_model_preference_is_pruned_to_topic_minimum_sufficient_agents() -> None:
    policy = PresetPolicy(
        {"new_winning_mechanism": ["equipment", "operation"]},
        {},
        {},
    )
    planner = ResearchPlanner(policy)
    candidates = [
        _agent("international_situation", ["situation", "threat"]),
        _agent("combat_scenario", ["scenario"]),
        _agent("weapon_equipment", ["equipment"]),
        _agent("operational_employment", ["operation"]),
    ]

    selected = planner.select_for_problem(
        ResearchProblem(
            "探索无人智能集群条件下的新作战战法及装备需求",
            "new_winning_mechanism",
        ),
        candidates,
        preferred_agent_ids=[
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ],
    )

    assert {agent.agent_id for agent in selected} == {
        "weapon_equipment",
        "operational_employment",
    }


def test_bus_rejects_raw_session_payload_and_targets_messages() -> None:
    bus = OrchestrationMessageBus()
    with pytest.raises(ValueError, match="raw session"):
        bus.publish(AgentMessageEnvelope("bad", "handoff_ready", "a", "b", [], {"raw_messages": []}))
    with pytest.raises(ValueError, match="raw session"):
        bus.publish(
            AgentMessageEnvelope(
                "nested-bad",
                "handoff_ready",
                "a",
                "b",
                [],
                {"handoff": {"authorization": "Bearer hidden"}},
            )
        )
    envelope = AgentMessageEnvelope(
        "ok",
        "handoff_ready",
        "a",
        "winning",
        ["packet-1"],
        {"summary": "safe"},
        ["threat"],
        status="failed",
        return_node="baseline-wave-2",
    )
    bus.publish(envelope)
    assert len(bus.drain_for("winning", ["winning_mechanism"])) == 1
    assert bus.drain_for("equipment", ["equipment"]) == []
    assert envelope.to_plain()["status"] == "failed"
    assert envelope.to_plain()["return_node"] == "baseline-wave-2"


def test_subagent_requires_all_four_conditions() -> None:
    policy = SubagentPolicy()
    assert policy.evaluate(SubtaskCandidate(True, True, "BaselineFindingPacket", True)).spawn
    assert not policy.evaluate(SubtaskCandidate(False, True, "BaselineFindingPacket", True)).spawn


def test_dynamic_resume_does_not_reuse_failed_s6_as_completed_result() -> None:
    result = {
        "concept_directions": [{"name": f"装备{i}"} for i in range(5)],
        "winning_swarm": {
            "final_equipment_portfolio": [
                {"name": f"装备{i}"} for i in range(5)
            ],
            "portfolio_quality_gate": {"passed": True},
        },
        "s6_quality_gate_passed": False,
        "s6_quality_gate_failed": True,
    }

    assert not _winning_analysis_reusable_for_profile(
        result,
        execution_profile_id="winning_swarm_dynamic_v2",
    )
    assert _winning_analysis_can_resume_s6_only(
        result,
        execution_profile_id="winning_swarm_dynamic_v2",
    )


def test_dynamic_resume_reuses_only_fully_passed_s6_result() -> None:
    result = {
        "concept_directions": [{"name": f"装备{i}"} for i in range(5)],
        "winning_swarm": {
            "final_equipment_portfolio": [
                {"name": f"装备{i}"} for i in range(5)
            ],
            "portfolio_quality_gate": {"passed": True},
        },
        "s6_quality_gate_passed": True,
        "s6_quality_gate_failed": False,
    }

    assert _winning_analysis_reusable_for_profile(
        result,
        execution_profile_id="winning_swarm_dynamic_v2",
    )
    assert not _winning_analysis_can_resume_s6_only(
        result,
        execution_profile_id="winning_swarm_dynamic_v2",
    )


def test_checkpoint_loader_demotes_legacy_s6_failure_to_warnings(tmp_path) -> None:
    sessions_dir = tmp_path / "agent_sessions"
    sessions_dir.mkdir()
    persisted_issues = [
        "装备1：指标画像缺少公开基线与判退条件",
        "装备2：语义一致性检查未通过",
    ]
    result = {
        "concept_directions": [{"name": f"装备{i}"} for i in range(8)],
        "winning_swarm": {
            "final_equipment_portfolio": [
                {"name": f"装备{i}"} for i in range(8)
            ],
            "portfolio_quality_gate": {"passed": True},
        },
        "s6_quality_gate_passed": False,
        "s6_quality_gate_failed": True,
        "s6_quality_gate_issues": persisted_issues,
    }
    row = {"event_type": "model_checkpoint", "result": result}
    (sessions_dir / "winning_mechanism.jsonl").write_text(
        json.dumps(row, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    loaded = DeepResearchRunner._load_latest_core_agent_result(
        type("Workspace", (), {"sessions_dir": sessions_dir})(),
        "winning_mechanism",
    )

    assert loaded["s6_quality_gate_passed"] is True
    assert loaded["s6_quality_gate_failed"] is False
    assert loaded["s6_quality_gate_limited"] is True
    assert loaded["s6_quality_gate_issues"] == []
    assert set(persisted_issues) <= set(loaded["s6_quality_warnings"])
    assert _winning_analysis_reusable_for_profile(
        loaded,
        execution_profile_id="winning_swarm_dynamic_v2",
    )
    assert not _winning_analysis_can_resume_s6_only(
        loaded,
        execution_profile_id="winning_swarm_dynamic_v2",
    )


def test_checkpoint_loader_returns_failed_dynamic_s6_checkpoint_for_s6_only_resume(
    tmp_path,
) -> None:
    sessions_dir = tmp_path / "agent_sessions"
    sessions_dir.mkdir()
    result = {
        "concept_directions": [{"name": f"新制装备{i}"} for i in range(5)],
        "winning_swarm": {
            "final_equipment_portfolio": [
                {"name": f"新制装备{i}"} for i in range(5)
            ],
            "portfolio_quality_gate": {
                "passed": False,
                "direct_combat_main_body_passed": True,
                "capability_portrait_gate_passed": True,
            },
        },
        "s6_quality_gate_passed": False,
        "s6_quality_gate_failed": True,
        "s6_quality_gate_issues": ["S6画像待修复"],
    }
    (sessions_dir / "winning_mechanism.jsonl").write_text(
        json.dumps(
            {"event_type": "model_checkpoint", "result": result},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = DeepResearchRunner._load_latest_core_agent_result(
        type("Workspace", (), {"sessions_dir": sessions_dir})(),
        "winning_mechanism",
    )

    assert loaded["s6_quality_gate_failed"] is True
    assert _winning_analysis_can_resume_s6_only(
        loaded,
        execution_profile_id="winning_swarm_dynamic_v2",
    )


def test_checkpoint_loader_restores_truncated_dynamic_s6_portfolio(tmp_path) -> None:
    sessions_dir = tmp_path / "agent_sessions"
    sessions_dir.mkdir()
    prior_directions = [
        {
            "hypothesis_id": f"hypothesis-{index}",
            "name": f"远海反潜自主拦截鱼雷{index}",
        }
        for index in range(8)
    ]
    prior_result = {
        "concept_directions": prior_directions,
        "winning_swarm": {
            "final_equipment_portfolio": list(prior_directions),
            "portfolio_quality_gate": {"passed": True},
        },
        "s6_quality_gate_passed": False,
        "s6_quality_gate_failed": True,
        "s6_quality_gate_issues": ["三张卡待补"],
    }
    repaired_rows = [
        {
            "hypothesis_id": f"hypothesis-{index}",
            "name": f"远海反潜自主拦截鱼雷{index}",
            "repair_marker": "latest",
        }
        for index in range(5, 8)
    ]
    truncated_result = {
        "concept_directions": repaired_rows,
        "winning_swarm": {
            "final_equipment_portfolio": repaired_rows,
            "portfolio_quality_gate": {"passed": True},
        },
        "s6_quality_gate_passed": False,
        "s6_quality_gate_failed": True,
        "s6_quality_gate_issues": ["步骤置信度低于0.65，需要定向复核"],
    }
    rows = [
        {"event_type": "model_checkpoint", "result": prior_result},
        {"event_type": "model_checkpoint", "result": truncated_result},
    ]
    (sessions_dir / "winning_mechanism.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    loaded = DeepResearchRunner._load_latest_core_agent_result(
        type("Workspace", (), {"sessions_dir": sessions_dir})(),
        "winning_mechanism",
    )

    assert len(loaded["concept_directions"]) == 8
    assert len(loaded["winning_swarm"]["final_equipment_portfolio"]) == 8
    assert all(
        loaded["concept_directions"][index]["repair_marker"] == "latest"
        for index in range(5, 8)
    )
    assert loaded["s6_quality_gate_failed"] is False
    assert loaded["s6_quality_gate_passed"] is True
    assert loaded["s6_quality_gate_limited"] is True
    assert loaded["s6_quality_gate_issues"] == []
    assert "步骤置信度低于0.65，需要定向复核" in loaded[
        "s6_quality_warnings"
    ]
    assert not _winning_analysis_can_resume_s6_only(
        loaded,
        execution_profile_id="winning_swarm_dynamic_v2",
    )


def test_domain_upsert_proposal_is_stable_per_content_and_versioned_on_change() -> None:
    approved = AuditResult(
        audit_id="audit-001",
        status="approved",
        checks={"report_quality": True},
        comments=[],
    )
    limited = AuditResult(
        audit_id="audit-001",
        status="limited",
        checks={"report_quality": False},
        comments=["待修复"],
    )

    first = DeepResearchRunner._domain_proposal("AuditResult", approved)
    repeated = DeepResearchRunner._domain_proposal("AuditResult", approved)
    updated = DeepResearchRunner._domain_proposal("AuditResult", limited)

    assert first.proposal_id == repeated.proposal_id
    assert first.idempotency_key == repeated.idempotency_key
    assert updated.proposal_id != first.proposal_id
    assert updated.idempotency_key != first.idempotency_key
    assert updated.payload["audit_id"] == "audit-001"


def test_claim_source_binding_allows_small_transparent_unbound_minority() -> None:
    rows = [
        {"claim": f"装备场景结论{index}", "public_urls": [f"https://example.test/{index}"]}
        for index in range(21)
    ]
    rows.extend(
        {"claim": f"待补来源的综合判断{index}", "public_urls": []}
        for index in range(5)
    )

    summary = _claim_source_binding_summary(
        rows,
        internal_reference_found=False,
    )

    assert CLAIM_SOURCE_BINDING_MINIMUM == 0.8
    assert summary["binding_rate"] == 0.807692
    assert summary["minimum_required"] == 0.8
    assert summary["unbound_claim_count"] == 5
    assert summary["unbound_claims"][0] == "待补来源的综合判断0"
    assert summary["passed"] is True


def test_claim_source_binding_still_blocks_internal_references() -> None:
    summary = _claim_source_binding_summary(
        [{"claim": "装备场景结论", "public_urls": ["https://example.test/source"]}],
        internal_reference_found=True,
    )

    assert summary["binding_rate"] == 1.0
    assert summary["passed"] is False


def test_report_gate_failure_resume_skips_completed_research_agents(tmp_path) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "report-only-resume")
    try:
        workspace.write_run_text(
            "report_failure.json",
            json.dumps(
                {
                    "status": "failed_quality_gate",
                    "report_written": True,
                    "resumable": True,
                }
            ),
        )
        checkpoint = RunCheckpoint(
            run_id="report-only-resume",
            checkpoint_id="checkpoint-report-only",
            round_index=1,
            budget_remaining={
                "baseline_tasks": 0,
                "finalize_tasks": 1,
                "rounds": 1,
            },
            topic="远海反潜",
            research_route="new_winning_mechanism",
            resolved_route="new_winning_mechanism",
            selected_agent_ids=["combat_scenario"],
            completed_task_ids=["baseline:combat_scenario"],
            pending_task_ids=[FINALIZE_TASK_ID],
            task_statuses={
                "baseline:combat_scenario": "completed",
                FINALIZE_TASK_ID: "pending",
            },
            status="running",
        )
        store = DomainStore()
        store.reports["report-001"] = object()  # type: ignore[assignment]
        store.audits["audit-001"] = object()  # type: ignore[assignment]
        store.stage_outputs["stage-L3"] = object()  # type: ignore[assignment]
        store.capability_images["cap-001"] = object()  # type: ignore[assignment]

        assert _is_report_delivery_only_resume(
            workspace=workspace,
            checkpoint=checkpoint,
            store=store,
            execution_profile_id="winning_swarm_dynamic_v2",
        )

        (workspace.run_dir / "report_failure.json").unlink()
        workspace.write_run_text(
            "report_quality_gate.json",
            json.dumps({"passed": True}),
        )
        workspace.write_run_text(
            "claim_source_binding.json",
            json.dumps({"passed": True}),
        )
        workspace.write_run_text(
            "branch_deliverables.json",
            json.dumps({"delivery_status": "complete"}),
        )
        store.audits["audit-001"] = AuditResult(
            audit_id="audit-001",
            status="limited",
            checks={"stage_gates_passed": False},
            comments=[],
        )
        assert _is_report_delivery_only_resume(
            workspace=workspace,
            checkpoint=checkpoint,
            store=store,
            execution_profile_id="winning_swarm_dynamic_v2",
        )

        incomplete = checkpoint.__class__(
            **{
                **checkpoint.__dict__,
                "completed_task_ids": [],
                "pending_task_ids": ["baseline:combat_scenario", FINALIZE_TASK_ID],
                "task_statuses": {
                    "baseline:combat_scenario": "pending",
                    FINALIZE_TASK_ID: "pending",
                },
            }
        )
        assert not _is_report_delivery_only_resume(
            workspace=workspace,
            checkpoint=incomplete,
            store=store,
            execution_profile_id="winning_swarm_dynamic_v2",
        )
    finally:
        workspace.close()


def test_authoritative_expert_gate_can_reconcile_historical_stage_diagnostic() -> None:
    audit = AuditResult(
        audit_id="audit-001",
        status="limited",
        checks={
            "stage_gates_passed": False,
            "confidence_ge_70": False,
            "expert_judge_passed": True,
            "coverage": True,
            "consistency": True,
            "round_limit": True,
            "source_materialization": True,
            "user_confirmation": True,
        },
        comments=[],
    )

    reconciled = _reconcile_final_audit_status(audit, optimized_v2=True)

    assert reconciled.status == "approved"
    assert reconciled.checks["stage_gates_passed"] is True
    assert reconciled.checks["confidence_ge_70"] is True


def test_required_callback_is_promoted_before_winning_analysis() -> None:
    scenario = _agent("combat_scenario", ["scenario"])
    equipment = _agent("weapon_equipment", ["equipment"])
    operation = _agent("operational_employment", ["operation"])
    registry = AgentRegistry(
        {
            scenario.agent_id: scenario,
            equipment.agent_id: equipment,
            operation.agent_id: operation,
        },
        "gpt-test",
    )
    blueprint = {
        "baseline_agent_plan": [
            {"agent_id": "combat_scenario", "mode": "required", "reason": "scenario"},
            {"agent_id": "weapon_equipment", "mode": "callback", "reason": "equipment gap"},
            {"agent_id": "operational_employment", "mode": "callback", "reason": "operation gap"},
        ]
    }

    selected, promoted = _promote_required_callbacks(
        selected_candidates=[scenario],
        discovery_blueprint=blueprint,
        registry=registry,
        required_tags=["scenario", "equipment", "operation"],
    )

    assert {item.agent_id for item in selected} == {
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
    }
    assert promoted == ["weapon_equipment", "operational_employment"]
    modes = {
        item["agent_id"]: item["mode"]
        for item in blueprint["baseline_agent_plan"]
    }
    assert modes["weapon_equipment"] == "required"
    assert modes["operational_employment"] == "required"
