"""Capability registry used by the deep-research Agent Loop.

The dialogue loop deliberately knows only how to ask a registry for one tool
and consume its observation.  Domain handlers, installed Skills and MCP
providers are registered at the edge.  This mirrors nanobot's small
``ToolRegistry`` while keeping the equipment runtime's stronger boundaries:

* built-in research actions are explicit and deterministic;
* an MCP declaration never starts a process or opens a socket by itself;
* a provider must be supplied by the host and must expose a bounded tool list;
* every mounted MCP tool remains namespaced by its server identity; and
* lifecycle failures are observable without turning the whole dialogue into a
  failed turn.

The module has no dependency on the model provider or on the web API.  A
``TurnState`` is passed to built-in handlers, while MCP adapters receive only
the JSON arguments supplied to their namespaced tool.  This keeps capability
and intelligence (the conductor/model) separate.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
import re
from typing import Any, Literal, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from equipment_deep_research.deep_runtime.capabilities import (
        DeepCapabilityRegistry,
        MCPDeclaration,
    )
    from equipment_deep_research.deep_runtime.state import TurnState


ToolSource = Literal["builtin", "mcp"]
MCPStatus = Literal[
    "declaration_only",
    "registered",
    "connecting",
    "ready",
    "failed",
    "stopping",
    "stopped",
]

_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MCP_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_SERVER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_MCP_TOOLS = 64
_MAX_DESCRIPTION = 1200
_MAX_ERROR = 600


def _text(value: object, limit: int = 1200) -> str:
    return " ".join(str(value or "").split()).strip()[: max(0, int(limit))]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_schema(value: object) -> dict[str, Any]:
    """Return a bounded JSON-schema shape suitable for a model definition."""

    if not isinstance(value, Mapping):
        return {"type": "object", "properties": {}}
    # Schemas are metadata, not an execution channel.  Keep only JSON-like
    # values and cap the serialized size to avoid a provider poisoning context.
    def project(item: Any, depth: int = 0) -> Any:
        if depth > 5:
            return None
        if item is None or isinstance(item, (bool, int, float, str)):
            return item if not isinstance(item, str) else item[:800]
        if isinstance(item, Mapping):
            return {
                str(key)[:120]: project(value, depth + 1)
                for key, value in list(item.items())[:64]
            }
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            return [project(value, depth + 1) for value in list(item)[:64]]
        return None

    result = project(value)
    if not isinstance(result, dict):
        return {"type": "object", "properties": {}}
    result.setdefault("type", "object")
    result.setdefault("properties", {})
    return result


def _namespace_tool(server_id: str, tool_name: str) -> str:
    """Build a stable model-safe MCP name without accepting path-like names."""

    server = _text(server_id, 128)
    name = _text(tool_name, 96)
    if not _SERVER_NAME.fullmatch(server):
        raise ValueError("invalid MCP server identity")
    if not _MCP_TOOL_NAME.fullmatch(name):
        raise ValueError("invalid MCP tool identity")
    candidate = f"mcp_{server}_{name}"
    # Provider tool names are generally ASCII and bounded.  Keep a deterministic
    # truncation rather than silently creating collisions.
    if len(candidate) > 128:
        import hashlib

        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:12]
        candidate = f"{candidate[:115]}_{digest}"
    return candidate


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One executable capability exposed to the loop."""

    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    source: ToolSource = "builtin"
    handler: Callable[["TurnState"], Awaitable[Mapping[str, Any]]] | None = field(
        default=None, repr=False, compare=False
    )
    plugin_id: str = ""
    server_id: str = ""
    original_name: str = ""

    def __post_init__(self) -> None:
        name = _text(self.name, 128)
        if not name or _TOOL_NAME.fullmatch(name) is None:
            raise ValueError(f"invalid tool name: {self.name!r}")
        if self.source not in {"builtin", "mcp"}:
            raise ValueError(f"unsupported tool source: {self.source!r}")
        if self.source == "builtin" and self.handler is None:
            raise ValueError("built-in tools require a handler")
        if self.source == "mcp" and not self.server_id:
            raise ValueError("MCP tools require a server identity")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", _text(self.description, _MAX_DESCRIPTION))
        object.__setattr__(self, "input_schema", _safe_schema(self.input_schema))
        object.__setattr__(self, "plugin_id", _text(self.plugin_id, 128))
        object.__setattr__(self, "server_id", _text(self.server_id, 128))
        object.__setattr__(self, "original_name", _text(self.original_name, 128))

    def public_payload(self) -> dict[str, Any]:
        """Return metadata safe to expose to the model/UI."""

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "source": self.source,
            **({"plugin_id": self.plugin_id} if self.plugin_id else {}),
            **({"server_id": self.server_id} if self.server_id else {}),
            **({"original_name": self.original_name} if self.original_name else {}),
        }


