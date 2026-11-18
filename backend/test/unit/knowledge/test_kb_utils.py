"""知识库 URL 边界回归。"""

from platform_core.knowledge.utils.kb_utils import parse_minio_url


def test_parse_minio_url_preserves_semicolon_in_object_name() -> None:
    """论文文件名中的 HTML 实体分号属于对象名。"""
    url = "http://localhost:9000/knowledgebases/kb/upload/Diverse&nbsp;AdaBoost.pdf"

    assert parse_minio_url(url) == (
        "knowledgebases",
        "kb/upload/Diverse&nbsp;AdaBoost.pdf",
    )


def test_parse_minio_url_decodes_object_name_and_ignores_query() -> None:
    """对象名按 URL 解码，签名查询参数不得进入对象键。"""
    url = "http://localhost:9000/knowledgebases/kb/upload/%E8%AE%BA%E6%96%87%3Bv1.pdf?signature=test"

    assert parse_minio_url(url) == (
        "knowledgebases",
        "kb/upload/论文;v1.pdf",
    )
