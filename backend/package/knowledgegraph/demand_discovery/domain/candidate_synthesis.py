"""Candidate synthesis from stopped research judgements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any

from knowledgegraph.demand_discovery.domain.evidence_quality import (
    evidence_can_support_candidate_synthesis,
)
from knowledgegraph.demand_discovery.domain.judgement import JudgementReport
from knowledgegraph.demand_discovery.domain.models import CandidateDemand
from knowledgegraph.demand_discovery.domain.store import DomainStore


@dataclass(frozen=True)
class CandidateSynthesisDraft:
    candidate_id: str
    title: str
    demand_statement: str
    evidence_ids: list[str]
    open_questions: list[str]
    solution_signals: list[str]
    judgement_id: str
    rationale: str
    status: str = "synthesized"
    stop_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "demand_statement": self.demand_statement,
            "evidence_ids": list(self.evidence_ids),
            "open_questions": list(self.open_questions),
            "solution_signals": list(self.solution_signals),
            "judgement_id": self.judgement_id,
            "rationale": self.rationale,
            "status": self.status,
            "stop_reason": self.stop_reason,
        }


def synthesize_candidate_from_judgement(
    judgement: JudgementReport,
    store: DomainStore,
) -> CandidateSynthesisDraft:
    evidence_ids = _existing_consensus_evidence_ids(judgement, store)
    if not evidence_ids:
        return CandidateSynthesisDraft(
            candidate_id="",
            title="",
            demand_statement="",
            evidence_ids=[],
            open_questions=[item.text for item in judgement.blind_spots],
            solution_signals=[],
            judgement_id=judgement.judgement_id,
            rationale=(
                "consensus has no direct or partial existing EvidenceCard "
                "references"
            ),
            status="needs_more_evidence",
            stop_reason="needs_more_evidence",
        )
    raw_consensus_text = "；".join(item.text for item in judgement.consensus_points)
    topic = _round_topic(judgement, store)
    consensus_text = _chinese_candidate_text(
        raw_consensus_text,
        topic=topic,
        evidence_ids=evidence_ids,
    )
    title = _title_from_consensus(consensus_text)
    candidate_id = f"cand-{_hash(judgement.judgement_id + '|' + '|'.join(evidence_ids))}"
    draft = CandidateSynthesisDraft(
        candidate_id=candidate_id,
        title=title,
        demand_statement=consensus_text,
        evidence_ids=evidence_ids,
        open_questions=[item.text for item in judgement.blind_spots],
        solution_signals=[item.text for item in judgement.unique_insights[:5]],
        judgement_id=judgement.judgement_id,
        rationale="candidate synthesized from judgement consensus and existing EvidenceCard refs",
    )
    now = datetime.now(timezone.utc)
    store.upsert_candidate(
        CandidateDemand(
            candidate_id=draft.candidate_id,
            title=draft.title,
            demand_statement=draft.demand_statement,
            status="candidate_demand",
            evidence_ids=list(draft.evidence_ids),
            open_questions=list(draft.open_questions),
            solution_signals=list(draft.solution_signals),
            created_by="candidate_synthesis",
            created_at=now,
            updated_at=now,
        )
    )
    return draft


def _existing_consensus_evidence_ids(
    judgement: JudgementReport,
    store: DomainStore,
) -> list[str]:
    rows: list[str] = []
    for item in judgement.consensus_points:
        for evidence_id in item.evidence_ids:
            if evidence_id in rows:
                continue
            if not evidence_can_support_candidate_synthesis(
                store,
                evidence_id,
                evidence_strength_map=judgement.evidence_strength_map,
            ):
                continue
            if evidence_id in store.evidence:
                rows.append(evidence_id)
    return rows


def _title_from_consensus(text: str) -> str:
    compact = text.strip() or "Autonomous research candidate"
    return compact[:48]


def _chinese_candidate_text(
    text: str,
    *,
    topic: str,
    evidence_ids: list[str],
) -> str:
    compact = text.strip()
    if _has_cjk(compact):
        return compact
    if _has_cjk(topic):
        refs = "、".join(evidence_ids)
        suffix = f"（证据：{refs}）" if refs else ""
        return (
            f"围绕“{topic}”，已有正文证据指向该方向存在需要继续核验的能力缺口；"
            f"应进一步明确任务场景、现有能力不足、约束条件和可审计补证路径{suffix}。"
        )
    return compact


def _round_topic(judgement: JudgementReport, store: DomainStore) -> str:
    research_round = store.research_rounds.get(judgement.round_id)
    if research_round is not None:
        return research_round.topic
    return ""


def _has_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
