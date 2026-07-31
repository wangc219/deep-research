"""Context cleanup helpers shared by live loops and session replay."""

from __future__ import annotations

from typing import Any

from knowledgegraph.demand_discovery.harness.types import AgentMessage, ToolResult


def annotate_transient_tool_error(
    message: AgentMessage,
    result: ToolResult,
) -> None:
    if result.details.get("error_type") != "schema_validation":
        return
    message.metadata.update(
        {
            "transient_error_type": "schema_validation",
            "transient_tool_call_id": result.tool_call_id,
        }
    )


def apply_transient_cleanup(
    messages: list[AgentMessage],
    cleanup: dict[str, Any],
) -> None:
    tool_name = str(cleanup.get("drop_schema_errors_for_tool", "")).strip()
    if not tool_name:
        return

    transient_call_ids = {
        message.tool_call_id
        for message in messages
        if message.role == "tool_result"
        and message.tool_name == tool_name
        and message.is_error
        and message.metadata.get("transient_error_type") == "schema_validation"
    }
    if not transient_call_ids:
        return

    cleaned: list[AgentMessage] = []
    for message in messages:
        if message.role == "tool_result" and message.tool_call_id in transient_call_ids:
            continue
        if message.role == "assistant" and isinstance(message.content, list):
            blocks = [
                block
                for block in message.content
                if not (
                    block.type == "tool_call"
                    and block.id in transient_call_ids
                )
            ]
            if len(blocks) != len(message.content):
                if not blocks:
                    continue
                message = AgentMessage(
                    role=message.role,
                    content=blocks,
                    timestamp=message.timestamp,
                    tool_call_id=message.tool_call_id,
                    tool_name=message.tool_name,
                    is_error=message.is_error,
                    metadata=dict(message.metadata),
                )
        cleaned.append(message)
    messages[:] = cleaned
