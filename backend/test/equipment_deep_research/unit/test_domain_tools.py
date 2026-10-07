import asyncio

from equipment_deep_research.tools.definitions import ToolCall, ToolExecutionContext
from equipment_deep_research.tools.domain_tools import (
    DOMAIN_TOOL_OUTPUTS,
    build_domain_tool_definitions,
)
from equipment_deep_research.tools.permissions import ToolAuthorizationPolicy


def test_every_domain_tool_has_schema_output_scope_and_auditable_trace() -> None:
    definitions = build_domain_tool_definitions(DOMAIN_TOOL_OUTPUTS)
    assert {item.name for item in definitions} == set(DOMAIN_TOOL_OUTPUTS)
    for definition in definitions:
        plain = definition.to_plain()
        assert plain["input_schema"]["required"]
        output_type = DOMAIN_TOOL_OUTPUTS[definition.name]
        policy = ToolAuthorizationPolicy.default()
        policy.authorize(
            definition.name,
            active_tool_names=[definition.name],
            object_write_scopes=[output_type],
        )
        arguments = {
            key: _example_value(value)
            for key, value in plain["input_schema"]["properties"].items()
        }
        result = asyncio.run(
            definition.handler(
                ToolCall("call-1", definition.name, arguments),
                ToolExecutionContext("run-1", "agent-1"),
            )
        )
        assert result.details["writes_object_type"] == output_type
        assert result.trace_proposals[0].event_type == "domain_tool_invoked"


def _example_value(schema: dict) -> object:
    if schema.get("type") == "array":
        return ["value"]
    if schema.get("type") == "object":
        return {"value": True}
    if schema.get("type") == "integer":
        return 1
    if schema.get("type") == "number":
        return 0.8
    return "value"
