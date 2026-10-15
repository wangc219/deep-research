from __future__ import annotations

from types import SimpleNamespace

import pytest

from platform_core.agents.toolkits import service as tool_service


def test_get_tool_metadata_includes_config_guide(monkeypatch):
    tool_service._metadata_cache.clear()

    fake_tool = SimpleNamespace(
        name="demo_tool",
        description="demo description",
        metadata={},
        args_schema=None,
    )
    fake_extra = SimpleNamespace(
        category="buildin",
        tags=["demo"],
        display_name="演示工具",
        config_guide="请先配置 DEMO_API_KEY",
    )

    monkeypatch.setattr(
        "platform_core.agents.toolkits.registry.get_all_tool_instances",
        lambda: [fake_tool],
    )
    monkeypatch.setattr(
        "platform_core.agents.toolkits.registry.get_all_extra_metadata",
        lambda: {"demo_tool": fake_extra},
    )

    result = tool_service.get_tool_metadata()

    assert result == [
        {
            "slug": "demo_tool",
            "name": "演示工具",
            "description": "demo description",
            "metadata": {},
            "args": [],
            "category": "buildin",
            "tags": ["demo"],
            "config_guide": "请先配置 DEMO_API_KEY",
        }
    ]

    tool_service._metadata_cache.clear()


@pytest.mark.asyncio
async def test_question_tool_is_available_without_explicit_tool_selection(monkeypatch):
    """澄清工具默认可用，并与配置中的同名工具去重。"""
    tools = [SimpleNamespace(name=name) for name in ("present_artifacts", "ask_user_question")]
    monkeypatch.setattr(tool_service, "get_tool_instances_by_category", lambda _: tools)
    monkeypatch.setattr("platform_core.agents.skills.runtime.resolve_skill_gated_tools", lambda _: [])

    result = await tool_service.resolve_configured_runtime_tools(SimpleNamespace(tools=[], mcps=[]))
    assert {tool.name for tool in result} == {"present_artifacts", "ask_user_question"}
    result = await tool_service.resolve_configured_runtime_tools(SimpleNamespace(tools=["ask_user_question"], mcps=[]))
    assert [tool.name for tool in result].count("ask_user_question") == 1
