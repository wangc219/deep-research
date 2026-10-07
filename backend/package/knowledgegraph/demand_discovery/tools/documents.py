"""Document reading and summarization tools backed by artifacts."""

from __future__ import annotations

from knowledgegraph.demand_discovery.harness.tools import (
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import ToolCall, ToolResult
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore
from knowledgegraph.demand_discovery.tools.network import UNTRUSTED_NOTICE


def create_read_document_tool(artifacts: ArtifactStore) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        ref = str(call.arguments["artifact_ref"])
        offset = max(0, int(call.arguments.get("offset", 0)))
        limit = max(1, int(call.arguments.get("limit", 40)))
        try:
            paragraphs = _paragraphs(artifacts.get_text(ref))
        except KeyError:
            return ToolResult(call.id, call.name, f"unknown artifact_ref: {ref}", {}, is_error=True)
        end = min(offset + limit, len(paragraphs))
        rows = [
            f"[para:{index}] {paragraphs[index]}\n"
            f"source_location: {ref}#para:{index}"
            for index in range(offset, end)
        ]
        remaining = max(0, len(paragraphs) - end)
        if remaining:
            rows.append(f"剩余 {remaining} 段；继续读取请使用 offset={end}。")
        content = f"{UNTRUSTED_NOTICE}\n" + "\n\n".join(rows)
        return ToolResult(
            call.id,
            call.name,
            content,
            {
                "artifact_ref": ref,
                "total_paragraphs": len(paragraphs),
                "returned_range": [offset, end],
                "truncated": remaining > 0,
            },
        )

    return ToolDefinition(
        name="read_document",
        description="Read paragraphs from a stored artifact by offset and limit.",
        parameters_schema={
            "type": "object",
            "required": ["artifact_ref"],
            "properties": {
                "artifact_ref": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        execute=execute,
    )


def create_extract_summary_tool(artifacts: ArtifactStore) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        ref = str(call.arguments["artifact_ref"])
        max_chars = max(1, int(call.arguments.get("max_chars", 800)))
        try:
            text = " ".join(_paragraphs(artifacts.get_text(ref)))
        except KeyError:
            return ToolResult(call.id, call.name, f"unknown artifact_ref: {ref}", {}, is_error=True)
        summary = text[:max_chars]
        return ToolResult(
            call.id,
            call.name,
            f"summary ({len(summary)} chars): {summary}",
            {
                "artifact_ref": ref,
                "summary_text": summary,
                "summary_source": "model_generated",
            },
        )

    return ToolDefinition(
        name="extract_summary",
        description="Create a short model-generated reading aid summary for an artifact.",
        parameters_schema={
            "type": "object",
            "required": ["artifact_ref"],
            "properties": {
                "artifact_ref": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        execute=execute,
    )


def _paragraphs(text: str) -> list[str]:
    return [item.strip() for item in text.split("\n\n") if item.strip()]
