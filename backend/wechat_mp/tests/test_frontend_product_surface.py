import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestFrontendProductSurface(unittest.TestCase):
    def test_runtime_page_does_not_expose_upstream_branding_or_disclaimer(self):
        index = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        app = (PROJECT_ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
        runtime_surface = index + "\n" + app

        self.assertNotIn("github.com/x554960766/wechat-mp-tools", runtime_surface)
        self.assertNotIn("GitHub 地址", runtime_surface)
        self.assertNotIn("免责声明", runtime_surface)
        self.assertNotIn("showDisclaimer", runtime_surface)
        self.assertNotIn("公众号文章 v2.3.3", runtime_surface)
        self.assertNotIn('id="version-display"', runtime_surface)
        self.assertNotIn('id="version-text"', runtime_surface)
        self.assertNotIn('id="update-dot"', runtime_surface)


if __name__ == "__main__":
    unittest.main()
