from __future__ import annotations

import asyncio
import json

import pytest

from equipment_deep_research.agents.workflows.orchestrator import _compact_deep_dialogue_seed_payload
from equipment_deep_research.deep_runtime.capabilities import MCPDeclaration
from equipment_deep_research.deep_runtime.planner import inbound_from_payload
from equipment_deep_research.deep_runtime.provider_runtime import ProviderRuntime
from equipment_deep_research.deep_runtime.runner import run_planned_tools
from equipment_deep_research.deep_runtime.state import TurnState
from equipment_deep_research.deep_runtime.tool_registry import InProcessMCPAdapter, build_tool_registry
from equipment_deep_research.deep_runtime import loop as runtime_loop, tools as runtime_tools


async def make_state(*, budget=4, fail=False, command=""):
    calls = []
    checkpoints = []
    received = []

    async def search(arguments):
        calls.append(arguments)
        if fail:
            raise ValueError("adapter error password=private")
        return {"finding": "public observation", "api_key": "private", "text": "<think>hidden</think>"}

    async def deepen(state):
        received.append(_compact_deep_dialogue_seed_payload(state.payload))
        return {"visible_summary": ["research complete"]}

    registry = build_tool_registry(handlers={"deepen": deepen, "inspect_memory": deepen, "help": deepen})
    registry.register_mcp_declaration(MCPDeclaration(server_id="sources", transport="inproc", plugin_id="support"))
    adapter = InProcessMCPAdapter({"search": search})
    await registry.attach_mcp_adapter("sources", adapter, allowed_tools=["search"])

    async def provider(_agent, _prompt, payload, _schema, _tokens, *, phase=""):
        assert phase == "deep_research_support"
        assert "session_id" not in json.dumps(payload)
        return {"calls": [
            {"name": "author_s6", "arguments": {}},
            {"name": "mcp_sources_search", "arguments": {"query": "public question"}},
        ]}

    payload = {"question": command or "follow up", "session_id": "private-session",
               "working_memory": {"candidate_directions": [{"name": "candidate"}]},
               "checkpoint_callback": checkpoints.append}
    state = TurnState(host=object(), payload=payload, inbound=inbound_from_payload(payload),
                      plan=["deepen"], tool_registry=registry,
                      provider_runtime=ProviderRuntime(json_callback=provider), max_tool_calls=budget)
    return state, calls, checkpoints, received, adapter


def test_mounted_mcp_observations_reach_research_without_granting_s6():
    async def scenario():
        state, calls, checkpoints, received, adapter = await make_state()
        await run_planned_tools(state)
        assert calls == [{"query": "public question"}]
        assert state.completed_tools == ["mcp_sources_search", "deepen"]
        assert state.tool_call_count == 2
        assert "public observation" in json.dumps(received)
        assert "external_data_policy" in received[0]
        assert "private" not in json.dumps(received)
        assert "hidden" not in json.dumps(received)
        assert "public observation" in json.dumps(checkpoints)
        assert adapter.started  # The host owns the adapter across turns.
        await state.tool_registry.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("budget,command", [(1, ""), (4, "/memory"), (4, "/help")])
def test_support_preserves_domain_budget_and_read_only_commands(budget, command):
    async def scenario():
        state, calls, _, _, _ = await make_state(budget=budget, command=command)
        await run_planned_tools(state)
        assert calls == []
        assert state.tool_call_count == 1
        await state.tool_registry.close()

    asyncio.run(scenario())


def test_support_failure_is_advisory_and_research_still_runs():
    async def scenario():
        state, calls, checkpoints, received, _ = await make_state(fail=True)
        await run_planned_tools(state)
        assert len(calls) == 1
        assert state.completed_tools == ["deepen"]
        assert state.status == "completed"
        assert state.tool_call_count == 2
        assert "ValueError" in json.dumps(received)
        assert "private" not in json.dumps(checkpoints)
        await state.tool_registry.close()

    asyncio.run(scenario())


def test_independent_support_probes_run_concurrently_in_selection_order():
    async def scenario():
        active = 0
        peak = 0
        completed = []

        async def probe(arguments):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            completed.append(arguments["name"])
            active -= 1
            return {"finding": arguments["name"]}

        async def deepen(_state):
            return {"visible_summary": ["done"]}

        async def provider(_agent, _prompt, _payload, _schema, _tokens, *, phase=""):
            if phase == "deep_research_conduct":
                return {"intent": "deepen", "tools": ["deepen"]}
            if phase == "deep_research_support":
                return {
                    "calls": [
                        {"name": "mcp_sources_alpha", "arguments": {"name": "alpha"}},
                        {"name": "mcp_sources_beta", "arguments": {"name": "beta"}},
                    ]
                }
            return {}

        registry = build_tool_registry(handlers={"deepen": deepen})
        registry.register_mcp_declaration(
            MCPDeclaration(server_id="sources", transport="inproc", plugin_id="support")
        )
        await registry.attach_mcp_adapter(
            "sources", InProcessMCPAdapter({"alpha": probe, "beta": probe}),
            allowed_tools=["alpha", "beta"],
        )
        payload = {
            "question": "follow up",
            "working_memory": {"candidate_directions": [{"name": "candidate"}]},
        }
        state = TurnState(
            host=object(), payload=payload, inbound=inbound_from_payload(payload),
            plan=["deepen"], tool_registry=registry,
            provider_runtime=ProviderRuntime(json_callback=provider), max_tool_calls=4,
        )
        await run_planned_tools(state, policy=lambda _state: "deepen")
        assert peak == 2
        assert completed == ["alpha", "beta"]
        assert state.completed_tools == ["mcp_sources_alpha", "mcp_sources_beta", "deepen"]
        assert state.tool_call_count == 3
        await registry.close()

    asyncio.run(scenario())


def test_host_injected_registry_enters_main_loop_without_entering_model_context(monkeypatch):
    async def scenario():
        state, calls, _, _, _ = await make_state()
        phases = []

        async def provider(_agent, _prompt, payload, _schema, _tokens, *, phase=""):
            phases.append(phase)
            assert "tool_registry" not in payload
            if phase == "deep_research_conduct":
                return {"intent": "deepen", "tools": ["deepen"]}
            return {"calls": [{"name": "mcp_sources_search", "arguments": {"query": "public"}}]}

        async def deepen(turn):
            assert "tool_registry" not in turn.payload
            assert "public observation" in json.dumps(turn.payload["external_tool_observations"])
            return {"visible_summary": ["research complete"], "concept_directions": []}

        monkeypatch.setitem(runtime_tools.TOOL_HANDLERS, "deepen", deepen)
        result = await runtime_loop._run_deep_research_turn(object(), {
            "question": "follow up",
            "working_memory": {"candidate_directions": [{"name": "candidate"}]},
            "provider_runtime": ProviderRuntime(json_callback=provider),
            "tool_registry": state.tool_registry,
        })
        assert calls == [{"query": "public"}]
        assert "deep_research_conduct" in phases
        assert "deep_research_support" in phases
        assert result["visible_summary"] == ["research complete"]
        await state.tool_registry.close()

    asyncio.run(scenario())


def test_cancellation_during_support_never_runs_domain_action():
    async def scenario():
        state, _, _, received, _ = await make_state()
        entered = asyncio.Event()
        exited = asyncio.Event()

        async def blocking(_name, _arguments):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                exited.set()

        state.tool_registry.mcp_runtime("sources").adapter.call = blocking
        task = asyncio.create_task(run_planned_tools(state))
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert exited.is_set()
        assert received == []
        await state.tool_registry.close()

    asyncio.run(scenario())
