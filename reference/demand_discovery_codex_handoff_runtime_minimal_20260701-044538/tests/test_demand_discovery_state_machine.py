from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    CandidateDemand,
    DomainTraceEvent,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.state_machine import (  # noqa: E402
    InvalidTransition,
    validate_transition,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


NOW = datetime(2026, 6, 11, tzinfo=timezone.utc)


class DemandDiscoveryStateMachineTests(unittest.TestCase):
    def test_validate_transition_accepts_known_legal_edges(self) -> None:
        validate_transition("raw_signal", "researchable_signal")
        validate_transition("researchable_signal", "candidate_demand")
        validate_transition("candidate_demand", "demand_report")
        validate_transition("demand_report", "candidate_demand")

    def test_validate_transition_rejects_terminal_revival(self) -> None:
        with self.assertRaises(InvalidTransition):
            validate_transition("discarded_signal", "candidate_demand")
        with self.assertRaises(InvalidTransition):
            validate_transition("human_reviewed", "demand_report")

    def test_store_rejects_illegal_candidate_status_change(self) -> None:
        store = _seed_store(source_tier="A")
        store.upsert_candidate(_candidate("cand-1", "discarded_signal"))

        with self.assertRaises(InvalidTransition):
            store.upsert_candidate(_candidate("cand-1", "candidate_demand"))

    def test_tier_status_cap_limits_candidate_status(self) -> None:
        def cap(tier: str) -> str:
            return {"C": "researchable_signal", "B": "candidate_demand"}.get(
                tier, "demand_report"
            )

        store = _seed_store(source_tier="C", tier_status_cap=cap)

        with self.assertRaises(ValueError):
            store.upsert_candidate(_candidate("cand-c", "candidate_demand"))

        accepted = store.upsert_candidate(_candidate("cand-c", "researchable_signal"))
        self.assertEqual(accepted.status, "researchable_signal")

    def test_registry_views_list_signals_and_parked_watchlist(self) -> None:
        store = _seed_store(source_tier="A")
        store.upsert_candidate(_candidate("cand-weak", "weak_signal"))
        store.upsert_candidate(_candidate("cand-research", "researchable_signal"))
        store.append_trace(
            DomainTraceEvent(
                domain_trace_id="dt-1",
                trace_id="trace-1",
                event_type="signal_parked",
                actor="tester",
                target_type="CandidateDemand",
                target_id="cand-weak",
                input_refs=["ev-1"],
                output_refs=["cand-weak"],
                summary="parked for review",
                decision="weak_signal",
                rationale="needs stronger source",
                model=None,
                prompt_id=None,
                tool_refs=[],
                runtime_event_id=None,
                created_at=NOW,
                payload={"recheck_conditions": ["new A/B source"]},
            )
        )

        self.assertEqual(
            [item.candidate_id for item in store.list_signals({"weak_signal"})],
            ["cand-weak"],
        )
        watchlist = store.watchlist_view()
        self.assertEqual(len(watchlist), 1)
        self.assertEqual(watchlist[0]["candidate_id"], "cand-weak")
        self.assertEqual(watchlist[0]["recheck_conditions"], ["new A/B source"])


def _seed_store(source_tier: str, tier_status_cap=None) -> DomainStore:
    store = DomainStore(tier_status_cap=tier_status_cap)
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source title",
            source_name="Source",
            source_tier=source_tier,
            source_type="journal",
            publish_time=NOW,
            url_or_path="https://example.test/source",
            summary_text="summary",
            summary_source="structured",
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
            claim="claim",
            evidence_summary="summary",
            excerpt="excerpt",
            source_location="p1",
            evidence_assessment="strong",
            created_by="tester",
            created_at=NOW,
        )
    )
    return store


def _candidate(candidate_id: str, status: str) -> CandidateDemand:
    return CandidateDemand(
        candidate_id=candidate_id,
        title="Candidate",
        demand_statement="Need capability.",
        status=status,
        evidence_ids=["ev-1"],
        open_questions=[],
        solution_signals=[],
        created_by="tester",
        created_at=NOW,
        updated_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
