from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
            raise GenerationValidationError(
                "lightweight web validation returned no usable HTTPS sources"
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
        prompt = {
            "topic": topic,
            "supplemental_information": supplemental_information,
            "reference_urls": list(reference_urls),
            "task": (
                "围绕无人、低空、远程火力和精确打击装备进行轻量联网校验。"
                "若提供reference_urls，优先访问这些网页并提取与母题相关的公开线索；无法访问时不要编造内容。"
                "执行3至5个公开资料检索，只提取近期术语、规划、能力动向、作战概念和待验证信号。"
                "最多返回8个实际访问过的HTTPS来源。搜索摘要只是生成线索，不是正式证据。"
            ),
        }
        messages = (
            ModelMessage(
                role="system",
                content=(
                    "你是需求挖掘Query生成模块的联网校验Agent。不得提供目标选择、武器制造、"
                    "攻击执行等可操作指导。只输出严格JSON。"
                ),
            ),
            ModelMessage(role="user", content=json.dumps(prompt, ensure_ascii=False)),
        )
        text, metadata = await _collect_stream(
            self.provider,
            messages,
            {
                **self.model_options,
                "reasoning_effort": self.model_options.get("reasoning_effort", "medium"),
                "max_output_tokens": 2600,
                "web_search": {"search_context_size": "medium"},
                "include_web_sources": True,
                "require_web_search": True,
                "output_schema": GROUNDING_SCHEMA,
            },
        )
        return _parse_json_object(text), metadata

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
                "source URL只能从allowed_sources中选择，不得编造URL。",
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
                "max_output_tokens": max(3000, len(remaining_slots) * 900),
                "output_schema": GENERATION_SCHEMA,
            },
        )
        return _parse_json_object(text), metadata


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
