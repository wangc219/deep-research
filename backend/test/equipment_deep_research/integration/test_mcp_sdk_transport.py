from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import sys

import httpx
import pytest

from equipment_deep_research.deep_runtime.mcp_transport import (
    HostMCPMount, MCPTransportConfig, PersistentMCPHost, ReloadingMCPHost, SDKMCPAdapter,
    mounted_mcp_transports,
)
from equipment_deep_research.deep_runtime.tool_registry import (
    MCPAdapterError, MCPNotEnabledError, ToolRegistry,
)


SERVER = Path(__file__).parents[1] / "fixtures" / "mcp_loopback_server.py"


def _registry(transport="stdio"):
    registry = ToolRegistry()
    registry.register_mcp_declaration({"server_id": "local:echo", "transport": transport})
    return registry


def _stdio_config():
    return MCPTransportConfig("stdio", command=sys.executable, args=(str(SERVER),), timeout=5)


def test_real_stdio_handshake_allowlist_call_and_child_shutdown():
    async def scenario():
        registry = _registry()
        mount = HostMCPMount("local:echo", _stdio_config(), ("echo",))
        async with mounted_mcp_transports(registry, [mount]):
            assert registry.names == ("mcp_local:echo_echo",)
            result = await registry.execute_mcp("mcp_local:echo_echo", {"text": "first\nsecond"})
            assert result["structuredContent"]["echo"] == "first\nsecond"
            child_pid = result["structuredContent"]["pid"]
            assert registry.mcp_runtime("local:echo").status == "ready"
        assert registry.mcp_runtime("local:echo").status == "stopped"
        assert registry.names == ()
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)

    asyncio.run(scenario())


def test_real_stdio_call_timeout_and_cancellation_keep_owner_closable():
    async def scenario():
        adapter = SDKMCPAdapter(_stdio_config())
        await adapter.start()
        try:
            adapter.config = replace(adapter.config, timeout=0.1)
            with pytest.raises(MCPAdapterError, match="timed out"):
                await adapter.call("echo", {"text": "slow", "delay": 1})
            adapter.config = replace(adapter.config, timeout=5)
            task = asyncio.create_task(adapter.call("echo", {"text": "cancelled", "delay": 10}))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            result = await adapter.call("echo", {"text": "still connected"})
            assert result["structuredContent"]["echo"] == "still connected"
            with pytest.raises(MCPAdapterError, match="returned an error"):
                await adapter.call("fail", {})
        finally:
            await asyncio.wait_for(adapter.stop(), timeout=5)
        with pytest.raises(MCPNotEnabledError):
            await adapter.call("echo", {})

    asyncio.run(scenario())


def test_real_http_handshake_call_and_session_cleanup():
    async def scenario():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(SERVER), "--http", "--port", str(port),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for _attempt in range(100):
                    if process.returncode is not None:
                        pytest.fail("local MCP HTTP fixture exited before readiness")
                    try:
                        await client.get(f"http://127.0.0.1:{port}/mcp", timeout=0.1)
                        break
                    except httpx.HTTPError:
                        await asyncio.sleep(0.05)
                else:
                    pytest.fail("local MCP HTTP fixture did not start")
            registry = _registry("http")
            mount = HostMCPMount("local:echo", MCPTransportConfig("http", url=f"http://127.0.0.1:{port}/mcp", timeout=5), ("echo",))
            async with mounted_mcp_transports(registry, [mount]):
                result = await registry.execute_mcp("mcp_local:echo_echo", {"text": "HTTP"})
                assert result["structuredContent"]["echo"] == "HTTP"
            assert registry.mcp_runtime("local:echo").status == "stopped"
        finally:
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_stalled_stdio_handshake_reaps_child_and_does_not_leak_future(tmp_path, cancel):
    async def scenario():
        errors = []
        asyncio.get_running_loop().set_exception_handler(lambda _loop, context: errors.append(context))
        pid_file = tmp_path / "child.pid"
        config = MCPTransportConfig("stdio", command=sys.executable,
            args=(str(SERVER), "--handshake-delay", "10", "--pid-file", str(pid_file)),
            timeout=5 if cancel else 0.8)
        adapter = SDKMCPAdapter(config)
        task = asyncio.create_task(adapter.start())
        for _attempt in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else (TimeoutError, MCPAdapterError)):
            await asyncio.wait_for(task, timeout=5)
        child_pid = int(pid_file.read_text(encoding="ascii"))
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
        await adapter.stop()
        assert errors == []

    asyncio.run(scenario())


