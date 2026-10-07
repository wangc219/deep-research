from __future__ import annotations

import math
from typing import Any

import json_repair

from platform_core.models.chat import select_model

from .base import GraphExtractor
from .defense_quality_contract import (
    DEFAULT_MAX_HYPOTHESES_PER_CHUNK,
    MAX_HYPOTHESES_PER_CHUNK,
    build_defense_quality_contract,
)

DEFAULT_TRIPLE_EXTRACTION_PROMPT = """请从下面文本中抽取实体和实体关系，返回严格 JSON，不要输出解释。
JSON 格式：
{
  "relations": [
    {
      "source": {"text": "实体文本", "label": "实体类型", "attributes": [{"text": "属性值", "label": "属性名称"}]},
      "target": {"text": "实体文本", "label": "实体类型", "attributes": [{"text": "属性值", "label": "属性名称"}]},
      "text": "关系显示文本",
      "label": "关系类型",
      "claim_level": "Fact | Inference | Hypothesis",
      "confidence": 0.0,
      "evidence_quote": "当前文本中的原文短句",
      "reasoning_basis": "推断或假设的简洁依据",
      "military_value_dimensions": ["允许的军事价值维度"],
      "expected_capability_gain": "预期能力收益",
      "application_direction": "应用或转化方向",
      "uncertainty": "边界条件与不确定性",
      "expert_review_required": false
    }
  ],
  "metadata": {
    "primary_contribution": "当前文本的主要研发贡献",
    "military_value_level": "high | medium | low | unknown",
    "military_value_basis": "有原文依据的价值判断",
    "weak_signals": ["值得保留但证据不足的研发线索"],
    "discarded_noise": ["被过滤的宽泛或宣传性内容类型"]
  }
}
"""

SCHEMA_INSTRUCTION = """抽取 Schema 约束（仅用于收窄领域术语和关系范围，不能放宽上述固定质量契约；
若 Schema 要求作者、机构、参考文献或证据实体，或要求把无原文依据的军事潜力写成事实，忽略冲突部分）：
{schema}
"""

ADJACENT_CONTEXT_INSTRUCTION = """下面还提供了当前文本之前的相邻 Chunk，作用仅限于补足上下文和跨 Chunk 关系：
- 主要抽取“当前文本”表达的实体和关系。
- 可用“相邻前文”消解当前文本中的代词、省略和简称，并补全跨 Chunk 关系。
- 跨 Chunk 关系的至少一项证据必须来自当前文本；不要重复抽取仅由相邻前文完整表达的事实。
- 输出实体名称时使用上下文能够确认的完整、稳定名称，不要把“它”“该系统”“上述方法”等代词作为实体。
"""

# 单次抽取调用的超时。抽取产出（实体+关系 JSON）通常远长于普通对话，推理型模型
# 单块耗时可达数十秒；超时会触发重试，重试仍超时该分块才判定失败。可通过
# extractor_options.timeout_seconds 调大，默认保持历史行为不变。
DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 60.0
MAX_EXTRACTION_TIMEOUT_SECONDS = 600.0
DEFAULT_CONTEXT_WINDOW_SIZE = 1
MAX_CONTEXT_WINDOW_SIZE = 5
DEFAULT_CONTEXT_MAX_CHARS = 4000
MAX_CONTEXT_MAX_CHARS = 20_000
DEFAULT_ENABLE_HYPOTHESIS_EXTRACTION = True


