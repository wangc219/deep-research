from pathlib import Path

from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.orchestration.routes import RoutePolicyRegistry


ROOT = Path(__file__).parents[3]
CONFIG = ROOT / "configs/equipment_deep_research"


def test_route_profiles_create_expected_parallel_waves() -> None:
    agents = AgentRegistry.load(CONFIG / "agents.yaml")
    routes = RoutePolicyRegistry.load(CONFIG / "routes.yaml")
    selected = agents.select_agents(
        [
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
        ]
    )

    new_waves = routes.execution_waves("new_winning_mechanism", selected)
    assert [[agent.agent_id for agent in wave] for wave in new_waves] == [
        ["international_situation"],
        ["combat_scenario", "weapon_equipment"],
        ["operational_employment"],
    ]
    traditional_waves = routes.execution_waves("traditional_gap", selected)
    assert [[agent.agent_id for agent in wave] for wave in traditional_waves] == [
        ["international_situation"],
        ["combat_scenario", "weapon_equipment"],
        ["operational_employment"],
    ]
