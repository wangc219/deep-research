"""项目 LLM 驱动的轻量化 LightRAG 图谱抽取器。"""

from __future__ import annotations

from typing import Any

from .base import GraphExtractionInput, GraphExtractor
from .lightrag_enhancement import LightRAGQualityEnhancer


class LightRAGPrimaryGraphExtractor(GraphExtractor):
    """只使用项目 LLM 完成 LightRAG 初抽、补抽和证据治理。"""

    extractor_type = "lightrag_primary"

    def __init__(self, options: dict[str, Any] | None = None):
        super().__init__(options)
        enhancement_options = dict(self.options.get("llm_enhancement") or {})
        self.enhancer = LightRAGQualityEnhancer(enhancement_options) if enhancement_options.get("enabled") else None

    def validate_options(self) -> None:
        if self.enhancer is None:
            raise ValueError("lightrag_primary 必须启用 llm_enhancement")
        self.enhancer.validate_options()

    async def extract(self, text: str, *, chunk_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        self.validate_options()
        result = await self.enhancer.enhance_initial(
            text,
            _empty_graph_result(self.options),
            chunk_metadata=chunk_metadata,
        )
        result = await self.enhancer.glean(text, result, chunk_metadata=chunk_metadata)
        self._apply_metadata(result)
        return result

    async def extract_batch(self, inputs: list[GraphExtractionInput]) -> list[dict[str, Any]]:
        """按配置的 Agent 并发槽批量运行纯 LightRAG 抽取。"""
        if not inputs:
            return []
        self.validate_options()
        results = await self.enhancer.enhance_initial_batch(
            inputs,
            [_empty_graph_result(self.options) for _ in inputs],
        )
        results = await self.enhancer.glean_batch(inputs, results)
        for result in results:
            self._apply_metadata(result)
        return results

    async def aclose(self) -> None:
        if self.enhancer is not None:
            await self.enhancer.aclose()

    def _apply_metadata(self, result: dict[str, Any]) -> None:
        metadata = result.setdefault("metadata", {})
        metadata.update(
            {
                "extractor_type": self.extractor_type,
                "orchestration_mode": self.extractor_type,
                "orchestration": "lightrag_primary_lightrag_gleaning",
                "lightrag_role": "direct_primary",
                "llm_enhancement_enabled": True,
                "primary_branches": ["lightrag_project_llm"],
            }
        )


def _empty_graph_result(options: dict[str, Any]) -> dict[str, Any]:
    """为纯 LightRAG 路线建立不伪造模型结果的空候选。"""
    return {
        "entities": [],
        "relations": [],
        "metadata": {
            "extractor_type": "lightrag_llm_enhancement",
            "ontology_version": options.get("ontology_version"),
            "pipeline_revision": options.get("pipeline_revision"),
        },
    }
