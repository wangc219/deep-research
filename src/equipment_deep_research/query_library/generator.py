from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import json
from typing import Any

from equipment_deep_research.providers.base import ModelMessage, ModelProvider
from equipment_deep_research.query_library.models import (
    GeneratedCandidate,
    GenerationResult,
    GenerationValidationError,
    SourceReference,
    now_iso,
)
from equipment_deep_research.query_library.quality import (
    coverage_plan,
    dedupe_sources,
    sanitize_source_reference,
    validate_generated_candidate,
)


GROUNDING_SCHEMA = {
    "summary": "string",
    "search_queries": ["string"],
    "signals": ["string"],
    "sources": [
        {
            "title": "string",
            "url": "https URL",
            "relevance_note": "string",
        }
    ],
}

GENERATION_SCHEMA = {
    "queries": [
        {
            "coverage_slot": "string",
            "query": "string",
            "supplemental_information": "string",
            "generation_rationale": "string",
            "sources": [{"url": "https URL", "relevance_note": "string"}],
        }
    ]
}


class ModelQueryGenerator:
    """Two-stage Query generator backed by an existing project model provider."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        provider_snapshot: Mapping[str, Any] | None = None,
        model_options: Mapping[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.provider_snapshot = dict(provider_snapshot or _snapshot(provider))
        self.model_options = dict(model_options or {})

    async def generate(
        self,
        *,
        topic: str,
        supplemental_information: str,
        reference_urls: tuple[str, ...] = (),
        count: int,
        existing_queries: list[str],
        on_stage: Callable[[str], None] | None = None,
    ) -> GenerationResult:
        autonomous_discovery = _is_autonomous_discovery(supplemental_information)
        slots = list(coverage_plan(count))
        if on_stage:
            on_stage("web_validation")
        grounding, grounding_metadata = await self._ground(
            topic=topic,
            supplemental_information=supplemental_information,
            reference_urls=reference_urls,
        )
        sources = _grounding_sources(grounding, grounding_metadata)
        if not sources:
            # Web grounding improves freshness but must not make the Query
            # generator unusable.  A configured agent session may be deliberately
            # offline, or its configured gateway may not expose hosted web
            # search.  Keep that limitation auditable as a document-style
            # source rather than fabricating an HTTPS citation or rejecting a
            # perfectly valid semantic-generation request.
            sources = (
                _model_analysis_source(
                    topic,
                    supplemental_information,
                    autonomous_discovery=autonomous_discovery,
                    provider_snapshot=self.provider_snapshot,
                ),
            )

        accepted: list[GeneratedCandidate] = []
        remaining_slots = list(slots)
        rejection_notes: list[str] = []
        if on_stage:
            on_stage("query_generation")
        for attempt in range(3):
            if not remaining_slots:
                break
            payload, _metadata = await self._generate_candidates(
                topic=topic,
                supplemental_information=supplemental_information,
                grounding=grounding,
                sources=sources,
                remaining_slots=remaining_slots,
                accepted=accepted,
                rejection_notes=rejection_notes,
                attempt=attempt,
            )
            rows = payload.get("queries", [])
            if not isinstance(rows, list):
                rows = []
            by_slot: dict[str, list[Mapping[str, Any]]] = {}
            for row in rows:
                if isinstance(row, Mapping):
                    by_slot.setdefault(str(row.get("coverage_slot", "")), []).append(
                        row
                    )

            next_remaining: list[str] = []
            rejection_notes = []
            for slot in remaining_slots:
                candidates = by_slot.get(slot, [])
                accepted_for_slot = False
                for raw in candidates:
                    try:
                        candidate = _candidate_from_payload(raw, sources)
                    except GenerationValidationError as exc:
                        rejection_notes.append(f"{slot}: {exc}")
                        continue
                    issues = validate_generated_candidate(
                        candidate,
                        expected_slot=slot,
                        existing_queries=existing_queries,
                        accepted_queries=[item.query for item in accepted],
                    )
                    if issues:
                        rejection_notes.append(f"{slot}: {'; '.join(issues)}")
                        continue
                    accepted.append(candidate)
                    accepted_for_slot = True
                    break
                if not accepted_for_slot:
                    next_remaining.append(slot)
            remaining_slots = next_remaining

        if remaining_slots:
            for candidate in _fallback_candidates(
                supplemental_information=supplemental_information,
                remaining_slots=remaining_slots,
                sources=sources,
            ):
                issues = validate_generated_candidate(
                    candidate,
                    expected_slot=candidate.coverage_slot,
                    existing_queries=existing_queries,
                    accepted_queries=[item.query for item in accepted],
                )
                if issues:
                    rejection_notes.append(
                        f"{candidate.coverage_slot}: {'; '.join(issues)}"
                    )
                    continue
                accepted.append(candidate)
                remaining_slots = [
                    slot
                    for slot in remaining_slots
                    if slot != candidate.coverage_slot
                ]

        if remaining_slots:
            detail = (
                "; ".join(rejection_notes[-8:]) or "model did not return required slots"
            )
            raise GenerationValidationError(
                f"only {len(accepted)}/{count} candidates passed quality gates; {detail}"
            )
        return GenerationResult(
            candidates=tuple(accepted),
            source_references=sources,
            provider_snapshot=self.provider_snapshot,
            search_queries=tuple(_string_list(grounding.get("search_queries", []))[:5]),
        )

    async def _ground(
        self,
        *,
        topic: str,
        supplemental_information: str,
        reference_urls: tuple[str, ...],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        autonomous_discovery = _is_autonomous_discovery(supplemental_information)
        current_date = datetime.now(timezone.utc).date().isoformat()
        if autonomous_discovery:
            task = (
                f"当前日期为{current_date}。topic是本次唯一的中国周边地域/战略视角，必须围绕该视角快速研判，"
                "不要扩展为泛化的全球态势扫描。最多设计3至5个聚焦检索，优先当年及近两年的权威公开信号，"
                "快速核对邻国、周边海域、岛链或边境任务环境中与topic直接相关的变化。"
                "严格按‘外部态势→任务压力→作战缺口→武器装备能力与发展需求’转译，"
                "无人作战、低空打击与反制、颠覆性远程打击、精确打击武器是高关注方向，但只是示例而非封闭目录；"
                "必须根据本次地域态势主动识别其他可能被牵引的装备形态、作战能力、对抗方式与体系架构，"
                "区分公开可核验信号、合理推演和未知项，不把推演写成既成事实。"
                "若联网检索可用，检索截至当前日期的中国政府、军队、行业主管部门和可信研究机构公开资料，"
                "最多返回6个实际访问过的HTTPS来源；若网搜不可用，仍须完成智能体态势研判并如实返回空sources，绝不编造URL。"
                "输出的signals应采用‘态势变化/外部挑战 → 任务约束 → 潜在能力缺口或技术机会’表达，为后续Query生成提供因果输入。"
            )
        else:
            task = (
                "围绕无人、低空、远程火力和精确打击装备进行轻量公开线索校验。"
                "若联网检索可用，优先访问reference_urls并补充公开资料；无法访问、没有参考URL或未返回来源时，"
                "如实返回空sources并继续基于用户母题梳理语义信号，绝不编造内容或URL。"
                "最多返回8个实际访问过的HTTPS来源。搜索摘要只是生成线索，不是正式证据。"
            )
        prompt = {
            "analysis_mode": (
                "codex_cli_china_situation_assessment"
                if autonomous_discovery
                else "topic_grounding"
            ),
            "current_date": current_date,
            "topic": topic,
            "supplemental_information": supplemental_information,
            "reference_urls": list(reference_urls),
            "task": task,
        }
        messages = (
            ModelMessage(
                role="system",
                content=(
                    "你是需求挖掘态势研判智能体。先理解中国当前安全环境与未来任务约束，"
                    "再提炼可研究的装备能力问题。不得提供目标选择、武器制造、攻击执行等可操作指导。只输出严格JSON。"
                ),
            ),
            ModelMessage(role="user", content=json.dumps(prompt, ensure_ascii=False)),
        )
        search_context_size = "low" if autonomous_discovery else "medium"
        text, metadata = await _collect_stream(
            self.provider,
            messages,
            {
                **self.model_options,
                "reasoning_effort": self.model_options.get("reasoning_effort", "medium"),
                "max_output_tokens": 2600,
                "web_search": {"search_context_size": search_context_size},
                "include_web_sources": True,
                # Search is opportunistic: the configured agent can use it when its
                # authenticated provider exposes hosted search, but offline
                # and custom-gateway sessions must still complete the task.
                "require_web_search": False,
                "_provider_retry_attempts": 1 if autonomous_discovery else 3,
                "output_schema": GROUNDING_SCHEMA,
            },
        )
        grounding = _safe_parse_json_object(text)
        if grounding is None:
            grounding = {
                "summary": text.strip()[:4000] or "已完成轻量公开态势研判。",
                "search_queries": [],
                "signals": [],
                "sources": [],
            }
        return grounding, metadata

    async def _generate_candidates(
        self,
        *,
        topic: str,
        supplemental_information: str,
        grounding: Mapping[str, Any],
        sources: tuple[SourceReference, ...],
        remaining_slots: list[str],
        accepted: list[GeneratedCandidate],
        rejection_notes: list[str],
        attempt: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        autonomous_discovery = _is_autonomous_discovery(supplemental_information)
        autonomous_requirements = [
            "topic是本次轮换的中国周边态势视角，所有Query都应回答该视角对武器装备发展的牵引，不写成时事摘要。",
            "每条Query必须对应实质不同的装备需求矛盾，不得围绕同一平台或同一能力只做同义改写。",
            "无人、低空反制、颠覆性远程打击和精确打击武器是高关注方向，但只能作为启发示例；不得将它们视为封闭目录，不设固定类别配额。",
            "必须先从grounding_signals中提炼本次态势特有的任务压力与能力断点，再自主推导可能的新装备形态、新质作战能力、跨域对抗方式或体系架构，充分发挥模型的异质发散能力。",
            "整批Query的主体必须是被态势直接牵引的武器装备需求；预警、指挥、通信、投送、防护、保障和产能等支撑方向仅在构成关键因果断点时纳入。",
            "Query要直接点明一种装备形态、关键能力或体系架构，聚焦能力需求与发展方向，避免空泛的态势研究。",
        ] if autonomous_discovery else []
        prompt = {
            "topic": topic,
            "supplemental_information": supplemental_information,
            "grounding_summary": grounding.get("summary", ""),
            "grounding_signals": _string_list(grounding.get("signals", []))[:20],
            "allowed_sources": [item.to_dict() for item in sources],
            "required_coverage_slots": remaining_slots,
            "already_accepted_queries": [item.query for item in accepted],
            "previous_rejections": rejection_notes[-12:],
            "attempt": attempt + 1,
            "requirements": [
                *autonomous_requirements,
                "先识别并保持用户给出的预期角度，再从需求牵引和技术驱动两个主轴发散，不能只是改写输入。",
                "需求牵引至少考虑当前与未来任务场景、对手能力与威胁形式、现有应对手段、作战痛点、单装与体系能力缺口。",
                "技术驱动至少考虑资源与技术现状、成熟度与路线图、通信/信息/人工智能途径、技术向装备能力映射及其对装备发展方向的影响。",
                "按coverage_slot补充体系实战与韧性、颠覆逻辑、工业化与规模建设等视角，各Query之间研究对象和核心矛盾必须明显不同。",
                "coverage_slot只是思考发生维度，不是最终装备目录；若与母题缺少直接因果关系，应换用同槽位下更相关的研究矛盾，不能机械套用示例。",
                "每个coverage_slot只生成一条中文短Query，作为研究任务标题使用。",
                "Query优先控制在18至25个汉字，语义确有需要时可在14至30个字符内浮动，采用‘对象+条件/能力+研究’形式。",
                "不要把分析维度、预期输出和多项并列要求堆进Query；这些内容全部写入supplemental_information。",
                "supplemental_information用80至220个汉字说明研究边界、关键维度、失效条件和预期装备能力输出。",
                "可参考‘卫星拒止条件下多源自主导航精打武器研究’、‘动态时敏目标快速感知—决策—打击一体化研究’的标题风格。",
                "Query与supplemental_information组合后必须落到装备能力需求、装备形态或体系效能，不生成简单事实问答。",
                "supplemental_information必须要求deep research先广泛发散、再收敛到可独立论证的具体装备项目，并逐项明确项目功能、Query因果链、直接军事效果、公开基线、失效边界和可证伪验证；项目功能回答谁在何种条件下依靠该装备完成什么动作并产生何种任务结果。",
                "综合体系化、实战化、智能化、颠覆化、通用化、系列化和规模化。",
                "整批兼顾传统能力红海跨代优势与新质能力蓝海高维优速。",
                "若allowed_sources含HTTPS网页，source URL只能从其中选择，不得编造URL。"
                "若allowed_sources只有态势研判或模型分析记录（source_kind=document），sources可留空；"
                "系统会保留该说明，绝不能伪造HTTPS URL。",
                "避免具体目标选择、攻击步骤、武器制造参数等可操作伤害指导。",
                "只输出严格JSON。",
            ],
        }
        messages = (
            ModelMessage(
                role="system",
                content=(
                    "你是军事装备需求发散生成Agent。围绕一个宽泛母题或文档选题角度，"
                    "从需求牵引、技术驱动、体系实战、颠覆逻辑和规模化等方向深度思考，"
                    "形成简洁、边界清楚、互不重复的短研究标题，并把详细研究要求放入补充信息。"
                    "将公开态势线索转化为可研究、可审计的装备需求选题，不把线索写成既成事实。"
                ),
            ),
            ModelMessage(role="user", content=json.dumps(prompt, ensure_ascii=False)),
        )
        text, metadata = await _collect_stream(
            self.provider,
            messages,
            {
                **self.model_options,
                "reasoning_effort": self.model_options.get("reasoning_effort", "high"),
                "max_output_tokens": max(2800, len(remaining_slots) * (760 if autonomous_discovery else 900)),
                "_provider_retry_attempts": 2 if autonomous_discovery else 3,
                "output_schema": GENERATION_SCHEMA,
            },
        )
        payload = _safe_parse_json_object(text)
        if payload is None:
            payload = {"queries": [], "_raw_text": text.strip()[:8000]}
        return payload, metadata


async def _collect_stream(
    provider: ModelProvider,
    messages: Sequence[ModelMessage],
    options: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    fragments: list[str] = []
    metadata: dict[str, Any] = {}
    final_seen = False
    stream = provider.stream(messages, (), options)
    if not hasattr(stream, "__aiter__"):
        raise TypeError("ModelProvider.stream must return an async iterator")
    async for event in stream:
        if final_seen:
            raise RuntimeError("provider emitted events after final turn")
        if event.event_type == "text_delta":
            fragments.append(event.delta)
        elif event.event_type == "final":
            final_seen = True
            assert event.final_turn is not None
            metadata = dict(event.final_turn.metadata)
            metadata["usage"] = dict(event.final_turn.usage)
            if event.final_turn.text is not None:
                fragments = [event.final_turn.text]
    if not final_seen:
        raise RuntimeError("provider stream ended without a final turn")
    return "".join(fragments).strip(), metadata


def _parse_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = value.removeprefix("```json").removeprefix("```")
        if value.endswith("```"):
            value = value[:-3]
        value = value.strip()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise GenerationValidationError(
                "model output did not contain a JSON object"
            )
        try:
            payload = json.loads(value[start : end + 1])
        except json.JSONDecodeError as exc:
            raise GenerationValidationError(
                "model output contained invalid JSON"
            ) from exc
    if not isinstance(payload, dict):
        raise GenerationValidationError("model output must be a JSON object")
    return payload


def _safe_parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse a model payload without aborting the whole generation on malformed JSON."""

    try:
        return _parse_json_object(text)
    except GenerationValidationError:
        return None


