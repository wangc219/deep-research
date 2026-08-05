from pathlib import Path

from equipment_deep_research.agents.prompts import BaselinePromptBuilder
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.agents.provider import AgentRunRequest, FakeAgentProvider
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.harness.context import ContextPackBuilder


ROOT = Path(__file__).parents[3]


def test_default_agent_output_contracts_are_differentiated() -> None:
    registry = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml")
    expected = {
        "international_situation": {"situation_assessment", "threat_assessment", "strategic_pattern", "opponent_moves"},
        "combat_scenario": {"scenario_framework", "enemy_coa", "critical_timeline", "environment_constraints"},
        "weapon_equipment": {
            "foreign_equipment_landscape",
            "current_parameters",
            "development_models",
            "technology_readiness",
            "capability_constraints",
            "expendable_decoy_electronic_attack_evidence",
            "counter_uas_interceptor_evidence",
            "defensive_countermeasure_options",
            "upgrade_requirements",
            "new_equipment_requirements",
            "verification_plan",
        },
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
    assert "国外装备能力" in prompt["role_guidance"]["analysis_chain"]
    assert "defensive_countermeasure_analysis" in {
        skill["name"] for skill in prompt["skills"]
    }


def test_weapon_equipment_policy_is_query_led_and_theme_examples_are_optional() -> None:
    agent = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml").get(
        "weapon_equipment"
    )
    policy = agent.research_policy
    theme_policy = policy["theme_policy"]

    assert "当前query始终优先" in theme_policy["query_precedence"]
    assert theme_policy["examples_non_exhaustive"] is True
    assert theme_policy["no_mandatory_coverage"] is True
    assert "先做Query大方向" in theme_policy["divergence_mode"]
    assert "项目功能" in theme_policy["project_function_rule"]
    assert "概念性工作名" in theme_policy["illustrative_name_rule"]
    assert "不能独立占用最终武器方向" in theme_policy["support_only_exclusion"]
    tracks = set(policy["search_tracks"])
    assert any(
        "Query优先的具体战斗打击型武器主题发散与舍弃" in track
        and "均为可选" in track
        for track in tracks
    )
    assert "五类非穷尽主题适用性筛选与舍弃理由" in policy[
        "required_outputs"
    ]
    assert "每个候选的项目功能与Query因果链" in policy["required_outputs"]


def test_situation_and_scenario_prompts_have_dedicated_business_guidance() -> None:
    registry = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml")
    builder = BaselinePromptBuilder()

    situation = builder.build(
        agent=registry.get("international_situation"),
        route="new_winning_mechanism",
        task={"topic": "test"},
        context={},
    )
    situation_guidance = situation["role_guidance"]
    assert "3至5个背景假设" in situation_guidance["output_contract_mapping"]["alternative_hypotheses"]
    assert "行为体-意图-能力三角验证" in situation_guidance["method"][1]
    assert "typed Packet" in situation_guidance["handoff_rule"]

    scenario = builder.build(
        agent=registry.get("combat_scenario"),
        route="new_winning_mechanism",
        task={"topic": "test"},
        context={},
    )
    scenario_guidance = scenario["role_guidance"]
    assert "2至3个候选场景" in scenario_guidance["output_contract_mapping"]["scenario_branches"]
    assert "五维评分" in scenario_guidance["method"][2]
    assert "背景假设ID" in scenario_guidance["handoff_rule"]


def test_default_agents_persist_every_required_analysis_section() -> None:
    registry = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml")
    provider = FakeAgentProvider()
    for agent in registry.enabled_baseline_agents():
        result = provider.run_baseline_agent(
            AgentRunRequest("run-1", agent, "低空无人机能力", "traditional_gap", {})
        )
        contract = agent.output_contract
        assert isinstance(contract, dict)
        assert set(contract["properties"]) <= set(result.packet.analysis_sections)
        assert all(result.packet.analysis_sections[name] for name in contract["properties"])
        assert result.packet.schema_version == "2.0"
        assert result.packet.payload_type
        assert set(contract["properties"]) <= set(result.packet.payload)
        result.packet.validate_for_submit()


def test_default_agents_have_differentiated_skills_and_research_policies() -> None:
    registry = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml")
    skill_sets = {
        agent.agent_id: {item["name"] for item in agent.skills}
        for agent in registry.enabled_baseline_agents()
    }
    assert len({frozenset(value) for value in skill_sets.values()}) == 6
    assert "threat_forecasting" in skill_sets["international_situation"]
    assert "scenario_engineering" in skill_sets["combat_scenario"]
    assert "equipment_osint" in skill_sets["weapon_equipment"]
    assert "coa_comparison" in skill_sets["operational_employment"]
    for agent in registry.enabled_baseline_agents():
        assert agent.research_policy["search_tracks"]
        assert agent.research_policy["target_source_count"] >= 7
        assert agent.research_policy["require_counter_evidence"] is True


def test_handoff_context_follows_situation_scenario_equipment_operation_flow() -> None:
    registry = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml")
    provider = FakeAgentProvider()
    builder = ContextPackBuilder()
    store = DomainStore()

    expected_upstream = {
        "international_situation": [],
        "combat_scenario": ["international_situation"],
        "weapon_equipment": ["international_situation", "combat_scenario"],
        "operational_employment": [
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
        ],
    }
    for agent_id in expected_upstream:
        agent = registry.get(agent_id)
        context = builder.build_for_baseline_agent(
            agent=agent,
            topic="低空无人集群威胁",
            research_route="new_winning_mechanism",
            store=store,
        )
        assert [
            item["agent_id"] for item in context.sections.get("upstream_handoffs", [])
        ] == expected_upstream[agent_id]
        assert "agent_harness" in context.sections
        result = provider.run_baseline_agent(
            AgentRunRequest(
                "run-flow",
                agent,
                "低空无人集群威胁",
                "new_winning_mechanism",
                context.sections,
            )
        )
        store.add_baseline_packet(result.packet)

    operational = store.baseline_packets["packet-operational_employment"]
    assert operational.analysis_sections["upstream_synthesis"]["consumed_agents"] == [
        "international_situation",
        "combat_scenario",
        "weapon_equipment",
    ]


def test_registry_parallelizes_independent_agents_before_synthesis() -> None:
    registry = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml")
    selected = registry.select_agents(
        [
            "operational_employment",
            "weapon_equipment",
            "international_situation",
            "combat_scenario",
        ]
    )
    assert [agent.agent_id for agent in registry.execution_order(selected)] == [
        "combat_scenario",
        "international_situation",
        "weapon_equipment",
        "operational_employment",
    ]
