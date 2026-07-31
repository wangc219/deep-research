from __future__ import annotations

from equipment_deep_research.agents.registry import AgentDef, AgentRegistry
from equipment_deep_research.domain.models import RecallRequest
from equipment_deep_research.orchestration.recall import RecallCoordinator
import asyncio


def test_recall_routes_by_capability_and_is_bounded() -> None:
    registry = AgentRegistry({"threat_agent": AgentDef("threat_agent", "Threat", "", ["threat"], [], {})}, "gpt-5.5")
    recall = RecallRequest("r-1", "L1", None, "threat", "need evidence", ["sources"], "L1", "high")
    coordinator = RecallCoordinator(max_per_target=1)
    assert coordinator.route(recall, registry, ["threat_agent"], round_index=1).target_agent_id == "threat_agent"
    assert coordinator.route(recall, registry, ["threat_agent"], round_index=2).status == "limited"


def test_routed_recall_executes_with_only_target_and_return_node() -> None:
    registry = AgentRegistry({"threat_agent": AgentDef("threat_agent", "Threat", "", ["threat"], [], {})}, "gpt-5.5")
    recall = RecallRequest("r-1", "L1", None, "threat", "need evidence", ["sources"], "L1", "high")
    coordinator = RecallCoordinator()
    routed = coordinator.route(recall, registry, ["threat_agent"], round_index=1)
    calls = []

    async def execute(agent_id: str, item: RecallRequest) -> list[str]:
        calls.append((agent_id, item.required_data, item.return_node))
        return ["packet-threat-r2"]

    completed = asyncio.run(coordinator.execute_pending(routed, execute))
    assert completed.status == "completed"
    assert completed.output_refs == ["packet-threat-r2"]
    assert calls == [("threat_agent", ["sources"], "L1")]
