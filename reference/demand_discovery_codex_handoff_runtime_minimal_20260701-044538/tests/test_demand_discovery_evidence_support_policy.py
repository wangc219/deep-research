from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.evidence_support import (  # noqa: E402
    core_conclusion_support_status,
    normalize_support_level,
    validate_evidence_support_scorecard,
)


class EvidenceSupportPolicyTests(unittest.TestCase):
    def test_normalizes_legacy_and_unknown_assessment_values(self) -> None:
        self.assertEqual(normalize_support_level("direct"), "direct")
        self.assertEqual(normalize_support_level("strong"), "direct")
        self.assertEqual(normalize_support_level("weak"), "weak")
        self.assertEqual(normalize_support_level(""), "unassessed")
        self.assertEqual(normalize_support_level("not-a-level"), "unassessed")

    def test_normalizes_explanatory_legacy_assessment_text(self) -> None:
        self.assertEqual(
            normalize_support_level("strong; official strategy source"),
            "direct",
        )
        self.assertEqual(
            normalize_support_level("medium-strong; oversight source"),
            "direct",
        )
        self.assertEqual(
            normalize_support_level("中等偏弱：相邻材料，不直接证明当前调研主题"),
            "weak",
        )

    def test_direct_or_two_partial_from_different_sources_can_support_review_ready(self) -> None:
        self.assertEqual(
            core_conclusion_support_status(
                [
                    {
                        "evidence_id": "ev-1",
                        "support_level": "direct",
                        "used_for_core": True,
                    }
                ],
                evidence_map={"ev-1": {"source_id": "src-a", "source_location": "text:a#p1"}},
            ),
            "supported",
        )
        self.assertEqual(
            core_conclusion_support_status(
                [
                    {
                        "evidence_id": "ev-1",
                        "support_level": "partial",
                        "used_for_core": True,
                    },
                    {
                        "evidence_id": "ev-2",
                        "support_level": "partial",
                        "used_for_core": True,
                    },
                ],
                evidence_map={
                    "ev-1": {"source_id": "src-a", "source_location": "text:a#p1"},
                    "ev-2": {"source_id": "src-b", "source_location": "text:b#p1"},
                },
            ),
            "supported_with_reasoning",
        )

    def test_two_partial_from_same_source_cannot_support_review_ready(self) -> None:
        self.assertEqual(
            core_conclusion_support_status(
                [
                    {
                        "evidence_id": "ev-1",
                        "support_level": "partial",
                        "used_for_core": True,
                    },
                    {
                        "evidence_id": "ev-2",
                        "support_level": "partial",
                        "used_for_core": True,
                    },
                ],
                evidence_map={
                    "ev-1": {"source_id": "src-a", "source_location": "text:a#p1"},
                    "ev-2": {"source_id": "src-a", "source_location": "text:a#p2"},
                },
            ),
            "unsupported",
        )
        self.assertEqual(
            core_conclusion_support_status(
                [
                    {
                        "evidence_id": "ev-1",
                        "support_level": "partial",
                        "used_for_core": True,
                    },
                    {
                        "evidence_id": "ev-2",
                        "support_level": "partial",
                        "used_for_core": True,
                    },
                ],
                evidence_map={
                    "ev-1": {"source_id": "src-a", "source_location": "text:a#p1"},
                    "ev-2": {"source_id": "src-a", "source_location": "text:b#p1"},
                },
            ),
            "unsupported",
        )

    def test_adjacent_weak_or_unassessed_cannot_support_core_conclusion(self) -> None:
        self.assertEqual(
            core_conclusion_support_status(
                [
                    {"evidence_id": "ev-1", "support_level": "adjacent", "used_for_core": True},
                    {"evidence_id": "ev-2", "support_level": "weak", "used_for_core": True},
                ],
                evidence_map={
                    "ev-1": {"source_id": "src-a", "source_location": "text:a#p1"},
                    "ev-2": {"source_id": "src-b", "source_location": "text:b#p1"},
                },
            ),
            "unsupported",
        )
        self.assertEqual(
            core_conclusion_support_status(
                [{"evidence_id": "ev-3", "support_level": "unassessed", "used_for_core": True}],
                evidence_map={"ev-3": {"source_id": "src-c", "source_location": "text:c#p1"}},
            ),
            "unassessed",
        )

    def test_scorecard_requires_review_for_every_report_evidence(self) -> None:
        scorecard = {
            "evidence_support": {
                "verdict": "pass",
                "reason": "direct body evidence supports candidate",
                "evidence_reviews": {
                    "ev-1": {
                        "support_level": "direct",
                        "support_type": "inferred_gap",
                        "used_for_core": True,
                        "reason": "正文说明能力缺口",
                        "missing_link": "",
                    }
                },
            }
        }

        errors = validate_evidence_support_scorecard(scorecard, evidence_ids=["ev-1"])

        self.assertEqual(errors, [])
        missing = validate_evidence_support_scorecard(scorecard, evidence_ids=["ev-1", "ev-2"])
        self.assertIn("missing evidence review for ev-2", missing)


if __name__ == "__main__":
    unittest.main()
