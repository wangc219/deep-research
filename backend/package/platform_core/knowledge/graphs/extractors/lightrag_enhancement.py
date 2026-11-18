"""LightRAG 风格的军事垂类初抽增强与一次补抽。"""

from __future__ import annotations

import asyncio
import json
import math
import re
from copy import deepcopy
from typing import Any

from platform_core.knowledge.chunking.ragflow_like.nlp import count_tokens
from platform_core.knowledge.graphs.defense_ontology import (
    DEFENSE_ONTOLOGY_V1,
    canonical_entity_type,
    ontology_payload,
    validate_relation_types,
)
from platform_core.knowledge.graphs.lightrag_contract import LIGHTRAG_ENHANCEMENT_REVISION
from platform_core.knowledge.graphs.graph_utils import resolve_entity_naming
from platform_core.knowledge.graphs.core_semantic_roles import (
    RESEARCH_THREAD_TYPES,
    build_domain_extraction_guidance,
)
from platform_core.knowledge.graphs.lightrag_adaptive_routing import (
    decide_lightrag_adaptive_routing,
    normalize_adaptive_routing_options,
)
from platform_core.knowledge.graphs.lightrag_layout_normalization import (
    LayoutNormalizedTextView,
    LayoutWhitespaceDeletion,
    build_layout_normalized_text_view,
)
from platform_core.knowledge.graphs.lightrag_text_quality import (
    OCRDamageSpan,
    detect_ocr_damage,
    reference_section_metrics,
)
from platform_core.knowledge.graphs.lightrag_ocr_repair_view import (
    build_ocr_repaired_text_view,
    candidates_for_repaired_view,
    partition_repaired_view_candidates,
)
from platform_core.knowledge.graphs.lightrag_relation_completion import (
    build_relation_completion_inventory,
    normalize_relation_completion_options,
    relation_completion_prompt_payload,
)
from platform_core.knowledge.graphs.semantic_chain_completion import analyze_five_role_recall
from platform_core.knowledge.graphs.lightrag_candidate_review import (
    DEFAULT_ENTITY_REVIEW_MIN_CONFIDENCE,
    ENTITY_REVIEW_MODES,
    ENTITY_REVIEW_TRIGGERS,
    build_entity_review_prompt,
    clear_non_ontology_entity_reason,
    filter_clear_non_ontology_candidates,
    resolve_deterministic_entity_type_conflicts,
    review_entities,
    validate_entity_review_decisions,
)

from .base import GraphExtractionInput
from .llm import ExtractionOutputTruncatedError, LLMGraphExtractor

DEFAULT_MAX_GLEANINGS = 1
DEFAULT_MAX_INITIAL_ENTITIES = 48
DEFAULT_MAX_INITIAL_RELATIONS = 64
DEFAULT_MAX_INITIAL_RECORDS = 96
DEFAULT_MAX_GLEANING_ENTITIES = 24
DEFAULT_MAX_GLEANING_RELATIONS = 32
DEFAULT_MAX_GLEANING_RECORDS = 48
DEFAULT_MAX_PROMPT_ENTITIES = 48
DEFAULT_MAX_PROMPT_RELATIONS = 64
DEFAULT_MAX_INITIAL_PROMPT_CHARS = 60_000
DEFAULT_MAX_GLEANING_INPUT_CHARS = 80_000
DEFAULT_MAX_INITIAL_PROMPT_TOKENS = 24_000
DEFAULT_MAX_GLEANING_INPUT_TOKENS = 32_000
MAX_LLM_CANDIDATE_RECORDS = 512
MAX_LLM_PROMPT_CHARS = 500_000
MAX_LLM_PROMPT_TOKENS = 200_000
MAX_ENHANCEMENT_CONCURRENCY = 8
MAX_CONTEXT_WINDOW_SIZE = 4
MAX_CONTEXT_CHARS = 8000
DEFAULT_OCR_REPAIR_MIN_CONFIDENCE = 0.85
DEFAULT_OCR_REPAIR_MAX_PROPOSALS = 8
DEFAULT_OCR_REPAIR_MAX_ENTITIES = 16
DEFAULT_OCR_REPAIR_MAX_RELATIONS = 20
DEFAULT_OCR_REPAIR_MAX_RECORDS = 28
DEFAULT_LAYOUT_NORMALIZATION_MAX_DELETIONS = 256
DEFAULT_LAYOUT_NORMALIZATION_MAX_WHITESPACE_CHARS = 8
DEFAULT_LAYOUT_NORMALIZATION_MAX_ENTITIES = 24
DEFAULT_LAYOUT_NORMALIZATION_MAX_RELATIONS = 32
DEFAULT_LAYOUT_NORMALIZATION_MAX_RECORDS = 48
MAX_INLINE_LAYOUT_HINTS = 32
DEFAULT_JSON_STOP_SEQUENCE = "<END_JSON>"
DOMAIN_EXTRACTION_GUIDANCE = """军事技术原理垂类示例（示例不是当前证据，不得从示例抽取）：
- 示例原文：“脉冲压缩采用匹配滤波算法，提高雷达距离分辨能力，并受ADC采样率限制。”
- 正确实体：脉冲压缩=KeyTechnology[0:4]；匹配滤波算法=AlgorithmModel[6:12]；
  雷达距离分辨能力=Capability[15:23]；ADC采样率=Constraint[26:32]。
- 正确方向：脉冲压缩 --USES_TECHNOLOGY--> 匹配滤波算法；
  脉冲压缩 --ENABLES_CAPABILITY--> 雷达距离分辨能力；脉冲压缩 --CONSTRAINED_BY--> ADC采样率。
- 反例：“本文”“该系统”“上述方法”不是实体；`@AB` 等损伤片段不是标准实体；
  “成功”“取得了成功”等一般结果描述不是 Achievement；研究机构名称在当前本体没有对应类型时应 reject；
  电子管、速调管、磁控管、慢波器件、天线、电极、芯片和模块通常是 Component，不是 ProductSystem 或 Material；
  ProductSystem 只用于能独立完成任务的完整装备、平台或系统；
  ScientificPrinciple 必须是可解释作用机理的原理，“快速爆炸”、“磁场”等孤立事件或环境词不应直接标为科学原理；
  “定向能武器系统”作为装备概念时不是 ScientificPrinciple，应 relabel 为 ProductSystem；
  优先保留具体 Capability、Metric 和 Constraint，不要只抽取泛化的装备名词；
  没有原文直接支持时，不得把“可能用于装备”改写为 APPLIED_TO 事实。
""".strip()

INITIAL_ENHANCEMENT_PROMPT = """你是军事武器装备技术原理知识图谱的高精度复核器。
请在严格遵守本体、关系方向和原文字符 Span 的前提下，对机器初抽结果进行质量增强。

任务：
1. 找出初抽遗漏的高价值垂类实体：科学原理、关键技术、算法模型、材料、技术组件、产品系统、
   产品能力、应用场景、技术领域、技术成果、技术指标和约束条件。
2. 找出原文直接支持、但初抽遗漏或类型/方向明显有误的关系。宁缺勿滥，不补常识，不外推列装或实战能力。
3. 识别 OCR/排版损伤并给出 repair proposal；proposal 只是建议，绝不能把修复文本当成原文证据。
4. 实体 text 必须逐字存在于原文，start/end 使用 Python 半开字符区间且 text == 原文[start:end]。
   同时返回 canonical_name、raw_name、aliases、naming_rationale：raw_name 必须等于 text；canonical_name
   是去除“本文提出的/一种面向”等论文句式后的短小稳定术语，保留决定身份的领域限定词、型号、材料体系和关键对象；
   禁止把“系统/平台/方法/模型/技术/能力/应用/结果/验证/数据集”等孤立泛词作为规范名。
5. 关系 evidence_spans 必须指向原文；不要返回 evidence_quote，平台会由 Span 截取原文。
6. 只输出新增候选，不重复初抽中已经正确的实体和关系。所有输出仍是待审核候选。
7. 结构上下文只能用于消解简称、省略和术语类型；实体与关系证据仍必须来自“当前原文”，不得抽取只在前文出现的实体。
8. 数量硬上限：实体不超过 {max_entities} 条，关系不超过 {max_relations} 条，实体+关系总数不超过 {max_records} 条。
9. 上限不是目标；不要为凑数复述机器候选。若没有遗漏，返回空数组。
10. confidence 必须是对当前候选的真实 0~1 置信度，不得照抄 0 占位；OCR 修复只有在上下文足以明确恢复时才返回，
    明确可恢复通常应不低于 0.85，不能确定时不要返回 proposal。
11. 对齐 LightRAG 的关系语义索引：每条关系必须给出 text（稳定、简短的中文关系语义短语）、reasoning_basis
    （只解释原文怎样支撑该连接，不补外部知识）、applicable_conditions 和 uncertainty。label 保持本体枚举，text 不得用
    “相关/关联/作用”等空泛词替代。输出前检查端点命名一致、关系方向合法、证据覆盖两端点，并优先保留能够形成
    五类实体之间原文明确表达的关键联系。证据不足允许链路缺项，禁止为了形成完整链路编造边。
请优先返回证据直接、术语边界明确、对军事技术原理图谱最有价值的候选。

{domain_guidance}

仅返回 JSON：
{{
  "entities": [{{
    "id":"llm-e1", "text":"原文实体", "label":"本体类型", "start":0, "end":4,
    "confidence":0.93, "canonical_name":"稳定规范名", "raw_name":"原文实体",
    "aliases":["缩写或译名"], "naming_rationale":"保留关键限定词的简短依据",
    "research_thread":"main", "attributes":[]
  }}],
  "relations": [{{
    "source":"llm-e1 或机器候选唯一 id", "target":"新增实体 id 或机器候选唯一 id", "label":"关系编码",
    "text":"稳定关系语义短语", "claim_level":"Fact 或 Inference", "confidence":0.91,
    "reasoning_basis":"原文如何支撑该关系", "applicable_conditions":[], "uncertainty":"",
    "evidence_spans":[{{"start":0,"end":10}}]
  }}],
  "ocr_repair_proposals": [{{
    "original_start":0, "original_end":3, "original_text":"@AB",
    "suggested_text":"仅建议，不替换原文", "confidence":0.92, "reason":"OCR 或排版损伤依据"
  }}]
}}

本体：
{ontology}

机器初抽候选：
{candidates}

结构上下文（仅辅助消歧，不是当前证据）：
{context}

平台检测到的疑似 OCR/排版损伤（只能对这些封闭 Span 给 repair proposal；没有充分上下文时不要猜）：
{ocr_damage}

平台确定的排版连续术语提示（只帮助识别被空白打断的术语；Span 仍必须定位下方未改写原文）：
{layout_hints}

原文：
{text}
"""

GLEANING_PROMPT = """你是军事武器装备技术原理知识图谱的二次补抽器。首次增强已完成。
请逐句复查原文，只补首次结果仍遗漏的关键实体、直接关系与 OCR repair proposal；不得重复已有候选。
规则与首次相同：严格本体和方向；实体及关系证据必须使用原文半开字符 Span；不得改写证据；
每个实体同时返回 canonical_name、raw_name、aliases、naming_rationale；raw_name 必须等于 text，
canonical_name 应短小、稳定、保留决定身份的领域限定词，禁止论文句式、整句和孤立泛词；
不得补常识或生成假设关系；结构上下文只用于消歧，不得作为当前证据；宁缺勿滥。
每条关系必须给出稳定的 text 关系语义短语、reasoning_basis、applicable_conditions 和 uncertainty；
label 仍使用本体枚举。输出前检查端点命名一致、方向、本体签名和证据覆盖，并优先补足五类实体之间
有原文证据的关键联系；不得为补齐角色或形成完整链路编造关系。
confidence 必须是真实 0~1 置信度，不得使用 0 占位；OCR 修复不能由上下文明确恢复时不要返回 proposal。
数量硬上限：实体不超过 {max_entities} 条，关系不超过 {max_relations} 条，
实体+关系总数不超过 {max_records} 条；超出时只保留证据最直接、价值最高的候选。
上限不是目标；不要为凑数复述已有候选。若没有遗漏，返回空数组。
{domain_guidance}
仅返回 JSON，字段结构必须完整：
{{
  "entities":[{{
    "id":"glean-e1","text":"原文实体","label":"本体类型","start":0,"end":4,
    "confidence":0.93,"canonical_name":"稳定规范名","raw_name":"原文实体",
    "aliases":["缩写或译名"],"naming_rationale":"简短命名依据",
    "research_thread":"main","attributes":[]
  }}],
  "relations":[{{
    "source":"glean-e1 或当前候选唯一 id","target":"新增实体 id 或当前候选唯一 id","label":"关系编码",
    "text":"稳定关系语义短语","claim_level":"Fact 或 Inference","confidence":0.91,
    "reasoning_basis":"原文如何支撑该关系","applicable_conditions":[],"uncertainty":"",
    "evidence_spans":[{{"start":0,"end":10}}]
  }}],
  "ocr_repair_proposals":[]
}}

本体：
{ontology}

当前完整候选：
{candidates}

平台五类实体/联系复查摘要（只决定本轮优先核验哪些原文，不是实体或关系证据）：
{semantic_chain_analysis}

结构上下文（仅辅助消歧，不是当前证据）：
{context}

平台检测到的疑似 OCR/排版损伤（只能对这些封闭 Span 给 repair proposal；没有充分上下文时不要猜）：
{ocr_damage}

原文：
{text}
"""

