"""Host-configured MCP SDK transports, independent of Agent Core.

Like nanobot's owned MCP connection, one task opens and closes SDK contexts.
Plugin declarations never construct these adapters or execute their commands.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from types import MappingProxyType
import sys
import threading
import time
from typing import Any, Literal
from urllib.parse import urlsplit

from equipment_deep_research.deep_runtime.tool_registry import (
    MCPAdapterError, MCPNotEnabledError, MCPToolDefinition, ToolRegistry,
)


@dataclass(frozen=True, slots=True)
class MCPTransportConfig:
    transport: Literal["stdio", "http"]
    command: str = field(default="", repr=False)
    args: tuple[str, ...] = field(default=(), repr=False)
    cwd: str | None = field(default=None, repr=False)
    env: Mapping[str, str] = field(default_factory=dict, repr=False)
    url: str = field(default="", repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    timeout: float = 20
    max_concurrent_calls: int = 4
    max_calls_per_turn: int = 64
    max_result_bytes: int = 256 * 1024
    max_result_depth: int = 16
    max_result_items: int = 4096

    def __post_init__(self):
        if not isinstance(self.timeout, (int, float)) or isinstance(self.timeout, bool) or not math.isfinite(self.timeout) or not 0 < self.timeout <= 120:
            raise ValueError("MCP timeout must be between 0 and 120 seconds")
        for label, value, low, high in (
            ("MCP max_concurrent_calls", self.max_concurrent_calls, 1, 32),
            ("MCP max_calls_per_turn", self.max_calls_per_turn, 1, 1024),
            ("MCP max_result_bytes", self.max_result_bytes, 1024, 4 * 1024 * 1024),
            ("MCP max_result_depth", self.max_result_depth, 1, 64),
            ("MCP max_result_items", self.max_result_items, 1, 100_000),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < low
                or value > high
            ):
                raise ValueError(f"{label} is outside the host limit")
        if self.transport == "stdio":
            executable = Path(self.command)
            if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
                raise ValueError("MCP command must be a host-selected executable with an absolute path")
            if self.url or self.headers:
                raise ValueError("stdio transport cannot include HTTP configuration")
            if self.cwd is not None and (not Path(self.cwd).is_absolute() or not Path(self.cwd).is_dir()):
                raise ValueError("MCP cwd must be an existing absolute directory")
        elif self.transport == "http":
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("MCP endpoint must be a host-selected HTTP(S) URL without embedded credentials")
            if self.command or self.args or self.env or self.cwd:
                raise ValueError("HTTP transport cannot include process configuration")
        else:
            raise ValueError("unsupported MCP transport")
        if isinstance(self.args, (str, bytes)) or not all(isinstance(value, str) for value in self.args):
            raise ValueError("MCP arguments must be strings")
        for values in (self.env, self.headers):
            if not all(isinstance(key, str) and isinstance(value, str) for key, value in values.items()):
                raise ValueError("MCP environment and headers must contain strings")
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "max_concurrent_calls", int(self.max_concurrent_calls))
        object.__setattr__(self, "max_calls_per_turn", int(self.max_calls_per_turn))
        object.__setattr__(self, "max_result_bytes", int(self.max_result_bytes))
        object.__setattr__(self, "max_result_depth", int(self.max_result_depth))
        object.__setattr__(self, "max_result_items", int(self.max_result_items))


def _bounded_mcp_result(value: Any, config: MCPTransportConfig) -> Any:
    remaining = [config.max_result_items]
    seen: set[int] = set()

    def project(item: Any, depth: int) -> Any:
        if depth > config.max_result_depth:
            raise MCPAdapterError("MCP result depth limit exceeded")
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        if isinstance(item, Mapping):
            marker = id(item)
            if marker in seen:
                raise MCPAdapterError("MCP result contains a recursive object")
            seen.add(marker)
            try:
                if len(item) > remaining[0]:
                    raise MCPAdapterError("MCP result item limit exceeded")
                remaining[0] -= len(item)
                projected: dict[str, Any] = {}
                for key, nested in item.items():
                    projected[str(key)[:512]] = project(nested, depth + 1)
                return projected
            finally:
                seen.discard(marker)
        if isinstance(item, (list, tuple)):
            marker = id(item)
            if marker in seen:
                raise MCPAdapterError("MCP result contains a recursive object")
            seen.add(marker)
            try:
                if len(item) > remaining[0]:
                    raise MCPAdapterError("MCP result item limit exceeded")
                remaining[0] -= len(item)
                return [project(nested, depth + 1) for nested in item]
            finally:
                seen.discard(marker)
        raise MCPAdapterError("MCP result is not JSON serializable")

    projected = project(value, 0)
    try:
        encoded = json.dumps(
            projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MCPAdapterError("MCP result is not JSON serializable") from exc
    if len(encoded) > config.max_result_bytes:
        raise MCPAdapterError("MCP result size limit exceeded")
    return projected


class SDKMCPAdapter:
    """Real stdio / Streamable HTTP adapter with an owning lifecycle task."""

    def __init__(self, config: MCPTransportConfig):
        self.config = config
        self._owner: asyncio.Task | None = None
        self._ready: asyncio.Future | None = None
        self._close_requested: asyncio.Event | None = None
        self._session: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._call_limiter: asyncio.Semaphore | None = None

    def _check_loop(self):
        if self._loop is not None and self._loop is not asyncio.get_running_loop():
            raise MCPAdapterError("MCP transport must remain on its owning event loop")

    def is_connected(self) -> bool:
        """Return owner-loop connection health without performing I/O."""

        self._check_loop()
        return bool(
            self._session is not None
            and self._owner is not None
            and not self._owner.done()
        )

    async def _own_connection(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamable_http_client
            import httpx

            async with AsyncExitStack() as stack:
                if self.config.transport == "stdio":
                    errlog = stack.enter_context(open(os.devnull, "w"))
                    params = StdioServerParameters(
                        command=self.config.command, args=list(self.config.args),
                        env=dict(self.config.env), cwd=self.config.cwd,
                    )
                    read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
                else:
                    client = await stack.enter_async_context(httpx.AsyncClient(
                        headers=dict(self.config.headers), timeout=self.config.timeout,
                        follow_redirects=False, trust_env=False,
                    ))
                    read, write, _session_id = await stack.enter_async_context(streamable_http_client(
                        self.config.url, http_client=client,
                    ))
                session = await stack.enter_async_context(ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=self.config.timeout),
                ))
                await session.initialize()
                definitions = []
                cursor = None
                seen_cursors = set()
                for _page in range(8):
                    result = await session.list_tools(cursor=cursor)
                    definitions.extend(MCPToolDefinition(tool.name, tool.description or "", tool.inputSchema)
                                       for tool in result.tools)
                    if len(definitions) > 64:
                        raise MCPAdapterError("MCP tool-count limit exceeded")
                    cursor = result.nextCursor
                    if not cursor:
                        break
                    if cursor in seen_cursors:
                        raise MCPAdapterError("MCP tool pagination did not advance")
                    seen_cursors.add(cursor)
                else:
                    raise MCPAdapterError("MCP tool-page limit exceeded")
                self._session = session
                self._call_limiter = asyncio.Semaphore(self.config.max_concurrent_calls)
                self._ready.set_result(tuple(definitions))
                await self._close_requested.wait()
        except BaseException as exc:
            if not self._ready.done():
                self._ready.set_exception(MCPAdapterError("MCP connection failed"))
            elif not isinstance(exc, asyncio.CancelledError):
                raise MCPAdapterError("MCP transport connection or shutdown failed") from None
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            self._session = None
            self._call_limiter = None

    async def start(self) -> Sequence[MCPToolDefinition]:
        self._check_loop()
        if self._owner is None or self._owner.done():
            self._loop = asyncio.get_running_loop()
            self._ready = self._loop.create_future()
            self._close_requested = asyncio.Event()
            self._owner = asyncio.create_task(self._own_connection(), name="mcp-transport-owner")
            self._owner.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        try:
            return await asyncio.wait_for(asyncio.shield(self._ready), timeout=self.config.timeout)
        except BaseException:
            await self.stop()
            # Retrieving a completed handshake exception prevents unobserved
            # future warnings when cancellation won the race with readiness.
            if self._ready.done() and not self._ready.cancelled():
                self._ready.exception()
            raise

    async def call(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        self._check_loop()
        if (
            self._session is None
            or self._owner is None
            or self._owner.done()
            or self._call_limiter is None
        ):
            raise MCPNotEnabledError("MCP transport is not connected")
        try:
            async with self._call_limiter:
                result = await asyncio.wait_for(
                    self._session.call_tool(tool_name, arguments=dict(arguments)),
                    timeout=self.config.timeout,
                )
            if result.isError:
                raise MCPAdapterError("MCP tool returned an error")
            try:
                dumped = result.model_dump(mode="json", by_alias=True, exclude_none=True)
            except Exception:
                raise MCPAdapterError("MCP tool result could not be serialized") from None
            return _bounded_mcp_result(dumped, self.config)
        except asyncio.CancelledError:
            raise
        except MCPAdapterError:
            raise
        except TimeoutError:
            raise MCPAdapterError("MCP tool timed out") from None
        except Exception:
            raise MCPAdapterError("MCP tool call failed") from None

    async def stop(self):
        self._check_loop()
        if self._owner is None:
            return
        if self._owner.done():
            if not self._owner.cancelled():
                self._owner.result()
            return
        self._close_requested.set()
        try:
            await asyncio.wait_for(asyncio.shield(self._owner), timeout=2)
        except TimeoutError:
            self._owner.cancel()
            await asyncio.gather(self._owner, return_exceptions=True)


@dataclass(frozen=True, slots=True)
class HostMCPMount:
    server_id: str
    config: MCPTransportConfig = field(repr=False)
    allowed_tools: tuple[str, ...] = ()


class _PersistentProxy:
    def __init__(self, host: "PersistentMCPHost", server_id: str, definitions: Sequence[MCPToolDefinition], *, max_calls: int):
        self.host = host
        self.server_id = server_id
        self.definitions = tuple(definitions)
        self._max_calls = int(max_calls)
        self._calls = 0

    async def start(self) -> Sequence[MCPToolDefinition]:
        return self.definitions

    async def call(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        if self._calls >= self._max_calls:
            raise MCPAdapterError("MCP per-turn call budget exceeded")
        self._calls += 1
        return await self.host.call(self.server_id, tool_name, arguments)

    async def stop(self) -> None:
        # The pool owns the SDK adapter. A turn only releases its local
        # ToolRegistry lease; it must not close a connection used by another
        # session.
        return None


class PersistentMCPHost:
    """A host-owned MCP pool on one dedicated event loop.

    HTTP worker threads may create a fresh Agent loop for every turn. This
    pool keeps SDK sessions on a stable loop and exposes proxy adapters to the
    short-lived per-turn ToolRegistry.
    """

    def __init__(self, mounts: Sequence[HostMCPMount]):
        if len(mounts) > 8 or len({item.server_id for item in mounts}) != len(mounts):
            raise ValueError("MCP host mounts must be unique and bounded")
        self.mounts = tuple(mounts)
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._closed = False
        self._closing = False
        self._state_lock = threading.RLock()
        self._adapters: dict[str, SDKMCPAdapter] = {}
        self._definitions: dict[str, tuple[MCPToolDefinition, ...]] = {}
        self._failure_counts: dict[str, int] = {}
        self._retry_after: dict[str, float] = {}
        self._configs = {item.server_id: item for item in self.mounts}
        self._host_lock: asyncio.Lock | None = None

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._host_lock = asyncio.Lock()
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _ensure_thread(self) -> None:
        with self._state_lock:
            if self._closed or self._closing:
                raise MCPAdapterError("MCP host is closed")
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._thread_main, name="deep-mcp-host", daemon=True
                )
                self._thread.start()
            ready = self._ready
        ready.wait(timeout=5)
        with self._state_lock:
            if self._closed or self._closing:
                raise MCPAdapterError("MCP host is closed")
            loop = self._loop
        if loop is None or not loop.is_running():
            raise MCPAdapterError("MCP host event loop is unavailable")

    async def _submit(self, coroutine):
        try:
            self._ensure_thread()
            with self._state_lock:
                if self._closed or self._closing or self._loop is None:
                    raise MCPAdapterError("MCP host is closed")
                future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except BaseException:
            close = getattr(coroutine, "close", None)
            if callable(close):
                close()
            raise
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise

    async def _start_one(self, mount: HostMCPMount):
        async with self._host_lock:
            adapter = self._adapters.get(mount.server_id)
            existing = self._configs.get(mount.server_id)
            if existing is not None and existing.config != mount.config:
                raise MCPAdapterError("MCP host mount configuration changed")
            if adapter is not None and not adapter.is_connected():
                try:
                    await adapter.stop()
                except BaseException:
                    pass
                self._adapters.pop(mount.server_id, None)
                self._definitions.pop(mount.server_id, None)
                adapter = None
            if adapter is None:
                if time.monotonic() < self._retry_after.get(mount.server_id, 0):
                    raise MCPAdapterError("MCP reconnect is waiting for backoff")
                adapter = SDKMCPAdapter(mount.config)
                try:
                    definitions = tuple(await adapter.start())
                except BaseException:
                    try:
                        await adapter.stop()
                    except BaseException:
                        pass
                    failures = min(7, self._failure_counts.get(mount.server_id, 0) + 1)
                    self._failure_counts[mount.server_id] = failures
                    self._retry_after[mount.server_id] = time.monotonic() + min(
                        30.0, 0.5 * (2 ** (failures - 1))
                    )
                    raise
                self._adapters[mount.server_id] = adapter
                self._definitions[mount.server_id] = definitions
                self._failure_counts.pop(mount.server_id, None)
                self._retry_after.pop(mount.server_id, None)
            return self._definitions[mount.server_id]

    async def _call_one(
        self, server_id: str, tool_name: str, arguments: Mapping[str, Any]
    ) -> Any:
        adapter = self._adapters.get(server_id)
        if adapter is None:
            raise MCPNotEnabledError("MCP host server is not connected")
        result = await adapter.call(tool_name, arguments)
        config = self._configs[server_id].config
        return _bounded_mcp_result(result, config)

    async def mount_registry(self, registry: ToolRegistry) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        attached: list[str] = []
        try:
            with self._state_lock:
                mounts = self.mounts
            for mount in mounts:
                runtime = registry.mcp_runtime(mount.server_id)
                if runtime is None:
                    registry.register_mcp_declaration({
                        "server_id": mount.server_id,
                        "transport": mount.config.transport,
                        "plugin_id": "host",
                    })
                elif runtime.transport != mount.config.transport:
                    raise MCPAdapterError("MCP host mount transport does not match declaration")
                definitions = await self._submit(self._start_one(mount))
                await registry.attach_mcp_adapter(
                    mount.server_id,
                    _PersistentProxy(
                        self,
                        mount.server_id,
                        definitions,
                        max_calls=mount.config.max_calls_per_turn,
                    ),
                    allowed_tools=mount.allowed_tools,
                )
                attached.append(mount.server_id)
        except BaseException:
            for server_id in reversed(attached):
                await registry.stop_mcp(server_id)
            raise

    async def unmount_registry(self, registry: ToolRegistry) -> None:
        with self._state_lock:
            mounts = self.mounts
        for mount in reversed(mounts):
            await registry.stop_mcp(mount.server_id)

    async def call(self, server_id: str, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        # Both adapter lookup and the SDK call happen on the owner loop.  This
        # avoids reading loop-owned dictionaries from an arbitrary Web worker
        # thread while shutdown or connection setup is changing them.
        with self._state_lock:
            if self._closed or self._closing:
                raise MCPNotEnabledError("MCP host is closed")
        return await self._submit(self._call_one(server_id, tool_name, arguments))

    def public_payload(self) -> dict[str, Any]:
        """Return a secret-free deployment snapshot without starting I/O."""

        with self._state_lock:
            mounts = self.mounts
            state = "closed" if self._closed else "closing" if self._closing else "configured"
        return {
            "schema_version": "deep-mcp-host-v1",
            "status": state,
            "reconnect": "bounded_exponential_backoff",
            "servers": [
                {
                    "server_id": mount.server_id,
                    "transport": mount.config.transport,
                    "allowed_tools": list(mount.allowed_tools),
                    "limits": {
                        "max_concurrent_calls": mount.config.max_concurrent_calls,
                        "max_calls_per_turn": mount.config.max_calls_per_turn,
                        "max_result_bytes": mount.config.max_result_bytes,
                        "max_result_depth": mount.config.max_result_depth,
                        "max_result_items": mount.config.max_result_items,
                    },
                }
                for mount in mounts
            ],
        }

    async def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            if self._closing:
                loop = self._loop
                thread = self._thread
                should_shutdown = False
            else:
                self._closing = True
                loop = self._loop
                thread = self._thread
                should_shutdown = bool(loop is not None and loop.is_running())
        if not should_shutdown:
            # A concurrent closer owns shutdown. Wait for its thread rather
            # than scheduling a second teardown coroutine on the same loop.
            if thread is not None and thread.is_alive():
                await asyncio.to_thread(thread.join, 5)
            with self._state_lock:
                if not self._closing or thread is None or not thread.is_alive():
                    self._closed = True
                    self._closing = False
            return
        if loop is not None:
            async def shutdown():
                for adapter in tuple(self._adapters.values()):
                    try:
                        await adapter.stop()
                    except BaseException:
                        pass
                self._adapters.clear()
                self._definitions.clear()
                self._failure_counts.clear()
                self._retry_after.clear()
            future = asyncio.run_coroutine_threadsafe(shutdown(), loop)
            try:
                await asyncio.wrap_future(future)
            finally:
                loop.call_soon_threadsafe(loop.stop)
                if thread is not None:
                    await asyncio.to_thread(thread.join, 5)
                with self._state_lock:
                    self._closed = True
                    self._closing = False


def _host_mapping(value: Any, *, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(f"{label} must contain strings")
        result[key] = item
    return result


def _resolve_env_references(value: Any, *, label: str) -> dict[str, str]:
    references = _host_mapping(value, label=label)
    resolved: dict[str, str] = {}
    for target, source in references.items():
        if not source or source not in os.environ:
            raise ValueError(f"{label} references an unavailable environment variable")
        resolved[target] = os.environ[source]
    return resolved


def _read_host_mcp_config(path: str | Path) -> tuple[bytes, Path]:
    config_path = Path(path).expanduser()
    if not config_path.is_absolute():
        raise ValueError("MCP host configuration path must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(config_path, flags)
    except OSError as exc:
        raise ValueError("MCP host configuration is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("MCP host configuration must be a regular non-symlink file")
        chunks: list[bytes] = []
        remaining = 256 * 1024 + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(raw) > 256 * 1024:
        raise ValueError("MCP host configuration is too large")
    return raw, config_path


def _parse_host_mcp_mounts(raw: bytes) -> tuple[HostMCPMount, ...]:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("MCP host configuration is invalid JSON") from exc
    if not isinstance(document, Mapping):
        raise ValueError("MCP host configuration must be an object")
    if document.get("schema_version") not in {None, "deep-mcp-host-v1"}:
        raise ValueError("unsupported MCP host configuration schema")
    rows = document.get("servers", [])
    if not isinstance(rows, list) or len(rows) > 8:
        raise ValueError("MCP host configuration must contain at most eight servers")
    mounts: list[HostMCPMount] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("MCP host server entry must be an object")
        server_id = str(row.get("server_id") or "").strip()
        transport = str(row.get("transport") or "").strip().lower()
        allowed = row.get("allowed_tools", [])
        if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
            raise ValueError("MCP allowed_tools must be a string list")
        allowed_tools = tuple(dict.fromkeys(item.strip() for item in allowed if item.strip()))
        if len(allowed_tools) > 64:
            raise ValueError("MCP allowed_tools exceeds the host limit")
        timeout = row.get("timeout", 20)
        max_concurrent_calls = row.get("max_concurrent_calls", 4)
        max_calls_per_turn = row.get("max_calls_per_turn", 64)
        max_result_bytes = row.get("max_result_bytes", 256 * 1024)
        max_result_depth = row.get("max_result_depth", 16)
        max_result_items = row.get("max_result_items", 4096)
        if transport == "stdio":
            env = _host_mapping(row.get("env"), label="MCP env")
            env.update(_resolve_env_references(row.get("env_from"), label="MCP env_from"))
            args = row.get("args", [])
            if not isinstance(args, list):
                raise ValueError("MCP args must be a string list")
            config = MCPTransportConfig(
                "stdio",
                command=str(row.get("command") or ""),
                args=tuple(args),
                cwd=str(row.get("cwd")) if row.get("cwd") is not None else None,
                env=env,
                timeout=timeout,
                max_concurrent_calls=max_concurrent_calls,
                max_calls_per_turn=max_calls_per_turn,
                max_result_bytes=max_result_bytes,
                max_result_depth=max_result_depth,
                max_result_items=max_result_items,
            )
        elif transport == "http":
            headers = _host_mapping(row.get("headers"), label="MCP headers")
            headers.update(
                _resolve_env_references(row.get("headers_from"), label="MCP headers_from")
            )
            config = MCPTransportConfig(
                "http", url=str(row.get("url") or ""), headers=headers, timeout=timeout,
                max_concurrent_calls=max_concurrent_calls,
                max_calls_per_turn=max_calls_per_turn,
                max_result_bytes=max_result_bytes,
                max_result_depth=max_result_depth,
                max_result_items=max_result_items,
            )
        else:
            raise ValueError("unsupported MCP host transport")
        mounts.append(HostMCPMount(server_id, config, allowed_tools))
    # Constructor performs the canonical unique-ID check.
    return PersistentMCPHost(tuple(mounts)).mounts


def load_host_mcp_mounts(path: str | Path) -> tuple[HostMCPMount, ...]:
    """Load a bounded, deployment-owned MCP configuration.

    This loader is deliberately separate from Plugin ``mcp.json``.  A plugin
    may declare a server, but only this explicitly selected host file can
    supply executable paths, endpoints, credentials and tool allowlists.
    """

    raw, _config_path = _read_host_mcp_config(path)
    return _parse_host_mcp_mounts(raw)


class ReloadingMCPHost:
    """Atomically hot-reload a deployment config between turn leases.

    Existing turns retain their old pool until they unmount; new turns use a
    new generation.  Thus config changes never tear down an SDK session that
    another Web job is actively calling.
    """

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path).expanduser().resolve()
        mounts, fingerprint = self._read()
        self._current = PersistentMCPHost(mounts)
        self._fingerprint = fingerprint
        self._lock = threading.RLock()
        self._leases: dict[int, tuple[ToolRegistry, PersistentMCPHost]] = {}
        self._counts: dict[PersistentMCPHost, int] = {self._current: 0}
        self._retired: set[PersistentMCPHost] = set()
        self._closed = False

    def _read(self) -> tuple[tuple[HostMCPMount, ...], str]:
        raw, _config_path = _read_host_mcp_config(self.config_path)
        fingerprint = hashlib.sha256(raw).hexdigest()
        return _parse_host_mcp_mounts(raw), fingerprint

    async def _refresh(self) -> None:
        mounts, fingerprint = await asyncio.to_thread(self._read)
        closable: list[PersistentMCPHost] = []
        with self._lock:
            if self._closed:
                raise MCPAdapterError("MCP host is closed")
            if fingerprint == self._fingerprint:
                return
            previous = self._current
            self._current = PersistentMCPHost(mounts)
            self._counts.setdefault(self._current, 0)
            self._fingerprint = fingerprint
            self._retired.add(previous)
            if self._counts.get(previous, 0) == 0:
                self._retired.discard(previous)
                self._counts.pop(previous, None)
                closable.append(previous)
        for host in closable:
            await host.close()

    async def mount_registry(self, registry: ToolRegistry) -> None:
        await self._refresh()
        key = id(registry)
        with self._lock:
            if self._closed:
                raise MCPAdapterError("MCP host is closed")
            if key in self._leases:
                raise MCPAdapterError("MCP registry already has a host lease")
            host = self._current
            self._leases[key] = (registry, host)
            self._counts[host] = self._counts.get(host, 0) + 1
        try:
            await host.mount_registry(registry)
        except BaseException:
            await self._release(key, unmount=False)
            raise

    async def _release(self, key: int, *, unmount: bool) -> None:
        with self._lock:
            lease = self._leases.pop(key, None)
        if lease is None:
            return
        registry, host = lease
        try:
            if unmount:
                await host.unmount_registry(registry)
        finally:
            close_host = False
            with self._lock:
                self._counts[host] = max(0, self._counts.get(host, 1) - 1)
                if host in self._retired and self._counts[host] == 0:
                    self._retired.discard(host)
                    self._counts.pop(host, None)
                    close_host = True
            if close_host:
                await host.close()

    async def unmount_registry(self, registry: ToolRegistry) -> None:
        await self._release(id(registry), unmount=True)

    def public_payload(self) -> dict[str, Any]:
        with self._lock:
            current = self._current
            generation = self._fingerprint[:12]
            retired = len(self._retired)
        payload = current.public_payload()
        payload.update({"reload": "per_turn", "generation": generation, "retired_pools": retired})
        return payload

    async def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            hosts = {self._current, *self._retired, *(item[1] for item in self._leases.values())}
            leases = list(self._leases.values())
            self._leases.clear()
            self._retired.clear()
            self._counts.clear()
        for registry, host in leases:
            try:
                await host.unmount_registry(registry)
            except BaseException:
                pass
        await asyncio.gather(*(host.close() for host in hosts), return_exceptions=True)


@asynccontextmanager
async def mounted_mcp_transports(registry: ToolRegistry, mounts: Sequence[HostMCPMount]):
    """Mount explicitly selected connections around an async host operation."""

    if len(mounts) > 8 or len({mount.server_id for mount in mounts}) != len(mounts):
        raise ValueError("MCP mounts must have unique identities and at most eight servers")
    attached = []
    try:
        for mount in mounts:
            runtime = registry.mcp_runtime(mount.server_id)
            if runtime is None or runtime.transport != mount.config.transport:
                raise ValueError("MCP mount must match a registered transport declaration")
            attached.append(mount.server_id)
            await registry.attach_mcp_adapter(mount.server_id, SDKMCPAdapter(mount.config),
                                              allowed_tools=mount.allowed_tools)
        yield registry
    finally:
        active_error = sys.exc_info()[1]
        errors = []
        for server_id in reversed(attached):
            try:
                await registry.stop_mcp(server_id)
            except BaseException as exc:
                errors.append(exc)
        if errors and active_error is None:
            raise errors[0]
