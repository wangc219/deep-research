from __future__ import annotations

import pytest

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.orchestration.communication import AgentMessageEnvelope, OrchestrationMessageBus
from equipment_deep_research.orchestration.coverage import PresetPolicy
from equipment_deep_research.orchestration.planning import ResearchPlanner
from equipment_deep_research.orchestration.subagents import SubagentPolicy, SubtaskCandidate


def _agent(agent_id: str, tags: list[str]) -> AgentDef:
    return AgentDef(agent_id, agent_id, "test", tags, [], {})


def test_planner_builds_map_reduce_nodes_for_selected_agents() -> None:
    policy = PresetPolicy({"new_winning_mechanism": ["threat", "scenario"]}, {}, {})
    graph = ResearchPlanner(policy).build(ResearchProblem("test"), [_agent("a", ["threat"]), _agent("b", ["scenario"])])
    maps = [item for item in graph.nodes if item.node_type == "baseline_map"]
    assert {item.target_agent_id for item in maps} == {"a", "b"}
    assert set(next(item for item in graph.nodes if item.node_type == "baseline_reduce").depends_on) == {item.node_id for item in maps}


def test_bus_rejects_raw_session_payload_and_targets_messages() -> None:
    bus = OrchestrationMessageBus()
    with pytest.raises(ValueError, match="raw session"):
        bus.publish(AgentMessageEnvelope("bad", "handoff_ready", "a", "b", [], {"raw_messages": []}))
    bus.publish(AgentMessageEnvelope("ok", "handoff_ready", "a", "winning", ["packet-1"], {"summary": "safe"}, ["threat"]))
    assert len(bus.drain_for("winning", ["winning_mechanism"])) == 1
    assert bus.drain_for("equipment", ["equipment"]) == []


def test_subagent_requires_all_four_conditions() -> None:
    policy = SubagentPolicy()
    assert policy.evaluate(SubtaskCandidate(True, True, "BaselineFindingPacket", True)).spawn
    assert not policy.evaluate(SubtaskCandidate(False, True, "BaselineFindingPacket", True)).spawn
