from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.audit_rubric import (  # noqa: E402
    load_rubric,
)
from knowledgegraph.demand_discovery.domain.models import CandidateDemand  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import (  # noqa: E402
    build_domain_tools,
    run_audit_tool,
)
from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402


class DemandDiscoveryAuditRubricTests(unittest.TestCase):
    def test_load_rubric_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rubric.json"
            path.write_text(
                """{"version": 1,
 "veto_items": [{"id": "no_source", "question": "source?"}],
 "check_items": [{"id": "gap_clear", "question": "gap?"}]}""",
                encoding="utf-8",
            )

            rubric = load_rubric(path)

            self.assertEqual(rubric.item_ids, ["no_source", "gap_clear"])

    def test_run_audit_rejects_missing_rubric_items(self) -> None:
        store = _store_with_candidate()
        rubric = load_rubric.from_dict(
            {
                "version": 1,
                "veto_items": [{"id": "no_source", "question": "source?"}],
                "check_items": [{"id": "gap_clear", "question": "gap?"}],
            }
        )
        tool = run_audit_tool(store, rubric=rubric)

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "audit",
                    "run_audit",
                    {
                        "audit_id": "audit-1",
                        "candidate_id": "cand-1",
                        "conclusion": "approved",
                        "scorecard": {
                            "no_source": {"verdict": "pass", "reason": "ok"}
                        },
                    },
                ),
                ToolExecutionContext("run", "agent", "auditor"),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("missing rubric scorecard item", result.content)

    def test_veto_fail_forces_rejected_conclusion(self) -> None:
        store = _store_with_candidate()
        rubric = load_rubric.from_dict(
            {
                "version": 1,
                "veto_items": [{"id": "no_source", "question": "source?"}],
                "check_items": [{"id": "gap_clear", "question": "gap?"}],
            }
        )
        tool = run_audit_tool(store, rubric=rubric)

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "audit",
                    "run_audit",
                    {
                        "audit_id": "audit-1",
                        "candidate_id": "cand-1",
                        "conclusion": "approved",
                        "scorecard": {
                            "no_source": {"verdict": "fail", "reason": "none"},
                            "gap_clear": {"verdict": "pass", "reason": "clear"},
                        },
                    },
                ),
                ToolExecutionContext("run", "agent", "auditor"),
            )
        )

        self.assertFalse(result.is_error)
        proposal = result.domain_proposals[0]
        self.assertEqual(proposal.payload["conclusion"], "rejected")

    def test_build_domain_tools_loads_default_rubric_for_audit(self) -> None:
        store = _store_with_candidate()
        tool = _get_tool(build_domain_tools(store), "run_audit")

        scorecard_schema = tool.parameters_schema["properties"]["scorecard"]
        self.assertIn("no_traceable_source", scorecard_schema["required"])

        result = asyncio.run(
            tool.execute(
                ToolCall(
                    "audit",
                    "run_audit",
                    {
                        "audit_id": "audit-default",
                        "candidate_id": "cand-1",
                        "conclusion": "approved",
                        "scorecard": {},
                    },
                ),
                ToolExecutionContext("run", "agent", "auditor"),
            )
        )

        self.assertTrue(result.is_error)
        self.assertIn("missing rubric scorecard item", result.content)


def _store_with_candidate() -> DomainStore:
    store = DomainStore()
    now = datetime.now(timezone.utc)
    store.upsert_candidate(
        CandidateDemand(
            candidate_id="cand-1",
            title="Candidate",
            demand_statement="Need",
            status="candidate_demand",
            evidence_ids=[],
            open_questions=[],
            solution_signals=[],
            created_by="test",
            created_at=now,
            updated_at=now,
        )
    )
    return store


def _get_tool(tools, name: str):
    for tool in tools:
        if tool.name == name:
            return tool
    raise AssertionError(f"missing tool {name}")


if __name__ == "__main__":
    unittest.main()
