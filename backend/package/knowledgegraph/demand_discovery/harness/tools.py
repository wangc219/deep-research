"""Tool registry and execution contract for the demand discovery harness.

A tool is a :class:`ToolDefinition` with a name, description, JSON-schema-subset
parameter spec, an async ``execute`` callable, and an execution mode. The
:class:`ToolRegistry` validates arguments against the schema, runs optional
``before_tool_call`` / ``after_tool_call`` hooks, and normalizes thrown errors
into error :class:`ToolResult` objects.

Schema validation deliberately implements only a small JSON-schema subset
(``type=object`` with ``required`` and ``properties`` of primitive types) so the
harness has no external dependency.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from knowledgegraph.demand_discovery.harness.cancellation import CancelToken
from knowledgegraph.demand_discovery.harness.types import ToolCall, ToolResult


class SchemaValidationError(ValueError):
    """Raised when tool arguments do not match the parameter schema."""


_PRIMITIVE_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Validate ``arguments`` against a small JSON-schema subset.

    Supports ``type=object`` with ``required`` and ``properties``; each property
    may declare a primitive ``type``. Raises :class:`SchemaValidationError` on a
    missing required key or a primitive type mismatch. Unknown keys are allowed.
    """

    if schema.get("type", "object") != "object":
        raise SchemaValidationError(
            f"unsupported schema type: {schema.get('type')!r}"
        )

    required = schema.get("required", [])
    for key in required:
        if key not in arguments:
            raise SchemaValidationError(f"missing required argument: {key!r}")

    properties = schema.get("properties", {})
    for key, spec in properties.items():
        if key not in arguments:
            continue
        declared = spec.get("type")
        if declared is None:
            continue
        expected = _PRIMITIVE_TYPES.get(declared)
        if expected is None:
            continue
        value = arguments[key]
        # bool is a subclass of int; reject it for numeric types explicitly.
        if declared in ("number", "integer") and isinstance(value, bool):
            raise SchemaValidationError(
                f"argument {key!r} expected {declared}, got bool"
            )
        if not isinstance(value, expected):
            raise SchemaValidationError(
                f"argument {key!r} expected {declared}, got "
                f"{type(value).__name__}"
            )


@dataclass
class ToolExecutionContext:
    """Identity and permission context handed to a tool at execution time."""

    run_id: str
    agent_run_id: str
    worker_id: str
    permissions: dict[str, Any] = field(default_factory=dict)
    cancel_token: CancelToken = field(default_factory=CancelToken)
    budget_state: str = "normal"


ToolExecute = Callable[[ToolCall, ToolExecutionContext], Awaitable[ToolResult]]
BeforeToolCall = Callable[
    [ToolCall, ToolExecutionContext], Optional[ToolResult]
]
AfterToolCall = Callable[
    [ToolCall, ToolExecutionContext, ToolResult], ToolResult
]


@dataclass
class ToolDefinition:
    """A registered tool.

    ``execution_mode`` is ``"parallel"`` (default) or ``"sequential"``. A batch
    that includes any sequential tool is forced sequential by the loop.
    """

    name: str
    description: str
    parameters_schema: dict[str, Any]
    execute: ToolExecute
    execution_mode: str = "parallel"
    prompt_guidelines: str = ""
    timeout_ms: int = 60_000


class ToolRegistry:
    """Holds tool definitions and runs them with validation and hooks."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._before: BeforeToolCall | None = None
        self._after: AfterToolCall | None = None

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        return self._tools[name]

    def list_active(self, names: list[str] | None = None) -> list[ToolDefinition]:
        if names is None:
            return list(self._tools.values())
        return [self._tools[name] for name in names if name in self._tools]

    def set_before_tool_call(self, hook: BeforeToolCall | None) -> None:
        self._before = hook

    def set_after_tool_call(self, hook: AfterToolCall | None) -> None:
        self._after = hook

    def requires_sequential(self, names: list[str]) -> bool:
        """True if any named tool declares sequential execution."""

        return any(
            name in self._tools
            and self._tools[name].execution_mode == "sequential"
            for name in names
        )

    async def execute(
        self, call: ToolCall, context: ToolExecutionContext
    ) -> ToolResult:
        """Validate, run hooks, execute the tool, and normalize errors."""

        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content=f"unknown tool: {call.name}",
                details={},
                is_error=True,
            )

        try:
            validate_arguments(tool.parameters_schema, call.arguments)
        except SchemaValidationError as exc:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content=str(exc),
                details={},
                is_error=True,
            )

        if self._before is not None:
            blocked = self._before(call, context)
            if blocked is not None:
                return blocked

        try:
            result = await asyncio.wait_for(
                tool.execute(call, context),
                timeout=max(tool.timeout_ms / 1000, 0.001),
            )
        except TimeoutError:
            result = ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content=f"tool timeout after {tool.timeout_ms} ms",
                details={"timeout_ms": tool.timeout_ms},
                is_error=True,
            )
        except Exception as exc:  # normalize thrown tool errors
            result = ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content=f"tool error: {exc}",
                details={},
                is_error=True,
            )

        if self._after is not None:
            result = self._after(call, context, result)

        return result
