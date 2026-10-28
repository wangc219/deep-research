from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
import asyncio
import inspect
import hashlib
import time
import json
import logging
from typing import Any

from equipment_deep_research.providers.base import ModelMessage, ModelProvider
from equipment_deep_research.providers.responses import ProviderRetryableError
from equipment_deep_research.query_library.models import (
    GeneratedCandidate,
    GenerationResult,
    GenerationValidationError,
    SourceReference,
    now_iso,
)
from equipment_deep_research.query_library.quality import (
    coverage_plan,
    coverage_tasks,
    dedupe_sources,
    sanitize_source_reference,
    validate_generated_candidate,
)


RESEARCH_FOCUS_REQUIREMENTS = (
    "默认以中国为研究主体，围绕中国当前安全态势及未来军事任务开展战略层面的装备能力研究；"
    "围绕母题和自动态势两种模式均适用，用户明确指定其他主体或民用范围时遵循其范围。",
    "每条命题须关联公开可核验的近期态势变化与具体武器装备类别，说明任务需求、能力缺口及研究价值；"
    "国外装备动态仅作为公开能力比较、外部约束或技术参照，不误写为国外自身建设需求。",
    "在战略层面评估装备类别对威慑、战略制衡、防护与任务韧性的潜在价值及局限，"
    "比较公开能力信息、发展趋势与不确定性，不预设某种装备能够制胜，也不提出针对现实对手的攻击方案或武器改进设计。",
    "选题以相关安全态势、面临威胁和未来军事作战需要为主线，从任务压力与现有能力缺口推导值得研究或深研的装备命题；"
    "技术信号只有在能改变军事任务可行性或装备能力边界时才作为选题依据。",
    "默认聚焦军事作战与装备发展，不主动生成极端灾害、民用应急救援或一般公共服务选题；"
    "仅当用户明确指定民用研究母题时，才按其指定范围研究。",
    "高原、极寒、强风浪等自然环境应作为军事任务的条件约束，说明其与军事任务、对抗威胁及装备能力缺口的关系，"
    "不能把自然灾害本身替代为军事需求来源。",
    "每个候选命题必须说明具体态势或威胁变化、未来任务、现有能力缺口和待研究的未决问题；"
    "按任务重要性、缺口严重性、变化紧迫性、公开证据和可验证性择优，避免热点拼接与常识问答。",
)


GROUNDING_SCHEMA = {
    "summary": "string",
    "search_queries": ["string"],
    "signals": ["string"],
    "situation_assessment": {
        "operational_context": "string",
        "change_drivers": ["string"],
        "future_missions": ["string"],
        "adversary_constraints": ["string"],
        "current_capability_gaps": ["string"],
        "technology_opportunities": ["string"],
        "uncertainties": ["string"],
    },
    "sources": [
        {
            "title": "string",
            "url": "https URL",
            "relevance_note": "string",
        }
    ],
}

DIVERGENCE_SCHEMA = {
    "hypotheses": [
        {
            "hypothesis_id": "H01",
            "dimension": "string",
            "situation_signal": "string",
            "future_mission": "string",
            "task_constraint": "string",
            "capability_gap": "string",
            "weapon_requirement": "string",
            "candidate_equipment_forms": ["string"],
            "evidence_status": "verified|inferred|unknown",
            "disconfirmation_condition": "string",
            "priority_reason": "string",
        }
    ]
}

logger = logging.getLogger(__name__)

GENERATION_SCHEMA = {
    "queries": [
        {
            "coverage_slot": "string",
            "query": "string",
            "demand_chain": {
                "situation_signal": "string",
                "future_mission": "string",
                "task_constraint": "string",
                "capability_gap": "string",
                "weapon_requirement": "string",
                "evidence_status": "verified|inferred|unknown",
                "disconfirmation_condition": "string",
            },
            "supplemental_information": "string",
            "generation_rationale": "string",
            "quality_review": {
                "causal_specificity": "pass|revise",
                "differentiation": "pass|revise",
                "researchability": "pass|revise",
                "verdict": "pass|revise",
                "revision_note": "string",
            },
            "sources": [{"url": "https URL", "relevance_note": "string"}],
        }
    ]
}