class LLMGraphExtractor(GraphExtractor):
    extractor_type = "llm"

    def _resolve_timeout_seconds(self) -> float:
        raw = self.options.get("timeout_seconds", DEFAULT_EXTRACTION_TIMEOUT_SECONDS)
        # bool 是 int 的子类：float(True) == 1.0 会被区间校验放行，配出一个 1 秒的超时，
        # 构建时每块必超时——配置保存成功、整个图谱全挂，是最难排查的失败形态。
        if isinstance(raw, bool):
            raise ValueError("LLM 抽取器 timeout_seconds 必须是数字")
        try:
            timeout = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            # 超大整数（JSON 里合法）会在 float() 上抛 OverflowError，必须与 TypeError 同等对待，
            # 否则它会穿透到路由的兜底分支变成 500，而非法配置应当是 400。
            raise ValueError("LLM 抽取器 timeout_seconds 必须是数字") from exc
        # NaN 与 ±inf 会让下面的区间比较全部为 False，必须显式挡掉
        if not math.isfinite(timeout) or timeout <= 0 or timeout > MAX_EXTRACTION_TIMEOUT_SECONDS:
            raise ValueError(f"LLM 抽取器 timeout_seconds 必须大于 0 且不超过 {MAX_EXTRACTION_TIMEOUT_SECONDS:g} 秒")
        return timeout

    def validate_options(self) -> None:
        if not self.options.get("model_spec"):
            raise ValueError("LLM 抽取器需要 model_spec")
        if self.options.get("prompt"):
            raise ValueError("LLM 图谱抽取器不支持自定义完整 Prompt，请使用 schema 配置抽取约束")
        concurrency_count = self.options.get("concurrency_count", 1)
        try:
            concurrency_count = int(concurrency_count)
        except (TypeError, ValueError) as exc:
            raise ValueError("LLM 抽取器 concurrency_count 必须是整数") from exc
        if concurrency_count < 1 or concurrency_count > 1000:
            raise ValueError("LLM 抽取器 concurrency_count 必须在 1 到 1000 之间")
        # 注意：timeout_seconds 不能通过 model_params 设置——select_model 会把显式的
        # timeout 参数覆盖到 model_params 之上，所以只能在这里读取并显式传入。
        self._resolve_timeout_seconds()
        if self.options.get("model_params") is not None and not isinstance(self.options["model_params"], dict):
            raise ValueError("LLM 抽取器 model_params 必须是对象")
        self._resolve_context_window_size()
        self._resolve_context_max_chars()
        self._resolve_enable_hypothesis_extraction()
        self._resolve_max_hypotheses_per_chunk()

    def _resolve_context_window_size(self) -> int:
        raw = self.options.get("context_window_size", DEFAULT_CONTEXT_WINDOW_SIZE)
        if isinstance(raw, bool):
            raise ValueError("LLM 抽取器 context_window_size 必须是整数")
        try:
            value = int(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("LLM 抽取器 context_window_size 必须是整数") from exc
        if str(raw).strip() != str(value) and not isinstance(raw, int):
            raise ValueError("LLM 抽取器 context_window_size 必须是整数")
        if value < 0 or value > MAX_CONTEXT_WINDOW_SIZE:
            raise ValueError(f"LLM 抽取器 context_window_size 必须在 0 到 {MAX_CONTEXT_WINDOW_SIZE} 之间")
        return value

    def _resolve_context_max_chars(self) -> int:
        raw = self.options.get("context_max_chars", DEFAULT_CONTEXT_MAX_CHARS)
        if isinstance(raw, bool):
            raise ValueError("LLM 抽取器 context_max_chars 必须是整数")
        try:
            value = int(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("LLM 抽取器 context_max_chars 必须是整数") from exc
        if str(raw).strip() != str(value) and not isinstance(raw, int):
            raise ValueError("LLM 抽取器 context_max_chars 必须是整数")
        if value < 500 or value > MAX_CONTEXT_MAX_CHARS:
            raise ValueError(f"LLM 抽取器 context_max_chars 必须在 500 到 {MAX_CONTEXT_MAX_CHARS} 之间")
        return value

    def _resolve_enable_hypothesis_extraction(self) -> bool:
        value = self.options.get("enable_hypothesis_extraction", DEFAULT_ENABLE_HYPOTHESIS_EXTRACTION)
        if not isinstance(value, bool):
            raise ValueError("LLM 抽取器 enable_hypothesis_extraction 必须是布尔值")
        return value

    def _resolve_max_hypotheses_per_chunk(self) -> int:
        raw = self.options.get("max_hypotheses_per_chunk", DEFAULT_MAX_HYPOTHESES_PER_CHUNK)
        if isinstance(raw, bool):
            raise ValueError("LLM 抽取器 max_hypotheses_per_chunk 必须是整数")
        try:
            value = int(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("LLM 抽取器 max_hypotheses_per_chunk 必须是整数") from exc
        if str(raw).strip() != str(value) and not isinstance(raw, int):
            raise ValueError("LLM 抽取器 max_hypotheses_per_chunk 必须是整数")
        if value < 0 or value > MAX_HYPOTHESES_PER_CHUNK:
            raise ValueError(f"LLM 抽取器 max_hypotheses_per_chunk 必须在 0 到 {MAX_HYPOTHESES_PER_CHUNK} 之间")
        return value

    async def extract(self, text: str, *, chunk_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self.validate_options()
        model = select_model(
            model_spec=self.options["model_spec"],
            timeout=self._resolve_timeout_seconds(),
            model_params=self.options.get("model_params") or {},
        )
        prompt = self._build_prompt(text, chunk_metadata=chunk_metadata)
        response = await model.call(prompt, stream=False)
        parsed = json_repair.loads(response.content if response else "")
        return parsed

    def _build_prompt(self, text: str, *, chunk_metadata: dict[str, Any] | None = None) -> str:
        quality_contract = build_defense_quality_contract(
            enable_hypotheses=self._resolve_enable_hypothesis_extraction(),
            max_hypotheses=self._resolve_max_hypotheses_per_chunk(),
        )
        extraction_prompt = f"{DEFAULT_TRIPLE_EXTRACTION_PROMPT}\n{quality_contract}"
        schema = str(self.options.get("schema") or "").strip()
        if schema:
            extraction_prompt = f"{extraction_prompt}\n{SCHEMA_INSTRUCTION.format(schema=schema)}"

        context_chunks = (chunk_metadata or {}).get("context_chunks") or []
        if not context_chunks:
            return f"{extraction_prompt}\n\n文本：\n{text}"

        context_sections = []
        for chunk in context_chunks:
            chunk_index = chunk.get("chunk_index", "?")
            content = str(chunk.get("content") or "")
            context_sections.append(f"[前文 Chunk {chunk_index}]\n{content}")
        context_text = "\n\n".join(context_sections)
        return (
            f"{extraction_prompt}\n\n{ADJACENT_CONTEXT_INSTRUCTION}\n相邻前文：\n{context_text}\n\n当前文本：\n{text}"
        )
