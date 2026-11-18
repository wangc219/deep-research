from __future__ import annotations

from typing import Any

from platform_core.knowledge.graphs.pipeline_config import lightweight_rag_only_enabled

from .base import GraphExtractor
from .ie_service import LightRAGPrimaryGraphExtractor
from .llm import LLMGraphExtractor


class GraphExtractorFactory:
    _registry: dict[str, type[GraphExtractor]] = {
        "llm": LLMGraphExtractor,
        "lightrag_primary": LightRAGPrimaryGraphExtractor,
    }

    @classmethod
    def create(cls, extractor_type: str | None, options: dict[str, Any] | None = None) -> GraphExtractor:
        normalized_type = (extractor_type or "").lower()
        if lightweight_rag_only_enabled() and normalized_type != "lightrag_primary":
            raise ValueError("生产环境仅支持轻量化 RAG 图谱抽取器")
        extractor_class = cls._registry.get(normalized_type)
        if not extractor_class:
            raise ValueError(f"不支持的图谱抽取器类型: {extractor_type}")
        extractor = extractor_class(options or {})
        extractor.validate_options()
        return extractor

    @classmethod
    def supported_types(cls) -> list[str]:
        if lightweight_rag_only_enabled():
            return ["lightrag_primary"]
        return list(cls._registry.keys())
