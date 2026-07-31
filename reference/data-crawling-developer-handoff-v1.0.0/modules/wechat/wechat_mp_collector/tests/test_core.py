import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wechat_mp_collector.accounts import DEFAULT_ACCOUNTS, accounts_by_name
from wechat_mp_collector.mp_api import fakeid_to_mp_id, parse_publish_page
from wechat_mp_collector.storage import DEFAULT_OUTPUT_DIR, safe_filename


class CoreParsingTests(unittest.TestCase):
    def test_fakeid_to_mp_id(self):
        self.assertEqual(fakeid_to_mp_id("MzA5MTM4MTU4MA=="), "MP_WXS_3091381580")

    def test_parse_publish_page(self):
        payload = {
            "publish_page": json.dumps(
                {
                    "publish_list": [
                        {
                            "create_time": 100,
                            "publish_info": json.dumps(
                                {
                                    "appmsgex": [
                                        {
                                            "aid": "abc",
                                            "title": "Title",
                                            "link": "https://mp.weixin.qq.com/s/test",
                                            "digest": "Digest",
                                            "cover": "https://example.test/cover.jpg",
                                            "update_time": 200,
                                        }
                                    ]
                                }
                            ),
                        }
                    ]
                }
            )
        }
        articles = parse_publish_page(payload, fakeid="MzA5MTM4MTU4MA==", page_no=0)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["aid"], "abc")
        self.assertEqual(articles[0]["title"], "Title")
        self.assertEqual(articles[0]["mp_id"], "MP_WXS_3091381580")

    def test_safe_filename(self):
        self.assertEqual(safe_filename('a/b:c*? "x"'), "a_b_c_x")

    def test_default_output_dir_is_repo_data_raw(self):
        expected = Path(__file__).resolve().parents[2] / "data" / "raw"
        self.assertEqual(DEFAULT_OUTPUT_DIR, expected)

    def test_default_accounts_include_requested_sources(self):
        names = {account["nickname"] for account in DEFAULT_ACCOUNTS}
        self.assertIn("防务快讯", names)
        self.assertIn("军民融合观察", names)
        selected = accounts_by_name(["防务快讯", "JMRHGC"])
        self.assertEqual([account["fakeid"] for account in selected], ["MzUxMTAyNzc0NQ==", "MzU0OTI0OTM5Nw=="])


if __name__ == "__main__":
    unittest.main()
