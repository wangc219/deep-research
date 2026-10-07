"""Tools for report context curation and read-only expansion."""

from __future__ import annotations

from typing import Any, Callable

from knowledgegraph.demand_discovery.domain.report_context import (
    CuratedReportItem,
)
from knowledgegraph.demand_discovery.harness.report_context import (
    ReportContextCandidatePool,
)
from knowledgegraph.demand_discovery.harness.tools import (
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import ToolCall, ToolResult


def create_record_report_context_curation_tool(
    pool: ReportContextCandidatePool,
    on_recorded: Callable[[list[CuratedReportItem]], None] | None = None,
) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        try:
            items = [
                CuratedReportItem(
                    item_id=str(item.get("item_id", "")),
                    material_ids=[str(value) for value in item.get("material_ids", [])],
                    report_use=str(item.get("report_use", "")),
                    claim_summary=str(item.get("claim_summary", "")),
                    curation_reason=str(item.get("curation_reason", "")),
                    required_caveat=str(item.get("required_caveat", "")),
                    excluded_reason=str(item.get("excluded_reason", "")),
                )
                for item in list(call.arguments.get("curated_items", []) or [])
            ]
        except ValueError as exc:
            return ToolResult(call.id, call.name, str(exc), {}, is_error=True)
        known = {material.material_id for material in pool.materials}
        missing = [
            material_id
            for item in items
            for material_id in item.material_ids
            if material_id not in known
        ]
        if missing:
            return ToolResult(
                call.id,
                call.name,
                f"unknown material_id: {missing[0]}",
                {},
                is_error=True,
            )
        if on_recorded is not None:
            on_recorded(items)
        return ToolResult(
            call.id,
            call.name,
            f"recorded {len(items)} curated report context items",
            {"curated_items": [item.to_dict() for item in items]},
        )

    return ToolDefinition(
        name="record_report_context_curation",
        description="Record semantic curation for a ReportContext candidate pool.",
        parameters_schema={
            "type": "object",
            "required": ["bundle_id", "curated_items"],
            "properties": {
                "bundle_id": {"type": "string"},
                "curated_items": {"type": "array", "items": {"type": "object"}},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
    )


def create_expand_report_context_tool(bundle: Any, artifacts: Any) -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        material_id = str(call.arguments.get("material_id", ""))
        material = next(
            (item for item in list(bundle.materials) if item.material_id == material_id),
            None,
        )
        if material is None:
            return ToolResult(
                call.id,
                call.name,
                f"unknown material_id: {material_id}",
                {},
                is_error=True,
            )
        window = material.window_text
        ref = material.source_location.split("#", 1)[0]
        if artifacts is not None and ref and hasattr(artifacts, "exists") and artifacts.exists(ref):
            try:
                window = artifacts.get_text(ref)[:6000]
            except KeyError:
                window = material.window_text
        return ToolResult(
            call.id,
            call.name,
            f"expanded report context {material_id}",
            {
                "material_id": material_id,
                "source_location": material.source_location,
                "window_text": window,
            },
        )

    return ToolDefinition(
        name="expand_report_context",
        description="Read a larger, sanitized window for a report context material.",
        parameters_schema={
            "type": "object",
            "required": ["material_id"],
            "properties": {"material_id": {"type": "string"}},
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
    )
