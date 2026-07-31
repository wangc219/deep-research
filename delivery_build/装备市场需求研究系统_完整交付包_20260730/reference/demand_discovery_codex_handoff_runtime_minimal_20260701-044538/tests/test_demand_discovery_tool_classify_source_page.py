from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "demand_discovery_pages"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.tools import ToolExecutionContext  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import ToolCall  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.discovery import create_classify_source_page_tool  # noqa: E402


class DemandDiscoveryClassifySourcePageToolTests(unittest.TestCase):
    def test_classifies_article_listing_download_and_unknown_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactStore(Path(tmp))
            article_ref = artifacts.put(
                (FIXTURE_ROOT / "article_with_pdf.html").read_text(encoding="utf-8"),
                kind="html",
                meta={"url": "https://example.test/articles/cuas.html"},
            )
            listing_ref = artifacts.put(
                (FIXTURE_ROOT / "listing_with_articles.html").read_text(encoding="utf-8"),
                kind="html",
                meta={"url": "https://example.test/listing.html"},
            )
            empty_ref = artifacts.put("<html><body></body></html>", kind="html", meta={})
            tool = create_classify_source_page_tool(artifacts)

            article = _run(tool, {"artifact_ref": article_ref, "topic": "低空无人机"})
            listing = _run(tool, {"artifact_ref": listing_ref, "topic": "低空无人机"})
            pdf = _run(tool, {"url": "https://example.test/downloads/report.pdf", "topic": "低空无人机"})
            unknown = _run(tool, {"artifact_ref": empty_ref, "topic": "低空无人机"})

        self.assertEqual(article.details["page_type"], "article")
        self.assertEqual(listing.details["page_type"], "listing")
        self.assertEqual(pdf.details["page_type"], "download_document")
        self.assertEqual(unknown.details["page_type"], "unknown")
        self.assertGreaterEqual(listing.details["candidate_link_count"], 3)


def _run(tool, args):
    return asyncio.run(tool.execute(ToolCall("call-1", tool.name, args), _ctx()))


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext("run-1", "agent-1", "reader", {})


if __name__ == "__main__":
    unittest.main()