def test_sdk_context_shutdown_failure_is_observable_without_raw_details(monkeypatch):
    from contextlib import asynccontextmanager
    from mcp.client import stdio

    original = stdio.stdio_client

    @asynccontextmanager
    async def failing_close(*args, **kwargs):
        async with original(*args, **kwargs) as streams:
            yield streams
        raise RuntimeError("api_key=private-upstream-secret")

    monkeypatch.setattr(stdio, "stdio_client", failing_close)

    async def scenario():
        errors = []
        asyncio.get_running_loop().set_exception_handler(lambda _loop, context: errors.append(context))
        registry = _registry()
        await registry.attach_mcp_adapter("local:echo", SDKMCPAdapter(_stdio_config()), allowed_tools=["echo"])
        with pytest.raises(MCPAdapterError, match="shutdown failed") as exception:
            await registry.close()
        assert "private" not in str(exception.value)
        assert registry.mcp_runtime("local:echo").status == "failed"
        assert registry.names == ()
        assert errors == []

    asyncio.run(scenario())


def test_persistent_host_reuses_one_sdk_connection_across_turn_registries():
    async def scenario():
        mount = HostMCPMount("host:echo", _stdio_config(), ("echo",))
        # The declaration's transport is a host concern; use the same ID with
        # an explicit host mount so no plugin metadata can create this pool.
        host = PersistentMCPHost((mount,))
        registry_a = ToolRegistry()
        registry_b = ToolRegistry()
        try:
            await asyncio.gather(host.mount_registry(registry_a), host.mount_registry(registry_b))
            assert len(host._adapters) == 1
            first = await registry_a.execute_mcp("mcp_host:echo_echo", {"text": "turn-a"})
            second = await registry_b.execute_mcp("mcp_host:echo_echo", {"text": "turn-b"})
            assert first["structuredContent"]["echo"] == "turn-a"
            assert second["structuredContent"]["echo"] == "turn-b"
            await host.unmount_registry(registry_a)
            still_alive = await registry_b.execute_mcp("mcp_host:echo_echo", {"text": "after-a"})
            assert still_alive["structuredContent"]["echo"] == "after-a"
        finally:
            await host.close()
        assert host._adapters == {}
        assert host._closed
        with pytest.raises(MCPNotEnabledError):
            await registry_b.execute_mcp("mcp_host:echo_echo", {})

    asyncio.run(scenario())


def test_hot_reload_keeps_active_generation_until_its_turn_releases(tmp_path):
    config_path = tmp_path / "mcp-host.json"

    def write_config(timeout):
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "deep-mcp-host-v1",
                    "servers": [
                        {
                            "server_id": "host:echo",
                            "transport": "stdio",
                            "command": sys.executable,
                            "args": [str(SERVER)],
                            "timeout": timeout,
                            "allowed_tools": ["echo"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    async def scenario():
        write_config(5)
        host = ReloadingMCPHost(config_path)
        registry_a = ToolRegistry()
        registry_b = ToolRegistry()
        try:
            await host.mount_registry(registry_a)
            first = await registry_a.execute_mcp("mcp_host:echo_echo", {"text": "old"})
            old_pid = first["structuredContent"]["pid"]

            # A different timeout changes the transport generation.  The
            # first registry remains leased to the old SDK session while a
            # new turn mounts the replacement pool.
            write_config(4)
            await host.mount_registry(registry_b)
            second = await registry_b.execute_mcp("mcp_host:echo_echo", {"text": "new"})
            new_pid = second["structuredContent"]["pid"]
            assert new_pid != old_pid
            still_old = await registry_a.execute_mcp(
                "mcp_host:echo_echo", {"text": "old-still-live"}
            )
            assert still_old["structuredContent"]["pid"] == old_pid

            await host.unmount_registry(registry_a)
            for _attempt in range(100):
                try:
                    os.kill(old_pid, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("retired MCP generation did not stop after its final lease")

            live = await registry_b.execute_mcp("mcp_host:echo_echo", {"text": "new-live"})
            assert live["structuredContent"]["pid"] == new_pid
        finally:
            await host.close()

    asyncio.run(scenario())


def test_persistent_host_close_rejects_new_mounts_and_stops_owner_thread():
    async def scenario():
        host = PersistentMCPHost((HostMCPMount("host:echo", _stdio_config(), ("echo",)),))
        registry = ToolRegistry()
        await host.mount_registry(registry)
        owner_thread = host._thread
        assert owner_thread is not None and owner_thread.is_alive()
        await asyncio.gather(host.close(), host.close())
        assert not owner_thread.is_alive()
        with pytest.raises(MCPAdapterError, match="closed"):
            await host.mount_registry(ToolRegistry())

    asyncio.run(scenario())
