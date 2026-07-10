"""Append-only domain trace store.

Domain trace events are durable lineage records for source/evidence/candidate/
audit/report state changes. Runtime events such as provider deltas, tool
progress, or turn lifecycle events stay on the runtime event bus and are not
accepted here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from knowledgegraph.demand_discovery.harness.types import DomainTraceProposal


@dataclass
class DomainTraceEvent:
    """A durable domain lineage event."""

    domain_trace_id: str
    trace_id: str
    event_type: str
    actor: str
    target_type: str
    target_id: str
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)
    summary: str = ""
    decision: str | None = None
    rationale: str | None = None
    model: str | None = None
    prompt_id: str | None = None
    tool_refs: list[str] = field(default_factory=list)
    runtime_event_id: str | None = None
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_trace_id": self.domain_trace_id,
            "trace_id": self.trace_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "summary": self.summary,
            "decision": self.decision,
            "rationale": self.rationale,
            "model": self.model,
            "prompt_id": self.prompt_id,
            "tool_refs": list(self.tool_refs),
            "runtime_event_id": self.runtime_event_id,
            "created_at": self.created_at,
        }


class DomainTraceStore:
    """In-memory append-only store for :class:`DomainTraceEvent`."""

    def __init__(self) -> None:
        self._events: list[DomainTraceEvent] = []
        self._clock = 0

    def append(self, event: DomainTraceEvent) -> DomainTraceEvent:
        if not isinstance(event, DomainTraceEvent):
            raise TypeError("DomainTraceStore only accepts DomainTraceEvent")
        self._events.append(event)
        self._clock = max(self._clock, event.created_at)
        return event

    def append_from_proposal(
        self,
        proposal: DomainTraceProposal,
        trace_id: str,
        actor: str,
        runtime_event_id: str | None = None,
    ) -> DomainTraceEvent:
        """Convert an accepted trace proposal into a durable trace event."""

        self._clock += 1
        event = DomainTraceEvent(
            domain_trace_id=f"dt-{uuid4().hex}",
            trace_id=trace_id,
            event_type=proposal.event_type,
            actor=actor,
            target_type=proposal.target_type,
            target_id=proposal.target_id,
            input_refs=list(proposal.input_refs),
            output_refs=list(proposal.output_refs),
            summary=proposal.payload_summary,
            decision=proposal.payload.get("decision"),
            rationale=proposal.payload.get("rationale"),
            model=proposal.payload.get("model"),
            prompt_id=proposal.payload.get("prompt_id"),
            tool_refs=list(proposal.payload.get("tool_refs", [])),
            runtime_event_id=runtime_event_id,
            created_at=self._clock,
        )
        return self.append(event)

    def events(self) -> list[DomainTraceEvent]:
        return list(self._events)

    def get_report_trace(self, report_id: str) -> list[DomainTraceEvent]:
        """Return source -> evidence -> candidate -> audit -> report lineage."""

        needed = {report_id}
        selected: set[str] = set()
        selected_audit_ids: set[str] = set()
        changed = True
        while changed:
            changed = False
            for event in reversed(self._events):
                refs = {event.target_id, *event.output_refs}
                if event.domain_trace_id in selected or refs.isdisjoint(needed):
                    continue
                if (
                    event.event_type == "audit_completed"
                    and event.target_id in selected_audit_ids
                ):
                    continue
                selected.add(event.domain_trace_id)
                if event.event_type == "audit_completed":
                    selected_audit_ids.add(event.target_id)
                before = len(needed)
                needed.update(event.input_refs)
                if len(needed) != before:
                    changed = True

        return [event for event in self._events if event.domain_trace_id in selected]
