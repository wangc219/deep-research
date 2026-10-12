"""可复现的本地关键词排序与证据去重；不依赖外部嵌入服务。"""

import copy
import math
import re
import unicodedata
from collections import Counter

from .contracts import ResearchError

STOP_WORDS = {
    "什么",
    "如何",
    "哪些",
    "请问",
    "这个",
    "一个",
    "可以",
    "我们",
    "需要",
    "进行",
    "the",
    "and",
    "for",
    "with",
}
CANDIDATES = ("Docling", "PaddleOCR", "Unstructured")


def terms(text: str) -> list[str]:
    """英文按完整词、中文按重叠双字词处理；查询与文档采用同一规则。"""
    result = re.findall(r"[a-z0-9_]{2,}", text.casefold())
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        result.extend(phrase[index : index + 2] for index in range(len(phrase) - 1))
    return [term for term in result if term not in STOP_WORDS]


def document_key(source: dict) -> tuple:
    """缺少文件标识时不把不同未知文件当作同一个文件。"""
    document = source.get("document_id") or source.get("source_url") or source.get("id")
    return source.get("origin"), source.get("library_id"), document


def _location(source: dict) -> dict:
    return {
        "original_id": source.get("id"),
        **{
            key: copy.deepcopy(source[key])
            for key in ("page", "excerpt_start", "excerpt_end")
            if key in source
        },
    }


def deduplicate_sources(sources: list[dict]) -> list[dict]:
    """只合并同一库、同一文件的重复片段；保留原文及其重复位置。"""
    result, seen = [], {}
    for index, source in enumerate(sources):
        text = source.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ResearchError("来源文本为空或类型无效。")
        document = document_key(source)
        # 未知文件且没有稳定片段 ID 时，宁可保留重复也不丢失来源。
        identity = document if document[-1] is not None else (*document, index)
        normalized = " ".join(unicodedata.normalize("NFC", text).split())
        key = (*identity, normalized)
        if key not in seen:
            retained = copy.deepcopy(source)
            seen[key] = retained
            result.append(retained)
            continue
        retained = seen[key]
        locations = retained.setdefault("duplicate_locations", [])
        for location in [_location(source), *source.get("duplicate_locations", [])]:
            if location != _location(retained) and location not in locations:
                locations.append(copy.deepcopy(location))
    return result


def rank_sources(
    sources: list[dict], query: str, *, keep_unmatched: bool = False
) -> list[dict]:
    """BM25 词频饱和、文长归一和逆文档频率；相同分数保留输入顺序。"""
    sources = deduplicate_sources(sources)
    query_terms = set(terms(query))
    documents = [Counter(terms(source["text"])) for source in sources]
    frequency = Counter(term for document in documents for term in document)
    lengths = [sum(document.values()) for document in documents]
    average_length = sum(lengths) / len(lengths) if lengths else 1
    average_length = max(average_length, 1)
    ranked = []
    for source, document, length in zip(sources, documents, lengths, strict=True):
        score = 0.0
        for term in sorted(query_terms):
            count = document.get(term, 0)
            if not count:
                continue
            inverse_frequency = math.log(
                1 + (len(sources) - frequency[term] + 0.5) / (frequency[term] + 0.5)
            )
            # 片段长度差异很大，使用 BM25 的 b=1 全文长归一，避免长片段
            # 仅靠重复关键词压过短而集中的证据；k1=1.2 保持词频饱和。
            denominator = count + 1.2 * length / average_length
            score += inverse_frequency * count * 2.2 / denominator
        if score or keep_unmatched:
            ranked.append((score, source))
    return [
        source for _, source in sorted(ranked, key=lambda pair: pair[0], reverse=True)
    ]


def candidate_mentions(text: str) -> list[str]:
    """候选全称匹配，排除嵌入其他英文词里的子串。"""
    return [
        name
        for name in CANDIDATES
        if re.search(
            r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", text, re.IGNORECASE
        )
    ]


def evidence_coverage(sources: list[dict]) -> dict:
    """仅声明所选原文是否提及候选名称，不能替代能力评估或实验。"""
    mentions = {source["id"]: candidate_mentions(source["text"]) for source in sources}
    candidates = [
        {
            "name": name,
            "source_ids": [
                source_id for source_id, names in mentions.items() if name in names
            ],
        }
        for name in CANDIDATES
    ]
    return {
        "kind": "text_mentions_only",
        "total_sources": len(sources),
        "candidates": candidates,
        "missing_candidates": [
            item["name"] for item in candidates if not item["source_ids"]
        ],
    }


def question_context(task: dict) -> list[str]:
    """服务端提供的有限问题历史仍按不可信输入验证；不接受模型答案。"""
    questions = task.get("context_questions", [])
    if (
        not isinstance(questions, list)
        or len(questions) > 3
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 2000
            for item in questions
        )
        or type(task.get("context_truncated", False)) is not bool
    ):
        raise ResearchError(
            "追问上下文无效：仅支持最多 3 个、每个不超过 2000 字符的历史问题。"
        )
    return copy.deepcopy(questions)


def retrieval_query(problem: str, questions: list[str]) -> str:
    """优先当前问题，其后是最近的问题；智谱截断时不先丢掉当前问题。"""
    return "\n".join([problem, *reversed(questions)])
