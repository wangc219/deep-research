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

    innovation = guidance["innovative_capability_image"]
    assert "S6单装备能力画像作者" in innovation
    assert "敌方优势" in innovation and "直接战果" in innovation
    assert "核心技术" in innovation and "攻防交换" in innovation
    assert "攻防交换" in innovation
    assert "未来战场态势" in innovation
    assert "禁止按字符硬切" in innovation

    concision = guidance["capability_portrait_concision"]
    assert "每栏都以约400个有效中文字为中心" in concision
    assert "复杂因果尚未闭合时可适当略多" in concision
    assert "禁止按字符硬切" in concision
    assert "五栏合计通常约2000至2250字" in concision
    assert "完整句和完整逻辑优先" in concision
    assert "严禁为凑字复用跨栏句子" in concision
    assert "同一次Codex调用内完成取舍" in concision
    assert "低于360字时优先补足" in concision

    overview = guidance["capability_overview"]
    assert "短卡，不是研究报告摘要" in overview
    assert "只回答三个问题" in overview
    assert "战场上最关键的断点" in overview
    assert "本装备改变了什么" in overview
    assert "直接取得什么制胜结果" in overview
    assert "以约400个有效中文字为中心" in overview
    assert "传统关系被打破" in overview
    assert "对手被迫承担的代价" in overview
    assert "不要只写‘面向某场景、具备某功能、提升某指标’" in overview

    implementation = guidance["technology_implementation"]
    assert "真正决定装备能否实现的主攻关键技术" in implementation
    assert "最核心的技术痛点" in implementation
    assert "必要的落装位置、作用对象和关键耦合" in implementation
    assert "不要求展开完整实现路线" in implementation
    assert "不做零部件清单" in implementation

    process = guidance["operational_feasibility"]
    assert "真实未来战场" in process
    assert "能否打仗、怎样打胜仗" in process
    assert "步骤数量和叙述结构由装备专属交战因果链决定" in process
    assert "改变任务状态或作战结果" in process

    effects = guidance["capability_effects"]
    assert "新增了什么能力、产生了什么效果" in effects
    assert "普通指标提升与过去无法执行的新任务" in effects
    assert "直接战果和后续影响都来自本装备的实际作用" in effects
    assert "新质和颠覆必须体现为" in effects

    winning_logic = guidance["winning_logic"]
    assert "本装备最有价值的判断" in winning_logic
    assert "旧作战模式、交换关系重写与新制胜作战模式" in winning_logic
    assert "成立条件" in winning_logic
    assert "不把这些概念写成固定开场白或逐项提示词" in winning_logic


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
