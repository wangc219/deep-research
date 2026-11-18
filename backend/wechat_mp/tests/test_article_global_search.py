import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend import articles as article_module  # noqa: E402


class ArticleGlobalSearchTests(unittest.TestCase):
    def setUp(self):
        article_module._article_search_cache.clear()

    def test_search_scans_beyond_current_page_and_deduplicates(self):
        pages = {
            0: ([{"id": "a", "title": "普通文章"}], 100, 1),
            50: (
                [
                    {"id": "a", "title": "普通文章"},
                    {"id": "b", "title": "全局命中的历史文章"},
                ],
                52,
                0,
            ),
        }

        def fetch(_fakeid, begin, count, keyword, account_name="", **_kwargs):
            self.assertEqual(count, 50)
            self.assertEqual(keyword, "")
            self.assertEqual(account_name, "防务快讯")
            return pages[begin]

        with patch.object(article_module, "_fetch_articles_page", side_effect=fetch) as mocked:
            result = article_module._search_all_article_pages("fakeid", "历史文章", "防务快讯")

        self.assertEqual([call.args[1] for call in mocked.call_args_list], [0, 50])
        self.assertEqual([item["id"] for item in result["articles"]], ["b"])
        self.assertEqual(result["scanned"], 2)
        self.assertTrue(result["complete"])

    def test_search_endpoint_paginates_cached_global_results(self):
        app = Flask(__name__)
        app.register_blueprint(article_module.articles_bp)
        result = {
            "articles": [
                {"id": "a", "title": "命中一"},
                {"id": "b", "title": "命中二"},
                {"id": "c", "title": "命中三"},
            ],
            "scanned": 120,
            "complete": True,
            "stop_reason": "upstream_complete",
        }

        with patch.object(article_module, "_search_all_article_pages", return_value=result) as mocked:
            client = app.test_client()
            first = client.get("/api/articles/search/fakeid?keyword=命中&begin=0&count=2")
            second = client.get("/api/articles/search/fakeid?keyword=命中&begin=2&count=2")

        self.assertEqual(first.status_code, 200)
        self.assertEqual([item["id"] for item in first.json["articles"]], ["a", "b"])
        self.assertEqual(first.json["search_scope"], "all_pages")
        self.assertEqual(first.json["can_msg_continue"], 1)
        self.assertEqual([item["id"] for item in second.json["articles"]], ["c"])
        self.assertEqual(second.json["can_msg_continue"], 0)
        mocked.assert_called_once()

    def test_time_range_search_excludes_unknown_and_out_of_range_articles(self):
        pages = {
            0: (
                [
                    {"id": "new", "title": "较新文章", "update_time": 300},
                    {"id": "hit", "title": "范围内文章", "update_time": 200},
                    {"id": "unknown", "title": "时间未知", "update_time": 0},
                ],
                4,
                1,
            ),
            50: ([{"id": "old", "title": "较早文章", "update_time": 100}], 4, 1),
        }

        def fetch(_fakeid, begin, _count, _keyword, account_name="", **_kwargs):
            self.assertEqual(account_name, "防务快讯")
            return pages[begin]

        with patch.object(article_module, "_fetch_articles_page", side_effect=fetch) as mocked:
            result = article_module._search_all_article_pages(
                "fakeid",
                "",
                "防务快讯",
                start_time=150,
                end_time=250,
            )

        self.assertEqual([item["id"] for item in result["articles"]], ["hit"])
        self.assertEqual(result["scanned"], 4)
        self.assertTrue(result["complete"])
        self.assertEqual(result["stop_reason"], "date_range_complete")
        self.assertEqual([call.args[1] for call in mocked.call_args_list], [0, 50])

    def test_title_and_time_range_must_both_match(self):
        page = [
            {"id": "outside", "title": "装备趋势", "update_time": 300},
            {"id": "wrong-title", "title": "其他主题", "update_time": 200},
            {"id": "hit", "title": "装备趋势分析", "update_time": 180},
        ]
        with patch.object(
            article_module,
            "_fetch_articles_page",
            return_value=(page, 3, 0),
        ):
            result = article_module._search_all_article_pages(
                "fakeid",
                "装备趋势",
                start_time=150,
                end_time=250,
            )

        self.assertEqual([item["id"] for item in result["articles"]], ["hit"])

    def test_search_endpoint_accepts_time_only_and_validates_date_pair(self):
        app = Flask(__name__)
        app.register_blueprint(article_module.articles_bp)
        result = {
            "articles": [{"id": "hit", "title": "范围内文章", "update_time": 200}],
            "scanned": 1,
            "complete": True,
            "stop_reason": "upstream_complete",
        }
        client = app.test_client()

        with patch.object(article_module, "_search_all_article_pages", return_value=result) as mocked:
            response = client.get(
                "/api/articles/search/fakeid?start_time=150&end_time=250&count=20"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json["articles"]], ["hit"])
        mocked.assert_called_once_with("fakeid", "", "", 150, 250)
        self.assertEqual(
            client.get("/api/articles/search/fakeid?start_time=150").status_code,
            400,
        )
        self.assertEqual(
            client.get(
                "/api/articles/search/fakeid?start_time=250&end_time=150"
            ).status_code,
            400,
        )

    def test_search_cache_is_partitioned_by_time_range(self):
        app = Flask(__name__)
        app.register_blueprint(article_module.articles_bp)
        result = {
            "articles": [],
            "scanned": 0,
            "complete": True,
            "stop_reason": "upstream_complete",
        }
        client = app.test_client()

        with patch.object(article_module, "_search_all_article_pages", return_value=result) as mocked:
            first = client.get(
                "/api/articles/search/fakeid?start_time=100&end_time=200"
            )
            repeated = client.get(
                "/api/articles/search/fakeid?start_time=100&end_time=200"
            )
            different = client.get(
                "/api/articles/search/fakeid?start_time=201&end_time=300"
            )

        self.assertEqual([first.status_code, repeated.status_code, different.status_code], [200, 200, 200])
        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