RELATION_COMPLETION_PROMPT = """你是军事武器装备技术原理知识图谱的高精度关系补抽器。
平台已经完成实体抽取，并从同句或受控相邻句实体中构造了封闭候选对。请只判断原文是否直接支持候选关系。

严格规则：
1. 只能选择“封闭关系候选”中的 pair_ref、source_ref、target_ref 和 allowed_labels；禁止新建、改写实体。
2. 只有原文明确表达技术依据、组成、实现、使用、提升、能力、应用、指标、约束、验证、演化或替代时才返回。
3. 共现不等于关系；标题并列、关键词罗列、参考文献、背景介绍和常识联想必须返回空。
   跨句候选只有在组成列表延续、明确代词回指或同一技术叙述连续时才可返回。
4. source/target 必须原样复制候选的 source_ref/target_ref，label 必须属于对应 allowed_labels。
5. evidence_spans 必须使用原文 Python 半开字符 Span，并同时覆盖 source 与 target；通常可直接使用候选的
   evidence_span。平台会截取证据原文，禁止返回 evidence_quote。
6. 只返回高置信候选，confidence 不得低于 {min_relation_confidence}；不确定时宁缺勿滥。
7. 不得重复“当前已有关系”；若没有新增关系，返回空 relations。
8. 最多返回 {max_relations} 条关系，所有结果仍是 pending，必须经过规则或人工门禁。

{domain_guidance}

仅返回 JSON：
{{
  "entities":[],
  "relations":[{{
    "pair_ref":"rc-p1","source":"rc-e1","target":"rc-e2","label":"关系编码",
    "claim_level":"Fact 或 Inference","confidence":0.91,
    "evidence_spans":[{{"start":0,"end":10}}]
  }}],
  "ocr_repair_proposals":[]
}}

本体：
{ontology}

当前已有关系（只用于去重）：
{existing_relations}

平台五类实体/联系复查摘要（只决定候选排序，不是关系证据）：
{semantic_chain_analysis}

封闭关系候选：
{relation_candidates}

结构上下文（仅辅助消歧，不是证据）：
{context}

原文：
{text}
"""

OCR_REPAIR_EXTRACTION_PROMPT = """你是军事技术文献 OCR 修复视图的受控知识抽取器。
平台没有改写原文，只为本次实验抽取构造了临时修复视图。请利用修复后的上下文补回遗漏实体和直接关系。

规则：
1. start/end 必须严格对应“临时修复视图”的 Python 半开字符 Span，实体 text 必须逐字匹配该视图。
2. 不得补常识、列装状态或推测能力；关系必须由当前视图直接支持并符合本体方向。
3. 可以返回位于修复片段内的候选，但平台会把它们隔离为 repair_dependent_candidate，不能进入权威图谱。
4. 平台只会把能够无歧义回切原文、且实体和证据均不与修复片段重叠的候选送入普通 pending 流程。
5. evidence_spans 必须定位当前视图，禁止返回 evidence_quote。
6. 不重复已有候选；实体不超过 {max_entities} 条，关系不超过 {max_relations} 条，总数不超过 {max_records} 条。

{domain_guidance}

仅返回 JSON：
{{
  "entities":[{{"id":"repair-e1","text":"实体","label":"本体类型","start":0,"end":2,"confidence":0.0}}],
  "relations":[{{
    "source":"repair-e1 或当前候选唯一 id","target":"新增实体 id 或当前候选唯一 id","label":"关系编码",
    "claim_level":"Fact 或 Inference","confidence":0.0,"evidence_spans":[{{"start":0,"end":10}}]
  }}]
}}

本体：
{ontology}

已校验修复清单（只作用于临时视图）：
{repair_manifest}

当前已有候选（Span 已映射到临时视图）：
{candidates}

结构上下文（仅辅助消歧，不是证据）：
{context}

临时修复视图：
{text}
"""


class EnhancementPromptBudgetExceededError(ValueError):
    """增强 Prompt 超出配置预算。"""

    def __init__(
        self,
        *,
        stage: str,
        actual_chars: int,
        limit_chars: int,
        actual_tokens: int,
        limit_tokens: int,
    ):
        self.stage = stage
        self.actual_chars = actual_chars
        self.limit_chars = limit_chars
        self.actual_tokens = actual_tokens
        self.limit_tokens = limit_tokens
        super().__init__(
            f"{stage} Prompt 预算超限: chars={actual_chars}/{limit_chars}, "
            f"estimated_tokens={actual_tokens}/{limit_tokens}"
        )


