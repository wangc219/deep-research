from pathlib import Path

import pytest
import yaml

from equipment_deep_research.agents.designs import (
    AgentDesignRegistry,
    AgentDesignSpec,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_default_design_registry_covers_configured_agents() -> None:
    config = yaml.safe_load(
        (PROJECT_ROOT / "configs/equipment_deep_research/agents.yaml").read_text(
            encoding="utf-8"
        )
    )
    configured_ids = [row["agent_id"] for row in config["agents"]]

    registry = AgentDesignRegistry.load_default()

    registry.validate_agent_ids(configured_ids, allow_custom=False)
    assert set(configured_ids) == set(registry.all_agent_ids())


def test_design_registry_rejects_duplicate_agent_id() -> None:
    design = AgentDesignSpec("test_agent", "test")
    registry = AgentDesignRegistry([design])

    with pytest.raises(ValueError, match="duplicate agent design"):
        registry.register(design)


def test_design_registry_reports_missing_builtin_design() -> None:
    registry = AgentDesignRegistry()

    with pytest.raises(ValueError, match="winning_s6_image"):
        registry.validate_agent_ids(["winning_s6_image"], allow_custom=False)


def test_custom_agent_uses_extension_fallback() -> None:
    registry = AgentDesignRegistry.load_default()

    registry.validate_agent_ids(["custom.agent_01-v2"])


def test_provider_module_remains_a_small_compatibility_facade() -> None:
    provider_path = (
        PROJECT_ROOT
        / "src/equipment_deep_research/agents/provider.py"
    )
    source = provider_path.read_text(encoding="utf-8")

    assert len(source.splitlines()) < 100
    assert "winning_s1_opponent" not in source
    assert "_report_draft_quality_issues" not in source
    assert "_capability_direction_quality_issues" not in source


def test_s6_design_owns_capability_portrait_writing_guidance() -> None:
    guidance = (
        AgentDesignRegistry.load_default()
        .get("winning_s6_image")
        .prompt_guidance()
    )

    from equipment_deep_research.agents.dynamic_prompt_resources import load_dynamic_winning_prompt

    # 文案以 Markdown 资源为唯一来源；不再锁定已退役版本的逐句措辞。
    sections = {
        "innovative_capability_image": "system",
        "capability_portrait_concision": "system",
        "capability_overview": "S6_1",
        "technology_implementation": "S6_2",
        "operational_feasibility": "S6_3",
        "capability_effects": "S6_4",
        "winning_logic": "S6_5",
    }
    for key, section in sections.items():
        expected = load_dynamic_winning_prompt("S6", section=section)
        assert expected.strip(), (key, section)
        assert guidance[key] == expected, (key, section)
    assert "query_semantics" in guidance["innovative_capability_image"]
    assert "candidate_weapon" in guidance["innovative_capability_image"]
    assert "winning_logic_overview" in guidance["innovative_capability_image"]


def test_s6_guidance_and_compact_parallel_contract_are_both_wired() -> None:
    workflow_source = (
        PROJECT_ROOT
        / "src/equipment_deep_research/agents/workflows/winning.py"
    ).read_text(encoding="utf-8")
    authoring_source = (
        PROJECT_ROOT
        / "src/equipment_deep_research/agents/workflows/winning_flows/s6_authoring.py"
    ).read_text(encoding="utf-8")

    assert workflow_source.count("+ _s6_markdown_authoring_contract()") >= 1
    assert "_dynamic_s6_module_guidance" in authoring_source
    assert "_parallel_s6_card_instruction()" in authoring_source
    assert '"overview": "只保留一个传统能力瓶颈、一个创新断点和一个直接战果' in workflow_source
    assert '"technology_implementation": "只保留一条技术痛点—突破原理—工程实现—能力跃迁' in workflow_source
    assert '"operational_process": "只保留使任务状态发生变化的装备专属战斗动作链' in workflow_source
    assert '"capability_effects": "只保留相对基线新增能力和可验证战场结果' in workflow_source
    assert '"winning_logic": "只保留主要战争交换关系、新制胜机制和对手新增成本' in workflow_source
