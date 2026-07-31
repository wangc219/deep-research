from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    DomainTraceProposal,
    DomainWriteProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    SchemaValidationError,
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    validate_arguments,
)


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run-1",
        agent_run_id="agent-1",
        worker_id="worker-1",
        permissions={},
    )


async def _echo(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
    return ToolResult(
        tool_call_id=call.id,
        tool_name=call.name,
        content=str(call.arguments.get("text", "")),
        details={"echoed": call.arguments.get("text", "")},
    )


def _echo_tool() -> ToolDefinition:
    return ToolDefinition(
        name="echo",
        description="echo back text",
        parameters_schema={
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
        execute=_echo,
    )


class DemandDiscoveryToolRegistryTests(unittest.TestCase):
    def test_register_exposes_metadata(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_tool())

        tool = registry.get("echo")
        self.assertEqual(tool.name, "echo")
        self.assertEqual(tool.description, "echo back text")
        self.assertEqual(tool.execution_mode, "parallel")
        self.assertIn("text", tool.parameters_schema["properties"])

    def test_list_active_filters_by_name(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_tool())
        registry.register(
            ToolDefinition(
                name="noop",
                description="",
                parameters_schema={"type": "object", "properties": {}},
                execute=_echo,
            )
        )

        active = registry.list_active(["echo"])
        self.assertEqual([t.name for t in active], ["echo"])
        self.assertEqual(len(registry.list_active()), 2)

    def test_schema_validation_rejects_missing_required(self) -> None:
        with self.assertRaises(SchemaValidationError):
            validate_arguments(
                {
                    "type": "object",
                    "required": ["text"],
                    "properties": {"text": {"type": "string"}},
                },
                {},
            )

    def test_schema_validation_rejects_wrong_type(self) -> None:
        with self.assertRaises(SchemaValidationError):
            validate_arguments(
                {
                    "type": "object",
                    "required": ["text"],
                    "properties": {"text": {"type": "string"}},
                },
                {"text": 123},
            )

    def test_schema_validation_accepts_valid(self) -> None:
        # should not raise
        validate_arguments(
            {
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
            {"text": "hi"},
        )

    def test_channels_stay_separated(self) -> None:
        async def make(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content="summary",
                details={"id": "ev-1"},
                domain_proposals=[
                    DomainWriteProposal(
                        action="upsert",
                        object_type="EvidenceCard",
                        payload={"evidence_id": "ev-1"},
                    )
                ],
                trace_proposals=[
                    DomainTraceProposal(
                        event_type="evidence_created",
                        target_type="EvidenceCard",
                        target_id="ev-1",
                        payload_summary="created ev-1",
                        output_refs=["ev-1"],
                    )
                ],
            )

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="make",
                description="",
                parameters_schema={"type": "object", "properties": {}},
                execute=make,
            )
        )

        call = ToolCall(id="c1", name="make", arguments={})
        result = asyncio.run(registry.execute(call, _context()))
        self.assertEqual(result.content, "summary")
        self.assertEqual(result.details, {"id": "ev-1"})
        self.assertEqual(result.domain_proposals[0].object_type, "EvidenceCard")
        self.assertEqual(result.trace_proposals[0].event_type, "evidence_created")
        # details must not carry executable domain writes
        self.assertNotIn("domain_proposals", result.details)

    def test_invalid_arguments_produce_error_result_without_executing(self) -> None:
        executed: list[str] = []

        async def guarded(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            executed.append(call.id)
            return ToolResult(call.id, call.name, "ok", {})

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="guarded",
                description="",
                parameters_schema={
                    "type": "object",
                    "required": ["text"],
                    "properties": {"text": {"type": "string"}},
                },
                execute=guarded,
            )
        )

        call = ToolCall(id="c1", name="guarded", arguments={})
        result = asyncio.run(registry.execute(call, _context()))
        self.assertTrue(result.is_error)
        self.assertEqual(executed, [])

    def test_before_tool_call_can_block(self) -> None:
        executed: list[str] = []

        async def runner(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            executed.append(call.id)
            return ToolResult(call.id, call.name, "ran", {})

        def before(call: ToolCall, context: ToolExecutionContext):
            if call.arguments.get("blocked"):
                return ToolResult(
                    call.id, call.name, "blocked by hook", {}, is_error=True
                )
            return None

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="runner",
                description="",
                parameters_schema={"type": "object", "properties": {}},
                execute=runner,
            )
        )
        registry.set_before_tool_call(before)

        blocked = asyncio.run(
            registry.execute(
                ToolCall(id="c1", name="runner", arguments={"blocked": True}),
                _context(),
            )
        )
        self.assertTrue(blocked.is_error)
        self.assertEqual(blocked.content, "blocked by hook")
        self.assertEqual(executed, [])

        allowed = asyncio.run(
            registry.execute(
                ToolCall(id="c2", name="runner", arguments={}), _context()
            )
        )
        self.assertEqual(allowed.content, "ran")
        self.assertEqual(executed, ["c2"])

    def test_after_tool_call_can_rewrite_and_terminate(self) -> None:
        async def runner(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            return ToolResult(call.id, call.name, "raw", {})

        def after(call: ToolCall, context: ToolExecutionContext, result: ToolResult):
            result.content = "rewritten"
            result.terminate = True
            return result

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="runner",
                description="",
                parameters_schema={"type": "object", "properties": {}},
                execute=runner,
            )
        )
        registry.set_after_tool_call(after)

        result = asyncio.run(
            registry.execute(
                ToolCall(id="c1", name="runner", arguments={}), _context()
            )
        )
        self.assertEqual(result.content, "rewritten")
        self.assertTrue(result.terminate)

    def test_thrown_tool_error_becomes_error_result(self) -> None:
        async def boom(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            raise RuntimeError("tool exploded")

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="boom",
                description="",
                parameters_schema={"type": "object", "properties": {}},
                execute=boom,
            )
        )

        result = asyncio.run(
            registry.execute(ToolCall(id="c1", name="boom", arguments={}), _context())
        )
        self.assertTrue(result.is_error)
        self.assertIn("tool exploded", result.content)

    def test_sequential_mode_detected_when_any_tool_sequential(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_tool())
        registry.register(
            ToolDefinition(
                name="writer",
                description="",
                parameters_schema={"type": "object", "properties": {}},
                execute=_echo,
                execution_mode="sequential",
            )
        )

        self.assertTrue(registry.requires_sequential(["echo", "writer"]))
        self.assertFalse(registry.requires_sequential(["echo"]))


if __name__ == "__main__":
    unittest.main()