class LightRAGQualityEnhancer:
    """组合严格 JSON 初抽增强、一次 gleaning 和领域质量钩子。"""

    def __init__(
        self,
        options: dict[str, Any] | None = None,
        *,
        llm: LLMGraphExtractor | None = None,
    ):
        self.options = dict(options or {})
        llm_options = {
            key: deepcopy(value)
            for key, value in self.options.items()
            if key
            in {
                "model_spec",
                "model_params",
                "timeout_seconds",
                "max_output_tokens",
                "enable_thinking",
                "thinking_budget",
                "max_truncation_retries",
            }
        }
        model_params = dict(llm_options.get("model_params") or {})
        model_params.setdefault("stop", [self._json_stop_sequence()])
        llm_options["model_params"] = model_params
        llm_options.update(
            {
                "enable_hypothesis_extraction": False,
                "max_hypotheses_per_chunk": 0,
                "context_window_size": 0,
            }
        )
        self.llm = llm or LLMGraphExtractor(llm_options)

    def validate_options(self) -> None:
        self.llm.validate_options()
        self._max_gleanings()
        self._concurrency()
        self._parallel_initial_review()
        self._context_window_size()
        self._context_max_chars()
        self._stage_limits("initial")
        self._stage_limits("gleaning")
        self._max_initial_prompt_chars()
        self._max_gleaning_input_chars()
        self._max_initial_prompt_tokens()
        self._max_gleaning_input_tokens()
        self._max_prompt_entities()
        self._max_prompt_relations()
        self._domain_guidance_enabled()
        self._entity_review_mode()
        self._entity_review_min_confidence()
        self._entity_review_trigger()
        self._entity_review_max_candidates()
        self._layout_normalization_config()
        self._ocr_repair_config()
        self._adaptive_routing_config()
        self._relation_completion_config()
        self._enhancement_revision()
        self._json_stop_sequence()

    async def _complete_json(
        self,
        prompt: str,
        *,
        chunk_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """以显式终止标记约束本地模型，避免 JSON 后重复生成直至 token 上限。"""

        stop = self._json_stop_sequence()
        bounded_prompt = (
            f"{prompt}\n\n输出一个完整 JSON 对象后，立即输出终止标记 {stop}；"
            "终止标记前后都不要输出解释、Markdown 或第二个 JSON。"
        )
        return await self.llm.complete_json(bounded_prompt, chunk_metadata=chunk_metadata)

    def _json_stop_sequence(self) -> str:
        value = str(self.options.get("json_stop_sequence") or DEFAULT_JSON_STOP_SEQUENCE).strip()
        if not value or len(value) > 64 or any(character.isspace() for character in value):
            raise ValueError("json_stop_sequence 必须是不含空白且不超过 64 字符的非空字符串")
        return value

    async def enhance(
        self,
        text: str,
        base_result: dict[str, Any],
        *,
        chunk_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行可独立降级的初抽增强和至多一次补抽。"""
        initial = await self.enhance_initial(text, base_result, chunk_metadata=chunk_metadata)
        return await self.glean(text, initial, chunk_metadata=chunk_metadata)

    async def enhance_initial(
        self,
        text: str,
        base_result: dict[str, Any],
        *,
        chunk_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """先过滤明显 OCR 损伤，再补充可供质量门禁复核的实体与关系候选。"""
        self.validate_options()
        filtered_result, damage_spans = apply_ocr_quality_hook(text, base_result)
        filtered_result = filter_clear_non_ontology_candidates(filtered_result)
        filtered_result = resolve_deterministic_entity_type_conflicts(filtered_result)
        reference_metrics = reference_section_metrics(text)
        if reference_metrics["is_reference_section"]:
            metadata = dict(filtered_result.get("metadata") or {})
            metadata["llm_enhancement"] = {
                "enabled": True,
                "status": "skipped_reference_section",
                "strategy": "reference_section_quality_guard",
                "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
                "model_spec": str(self.options.get("model_spec") or "unknown"),
                "initial_status": "skipped_reference_section",
                "gleaning_status": "skipped_reference_section",
                "gleaning_calls": 0,
                "reference_section": reference_metrics,
                "ocr_damage_count": len(detect_ocr_damage(text)),
                "repair_proposals": [],
            }
            return {**filtered_result, "metadata": metadata}
        adaptive_routing = decide_lightrag_adaptive_routing(
            text,
            filtered_result,
            self._adaptive_routing_config(),
        )
        if not adaptive_routing["should_enhance"]:
            metadata = dict(filtered_result.get("metadata") or {})
            metadata["llm_enhancement"] = {
                "enabled": True,
                "status": "skipped_adaptive",
                "strategy": "adaptive_lightrag_recall_then_supervised_review_then_gleaning",
                "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
                "model_spec": str(self.options.get("model_spec") or "unknown"),
                "initial_status": "skipped_adaptive",
                "gleaning_status": "skipped_adaptive",
                "gleaning_calls": 0,
                "ocr_damage_count": len(damage_spans),
                "repair_proposals": [],
                "adaptive_routing": adaptive_routing,
                "layout_normalization": {
                    "enabled": self._layout_normalization_config()["enabled"],
                    "status": "skipped_adaptive",
                    "llm_calls": 0,
                },
                "ocr_repair_extraction": {
                    "enabled": self._ocr_repair_config()["enabled"],
                    "status": "skipped_adaptive",
                    "llm_calls": 0,
                },
            }
            return {**filtered_result, "metadata": metadata}
        filtered_result, layout_normalization_report, layout_hints = self._prepare_layout_hints(
            text,
            filtered_result,
        )
        try:
            supplemental = bool(filtered_result.get("entities") or filtered_result.get("relations"))
            max_entities, max_relations, max_records = self._effective_stage_limits(
                "initial",
                len(text),
                supplemental=supplemental,
            )
            prompt_entities, prompt_relations = self._effective_prompt_limits(len(text))
            initial_candidates, initial_endpoint_aliases = _prompt_candidates_with_endpoint_aliases(
                filtered_result,
                max_entities=prompt_entities,
                max_relations=prompt_relations,
            )
            initial_prompt = INITIAL_ENHANCEMENT_PROMPT.format(
                ontology=self._ontology_prompt(),
                candidates=initial_candidates,
                context=_prompt_context(chunk_metadata, max_chars=self._context_max_chars()),
                ocr_damage=_prompt_ocr_damage(damage_spans),
                layout_hints=json.dumps(layout_hints, ensure_ascii=False, separators=(",", ":")),
                text=text,
                max_entities=max_entities,
                max_relations=max_relations,
                max_records=max_records,
                domain_guidance=self._domain_guidance(),
            )
            initial_prompt_tokens = _enforce_prompt_budget(
                initial_prompt,
                stage="initial_enhancement",
                max_chars=self._max_initial_prompt_chars(),
                max_tokens=self._max_initial_prompt_tokens(),
            )
            review_prompt, review_bindings = build_entity_review_prompt(
                text,
                filtered_result.get("entities") or [],
                ontology_definition=self._ontology_definition(),
                trigger=self._entity_review_trigger(),
                max_candidates=self._entity_review_max_candidates(),
            )
            if self._entity_review_mode() == "off":
                review_prompt, review_bindings = None, {}
            review_prompt_tokens = (
                _enforce_prompt_budget(
                    review_prompt,
                    stage="entity_review",
                    max_chars=self._max_initial_prompt_chars(),
                    max_tokens=self._max_initial_prompt_tokens(),
                )
                if review_prompt
                else 0
            )
            if review_prompt and self._parallel_initial_review():
                outcomes = await asyncio.gather(
                    self._complete_json(initial_prompt, chunk_metadata=chunk_metadata),
                    self._complete_json(review_prompt, chunk_metadata=chunk_metadata),
                    return_exceptions=True,
                )
            else:
                outcomes = [
                    await _capture_model_call(self._complete_json(initial_prompt, chunk_metadata=chunk_metadata))
                ]
                if review_prompt:
                    outcomes.append(
                        await _capture_model_call(self._complete_json(review_prompt, chunk_metadata=chunk_metadata))
                    )
            initial_raw = outcomes[0]
            initial_error: BaseException | None = None
            try:
                if isinstance(initial_raw, BaseException):
                    raise initial_raw
                initial = prepare_llm_candidates(
                    initial_raw,
                    source_text=text,
                    known_entities=filtered_result.get("entities") or [],
                    stage="initial_enhancement",
                    max_entities=max_entities,
                    max_relations=max_relations,
                    max_records=max_records,
                    endpoint_aliases=initial_endpoint_aliases,
                )
            except Exception as exc:
                if self.options.get("strict") is True:
                    raise
                initial_error = exc
                initial = {
                    "entities": [],
                    "relations": [],
                    "metadata": {
                        "stage": "initial_enhancement",
                        "ocr_repair_proposals": [],
                    },
                }
            review_proposals = []
            review_diagnostics = {
                "raw_decision_count": 0,
                "unknown_review_ref_count": 0,
                "valid_decision_count": 0,
            }
            review_call_status = "not_requested"
            review_error_type = None
            review_error_code = None
            if review_prompt:
                review_outcome = outcomes[1]
                if isinstance(review_outcome, BaseException):
                    if self.options.get("strict") is True:
                        raise review_outcome
                    review_call_status = "degraded"
                    review_error_type = type(review_outcome).__name__
                    review_error_code = _safe_enhancement_error_code(review_outcome)
                else:
                    review_call_status = "completed"
                    review_proposals, review_diagnostics = validate_entity_review_decisions(
                        review_outcome,
                        source_text=text,
                        bindings=review_bindings,
                    )
            reviewed_result = review_entities(
                filtered_result,
                review_proposals,
                mode=self._entity_review_mode(),
                min_confidence=self._entity_review_min_confidence(),
            )
            review_report = dict(reviewed_result.get("metadata", {}).get("entity_review") or {})
            review_report.update(
                {
                    "call_status": review_call_status,
                    "error_type": review_error_type,
                    "error_code": review_error_code,
                    "prompt_chars": len(review_prompt or ""),
                    "prompt_estimated_tokens": review_prompt_tokens,
                    "candidate_count": len(review_bindings),
                    **review_diagnostics,
                }
            )
            reviewed_result.setdefault("metadata", {})["entity_review"] = review_report
            enhanced = merge_enhancement_result(reviewed_result, initial)
            enhanced, ocr_repair_report = await self._enhance_from_ocr_repair_view(
                text,
                enhanced,
                initial.get("metadata", {}).get("ocr_repair_proposals") or [],
                damage_spans=damage_spans,
                chunk_metadata=chunk_metadata,
            )
            enhanced = filter_clear_non_ontology_candidates(enhanced)
            enhanced = resolve_deterministic_entity_type_conflicts(
                enhanced,
                relabel_single_candidates=self._entity_review_mode() == "apply_experiment",
            )
        except Exception as exc:
            if self.options.get("strict") is True:
                raise
            metadata = dict(filtered_result.get("metadata") or {})
            budget_exceeded = isinstance(exc, EnhancementPromptBudgetExceededError)
            metadata["llm_enhancement"] = {
                "enabled": True,
                "status": "degraded",
                "strategy": "lightrag_recall_then_supervised_review_then_gleaning",
                "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
                "model_spec": str(self.options.get("model_spec") or "unknown"),
                "initial_status": "skipped_budget" if budget_exceeded else "degraded",
                "gleaning_status": "not_started",
                "gleaning_calls": 0,
                "error_type": type(exc).__name__,
                "error_code": _safe_enhancement_error_code(exc),
                "initial_prompt_chars": exc.actual_chars if budget_exceeded else None,
                "initial_prompt_limit_chars": self._max_initial_prompt_chars(),
                "initial_prompt_estimated_tokens": exc.actual_tokens if budget_exceeded else None,
                "initial_prompt_limit_tokens": self._max_initial_prompt_tokens(),
                "ocr_damage_count": len(damage_spans),
                "repair_proposals": [],
                "adaptive_routing": adaptive_routing,
                "layout_normalization": layout_normalization_report,
                "ocr_repair_extraction": {
                    "enabled": self._ocr_repair_config()["enabled"],
                    "status": "not_completed",
                    "llm_calls": 0,
                },
            }
            return {**filtered_result, "metadata": metadata}

        metadata = dict(enhanced.get("metadata") or {})
        initial_degraded = initial_error is not None
        metadata["llm_enhancement"] = {
            "enabled": True,
            "status": "degraded" if initial_degraded else "completed",
            "strategy": "lightrag_recall_then_supervised_review_then_gleaning",
            "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
            "model_spec": str(self.options.get("model_spec") or "unknown"),
            "initial_status": "degraded" if initial_degraded else "completed",
            "gleaning_status": "not_started",
            "gleaning_calls": 0,
            "initial_prompt_chars": len(initial_prompt),
            "initial_prompt_limit_chars": self._max_initial_prompt_chars(),
            "initial_prompt_estimated_tokens": initial_prompt_tokens,
            "initial_prompt_limit_tokens": self._max_initial_prompt_tokens(),
            "initial_output_budget": _candidate_budget_metadata(initial),
            "effective_output_limits": {
                "entities": max_entities,
                "relations": max_relations,
                "records": max_records,
                "source_chars": len(text),
                "supplemental": supplemental,
            },
            "effective_prompt_limits": {
                "entities": prompt_entities,
                "relations": prompt_relations,
            },
            "max_output_tokens": self._configured_max_output_tokens(),
            "ocr_damage_count": len(damage_spans),
            "repair_proposals": initial.get("metadata", {}).get("ocr_repair_proposals") or [],
            "adaptive_routing": adaptive_routing,
            "layout_normalization": layout_normalization_report,
            "ocr_repair_extraction": ocr_repair_report,
            "entity_review": enhanced.get("metadata", {}).get("entity_review") or {},
        }
        if initial_error is not None:
            metadata["llm_enhancement"].update(
                {
                    "error_type": type(initial_error).__name__,
                    "error_code": _safe_enhancement_error_code(initial_error),
                }
            )
        return {**enhanced, "metadata": metadata}

    def _prepare_layout_hints(
        self,
        source_text: str,
        base_result: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """把可确定的排版断词并入初抽 Prompt，避免为同一 Chunk 单独调用 LLM。"""
        config = self._layout_normalization_config()
        base_report = {
            "enabled": config["enabled"],
            "release_channel": "stable" if config["enabled"] else None,
            "original_text_preserved": True,
            "llm_calls": 0,
            "strategy": "inline_initial_prompt_hints",
        }
        if not config["enabled"]:
            return base_result, {**base_report, "status": "disabled"}, []

        view = build_layout_normalized_text_view(
            source_text,
            max_deletions=config["max_deletions"],
            max_whitespace_chars=config["max_whitespace_chars"],
        )
        deletion_count = len(view.deletions)
        deleted_char_count = sum(len(item.deleted_text) for item in view.deletions)
        if not deletion_count:
            return (
                base_result,
                {
                    **base_report,
                    "status": "skipped_no_layout_damage",
                    "deletion_count": 0,
                    "deleted_char_count": 0,
                    "hint_count": 0,
                },
                [],
            )

        damage_spans = detect_ocr_damage(source_text)
        independent_deletions = [
            deletion
            for deletion in view.deletions
            if not any(
                deletion.original_start <= damage.end and deletion.original_end >= damage.start
                for damage in damage_spans
            )
        ]
        if damage_spans and not independent_deletions:
            return (
                base_result,
                {
                    **base_report,
                    "status": "skipped_ocr_damage_only",
                    "deletion_count": deletion_count,
                    "deleted_char_count": deleted_char_count,
                    "ocr_adjacent_deletion_count": deletion_count,
                    "hint_count": 0,
                },
                [],
            )

        hints = [_inline_layout_hint(view, deletion) for deletion in independent_deletions[:MAX_INLINE_LAYOUT_HINTS]]
        return (
            base_result,
            {
                **base_report,
                "status": "merged_into_initial_prompt",
                "deletion_count": deletion_count,
                "deleted_char_count": deleted_char_count,
                "ocr_adjacent_deletion_count": deletion_count - len(independent_deletions),
                "hint_count": len(hints),
                "hint_truncated": len(independent_deletions) > len(hints),
                "authority_write_enabled": False,
            },
            hints,
        )

    async def _enhance_from_ocr_repair_view(
        self,
        source_text: str,
        base_result: dict[str, Any],
        proposals: list[dict[str, Any]],
        *,
        damage_spans: list[OCRDamageSpan],
        chunk_metadata: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """在实验通道临时修复视图上复抽，并隔离依赖修复文本的结果。"""
        config = self._ocr_repair_config()
        base_report = {
            "enabled": config["enabled"],
            "release_channel": "experiment" if config["enabled"] else None,
            "original_text_preserved": True,
            "llm_calls": 0,
            "min_confidence": config.get("min_confidence"),
        }
        if not config["enabled"]:
            return base_result, {**base_report, "status": "disabled"}

        detected = [
            proposal
            for proposal in proposals
            if any(
                int(proposal.get("original_start", -1)) < damage.end
                and int(proposal.get("original_end", -1)) > damage.start
                for damage in damage_spans
            )
        ]
        view = build_ocr_repaired_text_view(
            source_text,
            detected,
            min_confidence=config["min_confidence"],
            max_proposals=config["max_proposals"],
        )
        if not view.patches:
            return base_result, {
                **base_report,
                "status": "skipped_no_valid_proposal",
                "proposal_count": len(proposals),
                "detected_damage_proposal_count": len(detected),
                "rejected_proposal_count": len(view.rejected_proposals),
                "rejection_reason_counts": _repair_rejection_reason_counts(view.rejected_proposals),
            }

        try:
            view_candidates = candidates_for_repaired_view(base_result, view)
            prompt_candidates, prompt_endpoint_aliases = _prompt_candidates_with_endpoint_aliases(
                view_candidates,
                max_entities=self._max_prompt_entities(),
                max_relations=self._max_prompt_relations(),
            )
            prompt = OCR_REPAIR_EXTRACTION_PROMPT.format(
                ontology=self._ontology_prompt(),
                repair_manifest=json.dumps(view.patch_manifest(), ensure_ascii=False, separators=(",", ":")),
                candidates=prompt_candidates,
                context=_prompt_context(chunk_metadata, max_chars=self._context_max_chars()),
                text=view.repaired_text,
                max_entities=config["max_entities"],
                max_relations=config["max_relations"],
                max_records=config["max_records"],
                domain_guidance=self._domain_guidance(),
            )
            prompt_tokens = _enforce_prompt_budget(
                prompt,
                stage="ocr_repair_extraction",
                max_chars=config["max_prompt_chars"],
                max_tokens=config["max_prompt_tokens"],
            )
            raw = await self._complete_json(prompt, chunk_metadata=chunk_metadata)
            prepared = prepare_llm_candidates(
                raw,
                source_text=view.repaired_text,
                known_entities=view_candidates["entities"],
                stage="ocr_repair_extraction",
                max_entities=config["max_entities"],
                max_relations=config["max_relations"],
                max_records=config["max_records"],
                endpoint_aliases=prompt_endpoint_aliases,
            )
            remapped = partition_repaired_view_candidates(
                prepared,
                view,
                original_known_entities=base_result.get("entities") or [],
            )
            enhanced = merge_enhancement_result(base_result, remapped)
            report = {
                **base_report,
                "status": "completed",
                "llm_calls": 1,
                "proposal_count": len(proposals),
                "applied_to_temporary_view_count": len(view.patches),
                "rejected_proposal_count": len(view.rejected_proposals),
                "rejection_reason_counts": _repair_rejection_reason_counts(view.rejected_proposals),
                "prompt_chars": len(prompt),
                "prompt_estimated_tokens": prompt_tokens,
                "regular_entity_count": len(remapped["entities"]),
                "regular_relation_count": len(remapped["relations"]),
                "repair_dependent_entity_count": remapped["metadata"]["repair_dependent_entity_count"],
                "repair_dependent_relation_count": remapped["metadata"]["repair_dependent_relation_count"],
                "authority_eligible_repair_dependent": False,
                "review_candidate_eligible_repair_dependent": False,
            }
            return enhanced, report
        except Exception as exc:
            if self.options.get("strict") is True:
                raise
            return base_result, {
                **base_report,
                "status": "degraded",
                "llm_calls": 1,
                "proposal_count": len(proposals),
                "applied_to_temporary_view_count": len(view.patches),
                "error_type": type(exc).__name__,
                "error_code": _safe_enhancement_error_code(exc),
            }

    async def glean(
        self,
        text: str,
        base_result: dict[str, Any],
        *,
        chunk_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """在监督复核后的完整候选上补漏；失败时保留此前所有成功结果。"""
        self.validate_options()
        base_result = filter_clear_non_ontology_candidates(base_result)
        base_result = resolve_deterministic_entity_type_conflicts(
            base_result,
            relabel_single_candidates=self._entity_review_mode() == "apply_experiment",
        )
        metadata = dict(base_result.get("metadata") or {})
        report = dict(metadata.get("llm_enhancement") or {})
        if report.get("initial_status") in {"skipped_adaptive", "skipped_reference_section"}:
            skipped_status = str(report["initial_status"])
            report.update({"gleaning_status": skipped_status, "gleaning_calls": 0})
            metadata["llm_enhancement"] = report
            return {**deepcopy(base_result), "metadata": metadata}
        if self._max_gleanings() == 0:
            report.update({"gleaning_status": "skipped", "gleaning_calls": 0})
            metadata["llm_enhancement"] = report
            return {**deepcopy(base_result), "metadata": metadata}

        max_entities, max_relations, max_records = self._effective_stage_limits(
            "gleaning",
            len(text),
            supplemental=True,
        )
        prompt_entities, prompt_relations = self._effective_prompt_limits(len(text))
        relation_completion = build_relation_completion_inventory(
            text,
            base_result,
            self._relation_completion_config(),
        )
        endpoint_aliases: dict[str, dict[str, Any]] = {}
        allowed_relation_claims: set[tuple[str, str, str]] | None = None
        min_relation_confidence = 0.0
        if relation_completion["config"]["enabled"]:
            if not relation_completion["candidates"]:
                report.update(
                    {
                        "enabled": True,
                        "status": "completed",
                        "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
                        "gleaning_status": "skipped_no_relation_candidates",
                        "gleaning_calls": 0,
                        "gleaning_mode": "relation_completion",
                        "relation_completion": {
                            "revision": relation_completion["revision"],
                            **relation_completion["metrics"],
                            "accepted_relation_count": 0,
                        },
                    }
                )
                metadata["llm_enhancement"] = report
                return {**deepcopy(base_result), "metadata": metadata}
            endpoint_aliases = relation_completion["endpoint_aliases"]
            allowed_relation_claims = relation_completion["allowed_relation_claims"]
            min_relation_confidence = relation_completion["config"]["min_relation_confidence"]
            gleaning_prompt = RELATION_COMPLETION_PROMPT.format(
                ontology=self._ontology_prompt(),
                existing_relations=json.dumps(
                    [
                        _compact_prompt_relation(relation)
                        for relation in (base_result.get("relations") or [])[:prompt_relations]
                        if isinstance(relation, dict)
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                semantic_chain_analysis=json.dumps(
                    analyze_five_role_recall(
                        base_result.get("entities") or [],
                        base_result.get("relations") or [],
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                relation_candidates=json.dumps(
                    relation_completion_prompt_payload(relation_completion),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                context=_prompt_context(chunk_metadata, max_chars=self._context_max_chars()),
                text=text,
                max_relations=max_relations,
                min_relation_confidence=min_relation_confidence,
                domain_guidance=self._domain_guidance(),
            )
            gleaning_mode = "relation_completion"
        else:
            prompt_candidates, balanced_endpoint_aliases = _prompt_candidates_with_endpoint_aliases(
                base_result,
                max_entities=prompt_entities,
                max_relations=prompt_relations,
            )
            endpoint_aliases = balanced_endpoint_aliases
            gleaning_prompt = GLEANING_PROMPT.format(
                ontology=self._ontology_prompt(),
                candidates=prompt_candidates,
                semantic_chain_analysis=json.dumps(
                    analyze_five_role_recall(
                        base_result.get("entities") or [],
                        base_result.get("relations") or [],
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                context=_prompt_context(chunk_metadata, max_chars=self._context_max_chars()),
                ocr_damage=_prompt_ocr_damage(detect_ocr_damage(text)),
                text=text,
                max_entities=max_entities,
                max_relations=max_relations,
                max_records=max_records,
                domain_guidance=self._domain_guidance(),
            )
            gleaning_mode = "balanced"
        gleaning_prompt_tokens = _estimate_prompt_tokens(gleaning_prompt)
        if (
            len(gleaning_prompt) > self._max_gleaning_input_chars()
            or gleaning_prompt_tokens > self._max_gleaning_input_tokens()
        ):
            if self.options.get("strict") is True:
                raise EnhancementPromptBudgetExceededError(
                    stage="gleaning",
                    actual_chars=len(gleaning_prompt),
                    limit_chars=self._max_gleaning_input_chars(),
                    actual_tokens=gleaning_prompt_tokens,
                    limit_tokens=self._max_gleaning_input_tokens(),
                )
            report.update(
                {
                    "enabled": True,
                    "status": "completed",
                    "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
                    "gleaning_status": "skipped_budget",
                    "gleaning_calls": 0,
                    "gleaning_prompt_chars": len(gleaning_prompt),
                    "gleaning_input_limit_chars": self._max_gleaning_input_chars(),
                    "gleaning_prompt_estimated_tokens": gleaning_prompt_tokens,
                    "gleaning_input_limit_tokens": self._max_gleaning_input_tokens(),
                }
            )
            metadata["llm_enhancement"] = report
            return {**deepcopy(base_result), "metadata": metadata}

        try:
            gleaned_raw = await self._complete_json(
                gleaning_prompt,
                chunk_metadata=chunk_metadata,
            )
            gleaned = prepare_llm_candidates(
                gleaned_raw,
                source_text=text,
                known_entities=base_result.get("entities") or [],
                stage="gleaning",
                max_entities=max_entities,
                max_relations=max_relations,
                max_records=max_records,
                endpoint_aliases=endpoint_aliases,
                allowed_relation_claims=allowed_relation_claims,
                min_relation_confidence=min_relation_confidence,
            )
            enhanced = merge_enhancement_result(base_result, gleaned)
            enhanced = filter_clear_non_ontology_candidates(enhanced)
            enhanced = resolve_deterministic_entity_type_conflicts(
                enhanced,
                relabel_single_candidates=self._entity_review_mode() == "apply_experiment",
            )
        except Exception as exc:
            if self.options.get("strict") is True:
                raise
            metadata = dict(base_result.get("metadata") or {})
            report = dict(metadata.get("llm_enhancement") or {})
            report.update(
                {
                    "enabled": True,
                    "status": "degraded",
                    "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
                    "model_spec": str(self.options.get("model_spec") or "unknown"),
                    "gleaning_status": "degraded",
                    "gleaning_calls": 1,
                    "gleaning_prompt_chars": len(gleaning_prompt),
                    "gleaning_input_limit_chars": self._max_gleaning_input_chars(),
                    "gleaning_prompt_estimated_tokens": gleaning_prompt_tokens,
                    "gleaning_input_limit_tokens": self._max_gleaning_input_tokens(),
                    "gleaning_error_type": type(exc).__name__,
                    "gleaning_error_code": _safe_enhancement_error_code(exc),
                }
            )
            metadata["llm_enhancement"] = report
            return {**deepcopy(base_result), "metadata": metadata}

        metadata = dict(enhanced.get("metadata") or {})
        report = dict(metadata.get("llm_enhancement") or report)
        report.update(
            {
                "enabled": True,
                "status": "completed",
                "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
                "model_spec": str(self.options.get("model_spec") or "unknown"),
                "gleaning_status": "completed",
                "gleaning_calls": 1,
                "gleaning_mode": gleaning_mode,
                "gleaning_prompt_chars": len(gleaning_prompt),
                "gleaning_input_limit_chars": self._max_gleaning_input_chars(),
                "gleaning_prompt_estimated_tokens": gleaning_prompt_tokens,
                "gleaning_input_limit_tokens": self._max_gleaning_input_tokens(),
                "gleaning_output_budget": _candidate_budget_metadata(gleaned),
                "gleaning_effective_output_limits": {
                    "entities": max_entities,
                    "relations": max_relations,
                    "records": max_records,
                    "source_chars": len(text),
                    "supplemental": True,
                },
                "gleaning_effective_prompt_limits": {
                    "entities": prompt_entities,
                    "relations": prompt_relations,
                },
                "max_output_tokens": self._configured_max_output_tokens(),
                "repair_proposals": _merge_repair_proposals(
                    report.get("repair_proposals") or [],
                    gleaned.get("metadata", {}).get("ocr_repair_proposals") or [],
                ),
                "relation_completion": {
                    "revision": relation_completion["revision"],
                    **relation_completion["metrics"],
                    "accepted_relation_count": len(gleaned.get("relations") or []),
                    "min_relation_confidence": min_relation_confidence,
                }
                if relation_completion["config"]["enabled"]
                else {"enabled": False},
            }
        )
        metadata["llm_enhancement"] = report
        return {**enhanced, "metadata": metadata}

    async def enhance_batch(
        self,
        inputs: list[GraphExtractionInput],
        base_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """有界并发增强批次，保持输入顺序。"""
        initial = await self.enhance_initial_batch(inputs, base_results)
        return await self.glean_batch(inputs, initial)

    async def enhance_initial_batch(
        self,
        inputs: list[GraphExtractionInput],
        base_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """有界并发执行初抽召回增强，供后续监督模型消费新增 Span。"""
        return await self._map_batch(inputs, base_results, self.enhance_initial)

    async def glean_batch(
        self,
        inputs: list[GraphExtractionInput],
        base_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """有界并发执行末端补抽，并保持输入顺序。"""
        return await self._map_batch(inputs, base_results, self.glean)

    async def _map_batch(self, inputs, base_results, operation) -> list[dict[str, Any]]:
        if len(inputs) != len(base_results):
            raise ValueError("LLM 增强要求输入与基础结果数量一致")
        semaphore = asyncio.Semaphore(self._concurrency())

        async def run_one(item: GraphExtractionInput, result: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await operation(item.text, result, chunk_metadata=item.chunk_metadata)

        return await asyncio.gather(*(run_one(item, result) for item, result in zip(inputs, base_results, strict=True)))

    async def aclose(self) -> None:
        await self.llm.aclose()

    def _max_gleanings(self) -> int:
        raw = self.options.get("max_gleanings", DEFAULT_MAX_GLEANINGS)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw not in {0, 1}:
            raise ValueError("llm_enhancement.max_gleanings 只能是 0 或 1")
        return raw

    def _concurrency(self) -> int:
        raw = self.options.get("concurrency_count", 1)
        if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= MAX_ENHANCEMENT_CONCURRENCY:
            raise ValueError(f"llm_enhancement.concurrency_count 必须在 1 到 {MAX_ENHANCEMENT_CONCURRENCY} 之间")
        return raw

    def _parallel_initial_review(self) -> bool:
        """本地默认串行初抽和判型，避免同一 Metal GPU 上长请求争抢与热峰值。"""
        value = self.options.get("parallel_initial_review", False)
        if not isinstance(value, bool):
            raise ValueError("llm_enhancement.parallel_initial_review 必须是布尔值")
        return value

    def _context_window_size(self) -> int:
        raw = self.options.get("context_window_size", 1)
        if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= MAX_CONTEXT_WINDOW_SIZE:
            raise ValueError(f"llm_enhancement.context_window_size 必须在 0 到 {MAX_CONTEXT_WINDOW_SIZE} 之间")
        return raw

    def _context_max_chars(self) -> int:
        raw = self.options.get("context_max_chars", 1200)
        if isinstance(raw, bool) or not isinstance(raw, int) or not 500 <= raw <= MAX_CONTEXT_CHARS:
            raise ValueError(f"llm_enhancement.context_max_chars 必须在 500 到 {MAX_CONTEXT_CHARS} 之间")
        return raw

    def _stage_limits(self, stage: str) -> tuple[int, int, int]:
        if stage == "initial":
            defaults = (
                DEFAULT_MAX_INITIAL_ENTITIES,
                DEFAULT_MAX_INITIAL_RELATIONS,
                DEFAULT_MAX_INITIAL_RECORDS,
            )
            keys = ("max_initial_entities", "max_initial_relations", "max_initial_records")
        elif stage == "gleaning":
            defaults = (
                DEFAULT_MAX_GLEANING_ENTITIES,
                DEFAULT_MAX_GLEANING_RELATIONS,
                DEFAULT_MAX_GLEANING_RECORDS,
            )
            keys = ("max_gleaning_entities", "max_gleaning_relations", "max_gleaning_records")
        else:  # pragma: no cover - 内部编程错误
            raise ValueError(f"未知增强阶段: {stage}")
        values = tuple(
            _bounded_int_option(
                self.options.get(key, default),
                f"llm_enhancement.{key}",
                minimum=1,
                maximum=MAX_LLM_CANDIDATE_RECORDS,
            )
            for key, default in zip(keys, defaults, strict=True)
        )
        if values[2] < values[0]:
            raise ValueError(f"llm_enhancement.{keys[2]} 不能小于 {keys[0]}")
        return values

    def _effective_stage_limits(
        self,
        stage: str,
        source_chars: int,
        *,
        supplemental: bool = False,
    ) -> tuple[int, int, int]:
        """按主抽或补漏密度约束短 Block，避免重复候选和截断 JSON。"""
        configured_entities, configured_relations, configured_records = self._stage_limits(stage)
        length = max(int(source_chars), 0)
        if supplemental:
            entity_limit = min(configured_entities, max(6, math.ceil(length / 75) + 2))
            relation_limit = min(configured_relations, max(6, math.ceil(length / 60) + 2))
            record_limit = min(configured_records, max(8, math.ceil(length / 55) + 4))
        else:
            entity_limit = min(configured_entities, max(8, math.ceil(length / 45) + 4))
            relation_limit = min(configured_relations, max(8, math.ceil(length / 35) + 4))
            record_limit = min(configured_records, max(12, math.ceil(length / 30) + 4))
        record_limit = max(record_limit, entity_limit)
        return entity_limit, relation_limit, record_limit

    def _effective_prompt_limits(self, source_chars: int) -> tuple[int, int]:
        """按原文长度裁剪已有候选输入，保留高优先级记录并控制 Prompt 规模。"""
        length = max(int(source_chars), 0)
        entity_limit = min(self._max_prompt_entities(), max(8, math.ceil(length / 45) + 4))
        relation_limit = min(self._max_prompt_relations(), max(8, math.ceil(length / 35) + 4))
        return entity_limit, relation_limit

    def _max_initial_prompt_chars(self) -> int:
        return _bounded_int_option(
            self.options.get("max_prompt_chars", DEFAULT_MAX_INITIAL_PROMPT_CHARS),
            "llm_enhancement.max_prompt_chars",
            minimum=2_000,
            maximum=MAX_LLM_PROMPT_CHARS,
        )

    def _max_gleaning_input_chars(self) -> int:
        return _bounded_int_option(
            self.options.get("max_gleaning_input_chars", DEFAULT_MAX_GLEANING_INPUT_CHARS),
            "llm_enhancement.max_gleaning_input_chars",
            minimum=2_000,
            maximum=MAX_LLM_PROMPT_CHARS,
        )

    def _max_initial_prompt_tokens(self) -> int:
        return _bounded_int_option(
            self.options.get("max_prompt_tokens", DEFAULT_MAX_INITIAL_PROMPT_TOKENS),
            "llm_enhancement.max_prompt_tokens",
            minimum=1_000,
            maximum=MAX_LLM_PROMPT_TOKENS,
        )

    def _max_gleaning_input_tokens(self) -> int:
        return _bounded_int_option(
            self.options.get("max_gleaning_input_tokens", DEFAULT_MAX_GLEANING_INPUT_TOKENS),
            "llm_enhancement.max_gleaning_input_tokens",
            minimum=1_000,
            maximum=MAX_LLM_PROMPT_TOKENS,
        )

    def _max_prompt_entities(self) -> int:
        return _bounded_int_option(
            self.options.get("max_prompt_entities", DEFAULT_MAX_PROMPT_ENTITIES),
            "llm_enhancement.max_prompt_entities",
            minimum=1,
            maximum=MAX_LLM_CANDIDATE_RECORDS,
        )

    def _max_prompt_relations(self) -> int:
        return _bounded_int_option(
            self.options.get("max_prompt_relations", DEFAULT_MAX_PROMPT_RELATIONS),
            "llm_enhancement.max_prompt_relations",
            minimum=1,
            maximum=MAX_LLM_CANDIDATE_RECORDS,
        )

    def _configured_max_output_tokens(self) -> int:
        params = self.options.get("model_params") or {}
        return int(
            params.get(
                "max_tokens",
                params.get("max_completion_tokens", self.options.get("max_output_tokens", 8192)),
            )
        )

    def _domain_guidance_enabled(self) -> bool:
        value = self.options.get("domain_guidance_enabled", True)
        if not isinstance(value, bool):
            raise ValueError("llm_enhancement.domain_guidance_enabled 必须是布尔值")
        return value

    def _domain_guidance(self) -> str:
        if not self._domain_guidance_enabled():
            return "未启用附加示例。"
        role_guidance = build_domain_extraction_guidance(DEFENSE_ONTOLOGY_V1.entity_types)
        return f"{role_guidance}\n\n{DOMAIN_EXTRACTION_GUIDANCE}"

    def _entity_review_mode(self) -> str:
        value = str(self.options.get("entity_review_mode") or "propose").strip()
        if value not in ENTITY_REVIEW_MODES:
            allowed = ", ".join(sorted(ENTITY_REVIEW_MODES))
            raise ValueError(f"llm_enhancement.entity_review_mode 必须是: {allowed}")
        return value

    def _entity_review_min_confidence(self) -> float:
        value = self.options.get(
            "entity_review_min_confidence",
            DEFAULT_ENTITY_REVIEW_MIN_CONFIDENCE,
        )
        if isinstance(value, bool):
            raise ValueError("llm_enhancement.entity_review_min_confidence 必须是 0 到 1 之间的数字")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("llm_enhancement.entity_review_min_confidence 必须是 0 到 1 之间的数字") from exc
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError("llm_enhancement.entity_review_min_confidence 必须是 0 到 1 之间的数字")
        return number

    def _entity_review_trigger(self) -> str:
        value = str(self.options.get("entity_review_trigger") or "suspect_only").strip()
        if value not in ENTITY_REVIEW_TRIGGERS:
            allowed = ", ".join(sorted(ENTITY_REVIEW_TRIGGERS))
            raise ValueError(f"llm_enhancement.entity_review_trigger 必须是: {allowed}")
        return value

    def _entity_review_max_candidates(self) -> int:
        return _bounded_int_option(
            self.options.get("entity_review_max_candidates", 24),
            "llm_enhancement.entity_review_max_candidates",
            minimum=1,
            maximum=MAX_LLM_CANDIDATE_RECORDS,
        )

    def _layout_normalization_config(self) -> dict[str, Any]:
        raw = self.options.get("layout_normalization") or {}
        if not isinstance(raw, dict):
            raise ValueError("llm_enhancement.layout_normalization 必须是对象")
        enabled = raw.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("llm_enhancement.layout_normalization.enabled 必须是布尔值")
        if not enabled:
            return {"enabled": False}

        max_entities = _bounded_int_option(
            raw.get("max_entities", DEFAULT_LAYOUT_NORMALIZATION_MAX_ENTITIES),
            "layout_normalization.max_entities",
            minimum=1,
            maximum=128,
        )
        max_records = _bounded_int_option(
            raw.get("max_records", DEFAULT_LAYOUT_NORMALIZATION_MAX_RECORDS),
            "layout_normalization.max_records",
            minimum=1,
            maximum=256,
        )
        if max_records < max_entities:
            raise ValueError("layout_normalization.max_records 不能小于 max_entities")
        return {
            "enabled": True,
            "max_deletions": _bounded_int_option(
                raw.get("max_deletions", DEFAULT_LAYOUT_NORMALIZATION_MAX_DELETIONS),
                "layout_normalization.max_deletions",
                minimum=1,
                maximum=4096,
            ),
            "max_whitespace_chars": _bounded_int_option(
                raw.get("max_whitespace_chars", DEFAULT_LAYOUT_NORMALIZATION_MAX_WHITESPACE_CHARS),
                "layout_normalization.max_whitespace_chars",
                minimum=1,
                maximum=32,
            ),
            "max_entities": max_entities,
            "max_relations": _bounded_int_option(
                raw.get("max_relations", DEFAULT_LAYOUT_NORMALIZATION_MAX_RELATIONS),
                "layout_normalization.max_relations",
                minimum=1,
                maximum=128,
            ),
            "max_records": max_records,
            "max_prompt_chars": _bounded_int_option(
                raw.get("max_prompt_chars", self._max_initial_prompt_chars()),
                "layout_normalization.max_prompt_chars",
                minimum=2_000,
                maximum=MAX_LLM_PROMPT_CHARS,
            ),
            "max_prompt_tokens": _bounded_int_option(
                raw.get("max_prompt_tokens", self._max_initial_prompt_tokens()),
                "layout_normalization.max_prompt_tokens",
                minimum=1_000,
                maximum=MAX_LLM_PROMPT_TOKENS,
            ),
        }

    def _ocr_repair_config(self) -> dict[str, Any]:
        raw = self.options.get("ocr_repair_extraction") or {}
        if not isinstance(raw, dict):
            raise ValueError("llm_enhancement.ocr_repair_extraction 必须是对象")
        enabled = raw.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("llm_enhancement.ocr_repair_extraction.enabled 必须是布尔值")
        if not enabled:
            return {"enabled": False}

        min_confidence = raw.get("min_confidence", DEFAULT_OCR_REPAIR_MIN_CONFIDENCE)
        if isinstance(min_confidence, bool):
            raise ValueError("ocr_repair_extraction.min_confidence 必须是 0 到 1 之间的数字")
        try:
            min_confidence = float(min_confidence)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("ocr_repair_extraction.min_confidence 必须是 0 到 1 之间的数字") from exc
        if not math.isfinite(min_confidence) or not 0.0 <= min_confidence <= 1.0:
            raise ValueError("ocr_repair_extraction.min_confidence 必须是 0 到 1 之间的数字")

        max_entities = _bounded_int_option(
            raw.get("max_entities", DEFAULT_OCR_REPAIR_MAX_ENTITIES),
            "ocr_repair_extraction.max_entities",
            minimum=1,
            maximum=128,
        )
        max_records = _bounded_int_option(
            raw.get("max_records", DEFAULT_OCR_REPAIR_MAX_RECORDS),
            "ocr_repair_extraction.max_records",
            minimum=1,
            maximum=256,
        )
        if max_records < max_entities:
            raise ValueError("ocr_repair_extraction.max_records 不能小于 max_entities")
        return {
            "enabled": True,
            "min_confidence": min_confidence,
            "max_proposals": _bounded_int_option(
                raw.get("max_proposals", DEFAULT_OCR_REPAIR_MAX_PROPOSALS),
                "ocr_repair_extraction.max_proposals",
                minimum=1,
                maximum=64,
            ),
            "max_entities": max_entities,
            "max_relations": _bounded_int_option(
                raw.get("max_relations", DEFAULT_OCR_REPAIR_MAX_RELATIONS),
                "ocr_repair_extraction.max_relations",
                minimum=1,
                maximum=128,
            ),
            "max_records": max_records,
            "max_prompt_chars": _bounded_int_option(
                raw.get("max_prompt_chars", self._max_initial_prompt_chars()),
                "ocr_repair_extraction.max_prompt_chars",
                minimum=2_000,
                maximum=MAX_LLM_PROMPT_CHARS,
            ),
            "max_prompt_tokens": _bounded_int_option(
                raw.get("max_prompt_tokens", self._max_initial_prompt_tokens()),
                "ocr_repair_extraction.max_prompt_tokens",
                minimum=1_000,
                maximum=MAX_LLM_PROMPT_TOKENS,
            ),
        }

    def _adaptive_routing_config(self) -> dict[str, Any]:
        """读取确定性疑难 Block 路由策略。"""
        return normalize_adaptive_routing_options(self.options.get("adaptive_routing"))

    def _relation_completion_config(self) -> dict[str, Any]:
        """读取封闭端点关系补抽策略。"""
        return normalize_relation_completion_options(self.options.get("relation_completion"))

    def _enhancement_revision(self) -> str:
        value = str(self.options.get("enhancement_revision") or LIGHTRAG_ENHANCEMENT_REVISION)
        if value != LIGHTRAG_ENHANCEMENT_REVISION:
            raise ValueError(f"当前仅支持 llm_enhancement.enhancement_revision={LIGHTRAG_ENHANCEMENT_REVISION}")
        return value

    def _ontology_prompt(self) -> str:
        definition = self._ontology_definition()
        entity_types = [
            {
                "code": str(item.get("code") or ""),
                "description": str(item.get("description") or ""),
            }
            for item in definition.get("entity_types") or []
            if isinstance(item, dict) and item.get("code")
        ]
        relation_types = [
            {
                "code": str(item.get("code") or ""),
                "head_types": list(item.get("head_types") or []),
                "tail_types": list(item.get("tail_types") or []),
                "description": str(item.get("description") or ""),
            }
            for item in definition.get("relation_types") or []
            if isinstance(item, dict) and item.get("code") and item.get("hypothesis_only") is not True
        ]
        return json.dumps(
            {"entity_types": entity_types, "relation_types": relation_types},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _ontology_definition(self) -> dict[str, Any]:
        return self.options.get("ontology_definition") or ontology_payload()


def _inline_layout_hint(
    view: LayoutNormalizedTextView,
    deletion: LayoutWhitespaceDeletion,
) -> dict[str, Any]:
    """生成短小、可核对且不改变权威原文坐标的排版连续术语提示。"""
    source_text = view.original_text
    start = deletion.original_start
    end = deletion.original_end
    excerpt_start = max(0, start - 16)
    excerpt_end = min(len(source_text), end + 16)
    normalized_start = view.original_prefix_kept[excerpt_start]
    normalized_end = view.original_prefix_kept[excerpt_end]
    return {
        "original_start": start,
        "original_end": end,
        "reason": deletion.reason,
        "excerpt_start": excerpt_start,
        "excerpt_end": excerpt_end,
        "original_excerpt": source_text[excerpt_start:excerpt_end],
        "continuous_excerpt": view.normalized_text[normalized_start:normalized_end],
    }


def apply_ocr_quality_hook(
    source_text: str,
    result: dict[str, Any],
) -> tuple[dict[str, Any], list[OCRDamageSpan]]:
    """过滤与明显损伤重叠的实体及悬空关系，并保留可审计统计。"""
    damage = detect_ocr_damage(source_text)
    if not damage:
        return deepcopy(result), []

    entities = [dict(entity) for entity in result.get("entities") or []]
    damaged_refs: set[str] = set()
    clean_entities = []
    for entity in entities:
        start, end = entity.get("start"), entity.get("end")
        damaged = any(
            isinstance(start, int) and isinstance(end, int) and start < item.end and end > item.start for item in damage
        ) or any(item.text == str(entity.get("text") or "") for item in damage)
        if not damaged:
            clean_entities.append(entity)
            continue
        damaged_refs.update({str(entity.get("id") or ""), str(entity.get("text") or "")})

    clean_relations = []
    dropped_relations = 0
    for relation in result.get("relations") or []:
        source_ref = _endpoint_ref(relation.get("source"))
        target_ref = _endpoint_ref(relation.get("target"))
        if source_ref in damaged_refs or target_ref in damaged_refs:
            dropped_relations += 1
            continue
        clean_relations.append(deepcopy(relation))

    metadata = dict(result.get("metadata") or {})
    metadata["ocr_quality_hook"] = {
        "damage_spans": [
            {"start": item.start, "end": item.end, "text": item.text, "reason": item.reason} for item in damage
        ],
        "dropped_entities": len(entities) - len(clean_entities),
        "dropped_relations": dropped_relations,
        "original_text_preserved": True,
    }
    return {
        "entities": clean_entities,
        "relations": clean_relations,
        "metadata": metadata,
    }, damage


async def _capture_model_call(call) -> dict[str, Any] | BaseException:
    """串行功耗模式下把单次模型失败保留为阶段结果，继续执行独立复核。"""
    try:
        return await call
    except Exception as exc:
        return exc


def _safe_enhancement_error_code(exc: BaseException) -> str:
    """把增强异常收敛为不包含模型原文或敏感正文的稳定审计编码。"""
    if isinstance(exc, EnhancementPromptBudgetExceededError):
        return "prompt_budget_exceeded"
    if isinstance(exc, ExtractionOutputTruncatedError):
        return "model_output_truncated"
    if isinstance(exc, TimeoutError):
        return "model_timeout"
    message = str(exc)
    if "模型未返回要求的 JSON 字段" in message:
        return "missing_required_json_keys"
    if "模型返回空抽取内容" in message:
        return "empty_model_output"
    if isinstance(exc, ValueError):
        return "invalid_model_payload"
    return "model_call_failed"


def prepare_llm_candidates(
    raw: dict[str, Any],
    *,
    source_text: str,
    known_entities: list[dict[str, Any]],
    stage: str,
    max_entities: int | None = None,
    max_relations: int | None = None,
    max_records: int | None = None,
    endpoint_aliases: dict[str, dict[str, Any]] | None = None,
    allowed_relation_claims: set[tuple[str, str, str]] | None = None,
    min_relation_confidence: float = 0.0,
) -> dict[str, Any]:
    """收敛 LLM 候选，并在平台侧执行确定性数量上限。"""
    entity_limit = _optional_positive_limit(max_entities, "max_entities")
    relation_limit = _optional_positive_limit(max_relations, "max_relations")
    record_limit = _optional_positive_limit(max_records, "max_records")
    prepared = _prepare_llm_candidates_unbounded(
        raw,
        source_text=source_text,
        known_entities=known_entities,
        stage=stage,
        endpoint_aliases=endpoint_aliases,
        allowed_relation_claims=allowed_relation_claims,
        min_relation_confidence=min_relation_confidence,
    )
    valid_entities = list(prepared["entities"])
    valid_relations = list(prepared["relations"])
    entity_rows = list(enumerate(valid_entities))
    entity_rows.sort(key=lambda row: _entity_priority(row[1], row[0]))
    valid_entities = [row[1] for row in entity_rows]

    entity_count = len(valid_entities)
    if entity_limit is not None:
        entity_count = min(entity_count, entity_limit)
    if record_limit is not None:
        entity_count = min(entity_count, record_limit)
    entities = valid_entities[:entity_count]
    truncated_entities = len(valid_entities) - len(entities)

    allowed_keys = {_entity_key(entity) for entity in [*known_entities, *entities]}
    non_dangling_relations = [
        relation
        for relation in valid_relations
        if _entity_key(relation["source"]) in allowed_keys and _entity_key(relation["target"]) in allowed_keys
    ]
    dangling_relations = len(valid_relations) - len(non_dangling_relations)
    relation_rows = list(enumerate(non_dangling_relations))
    relation_rows.sort(key=lambda row: _relation_priority(row[1], row[0]))
    non_dangling_relations = [row[1] for row in relation_rows]
    relation_count = len(non_dangling_relations)
    if relation_limit is not None:
        relation_count = min(relation_count, relation_limit)
    if record_limit is not None:
        relation_count = min(relation_count, max(record_limit - len(entities), 0))
    relations = non_dangling_relations[:relation_count]
    truncated_relations = len(non_dangling_relations) - len(relations)

    metadata = dict(prepared["metadata"])
    metadata.update(
        {
            "raw_entity_count": len(raw.get("entities") or []) if isinstance(raw.get("entities"), list) else 0,
            "raw_relation_count": len(raw.get("relations") or []) if isinstance(raw.get("relations"), list) else 0,
            "valid_entity_count": len(valid_entities),
            "valid_relation_count": len(valid_relations),
            "kept_entity_count": len(entities),
            "kept_relation_count": len(relations),
            "truncated_entities": truncated_entities,
            "truncated_relations": truncated_relations,
            "relations_dropped_with_truncated_endpoint": dangling_relations,
            "max_entities": entity_limit,
            "max_relations": relation_limit,
            "max_records": record_limit,
            "deterministic_truncation_applied": bool(truncated_entities or truncated_relations or dangling_relations),
            "output_limit_reached": bool(
                (entity_limit is not None and len(valid_entities) >= entity_limit)
                or (relation_limit is not None and len(non_dangling_relations) >= relation_limit)
                or (record_limit is not None and len(entities) + len(relations) >= record_limit)
            ),
        }
    )
    metadata["dropped_entities"] = int(metadata.get("dropped_entities") or 0) + truncated_entities
    metadata["dropped_relations"] = (
        int(metadata.get("dropped_relations") or 0) + truncated_relations + dangling_relations
    )
    return {"entities": entities, "relations": relations, "metadata": metadata}


def _prepare_llm_candidates_unbounded(
    raw: dict[str, Any],
    *,
    source_text: str,
    known_entities: list[dict[str, Any]],
    stage: str,
    endpoint_aliases: dict[str, dict[str, Any]] | None = None,
    allowed_relation_claims: set[tuple[str, str, str]] | None = None,
    min_relation_confidence: float = 0.0,
) -> dict[str, Any]:
    """将 LLM JSON 收敛为可由原文重建、符合本体方向的候选。"""
    entity_by_ref: dict[str, dict[str, Any]] = {}
    for entity in known_entities:
        for ref in _entity_refs(entity):
            entity_by_ref[ref] = entity
    for ref, entity in (endpoint_aliases or {}).items():
        if isinstance(entity, dict) and str(ref).strip():
            entity_by_ref[str(ref).strip()] = entity

    entities = []
    dropped_entities = 0
    quality_rejection_counts: dict[str, int] = {}
    for index, raw_entity in enumerate(raw.get("entities") or []):
        entity = _align_llm_entity(raw_entity, source_text, f"{stage}-e{index + 1}")
        if entity is None:
            dropped_entities += 1
            continue
        rejection_reason = clear_non_ontology_entity_reason(entity.get("text"))
        if rejection_reason:
            dropped_entities += 1
            quality_rejection_counts[rejection_reason] = quality_rejection_counts.get(rejection_reason, 0) + 1
            continue
        entity["model_sources"] = [f"lightrag_llm_{stage}"]
        entities.append(entity)
        for ref in _entity_refs(entity):
            entity_by_ref[ref] = entity

    relations = []
    dropped_relations = 0
    relation_rejection_counts: dict[str, int] = {}
    for raw_relation in raw.get("relations") or []:
        if not isinstance(raw_relation, dict):
            dropped_relations += 1
            relation_rejection_counts["invalid_record"] = relation_rejection_counts.get("invalid_record", 0) + 1
            continue
        raw_source_ref = _endpoint_ref(raw_relation.get("source"))
        raw_target_ref = _endpoint_ref(raw_relation.get("target"))
        relation_type = str(raw_relation.get("label") or "").strip().upper()
        if (
            allowed_relation_claims is not None
            and (
                raw_source_ref,
                relation_type,
                raw_target_ref,
            )
            not in allowed_relation_claims
        ):
            dropped_relations += 1
            relation_rejection_counts["outside_closed_relation_candidates"] = (
                relation_rejection_counts.get("outside_closed_relation_candidates", 0) + 1
            )
            continue
        source = _resolve_endpoint(raw_relation.get("source"), entity_by_ref)
        target = _resolve_endpoint(raw_relation.get("target"), entity_by_ref)
        ontology_relation = DEFENSE_ONTOLOGY_V1.relation_type_by_code.get(relation_type)
        if (
            source is None
            or target is None
            or ontology_relation is None
            or ontology_relation.hypothesis_only
            or not validate_relation_types(source["label"], relation_type, target["label"])
        ):
            dropped_relations += 1
            relation_rejection_counts["invalid_endpoint_or_ontology"] = (
                relation_rejection_counts.get("invalid_endpoint_or_ontology", 0) + 1
            )
            continue
        evidence_spans = _valid_evidence_spans(raw_relation.get("evidence_spans"), source_text)
        if not evidence_spans:
            dropped_relations += 1
            relation_rejection_counts["missing_relation_evidence"] = (
                relation_rejection_counts.get("missing_relation_evidence", 0) + 1
            )
            continue
        if not _evidence_spans_cover_endpoint(evidence_spans, source) or not _evidence_spans_cover_endpoint(
            evidence_spans,
            target,
        ):
            dropped_relations += 1
            relation_rejection_counts["evidence_does_not_cover_endpoints"] = (
                relation_rejection_counts.get("evidence_does_not_cover_endpoints", 0) + 1
            )
            continue
        confidence = _safe_confidence(raw_relation.get("confidence"))
        if confidence < min_relation_confidence:
            dropped_relations += 1
            relation_rejection_counts["below_relation_confidence"] = (
                relation_rejection_counts.get("below_relation_confidence", 0) + 1
            )
            continue
        claim_level = str(raw_relation.get("claim_level") or "Fact").strip().title()
        if claim_level not in {"Fact", "Inference"}:
            claim_level = "Inference"
        relation_text = str(raw_relation.get("text") or f"{source['text']} → {relation_type} → {target['text']}")[:1000]
        relations.append(
            {
                **raw_relation,
                "source": source,
                "target": target,
                "label": relation_type,
                "text": relation_text,
                "claim_level": claim_level,
                "confidence": confidence,
                "evidence_quote": "",
                "evidence_spans": evidence_spans,
                "expert_review_required": True,
                "review_status": "pending",
                "model_sources": [f"lightrag_llm_{stage}"],
            }
        )

    proposals = _valid_repair_proposals(raw.get("ocr_repair_proposals"), source_text)
    return {
        "entities": entities,
        "relations": relations,
        "metadata": {
            "extractor_type": "lightrag_llm_enhancement",
            "stage": stage,
            "dropped_entities": dropped_entities,
            "dropped_relations": dropped_relations,
            "quality_rejection_counts": dict(sorted(quality_rejection_counts.items())),
            "relation_rejection_counts": dict(sorted(relation_rejection_counts.items())),
            "ocr_repair_proposals": proposals,
        },
    }


def merge_enhancement_result(base: dict[str, Any], enhancement: dict[str, Any]) -> dict[str, Any]:
    """按类型、原文 Span 和关系方向幂等合并增强候选。"""
    entities: dict[tuple[str, int | None, int | None, str], dict[str, Any]] = {}
    refs: dict[str, dict[str, Any]] = {}
    for source_name, result in (("existing_pipeline", base), ("lightrag_llm", enhancement)):
        for raw_entity in result.get("entities") or []:
            entity = deepcopy(raw_entity)
            key = _entity_key(entity)
            existing = entities.get(key)
            sources = list(entity.get("model_sources") or [source_name])
            if existing is None:
                entity["model_sources"] = list(dict.fromkeys(sources))
                entities[key] = entity
                existing = entity
            else:
                existing["model_sources"] = list(dict.fromkeys([*(existing.get("model_sources") or []), *sources]))
                existing["confidence"] = max(
                    float(existing.get("confidence") or 0.0),
                    float(entity.get("confidence") or 0.0),
                )
                existing["attributes"] = _merge_entity_attributes(
                    existing.get("attributes"),
                    entity.get("attributes"),
                )
                if any(entity.get(field) for field in ("canonical_name", "aliases", "naming_rationale")):
                    existing.update(
                        resolve_entity_naming(
                            existing["text"],
                            canonical_name=entity.get("canonical_name") or existing.get("canonical_name"),
                            aliases=[*(existing.get("aliases") or []), *(entity.get("aliases") or [])],
                            naming_rationale=entity.get("naming_rationale") or existing.get("naming_rationale"),
                        )
                    )
            for ref in _entity_refs(raw_entity):
                refs[ref] = existing

    relations: dict[tuple[str, tuple, tuple], dict[str, Any]] = {}
    relation_merge_rejections: dict[str, int] = {}
    for source_name, result in (("existing_pipeline", base), ("lightrag_llm", enhancement)):
        for raw_relation in result.get("relations") or []:
            relation = deepcopy(raw_relation)
            source = _resolve_merged_endpoint(relation.get("source"), entities, refs)
            target = _resolve_merged_endpoint(relation.get("target"), entities, refs)
            if source is None or target is None:
                continue
            review_status = str(relation.get("review_status") or "pending").lower()
            if review_status not in {"accepted", "rejected"}:
                if _entity_key(source) == _entity_key(target):
                    relation_merge_rejections["self_loop_after_entity_merge"] = (
                        relation_merge_rejections.get("self_loop_after_entity_merge", 0) + 1
                    )
                    continue
                if not validate_relation_types(
                    str(source.get("label") or ""),
                    str(relation.get("label") or ""),
                    str(target.get("label") or ""),
                ):
                    relation_merge_rejections["invalid_ontology_after_entity_merge"] = (
                        relation_merge_rejections.get("invalid_ontology_after_entity_merge", 0) + 1
                    )
                    continue
            key = (str(relation.get("label") or ""), _entity_key(source), _entity_key(target))
            sources = list(relation.get("model_sources") or [source_name])
            existing = relations.get(key)
            if existing is None:
                relation.update(
                    {
                        "source": source,
                        "target": target,
                        "model_sources": list(dict.fromkeys(sources)),
                    }
                )
                relations[key] = relation
                continue
            existing["model_sources"] = list(dict.fromkeys([*(existing.get("model_sources") or []), *sources]))
            if str(existing.get("review_status") or "").lower() in {"accepted", "rejected"}:
                # 已完成人审的关系只记录模型来源，不允许未审核补抽改写其证据或结论。
                continue
            existing["confidence"] = max(
                float(existing.get("confidence") or 0.0),
                float(relation.get("confidence") or 0.0),
            )
            existing["evidence_spans"] = _merge_evidence_spans(
                existing.get("evidence_spans"),
                relation.get("evidence_spans"),
            )
            existing["applicable_conditions"] = _merge_string_values(
                existing.get("applicable_conditions"),
                relation.get("applicable_conditions"),
                max_items=16,
                max_chars=500,
            )
            if relation.get("claim_level") == "Fact":
                existing["claim_level"] = "Fact"
            # 待审候选只允许强化审核要求。
            existing["expert_review_required"] = bool(
                existing.get("expert_review_required") or relation.get("expert_review_required")
            )

    metadata = dict(base.get("metadata") or {})
    metadata.setdefault("enhancement_stages", []).append(dict(enhancement.get("metadata") or {}))
    if relation_merge_rejections:
        existing_rejections = dict(metadata.get("relation_merge_rejection_counts") or {})
        for reason, count in relation_merge_rejections.items():
            existing_rejections[reason] = int(existing_rejections.get(reason) or 0) + count
        metadata["relation_merge_rejection_counts"] = dict(sorted(existing_rejections.items()))
    return {
        "entities": list(entities.values()),
        "relations": list(relations.values()),
        "metadata": metadata,
    }


def _merge_entity_attributes(*groups: Any) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, list):
            continue
        for attribute in group:
            if not isinstance(attribute, dict):
                continue
            label = str(attribute.get("label") or "")[:128]
            text = str(attribute.get("text") or "")[:512]
            if not label and not text:
                continue
            merged.setdefault((label, text), deepcopy(attribute))
            if len(merged) >= 64:
                return list(merged.values())
    return list(merged.values())


def _merge_evidence_spans(*groups: Any) -> list[dict[str, int]]:
    merged: dict[tuple[int, int], dict[str, int]] = {}
    for group in groups:
        if not isinstance(group, list):
            continue
        for span in group:
            if not isinstance(span, dict):
                continue
            start, end = span.get("start"), span.get("end")
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
            ):
                continue
            merged[(start, end)] = {"start": start, "end": end}
    return [merged[key] for key in sorted(merged)]


def _merge_string_values(*groups: Any, max_items: int, max_chars: int) -> list[str]:
    merged: dict[str, None] = {}
    for group in groups:
        if not isinstance(group, list):
            continue
        for value in group:
            normalized = str(value or "").strip()[:max_chars]
            if normalized:
                merged.setdefault(normalized, None)
            if len(merged) >= max_items:
                return list(merged)
    return list(merged)


def _entity_priority(entity: dict[str, Any], original_index: int) -> tuple[Any, ...]:
    """优先高置信度、短而边界明确的实体，保证跨运行稳定。"""
    text = str(entity.get("text") or "")
    return (
        -_safe_confidence(entity.get("confidence")),
        len(text),
        int(entity.get("start") or 0),
        int(entity.get("end") or 0),
        str(entity.get("label") or ""),
        text,
        str(entity.get("id") or ""),
        original_index,
    )


def _relation_priority(relation: dict[str, Any], original_index: int) -> tuple[Any, ...]:
    """优先原文事实、高置信度和较紧凑的证据范围。"""
    spans = relation.get("evidence_spans") or []
    evidence_width = sum(int(span["end"]) - int(span["start"]) for span in spans)
    source = relation.get("source") or {}
    target = relation.get("target") or {}
    source_start = int(source.get("start") or 0) if isinstance(source, dict) else 0
    target_start = int(target.get("start") or 0) if isinstance(target, dict) else 0
    source_ref = _endpoint_ref(source)
    target_ref = _endpoint_ref(target)
    return (
        0 if relation.get("claim_level") == "Fact" else 1,
        -_safe_confidence(relation.get("confidence")),
        evidence_width,
        str(relation.get("label") or ""),
        source_start,
        target_start,
        source_ref,
        target_ref,
        original_index,
    )


def _safe_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return confidence if math.isfinite(confidence) else 0.0


def _optional_positive_limit(value: int | None, field: str) -> int | None:
    if value is None:
        return None
    return _bounded_int_option(value, field, minimum=1, maximum=MAX_LLM_CANDIDATE_RECORDS)


def _bounded_int_option(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field} 必须是 {minimum} 到 {maximum} 之间的整数")
    return value


def _estimate_prompt_tokens(prompt: str) -> int:
    """使用与现有分块器一致的词法计数，并对 CJK 和 JSON 字节做保守补偿。"""
    if not prompt:
        return 0
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", prompt))
    non_cjk = re.sub(r"[\u3400-\u9fff]", "", prompt)
    byte_estimate = math.ceil(len(non_cjk.encode("utf-8")) / 4)
    raw_estimate = max(count_tokens(prompt), cjk_count * 2 + byte_estimate)
    # Chat template 和不同中文 tokenizer 会增加少量协议 token；保留 10% 安全余量。
    return math.ceil(raw_estimate * 1.1)


def _enforce_prompt_budget(prompt: str, *, stage: str, max_chars: int, max_tokens: int) -> int:
    estimated_tokens = _estimate_prompt_tokens(prompt)
    if len(prompt) > max_chars or estimated_tokens > max_tokens:
        raise EnhancementPromptBudgetExceededError(
            stage=stage,
            actual_chars=len(prompt),
            limit_chars=max_chars,
            actual_tokens=estimated_tokens,
            limit_tokens=max_tokens,
        )
    return estimated_tokens


def _candidate_budget_metadata(result: dict[str, Any]) -> dict[str, Any]:
    metadata = result.get("metadata") or {}
    keys = (
        "raw_entity_count",
        "raw_relation_count",
        "valid_entity_count",
        "valid_relation_count",
        "kept_entity_count",
        "kept_relation_count",
        "truncated_entities",
        "truncated_relations",
        "relations_dropped_with_truncated_endpoint",
        "max_entities",
        "max_relations",
        "max_records",
        "deterministic_truncation_applied",
        "output_limit_reached",
        "quality_rejection_counts",
        "relation_rejection_counts",
    )
    return {key: metadata.get(key) for key in keys}


def _evidence_spans_cover_endpoint(
    evidence_spans: list[dict[str, int]],
    endpoint: dict[str, Any],
) -> bool:
    """关系证据必须覆盖端点原文 Span，禁止无关合法 Span 冒充支撑证据。"""
    start, end = endpoint.get("start"), endpoint.get("end")
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or end <= start
    ):
        return False
    return any(span["start"] <= start and span["end"] >= end for span in evidence_spans)


def _align_llm_entity(raw: Any, source_text: str, generated_id: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    label = canonical_entity_type(str(raw.get("label") or ""))
    if not text or label not in DEFENSE_ONTOLOGY_V1.entity_type_by_code:
        return None
    start, end = raw.get("start"), raw.get("end")
    if not (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and 0 <= start < end <= len(source_text)
        and source_text[start:end] == text
    ):
        occurrences = [match.start() for match in re.finditer(re.escape(text), source_text)]
        if len(occurrences) != 1:
            return None
        start = occurrences[0]
        end = start + len(text)
    if detect_ocr_damage(text):
        return None
    try:
        confidence = max(0.0, min(float(raw.get("confidence", 0.5)), 1.0))
    except (TypeError, ValueError, OverflowError):
        confidence = 0.5
    naming = resolve_entity_naming(
        text,
        canonical_name=raw.get("canonical_name"),
        aliases=raw.get("aliases"),
        naming_rationale=raw.get("naming_rationale"),
    )
    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), list) else []
    research_thread = str(raw.get("research_thread") or "").strip().lower()
    if research_thread in RESEARCH_THREAD_TYPES and not any(
        isinstance(item, dict) and str(item.get("label") or "").strip().casefold() == "researchthread"
        for item in attributes
    ):
        attributes = [*attributes, {"label": "ResearchThread", "text": research_thread}]
    return {
        "id": str(raw.get("id") or generated_id),
        "text": text,
        "label": label,
        "start": start,
        "end": end,
        "confidence": confidence,
        "attributes": attributes,
        **naming,
        "model_sources": ["lightrag_llm"],
    }


def _valid_evidence_spans(value: Any, source_text: str) -> list[dict[str, int]]:
    if not isinstance(value, list):
        return []
    spans = []
    for item in value:
        if not isinstance(item, dict):
            return []
        start, end = item.get("start"), item.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(source_text)
        ):
            return []
        spans.append({"start": start, "end": end})
    return spans


def _valid_repair_proposals(value: Any, source_text: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    proposals = []
    for item in value:
        if not isinstance(item, dict):
            continue
        start, end = item.get("original_start"), item.get("original_end")
        original_text = str(item.get("original_text") or "")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(source_text)
            or source_text[start:end] != original_text
        ):
            continue
        try:
            confidence = max(0.0, min(float(item.get("confidence", 0.0)), 1.0))
        except (TypeError, ValueError, OverflowError):
            confidence = 0.0
        proposals.append(
            {
                "original_start": start,
                "original_end": end,
                "original_text": original_text,
                "suggested_text": str(item.get("suggested_text") or "")[:500],
                "confidence": confidence,
                "reason": str(item.get("reason") or "")[:1000],
                "applied": False,
            }
        )
    return proposals


def _prompt_candidates(
    result: dict[str, Any],
    *,
    max_entities: int = DEFAULT_MAX_PROMPT_ENTITIES,
    max_relations: int = DEFAULT_MAX_PROMPT_RELATIONS,
) -> str:
    """只将补抽判断必需字段送入 Prompt，避免内部 metadata 和大字段挤占上下文。"""
    payload, _endpoint_aliases = _prompt_candidates_with_endpoint_aliases(
        result,
        max_entities=max_entities,
        max_relations=max_relations,
    )
    return payload


def _prompt_candidates_with_endpoint_aliases(
    result: dict[str, Any],
    *,
    max_entities: int = DEFAULT_MAX_PROMPT_ENTITIES,
    max_relations: int = DEFAULT_MAX_PROMPT_RELATIONS,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """为 Prompt 中已有实体分配唯一局部引用，并保留回映射。"""
    entity_rows = [
        (index, entity) for index, entity in enumerate(result.get("entities") or []) if isinstance(entity, dict)
    ]
    entity_rows.sort(key=lambda row: _entity_priority(row[1], row[0]))
    selected_entities = [entity for _, entity in entity_rows[:max_entities]]
    endpoint_aliases = {f"candidate-e{index}": entity for index, entity in enumerate(selected_entities, start=1)}
    relation_rows = [
        (index, relation) for index, relation in enumerate(result.get("relations") or []) if isinstance(relation, dict)
    ]
    relation_rows.sort(key=lambda row: _relation_priority(row[1], row[0]))
    payload = {
        "entities": [{**_compact_prompt_entity(entity), "id": alias} for alias, entity in endpoint_aliases.items()],
        "relations": [_compact_prompt_relation(relation) for _, relation in relation_rows[:max_relations]],
        "input_counts": {
            "entities": len(entity_rows),
            "relations": len(relation_rows),
            "entities_in_prompt": min(len(entity_rows), max_entities),
            "relations_in_prompt": min(len(relation_rows), max_relations),
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str), endpoint_aliases


def _compact_prompt_entity(entity: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "id": str(entity.get("id") or "")[:256],
        "text": str(entity.get("text") or "")[:256],
        "label": str(entity.get("label") or "")[:64],
        "start": entity.get("start"),
        "end": entity.get("end"),
        "confidence": _safe_confidence(entity.get("confidence")),
    }
    attributes = []
    for attribute in entity.get("attributes") or []:
        if not isinstance(attribute, dict) or len(attributes) >= 4:
            continue
        attributes.append(
            {
                "label": str(attribute.get("label") or "")[:64],
                "text": str(attribute.get("text") or "")[:128],
            }
        )
    if attributes:
        compact["attributes"] = attributes
    naming = resolve_entity_naming(
        compact["text"],
        canonical_name=entity.get("canonical_name"),
        aliases=entity.get("aliases"),
        naming_rationale=entity.get("naming_rationale"),
    )
    compact.update(
        {
            "canonical_name": naming["canonical_name"],
            "raw_name": naming["raw_name"],
            "aliases": naming["aliases"],
        }
    )
    if naming["naming_rationale"]:
        compact["naming_rationale"] = naming["naming_rationale"]
    return compact


def _compact_prompt_relation(relation: dict[str, Any]) -> dict[str, Any]:
    evidence_spans = []
    for span in relation.get("evidence_spans") or []:
        if isinstance(span, dict) and len(evidence_spans) < 8:
            evidence_spans.append({"start": span.get("start"), "end": span.get("end")})
    return {
        "source": _compact_prompt_endpoint(relation.get("source")),
        "target": _compact_prompt_endpoint(relation.get("target")),
        "label": str(relation.get("label") or "")[:128],
        "claim_level": str(relation.get("claim_level") or "")[:32],
        "confidence": _safe_confidence(relation.get("confidence")),
        "evidence_spans": evidence_spans,
    }


def _compact_prompt_endpoint(endpoint: Any) -> str | dict[str, Any]:
    if not isinstance(endpoint, dict):
        return str(endpoint or "")[:256]
    return {
        "id": str(endpoint.get("id") or "")[:256],
        "text": str(endpoint.get("text") or "")[:256],
        "label": str(endpoint.get("label") or "")[:64],
        "start": endpoint.get("start"),
        "end": endpoint.get("end"),
    }


def _prompt_context(metadata: dict[str, Any] | None, *, max_chars: int) -> str:
    """按固定字符预算组装标题和相邻前文，不改变当前 Block 的 Span 坐标。"""
    payload = metadata or {}
    heading = " / ".join(str(item).strip() for item in payload.get("heading_path") or [] if str(item).strip())
    sections = [f"标题层级：{heading[:500]}"] if heading else []
    remaining = max_chars
    for chunk in reversed(payload.get("context_chunks") or []):
        content = " ".join(str(chunk.get("content") or "").split())
        if not content or remaining <= 0:
            continue
        excerpt = content[-remaining:]
        sections.append(f"前文 Chunk {chunk.get('chunk_index', '?')}：{excerpt}")
        remaining -= len(excerpt)
    return "\n".join(sections) or "无"


def _prompt_ocr_damage(spans: list[OCRDamageSpan], *, max_spans: int = 32) -> str:
    """只向模型提供平台已检测的封闭损伤 Span，避免自由改写原文。"""
    payload = [
        {
            "original_start": item.start,
            "original_end": item.end,
            "original_text": item.text,
            "reason": item.reason,
        }
        for item in spans[:max_spans]
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _repair_rejection_reason_counts(rejected: tuple[dict[str, Any], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in rejected:
        reason = str(item.get("rejection_reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _entity_key(entity: dict[str, Any]) -> tuple[str, int | None, int | None, str]:
    return (
        canonical_entity_type(str(entity.get("label") or "")),
        entity.get("start") if isinstance(entity.get("start"), int) else None,
        entity.get("end") if isinstance(entity.get("end"), int) else None,
        str(entity.get("text") or ""),
    )


def _entity_refs(entity: dict[str, Any]) -> list[str]:
    return [value for value in (str(entity.get("id") or "").strip(), str(entity.get("text") or "").strip()) if value]


def _endpoint_ref(endpoint: Any) -> str:
    if isinstance(endpoint, dict):
        return str(endpoint.get("id") or endpoint.get("text") or "").strip()
    return str(endpoint or "").strip()


def _resolve_endpoint(endpoint: Any, refs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if isinstance(endpoint, dict):
        for ref in _entity_refs(endpoint):
            if ref in refs:
                return refs[ref]
        return endpoint if endpoint.get("text") and endpoint.get("label") else None
    return refs.get(str(endpoint or "").strip())


def _resolve_merged_endpoint(
    endpoint: Any,
    entities: dict[tuple[str, int | None, int | None, str], dict[str, Any]],
    refs: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """嵌套端点优先按类型和 Span 精确绑定，避免分窗局部 ID 冲突。"""
    if isinstance(endpoint, dict):
        exact = entities.get(_entity_key(endpoint))
        if exact is not None:
            return exact
    return _resolve_endpoint(endpoint, refs)


def _merge_repair_proposals(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[int, int, str], dict[str, Any]] = {}
    for group in groups:
        for proposal in group:
            key = (
                int(proposal["original_start"]),
                int(proposal["original_end"]),
                str(proposal["suggested_text"]),
            )
            merged[key] = proposal
    return list(merged.values())
