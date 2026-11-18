"""用项目 LLM 识别值得重点复抽的高新质军事技术文档。"""

from __future__ import annotations

import json
import math
from typing import Any

from platform_core.knowledge.graphs.extractors.llm import LLMGraphExtractor
from platform_core.knowledge.graphs.lightrag_text_quality import reference_section_metrics

DOCUMENT_VALUE_ROUTING_VERSION = "defense-lightrag-document-value-routing-v1"
_MILITARY_RELEVANCE = frozenset({"direct", "dual_use", "general", "uncertain"})
_NOVELTY_LEVELS = frozenset({"breakthrough", "emerging", "incremental", "unknown"})
_PRIORITY_LEVELS = frozenset({"high", "normal", "low"})
_VALUE_DIMENSIONS = frozenset(
    {
        "科学原理突破",
        "关键技术跃迁",
        "装备能力增益",
        "复杂环境适应",
        "体系协同",
        "自主智能",
        "材料与制造",
        "探测感知",
        "通信与对抗",
        "跨域迁移",
    }
)

_PROMPT = """你是军事武器装备技术原理知识工程的文档价值分流器。
请判断当前研究资料是否属于值得增加实体、关系和跨段复抽预算的“高新质军事技术”文档。

判据：
1. 必须以当前文档原文为依据，不得用外部常识推断列装、实战效果或成熟度。
2. direct 表示明确面向军事、武器装备、作战任务或能力；dual_use 表示通用前沿技术具有原文明示的军事迁移路径；
   general 表示一般研究；uncertain 表示证据不足。
3. breakthrough/emerging 需要原文出现新机理、新架构、新材料、新算法、显著指标改进、复杂环境适应或跨域组合证据；
   仅有“先进、创新、首次”等宣传词不足以成立。
4. priority=high 仅用于 direct/dual_use 且 novelty 为 breakthrough/emerging 的文档。
5. evidence 只能引用下方 Block，使用 Python 半开字符 Span；不得编写 evidence_quote。
6. dimensions 只能取允许值；没有充分证据时返回 normal/uncertain/unknown。
7. 本结果只决定复抽优先级，不是事实准入、人工 Gold 或创新结论。

仅返回 JSON：
{{
  "military_relevance":"direct|dual_use|general|uncertain",
  "novelty":"breakthrough|emerging|incremental|unknown",
  "priority":"high|normal|low",
  "confidence":0.0,
  "dimensions":["允许的价值维度"],
  "reason":"基于原文的简短理由",
  "evidence":[{{"block_id":"b1","start":0,"end":10}}]
}}

允许的价值维度：
{dimensions}

规则分流摘要（只作参考，不能替代原文证据）：
{triage}

文档标题：{title}

原文 Block：
{blocks}
"""


class LightRAGDocumentValueRouter:
    """对规则初筛后的文档执行一次有证据约束的价值判别。"""

    def __init__(self, options: dict[str, Any] | None = None, *, llm: LLMGraphExtractor | None = None) -> None:
        self.options = dict(options or {})
        self.model_spec = str(self.options.get("model_spec") or "").strip()
        if not self.model_spec:
            raise ValueError("文档价值分流需要 model_spec")
        self.max_chars = _bounded_integer(self.options.get("max_chars", 12_000), "max_chars", 1000, 100_000)
        self.min_confidence = _probability(self.options.get("min_confidence", 0.8), "min_confidence")
        self.llm = llm or LLMGraphExtractor(
            {
                "model_spec": self.model_spec,
                "model_params": {
                    "temperature": 0,
                    "max_tokens": _bounded_integer(
                        self.options.get("max_output_tokens", 1200),
                        "max_output_tokens",
                        256,
                        4096,
                    ),
                    "max_retries": 0,
                },
                "timeout_seconds": float(self.options.get("timeout_seconds") or 120.0),
                "concurrency_count": 1,
                "enable_thinking": self.options.get("enable_thinking", False),
                "max_truncation_retries": self.options.get("max_truncation_retries", 0),
                "enable_hypothesis_extraction": False,
                "max_hypotheses_per_chunk": 0,
            }
        )

    async def assess(self, document: dict[str, Any], triage: dict[str, Any]) -> dict[str, Any]:
        """返回可审计优先级；非法枚举或不可回切证据会降为普通处理。"""

        selected_blocks = _select_blocks(document.get("blocks") or [], self.max_chars)
        block_by_id = {str(item["block_id"]): item for item in selected_blocks}
        payload = await self.llm.complete_json(
            _PROMPT.format(
                dimensions="、".join(sorted(_VALUE_DIMENSIONS)),
                triage=json.dumps(_triage_summary(triage), ensure_ascii=False, separators=(",", ":")),
                title=str(document.get("title") or "")[:500],
                blocks=json.dumps(selected_blocks, ensure_ascii=False, separators=(",", ":")),
            ),
            required_keys=("military_relevance", "novelty", "priority", "confidence", "evidence"),
        )
        relevance = str(payload.get("military_relevance") or "").strip()
        novelty = str(payload.get("novelty") or "").strip()
        priority = str(payload.get("priority") or "").strip()
        confidence = _runtime_probability(payload.get("confidence"))
        if relevance not in _MILITARY_RELEVANCE or novelty not in _NOVELTY_LEVELS or priority not in _PRIORITY_LEVELS:
            raise ValueError("文档价值分流返回了非法枚举")
        dimensions = [
            value
            for value in dict.fromkeys(str(item).strip() for item in payload.get("dimensions") or [])
            if value in _VALUE_DIMENSIONS
        ]
        evidence, rejected_evidence_count = _validated_evidence(payload.get("evidence"), block_by_id)
        focused = (
            priority == "high"
            and relevance in {"direct", "dual_use"}
            and novelty in {"breakthrough", "emerging"}
            and confidence >= self.min_confidence
            and bool(dimensions)
            and bool(evidence)
        )
        return {
            "version": DOCUMENT_VALUE_ROUTING_VERSION,
            "status": "completed",
            "model_spec": self.model_spec,
            "military_relevance": relevance,
            "novelty": novelty,
            "priority": priority,
            "confidence": confidence,
            "dimensions": dimensions,
            "reason": str(payload.get("reason") or "")[:1000],
            "evidence": evidence,
            "rejected_evidence_count": rejected_evidence_count,
            "focused_reextraction_recommended": focused,
            "expert_review_required": True,
        }

    async def aclose(self) -> None:
        await self.llm.aclose()


