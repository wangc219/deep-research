"""研究配置目录和预览使用与执行器相同的领域注册表。"""

import pytest

from equipment_deep_research.domain.models import ResearchProblem
from platform_core.services.equipment_research_config import research_catalog, preview_research_agents


def test_catalog_contains_original_launch_options():
    catalog = research_catalog()
    assert {item["id"] for item in catalog["discovery_branches"]} == set("ABCDEFGH")
    assert {item["id"] for item in catalog["interaction_modes"]} == {"expert", "autonomous"}
    assert next(item["id"] for item in catalog["report_templates"] if item["default"]) == "project_argument_v1"
    assert len(catalog["routes"]) == 3
    assert "weapon_equipment" in {agent["agent_id"] for agent in catalog["agents"]}
    assert "api_key" not in str(catalog)


@pytest.mark.parametrize("branch", list("ABCDEFGH"))
def test_preview_preserves_explicit_branch_and_returns_registered_roles(branch):
    catalog = research_catalog()
    preview = preview_research_agents(ResearchProblem(topic="民用应急照明可靠性研究", discovery_branch=branch))
    assert preview["primary_branch"] == branch
    assert preview["selected_agent_ids"]
    assert set(preview["selected_agent_ids"]) <= {agent["agent_id"] for agent in catalog["agents"]}
    assert [item["agent_id"] for item in preview["plan"]] == preview["selected_agent_ids"]