@dataclass(frozen=True, slots=True)
class MCPToolDefinition:
    """Tool metadata returned by an MCP adapter before it is mounted."""

    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = _text(self.name, 96)
        if not name or _MCP_TOOL_NAME.fullmatch(name) is None:
            raise ValueError(f"invalid MCP tool name: {self.name!r}")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", _text(self.description, _MAX_DESCRIPTION))
        object.__setattr__(self, "input_schema", _safe_schema(self.input_schema))


@runtime_checkable
class MCPAdapter(Protocol):
    """Small lifecycle contract implemented by a controlled MCP provider.

    Adapters own transport details.  The deep Agent Loop never imports an MCP
    SDK, spawns a process, or handles credentials.  Hosts can provide an
    in-process adapter in tests or a hardened transport adapter in deployment.
    """

    async def start(self) -> Sequence[MCPToolDefinition]: ...

    async def call(self, tool_name: str, arguments: Mapping[str, Any]) -> Any: ...

    async def stop(self) -> None: ...


class MCPAdapterError(RuntimeError):
    """Base error for controlled MCP lifecycle and invocation failures."""


class MCPNotEnabledError(MCPAdapterError):
    """Raised when a declaration has no explicitly attached adapter."""


class MCPToolNotAllowedError(MCPAdapterError):
    """Raised when an adapter advertises a tool outside its host allowlist."""


