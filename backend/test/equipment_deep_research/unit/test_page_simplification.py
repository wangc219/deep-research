from pathlib import Path

from equipment_deep_research.tools.artifacts import SecureArtifactStore
from equipment_deep_research.tools.simplify import paragraph_at, simplify_html


def test_simplifier_removes_navigation_and_creates_exact_locations(tmp_path: Path) -> None:
    store = SecureArtifactStore(tmp_path)
    try:
        page = simplify_html('''<html><head><title>测试文章</title><meta property="article:published_time" content="2026-06-01"/></head><body><nav>导航</nav><article><h1>测试文章</h1><p>第一段关于低空无人机探测能力的有效正文内容。</p><p>第二段说明复杂环境下抗干扰和协同处置约束。</p></article><footer>页脚</footer></body></html>''', store)
        assert "导航" not in page.text
        assert page.title == "测试文章"
        assert page.published_at == "2026-06-01"
        assert paragraph_at(page, page.paragraphs[1].location).text.startswith("第二段")
    finally:
        store.close()
