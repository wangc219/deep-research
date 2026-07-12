from __future__ import annotations

from equipment_deep_research.agents.registry import AgentDef, AgentRegistry
from equipment_deep_research.domain.models import RecallRequest
from equipment_deep_research.orchestration.recall import RecallCoordinator


def test_recall_routes_by_capability_and_is_bounded() -> None:
    registry = AgentRegistry({"threat_agent": AgentDef("threat_agent", "Threat", "", ["threat"], [], {})}, "gpt-5.5")
    recall = RecallRequest("r-1", "L1", None, "threat", "need evidence", ["sources"], "L1", "high")
    coordinator = RecallCoordinator(max_per_target=1)
    assert coordinator.route(recall, registry, ["threat_agent"], round_index=1).target_agent_id == "threat_agent"
    assert coordinator.route(recall, registry, ["threat_agent"], round_index=2).status == "limited"
