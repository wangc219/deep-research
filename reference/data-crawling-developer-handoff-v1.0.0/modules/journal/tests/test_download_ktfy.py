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

import download_ktfy  # noqa: E402


ARCHIVE_HTML = """
<a href="/ktfy/cn/article/2025/2">2025年第2期</a>
<a href="/ktfy/cn/article/2025/1">2025年第1期</a>
<a href="/ktfy/article/2025/1">第 1 期</a>
"""

ISSUE_HTML = """
<a href="/ktfy/article/id/article-a">第一篇论文标题</a>
<a href="javascript:void(0);" onclick="downloadpdf('article-a')">PDF下载</a>
<a href="/ktfy/article/id/article-b">
  <img alt="第二篇论文标题" src="/cover.png">
</a>
<a href="javascript:void(0);" onclick="downloadpdf('article-b')">PDF下载</a>
<a href="/ktfy/article/id/{{article.id}}">{{article.titleCn}}</a>
<a href="javascript:void(0);" onclick="downloadpdf('{{article.id}}')">PDF下载</a>
"""

CATALOG_MAP = {
    "data": {
        "archive_list": {
            "2025": [
                {"year": "2025", "issue": "2"},
                {"year": "2025", "issue": "1"},
            ]
        }
    }
}


class DownloadKtfyTests(unittest.TestCase):
    def test_select_issue_url_matches_year_and_numeric_issue(self) -> None:
        issue_url = download_ktfy.select_issue_url(ARCHIVE_HTML, year="2025", issue="1")

        self.assertEqual(issue_url, "https://www.spacejournal.cn/ktfy/cn/article/2025/1")

    def test_parse_issues_from_catalog_map_api_payload(self) -> None:
        issues = download_ktfy.parse_issues_from_catalog_map(CATALOG_MAP)

        self.assertEqual(
            [(issue.year, issue.issue, issue.url) for issue in issues],
            [
                ("2025", "02", "https://www.spacejournal.cn/ktfy/cn/article/2025/2"),
                ("2025", "01", "https://www.spacejournal.cn/ktfy/cn/article/2025/1"),
            ],
        )

    def test_parse_papers_pairs_download_ids_with_titles(self) -> None:
        papers = download_ktfy.parse_papers(
            ISSUE_HTML,
            source_page="https://www.spacejournal.cn/ktfy/cn/article/2025/1",
        )

        self.assertEqual([paper.article_id for paper in papers], ["article-a", "article-b"])
        self.assertEqual([paper.title for paper in papers], ["第一篇论文标题", "第二篇论文标题"])
        self.assertEqual(
            [paper.article_page for paper in papers],
            [
                "https://www.spacejournal.cn/ktfy/article/id/article-a",
                "https://www.spacejournal.cn/ktfy/article/id/article-b",
            ],
        )

    def test_main_uses_year_and_issue_to_discover_papers(self) -> None:
        def fake_request_text(url: str, headers: dict[str, str] | None = None) -> str:
            if url == "https://www.spacejournal.cn/ktfy/archive_list":
                return ARCHIVE_HTML
            if url == "https://www.spacejournal.cn/ktfy/cn/article/2025/1":
                return ISSUE_HTML
            raise AssertionError(f"unexpected URL: {url}")

        with (
            patch.object(download_ktfy, "request_text", side_effect=fake_request_text),
            redirect_stdout(StringIO()) as stdout,
        ):
            exit_code = download_ktfy.main(
                ["--year", "2025", "--issue", "1", "--max-papers", "-1", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([item["article_id"] for item in payload], ["article-a", "article-b"])

    def test_main_skips_manifest_completed_article_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "manifest.jsonl"
            manifest.write_text(
                json.dumps({"status": "downloaded", "paper": {"article_id": "article-a"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            with (
                patch.object(download_ktfy, "download_pdf") as download_pdf,
                redirect_stdout(StringIO()) as stdout,
            ):
                exit_code = download_ktfy.main(
                    [
                        "--article-id",
                        "article-a",
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
