from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.candidate_synthesis import (  # noqa: E402
    synthesize_candidate_from_judgement,
)
from knowledgegraph.demand_discovery.domain.judgement import JudgementItem, JudgementReport  # noqa: E402
from knowledgegraph.demand_discovery.domain.models import EvidenceCard, SourceRecord  # noqa: E402
from knowledgegraph.demand_discovery.domain.research_state import ResearchRound  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


class DemandDiscoveryCandidateSynthesisTests(unittest.TestCase):
    def test_synthesizes_candidate_only_from_existing_evidence_refs(self) -> None:
        store = _store_with_evidence()
        judgement = _judgement(evidence_ids=["ev-1"])

        draft = synthesize_candidate_from_judgement(judgement, store)

        self.assertEqual(draft.status, "synthesized")
        self.assertEqual(draft.evidence_ids, ["ev-1"])
        self.assertEqual(draft.judgement_id, "judge-1")
        self.assertIn(draft.candidate_id, store.candidates)
        self.assertEqual(store.candidates[draft.candidate_id].evidence_ids, ["ev-1"])

    def test_refuses_candidate_when_consensus_has_no_existing_evidence_refs(self) -> None:
        store = _store_with_evidence()
        judgement = _judgement(evidence_ids=["ev-missing"])

        draft = synthesize_candidate_from_judgement(judgement, store)

        self.assertEqual(draft.status, "needs_more_evidence")
        self.assertEqual(draft.candidate_id, "")
        self.assertEqual(store.candidates, {})

    def test_refuses_candidate_when_consensus_evidence_is_only_adjacent_or_weak(self) -> None:
        store = _store_with_evidence(
            evidence_assessment=(
                "中等偏弱：正文证据明确，但为相邻材料，不直接证明当前调研主题"
            )
        )
        judgement = _judgement(
            evidence_ids=["ev-1"],
            evidence_strength_map={
                "ev-1": (
                    "中等偏弱：正文证据明确，但为相邻材料，"
                    "不直接证明当前调研主题"
                )
            },
        )

        draft = synthesize_candidate_from_judgement(judgement, store)

        self.assertEqual(draft.status, "needs_more_evidence")
        self.assertEqual(draft.candidate_id, "")
        self.assertEqual(draft.evidence_ids, [])
        self.assertEqual(store.candidates, {})
        self.assertIn("direct or partial", draft.rationale)

    def test_synthesizes_candidate_from_chinese_strong_evidence_labels(self) -> None:
        store = _store_with_evidence(
            evidence_assessment=(
                "较强：政策原文转载，覆盖能力缺口清单；但仍需交叉验证"
            )
        )
        judgement = _judgement(
            evidence_ids=["ev-1"],
            evidence_strength_map={
                "ev-1": "中等偏强：政府官网转载发布会报道，能支撑应急响应难点"
            },
        )

        draft = synthesize_candidate_from_judgement(judgement, store)

        self.assertEqual(draft.status, "synthesized")
        self.assertEqual(draft.evidence_ids, ["ev-1"])
        self.assertIn(draft.candidate_id, store.candidates)

    def test_synthesizes_candidate_from_moderate_partial_evidence_for_audit(self) -> None:
        store = _store_with_evidence(
            evidence_assessment=(
                "moderate：正文直接相关，但仍需要独立来源交叉验证"
            )
        )
        judgement = _judgement(
            evidence_ids=["ev-1"],
            evidence_strength_map={
                "ev-1": "moderate：正文支持能力缺口，但需进一步审计"
            },
        )

        draft = synthesize_candidate_from_judgement(judgement, store)

        self.assertEqual(draft.status, "synthesized")
        self.assertEqual(draft.evidence_ids, ["ev-1"])
        self.assertIn(draft.candidate_id, store.candidates)

    def test_synthesized_candidate_uses_chinese_statement_for_english_consensus(self) -> None:
        store = _store_with_evidence()
        store.upsert_research_round(
            ResearchRound(
                round_id="round-1",
                run_id="run-1",
                index=1,
                topic="高寒地区联合救援保障能力缺口",
                hypothesis="验证高寒地区联合救援保障能力缺口",
                source_strategy_id="strategy-1",
                worker_report_ids=["agent-1", "agent-2"],
                judgement_id="judge-1",
                next_round_plan={},
                stop_reason="max_rounds",
                status="stopped",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        judgement = JudgementReport(
            judgement_id="judge-1",
            round_id="round-1",
            consensus_points=[
                JudgementItem(
                    text="cold-region joint rescue support capability gap",
                    worker_report_ids=["agent-1", "agent-2"],
                    evidence_ids=["ev-1"],
                    lead_ids=["lead-1"],
                )
            ],
            contradictions=[],
            partial_coverage=[],
            unique_insights=[],
            blind_spots=[],
            evidence_strength_map={"ev-1": "strong"},
            next_round_plan={},
            stop_or_continue="stop",
            rationale="max rounds reached",
            created_at=NOW,
        )

        draft = synthesize_candidate_from_judgement(judgement, store)

        self.assertIn("高寒地区联合救援保障能力缺口", draft.demand_statement)
        self.assertIn("已有正文证据", draft.demand_statement)
        self.assertFalse(draft.demand_statement.startswith("cold-region"))
        self.assertIn("高寒地区联合救援保障能力缺口", store.candidates[draft.candidate_id].title)


def _store_with_evidence(*, evidence_assessment: str = "strong") -> DomainStore:
    store = DomainStore()
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="低空无人机防护",
            source_name="Fixture",
            source_tier="A",
            source_type="official",
            publish_time=NOW,
            url_or_path="https://example.test/article",
            summary_text="summary",
            summary_source="manual",
            collection_decision="use_as_evidence",
            author_or_org=None,
            is_repost=False,
            original_source=None,
            institutional_stance=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_evidence(
        EvidenceCard(
            evidence_id="ev-1",
            source_id="src-1",
            claim="需要多源探测和快速告警",
            evidence_summary="低空无人机压缩预警时间。",
            excerpt="低空小型无人机压缩预警时间，需要多源探测。",
            source_location="text:abc#para:0",
            evidence_assessment=evidence_assessment,
            created_by="reader",
            created_at=NOW,
        )
    )
    return store


def _judgement(
    evidence_ids: list[str],
    *,
    evidence_strength_map: dict[str, str] | None = None,
) -> JudgementReport:
    return JudgementReport(
        judgement_id="judge-1",
        round_id="round-1",
        consensus_points=[
            JudgementItem(
                text="需要多源探测和快速告警",
                worker_report_ids=["agent-1", "agent-2"],
                evidence_ids=evidence_ids,
                lead_ids=["lead-1"],
            )
        ],
        contradictions=[],
        partial_coverage=[],
        unique_insights=[],
        blind_spots=[
            JudgementItem(text="缺少处置链路", worker_report_ids=["agent-1"], lead_ids=["lead-1"])
        ],
        evidence_strength_map=(
            evidence_strength_map
            if evidence_strength_map is not None
            else {evidence_id: "strong" for evidence_id in evidence_ids}
        ),
        next_round_plan={"queries": ["处置链路"]},
        stop_or_continue="stop",
        rationale="max rounds reached",
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
