from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from equipment_deep_research.domain.models import (
    AuditResult,
    BaselineFindingPacket,
    CapabilityImageItem,
    EvidenceCard,
    ResearchReport,
    TraceEvent,
    WinningMechanismStageOutput,
    to_plain,
)


class DomainStore:
    def __init__(self) -> None:
        self.evidence: dict[str, EvidenceCard] = {}
        self.baseline_packets: dict[str, BaselineFindingPacket] = {}
        self.stage_outputs: dict[str, WinningMechanismStageOutput] = {}
        self.capability_images: dict[str, CapabilityImageItem] = {}
        self.audits: dict[str, AuditResult] = {}
        self.reports: dict[str, ResearchReport] = {}

    def add_evidence(self, item: EvidenceCard) -> None:
        self.evidence[item.evidence_id] = item

    def add_baseline_packet(self, item: BaselineFindingPacket) -> None:
        self.baseline_packets[item.packet_id] = item

    def add_stage_output(self, item: WinningMechanismStageOutput) -> None:
        self.stage_outputs[item.stage_id] = item

    def add_capability_image(self, item: CapabilityImageItem) -> None:
        item.validate()
        self.capability_images[item.capability_id] = item

    def add_audit(self, item: AuditResult) -> None:
        self.audits[item.audit_id] = item

    def add_report(self, item: ResearchReport) -> None:
        self.reports[item.report_id] = item

    def evidence_index(self) -> list[dict[str, Any]]:
        return [
            {
                "evidence_id": item.evidence_id,
                "source_title": item.source_title,
                "source_tier": item.source_tier,
                "claim": item.claim,
                "created_by": item.created_by,
            }
            for item in self.evidence.values()
        ]

    def coverage_tags(self) -> set[str]:
        tags: set[str] = set()
        for packet in self.baseline_packets.values():
            tags.update(packet.capability_tags)
        return tags

    def export_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, Any]] = []
        rows.extend({"type": "EvidenceCard", "payload": to_plain(item)} for item in self.evidence.values())
        rows.extend({"type": "BaselineFindingPacket", "payload": to_plain(item)} for item in self.baseline_packets.values())
        rows.extend({"type": "WinningMechanismStageOutput", "payload": to_plain(item)} for item in self.stage_outputs.values())
        rows.extend({"type": "CapabilityImageItem", "payload": to_plain(item)} for item in self.capability_images.values())
        rows.extend({"type": "AuditResult", "payload": to_plain(item)} for item in self.audits.values())
        rows.extend({"type": "ResearchReport", "payload": to_plain(item)} for item in self.reports.values())
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
            + ("\n" if rows else ""),
            encoding="utf-8",
        )

    def summary(self) -> dict[str, Any]:
        return {
            "evidence_count": len(self.evidence),
            "baseline_packet_count": len(self.baseline_packets),
            "stage_output_count": len(self.stage_outputs),
            "capability_image_count": len(self.capability_images),
            "audit_count": len(self.audits),
            "report_count": len(self.reports),
            "coverage_tags": sorted(self.coverage_tags()),
            "materialized_evidence_count": sum(1 for item in self.evidence.values() if item.artifact_refs),
        }


class TraceStore:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def append(self, event: TraceEvent) -> None:
        self.events.append(event)

    def export_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                json.dumps({"type": "TraceEvent", "payload": to_plain(event)}, ensure_ascii=False, sort_keys=True)
                for event in self.events
            )
            + ("\n" if self.events else ""),
            encoding="utf-8",
        )

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "event_type": event.event_type,
                "actor": event.actor,
                "summary": event.summary,
                "output_refs": list(event.output_refs),
            }
            for event in self.events
        ]
