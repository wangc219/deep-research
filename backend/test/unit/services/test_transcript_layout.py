"""文字稿分段保持原文、数字与段落，并在各导出渠道使用同一结构。"""

from io import BytesIO
import re

from docx import Document
import pytest

from platform_core.knowledge.video_transcriber.utils.docx_exporter import video_docx_bytes
from platform_core.knowledge.video_transcriber.utils.transcript_layout import (
    readable_paragraphs,
    transcript_presentation,
    video_markdown,
)


@pytest.mark.parametrize(
    "text",
    [
        "他说：“保留 75% 的面积，数值是 3.14。”后续仍需观察。" * 18,
        "A measured value is 3.14. Keep the 2026-10-24 date and https://example.com/a. " * 16,
        "这是没有句号但有长分句的原文，" * 50,
        "没有标点也不应随意切断词语" * 35,
        "第一段。\n\n第二段保留原有换行。\n第三段。",
        "正文结束。#国际观察 #视频文字稿",
        "",
    ],
)
def test_paragraphs_preserve_all_non_whitespace_characters(text):
    """仅改变段落空白，不删减、重复或改写任何文字与标点。"""
    result = readable_paragraphs(text)
    assert re.sub(r"\s", "", "".join(result)) == re.sub(r"\s", "", text)
    assert all(paragraph.strip() == paragraph and paragraph for paragraph in result)
    if "第一段" in text:
        assert len(result) == 3


def test_sentence_boundaries_and_preview_word_markdown_agree():
    """长段落变为多段，预览、Word、Markdown 采用完全相同的正文。"""
    description = "这是完整的视频简介，包含原始背景信息。" * 26
    transcript = "这是语音识别正文，包含可核查的 3.14 和 75% 数值。" * 32
    presentation = transcript_presentation(description, transcript)
    assert len(presentation["description_paragraphs"]) > 2
    assert len(presentation["transcript_paragraphs"]) > 3
    assert all(len(p) <= 260 and p.endswith("。") for p in presentation["transcript_paragraphs"])
    document = Document(BytesIO(video_docx_bytes(description, transcript, "示例视频号")))
    paragraphs = [p.text for p in document.paragraphs]
    assert paragraphs == [
        "视频简介与文字稿",
        "视频号  示例视频号",
        "简介：",
        *presentation["description_paragraphs"],
        "文字稿：",
        *presentation["transcript_paragraphs"],
    ]
    markdown = video_markdown(description, transcript, "示例视频号", "oid")
    assert markdown.startswith("# 视频简介与文字稿\n")
    for paragraph in presentation["transcript_paragraphs"]:
        assert "\n\n" + paragraph in markdown
    assert document.styles["Heading 1"].paragraph_format.keep_with_next
    assert document.styles["Normal"].paragraph_format.widow_control
