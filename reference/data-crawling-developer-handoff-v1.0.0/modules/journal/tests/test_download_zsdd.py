from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "journal"))

import download_zsdd  # noqa: E402


ISSUE_HTML = """
<a onclick="guokanTurnPageList('2026','01','year-a','issue-a')">2026-01</a>
<a onclick="guokanTurnPageList('2026','02','year-b','issue-b')">2026-02</a>
"""


class DownloadZsddTests(unittest.TestCase):
    def test_select_issue_url_matches_numeric_issue(self) -> None:
        issue_url = download_zsdd.select_issue_url(ISSUE_HTML, year="2026", issue="2")

        self.assertEqual(
            issue_url,
            "https://zsdd.cbpt.cnki.net/portal/journal/portal/client/guokan_list"
            "?year=2026&issue=02&yearId=year-b&issueId=issue-b",
        )

    def test_main_uses_year_and_issue_to_seed_paper_discovery(self) -> None:
        with (
            patch.object(download_zsdd, "request_text", return_value=ISSUE_HTML),
            patch.object(download_zsdd, "discover_papers", return_value=[]) as discover,
            redirect_stdout(StringIO()),
        ):
            exit_code = download_zsdd.main(
                [
                    "--year",
                    "2026",
                    "--issue",
                    "2",
                    "--dry-run",
                    "--max-papers",
                    "-1",
                ]
            )

        self.assertEqual(exit_code, 0)
        discover.assert_called_once_with(
            seed_urls=[
                "https://zsdd.cbpt.cnki.net/portal/journal/portal/client/guokan_list"
                "?year=2026&issue=02&yearId=year-b&issueId=issue-b"
            ],
            max_issues=0,
        )

    def test_main_skips_manifest_completed_content_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "manifest.jsonl"
            manifest.write_text(
                json.dumps({"status": "downloaded", "paper": {"content_id": "paper-a"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            with (
                patch.object(download_zsdd, "download_pdf") as download_pdf,
                redirect_stdout(StringIO()) as stdout,
            ):
                exit_code = download_zsdd.main(
                    [
                        "--content-id",
                        "paper-a",
                        "--title",
                        "第一篇",
                        "--output-dir",
                        str(Path(tmpdir) / "papers"),
                        "--manifest",
                        str(manifest),
                    ]
                )

        self.assertEqual(exit_code, 0)
        download_pdf.assert_not_called()
        self.assertEqual(json.loads(stdout.getvalue())["status"], "skipped_manifest")


if __name__ == "__main__":
    unittest.main()