_FALLBACK_QUERY_BY_SLOT = {
    "需求牵引-战争任务与未来场景": "未来作战场景需求研究",
    "技术驱动-技术现状与趋势": "智能技术现状与趋势研判",
    "体系实战-全链条制胜机理": "全链条智能制胜机理研究",
    "颠覆逻辑-成本或平台": "低成本颠覆逻辑研究",
    "通用系列规模化-工业与装备族": "通用系列装备族研究",
    "需求牵引-对手威胁与反制": "对手威胁反制研究",
    "技术驱动-成熟度与发展规划": "技术成熟度规划评估",
    "体系实战-跨域协同与战损韧性": "跨域协同战损韧性研究",
    "颠覆逻辑-时间毁伤体系或伦理博弈": "新质时间毁伤体系研究",
    "需求牵引-作战痛点与难点": "作战痛点难点研究",
    "技术驱动-技术向装备能力映射": "技术装备能力映射评估",
    "需求牵引-单装与体系能力缺口": "单装体系跨代缺口研究",
    "需求牵引-任务链断点与失效边界": "任务链断点失效边界研究",
    "需求牵引-保障持续性与战损恢复": "保障持续战损恢复研究",
    "技术驱动-多技术融合与工程化": "多技术融合工程化评估",
    "技术驱动-试验验证与可信安全": "试验验证可信安全评估",
    "体系实战-有人无人协同": "有人无人协同研究",
    "体系实战-信息链与指挥控制韧性": "信息链指挥控制韧性研究",
    "颠覆逻辑-认知信息与非动能效应": "认知信息非动能效应研究",
    "规模建设-供应链动员与柔性产能": "供应链动员柔性产能研究",
}


