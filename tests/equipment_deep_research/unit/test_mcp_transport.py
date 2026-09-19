from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest

import equipment_deep_research.deep_runtime.mcp_transport as mcp_transport_module
from equipment_deep_research.deep_runtime.mcp_transport import (
    HostMCPMount,
    MCPTransportConfig,
    PersistentMCPHost,
    ReloadingMCPHost,
    load_host_mcp_mounts,
)
from equipment_deep_research.deep_runtime.tool_registry import (
    InProcessMCPAdapter, MCPAdapterError, MCPToolDefinition, ToolRegistry,
)


@pytest.mark.parametrize("configuration", [
    {"transport": "unknown"}, {"transport": "stdio", "command": "python"},
    {"transport": "stdio", "command": sys.executable, "args": "script.py"},
    {"transport": "http", "url": "file:///etc/passwd"},
    {"transport": "http", "url": "http://user:password@localhost/mcp"},
    {"transport": "http", "url": "http://localhost/mcp", "command": sys.executable},
    {"transport": "http", "url": "http://localhost/mcp", "timeout": float("nan")},
    {"transport": "http", "url": "http://localhost/mcp", "timeout": True},
    {"transport": "http", "url": "http://localhost/mcp", "max_concurrent_calls": 0},
    {"transport": "http", "url": "http://localhost/mcp", "max_calls_per_turn": 0},
    {"transport": "http", "url": "http://localhost/mcp", "max_calls_per_turn": 1025},
    {"transport": "http", "url": "http://localhost/mcp", "max_result_bytes": 12},
    {"transport": "http", "url": "http://localhost/mcp", "max_result_depth": 0},
    {"transport": "http", "url": "http://localhost/mcp", "max_result_items": 0},
])
def test_transport_configuration_requires_explicit_host_settings(configuration):
    with pytest.raises(ValueError):
        MCPTransportConfig(**configuration)


def test_configuration_repr_never_contains_process_or_http_secrets():
    config = MCPTransportConfig("http", url="https://private.example/mcp?key=private",
                                headers={"Authorization": "Bearer private"})
    assert "private" not in repr(config)
    with pytest.raises(TypeError):
        config.headers["Authorization"] = "replacement"


def _registry(*server_ids):
    registry = ToolRegistry()
    for server_id in server_ids:
        registry.register_mcp_declaration({"server_id": server_id, "transport": "inproc"})
    return registry


def test_invalid_metadata_never_partially_mounts_capabilities():
    class InvalidAdapter(InProcessMCPAdapter):
        async def start(self):
            self.started = True
            return [MCPToolDefinition("echo"), object()]

    async def scenario():
        adapter = InvalidAdapter({})
        registry = _registry("host:echo")
        with pytest.raises(MCPAdapterError):
            await registry.attach_mcp_adapter("host:echo", adapter, allowed_tools=["echo"])
        assert registry.names == ()
        assert not adapter.started
        assert registry.mcp_runtime("host:echo").status == "failed"

    asyncio.run(scenario())


def test_replacing_adapter_closes_previous_connection_and_unmounts_old_tools():
    async def scenario():
        registry = _registry("host:echo")
        first = InProcessMCPAdapter({"old": lambda _args: "old"})
        second = InProcessMCPAdapter({"new": lambda _args: "new"})
        await registry.attach_mcp_adapter("host:echo", first, allowed_tools=["old"])
        registry.definitions()
        await registry.attach_mcp_adapter("host:echo", second, allowed_tools=["new"])
        assert not first.started
        assert registry.names == ("mcp_host:echo_new",)
        assert len(registry.definitions()) == 1
        assert await registry.execute_mcp("mcp_host:echo_new", {}) == "new"
        await registry.close()

    asyncio.run(scenario())


