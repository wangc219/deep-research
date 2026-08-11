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
    assert "新质装备论证卡" in innovation
    assert "创新断点、技术突破链和颠覆制胜机制" in innovation
    assert "技术瓶颈—核心原理—工程实现—作战能力变化" in innovation
    assert "战争交换关系" in innovation
    assert "十年后的战争为何需要它" in innovation
    assert "不是固定创新维度、关键词命中规则" in innovation

    concision = guidance["capability_portrait_concision"]
    assert "平均约100至150个中文字" in concision
    assert "允许某一栏因装备机理自然略短或略长" in concision
    assert "不设最低字数、不逐栏计数" in concision
    assert "不因篇幅偏差失败、重试或截断" in concision
    assert "同一次Codex调用内完成取舍" in concision
    assert "不以事后压缩补救首稿" in concision

    overview = guidance["capability_overview"]
    assert "短卡，不是研究报告摘要" in overview
    assert "只回答三个问题" in overview
    assert "战场上最关键的断点" in overview
    assert "本装备改变了什么" in overview
    assert "直接取得什么制胜结果" in overview
    assert "不要套用固定连接词、固定句式或最低字数" in overview

    implementation = guidance["technology_implementation"]
    assert "决定成败的一项核心机理" in implementation
    assert "落实到主装备构型并解除关键限制" in implementation
    assert "用最少的完整文字" in implementation
    assert "不做零部件清单" in implementation


def test_s6_innovation_guidance_is_wired_into_parallel_card_authoring() -> None:
    workflow_source = (
        PROJECT_ROOT
        / "src/equipment_deep_research/agents/workflows/winning.py"
    ).read_text(encoding="utf-8")

    assert workflow_source.count("+ INNOVATIVE_CAPABILITY_IMAGE_GUIDANCE") >= 2
    assert workflow_source.count("+ CAPABILITY_PORTRAIT_CONCISION_GUIDANCE") >= 5
    assert '"overview": "只保留一个传统能力瓶颈、一个创新断点和一个直接战果' in workflow_source
    assert '"technology_implementation": "只保留一条技术痛点—突破原理—工程实现—能力跃迁' in workflow_source
    assert '"operational_process": "只保留使任务状态发生变化的装备专属战斗动作链' in workflow_source
    assert '"capability_effects": "只保留相对基线新增能力和可验证战场结果' in workflow_source
    assert '"winning_logic": "只保留主要战争交换关系、新制胜机制和对手新增成本' in workflow_source
