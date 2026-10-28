"""Conservative cleanup of letter-spaced acronyms in mixed Chinese ASR output."""

import re

_ACRONYMS = ("AI", "GPS", "GBU", "KC", "MK", "EMP", "UAV", "CPU", "GPU", "DNA", "RNA", "NATO")
_KNOWN = [(re.compile(r"(?<![A-Za-z])" + r"[ \t]*".join(word) + r"(?![A-Za-z])", re.I), word) for word in _ACRONYMS]
_CAPITAL_LETTERS = re.compile(r"(?<![A-Za-z])[A-Z](?:[ \t]+[A-Z])+(?![A-Za-z])")

# Match whole, conventional engagement prompts, not arbitrary text containing
# 关注, which can also be part of the substantive conclusion.
_ENGAGEMENT_ACTION = (
    r"(?:点(?:个|一下|一波)?赞|关注(?:一下|我|我们|本号|账号)?|收藏(?:一下)?|转发(?:一下)?|分享(?:一下)?)"
)
_ENGAGEMENT_SEPARATOR = r"[\s、，,。.!！和与及并也再]*"
_ENGAGEMENT_VERB = r"(?:(?:请|欢迎|记得|别忘了|别忘记|不要忘了|麻烦|大家|朋友们|帮忙|顺手|多多|给我|给我们)\s*)*"
_ENGAGEMENT_INTRO = r"(?:(?:如果)?(?:喜欢|觉得)(?:本期|这期|这个|这类)?(?:视频|内容)?(?:有用|有帮助|不错)?(?:的话|的朋友|的朋友们)?[\s，,]*)?"
_ENGAGEMENT_END = r"(?:[\s，,。.!！、]*(?:哦|哟|呀|吧|啊|啦|谢谢(?:大家)?|感谢(?:大家)?(?:支持|观看)?|支持一下|我们下期再见|下期再见|下期见))*[\s，,。.!！]*"
_TRAILING_ENGAGEMENT = re.compile(
    _ENGAGEMENT_INTRO
    + _ENGAGEMENT_VERB
    + _ENGAGEMENT_ACTION
    + r"(?:"
    + _ENGAGEMENT_SEPARATOR
    + _ENGAGEMENT_VERB
    + _ENGAGEMENT_ACTION
    + r")*"
    + _ENGAGEMENT_END
)


def strip_trailing_engagement_prompt(text: str) -> str:
    """Remove only a recognized engagement prompt at the end of a TXT body."""
    starts = [0] + [match.end() for match in re.finditer(r"[。！？!?；;\n，,]", text)]
    for start in starts:
        if len(text) - start > 200:
            continue
        suffix = text[start:].strip()
        if suffix and _TRAILING_ENGAGEMENT.fullmatch(suffix):
            return text[:start].rstrip(" \t\r\n，,；;")
    return text


def normalize_english_spacing(text: str) -> str:
    # Do not infer acronym spelling in ordinary English sentences.
    if not re.search(r"[\u3400-\u9fff]", text):
        return text
    for pattern, spelling in _KNOWN:
        text = pattern.sub(lambda match: spelling if re.search(r"[ \t]", match[0]) else match[0], text)
    return _CAPITAL_LETTERS.sub(lambda match: re.sub(r"[ \t]+", "", match[0]), text)
