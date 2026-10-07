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

COVERAGE_TASKS = {
    "需求牵引-战争任务与未来场景": "从未来任务阶段、环境约束和时间窗口反推不可替代的装备能力",
    "技术驱动-技术现状与趋势": "只选择能改变任务可行性且成熟度可判断的技术机会",
    "体系实战-全链条制胜机理": "定位侦察、决策、行动、评估闭环中的决定性断点与装备作用",
    "颠覆逻辑-成本或平台": "寻找能改变成本交换比、暴露方式或平台依赖的装备构型",
    "通用系列规模化-工业与装备族": "论证通用底座、系列派生和规模部署对应的持续作战需求",
    "需求牵引-对手威胁与反制": "由对手能力演进及其可能行动反推防御性制衡装备需求",
    "技术驱动-成熟度与发展规划": "区分近期可形成、阶段验证和远期储备的装备路线",
    "体系实战-跨域协同与战损韧性": "研究跨域协同受阻或节点受损时仍能维持任务的装备需求",
    "颠覆逻辑-时间毁伤体系或伦理博弈": "寻找改变决策时间、效应生成或非动能博弈关系的新质能力",
    "需求牵引-作战痛点与难点": "把高频且后果严重的任务痛点转化为具体装备功能缺口",
    "技术驱动-技术向装备能力映射": "说明技术组合如何转化为可验证的装备功能和任务效果",
    "需求牵引-单装与体系能力缺口": "比较现有单装与体系基线，识别必须跨代突破的能力缺口",
    "需求牵引-任务链断点与失效边界": "围绕最脆弱任务环节及其失效条件提出装备需求",
    "需求牵引-保障持续性与战损恢复": "从补充、维修、再生和恢复时限反推保障装备能力",
    "技术驱动-多技术融合与工程化": "识别多技术集成的关键接口、工程瓶颈与装备化路径",
    "技术驱动-试验验证与可信安全": "把可信性、安全性和复杂环境试验需求转成装备验证问题",
    "体系实战-有人无人协同": "明确人与无人平台的任务分工、控制边界和协同装备需求",
    "体系实战-信息链与指挥控制韧性": "由信息不完备、链路受扰和降级运行反推装备能力",
    "颠覆逻辑-认知信息与非动能效应": "研究非动能效应如何改变对抗关系及其装备载体",
    "规模建设-供应链动员与柔性产能": "由消耗强度、补充速度和供应风险反推规模建设需求",
}

DEMAND_CHAIN_FIELDS = (
    "situation_signal",
    "future_mission",
    "task_constraint",
    "capability_gap",
    "weapon_requirement",
    "disconfirmation_condition",
)
EVIDENCE_STATUSES = {"verified", "inferred", "unknown", "公开信号", "合理推演", "未知"}

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


def coverage_tasks(slots: list[str] | tuple[str, ...]) -> tuple[dict[str, str], ...]:
    """为每个覆盖槽补充可独立执行的研究产出标准。"""

    return tuple(
        {
            "coverage_slot": slot,
            "focus": COVERAGE_TASKS[slot],
            "output_standard": "形成一条完整牵引链，并落到一种可独立论证的装备形态、关键能力或体系架构。",
        }
        for slot in slots
    )


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
    require_demand_chain: bool = True,
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
    if require_demand_chain:
        chain = candidate.demand_chain
        for field in DEMAND_CHAIN_FIELDS:
            if len(str(chain.get(field, "")).strip()) < 6:
                issues.append(f"demand_chain.{field} is missing or too generic")
        evidence_status = str(chain.get("evidence_status", "")).strip()
        if evidence_status not in EVIDENCE_STATUSES:
            issues.append("demand_chain.evidence_status must distinguish verified, inferred, or unknown")
        weapon_requirement = str(chain.get("weapon_requirement", ""))
        if weapon_requirement and not any(term in weapon_requirement for term in OUTCOME_TERMS):
            issues.append("demand_chain.weapon_requirement does not describe an equipment capability outcome")
        if weapon_requirement and not _shares_domain_anchor(query, weapon_requirement):
            issues.append("query is not anchored to its weapon requirement")
        verdict = str(candidate.quality_review.get("verdict", "")).strip().lower()
        if verdict not in {"pass", "通过"}:
            issues.append("quality_review.verdict must pass after self-revision")
        for field in ("causal_specificity", "differentiation", "researchability"):
            value = str(candidate.quality_review.get(field, "")).strip().lower()
            if value not in {"pass", "通过"}:
                issues.append(f"quality_review.{field} must pass after self-revision")
    if not candidate.source_references:
        issues.append("at least one source reference is required")
    for prior in [*existing_queries, *accepted_queries]:
        if near_duplicate(query, prior):
            issues.append("query is an exact or near duplicate")
            break
    return issues


def _shares_domain_anchor(query: str, weapon_requirement: str) -> bool:
    shared_terms = [
        term
        for term in (*DOMAIN_TERMS, "集群", "平台", "传感器", "指控", "补给", "维修")
        if term in query and term in weapon_requirement
    ]
    return bool(shared_terms)
