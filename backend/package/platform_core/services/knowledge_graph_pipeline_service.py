"""知识图谱抽取配置的应用编排。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.knowledge.graphs.pipeline_config import IE_EXTRACTOR_TYPES, normalize_pipeline_options
from platform_core.repositories.knowledge_graph_acceptance_repository import (
    KnowledgeGraphAcceptanceRepository,
)
from platform_core.services.knowledge_graph_governance_service import KnowledgeGraphGovernanceService
from platform_core.services.knowledge_graph_document_enhancement_service import (
    KnowledgeGraphDocumentEnhancementService,
)
from platform_core.services.knowledge_graph_document_audit_service import (
    KnowledgeGraphDocumentAuditService,
)
from platform_core.utils import logger


async def _default_project_chat_model_spec() -> str:
    """读取项目模型设置，避免 LightRAG 子阶段各自维护模型默认值。"""
    from platform_core.services.equipment_model_adapter import default_chat_model_spec

    return await default_chat_model_spec(None)


class KnowledgeGraphPipelineService:
    """在本体治理与可替换图谱运行时之间维护稳定用例边界。"""

    def __init__(
        self,
        graph_service: MilvusGraphService | None = None,
        governance_service: KnowledgeGraphGovernanceService | None = None,
        acceptance_repository: KnowledgeGraphAcceptanceRepository | None = None,
        document_enhancement_service: KnowledgeGraphDocumentEnhancementService | None = None,
        document_audit_service: KnowledgeGraphDocumentAuditService | None = None,
        project_model_resolver: Any | None = None,
    ):
        self.graph_service = graph_service or MilvusGraphService()
        self.governance_service = governance_service or KnowledgeGraphGovernanceService()
        self.acceptance_repository = acceptance_repository or KnowledgeGraphAcceptanceRepository()
        self.document_enhancement_service = document_enhancement_service or KnowledgeGraphDocumentEnhancementService(
            entity_aligner=self.graph_service.align_document_entity_records,
        )
        self.document_audit_service = document_audit_service or KnowledgeGraphDocumentAuditService()
        self.project_model_resolver = project_model_resolver or _default_project_chat_model_spec

    async def configure(
        self,
        *,
        kb_id: str,
        extractor_type: str,
        extractor_options: dict[str, Any] | None,
        created_by: str,
    ) -> dict[str, Any]:
        """注册默认本体并保存固定版本的抽取配置。"""
        normalized_extractor_type = str(extractor_type or "").strip().lower()
        effective_options = await self._bind_project_model_defaults(
            normalized_extractor_type,
            extractor_options,
        )
        default_ontology = await self.governance_service.ensure_default_ontology(created_by=created_by)
        ontology_definition = None
        if normalized_extractor_type in IE_EXTRACTOR_TYPES:
            requested_version = str(
                effective_options.get("ontology_version") or default_ontology.get("version") or "defense-kg-1.0"
            )
            ontology_definition = (
                default_ontology
                if requested_version == default_ontology.get("version")
                else await self.governance_service.get_ontology(requested_version)
            )
        normalized_options = normalize_pipeline_options(
            normalized_extractor_type,
            effective_options,
            ontology_definition=ontology_definition,
        )
        return await self.graph_service.configure(
            kb_id,
            extractor_type=normalized_extractor_type,
            extractor_options=normalized_options,
            created_by=created_by,
        )

    async def _bind_project_model_defaults(
        self,
        extractor_type: str,
        extractor_options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """为已启用的 LightRAG 阶段惰性绑定项目默认通用模型。"""
        options = deepcopy(extractor_options or {})
        if extractor_type != "lightrag_primary":
            return options

        sections = []
        for key in ("llm_enhancement", "entity_alignment", "retrieval_evidence_summary"):
            section = options.get(key)
            if isinstance(section, dict) and section.get("enabled"):
                sections.append(section)

        document_audit = options.get("document_audit")
        if isinstance(document_audit, dict) and document_audit.get("enabled", True):
            value_routing = document_audit.get("value_routing")
            if isinstance(value_routing, dict) and value_routing.get("enabled"):
                sections.append(value_routing)

        document = options.get("document_enhancement")
        if isinstance(document, dict) and document.get("enabled"):
            for key in (
                "entity_enhancement",
                "llm_enhancement",
                "cross_document_relation_enhancement",
            ):
                section = document.get(key)
                if isinstance(section, dict) and section.get("enabled"):
                    sections.append(section)

        missing_model_sections = [section for section in sections if not str(section.get("model_spec") or "").strip()]
        if not missing_model_sections:
            return options

        model_spec = str(await self.project_model_resolver()).strip()
        if not model_spec:
            raise ValueError("项目模型设置尚未配置 default_model，无法启用 LightRAG LLM 阶段")
        for section in missing_model_sections:
            section["model_spec"] = model_spec
        return options

    async def build_pending_chunks(
        self,
        *,
        kb_id: str,
        context: Any = None,
        failed_only: bool = False,
        started_by: str | None = None,
        max_chunks: int | None = None,
    ) -> dict[str, Any]:
        """固定模型与本体版本后执行构建，并持久化成功、失败或取消终态。"""
        config = await self.graph_service.get_build_configuration(kb_id)
        lineage = _build_lineage(config)
        run = await self.acceptance_repository.start_build_run(
            kb_id=kb_id,
            pipeline_revision=lineage["pipeline_revision"],
            ontology_version=lineage["ontology_version"],
            model_versions=lineage["model_versions"],
            rule_version=lineage["rule_version"],
            scope="failed" if failed_only else "pending",
            started_by=started_by,
            max_chunks=max_chunks,
        )
        source_stage = await self._start_stage(
            run=run,
            lineage=lineage,
            stage_code="source_snapshot",
            stage_order=10,
            input_payload={
                "kb_id": kb_id,
                "scope": "failed" if failed_only else "pending",
                "chunk_ids": run.get("chunk_ids"),
            },
        )
        await self._finish_stage(
            source_stage,
            status="completed",
            metrics={"source_document_count": len(run["document_ids"])},
            output_payload={
                "document_ids": run["document_ids"],
                "chunk_ids": run.get("chunk_ids"),
                "build_input_hash": run["input_hash"],
            },
        )
        audit_options = (config.get("extractor_options") or {}).get("document_audit") or {"enabled": False}
        triage_stage = await self._start_stage(
            run=run,
            lineage=lineage,
            stage_code="document_triage",
            stage_order=15,
            input_payload={
                "build_input_hash": run["input_hash"],
                "document_ids": run["document_ids"],
                "options": audit_options,
            },
        )
        try:
            triage = await self.document_audit_service.triage(
                kb_id=kb_id,
                document_ids=run["document_ids"],
                options=audit_options,
            )
        except Exception as exc:
            await self._finish_stage(triage_stage, status="failed", metrics={}, error=str(exc))
            await self._finish_failed_run(run["run_id"], "failed", str(exc))
            raise
        await self._finish_stage(
            triage_stage,
            status="skipped" if triage.get("status") == "skipped" else "completed",
            metrics={
                "documents": int(triage.get("documents") or 0),
                "excluded": int(triage.get("excluded") or 0),
                "observed_non_research": int(triage.get("observed_non_research") or 0),
                "focused_reextraction_documents": int(triage.get("focused_reextraction_documents") or 0),
                "value_routing_degraded_documents": int(triage.get("value_routing_degraded_documents") or 0),
            },
            output_payload={key: value for key, value in triage.items() if key != "results"},
        )
        observed_stages = await self._start_graph_stages(run=run, lineage=lineage)
        try:
            result = await self.graph_service.build_pending_chunks(
                kb_id,
                context=context,
                failed_only=failed_only,
                chunk_ids=run.get("chunk_ids"),
            )
        except asyncio.CancelledError:
            await self._finish_graph_stages(
                observed_stages,
                status="cancelled",
                result={},
                error="构建任务已取消",
            )
            await self._finish_failed_run(run["run_id"], "cancelled", "构建任务已取消")
            raise
        except Exception as exc:
            await self._finish_graph_stages(
                observed_stages,
                status="failed",
                result={},
                error=str(exc),
            )
            await self._finish_failed_run(run["run_id"], "failed", str(exc))
            raise

        await self._finish_graph_stages(observed_stages, status="completed", result=result)
        enhancement_stage = await self._start_stage(
            run=run,
            lineage=lineage,
            stage_code="document_relation_enhancement",
            stage_order=65,
            input_payload={
                "build_input_hash": run["input_hash"],
                "document_ids": run["document_ids"],
                "model_version": lineage.get("document_model_version"),
            },
        )
        try:
            priority_document_ids = {
                str(item["document_id"])
                for item in triage.get("results") or []
                if item.get("focused_reextraction_recommended") is True
            }
            enhancement = await self.document_enhancement_service.run(
                kb_id=kb_id,
                document_ids=run["document_ids"],
                options=(config.get("extractor_options") or {}).get("document_enhancement"),
                pipeline_revision=lineage["pipeline_revision"],
                ontology_version=lineage["ontology_version"],
                ontology_definition=(config.get("extractor_options") or {}).get("ontology_definition"),
                entity_alignment_options=(config.get("extractor_options") or {}).get("entity_alignment"),
                priority_document_ids=priority_document_ids,
            )
        except asyncio.CancelledError:
            await self._finish_stage(
                enhancement_stage,
                status="cancelled",
                metrics={},
                error="文档级关系增强已取消",
            )
            await self._finish_failed_run(run["run_id"], "cancelled", "文档级关系增强已取消")
            raise
        except Exception as exc:
            await self._finish_stage(
                enhancement_stage,
                status="failed",
                metrics={},
                error=str(exc),
            )
            await self._finish_failed_run(run["run_id"], "failed", str(exc))
            raise
        enhancement_status = "skipped" if enhancement.get("status") == "skipped" else "completed"
        await self._finish_stage(
            enhancement_stage,
            status=enhancement_status,
            metrics={
                "documents": int(enhancement.get("documents") or 0),
                "windows": int(enhancement.get("windows") or 0),
                "entity_windows": int(enhancement.get("entity_windows") or 0),
                "entities": int(enhancement.get("entities") or 0),
                "relations": int(enhancement.get("relations") or 0),
                "cross_document_candidate_pairs": int(enhancement.get("cross_document_candidate_pairs") or 0),
                "cross_document_relations": int(enhancement.get("cross_document_relations") or 0),
                "cross_document_source_documents": int(enhancement.get("cross_document_source_documents") or 0),
                "cross_document_scope_documents": int(enhancement.get("cross_document_scope_documents") or 0),
                "cross_document_seed_documents": int(enhancement.get("cross_document_seed_documents") or 0),
                "priority_documents": int(enhancement.get("priority_documents") or 0),
                "priority_entity_windows": int(enhancement.get("priority_entity_windows") or 0),
                "priority_relation_windows": int(enhancement.get("priority_relation_windows") or 0),
                "reason": str(enhancement.get("reason") or ""),
            },
            output_payload=enhancement,
        )
        result = {**result, "document_relation_enhancement": enhancement}
        card_stage = await self._start_stage(
            run=run,
            lineage=lineage,
            stage_code="document_knowledge_audit",
            stage_order=70,
            input_payload={
                "build_input_hash": run["input_hash"],
                "document_ids": run["document_ids"],
                "triage_rule": audit_options,
            },
        )
        try:
            document_audit = await self.document_audit_service.build_cards(
                kb_id=kb_id,
                document_ids=run["document_ids"],
                triage_results=list(triage.get("results") or []),
                pipeline_revision=lineage["pipeline_revision"],
                ontology_version=lineage["ontology_version"],
                options=audit_options,
            )
        except Exception as exc:
            await self._finish_stage(card_stage, status="failed", metrics={}, error=str(exc))
            await self._finish_failed_run(run["run_id"], "failed", str(exc))
            raise
        await self._finish_stage(
            card_stage,
            status="skipped" if document_audit.get("status") == "skipped" else "completed",
            metrics={
                "documents": int(document_audit.get("documents") or 0),
                "cards": int(document_audit.get("cards") or 0),
                "threads": int(document_audit.get("threads") or 0),
            },
            output_payload=document_audit,
        )
        triage_summary = {key: value for key, value in triage.items() if key != "results"}
        result = {
            **result,
            "document_triage": triage_summary,
            "document_knowledge_audit": document_audit,
        }
        quality_stage = await self._start_stage(
            run=run,
            lineage=lineage,
            stage_code="quality_summary",
            stage_order=80,
            input_payload=result,
        )
        await self._finish_stage(
            quality_stage,
            status="completed",
            metrics={
                "verified_facts": int(result.get("verified_facts") or 0),
                "evidence_review_required": int(result.get("evidence_review_required") or 0),
                "failed": int(result.get("failed") or 0),
            },
            output_payload=result,
        )
        completed = await self.acceptance_repository.finish_build_run(
            run_id=run["run_id"],
            status="completed",
            metrics=result,
        )
        if not completed:
            raise RuntimeError(f"图谱构建运行 {run['run_id']} 无法提交 completed 终态")
        return {**result, "build_run_id": run["run_id"], "build_input_hash": run["input_hash"]}

    async def _start_graph_stages(
        self,
        *,
        run: dict[str, Any],
        lineage: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """为图服务并发热路径登记真实执行范围内的阶段。"""
        stages = {}
        for stage_code, stage_order in (
            ("information_extraction", 20),
            ("entity_alignment", 30),
            ("authoritative_commit", 40),
            ("graph_projection", 50),
            ("vector_projection", 60),
        ):
            stages[stage_code] = await self._start_stage(
                run=run,
                lineage=lineage,
                stage_code=stage_code,
                stage_order=stage_order,
                input_payload={
                    "build_input_hash": run["input_hash"],
                    "document_ids": run["document_ids"],
                    "execution_boundary": "concurrent_graph_service",
                },
            )
        return stages

    async def _start_stage(
        self,
        *,
        run: dict[str, Any],
        lineage: dict[str, Any],
        stage_code: str,
        stage_order: int,
        input_payload: Any,
    ) -> dict[str, Any]:
        """使用统一运行谱系登记阶段。"""
        return await self.acceptance_repository.start_stage(
            run_id=run["run_id"],
            stage_code=stage_code,
            stage_order=stage_order,
            input_payload=input_payload,
            model_versions=lineage["model_versions"],
            ontology_version=lineage["ontology_version"],
            rule_version=lineage["rule_version"],
        )

    async def _finish_stage(
        self,
        stage: dict[str, Any],
        *,
        status: str,
        metrics: dict[str, Any],
        output_payload: Any | None = None,
        error: str = "",
    ) -> None:
        """提交阶段终态，拒绝静默丢失处理日志。"""
        completed = await self.acceptance_repository.finish_stage(
            stage_run_id=stage["stage_run_id"],
            status=status,
            metrics=metrics,
            output_payload=output_payload,
            error=error,
        )
        if not completed:
            raise RuntimeError(f"图谱构建阶段 {stage['stage_run_id']} 无法提交 {status} 终态")

    async def _finish_graph_stages(
        self,
        stages: dict[str, dict[str, Any]],
        *,
        status: str,
        result: dict[str, Any],
        error: str = "",
    ) -> None:
        """按并发图服务的可观测边界完成各阶段日志。"""
        metrics = _stage_metrics(result)
        for stage_code, stage in stages.items():
            try:
                await self._finish_stage(
                    stage,
                    status=status,
                    metrics=metrics[stage_code],
                    output_payload={"stage_code": stage_code, "result": result, "status": status},
                    error=error,
                )
            except Exception:
                if status == "completed":
                    raise
                logger.exception(
                    "图谱构建阶段终态持久化失败 stage_run_id={} status={}",
                    stage["stage_run_id"],
                    status,
                )

    async def _finish_failed_run(self, run_id: str, status: str, error: str) -> None:
        try:
            completed = await self.acceptance_repository.finish_build_run(
                run_id=run_id,
                status=status,
                metrics={},
                error=error,
            )
            if not completed:
                logger.error("图谱构建运行无法提交终态 run_id={} status={}", run_id, status)
        except Exception:
            logger.exception("图谱构建运行终态持久化失败 run_id={} status={}", run_id, status)


def _build_lineage(config: dict[str, Any]) -> dict[str, Any]:
    """从稳定配置契约提取不含服务地址和密钥的运行谱系。"""
    extractor_type = str(config.get("extractor_type") or "unknown")
    options = dict(config.get("extractor_options") or {})
    ontology_version = str(options.get("ontology_version") or "legacy-unversioned")
    pipeline_revision = str(options.get("pipeline_revision") or "legacy-v1")
    rule_version = str(options.get("rule_version") or "defense-quality-contract-v1")
    model_versions: dict[str, Any] = {"extractor_type": extractor_type}
    if extractor_type == "llm":
        model_versions["llm"] = str(options.get("model_spec") or "unknown")
    elif extractor_type == "lightrag_primary":
        model_versions["orchestration_mode"] = "lightrag_primary"
        llm_enhancement = dict(options.get("llm_enhancement") or {})
        model_versions["primary"] = str(llm_enhancement.get("model_spec") or "unknown")
        model_versions["lightrag_primary"] = model_versions["primary"]
        document_enhancement = dict(options.get("document_enhancement") or {})
        if document_enhancement.get("enabled"):
            document_llm = dict(document_enhancement.get("llm_enhancement") or {})
            if document_llm.get("enabled"):
                model_versions["document_llm"] = str(document_llm.get("model_spec") or "unknown")
            document_entity = dict(document_enhancement.get("entity_enhancement") or {})
            if document_entity.get("enabled"):
                model_versions["document_entity_llm"] = str(document_entity.get("model_spec") or "unknown")
            cross_document = dict(document_enhancement.get("cross_document_relation_enhancement") or {})
            if cross_document.get("enabled"):
                model_versions["cross_document_relation_llm"] = str(cross_document.get("model_spec") or "unknown")
    else:
        model_versions[extractor_type] = str(options.get("model_version") or "unknown")
    lineage = {
        "pipeline_revision": pipeline_revision,
        "ontology_version": ontology_version,
        "rule_version": rule_version,
        "model_versions": model_versions,
    }
    if extractor_type == "lightrag_primary":
        document_enhancement = dict(options.get("document_enhancement") or {})
        document_llm = dict(document_enhancement.get("llm_enhancement") or {})
        if document_enhancement.get("enabled") and document_llm.get("enabled"):
            lineage["document_model_version"] = str(document_llm.get("model_spec") or "unknown")
        else:
            lineage["document_model_version"] = None
    return lineage


def _stage_metrics(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """从图服务真实返回值派生阶段级汇总，不虚构内部计时。"""
    success = int(result.get("success") or 0)
    return {
        "information_extraction": {
            "processed_chunks": success,
            "failed_chunks": int(result.get("extraction_failed") or 0),
        },
        "entity_alignment": {
            "processed_chunks": success,
            "execution_boundary": "concurrent_graph_service",
        },
        "authoritative_commit": {
            "committed_chunks": success,
            "failed_chunks": int(result.get("write_failed") or 0),
        },
        "graph_projection": {
            "queued_chunks": success,
            "failed_chunks": int(result.get("write_failed") or 0),
            "execution_boundary": "durable_outbox",
        },
        "vector_projection": {
            "indexed_chunks": success,
            "failed_records": int(result.get("vector_failed") or 0),
        },
    }