def _fallback_candidates(
    *,
    supplemental_information: str,
    remaining_slots: list[str],
    sources: tuple[SourceReference, ...],
) -> list[GeneratedCandidate]:
    """Provide deterministic candidates when a model turn cannot be parsed."""

    theme = (
        "无人低空远程精确打击"
        if _is_autonomous_discovery(supplemental_information)
        else "无人精确打击装备"
    )
    references = dedupe_sources(list(sources), limit=4)
    results: list[GeneratedCandidate] = []
    for slot in remaining_slots:
        query = f"{theme}{_FALLBACK_QUERY_BY_SLOT.get(slot, '作战运用研究')}"
        supplemental = _fallback_supplemental(theme, slot)
        results.append(
            GeneratedCandidate(
                coverage_slot=slot,
                query=query,
                supplemental_information=supplemental,
                generation_rationale=(
                    f"模型结构化输出不可用，系统基于{theme}装备研究框架生成兜底选题。"
                ),
                source_references=references,
            )
        )
    return results


def _fallback_supplemental(theme: str, slot: str) -> str:
    text = (
        f"围绕{theme}装备发展，从“{slot}”维度分析任务需求、技术途径、"
        "体系效能与装备能力缺口，形成可研究的装备能力需求。"
    )
    if slot in {
        "技术驱动-技术现状与趋势",
        "体系实战-全链条制胜机理",
    }:
        text += "突出智能自主、多源感知与算法驱动。"
    if slot == "需求牵引-单装与体系能力缺口":
        text += "突出传统现役装备跨代升级与单装/体系缺口。"
    if slot == "颠覆逻辑-时间毁伤体系或伦理博弈":
        text += "突出新质蓝海、跨域拓新与颠覆效应。"
    if slot == "通用系列规模化-工业与装备族":
        text += "突出通用、系列、规模化、供应链与装备族建设。"
    return text