class DeclarationOnlyMCPAdapter:
    """Safe default for a discovered declaration.

    It deliberately never performs I/O.  This is useful for the normal web
    process where plugin metadata may be displayed before an operator chooses
    a separately sandboxed transport.
    """

    async def start(self) -> Sequence[MCPToolDefinition]:
        return ()

    async def call(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        raise MCPNotEnabledError("MCP server is declaration-only")

    async def stop(self) -> None:
        return None


class InProcessMCPAdapter:
    """A small adapter for trusted, explicitly registered local capabilities.

    This gives plugins and tests a usable MCP-shaped extension point without
    granting arbitrary plugin files the ability to execute subprocesses.  A
    deployment may wrap a real MCP client behind the same protocol after its
    own sandbox and network policy has approved it.
    """

    def __init__(
        self,
        tools: Mapping[
            str,
            Callable[[Mapping[str, Any]], Awaitable[Any] | Any]
            | MCPToolDefinition,
        ],
    ) -> None:
        self._tools: dict[str, MCPToolDefinition] = {}
        self._handlers: dict[str, Callable[[Mapping[str, Any]], Awaitable[Any] | Any]] = {}
        for name, value in tools.items():
            if isinstance(value, MCPToolDefinition):
                definition = value
            else:
                definition = MCPToolDefinition(name=name)
                if not callable(value):
                    raise TypeError(f"MCP handler for {name!r} is not callable")
                self._handlers[definition.name] = value
            self._tools[definition.name] = definition
            if callable(value) and definition.name not in self._handlers:
                self._handlers[definition.name] = value
        self.started = False

    async def start(self) -> Sequence[MCPToolDefinition]:
        self.started = True
        return tuple(self._tools.values())

    async def call(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        if not self.started:
            raise MCPNotEnabledError("MCP adapter has not been started")
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise MCPToolNotAllowedError(f"MCP tool is not registered: {tool_name}")
        result = handler(dict(arguments))
        if inspect.isawaitable(result):
            result = await result
        return result

    async def stop(self) -> None:
        self.started = False


@dataclass(slots=True)
class MCPServerRuntime:
    server_id: str
    transport: str
    plugin_id: str = ""
    status: MCPStatus = "declaration_only"
    tool_names: tuple[str, ...] = ()
    error: str = ""
    updated_at: str = field(default_factory=_now)
    adapter: MCPAdapter | None = field(default=None, repr=False)
    allowed_tool_names: frozenset[str] = field(default_factory=frozenset, repr=False)

    def public_payload(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "transport": self.transport,
            "plugin_id": self.plugin_id,
            "status": self.status,
            "execution_status": self.status,
            "tool_names": list(self.tool_names),
            "error": self.error,
            "updated_at": self.updated_at,
        }


class ToolRegistry:
    """Dynamic registry with explicit registration and MCP lifecycle."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._mcp_servers: dict[str, MCPServerRuntime] = {}
        self._definitions_cache: tuple[dict[str, Any], ...] | None = None
        self._mcp_locks: dict[str, asyncio.Lock] = {}

    # ---- built-in / generic tool API -------------------------------------------------
    def register(self, spec: ToolSpec, *, replace: bool = False) -> ToolSpec:
        if not isinstance(spec, ToolSpec):
            raise TypeError("registry accepts ToolSpec values")
        if spec.name in self._tools and not replace:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec
        self._definitions_cache = None
        return spec

    def register_handler(
        self,
        name: str,
        handler: Callable[["TurnState"], Awaitable[Mapping[str, Any]]],
        *,
        description: str = "",
        input_schema: Mapping[str, Any] | None = None,
        replace: bool = False,
    ) -> ToolSpec:
        if not callable(handler):
            raise TypeError("tool handler must be callable")
        return self.register(
            ToolSpec(
                name=name,
                description=description or f"Equipment deep-research action: {name}",
                input_schema=input_schema or {},
                source="builtin",
                handler=handler,
            ),
            replace=replace,
        )

    def unregister(self, name: str) -> None:
        self._tools.pop(str(name), None)
        self._definitions_cache = None

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(str(name))

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Nanobot-compatible alias used by diagnostics and callers."""

        return self.names

    def definitions(self) -> list[dict[str, Any]]:
        if self._definitions_cache is None:
            self._definitions_cache = tuple(
                item.public_payload() for item in sorted(self._tools.values(), key=lambda x: x.name)
            )
        return [dict(item) for item in self._definitions_cache]

    # Nanobot uses get_definitions; retaining the name makes adapters easy to
    # reuse while the returned shape stays secret-safe.
    get_definitions = definitions

    def register_builtin_handlers(
        self,
        handlers: Mapping[str, Callable[["TurnState"], Awaitable[Mapping[str, Any]]]],
    ) -> None:
        for name, handler in handlers.items():
            self.register_handler(str(name), handler, replace=True)

    async def execute(self, name: str, state: "TurnState") -> Mapping[str, Any]:
        """Execute one registered built-in action against the current state."""

        spec = self.get(name)
        if spec is None:
            raise KeyError(f"unknown runtime tool: {name}")
        if spec.source != "builtin" or spec.handler is None:
            raise MCPNotEnabledError(
                f"{name} is an MCP capability; call execute_mcp with JSON arguments"
            )
        result = spec.handler(state)
        if not inspect.isawaitable(result):
            raise TypeError(f"tool handler {name!r} must be async")
        resolved = await result
        if not isinstance(resolved, Mapping):
            raise TypeError(f"tool handler {name!r} returned a non-object result")
        return resolved

    # ---- MCP declaration and lifecycle -----------------------------------------------
    def register_mcp_declaration(self, declaration: "MCPDeclaration | Mapping[str, Any]") -> MCPServerRuntime:
        if isinstance(declaration, Mapping):
            server_id = _text(declaration.get("server_id"), 128)
            transport = _text(declaration.get("transport") or "unknown", 24)
            plugin_id = _text(declaration.get("plugin_id"), 128)
        else:
            server_id = _text(getattr(declaration, "server_id", ""), 128)
            transport = _text(getattr(declaration, "transport", "unknown"), 24)
            plugin_id = _text(getattr(declaration, "plugin_id", ""), 128)
        if not server_id or not _SERVER_NAME.fullmatch(server_id):
            raise ValueError("invalid MCP server identity")
        current = self._mcp_servers.get(server_id)
        if current is not None:
            return current
        runtime = MCPServerRuntime(
            server_id=server_id,
            transport=transport or "unknown",
            plugin_id=plugin_id,
            status="declaration_only",
        )
        self._mcp_servers[server_id] = runtime
        return runtime

    def mcp_runtime(self, server_id: str) -> MCPServerRuntime | None:
        return self._mcp_servers.get(str(server_id))

    def mcp_status(self) -> dict[str, dict[str, Any]]:
        return {
            server_id: runtime.public_payload()
            for server_id, runtime in sorted(self._mcp_servers.items())
        }

    async def attach_mcp_adapter(
        self,
        server_id: str,
        adapter: MCPAdapter,
        *,
        allowed_tools: Sequence[str] = (),
    ) -> tuple[ToolSpec, ...]:
        lock = self._mcp_locks.setdefault(str(server_id), asyncio.Lock())
        async with lock:
            return await self._attach_mcp_adapter(server_id, adapter, allowed_tools=allowed_tools)

    async def _attach_mcp_adapter(
        self,
        server_id: str,
        adapter: MCPAdapter,
        *,
        allowed_tools: Sequence[str] = (),
    ) -> tuple[ToolSpec, ...]:
        """Start and mount a host-approved MCP adapter.

        The caller must first register the corresponding declaration.  An
        explicit ``allowed_tools`` list is required for non-empty adapter
        output; an empty list means the adapter can be observed but cannot
        expose tools.  This prevents a plugin from silently expanding the
        Agent Loop's execution surface.
        """

        runtime = self._mcp_servers.get(str(server_id))
        if runtime is None:
            raise KeyError(f"MCP declaration not found: {server_id}")
        if not isinstance(adapter, MCPAdapter):
            raise TypeError("adapter must implement MCPAdapter")
        allow = frozenset(
            _text(item, 96) for item in allowed_tools if _text(item, 96)
        )
        if runtime.adapter is not None:
            await self._stop_mcp(server_id)
        runtime.adapter = adapter
        runtime.allowed_tool_names = allow
        runtime.status = "connecting"
        runtime.error = ""
        runtime.updated_at = _now()
        try:
            definitions = list(await adapter.start())
            if len(definitions) > _MAX_MCP_TOOLS:
                raise MCPAdapterError("MCP tool-count limit exceeded")
            mounted: list[ToolSpec] = []
            seen: set[str] = set()
            for definition in definitions:
                if not isinstance(definition, MCPToolDefinition):
                    raise MCPAdapterError("adapter returned invalid tool metadata")
                if definition.name not in allow:
                    continue
                if definition.name in seen:
                    raise MCPAdapterError("adapter returned duplicate tool metadata")
                seen.add(definition.name)
                qualified = _namespace_tool(runtime.server_id, definition.name)

                async def invoke(
                    state: "TurnState",
                    *,
                    _adapter: MCPAdapter = adapter,
                    _tool_name: str = definition.name,
                    _server_id: str = runtime.server_id,
                ) -> Mapping[str, Any]:
                    # The state payload is intentionally not forwarded: MCP
                    # adapters receive only explicit JSON arguments through
                    # ``execute_mcp``.  Built-in loop calls cannot smuggle
                    # session internals into an external provider.
                    del state
                    result = await _adapter.call(_tool_name, {})
                    if isinstance(result, Mapping):
                        return dict(result)
                    return {"value": result, "mcp_server": _server_id, "tool": _tool_name}

                spec = ToolSpec(
                    name=qualified,
                    description=definition.description,
                    input_schema=definition.input_schema,
                    source="mcp",
                    handler=invoke,
                    plugin_id=runtime.plugin_id,
                    server_id=runtime.server_id,
                    original_name=definition.name,
                )
                mounted.append(spec)
            for spec in mounted:
                self.register(spec, replace=True)
            runtime.tool_names = tuple(item.name for item in mounted)
            runtime.status = "ready" if mounted else "registered"
            runtime.updated_at = _now()
            self._definitions_cache = None
            return tuple(mounted)
        except BaseException:
            runtime.status = "failed"
            runtime.error = "MCP connection failed"
            runtime.updated_at = _now()
            try:
                await adapter.stop()
            except BaseException:
                pass
            raise

    async def execute_mcp(
        self,
        qualified_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> Any:
        """Invoke a mounted MCP tool with explicit JSON arguments."""

        spec = self.get(qualified_name)
        if spec is None or spec.source != "mcp":
            raise KeyError(f"unknown MCP tool: {qualified_name}")
        runtime = self._mcp_servers.get(spec.server_id)
        if runtime is None or runtime.adapter is None or runtime.status != "ready":
            raise MCPNotEnabledError(f"MCP server is not ready: {spec.server_id}")
        original = spec.original_name
        if not original or original not in runtime.allowed_tool_names:
            raise MCPToolNotAllowedError(f"MCP tool is outside the host allowlist: {qualified_name}")
        params = arguments if isinstance(arguments, Mapping) else {}
        try:
            return await runtime.adapter.call(original, dict(params))
        except Exception:
            runtime.status = "failed"
            runtime.error = "MCP tool call failed"
            runtime.updated_at = _now()
            raise

    async def stop_mcp(self, server_id: str) -> None:
        lock = self._mcp_locks.setdefault(str(server_id), asyncio.Lock())
        async with lock:
            await self._stop_mcp(server_id)

    async def _stop_mcp(self, server_id: str) -> None:
        runtime = self._mcp_servers.get(str(server_id))
        if runtime is None:
            return
        adapter = runtime.adapter
        runtime.status = "stopping"
        runtime.updated_at = _now()
        try:
            if adapter is not None:
                await adapter.stop()
        except BaseException:
            runtime.status = "failed"
            runtime.error = "MCP shutdown failed"
            raise
        else:
            runtime.adapter = None
            runtime.status = "stopped"
            runtime.error = ""
        finally:
            for name in runtime.tool_names:
                self.unregister(name)
            runtime.tool_names = ()
            runtime.allowed_tool_names = frozenset()
            runtime.updated_at = _now()

    async def close(self) -> None:
        errors: list[BaseException] = []
        for server_id in tuple(self._mcp_servers):
            try:
                await self.stop_mcp(server_id)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def public_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "deep-tool-registry-v1",
            "tools": self.definitions(),
            "mcp_servers": [
                item.public_payload()
                for item in sorted(self._mcp_servers.values(), key=lambda value: value.server_id)
            ],
            "limits": {"max_mcp_tools": _MAX_MCP_TOOLS},
        }


def build_tool_registry(
    *,
    handlers: Mapping[str, Callable[["TurnState"], Awaitable[Mapping[str, Any]]]] | None = None,
    capability_registry: "DeepCapabilityRegistry | None" = None,
) -> ToolRegistry:
    """Build one per-turn registry from the current capability snapshot."""

    registry = ToolRegistry()
    if handlers is None:
        # Local import avoids importing domain tools when a caller only needs
        # to inspect MCP lifecycle metadata.
        from equipment_deep_research.deep_runtime.tools import TOOL_HANDLERS

        handlers = TOOL_HANDLERS
    registry.register_builtin_handlers(handlers)
    if capability_registry is not None:
        for plugin in capability_registry.plugins:
            for declaration in plugin.mcp_servers:
                registry.register_mcp_declaration(declaration)
    return registry


__all__ = [
    "DeclarationOnlyMCPAdapter",
    "InProcessMCPAdapter",
    "MCPAdapter",
    "MCPAdapterError",
    "MCPNotEnabledError",
    "MCPServerRuntime",
    "MCPStatus",
    "MCPToolDefinition",
    "MCPToolNotAllowedError",
    "ToolRegistry",
    "ToolSource",
    "ToolSpec",
    "build_tool_registry",
]
