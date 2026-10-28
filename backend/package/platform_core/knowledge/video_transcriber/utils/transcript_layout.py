"""预览、Word 与 Markdown 共用的保守分段；只调整空白，不改写原文。"""

import re

from platform_core.knowledge.video_transcriber.utils.text_normalizer import strip_trailing_engagement_prompt

LAYOUT_VERSION = 3
_SENTENCE_END = re.compile(r"""[。！？!?]+[”’」』）】"')]*|\.(?=\s|$)""")
_CLAUSE_END = re.compile(r"[，；;]")


def readable_paragraphs(text: str) -> list[str]:
    """保留原有换行，长段在句末或长句的分句处断开，避免切断词句。"""
    paragraphs = []
    for block in re.split(r"\r\n|\r|\n", text or ""):
        block = block.strip()
        if not block:
            continue
        units = []
        start = 0
        for boundary in _SENTENCE_END.finditer(block):
            units.append(block[start : boundary.end()])
            start = boundary.end()
        if start < len(block):
            units.append(block[start:])
        chunks = []
        for unit in units:
            if len(unit) <= 260:
                chunks.append(unit)
                continue
            start = 0
            for boundary in _CLAUSE_END.finditer(unit):
                chunks.append(unit[start : boundary.end()])
                start = boundary.end()
            if start < len(unit):
                chunks.append(unit[start:])
        current = ""
        for chunk in chunks:
            if len(current) >= 80 and len(current) + len(chunk) > 260:
                paragraphs.append(current.strip())
                current = ""
            current += chunk
            if len(current) >= 160:
                paragraphs.append(current.strip())
                current = ""
        if current.strip():
            paragraphs.append(current.strip())
    return paragraphs


def transcript_presentation(description: str, transcript: str) -> dict:
    """形成所有展示渠道共用的简介和正文段落。"""
    return {
        "description_paragraphs": readable_paragraphs(description),
        "transcript_paragraphs": readable_paragraphs(strip_trailing_engagement_prompt(transcript or "")),
    }


def video_markdown(description: str, transcript: str, account: str = "", oid: str = "") -> str:
    """生成有标题层级和自然段的可检索文字稿，长简介作为正文保留。"""
    layout = transcript_presentation(description, transcript)
    blocks = ["# 视频简介与文字稿"]
    if account:
        blocks.append(f"视频号：{account}")
    if oid:
        blocks.append(f"视频 OID：{oid}")
    blocks.extend(["## 简介", *layout["description_paragraphs"], "## 文字稿", *layout["transcript_paragraphs"]])
    return "\n\n".join(blocks) + "\n"
