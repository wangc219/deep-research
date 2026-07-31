from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.documents import (  # noqa: E402
    create_extract_summary_tool,
    create_read_document_tool,
)


class DemandDiscoveryReadDocumentToolTests(unittest.TestCase):
    def test_read_document_returns_paragraph_window_and_continuation_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            ref = artifacts.put(
                "para 0\n\npara 1\n\npara 2\n\npara 3",
                kind="text",
                meta={"url": "https://example.test/a"},
            )
            tool = create_read_document_tool(artifacts)

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        id="call-1",
                        name="read_document",
                        arguments={"artifact_ref": ref, "offset": 1, "limit": 2},
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertIn("[para:1] para 1", result.content)
        self.assertIn("[para:2] para 2", result.content)
        self.assertIn("剩余 1 段", result.content)
        self.assertEqual(result.details["returned_range"], [1, 3])
        self.assertTrue(result.details["truncated"])
        self.assertEqual(result.domain_proposals, [])

    def test_extract_summary_marks_model_generated_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            ref = artifacts.put(
                "低空探测存在短板。\n\n需要融合预警能力。",
                kind="text",
                meta={},
            )
            tool = create_extract_summary_tool(artifacts)

            result = asyncio.run(
                tool.execute(
                    ToolCall(
                        "call-1",
                        "extract_summary",
                        {"artifact_ref": ref, "max_chars": 10},
                    ),
                    _ctx(),
                )
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.details["summary_source"], "model_generated")
        self.assertLessEqual(len(result.details["summary_text"]), 10)


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "worker-1", {})


if __name__ == "__main__":
    unittest.main()
