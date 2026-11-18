"""文档知识审计的应用编排。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from platform_core.knowledge.graphs.document_knowledge_audit import (
    build_document_knowledge,
    triage_document,
)
from platform_core.knowledge.graphs.lightrag_document_value_routing import (
    LightRAGDocumentValueRouter,
)
from platform_core.repositories.knowledge_graph_document_audit_repository import (
    KnowledgeGraphDocumentAuditRepository,
)


class KnowledgeGraphDocumentAuditService:
    """执行抽取前分流和抽取后知识卡构建。"""

    def __init__(
        self,
        repository: KnowledgeGraphDocumentAuditRepository | None = None,
        value_router_factory: Callable[..., LightRAGDocumentValueRouter] | None = None,
    ) -> None:
        self.repository = repository or KnowledgeGraphDocumentAuditRepository()
        self.value_router_factory = value_router_factory or LightRAGDocumentValueRouter

    async def triage(
        self,
        *,
        kb_id: str,
        document_ids: list[str],
        options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """生成分流记录，并按配置从热路径排除明确非研究材料。"""
        config = _normalize_runtime_options(options)
        if not config["enabled"]:
            return {"status": "skipped", "reason": "document_audit 未启用", "documents": 0, "excluded": 0}
        documents = await self.repository.load_documents(
            kb_id=kb_id,
            document_ids=document_ids,
            include_graph=False,
        )
        results = [triage_document(document) for document in documents]
        value_routing = config["value_routing"]
        if value_routing["enabled"]:
            router = self.value_router_factory(value_routing)
            semaphore = asyncio.Semaphore(value_routing["concurrency_count"])

            async def assess(document: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
                if not result.get("eligible_for_extraction") or not result.get("deep_extraction_recommended"):
                    assessment = {
                        "status": "skipped_prefilter",
                        "focused_reextraction_recommended": False,
                        "reason": "规则初筛未发现军事或前沿技术迁移信号",
                    }
                else:
                    try:
                        async with semaphore:
                            assessment = await router.assess(document, result)
                    except Exception as exc:
                        if value_routing["strict"]:
                            raise
                        assessment = {
                            "status": "degraded",
                            "focused_reextraction_recommended": False,
                            "reason": "文档价值 LLM 判别失败，保留普通抽取预算",
                            "error_type": type(exc).__name__,
                        }
                normalized = dict(result)
                signals = dict(normalized.get("signals") or {})
                signals["lightrag_value_routing"] = assessment
                normalized["signals"] = signals
                normalized["value_routing"] = assessment
                normalized["focused_reextraction_recommended"] = bool(
                    assessment.get("focused_reextraction_recommended")
                )
                return normalized

            try:
                results = list(
                    await asyncio.gather(
                        *(assess(document, result) for document, result in zip(documents, results, strict=True))
                    )
                )
            finally:
                await router.aclose()
        await self.repository.persist_triage(
            kb_id=kb_id,
            results=results,
            apply_filter=config["filter_non_research"],
        )
        excluded = sum(1 for item in results if not item["eligible_for_extraction"])
        focused = sum(1 for item in results if item.get("focused_reextraction_recommended") is True)
        value_degraded = sum(1 for item in results if (item.get("value_routing") or {}).get("status") == "degraded")
        return {
            "status": "completed",
            "reason": "",
            "documents": len(results),
            "excluded": excluded if config["filter_non_research"] else 0,
            "observed_non_research": excluded,
            "focused_reextraction_documents": focused,
            "value_routing_degraded_documents": value_degraded,
            "filter_non_research": config["filter_non_research"],
            "value_routing_enabled": value_routing["enabled"],
            "results": results,
        }

    async def build_cards(
        self,
        *,
        kb_id: str,
        document_ids: list[str],
        triage_results: list[dict[str, Any]],
        pipeline_revision: str,
        ontology_version: str,
        options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """用本轮权威知识重建研究链和知识卡。"""
        config = _normalize_runtime_options(options)
        if not config["enabled"]:
            return {"status": "skipped", "reason": "document_audit 未启用", "documents": 0, "cards": 0}
        triage_by_document = {str(item["document_id"]): item for item in triage_results}
        documents = await self.repository.load_documents(
            kb_id=kb_id,
            document_ids=document_ids,
            include_graph=True,
        )
        card_count = 0
        thread_count = 0
        for document in documents:
            triage = triage_by_document.get(str(document["document_id"]))
            if triage is None:
                triage = triage_document(document)
            bundle = build_document_knowledge(
                document,
                triage=triage,
                pipeline_revision=pipeline_revision,
                ontology_version=ontology_version,
            )
            await self.repository.persist_document_knowledge(
                document=document,
                bundle=bundle,
                pipeline_revision=pipeline_revision,
            )
            card_count += 1
            thread_count += len(bundle["threads"])
        return {
            "status": "completed",
            "reason": "",
            "documents": len(documents),
            "cards": card_count,
            "threads": thread_count,
        }

    async def list_cards(
        self,
        *,
        kb_id: str,
        governance_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出文档知识卡。"""
        return await self.repository.list_cards(
            kb_id=kb_id,
            governance_status=governance_status,
            limit=limit,
            offset=offset,
        )

    async def get_card(self, *, kb_id: str, card_id: str) -> dict[str, Any]:
        """读取带研究链和证据引用的知识卡。"""
        result = await self.repository.get_card(kb_id=kb_id, card_id=card_id)
        if result is None:
            raise LookupError("知识卡不存在")
        return result


def _normalize_runtime_options(options: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(options or {})
    value_routing = dict(config.get("value_routing") or {})
    return {
        "enabled": config.get("enabled", True) is not False,
        "filter_non_research": config.get("filter_non_research", True) is not False,
        "value_routing": {
            **value_routing,
            "enabled": value_routing.get("enabled", False) is True,
            "strict": value_routing.get("strict", False) is True,
            "concurrency_count": max(1, min(int(value_routing.get("concurrency_count") or 2), 8)),
        },
    }
