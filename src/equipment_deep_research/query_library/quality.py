from __future__ import annotations

from dataclasses import replace
from difflib import SequenceMatcher
import ipaddress
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from equipment_deep_research.query_library.models import (
    GeneratedCandidate,
    GenerationValidationError,
    SourceReference,
    normalize_query,
)


DEFAULT_COVERAGE_SLOTS = (
    "需求牵引-战争任务与未来场景",
    "技术驱动-技术现状与趋势",
    "体系实战-全链条制胜机理",
    "颠覆逻辑-成本或平台",
    "通用系列规模化-工业与装备族",
    "需求牵引-对手威胁与反制",
    "技术驱动-成熟度与发展规划",
    "体系实战-跨域协同与战损韧性",
    "颠覆逻辑-时间毁伤体系或伦理博弈",
    "需求牵引-作战痛点与难点",
    "技术驱动-技术向装备能力映射",
    "需求牵引-单装与体系能力缺口",
    "需求牵引-任务链断点与失效边界",
    "需求牵引-保障持续性与战损恢复",
    "技术驱动-多技术融合与工程化",
    "技术驱动-试验验证与可信安全",
    "体系实战-有人无人协同",
    "体系实战-信息链与指挥控制韧性",
    "颠覆逻辑-认知信息与非动能效应",
    "规模建设-供应链动员与柔性产能",
)

DOMAIN_TERMS = (
    "无人",
    "低空",
    "远程火力",
    "远程打击",
    "精确打击",
    "精确制导",
    "导弹",
    "弹药",
    "火力",
    "毁伤",
    "压制",
    "打击装备",
    "预警",
    "侦察",
    "探测",
    "雷达",
    "防空",
    "反导",
    "指挥",
    "通信",
    "电磁",
    "电子战",
    "导航",
    "投送",
    "防护",
    "保障",
)
RESEARCH_TERMS = ("研究", "分析", "研判", "评估", "论证", "挖掘", "识别", "推演")
OUTCOME_TERMS = ("装备", "能力", "体系", "需求", "发展", "形态", "效能")
ACTIONABLE_HARM_TERMS = (
    "具体目标坐标",
    "目标清单",
    "攻击步骤",
    "武器制造步骤",
    "炸药配方",
    "引信制作",
    "规避安保",
    "人员伤亡最大化",
)
INTELLIGENCE_TERMS = ("智能", "自主", "算法")
RED_OCEAN_TERMS = ("传统", "现役", "存量", "跨代", "做优", "升级", "缺口")
BLUE_OCEAN_TERMS = ("新质", "蓝海", "新赛道", "颠覆", "拓新", "跨域")
INDUSTRIAL_TERMS = ("通用", "系列", "规模", "低成本", "供应链", "产线", "装备族")
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "key",
    "password",
    "secret",
    "signature",
    "sig",
    "token",
}


def coverage_plan(count: int) -> tuple[str, ...]:
    if not 1 <= count <= len(DEFAULT_COVERAGE_SLOTS):
        raise ValueError(
            f"generation count must be between 1 and {len(DEFAULT_COVERAGE_SLOTS)}"
        )
    return DEFAULT_COVERAGE_SLOTS[:count]


def sanitize_source_reference(reference: SourceReference) -> SourceReference:
    title = " ".join(reference.title.split())[:500]
    note = " ".join(reference.relevance_note.split())[:1000]
    if reference.source_kind == "document":
        if not title:
            raise GenerationValidationError("document source title is required")
        return replace(reference, title=title, url="", relevance_note=note)

    parsed = urlsplit(reference.url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise GenerationValidationError("web source URL must use HTTPS")
    if parsed.username or parsed.password:
        raise GenerationValidationError("source URL must not contain credentials")
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise GenerationValidationError("local source URL is not allowed")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise GenerationValidationError(
            "private or non-global source URL is not allowed"
        )
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in SENSITIVE_QUERY_KEYS
    ]
    clean_url = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            urlencode(filtered_query),
            "",
        )
    )
    if not title:
        title = hostname
    return replace(reference, title=title, url=clean_url, relevance_note=note)


def dedupe_sources(
    references: list[SourceReference], *, limit: int = 8
) -> tuple[SourceReference, ...]:
    result: list[SourceReference] = []
    seen: set[str] = set()
    for raw in references:
        item = sanitize_source_reference(raw)
        key = item.url or f"document:{item.title}"
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return tuple(result)


def sanitize_reference_urls(values: list[str] | tuple[str, ...], *, limit: int = 12) -> tuple[str, ...]:
    if len(values) > limit:
        raise GenerationValidationError(f"at most {limit} reference URLs are allowed")
    references = [
        SourceReference(
            title="",
            url=str(value).strip(),
            relevance_note="用户提供的优先检索线索。",
        )
        for value in values
        if str(value).strip()
    ]
    return tuple(item.url for item in dedupe_sources(references, limit=limit))


def near_duplicate(left: str, right: str, *, threshold: float = 0.95) -> bool:
    left_key = normalize_query(left)
    right_key = normalize_query(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    return SequenceMatcher(None, left_key, right_key).ratio() >= threshold


def validate_generated_candidate(
    candidate: GeneratedCandidate,
    *,
    expected_slot: str,
    existing_queries: list[str],
    accepted_queries: list[str],
) -> list[str]:
    issues: list[str] = []
    query = " ".join(candidate.query.split())
    if candidate.coverage_slot != expected_slot:
        issues.append(f"coverage_slot must be {expected_slot}")
    if len(query) < 14:
        issues.append("query is too short to be a clear research title")
    if len(query) > 30:
        issues.append("query should stay close to the preferred 18-25 character range")
    if not any(term in query for term in DOMAIN_TERMS):
        issues.append("query is outside the supported weapon-equipment capability domain")
    if not any(term in query for term in RESEARCH_TERMS):
        issues.append("query lacks an explicit research or analysis action")
    combined_scope = f"{query} {candidate.supplemental_information}"
    if not any(term in combined_scope for term in OUTCOME_TERMS):
        issues.append("query and supplemental information do not lead to an equipment capability demand")
    if any(term in query for term in ACTIONABLE_HARM_TERMS):
        issues.append(
            "query requests actionable targeting, attack, or weapon construction guidance"
        )
    if expected_slot in {
        "技术驱动-技术现状与趋势",
        "体系实战-全链条制胜机理",
    } and not any(term in combined_scope for term in INTELLIGENCE_TERMS):
        issues.append("required intelligent or autonomous capability lens is missing")
    if expected_slot == "需求牵引-单装与体系能力缺口" and not any(
        term in combined_scope for term in RED_OCEAN_TERMS
    ):
        issues.append("traditional red-ocean cross-generation lens is missing")
    if expected_slot == "颠覆逻辑-时间毁伤体系或伦理博弈" and not any(
        term in combined_scope for term in BLUE_OCEAN_TERMS
    ):
        issues.append("new-quality blue-ocean lens is missing")
    if expected_slot == "通用系列规模化-工业与装备族" and not any(
        term in combined_scope for term in INDUSTRIAL_TERMS
    ):
        issues.append("industrialization or equipment-family lens is missing")
    if len(candidate.generation_rationale.strip()) < 10:
        issues.append("generation_rationale is too short")
    if len(candidate.supplemental_information.strip()) < 30:
        issues.append("supplemental_information is too short to carry the detailed research dimensions")
    if not candidate.source_references:
        issues.append("at least one source reference is required")
    for prior in [*existing_queries, *accepted_queries]:
        if near_duplicate(query, prior):
            issues.append("query is an exact or near duplicate")
            break
    return issues