def _grounding_sources(
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> tuple[SourceReference, ...]:
    rows: list[SourceReference] = []
    for raw in payload.get("sources", []):
        if isinstance(raw, Mapping):
            rows.append(
                SourceReference(
                    title=str(raw.get("title", "")),
                    url=str(raw.get("url", "")),
                    relevance_note=str(raw.get("relevance_note", "")),
                )
            )
    for raw in metadata.get("web_sources", []):
        if isinstance(raw, Mapping):
            rows.append(
                SourceReference(
                    title=str(raw.get("title", "")),
                    url=str(raw.get("url", "")),
                    relevance_note=str(raw.get("snippet", "")),
                )
            )
    valid: list[SourceReference] = []
    for row in rows:
        try:
            valid.append(sanitize_source_reference(row))
        except GenerationValidationError:
            continue
    return dedupe_sources(valid, limit=8)


def _model_analysis_source(
    topic: str,
    supplemental_information: str,
    *,
    autonomous_discovery: bool,
    provider_snapshot: Mapping[str, Any],
) -> SourceReference:
    """Record model analysis without pretending that it is web evidence."""

    topic_text = " ".join(str(topic or "").split())[:180] or "用户输入母题"
    context_text = " ".join(str(supplemental_information or "").split())[:280]
    is_codex_cli = str(provider_snapshot.get("type", "")) == "codex_cli"
    if autonomous_discovery and is_codex_cli:
        title = "态势研判：中国当前安全环境与装备需求信号"
        note = (
            "智能体已围绕中国当前安全环境、未来作战任务、装备基础与技术信号完成态势研判；"
            "本次未获得可核验的公开HTTPS来源，因此该记录仅作为Query生成的分析过程与推演线索，不作为正式证据。"
        )
    else:
        title = f"模型分析记录：{topic_text}"
        note = "未获得可核验的公开HTTPS来源；模型基于用户母题完成需求语义分析。该记录不是正式证据。"
    if context_text:
        note = f"{note} 已纳入补充约束：{context_text}"
    return SourceReference(
        title=title,
        relevance_note=note,
        source_kind="document",
    )


def _is_autonomous_discovery(supplemental_information: str) -> bool:
    return "自动态势发散模式" in str(supplemental_information or "")


def _candidate_from_payload(
    raw: Mapping[str, Any],
    allowed_sources: tuple[SourceReference, ...],
) -> GeneratedCandidate:
    source_map = {item.url: item for item in allowed_sources if item.url}
    references: list[SourceReference] = []
    for raw_source in raw.get("sources", []):
        if not isinstance(raw_source, Mapping):
            continue
        url = str(raw_source.get("url", "")).strip()
        base = source_map.get(url)
        if base is None:
            continue
        note = " ".join(str(raw_source.get("relevance_note", "")).split())[:1000]
        references.append(
            SourceReference(
                title=base.title,
                url=base.url,
                accessed_at=base.accessed_at or now_iso(),
                relevance_note=note or base.relevance_note,
            )
        )
    if not references and allowed_sources:
        references = list(allowed_sources[:2])
    return GeneratedCandidate(
        coverage_slot=str(raw.get("coverage_slot", "")).strip(),
        query=" ".join(str(raw.get("query", "")).split()),
        supplemental_information=" ".join(
            str(raw.get("supplemental_information", "")).split()
        )[:8000],
        generation_rationale=" ".join(str(raw.get("generation_rationale", "")).split())[
            :2000
        ],
        source_references=dedupe_sources(references, limit=4),
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _snapshot(provider: object) -> dict[str, Any]:
    snapshot = getattr(provider, "snapshot", None)
    if callable(snapshot):
        value = snapshot()
        if isinstance(value, Mapping):
            return dict(value)
    return {"type": type(provider).__name__}