def test_shutdown_failure_does_not_skip_other_connections_or_expose_errors():
    class FailingAdapter(InProcessMCPAdapter):
        async def stop(self):
            raise RuntimeError("api_key=private")

    async def scenario():
        registry = _registry("host:first", "host:second")
        broken = FailingAdapter({"echo": lambda _args: "first"})
        healthy = InProcessMCPAdapter({"echo": lambda _args: "second"})
        await registry.attach_mcp_adapter("host:first", broken, allowed_tools=["echo"])
        await registry.attach_mcp_adapter("host:second", healthy, allowed_tools=["echo"])
        with pytest.raises(RuntimeError):
            await registry.close()
        assert not healthy.started
        assert registry.names == ()
        assert registry.mcp_runtime("host:first").status == "failed"
        assert registry.mcp_runtime("host:second").status == "stopped"
        assert "private" not in str(registry.public_payload())

    asyncio.run(scenario())


def test_cancelled_connection_attempt_cleans_up_and_never_marks_ready():
    class WaitingAdapter(InProcessMCPAdapter):
        async def start(self):
            self.started = True
            await asyncio.Event().wait()

    async def scenario():
        registry = _registry("host:echo")
        adapter = WaitingAdapter({})
        task = asyncio.create_task(registry.attach_mcp_adapter("host:echo", adapter))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not adapter.started
        assert registry.mcp_runtime("host:echo").status == "failed"
        assert registry.names == ()

    asyncio.run(scenario())


def test_concurrent_adapter_replacement_does_not_resurrect_old_tools():
    async def scenario():
        gate = asyncio.Event()
        started = asyncio.Event()

        class WaitingAdapter(InProcessMCPAdapter):
            async def start(self):
                started.set()
                await gate.wait()
                return await super().start()

        registry = _registry("host:echo")
        old = WaitingAdapter({"old": lambda _args: "old"})
        new = InProcessMCPAdapter({"new": lambda _args: "new"})
        first = asyncio.create_task(registry.attach_mcp_adapter("host:echo", old, allowed_tools=["old"]))
        await started.wait()
        second = asyncio.create_task(registry.attach_mcp_adapter("host:echo", new, allowed_tools=["new"]))
        await asyncio.sleep(0)
        assert registry.mcp_runtime("host:echo").adapter is old
        gate.set()
        await asyncio.gather(first, second)
        assert not old.started
        assert registry.names == ("mcp_host:echo_new",)
        assert registry.mcp_runtime("host:echo").adapter is new
        await registry.close()

    asyncio.run(scenario())


def test_shutdown_rejects_new_calls_before_transport_finishes_closing():
    from equipment_deep_research.deep_runtime.tool_registry import MCPNotEnabledError

    async def scenario():
        closing = asyncio.Event()
        gate = asyncio.Event()

        class SlowAdapter(InProcessMCPAdapter):
            async def stop(self):
                closing.set()
                await gate.wait()
                await super().stop()

        registry = _registry("host:echo")
        adapter = SlowAdapter({"echo": lambda _args: "echo"})
        await registry.attach_mcp_adapter("host:echo", adapter, allowed_tools=["echo"])
        task = asyncio.create_task(registry.stop_mcp("host:echo"))
        await closing.wait()
        with pytest.raises(MCPNotEnabledError):
            await registry.execute_mcp("mcp_host:echo_echo", {})
        gate.set()
        await task
        assert registry.names == ()

    asyncio.run(scenario())



def test_sdk_adapter_limits_concurrent_calls_on_owner_loop() -> None:
    class FakeResult:
        isError = False

        def __init__(self, value: int) -> None:
            self.value = value

        def model_dump(self, **_kwargs):
            return {"structuredContent": {"value": self.value}}

    class FakeSession:
        def __init__(self) -> None:
            self.inflight = 0
            self.max_inflight = 0

        async def call_tool(self, _tool_name, arguments):
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            try:
                await asyncio.sleep(0.02)
                return FakeResult(int(arguments["value"]))
            finally:
                self.inflight -= 1

    async def scenario() -> None:
        config = MCPTransportConfig(
            "http",
            url="https://mcp.example.invalid/service",
            max_concurrent_calls=1,
        )
        adapter = mcp_transport_module.SDKMCPAdapter(config)
        session = FakeSession()
        adapter._loop = asyncio.get_running_loop()
        adapter._owner = asyncio.current_task()
        adapter._session = session
        adapter._call_limiter = asyncio.Semaphore(config.max_concurrent_calls)

        results = await asyncio.gather(
            adapter.call("echo", {"value": 1}),
            adapter.call("echo", {"value": 2}),
            adapter.call("echo", {"value": 3}),
        )

        assert [item["structuredContent"]["value"] for item in results] == [1, 2, 3]
        assert session.max_inflight == 1

    asyncio.run(scenario())


