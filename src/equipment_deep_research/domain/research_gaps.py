"""Public projection rules for research gaps.

Provider and quality-gate diagnostics can mention retrieval availability. Those
details are useful for audit, but they are not actionable manuscript content
and should never survive into the conversation memory or browser summary.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any


_INTERNAL_RETRIEVAL_HINTS = (
    "来源边界",
    "来源受限",
    "来源不可用",
    "来源或工程闭环提示",
    "检索不可用",
    "联网检索不可用",
    "搜索失败",
    "检索失败",
    "本轮检索",
    "未发现可靠可迁移的新技术",
    "未形成可靠可迁移的新技术结论",
    "未获得可核验的公开来源",
)

# Providers do not use one fixed wording for a failed search. Keep these
# patterns narrow enough to preserve ordinary, actionable research questions
# such as "仍需补充公开证据" while removing transport/source-status notices.
_INTERNAL_RETRIEVAL_PATTERNS = (
    re.compile(
        r"(?:联网|网页|网络|web\s*)?(?:检索|搜索|retrieval|search)"
        r"(?:通道|渠道|接口)?\s*(?:不通|不畅|失败|不可用|受限|中断|"
        r"无结果|没有结果|未返回|"
        r"未找到|未检索到|无响应|超时|异常|错误)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:国内外|国内|国外|国际|中国|英文)?"
        r"(?:公开)?(?:来源|网站|页面|站点|通道|渠道|接口)"
        r"(?:通道|渠道|接口)?\s*(?:不可达|无法访问|访问失败|不可用|受限|中断|失败|"
        r"无响应|超时|异常|错误)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:无法|不能|未能)\s*(?:访问|打开|连接)"
        r"[^。！？\n]{0,50}"
        r"(?:来源|网站|页面|站点|知网|数据库|论文|期刊|pubmed|doi|arxiv|cnki)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:没有|无|缺少|未获得|未找到|未检索到|未发现|暂无)"
        r"[^。！？\n]{0,32}"
        r"(?:可引用|可靠|可核验|公开)"
        r"[^。！？\n]{0,24}"
        r"(?:来源|新技术|技术结论|资料|证据)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:source|search|retrieval|web\s*search)\s*"
        r"(?:boundary|unavailable|failed|failure|inaccessible|"
        r"no\s+(?:reliable|citable)\s+sources?)",
        re.IGNORECASE,
    ),
)


def _is_internal_retrieval_notice(value: Any) -> bool:
    """Return whether one prose unit is a transport/source-status notice.

    ``sanitize_public_research_gap`` intentionally treats a few broad markers
    (for example ``本轮检索``) as internal when the whole value is a gap.  A
    paragraph needs a narrower predicate: a normal sentence can mention that
    a search was performed while still carrying useful engineering judgment.
    """

    text = " ".join(str(value or "").split()).strip()
    if not text:
        return False
    # These labels are emitted by the retrieval/runtime layer and have no
    # manuscript value even when the rest of the sentence is abbreviated.
    if any(
        marker in text
        for marker in (
            "来源边界",
            "来源受限",
            "来源不可用",
            "来源或工程闭环提示",
            "检索不可用",
            "联网检索不可用",
            "搜索失败",
            "检索失败",
            "未发现可靠可迁移的新技术",
            "未形成可靠可迁移的新技术结论",
            "未获得可核验的公开来源",
        )
    ):
        return True
    return any(pattern.search(text) for pattern in _INTERNAL_RETRIEVAL_PATTERNS)


def sanitize_public_research_gap(value: Any, *, limit: int = 400) -> str:
    """Return an actionable gap or an empty string for internal diagnostics."""

    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if any(hint in text for hint in _INTERNAL_RETRIEVAL_HINTS) or any(
        pattern.search(text) for pattern in _INTERNAL_RETRIEVAL_PATTERNS
    ):
        return ""
    return text[: max(0, int(limit))]


def sanitize_public_research_gaps(
    values: Iterable[Any], *, limit: int = 8, item_limit: int = 400
) -> list[str]:
    """Normalize, filter and de-duplicate gaps for public conversation state."""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = sanitize_public_research_gap(value, limit=item_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= max(0, int(limit)):
            break
    return result


def sanitize_public_research_prose(value: Any, limit: int = 12000) -> str:
    """Remove retrieval-status sentences while retaining substantive prose.

    Provider responses can contain a useful engineering paragraph followed by
    a sentence such as ``来源边界提示：国内外检索通道不可达``.  Filtering the
    entire field would discard the useful paragraph, while exposing the status
    sentence makes the manuscript read like an error report.  Split on normal
    sentence/paragraph boundaries, remove only status units, and retain the
    original punctuation and Markdown line structure as far as possible.

    ``limit`` is positional on purpose: callers in the deep-thinking and API
    projections use the compact ``(value, limit=...)`` contract.
    """

    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return ""

    # Keep line boundaries visible to Markdown callers.  Within each line,
    # split after sentence punctuation; this avoids flattening bullet lists and
    # lets a status sentence be removed independently of neighboring prose.
    sentence_boundary_re = re.compile(r"[。！？；;.!?](?:\s+|(?=\S))")
    kept_lines: list[str] = []
    for line in raw.split("\n"):
        if not line.strip():
            if kept_lines and kept_lines[-1] != "":
                kept_lines.append("")
            continue
        # A numbered/bulleted Markdown prefix is not a sentence.  Strip it
        # while splitting so a diagnostic item such as ``2. 来源边界提示`` is
        # removed as a whole instead of leaving a dangling ``2.`` marker.
        marker_match = re.match(r"^(\s*(?:[-*+]\s+|\d+[.)]\s*))", line)
        marker = marker_match.group(1) if marker_match else ""
        content = line[len(marker) :] if marker else line
        units: list[tuple[str, str]] = []
        cursor = 0
        for match in sentence_boundary_re.finditer(content):
            # Include the punctuation in the current unit.  Keep the original
            # boundary whitespace separately so Chinese prose does not gain a
            # synthetic space while English prose retains its source spacing.
            end = match.start() + 1
            units.append((content[cursor:end], content[end : match.end()]))
            cursor = match.end()
        units.append((content[cursor:], ""))
        kept_units = [
            (unit, separator)
            for unit, separator in units
            if unit.strip() and not _is_internal_retrieval_notice(unit)
        ]
        if kept_units:
            rendered = "".join(
                unit.strip() + (separator if index < len(kept_units) - 1 else "")
                for index, (unit, separator) in enumerate(kept_units)
            )
            kept_lines.append(marker + rendered)

    result = "\n".join(kept_lines).strip()
    return result[: max(0, int(limit))]


def sanitize_public_research_value(
    value: Any,
    *,
    limit: int = 12000,
    max_depth: int = 6,
) -> Any:
    """Recursively scrub retrieval diagnostics from a public JSON value.

    Deep answers are assembled from provider-shaped dictionaries.  An adapter
    can add a new nested field (for example ``provider_metadata`` or a
    diagnostic envelope) without that field being explicitly listed in the
    public projection.  Scrub only strings that actually look like retrieval
    status text and retain ordinary identifiers, URLs and structured values.
    This keeps the projection forward-compatible without exposing a transport
    failure after a refresh or branch switch.
    """

    if max_depth < 0:
        return "<redacted-depth>"
    if isinstance(value, str):
        text = value[: max(0, int(limit))]
        if (
            _is_internal_retrieval_notice(text)
            or any(marker in text for marker in _INTERNAL_RETRIEVAL_HINTS)
            or any(pattern.search(text) for pattern in _INTERNAL_RETRIEVAL_PATTERNS)
        ):
            return sanitize_public_research_prose(text, limit=limit)
        return text
    if isinstance(value, Mapping):
        projected: dict[Any, Any] = {}
        for key, child in value.items():
            cleaned = sanitize_public_research_value(
                child,
                limit=limit,
                max_depth=max_depth - 1,
            )
            # Empty strings are diagnostic-only leaves after sanitization;
            # dropping them prevents a UI from rendering an empty warning row.
            if cleaned == "" and isinstance(child, str):
                continue
            projected[key] = cleaned
        return projected
    if isinstance(value, (list, tuple, set, frozenset)):
        cleaned_items = [
            sanitize_public_research_value(
                item,
                limit=limit,
                max_depth=max_depth - 1,
            )
            for item in value
        ]
        return [item for item in cleaned_items if item != ""]
    return value
