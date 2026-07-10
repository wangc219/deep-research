from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Literal


ResearchRoute = Literal[
    "auto",
    "new_winning_mechanism",
    "traditional_gap",
    "war_case_learning",
]

CapabilityImageType = Literal["new_capability", "upgrade"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class ResearchProblem:
    topic: str
    research_route: ResearchRoute = "auto"
    selected_agent_ids: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def resolved_route(self) -> str:
        if self.research_route != "auto":
            return self.research_route
        topic = self.topic
        if any(word in topic for word in ["战例", "战争", "案例", "经验"]):
            return "war_case_learning"
        if any(word in topic for word in ["传统", "现有", "升级", "缺口", "不足"]):
            return "traditional_gap"
        return "new_winning_mechanism"


@dataclass(frozen=True)
class EvidenceCard:
    evidence_id: str
    source_title: str
    source_url: str
    source_tier: str
    claim: str
    excerpt: str
    source_location: str
    quality_assessment: str
    created_by: str
    artifact_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class BaselineFindingPacket:
    packet_id: str
    agent_id: str
    capability_tags: list[str]
    topic_focus: str
    findings: list[str]
    evidence_ids: list[str]
    confidence: float
    coverage_notes: list[str]
    open_questions: list[str]
    handoff_summary: str
    checkpoint: str
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class RecallRequest:
    recall_id: str
    source_layer: str
    target_agent_id: str | None
    target_capability_tag: str | None
    reason: str
    required_data: list[str]
    return_node: str
    urgency: str
    status: str = "pending"
    created_at: str = field(default_factory=now_iso)

    def target_key(self) -> str:
        return self.target_agent_id or self.target_capability_tag or "unroutable"


@dataclass(frozen=True)
class AgentRecommendation:
    recommendation_id: str
    missing_capability_tag: str
    reason: str
    suggested_agent_description: str
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class WinningMechanismStageOutput:
    stage_id: str
    layer: Literal["L1", "L2", "L3"]
    title: str
    outputs: dict[str, Any]
    confidence: float
    evidence_ids: list[str]
    gate_passed: bool
    gate_reasons: list[str]
    recall_requests: list[RecallRequest] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class CapabilityImageItem:
    capability_id: str
    name: str
    equipment_category: str
    capability_type: CapabilityImageType
    source_winning_logic: str
    related_scenario: str
    priority: str
    capability_gap: str
    capability_image: str
    evidence_ids: list[str]
    confidence: float
    created_at: str = field(default_factory=now_iso)

    def validate(self) -> None:
        required = [
            self.capability_id,
            self.name,
            self.equipment_category,
            self.capability_type,
            self.source_winning_logic,
            self.related_scenario,
            self.priority,
            self.capability_gap,
            self.capability_image,
        ]
        if any(not str(item).strip() for item in required):
            raise ValueError("CapabilityImageItem requires all nine display fields")
        if self.capability_type not in {"new_capability", "upgrade"}:
            raise ValueError(f"invalid capability_type: {self.capability_type}")


@dataclass(frozen=True)
class AuditResult:
    audit_id: str
    status: str
    checks: dict[str, bool]
    comments: list[str]
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class ResearchReport:
    report_id: str
    title: str
    body: str
    capability_ids: list[str]
    evidence_ids: list[str]
    audit_id: str
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    event_type: str
    actor: str
    summary: str
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
