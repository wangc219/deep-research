"""Project layered tool results into model-facing messages.

The mediator keeps acquisition control/debug data out of the model context while
rendering the model payload into compact, readable material.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from knowledgegraph.demand_discovery.harness.types import ToolResult


@dataclass(frozen=True)
class MediatedToolResult:
    message_content: str
    control_event: dict[str, Any] = field(default_factory=dict)
    debug_refs: list[str] = field(default_factory=list)
    pause_requested: bool = False
    terminate_turn: bool = False
    transient_cleanup: dict[str, Any] = field(default_factory=dict)


def mediate_tool_result(result: ToolResult) -> MediatedToolResult:
    details = result.details or {}
    if not {"model_payload", "control", "debug"} <= set(details):
        return MediatedToolResult(message_content=result.content)

    control = dict(details.get("control") or {})
    status = str(control.get("overall_status", "")).strip()
    debug = dict(details.get("debug") or {})
    debug_refs = _debug_refs(debug)
    control_event = _control_event(result, control)
    cleanup = {
        "drop_schema_errors_for_tool": result.tool_name,
    }

    if status in {"ok", "partial"}:
        return MediatedToolResult(
            message_content=_render_documents(
                status,
                _documents(details),
                control_event,
            ),
            control_event=control_event,
            debug_refs=debug_refs,
            transient_cleanup=cleanup,
        )
    if status == "exhausted":
        return MediatedToolResult(
            message_content=(
                "whitelist acquisition found no readable documents in this round. "
                "Report this evidence gap to judge/controller instead of repeating "
                "the same source route."
            ),
            control_event=control_event,
            debug_refs=debug_refs,
            transient_cleanup=cleanup,
        )
    if status == "needs_auth":
        interrupt = dict(control.get("interrupt") or {})
        user_message = str(interrupt.get("user_message", "")).strip()
        if not user_message:
            provider = str(interrupt.get("provider", "")).strip()
            user_message = (
                f"需要用户授权后恢复来源采集。provider={provider}"
                if provider
                else "需要用户授权后恢复来源采集。"
            )
        return MediatedToolResult(
            message_content=user_message,
            control_event=control_event,
            debug_refs=debug_refs,
            pause_requested=True,
            terminate_turn=True,
            transient_cleanup=cleanup,
        )
    if status == "failed":
        return MediatedToolResult(
            message_content=(
                "The acquisition tool failed and the runtime recorded the "
                "diagnostics. Do not infer evidence from this failure; report "
                "the acquisition issue or wait for controller retry/skip."
            ),
            control_event=control_event,
            debug_refs=debug_refs,
            transient_cleanup=cleanup,
        )

    return MediatedToolResult(
        message_content=result.content,
        control_event=control_event,
        debug_refs=debug_refs,
        transient_cleanup=cleanup,
    )


def _documents(details: dict[str, Any]) -> list[dict[str, Any]]:
    payload = details.get("model_payload", {})
    if not isinstance(payload, dict):
        return []
    documents = payload.get("documents", [])
    if not isinstance(documents, list):
        return []
    return [dict(item) for item in documents if isinstance(item, dict)]


def _debug_refs(debug: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    diagnostics_ref = str(debug.get("diagnostics_ref", "")).strip()
    if diagnostics_ref:
        refs.append(diagnostics_ref)
    extra_refs = debug.get("debug_refs", [])
    if isinstance(extra_refs, list):
        refs.extend(str(item).strip() for item in extra_refs if str(item).strip())
    return _dedupe(refs)


def _control_event(result: ToolResult, control: dict[str, Any]) -> dict[str, Any]:
    source_statuses = control.get("source_statuses", [])
    if not isinstance(source_statuses, list):
        source_statuses = []
    sanitized_source_statuses = _source_status_events(source_statuses)
    event = {
        "tool_name": result.tool_name,
        "tool_call_id": result.tool_call_id,
        "overall_status": str(control.get("overall_status", "")).strip(),
        "source_status_count": len(sanitized_source_statuses),
        "source_statuses": sanitized_source_statuses,
        "interrupt": control.get("interrupt"),
    }
    return event


def _source_status_events(source_statuses: list[Any]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for item in source_statuses:
        if not isinstance(item, dict):
            continue
        events.append(
            {
                "source_name": str(item.get("source_name", "")).strip(),
                "status": str(item.get("status", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
                "action": str(item.get("action", "")).strip(),
            }
        )
    return events


def _render_documents(
    status: str,
    documents: list[dict[str, Any]],
    control_event: dict[str, Any],
) -> str:
    if not documents:
        prefix = (
            "Whitelist acquisition completed but returned no document previews."
        )
    else:
        prefix = f"Whitelist acquisition returned {len(documents)} document candidate(s)."
    if status == "partial":
        prefix += (
            " Status: partial. Some sources returned no usable result or were "
            "degraded."
        )

    rows = [prefix]
    for document in documents:
        rows.extend(_render_document(document))
    if control_event.get("source_status_count"):
        rows.append(
            "Source status summary was recorded for controller review; internal "
            "adapter diagnostics are not shown here."
        )
    return "\n".join(rows).strip()


def _render_document(document: dict[str, Any]) -> list[str]:
    document_id = str(document.get("document_id", "")).strip()
    title = str(document.get("title", "")).strip()
    source_name = str(document.get("source_name", "")).strip()
    published_at = str(document.get("published_at", "") or "").strip()
    source_credibility = str(document.get("source_credibility", "")).strip()
    evidence_use = str(document.get("evidence_use", "")).strip()
    next_action = str(document.get("next_action", "")).strip()
    url = str(document.get("url", "")).strip()

    lines = ["", f"Document document_id={document_id or 'unknown'}"]
    if title:
        lines.append(f"Title: {title}")
    if source_name:
        lines.append(f"Source: {source_name}")
    if source_credibility:
        lines.append(f"Source credibility: {source_credibility}")
    if published_at:
        lines.append(f"Published at: {published_at}")
    if url:
        lines.append(f"URL: {url}")
    for preview in _content_preview(document):
        text = str(preview.get("text", "")).strip()
        why = str(preview.get("why_relevant", "")).strip()
        if text:
            lines.append(f"Preview: {text}")
        if why:
            lines.append(f"Why relevant: {why}")
    if evidence_use:
        lines.append(f"Evidence use: {evidence_use}")
    if next_action:
        lines.append(
            f"Next action: {next_action}; call read_acquired_document with "
            f"document_id={document_id} when deeper reading is useful."
        )
    return lines


def _content_preview(document: dict[str, Any]) -> list[dict[str, Any]]:
    preview = document.get("content_preview", [])
    if not isinstance(preview, list):
        return []
    return [dict(item) for item in preview if isinstance(item, dict)]


def _dedupe(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows
