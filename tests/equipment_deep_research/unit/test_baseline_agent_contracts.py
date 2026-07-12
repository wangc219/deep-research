from pathlib import Path

from equipment_deep_research.agents.prompts import BaselinePromptBuilder
from equipment_deep_research.agents.registry import AgentRegistry


ROOT = Path(__file__).parents[3]


def test_default_agent_output_contracts_are_differentiated() -> None:
    registry = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml")
    expected = {
        "international_situation": {"situation_assessment", "threat_assessment", "strategic_pattern", "opponent_moves"},
        "combat_scenario": {"scenario_framework", "enemy_coa", "critical_timeline", "environment_constraints"},
        "weapon_equipment": {"current_parameters", "development_models", "technology_readiness", "capability_constraints"},
        "operational_employment": {"operational_constraints", "force_coordination", "coa", "lessons"},
    }
    for agent_id, required in expected.items():
        contract = registry.get(agent_id).output_contract
        assert isinstance(contract, dict)
        assert required <= set(contract["properties"])


def test_prompt_only_contains_local_context_and_contract() -> None:
    agent = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml").get("weapon_equipment")
    prompt = BaselinePromptBuilder().build(agent=agent, route="traditional_gap", task={"topic": "test"}, context={"evidence_index": ["ev-1"]})
    assert prompt["role"] == "武器装备"
    assert "raw_sessions" not in str(prompt)
    assert "current_parameters" in prompt["output_contract"]["properties"]
