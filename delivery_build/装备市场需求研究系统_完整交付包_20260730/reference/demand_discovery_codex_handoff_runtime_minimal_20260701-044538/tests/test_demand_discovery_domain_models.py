from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    AuditReport,
    CandidateDemand,
    DemandReport,
    DomainTraceEvent,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)


def _source(source_id: str = "src-1") -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        title="Source title",
        source_name="Journal",
        source_tier="A",
        source_type="journal",
        publish_time=NOW,
        url_or_path="https://example.test/source",
        summary_text="summary",
        summary_source="structured_abstract",
        collection_decision="use_as_evidence",
        author_or_org="org",
        is_repost=False,
        original_source=None,
        institutional_stance="official",
        created_at=NOW,
        updated_at=NOW,
    )


def _evidence(evidence_id: str = "ev-1", source_id: str = "src-1") -> EvidenceCard:
    return EvidenceCard(
        evidence_id=evidence_id,
        source_id=source_id,
        claim="capability gap claim",
        evidence_summary="evidence summary",
        excerpt="quoted excerpt",
        source_location="p1",
        evidence_assessment="strong",
        created_by="tester",
        created_at=NOW,
    )


def _candidate(
    candidate_id: str = "cand-1",
    evidence_ids: list[str] | None = None,
    status: str = "candidate_demand",
) -> CandidateDemand:
    return CandidateDemand(
        candidate_id=candidate_id,
        title="Candidate Demand",
        demand_statement="Need better capability for this scenario.",
        status=status,
        evidence_ids=evidence_ids or ["ev-1"],
        open_questions=["what scenario?"],
        solution_signals=["known concept"],
        created_by="tester",
        created_at=NOW,
        updated_at=NOW,
    )


class DemandDiscoveryDomainModelsTests(unittest.TestCase):
    def test_domain_objects_serialize_to_dict(self) -> None:
        trace = DomainTraceEvent(
            domain_trace_id="dt-1",
            trace_id="trace-1",
            event_type="candidate_created",
            actor="tester",
            target_type="CandidateDemand",
            target_id="cand-1",
            input_refs=["ev-1"],
            output_refs=["cand-1"],
            summary="created candidate",
            decision=None,
            rationale=None,
            model=None,
            prompt_id=None,
            tool_refs=[],
            runtime_event_id=None,
            created_at=NOW,
        )
        audit = AuditReport(
            audit_id="audit-1",
            candidate_id="cand-1",
            conclusion="approved",
            scorecard={"evidence": "ok"},
            comments="looks valid",
            required_rework=[],
            created_by="auditor",
            created_at=NOW,
        )
        report = DemandReport(
            report_id="report-1",
            candidate_id="cand-1",
            title="Report",
            body="body",
            evidence_ids=["ev-1"],
            audit_id="audit-1",
            domain_trace_ids=["dt-1"],
            created_at=NOW,
        )

        for obj in [_source(), _evidence(), _candidate(), trace, audit, report]:
            data = obj.to_dict()
            self.assertIsInstance(data, dict)
            self.assertIn(next(iter(data)), data)

        self.assertEqual(_source().to_dict()["publish_time"], NOW.isoformat())

    def test_core_field_names_match_discussion_schema(self) -> None:
        self.assertEqual(
            set(_source().to_dict()),
            {
                "source_id",
                "title",
                "source_name",
                "source_tier",
                "source_type",
                "publish_time",
                "url_or_path",
                "summary_text",
                "summary_source",
                "collection_decision",
                "author_or_org",
                "is_repost",
                "original_source",
                "institutional_stance",
                "open_source_lead_id",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(
            set(_candidate().to_dict()),
            {
                "candidate_id",
                "title",
                "demand_statement",
                "status",
                "evidence_ids",
                "open_questions",
                "solution_signals",
                "created_by",
                "created_at",
                "updated_at",
                "superseded_by",
                "superseded_reason",
            },
        )


class DemandDiscoveryDomainStoreTests(unittest.TestCase):
    def test_candidate_evidence_ids_must_exist(self) -> None:
        store = DomainStore()
        store.upsert_source(_source())
        store.upsert_evidence(_evidence())

        store.upsert_candidate(_candidate(evidence_ids=["ev-1"]))

        with self.assertRaises(ValueError):
            store.upsert_candidate(_candidate("cand-2", evidence_ids=["missing"]))

    def test_candidate_status_moves_by_appending_trace(self) -> None:
        store = DomainStore()
        store.upsert_source(_source())
        store.upsert_evidence(_evidence())
        store.upsert_candidate(_candidate(status="candidate_demand"))

        store.update_candidate_status(
            "cand-1", "demand_report", "promoted", actor="tester"
        )
        store.update_candidate_status(
            "cand-1", "candidate_demand", "rollback", actor="tester"
        )

        self.assertEqual(store.get_candidate("cand-1").status, "candidate_demand")
        self.assertEqual(
            [event.event_type for event in store.trace_events],
            ["candidate_status_changed", "candidate_status_changed"],
        )

    def test_merged_candidates_are_superseded_not_removed(self) -> None:
        store = DomainStore()
        store.upsert_source(_source())
        store.upsert_evidence(_evidence())
        store.upsert_candidate(_candidate("cand-1"))
        store.upsert_candidate(_candidate("cand-2"))

        store.merge_candidate("cand-2", surviving_candidate_id="cand-1", actor="tester")

        merged = store.get_candidate("cand-2")
        self.assertEqual(merged.superseded_by, "cand-1")
        self.assertIn("cand-2", [c.candidate_id for c in store.list_candidates()])

    def test_jsonl_export_writes_domain_objects(self) -> None:
        store = DomainStore()
        store.upsert_source(_source())
        store.upsert_evidence(_evidence())
        store.upsert_candidate(_candidate())

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "domain.jsonl"
            store.export_jsonl(path)
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(
            [row["type"] for row in rows],
            ["SourceRecord", "EvidenceCard", "CandidateDemand"],
        )


if __name__ == "__main__":
    unittest.main()
