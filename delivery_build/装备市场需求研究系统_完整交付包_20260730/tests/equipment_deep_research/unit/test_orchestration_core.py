from __future__ import annotations

import pytest

from equipment_deep_research.agents.registry import AgentDef, AgentRegistry
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.orchestration.communication import AgentMessageEnvelope, OrchestrationMessageBus
from equipment_deep_research.orchestration.coverage import PresetPolicy
from equipment_deep_research.orchestration.planning import ResearchPlanner
from equipment_deep_research.orchestration.runner import _promote_required_callbacks
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