class ModelQueryGenerator:
    """以态势研判、需求发散和批判收敛三阶段生成 Query。"""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        provider_snapshot: Mapping[str, Any] | None = None,
        model_options: Mapping[str, Any] | None = None,
        default_profile: str = "balanced",
    ) -> None:
        self.provider = provider
        self.provider_snapshot = dict(provider_snapshot or _snapshot(provider))
        self.model_options = dict(model_options or {})
        self.default_profile = default_profile

    async def generate(
        self,
        *,
        topic: str,
        supplemental_information: str,
        reference_urls: tuple[str, ...] = (),
        count: int,
        existing_queries: list[str],
        on_stage: Callable[[str], Any] | None = None,
        checkpoint: Mapping[str, Any] | None = None,
        on_checkpoint: Callable[[dict[str, Any]], Any] | None = None,
        accepted_candidates: Sequence[GeneratedCandidate] = (),
        on_candidate: Callable[[GeneratedCandidate], Any] | None = None,
        on_batch: Callable[[dict[str, Any]], Any] | None = None,
        batch_size: int = 2,
        max_parallel: int = 2,
        before_batch: Callable[[], Any] | None = None,
    ) -> GenerationResult:
        """小批次有界并发生成，逐条保存合格结果，重试复用已提交的规划。"""

        async def emit(callback, value):
            if callback is not None:
                result = callback(value)
                if inspect.isawaitable(result):
                    await result

        generation_profile = _generation_profile(supplemental_information, default=self.default_profile)
        slots = list(coverage_plan(count))
        started = time.monotonic()
        cache_identity = hashlib.sha256(
            json.dumps(
                {
                    "version": 3,
                    "provider": self.provider_snapshot,
                    "options": self.model_options,
                    "profile": generation_profile,
                    "topic": topic,
                    "supplemental_information": supplemental_information,
                    "reference_urls": reference_urls,
                    "count": count,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        cached = dict(checkpoint or {})
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(str(cached.get("cached_at") or ""))).total_seconds()
            if cached.get("identity") != cache_identity or not 0 <= age < 3600:
                cached = {}
        except (TypeError, ValueError):
            cached = {}
        planning_reused = "grounding" in cached
        cached.update(identity=cache_identity)
        cached.setdefault("cached_at", now_iso())
        accepted = list(
            {item.coverage_slot: item for item in accepted_candidates if item.coverage_slot in slots}.values()
        )
        if len(accepted) >= count:
            await emit(
                on_batch,
                {
                    "completed": len(accepted),
                    "total": count,
                    "attempt": 0,
                    "remaining": 0,
                    "request_batches": 0,
                    "repair_batches": 0,
                    "restored_count": len(accepted),
                    "planning_reused": planning_reused,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "model_seconds": 0.0,
                    "rejected_count": 0,
                    "rejections": [],
                },
            )
            sources = dedupe_sources([source for item in accepted for source in item.source_references], limit=8)
            return GenerationResult(
                tuple(accepted),
                sources,
                self.provider_snapshot,
                tuple(_string_list((cached.get("grounding") or {}).get("search_queries", []))),
            )
        if "grounding" in cached:
            grounding = dict(cached["grounding"])
            metadata = dict(cached.get("grounding_metadata") or {})
        else:
            capabilities = getattr(self.provider, "capabilities", None)
            can_search = not callable(capabilities) or capabilities().hosted_web_search
            await emit(on_stage, "web_validation" if can_search else "context_analysis")
            if generation_profile == "efficient" and not can_search:
                # 无联网能力时不额外调用一次模型伪装成公开检索。
                grounding, metadata = (
                    {
                        "summary": "未执行网页检索；后续根据用户输入直接分析，所有推演均需独立核验。",
                        "signals": [],
                        "sources": [],
                        "search_queries": [],
                    },
                    {},
                )
            else:
                grounding, metadata = await self._ground(
                    topic=topic,
                    supplemental_information=supplemental_information,
                    reference_urls=reference_urls,
                )
            cached.update(
                grounding=grounding,
                grounding_metadata={
                    "web_sources": [
                        {"title": item.title, "url": item.url, "snippet": item.relevance_note}
                        for item in _grounding_sources(grounding, metadata)
                    ]
                },
            )
            await emit(on_checkpoint, cached)
        sources = _grounding_sources(grounding, metadata)
        if not sources:
            sources = (
                _model_analysis_source(
                    topic,
                    supplemental_information,
                    autonomous_discovery=_is_autonomous_discovery(supplemental_information),
                    provider_snapshot=self.provider_snapshot,
                ),
            )
        if "hypotheses" in cached:
            hypotheses = list(cached["hypotheses"])
        elif generation_profile == "efficient":
            # 候选比较与完整因果链已经包含在每批生成合同中，无需串行重复规划。
            hypotheses = []
            cached["hypotheses"] = hypotheses
            await emit(on_checkpoint, cached)
        else:
            await emit(on_stage, "demand_divergence")
            hypotheses = await self._diverge_demand_hypotheses(
                topic=topic,
                supplemental_information=supplemental_information,
                grounding=grounding,
                count=count,
            )
            cached["hypotheses"] = hypotheses
            await emit(on_checkpoint, cached)
        await emit(on_stage, "query_generation")
        remaining = [slot for slot in slots if slot not in {item.coverage_slot for item in accepted}]
        rejection_notes: list[str] = []
        request_batches = 0
        repair_batches = 0
        model_seconds = 0.0
        restored_count = len(accepted)
        gate = asyncio.Lock()

        async def report_progress(attempt):
            """记录本次执行的耗时、模型批次、恢复数量和校验拒绝原因。"""
            await emit(
                on_batch,
                {
                    "completed": len(accepted),
                    "total": count,
                    "attempt": attempt + 1,
                    "remaining": count - len(accepted),
                    "request_batches": request_batches,
                    "repair_batches": repair_batches,
                    "restored_count": restored_count,
                    "planning_reused": planning_reused,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "model_seconds": round(model_seconds, 3),
                    "rejected_count": len(rejection_notes),
                    "rejections": rejection_notes[-8:],
                },
            )

        semaphore = asyncio.Semaphore(max(1, min(max_parallel, 4)))

        async def generate_batch(batch, attempt):
            nonlocal request_batches, repair_batches, model_seconds
            async with semaphore:
                if before_batch is not None:
                    control = before_batch()
                    if inspect.isawaitable(control):
                        await control
                request_batches += 1
                repair_batches += int(attempt > 0)
                model_started = time.monotonic()
                try:
                    payload, _ = await self._generate_candidates(
                        topic=topic,
                        supplemental_information=supplemental_information,
                        grounding=grounding,
                        hypotheses=hypotheses,
                        sources=sources,
                        remaining_slots=batch,
                        accepted=list(accepted),
                        rejection_notes=list(rejection_notes),
                        attempt=attempt,
                    )
                except ProviderRetryableError as exc:
                    rejection_notes.append(f"模型生成失败：{type(exc).__name__}")
                    payload = None
                finally:
                    model_seconds += time.monotonic() - model_started
            if payload is None:
                async with gate:
                    await report_progress(attempt)
                return
            rows = payload.get("queries", [])
            if not isinstance(rows, list):
                rows = []
            async with gate:
                for slot in batch:
                    found = False
                    for raw in rows:
                        if not isinstance(raw, Mapping) or raw.get("coverage_slot") != slot:
                            continue
                        try:
                            candidate = _candidate_from_payload(raw, sources)
                            issues = validate_generated_candidate(
                                candidate,
                                expected_slot=slot,
                                existing_queries=existing_queries,
                                accepted_queries=[item.query for item in accepted],
                                topic=topic,
                            )
                        except GenerationValidationError as exc:
                            rejection_notes.append(f"{slot}: {exc}")
                            continue
                        if issues:
                            rejection_notes.append(f"{slot}（{candidate.query[:60]}）: {'; '.join(issues)}")
                            continue
                        try:
                            await emit(on_candidate, candidate)
                        except GenerationValidationError as exc:
                            rejection_notes.append(f"{slot}: {exc}")
                            continue
                        accepted.append(candidate)
                        found = True
                        break
                    if not found:
                        rejection_notes.append(f"{slot}: 未返回通过校验的模型结果")
                await report_progress(attempt)

        for attempt in range(2 if generation_profile == "efficient" else 3):
            if not remaining:
                break
            size = max(1, min(batch_size, 20))
            tasks = []
            async with asyncio.TaskGroup() as group:
                for index in range(0, len(remaining), size):
                    tasks.append(group.create_task(generate_batch(remaining[index : index + size], attempt)))
            if any(task.cancelled() for task in tasks):
                raise asyncio.CancelledError("Query generation no longer owns its execution")
            remaining = [slot for slot in slots if slot not in {item.coverage_slot for item in accepted}]
        if remaining:
            detail = "; ".join(rejection_notes[-8:]) or "模型未返回合格结果"
            raise GenerationValidationError(
                f"仅 {len(accepted)}/{count} 条通过校验，已保存结果可在重试时复用；{detail}"
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
        generation_profile = _generation_profile(supplemental_information, default=self.default_profile)
        current_date = datetime.now(UTC).date().isoformat()
        if autonomous_discovery:
            task = (
                f"当前日期为{current_date}。topic是本次唯一的中国周边地域/战略视角，必须围绕该视角快速研判，"
                "不要扩展为泛化的全球态势扫描。最多设计3至5个聚焦检索，优先当年及近两年的权威公开信号，"
                "快速核对邻国、周边海域、岛链或边境任务环境中与topic直接相关的变化。"
                "研究主体始终是中国面临的安全态势、未来作战任务与装备发展需要；"
                "国外能力只作为威胁、约束、对手行动和可借鉴技术基线，不生成国外自身装备需求。"
                "严格按‘外部态势→任务压力→作战缺口→武器装备能力与发展需求’转译，"
                "无人作战、低空打击与反制、颠覆性远程打击、精确打击武器是高关注方向，但只是示例而非封闭目录；"
                "必须根据本次地域态势主动识别其他可能被牵引的装备形态、作战能力、对抗方式与体系架构，"
                "区分公开可核验信号、合理推演和未知项，不把推演写成既成事实。"
                "若联网检索可用，检索截至当前日期的中国政府、军队、行业主管部门和可信研究机构公开资料，"
                "最多返回6个实际访问过的HTTPS来源；若网搜不可用，仍须完成智能体态势研判并如实返回空sources，绝不编造URL。"
                "输出的signals应采用‘态势变化/外部挑战 → 任务约束 → 潜在能力缺口或技术机会’表达，"
                "为后续Query生成提供因果输入。"
            )
        else:
            task = (
                f"当前日期为{current_date}。围绕用户母题及其相关安全态势、威胁变化和未来军事任务进行轻量公开线索校验。"
                "默认从中国视角研判，优先核对当年及近两年与母题直接相关的公开资料，标明资料日期及其适用边界。"
                "若联网检索可用，优先访问reference_urls并补充公开资料；无法访问、没有参考URL或未返回来源时，"
                "如实返回空sources并继续基于用户母题梳理语义信号，绝不编造内容或URL。"
                "最多返回8个实际访问过的HTTPS来源。搜索摘要只是生成线索，不是正式证据。"
            )
        prompt = {
            "analysis_mode": ("codex_cli_china_situation_assessment" if autonomous_discovery else "topic_grounding"),
            "current_date": current_date,
            "topic": topic,
            "supplemental_information": supplemental_information,
            "reference_urls": list(reference_urls),
            "task": task,
            "output_contract": [
                *RESEARCH_FOCUS_REQUIREMENTS,
                "situation_assessment按作战环境、变化驱动、未来任务、对手约束、现有能力缺口、技术机会和不确定性组织。",
                "事实、合理推演和未知项分开表达；没有公开证据时不得把推演写成事实。",
                "signals必须写成‘变化信号→任务压力→潜在缺口’而不是关键词列表。",
            ],
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
        try:
            text, metadata = await _collect_stream(
                self.provider,
                messages,
                {
                    **self.model_options,
                    **self._stage_options("grounding", generation_profile),
                    "reasoning_effort": _stage_reasoning_effort("grounding", generation_profile, self.model_options),
                    "max_output_tokens": 2200 if generation_profile == "efficient" else 2600,
                    "web_search": {"search_context_size": search_context_size},
                    "include_web_sources": True,
                    # Grounding is an optional enrichment stage. Bound it separately
                    # so a slow or unsupported hosted-search path cannot consume the
                    # entire Query generation budget.
                    "_provider_timeout_seconds": 45 if generation_profile == "efficient" else 90,
                    "require_web_search": False,
                    "_provider_retry_attempts": 1 if autonomous_discovery else 3,
                    "output_schema": GROUNDING_SCHEMA,
                },
            )
        except ProviderRetryableError as exc:
            logger.warning("Query grounding unavailable; continuing without web enrichment: %s", exc)
            text = ""
            metadata = {"grounding_degraded": True, "grounding_error_type": type(exc).__name__}
        grounding = _safe_parse_json_object(text)
        if grounding is None:
            grounding = {
                "summary": text.strip()[:4000] or "已完成轻量公开态势研判。",
                "search_queries": [],
                "signals": [],
                "sources": [],
            }
        grounding["sources"] = [item.to_dict() for item in _grounding_sources(grounding, metadata)]
        return grounding, metadata

    async def _diverge_demand_hypotheses(
        self,
        *,
        topic: str,
        supplemental_information: str,
        grounding: Mapping[str, Any],
        count: int,
    ) -> list[dict[str, Any]]:
        """让独立规划角色先过量发散需求假设，避免标题阶段过早收敛。"""

        autonomous_discovery = _is_autonomous_discovery(supplemental_information)
        generation_profile = _generation_profile(supplemental_information, default=self.default_profile)
        target_count = _hypothesis_target(count, generation_profile)
        prompt = {
            "topic": topic,
            "supplemental_information": supplemental_information,
            "strategic_subject": "中国（默认；用户明确指定其他研究主体时遵循用户范围）",
            "grounding_summary": grounding.get("summary", ""),
            "situation_assessment": grounding.get("situation_assessment", {}),
            "grounding_signals": _string_list(grounding.get("signals", []))[:24],
            "target_hypothesis_count": target_count,
            "divergence_dimensions": [
                "未来任务与阶段演化",
                "对手能力与攻防适应",
                "任务链断点与极限环境",
                "现役单装与体系缺口",
                "新技术成熟度与组合机会",
                "跨域协同与降级韧性",
                "成本交换、规模消耗与工业动员",
                "新构型、新机理与非动能效应",
            ],
            "requirements": [
                *RESEARCH_FOCUS_REQUIREMENTS,
                *(
                    [
                        "自动发散的研究主体必须是中国：从中国面临的态势与未来作战需要反推装备需求；"
                        "国外动态仅作威胁、约束、对手基线或技术参照。"
                    ]
                    if autonomous_discovery
                    else []
                ),
                "先广泛生成需求假设，不写最终Query标题；数量达到target_hypothesis_count并保持研究对象异质。",
                "每条都写完整的态势信号→未来任务→任务约束→能力缺口→武器装备需求因果链。",
                "同一态势至少探索两种不同解法，同一装备方向也要寻找替代假设，避免被用户示例锚定。",
                "至少三分之一假设来自非显然方向，但必须能说明与topic的直接任务因果关系。",
                "candidate_equipment_forms给出2至4种可比较形态，不提前锁死唯一技术方案。",
                "区分verified、inferred和unknown；为每条假设给出能推翻需求判断的disconfirmation_condition。",
                "过滤只有技术热词、只有时事复述、没有能力缺口、无法形成装备项目的想法。",
                "不得提供具体目标选择、攻击步骤或武器制造参数。只输出严格JSON。",
            ],
        }
        messages = (
            ModelMessage(
                role="system",
                content=(
                    "你是装备需求规划智能体，职责是过量发散并构造竞争性需求假设。"
                    "像高质量研究对话的规划者一样，主动寻找替代解释、反例和被忽略的任务断点；"
                    "事实、推断与未知项必须分开。"
                ),
            ),
            ModelMessage(role="user", content=json.dumps(prompt, ensure_ascii=False)),
        )
        try:
            text, _metadata = await _collect_stream(
                self.provider,
                messages,
                {
                    **self.model_options,
                    **self._stage_options("divergence", generation_profile),
                    "reasoning_effort": _stage_reasoning_effort("divergence", generation_profile, self.model_options),
                    "max_output_tokens": max(3200, target_count * 300),
                    "_provider_retry_attempts": 1,
                    "output_schema": DIVERGENCE_SCHEMA,
                },
            )
        except ProviderRetryableError as exc:
            logger.warning("Query demand divergence unavailable; continuing from grounding: %s", exc)
            return []
        payload = _safe_parse_json_object(text) or {}
        rows = payload.get("hypotheses", [])
        if not isinstance(rows, list):
            return []
        return [dict(item) for item in rows if isinstance(item, Mapping)][:target_count]

    async def _generate_candidates(
        self,
        *,
        topic: str,
        supplemental_information: str,
        grounding: Mapping[str, Any],
        hypotheses: list[dict[str, Any]],
        sources: tuple[SourceReference, ...],
        remaining_slots: list[str],
        accepted: list[GeneratedCandidate],
        rejection_notes: list[str],
        attempt: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        autonomous_discovery = _is_autonomous_discovery(supplemental_information)
        generation_profile = _generation_profile(supplemental_information, default=self.default_profile)
        autonomous_requirements = (
            [
                "topic是本次轮换的中国周边态势视角，所有Query都应回答该视角对武器装备发展的牵引，不写成时事摘要。",
                "每条Query必须对应实质不同的装备需求矛盾，不得围绕同一平台或同一能力只做同义改写。",
                "研究主体必须是中国面临的未来任务和装备发展需要；国外能力只作为对手威胁、约束或参照基线。",
                "无人、低空反制、颠覆性远程打击和精确打击武器是高关注方向，但只能作为启发示例；不得将它们视为封闭目录，不设固定类别配额。",
                "必须先从grounding_signals中提炼本次态势特有的任务压力与能力断点，再自主推导可能的新装备形态、新质作战能力、跨域对抗方式或体系架构，充分发挥模型的异质发散能力。",
                "整批Query的主体必须是被态势直接牵引的武器装备需求；预警、指挥、通信、投送、防护、保障和产能等支撑方向仅在构成关键因果断点时纳入。",
                "Query要直接点明一种装备形态、关键能力或体系架构，聚焦能力需求与发展方向，避免空泛的态势研究。",
            ]
            if autonomous_discovery
            else []
        )
        prompt = {
            "topic": topic,
            "supplemental_information": supplemental_information,
            "grounding_summary": grounding.get("summary", ""),
            "situation_assessment": grounding.get("situation_assessment", {}),
            "grounding_signals": _string_list(grounding.get("signals", []))[:20],
            "demand_hypotheses": hypotheses,
            "allowed_sources": [item.to_dict() for item in sources],
            "coverage_tasks": list(coverage_tasks(remaining_slots)),
            "already_accepted_queries": [item.query for item in accepted],
            "previous_rejections": rejection_notes[-12:],
            "attempt": attempt + 1,
            "requirements": [
                *RESEARCH_FOCUS_REQUIREMENTS,
                *autonomous_requirements,
                "先识别并保持用户给出的预期角度，再从需求牵引和技术驱动两个主轴发散，不能只是改写输入。",
                "需求牵引至少考虑当前与未来任务场景、对手能力与威胁形式、现有应对手段、作战痛点、单装与体系能力缺口。",
                "技术驱动至少考虑资源与技术现状、成熟度与路线图、通信/信息/人工智能途径、技术向装备能力映射及其对装备发展方向的影响。",
                "按coverage_slot补充体系实战与韧性、颠覆逻辑、工业化与规模建设等视角，各Query之间研究对象和核心矛盾必须明显不同。",
                "coverage_slot只是思考发生维度，不是最终装备目录；若与母题缺少直接因果关系，应换用同槽位下更相关的研究矛盾，不能机械套用示例。",
                "优先从demand_hypotheses中选择任务价值高且彼此差异最大的牵引链；必要时可综合或提出新链，但不得跳过因果说明。",
                "生成每条标题前至少比较两个候选方向，按因果具体性、任务价值、与已有Query差异度、可研究性择优，只输出胜出项。",
                "demand_chain必须完整复述胜出项的六段因果链并标注evidence_status；不得用‘提升能力’等套话代替具体缺口。",
                "完成标题后进行反向质检：若移除态势信号后标题仍完全成立，说明牵引不够具体，必须重写。"
                "默认军事范围内，偏离军事任务的民用灾害命题必须替换；quality_review仅在三项均通过后verdict=pass。",
                "generation_rationale说明为何值得现在研究，关联态势或威胁、任务价值与能力缺口；"
                "supplemental_information明确待深研的核心问题、公开证据缺口与验证路径。",
                "每个coverage_slot只生成一条中文短Query，作为研究任务标题使用。",
                "标题、补充信息与demand_chain.weapon_requirement须使用一致的具体装备主体词，"
                "weapon_requirement明确写出装备能力或体系效能需求，不能只写抽象技术趋势。",
                "技术驱动-技术现状与趋势及体系实战-全链条制胜机理槽位，须在标题或补充信息中明确研究智能、自主或算法能力及其边界。",
                "Query优先控制在18至25个汉字，语义确有需要时可在14至30个字符内浮动，采用‘对象+条件/能力+研究’形式。",
                "不要把分析维度、预期输出和多项并列要求堆进Query；这些内容全部写入supplemental_information。",
                "supplemental_information用80至220个汉字说明研究边界、关键维度、失效条件和预期装备能力输出。",
                "可参考‘卫星拒止条件下多源自主导航精打武器研究’、‘动态时敏目标快速感知—决策—打击一体化研究’的标题风格。",
                "Query与supplemental_information组合后必须落到装备能力需求、装备形态或体系效能，不生成简单事实问答。",
                "supplemental_information必须要求deep research先广泛发散、再收敛到可独立论证的具体装备项目，"
                "并逐项明确项目功能、Query因果链、直接军事效果、公开基线、失效边界和可证伪验证；"
                "项目功能回答谁在何种条件下依靠该装备完成什么动作并产生何种任务结果。",
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
                **self._stage_options("generation", generation_profile),
                "reasoning_effort": _stage_reasoning_effort("generation", generation_profile, self.model_options),
                "max_output_tokens": _generation_token_budget(
                    len(remaining_slots),
                    autonomous_discovery=autonomous_discovery,
                    profile=generation_profile,
                ),
                "_provider_retry_attempts": 1 if generation_profile == "efficient" else 2,
                "output_schema": GENERATION_SCHEMA,
            },
        )
        payload = _safe_parse_json_object(text)
        if payload is None:
            payload = {"queries": [], "_raw_text": text.strip()[:8000]}
        return payload, metadata

    def _stage_options(self, stage: str, profile: str) -> dict[str, Any]:
        """Query 调用独立计量，并限制整阶段重试与隐藏推理预算。"""
        timeout = 60 if profile == "efficient" else (90 if profile == "balanced" else 180)
        return {
            "phase": f"query_{stage}",
            "_provider_timeout_seconds": timeout,
            "_query_stage_timeout_seconds": timeout,
            "_provider_structured_retry_attempts": 0 if profile == "efficient" else 1,
            **({"_disable_hidden_reasoning": True} if profile == "efficient" else {}),
        }


async def _collect_stream(
    provider: ModelProvider,
    messages: Sequence[ModelMessage],
    options: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    timeout = options.get("_query_stage_timeout_seconds")
    try:
        async with asyncio.timeout(float(timeout) if timeout is not None else None):
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

    except TimeoutError as exc:
        raise ProviderRetryableError(f"Query 模型阶段超时（{timeout} 秒），可重试未完成维度") from exc


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
            raise GenerationValidationError("model output did not contain a JSON object")
        try:
            payload = json.loads(value[start : end + 1])
        except json.JSONDecodeError as exc:
            raise GenerationValidationError("model output contained invalid JSON") from exc
    if not isinstance(payload, dict):
        raise GenerationValidationError("model output must be a JSON object")
    return payload


def _safe_parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse a model payload without aborting the whole generation on malformed JSON."""

    try:
        return _parse_json_object(text)
    except GenerationValidationError:
        return None


def _grounding_sources(
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> tuple[SourceReference, ...]:
    # 只有供应商工具返回的来源元数据能够证明发生过检索。
    rows = metadata.get("web_sources", [])
    if not isinstance(rows, list):
        return ()
    valid: list[SourceReference] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        try:
            valid.append(
                sanitize_source_reference(
                    SourceReference(
                        title=str(raw.get("title", "")),
                        url=str(raw.get("url", "")),
                        relevance_note=str(raw.get("snippet", "")),
                    )
                )
            )
        except (GenerationValidationError, ValueError):
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


def _generation_profile(supplemental_information: str, *, default: str = "balanced") -> str:
    text = str(supplemental_information or "")
    if "生成策略：高效" in text:
        return "efficient"
    if "生成策略：深度" in text:
        return "deep"
    if "生成策略：均衡" in text:
        return "balanced"
    return default


def _hypothesis_target(count: int, profile: str) -> int:
    if profile == "efficient":
        return min(20, max(6, count + max(2, count // 2)))
    if profile == "deep":
        return min(30, max(12, count * 2))
    return min(24, max(8, count * 2))


def _stage_reasoning_effort(
    stage: str,
    profile: str,
    model_options: Mapping[str, Any],
) -> str:
    configured = str(model_options.get("reasoning_effort", "")).strip()
    if profile == "deep":
        return configured if configured in {"high", "xhigh"} else "high"
    if stage == "grounding":
        return "low" if profile == "efficient" else "medium"
    if stage == "divergence" and profile == "efficient":
        return "medium"
    return configured or "high"


def _generation_token_budget(
    slot_count: int,
    *,
    autonomous_discovery: bool,
    profile: str,
) -> int:
    per_slot = 620 if autonomous_discovery else 700
    if profile == "efficient":
        per_slot -= 80
    elif profile == "deep":
        per_slot += 80
    return max(4096 if profile == "efficient" else 2600, slot_count * per_slot)


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
    raw_chain = raw.get("demand_chain", {})
    demand_chain = (
        {str(key): " ".join(str(value).split())[:1200] for key, value in raw_chain.items()}
        if isinstance(raw_chain, Mapping)
        else {}
    )
    raw_review = raw.get("quality_review", {})
    quality_review = (
        {str(key): " ".join(str(value).split())[:500] for key, value in raw_review.items()}
        if isinstance(raw_review, Mapping)
        else {}
    )
    if not any(item.url and item.source_kind == "web" for item in allowed_sources):
        if demand_chain.get("evidence_status") in {"verified", "公开信号"}:
            demand_chain["evidence_status"] = "inferred"
    return GeneratedCandidate(
        coverage_slot=str(raw.get("coverage_slot", "")).strip(),
        query=" ".join(str(raw.get("query", "")).split()),
        supplemental_information=" ".join(str(raw.get("supplemental_information", "")).split())[:8000],
        generation_rationale=" ".join(str(raw.get("generation_rationale", "")).split())[:2000],
        source_references=dedupe_sources(references, limit=4),
        demand_chain=demand_chain,
        quality_review=quality_review,
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