def test_persistent_proxy_enforces_per_turn_call_budget() -> None:
    class Host:
        async def call(self, _server_id, _tool_name, arguments):
            return arguments["value"]

    async def scenario() -> None:
        proxy = mcp_transport_module._PersistentProxy(
            Host(), "host:echo", [MCPToolDefinition("echo")], max_calls=2
        )
        assert await proxy.call("echo", {"value": 1}) == 1
        assert await proxy.call("echo", {"value": 2}) == 2
        with pytest.raises(MCPAdapterError, match="per-turn call budget"):
            await proxy.call("echo", {"value": 3})

    asyncio.run(scenario())

def test_host_config_is_explicit_bounded_and_secret_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PRIVATE_MCP_TOKEN", "private-token-value")
    config_path = tmp_path / "mcp-host.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "deep-mcp-host-v1",
                "servers": [
                    {
                        "server_id": "host:research",
                        "transport": "http",
                        "url": "https://mcp.example.invalid/service",
                        "headers_from": {"Authorization": "PRIVATE_MCP_TOKEN"},
                        "allowed_tools": ["search", "search"],
                        "max_concurrent_calls": 2,
                        "max_calls_per_turn": 7,
                        "max_result_bytes": 4096,
                        "max_result_depth": 8,
                        "max_result_items": 512,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    mounts = load_host_mcp_mounts(config_path)

    assert len(mounts) == 1
    assert mounts[0].allowed_tools == ("search",)
    assert mounts[0].config.headers["Authorization"] == "private-token-value"
    assert mounts[0].config.max_concurrent_calls == 2
    assert mounts[0].config.max_calls_per_turn == 7
    assert mounts[0].config.max_result_bytes == 4096
    assert mounts[0].config.max_result_depth == 8
    assert mounts[0].config.max_result_items == 512
    assert "private-token-value" not in repr(mounts)


def test_host_config_rejects_symlinks_and_missing_secret_references(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.json"
    target.write_text('{"servers": []}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="unavailable"):
        load_host_mcp_mounts(link)

    missing = tmp_path / "missing-secret.json"
    missing.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "server_id": "host:research",
                        "transport": "http",
                        "url": "https://mcp.example.invalid/service",
                        "headers_from": {"Authorization": "ENV_DOES_NOT_EXIST_123"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unavailable environment"):
        load_host_mcp_mounts(missing)


def test_reloading_host_public_snapshot_does_not_start_transport(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp-host.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "deep-mcp-host-v1",
                "servers": [
                    {
                        "server_id": "host:echo",
                        "transport": "stdio",
                        "command": sys.executable,
                        "args": ["/does/not/need/to/exist/until-mounted.py"],
                        "allowed_tools": ["echo"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    host = ReloadingMCPHost(config_path)

    public = host.public_payload()

    assert public["status"] == "configured"
    assert public["servers"] == [
        {
            "server_id": "host:echo",
            "transport": "stdio",
            "allowed_tools": ["echo"],
                "limits": {
                    "max_concurrent_calls": 4,
                    "max_calls_per_turn": 64,
                    "max_result_bytes": 262144,
                "max_result_depth": 16,
                "max_result_items": 4096,
            },
        }
    ]
    assert host._current._thread is None
    asyncio.run(host.close())


def test_persistent_host_bounds_mcp_results_before_returning_to_agent_loop(monkeypatch) -> None:
    class LargeResultAdapter:
        def __init__(self, _config) -> None:
            self.connected = False

        def is_connected(self) -> bool:
            return self.connected

        async def start(self):
            self.connected = True
            return [MCPToolDefinition("echo")]

        async def call(self, _name, _arguments):
            return {"content": "x" * 2000}

        async def stop(self) -> None:
            self.connected = False

    monkeypatch.setattr(mcp_transport_module, "SDKMCPAdapter", LargeResultAdapter)
    mount = HostMCPMount(
        "host:echo",
        MCPTransportConfig(
            "http",
            url="https://mcp.example.invalid/service",
            max_result_bytes=1024,
        ),
        ("echo",),
    )

    async def scenario() -> None:
        host = PersistentMCPHost((mount,))
        registry = ToolRegistry()
        try:
            await host.mount_registry(registry)
            with pytest.raises(MCPAdapterError, match="size limit"):
                await registry.execute_mcp("mcp_host:echo_echo", {})
        finally:
            await host.close()

    asyncio.run(scenario())


def test_persistent_host_rejects_deep_or_wide_mcp_results(monkeypatch) -> None:
    class DeepResultAdapter:
        def __init__(self, _config) -> None:
            self.connected = False

        def is_connected(self) -> bool:
            return self.connected

        async def start(self):
            self.connected = True
            return [MCPToolDefinition("echo")]

        async def call(self, _name, _arguments):
            return {"a": {"b": {"c": "too deep"}}}

        async def stop(self) -> None:
            self.connected = False

    monkeypatch.setattr(mcp_transport_module, "SDKMCPAdapter", DeepResultAdapter)
    mount = HostMCPMount(
        "host:echo",
        MCPTransportConfig(
            "http",
            url="https://mcp.example.invalid/service",
            max_result_depth=2,
        ),
        ("echo",),
    )

    async def scenario() -> None:
        host = PersistentMCPHost((mount,))
        registry = ToolRegistry()
        try:
            await host.mount_registry(registry)
            with pytest.raises(MCPAdapterError, match="depth limit"):
                await registry.execute_mcp("mcp_host:echo_echo", {})
        finally:
            await host.close()

    asyncio.run(scenario())


def test_persistent_host_reconnects_after_bounded_backoff(monkeypatch) -> None:
    class FlakyAdapter:
        attempts = 0

        def __init__(self, _config) -> None:
            self.connected = False

        def is_connected(self) -> bool:
            return self.connected

        async def start(self):
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise MCPAdapterError("temporary handshake failure")
            self.connected = True
            return [MCPToolDefinition("echo")]

        async def call(self, _name, arguments):
            return {"echo": dict(arguments)}

        async def stop(self) -> None:
            self.connected = False

    monkeypatch.setattr(mcp_transport_module, "SDKMCPAdapter", FlakyAdapter)
    mount = HostMCPMount(
        "host:echo",
        MCPTransportConfig("http", url="https://mcp.example.invalid/service"),
        ("echo",),
    )

    async def scenario() -> None:
        host = PersistentMCPHost((mount,))
        try:
            with pytest.raises(MCPAdapterError, match="temporary"):
                await host.mount_registry(ToolRegistry())
            with pytest.raises(MCPAdapterError, match="backoff"):
                await host.mount_registry(ToolRegistry())
            await asyncio.sleep(0.55)
            registry = ToolRegistry()
            await host.mount_registry(registry)
            assert await registry.execute_mcp(
                "mcp_host:echo_echo", {"value": "recovered"}
            ) == {"echo": {"value": "recovered"}}
            assert FlakyAdapter.attempts == 2
            await host.unmount_registry(registry)
            host._adapters["host:echo"].connected = False
            replacement = ToolRegistry()
            await host.mount_registry(replacement)
            assert FlakyAdapter.attempts == 3
            assert await replacement.execute_mcp(
                "mcp_host:echo_echo", {"value": "reconnected"}
            ) == {"echo": {"value": "reconnected"}}
        finally:
            await host.close()

    asyncio.run(scenario())
