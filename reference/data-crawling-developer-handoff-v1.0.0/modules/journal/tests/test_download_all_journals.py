from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "journal"))

import download_all_journals as batch  # noqa: E402
import download_xxdkjs  # noqa: E402


class DownloadAllJournalsTests(unittest.TestCase):
    def test_parse_wanfang_year_issue_response_extracts_normalized_issues(self) -> None:
        message = (
            b"\x1a\x0f\n\x042022\x12\x011\x12\x012\x12\x013"
            b"\x1a\x15\n\x042023\x12\x011\x12\x012\x12\x013\x12\x014\x12\x016"
        )
        response = b"\x00" + len(message).to_bytes(4, "big") + message

        issues = batch.parse_wanfang_year_issue_response(response, journal_slug="xxdkjs")

        self.assertEqual(
            [(issue.journal_slug, issue.year, issue.issue) for issue in issues],
            [
                ("xxdkjs", "2022", "01"),
                ("xxdkjs", "2022", "02"),
                ("xxdkjs", "2022", "03"),
                ("xxdkjs", "2023", "01"),
                ("xxdkjs", "2023", "02"),
                ("xxdkjs", "2023", "03"),
                ("xxdkjs", "2023", "04"),
                ("xxdkjs", "2023", "06"),
            ],
        )

    def test_filter_issues_applies_journal_and_year_bounds(self) -> None:
        issues = [
            batch.IssueTarget("zsdd", "2024", "01"),
            batch.IssueTarget("xxdkjs", "2025", "01"),
            batch.IssueTarget("xxdkjs", "2026", "02"),
        ]

        selected = batch.filter_issues(issues, journals={"xxdkjs"}, start_year=2025, end_year=2025)

        self.assertEqual(selected, [batch.IssueTarget("xxdkjs", "2025", "01")])

    def test_run_issue_download_uses_issue_directory_paths(self) -> None:
        issue = batch.IssueTarget("xxdkjs", "2026", "01")

        with patch.object(download_xxdkjs, "main", return_value=0) as main:
            result = batch.run_issue_download(issue, max_papers=-1, paper_sleep=0.5)

        self.assertEqual(result.status, "ok")
        main.assert_called_once_with(
            [
                "--year",
                "2026",
                "--issue",
                "01",
                "--max-papers",
                "-1",
                "--sleep",
                "0.5",
                "--output-dir",
                "data/raw/xxdkjs/2026-01/papers",
                "--manifest",
                "data/raw/xxdkjs/2026-01/manifest.jsonl",
            ]
        )

    def test_run_issue_download_maps_custom_output_root(self) -> None:
        issue = batch.IssueTarget("xxdkjs", "2026", "01")
        output_root = Path("D:/handoff-data/raw")

        with patch.object(download_xxdkjs, "main", return_value=0) as main:
            result = batch.run_issue_download(
                issue,
                max_papers=1,
                paper_sleep=0,
                output_root=output_root,
            )

        self.assertEqual(result.status, "ok")
        main.assert_called_once_with(
            [
                "--year",
                "2026",
                "--issue",
                "01",
                "--max-papers",
                "1",
                "--sleep",
                "0",
                "--output-dir",
                (output_root / "xxdkjs" / "2026-01" / "papers").as_posix(),
                "--manifest",
                (output_root / "xxdkjs" / "2026-01" / "manifest.jsonl").as_posix(),
            ]
        )

    def test_hkxb_year_parser_sorts_years_descending(self) -> None:
        html = """
        <a href="showTenYearVolumnDetail.do?nian=2020">2020</a>
        <a href="showTenYearVolumnDetail.do?nian=2026">2026</a>
        <a href="showTenYearVolumnDetail.do?nian=2025">2025</a>
        """

        self.assertEqual(batch._parse_hkxb_years(html), ["2026", "2025", "2020"])


if __name__ == "__main__":
    unittest.main()
