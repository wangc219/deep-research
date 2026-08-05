"""Projection-only context construction for isolated subagents."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.messages import TaskEnvelope
from equipment_deep_research.domain.models import to_plain
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.harness.compaction import ContextCompactor


_HANDOFF_FIELD_HINTS = (
    "finding",
    "assessment",
    "effect",
    "gap",
    "constraint",
    "requirement",
    "risk",
    "assumption",
    "timeline",
    "dependency",
    "scenario",
)


@dataclass(frozen=True)
class ContextPolicy:
    visible_sections: tuple[str, ...]
    max_items_per_section: int = 12
    token_budget: int = 5000
    hide_raw_sessions: bool = True

    @classmethod
    def from_agent(cls, agent: AgentDef) -> "ContextPolicy":
        raw = agent.context_policy
        return cls(
            tuple(raw.get("visible_sections", ())),
            int(raw.get("max_items_per_section", 12)),
            int(raw.get("token_budget", 5000)),
            bool(raw.get("hide_other_agent_raw_sessions", True)),
        )


@dataclass(frozen=True)
class ContextPack:
    agent_id: str
    sections: dict[str, Any]

    @property
    def context_hash(self) -> str:
        content = json.dumps(
            self.sections, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


class ContextProjector:
    def __init__(self, *, compactor: ContextCompactor | None = None) -> None:
        self.compactor = compactor or ContextCompactor()

    def project(
        self, task: TaskEnvelope, agent: AgentDef, store: DomainStore
    ) -> ContextPack:
        policy = ContextPolicy.from_agent(agent)
        sections: dict[str, Any] = {
            "task": {
                "objective": task.objective,
                "research_questions": task.research_questions,
                "return_node": task.return_node,
            }
        }
        if "EvidenceCard" in agent.object_read_scopes:
            sections["evidence_index"] = store.evidence_index()[
                : policy.max_items_per_section
            ]
        if "BaselineFindingPacket" in agent.object_read_scopes:
            sections["baseline_packets"] = [
                {
                    "agent_id": packet.agent_id,
                    "capability_tags": packet.capability_tags,
                    "handoff_summary": packet.handoff_summary,
                    "confidence": packet.confidence,
                    "open_questions": packet.open_questions,
                    "evidence_ids": packet.evidence_ids,
                }
                for packet in list(store.baseline_packets.values())[
                    : policy.max_items_per_section
                ]
            ]
        if "WinningMechanismStageOutput" in agent.object_read_scopes:
            sections["stage_outputs"] = [
                to_plain(item)
                for item in list(store.stage_outputs.values())[
                    : policy.max_items_per_section
                ]
            ]
        if "CapabilityImageItem" in agent.object_read_scopes:
            sections["capability_images"] = [
                to_plain(item)
                for item in list(store.capability_images.values())[
                    : policy.max_items_per_section
                ]
            ]
        visible = set(policy.visible_sections)
        sections = {
            key: value
            for key, value in sections.items()
            if key == "task" or key in visible
        }
        pack = ContextPack(agent.agent_id, sections)
        return self.compactor.compact(pack, token_budget=policy.token_budget)[0]


class ContextPackBuilder:
    """Compatibility facade used by the current scheduler."""

    def __init__(self) -> None:
        self.projector = ContextProjector()

    def build_for_baseline_agent(
        self,
        *,
        agent: AgentDef,
        topic: str,
        research_route: str,
        store: DomainStore,
        recall_request: dict[str, Any] | None = None,
        minimal_handoff: bool = False,
    ) -> ContextPack:
        allowed_upstream = set(agent.handoff_policy.get("accept_from", []))
        maximum_items = int(agent.context_policy.get("max_items_per_section", 12))
        upstream_handoffs = [
            _dependency_handoff(
                packet,
                target_agent_id=agent.agent_id,
                minimal=minimal_handoff,
                query=topic,
            )
            for packet in store.baseline_packet_snapshot()
            if packet.agent_id in allowed_upstream
        ][:maximum_items]
        sections = {
            "task": {"topic": topic, "research_route": research_route},
            "evidence_policy": {
                "public_sources_only": True,
                "quality_threshold_required_for_formal_evidence": True,
                "cross_source_corroboration": True,
            },
            "own_checkpoint": "",
            "recall_request": recall_request or {},
            "agent_harness": {
                "skills": agent.skills,
                "research_policy": agent.research_policy,
                "handoff_policy": agent.handoff_policy,
                "model_profile": {
                    key: value
                    for key, value in agent.model_profile.items()
                    if key not in {"provider", "model"}
                },
            },
            "upstream_handoffs": upstream_handoffs,
        }
        allowed = set(agent.context_policy.get("visible_sections", ()))
        pack = ContextPack(
            agent.agent_id,
            {key: value for key, value in sections.items() if key in allowed},
        )
        token_budget = int(agent.context_policy.get("token_budget", 5000))
        return self.projector.compactor.compact(pack, token_budget=token_budget)[0]

    def build_for_winning_mechanism(
        self,
        *,
        topic: str,
        research_route: str,
        store: DomainStore,
        coverage: dict[str, Any],
    ) -> ContextPack:
        return ContextPack(
            "winning_mechanism",
            {
                "task": {"topic": topic, "research_route": research_route},
                "baseline_summaries": [
                    {
                        "packet_id": p.packet_id,
                        "agent_id": p.agent_id,
                        "capability_tags": p.capability_tags,
                        "payload_type": p.payload_type or "legacy_analysis_sections",
                        "payload": p.payload or p.analysis_sections,
                        "evidence_ids": p.evidence_ids,
                        "confidence": p.confidence,
                        "open_questions": p.open_questions,
                    }
                    for p in store.baseline_packets.values()
                ],
                "evidence_index": store.evidence_index(),
                "coverage": coverage,
                "checkpoints": [p.checkpoint for p in store.baseline_packets.values()],
            },
        )


def _project_upstream_payload(
    *,
    target_agent_id: str,
    source_agent_id: str,
    payload: Any,
) -> Any:
    del target_agent_id, source_agent_id
    if not isinstance(payload, dict):
        return payload
    order = {key: index for index, key in enumerate(payload)}
    candidates = [
        (key, value)
        for key, value in payload.items()
        if value not in (None, "", [], {})
    ]
    candidates.sort(
        key=lambda item: (
            -sum(hint in str(item[0]).lower() for hint in _HANDOFF_FIELD_HINTS),
            order[item[0]],
        )
    )
    return dict(candidates[:5])


def compact_packet_handoff(
    packet: Any,
    *,
    minimal: bool = False,
) -> dict[str, Any]:
    """Build the only cross-agent representation allowed on model prompts.

    Raw sessions and full typed payloads stay in the run store.  Downstream
    agents receive a bounded decision packet containing conclusions, evidence
    references, uncertainty and the smallest role-relevant payload projection.
    """

    payload = getattr(packet, "payload", None) or getattr(
        packet, "analysis_sections", {}
    )
    agent_id = str(getattr(packet, "agent_id", ""))
    full_case_packet = agent_id == "case_research"
    finding_limit = 12 if full_case_packet else (3 if minimal else 5)
    string_limit = 1200 if full_case_packet else (220 if minimal else 420)
    list_limit = 14 if full_case_packet else (3 if minimal else 6)
    if minimal and isinstance(payload, dict):
        payload = _project_upstream_payload(
            target_agent_id="winning_mechanism",
            source_agent_id=agent_id,
            payload=payload,
        )
    return {
        "packet_id": str(getattr(packet, "packet_id", "")),
        "agent_id": agent_id,
        "capability_tags": list(getattr(packet, "capability_tags", []))[
            : 5 if minimal else 12
        ],
        "payload_type": str(
            getattr(packet, "payload_type", "") or "legacy_analysis_sections"
        ),
        "handoff_summary": _compact_text(
            getattr(packet, "handoff_summary", ""), 260 if minimal else 520
        ),
        "key_findings": [
            _compact_text(item, 220 if minimal else 360)
            for item in list(getattr(packet, "findings", []))[:finding_limit]
        ],
        "payload": compact_handoff_value(
            payload,
            max_string_chars=string_limit,
            max_list_items=list_limit,
            max_mapping_items=18 if full_case_packet else (5 if minimal else 10),
        ),
        "evidence_ids": list(getattr(packet, "evidence_ids", []))[
            : 6 if minimal else 14
        ],
        "confidence": getattr(packet, "confidence", None),
        "claim_ids": list(getattr(packet, "claim_ids", []))[
            : 6 if minimal else 20
        ],
        "claim_bundle_ref": str(getattr(packet, "claim_bundle_ref", "")),
        "admission_status": str(getattr(packet, "admission_status", "")),
        "limitations": [
            _compact_text(item, 160 if minimal else 260)
            for item in list(getattr(packet, "limitations", []))[
                : 1 if minimal else 3
            ]
        ],
        "open_questions": [
            _compact_text(item, 180 if minimal else 240)
            for item in list(getattr(packet, "open_questions", []))[
                : 1 if minimal else 3
            ]
        ],
    }


def _dependency_handoff(
    packet: Any,
    *,
    target_agent_id: str,
    minimal: bool,
    query: str = "",
) -> dict[str, Any]:
    payload = _project_upstream_payload(
        target_agent_id=target_agent_id,
        source_agent_id=str(getattr(packet, "agent_id", "")),
        payload=getattr(packet, "payload", None)
        or getattr(packet, "analysis_sections", {}),
    )
    if not minimal:
        return {
            "agent_id": str(getattr(packet, "agent_id", "")),
            "packet_id": str(getattr(packet, "packet_id", "")),
            "capability_tags": list(getattr(packet, "capability_tags", [])),
            "handoff_summary": _compact_text(
                getattr(packet, "handoff_summary", ""), 520
            ),
            "key_findings": [
                _compact_text(item, 360)
                for item in list(getattr(packet, "findings", []))[:4]
            ],
            "payload_type": str(
                getattr(packet, "payload_type", "")
                or "legacy_analysis_sections"
            ),
            "payload": compact_handoff_value(
                payload,
                max_string_chars=420,
                max_list_items=6,
                max_mapping_items=8,
            ),
            "evidence_ids": list(getattr(packet, "evidence_ids", []))[:12],
            "confidence": getattr(packet, "confidence", None),
            "open_questions": [
                _compact_text(item, 240)
                for item in list(getattr(packet, "open_questions", []))[:3]
            ],
        }
    finding_limit = 3
    open_questions = list(getattr(packet, "open_questions", []))
    uncertainties = [
        *list(getattr(packet, "limitations", []))[:2],
        *open_questions[:1],
    ]
    return {
        "handoff_version": "2.0",
        "agent_id": str(getattr(packet, "agent_id", "")),
        "packet_id": str(getattr(packet, "packet_id", "")),
        # Keep the legacy alias for readers of older persisted checkpoints,
        # while all new scheduling and audit code uses agent_id/packet_id.
        "source": str(getattr(packet, "agent_id", "")),
        "summary": _compact_text(
            getattr(packet, "handoff_summary", ""),
            300,
        ),
        "decisions": [
            _compact_text(item, 260)
            for item in list(getattr(packet, "findings", []))[:finding_limit]
        ],
        "context_delta": compact_handoff_value(
            payload,
            max_string_chars=280,
            max_list_items=4,
            max_mapping_items=5,
        ),
        "evidence_refs": list(getattr(packet, "evidence_ids", []))[
            :8
        ],
        "confidence": getattr(packet, "confidence", None),
        "uncertainties": [
            _compact_text(item, 180)
            for item in uncertainties
        ],
        "requested_next_action": (
            _compact_text(open_questions[0], 160)
            if open_questions
            else f"仅消费与当前Query“{_compact_text(query, 80)}”直接相关的增量。"
        ),
    }


def compact_handoff_value(
    value: Any,
    *,
    max_string_chars: int = 420,
    max_list_items: int = 6,
    max_mapping_items: int = 10,
    depth: int = 0,
) -> Any:
    """Recursively bound an agent handoff without flattening its semantics."""

    if value in (None, "", [], {}):
        return value
    if isinstance(value, str):
        return _compact_text(value, max_string_chars)
    if isinstance(value, (int, float, bool)):
        return value
    if depth >= 4:
        return _compact_text(json.dumps(value, ensure_ascii=False), max_string_chars)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            result[str(key)] = compact_handoff_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_mapping_items=max_mapping_items,
                depth=depth + 1,
            )
            if len(result) >= max_mapping_items:
                break
        return result
    if isinstance(value, (list, tuple, set)):
        return [
            compact_handoff_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_mapping_items=max_mapping_items,
                depth=depth + 1,
            )
            for item in list(value)[:max_list_items]
            if item not in (None, "", [], {})
        ]
    return _compact_text(str(value), max_string_chars)


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    cut = max(
        (text.rfind(mark, 0, limit) for mark in ("。", "；", "，")),
        default=-1,
    )
    if cut < limit // 2:
        cut = limit
    return text[:cut].rstrip("，；。 ") + "…"
