from __future__ import annotations

import asyncio

import pytest

from equipment_deep_research.agents.provider import (
    AgentRunRequest,
    ResponsesAgentProvider,
)
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.contracts.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)
from equipment_deep_research.providers.base import (
    ProviderFinalTurn,
    ProviderStreamEvent,
    ProviderToolCall,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider


def _agent(agent_id: str) -> AgentDef:
    return AgentDef(
        agent_id,
        agent_id,
        "research",
        [agent_id],
        ["search_sources"],
        {"visible_sections": ["upstream_handoffs"]},
        output_contract={"name": "baseline_finding_packet", "properties": []},
        research_policy={"search_tracks": ["capability"], "target_source_count": 4},
    )


def _knowledge_tool(calls: list[str]) -> ToolDefinition:
    async def query_kb(
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolResult:
        del context
        calls.append(call.call_id)
        return ToolResult(call.call_id, "bounded knowledge result")

    return ToolDefinition(
        name="query_kb",
        description="Retrieve authorized enterprise knowledge when needed",
        input_schema={
            "type": "object",
            "required": ["query_text"],
            "properties": {"query_text": {"type": "string"}},
        },
        handler=query_kb,
    )


@pytest.mark.parametrize(
    "agent_id",
    ["weapon_equipment", "technology_radar", "case_research"],
)
def test_baseline_divergence_and_reference_lanes_do_not_receive_knowledge_tools(
    monkeypatch: pytest.MonkeyPatch,
    agent_id: str,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_MAX_BATCHES", "1")
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text="discovery"))],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=(
                            '{"findings":["完成"],"confidence":0.8,'
                            '"open_questions":[],"handoff_summary":"完成",'
                            '"contradictions":[],"source_claims":[],'
                            '"analysis_sections":{}}'
                        )
                    )
                )
            ],
        ]
    )
    host = ResponsesAgentProvider(backend)
    calls: list[str] = []
    host.set_research_knowledge_tools([_knowledge_tool(calls)])

    host.run_baseline_agent(
        AgentRunRequest(
            f"run-{agent_id}",
            _agent(agent_id),
            "topic",
            "traditional_gap",
            {},
        )
    )

    assert len(backend.inputs) == 2
    assert [
        tuple(tool.name for tool in tools)
        for _, tools, _ in backend.inputs
    ] == [(), ()]
    assert calls == []


@pytest.mark.parametrize(
    ("phase", "payload", "expected_tools"),
    [
        (
            "winning_s6_parallel_card_01_module_technology_implementation",
            {"candidate_weapon": {"name": "test"}},
            ("query_kb",),
        ),
        (
            "winning_s6_parallel_card_01_module_technology_implementation",
            {
                "candidate_weapon": {"name": "test"},
                "portrait_module_attempt": 2,
            },
            (),
        ),
        (
            "winning_s6_parallel_card_01_module_technology_implementation_retry",
            {"candidate_weapon": {"name": "test"}},
            (),
        ),
        (
            "winning_s6_parallel_card_01_module_technology_implementation_repair",
            {"candidate_weapon": {"name": "test"}},
            (),
        ),
        (
            "winning_s6_parallel_card_01_module_overview",
            {"candidate_weapon": {"name": "test"}},
            (),
        ),
    ],
)
def test_s6_routes_knowledge_tool_only_to_first_technology_generation(
    phase: str,
    payload: dict[str, object],
    expected_tools: tuple[str, ...],
) -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    host = ResponsesAgentProvider(backend)
    calls: list[str] = []
    host.set_research_knowledge_tools([_knowledge_tool(calls)])

    result = asyncio.run(
        host._run_core_text(
            "winning_s6_image",
            "system",
            payload,
            3200,
            phase=phase,
            output_schema={"ok": "boolean"},
        )
    )

    assert result == '{"ok":true}'
    assert len(backend.inputs) == 1
    assert tuple(tool.name for tool in backend.inputs[0][1]) == expected_tools
    visible_prompt = "\n".join(
        str(message.content) for message in backend.inputs[0][0]
    )
    if expected_tools:
        assert "仅是可选的事实核验工具" in visible_prompt
        assert "本次最多一次工具回合" in visible_prompt
        assert "不得据此收缩或淘汰候选" in visible_prompt
    else:
        assert "仅是可选的事实核验工具" not in visible_prompt
    assert calls == []


def test_s6_knowledge_miss_does_not_fail_or_trigger_another_tool_round() -> None:
    calls: list[str] = []

    async def no_match(
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolResult:
        del context
        calls.append(call.call_id)
        return ToolResult(
            call.call_id,
            "授权知识库未命中；继续开放推理并标注不确定性。",
            is_error=True,
        )

    tool = ToolDefinition(
        name="query_kb",
        description="Optional fact verification",
        input_schema={
            "type": "object",
            "required": ["query_text"],
            "properties": {"query_text": {"type": "string"}},
        },
        handler=no_match,
    )
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        tool_calls=[
                            ProviderToolCall(
                                "kb-call-1",
                                "query_kb",
                                {"query_text": "核验关键器件成熟度"},
                            )
                        ]
                    )
                )
            ],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(text='{"ok":true,"basis":"open_reasoning"}')
                )
            ],
        ]
    )
    host = ResponsesAgentProvider(backend)
    host.set_research_knowledge_tools([tool])

    result = asyncio.run(
        host._run_core_text(
            "winning_s6_image",
            "system",
            {"candidate_weapon": {"name": "test"}},
            3200,
            phase="winning_s6_parallel_card_01_module_technology_implementation",
            output_schema={"ok": "boolean", "basis": "string"},
        )
    )

    assert result == '{"ok":true,"basis":"open_reasoning"}'
    assert calls == ["kb-call-1"]
    assert len(backend.inputs) == 2
    assert tuple(tool.name for tool in backend.inputs[0][1]) == ("query_kb",)
    assert backend.inputs[1][1] == ()
    assert [message.role for message in backend.inputs[1][0]][-2:] == [
        "assistant",
        "tool",
    ]
