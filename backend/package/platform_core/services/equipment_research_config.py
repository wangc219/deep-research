"""研究启动配置与 Agent 预览，复用领域注册表和发现蓝图。"""

from pathlib import Path

from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.orchestration.blueprints import (
    BRANCH_BLUEPRINTS,
    build_discovery_blueprint,
    winning_step_modes,
)
from equipment_deep_research.orchestration.coverage import load_preset_policy


def research_catalog() -> dict:
    """返回启动表单所需的公开配置，不包含模型凭据或运行数据。"""
    config_root = Path(__file__).resolve().parents[4] / "configs/equipment_deep_research"
    if not config_root.is_dir():
        config_root = Path("/app/configs/equipment_deep_research")
    registry = AgentRegistry.load(config_root / "agents.yaml")
    policy = load_preset_policy(config_root / "presets.yaml")
    route_names = {
        "new_winning_mechanism": "新制胜机理",
        "traditional_gap": "传统能力缺口",
        "war_case_learning": "局部战争案例",
    }
    return {
        "report_templates": [
            {
                "id": "project_argument_v1",
                "name": "项目论证五章",
                "description": "需求分析、项目画像、总体方案、关键技术与研制基础。",
                "default": True,
            },
            {
                "id": "three_layer_nine_item",
                "name": "三层九项",
                "description": "需求挖掘、技术攻关、能力图像与效能贡献结构。",
                "default": False,
            },
        ],
        "interaction_modes": [
            {"id": "expert", "name": "专家模式"},
            {"id": "autonomous", "name": "智能模式"},
        ],
        "discovery_branches": [
            {
                "id": code,
                "name": spec.name,
                "runtime_route": spec.route,
                "step_modes": [
                    {"step": step, "execution_mode": mode}
                    for step, mode in winning_step_modes(code, research_route=spec.route).items()
                ],
            }
            for code, spec in BRANCH_BLUEPRINTS.items()
        ],
        "routes": [
            {"id": route_id, "name": route_names.get(route_id, route_id), "required_tags": tags}
            for route_id, tags in policy.required_capability_tags.items()
        ],
        "agents": [
            {
                "agent_id": agent.agent_id,
                "display_name": agent.display_name,
                "description": agent.description,
                "capability_tags": agent.capability_tags,
            }
            for agent in registry.enabled_baseline_agents()
        ],
    }


def preview_research_agents(problem: ResearchProblem) -> dict:
    """按当前 Query 和分支预览系统默认角色，不创建研究任务。"""
    agents = research_catalog()["agents"]
    blueprint = build_discovery_blueprint(
        problem,
        available_agent_capabilities={agent["agent_id"]: agent["capability_tags"] for agent in agents},
    )
    names = {agent["agent_id"]: agent["display_name"] for agent in agents}
    plan = [
        {**item, "display_name": names.get(item["agent_id"], item["agent_id"])}
        for item in blueprint["baseline_agent_plan"]
        if item["mode"] in {"required", "reference"}
    ]
    return {
        "primary_branch": blueprint["primary_branch"],
        "branch_name": blueprint["branch_name"],
        "runtime_route": blueprint["runtime_route"],
        "selected_agent_ids": [item["agent_id"] for item in plan],
        "plan": plan,
        "callback_agent_ids": blueprint["callback_agent_ids"],
        "structured_query_brief": blueprint["structured_query_brief"],
    }
