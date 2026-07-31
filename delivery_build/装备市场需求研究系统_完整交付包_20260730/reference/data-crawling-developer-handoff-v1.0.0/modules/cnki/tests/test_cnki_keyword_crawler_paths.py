# -*- coding: utf-8 -*-

from pathlib import Path
import os
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cnki_keyword_crawler.cnki_keyword_downloader import (
    build_storage_paths,
    configure_chromium_options,
)


class CnkiKeywordCrawlerPathTests(unittest.TestCase):
    def test_default_storage_paths_use_data_raw_cnki(self):
        paths = build_storage_paths()

        self.assertEqual(paths.raw_dir, PROJECT_ROOT / "data" / "raw" / "cnki")
        self.assertEqual(paths.output_dir, PROJECT_ROOT / "data" / "raw" / "cnki" / "papers")
        self.assertEqual(paths.log_dir, PROJECT_ROOT / "data" / "raw" / "cnki" / "logs")
        self.assertEqual(paths.log_path, PROJECT_ROOT / "data" / "raw" / "cnki" / "logs" / "spider_dp.log")
        self.assertEqual(paths.report_path, PROJECT_ROOT / "data" / "raw" / "cnki" / "download_report.json")
        self.assertEqual(paths.fail_path, PROJECT_ROOT / "data" / "raw" / "cnki" / "fail.txt")

    def test_relative_raw_dir_resolves_from_project_root(self):
        paths = build_storage_paths("data/raw/cnki_custom")

        self.assertEqual(paths.raw_dir, PROJECT_ROOT / "data" / "raw" / "cnki_custom")
        self.assertEqual(paths.output_dir, paths.raw_dir / "papers")
        self.assertEqual(paths.log_path, paths.raw_dir / "logs" / "spider_dp.log")

    def test_linux_container_chromium_options_use_runtime_and_no_sandbox(self):
        class RecordingOptions:
            def __init__(self):
                self.browser_path = ""
                self.arguments = []
                self.user_data_path = ""

            def set_browser_path(self, value):
                self.browser_path = value
                return self

            def set_argument(self, value):
                self.arguments.append(value)
                return self

            def set_user_data_path(self, value):
                self.user_data_path = value
                return self

        options = configure_chromium_options(
            RecordingOptions(),
            environment={
                "CHROME_BIN": "/usr/bin/chromium",
                "CRAWLER_RUNTIME_ROOT": "/workspace/runtime",
            },
            os_name="posix",
        )

        self.assertEqual(options.browser_path, "/usr/bin/chromium")
        self.assertIn("--no-sandbox", options.arguments)
        self.assertIn("--disable-dev-shm-usage", options.arguments)
        self.assertEqual(
            options.user_data_path,
            str(Path("/workspace/runtime") / "cnki-chromium"),
        )


if __name__ == "__main__":
    unittest.main()