def _select_blocks(blocks: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    """分层采样摘要、方法、结果与结论，避免仅凭标题或引言评估技术价值。"""

    candidates = []
    total_blocks = len(blocks)
    for index, raw in enumerate(blocks):
        text = str(raw.get("text") or "")
        block_id = str(raw.get("block_id") or "")
        if not text or not block_id or reference_section_metrics(text)["is_reference_section"]:
            continue
        heading = " ".join(str(item) for item in raw.get("heading_path") or [])
        candidates.append((_block_priority(heading, index, total_blocks), index, raw, text))

    selected = []
    remaining = max_chars
    per_block_limit = max(1000, min(3000, max_chars // 4))
    for _, index, raw, text in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if remaining <= 0:
            break
        excerpt = text[: min(remaining, per_block_limit)]
        selected.append(
            {
                "block_id": str(raw.get("block_id") or ""),
                "page": raw.get("page"),
                "heading_path": list(raw.get("heading_path") or [])[:8],
                "text": excerpt,
                "document_order": index,
            }
        )
        remaining -= len(excerpt)
    return sorted(selected, key=lambda item: item["document_order"])


def _block_priority(heading: str, index: int, total_blocks: int) -> int:
    normalized = heading.casefold()
    section_scores = (
        (("摘要", "abstract"), 100),
        (("结论", "展望", "conclusion", "outlook"), 95),
        (("结果", "讨论", "result", "discussion"), 90),
        (("原理", "机理", "方法", "架构", "模型", "method", "architecture"), 85),
        (("实验", "验证", "experiment", "evaluation"), 80),
        (("引言", "绪论", "introduction"), 60),
    )
    score = next((value for markers, value in section_scores if any(marker in normalized for marker in markers)), 20)
    if index < 3:
        score += 20 - index
    if total_blocks and index >= max(0, total_blocks - 4):
        score += 10
    return score


def _validated_evidence(value: Any, block_by_id: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    accepted = []
    rejected = 0
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        block = block_by_id.get(str(raw.get("block_id") or ""))
        start = raw.get("start")
        end = raw.get("end")
        if (
            block is None
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or end > len(block["text"])
        ):
            rejected += 1
            continue
        accepted.append(
            {
                "block_id": str(block["block_id"]),
                "page": block.get("page"),
                "start": start,
                "end": end,
                "text": block["text"][start:end],
            }
        )
    return accepted[:12], rejected + max(0, len(accepted) - 12)


def _triage_summary(triage: dict[str, Any]) -> dict[str, Any]:
    signals = dict(triage.get("signals") or {})
    return {
        "document_kind": triage.get("document_kind"),
        "triage_level": triage.get("triage_level"),
        "military_value_code": triage.get("military_value_code"),
        "military_markers": list(signals.get("military_markers") or [])[:20],
        "potential_military_markers": list(signals.get("potential_military_markers") or [])[:20],
        "transfer_markers": list(signals.get("transfer_markers") or [])[:20],
    }


def _bounded_integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"文档价值分流 {field} 必须是 {minimum} 到 {maximum} 之间的整数")
    return value


def _probability(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"文档价值分流 {field} 必须是 0 到 1 之间的数字")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"文档价值分流 {field} 必须是 0 到 1 之间的数字") from exc
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError(f"文档价值分流 {field} 必须是 0 到 1 之间的数字")
    return number


def _runtime_probability(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return round(max(0.0, min(number, 1.0)), 6) if math.isfinite(number) else 0.0
