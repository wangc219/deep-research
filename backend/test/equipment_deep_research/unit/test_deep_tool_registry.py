from __future__ import annotations

import asyncio

import pytest

from equipment_deep_research.deep_runtime.capabilities import MCPDeclaration
from equipment_deep_research.deep_runtime.tool_registry import (
    DeclarationOnlyMCPAdapter,
    InProcessMCPAdapter,
    MCPNotEnabledError,
    MCPToolDefinition,
    ToolRegistry,
    build_tool_registry,
)


def test_builtin_registry_is_stable_and_exposes_schemas() -> None:
    async def inspect(_state):
        return {"ok": True}

    registry = build_tool_registry(handlers={"deepen": inspect, "help": inspect})

    assert registry.names == ("deepen", "help")
    assert [item["name"] for item in registry.get_definitions()] == [
        "deepen",
        "help",
    ]
    assert registry.get("deepen").source == "builtin"  # type: ignore[union-attr]


def test_mcp_declaration_is_inert_without_explicit_adapter() -> None:
    async def should_not_run(_name, _arguments):
        raise AssertionError("declaration-only MCP must never invoke a transport")

    registry = ToolRegistry()
    registry.register_mcp_declaration(
        MCPDeclaration(server_id="intel:evidence", transport="stdio", plugin_id="intel")
    )

    runtime = registry.mcp_runtime("intel:evidence")
    assert runtime is not None
    assert runtime.status == "declaration_only"
    assert registry.get("mcp_intel:evidence_search") is None
    assert registry.public_payload()["mcp_servers"][0]["execution_status"] == "declaration_only"


def test_explicit_in_process_adapter_mounts_only_allowed_tools() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def search(arguments):
        calls.append(("search", dict(arguments)))
        return {"rows": ["candidate"]}

    adapter = InProcessMCPAdapter(
        {
            "search": search,
            "secret": MCPToolDefinition(
                name="secret",
                description="must remain private",
            ),
        }
    )
    registry = ToolRegistry()
    registry.register_mcp_declaration(
        MCPDeclaration(server_id="intel:evidence", transport="inproc", plugin_id="intel")
    )

    mounted = asyncio.run(
        registry.attach_mcp_adapter(
            "intel:evidence",
            adapter,
            allowed_tools=["search"],
        )
    )

    assert [item.name for item in mounted] == ["mcp_intel:evidence_search"]
    assert registry.mcp_runtime("intel:evidence").status == "ready"  # type: ignore[union-attr]
    result = asyncio.run(
        registry.execute_mcp(
            "mcp_intel:evidence_search",
            {"query": "radar"},
        )
    )
    assert result == {"rows": ["candidate"]}
    assert calls == [("search", {"query": "radar"})]
    assert registry.get("mcp_intel:evidence_secret") is None


def test_mcp_stop_unmounts_tools_and_calls_adapter_stop() -> None:
    adapter = InProcessMCPAdapter({"probe": lambda _arguments: {"ok": True}})
    registry = ToolRegistry()
    registry.register_mcp_declaration(
        MCPDeclaration(server_id="intel:probe", transport="inproc", plugin_id="intel")
    )
    asyncio.run(
        registry.attach_mcp_adapter(
            "intel:probe", adapter, allowed_tools=["probe"]
        )
    )

    asyncio.run(registry.stop_mcp("intel:probe"))

    assert registry.get("mcp_intel:probe_probe") is None
    assert registry.mcp_runtime("intel:probe").status == "stopped"  # type: ignore[union-attr]
    with pytest.raises(KeyError):
        asyncio.run(registry.execute_mcp("mcp_intel:probe_probe", {}))


def test_declaration_only_adapter_is_explicitly_non_executable() -> None:
    adapter = DeclarationOnlyMCPAdapter()
    with pytest.raises(MCPNotEnabledError):
        asyncio.run(adapter.call("search", {}))

