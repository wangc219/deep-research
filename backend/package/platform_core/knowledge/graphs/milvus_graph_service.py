from __future__ import annotations

import asyncio
import json
import time
import weakref
from typing import Any

from platform_core.knowledge.graphs.entity_alignment import (
    apply_entity_alignment_decisions,
    resolve_semantic_entity_alignments,
)
from platform_core.knowledge.graphs.core_semantic_roles import core_role_for_entity_type
from platform_core.knowledge.graphs.entity_type_governance import (
    apply_entity_type_conflict_decisions,
    resolve_entity_type_conflicts,
)
from platform_core.knowledge.graphs.extraction_batch import (
    ChunkExtractionBatchCoordinator,
    is_retryable_extraction_error as _is_retryable_extraction_error,
)
from platform_core.knowledge.graphs.entity_identity import new_entity_uuid, relation_uuid
from platform_core.knowledge.graphs.extraction_cache import semantic_config_fingerprint
from platform_core.knowledge.graphs.extractors import GraphExtractor, GraphExtractorFactory
from platform_core.knowledge.graphs.extractors.llm import (
    DEFAULT_CONTEXT_MAX_CHARS,
    DEFAULT_CONTEXT_WINDOW_SIZE,
    DEFAULT_EXTRACTION_CONCURRENCY,
)
from platform_core.knowledge.graphs.graph_utils import (
    build_graph_payload,
    cypher_merge_chunk,
    cypher_merge_entity_mention,
    cypher_merge_relation,
    normalize_entity_name,
    resolve_entity_naming,
)
from platform_core.knowledge.graphs.lightrag_query_enhancement import (
    LightRAGQueryPlanner,
    graph_keyword_entity_hits,
    graph_keyword_queries,
    merge_graph_subgraphs,
    normalize_retrieval_mode,
    reciprocal_rank_fuse_graph_hits,
    retrieval_queries,
)
from platform_core.knowledge.graphs.lightrag_path_reranking import LightRAGPathReranker
from platform_core.knowledge.graphs.lightrag_evidence_summary import LightRAGEvidenceSummarySelector
from platform_core.knowledge.graphs.lightrag_entity_alignment import LightRAGEntityAlignmentEnhancer
from platform_core.knowledge.graphs.milvus_graph_vector_store import MilvusGraphVectorStore
from platform_core.knowledge.graphs.path_discovery import (
    PathQueryOptions,
    discover_paths as discover_graph_paths,
)
from platform_core.knowledge.graphs.projection_contract import (
    EntityRedirectProjectionPayload,
    GraphProjectionPayload,
    RelationLifecycleProjectionPayload,
    ReviewStatusProjectionPayload,
    build_projection_event,
)
from platform_core.knowledge.graphs.requirement_analysis import analyze_requirement_query
from platform_core.repositories.knowledge_base_repository import KnowledgeBaseRepository
from platform_core.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from platform_core.repositories.knowledge_graph_repository import KnowledgeGraphRepository
from platform_core.storage.neo4j import (
    Neo4jConnectionManager,
    get_shared_neo4j_connection,
    neo4j_read,
    neo4j_write,
    safe_neo4j_label,
)
from platform_core.utils import logger
from platform_core.utils.datetime_utils import utc_isoformat

GRAPH_CONFIG_KEY = "graph_build_config"
GRAPH_TASK_TYPE = "knowledge_graph_index"
NEO4J_QUERY_OFFLOAD_LIMIT = 8
# 数据库游标每次预取的 chunk 数量边界，只控制查询频率和单页内存，不限制 LLM 并发。
# LightRAG 主抽以批内 semaphore 作为唯一 Agent 槽位；融合模式仍可用环境变量形成 GPU/LLM 流水线。
GRAPH_BUILD_FETCH_MIN_SIZE = 100
GRAPH_BUILD_FETCH_MAX_SIZE = 1000
# 构建任务 INFO 汇总日志与前端进度更新间隔；单个 chunk 的耗时明细使用 DEBUG 日志。
GRAPH_BUILD_LOG_INTERVAL_SECONDS = 5.0
GRAPH_VECTOR_BATCH_SIZE = 100
GRAPH_VECTOR_LEASE_SECONDS = 300
GRAPH_VECTOR_FLUSH_INTERVAL_SECONDS = 0.2
GRAPH_EXTRACTION_MAX_ATTEMPTS = 3
GRAPH_EXTRACTION_RETRY_DELAYS_SECONDS = (2.0, 10.0)
# 用户配置值保留原样，便于本地高并发部署迁移；实际 worker 数在此收敛。
# SiliconFlow 公网端点在大并发下会排队并触发客户端超时，因此使用更保守的上限。
GRAPH_EXTRACTION_MAX_RUNTIME_CONCURRENCY = 64
GRAPH_EXTRACTION_PROVIDER_CONCURRENCY_LIMITS = {
    "siliconflow": 16,
    "siliconflow-cn": 16,
}
GRAPH_LIGHTRAG_DEFAULT_AGENT_PARALLELISM = 4
GRAPH_LIGHTRAG_MAX_AGENT_PARALLELISM = 8
GRAPH_MIX_MAX_CHUNK_ENTITY_ANCHORS = 48
GRAPH_REVIEW_SCOPE_ALL = "all"
# 兼容旧调用方；关系检索已取消 accepted/pending_preview 隔离。
GRAPH_REVIEW_SCOPE_ACCEPTED = "accepted"
GRAPH_REVIEW_SCOPE_PENDING_PREVIEW = "pending_preview"
GRAPH_PIPELINE_CONTRACT_VERSION = "lightrag-graph-pipeline-v1"
GRAPH_QUERY_TRACE_CONTRACT_VERSION = "lightrag-query-trace-v1"
_neo4j_query_offload_semaphore_refs: dict[
    int,
    tuple[weakref.ReferenceType[asyncio.AbstractEventLoop], weakref.ReferenceType[asyncio.Semaphore]],
] = {}

# 保留既有导入边界；实现已收敛到高内聚的批抽取模块。
is_retryable_extraction_error = _is_retryable_extraction_error


def build_graph_pipeline_stages(
    *,
    configured: bool,
    total_chunks: int,
    pending_chunks: int,
    indexed_chunks: int,
    structured_chunks: int,
    extraction_counts: dict[str, int],
    vector_counts: dict[str, int],
    projection_counts: dict[str, int],
    entity_count: int,
    relationship_count: int,
    build_task_status: str | None,
    build_task_progress: int,
) -> dict[str, Any]:
    """把真实存储统计投影为稳定、可展示的图谱构建阶段。"""
    build_active = build_task_status in {"pending", "running"}
    build_failed = build_task_status == "failed"
    extraction_failed = int(extraction_counts.get("failed") or 0)
    extraction_pending = int(extraction_counts.get("pending") or 0)
    vector_failed = int(vector_counts.get("failed") or 0)
    vector_pending = int(vector_counts.get("pending") or 0) + int(vector_counts.get("processing") or 0)
    projection_failed = int(projection_counts.get("failed") or 0)
    projection_pending = int(projection_counts.get("pending") or 0) + int(projection_counts.get("processing") or 0)
    authoritative_records = max(int(entity_count), 0) + max(int(relationship_count), 0)

    parse_status = "completed" if total_chunks else ("active" if configured else "idle")
    if build_failed or extraction_failed:
        extraction_status = "warning"
    elif build_active or extraction_pending or pending_chunks:
        extraction_status = "active"
    elif total_chunks and structured_chunks >= total_chunks:
        extraction_status = "completed"
    else:
        extraction_status = "idle"

    if build_failed:
        alignment_status = "warning"
    elif build_active and structured_chunks < total_chunks:
        alignment_status = "active"
    elif structured_chunks:
        alignment_status = "completed"
    else:
        alignment_status = "idle"

    if build_failed:
        commit_status = "warning"
    elif build_active and (structured_chunks or authoritative_records):
        commit_status = "active"
    elif structured_chunks and structured_chunks >= total_chunks:
        commit_status = "completed"
    else:
        commit_status = "idle"

    if projection_failed:
        graph_projection_status = "warning"
    elif projection_pending:
        graph_projection_status = "active"
    elif structured_chunks and int(projection_counts.get("completed") or 0) >= structured_chunks:
        graph_projection_status = "completed"
    elif authoritative_records:
        graph_projection_status = "active"
    else:
        graph_projection_status = "idle"

    if vector_failed:
        vector_projection_status = "warning"
    elif vector_pending or (build_active and structured_chunks > indexed_chunks):
        vector_projection_status = "active"
    elif total_chunks and indexed_chunks >= total_chunks:
        vector_projection_status = "completed"
    else:
        vector_projection_status = "idle"

    return {
        "contract_version": GRAPH_PIPELINE_CONTRACT_VERSION,
        "stages": [
            {
                "key": "document_parse",
                "label": "文档解析",
                "status": parse_status,
                "metrics": {"total_chunks": int(total_chunks)},
            },
            {
                "key": "information_extraction",
                "label": "信息抽取",
                "status": extraction_status,
                "metrics": {
                    "pending_chunks": int(pending_chunks),
                    "succeeded_chunks": int(extraction_counts.get("succeeded") or 0),
                    "failed_chunks": extraction_failed,
                    "task_progress": int(build_task_progress),
                },
            },
            {
                "key": "entity_alignment",
                "label": "实体归一",
                "status": alignment_status,
                "metrics": {"processed_chunks": int(structured_chunks)},
            },
            {
                "key": "authoritative_commit",
                "label": "权威提交",
                "status": commit_status,
                "metrics": {
                    "structured_chunks": int(structured_chunks),
                    "entity_count": int(entity_count),
                    "relationship_count": int(relationship_count),
                },
            },
            {
                "key": "graph_projection",
                "label": "图谱投影",
                "status": graph_projection_status,
                "metrics": {
                    "pending": projection_pending,
                    "completed": int(projection_counts.get("completed") or 0),
                    "failed": projection_failed,
                },
            },
            {
                "key": "vector_projection",
                "label": "向量投影",
                "status": vector_projection_status,
                "metrics": {
                    "indexed_chunks": int(indexed_chunks),
                    "pending_records": vector_pending,
                    "failed_records": vector_failed,
                },
            },
        ],
    }


def build_query_pipeline_trace(
    *,
    requested_retrieval_mode: str,
    query_plan: dict[str, Any],
    entity_hits: list[dict[str, Any]],
    triple_hits: list[dict[str, Any]],
    chunk_hits: list[dict[str, Any]],
    fusion: dict[str, Any],
    retrieval_failures: list[dict[str, str]],
    subgraph_node_count: int,
    subgraph_edge_count: int,
    candidate_path_count: int,
    returned_path_count: int,
    reranking: dict[str, Any],
    semantic_retrieval_available: bool = True,
    chunk_retrieval_available: bool = True,
) -> dict[str, Any]:
    """生成一次多跳查询的可解释执行轨迹，不伪造耗时或中间事件。"""
    failure_channels = [str(item.get("channel") or "unknown") for item in retrieval_failures]
    planner_status = str((query_plan.get("provenance") or {}).get("status") or "disabled")
    reranker_status = str((reranking.get("provenance") or {}).get("status") or "disabled")

    def retrieval_stage(
        channel: str,
        label: str,
        count: int,
        enabled: bool,
        *,
        failure_aliases: tuple[str, ...] = (),
        available: bool = True,
    ) -> dict[str, Any]:
        channel_failures = [item for item in failure_channels if item in {channel, "vector_store", *failure_aliases}]
        if enabled and not available:
            channel_failures.append(f"{channel}_unavailable")
        status = "warning" if channel_failures else ("completed" if enabled else "skipped")
        return {
            "key": f"{channel}_retrieval",
            "label": label,
            "status": status,
            "count": int(count),
            "metrics": {
                "hit_count": int(count),
                "requested": bool(enabled),
                "available": bool(available),
            },
            "degraded": bool(channel_failures),
            "failure_channels": channel_failures,
        }

    entity_enabled = requested_retrieval_mode in {"local", "hybrid", "mix"}
    relation_enabled = requested_retrieval_mode in {"global", "hybrid", "mix"}
    chunk_enabled = requested_retrieval_mode in {"naive", "mix"}
    relation_stage = retrieval_stage(
        "relation",
        "关系召回",
        len(triple_hits),
        relation_enabled,
        failure_aliases=("triple",),
        available=semantic_retrieval_available,
    )
    relation_stage["metrics"].update(
        {
            "relationship_hit_count": len(triple_hits),
            "collection_scope": "all_active_relationships",
        }
    )
    stages = [
        {
            "key": "query_planning",
            "label": "查询规划",
            "status": "completed"
            if planner_status == "completed"
            else ("warning" if planner_status == "degraded" else "skipped"),
            "count": len(query_plan.get("low_level_keywords") or []) + len(query_plan.get("high_level_keywords") or []),
            "metrics": {"planner_status": planner_status},
            "degraded": planner_status == "degraded",
            "failure_channels": [],
        },
        retrieval_stage(
            "entity",
            "实体召回",
            len(entity_hits),
            entity_enabled,
            available=semantic_retrieval_available,
        ),
        relation_stage,
        retrieval_stage(
            "chunk",
            "原文召回",
            len(chunk_hits),
            chunk_enabled,
            available=chunk_retrieval_available,
        ),
        {
            "key": "graph_fusion",
            "label": "图谱融合",
            "status": "warning" if failure_channels else "completed",
            "count": len(fusion.get("entity_ids") or []),
            "metrics": {
                "fusion_method": fusion.get("fusion_method") or "none",
                "subgraph_node_count": int(subgraph_node_count),
                "subgraph_edge_count": int(subgraph_edge_count),
            },
            "degraded": bool(failure_channels),
            "failure_channels": list(dict.fromkeys(failure_channels)),
        },
        {
            "key": "path_search",
            "label": "路径搜索",
            "status": "completed",
            "count": int(candidate_path_count),
            "metrics": {"candidate_path_count": int(candidate_path_count)},
            "degraded": False,
            "failure_channels": [],
        },
        {
            "key": "path_reranking",
            "label": "路径重排",
            "status": "completed"
            if reranker_status == "completed"
            else ("warning" if reranker_status == "degraded" else "skipped"),
            "count": int(returned_path_count),
            "metrics": {
                "reranker_status": reranker_status,
                "returned_path_count": int(returned_path_count),
            },
            "degraded": reranker_status == "degraded",
            "failure_channels": [],
        },
    ]
    return {
        "contract_version": GRAPH_QUERY_TRACE_CONTRACT_VERSION,
        "degraded": any(bool(stage["degraded"]) for stage in stages),
        "stages": stages,
    }


def _has_extraction_cache_metadata(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    metadata = result.get("metadata")
    return isinstance(metadata, dict) and "extraction_cache" in metadata


def _get_neo4j_query_offload_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    entry = _neo4j_query_offload_semaphore_refs.get(loop_id)
    if entry is not None:
        loop_ref, semaphore_ref = entry
        semaphore = semaphore_ref()
        if loop_ref() is loop and semaphore is not None:
            return semaphore

    semaphore = asyncio.Semaphore(NEO4J_QUERY_OFFLOAD_LIMIT)

    def cleanup(ref, stale_loop_id=loop_id):
        current_entry = _neo4j_query_offload_semaphore_refs.get(stale_loop_id)
        if current_entry is not None and current_entry[1] is ref:
            _neo4j_query_offload_semaphore_refs.pop(stale_loop_id, None)

    _neo4j_query_offload_semaphore_refs[loop_id] = (weakref.ref(loop), weakref.ref(semaphore, cleanup))
    return semaphore


async def _run_neo4j_query_io(func, /, *args, **kwargs):
    semaphore = _get_neo4j_query_offload_semaphore()
    await semaphore.acquire()
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))

    def release_capacity(completed_task: asyncio.Task):
        semaphore.release()
        if completed_task.cancelled():
            return
        completed_task.exception()

    task.add_done_callback(release_capacity)
    return await asyncio.shield(task)


class MilvusGraphService:
    def __init__(
        self,
        *,
        kb_id: str | None = None,
        kb_repo: KnowledgeBaseRepository | None = None,
        chunk_repo: KnowledgeChunkRepository | None = None,
        graph_repo: KnowledgeGraphRepository | None = None,
        graph_vector_store: MilvusGraphVectorStore | None = None,
        neo4j_connection: Neo4jConnectionManager | None = None,
        query_planner_factory: Any | None = None,
        path_reranker_factory: Any | None = None,
        evidence_summary_selector_factory: Any | None = None,
        chunk_retriever: Any | None = None,
    ):
        self.kb_id = kb_id
        self.kb_repo = kb_repo or KnowledgeBaseRepository()
        self.chunk_repo = chunk_repo or KnowledgeChunkRepository()
        self.graph_repo = graph_repo or KnowledgeGraphRepository()
        self._graph_vector_store = graph_vector_store
        self._graph_vector_store_lock = asyncio.Lock()
        self._connection = neo4j_connection
        self._query_planner_factory = query_planner_factory or LightRAGQueryPlanner
        self._path_reranker_factory = path_reranker_factory or LightRAGPathReranker
        self._evidence_summary_selector_factory = evidence_summary_selector_factory or LightRAGEvidenceSummarySelector
        self._chunk_retriever = chunk_retriever

    @property
    def connection(self) -> Neo4jConnectionManager:
        if self._connection is None:
            self._connection = get_shared_neo4j_connection()
        return self._connection

    @property
    def graph_vector_store(self) -> MilvusGraphVectorStore:
        if self._graph_vector_store is None:
            self._graph_vector_store = MilvusGraphVectorStore()
        return self._graph_vector_store

    async def get_graph_vector_store(self) -> MilvusGraphVectorStore:
        if self._graph_vector_store is not None:
            return self._graph_vector_store
        async with self._graph_vector_store_lock:
            if self._graph_vector_store is None:
                self._graph_vector_store = await asyncio.to_thread(MilvusGraphVectorStore)
        return self._graph_vector_store

    async def index_pending_graph_vectors(
        self,
        kb_id: str,
        *,
        limit: int = GRAPH_VECTOR_BATCH_SIZE,
        record_types: tuple[str, ...] = ("entity", "triple"),
    ) -> dict[str, dict[str, int]]:
        """用 PostgreSQL lease 索引一批待刷新实体/三元组向量。"""
        kb = await self._get_milvus_kb(kb_id)
        graph_vector_store = await self.get_graph_vector_store()
        graph_config = dict((kb.additional_params or {}).get(GRAPH_CONFIG_KEY) or {})
        extractor_options = dict(graph_config.get("extractor_options") or {})
        evidence_summary = dict(extractor_options.get("retrieval_evidence_summary") or {})
        bounded_limit = max(1, min(int(limit), 500))
        invalid_types = sorted(set(record_types) - {"entity", "triple"})
        if invalid_types:
            raise ValueError(f"不支持的图向量记录类型: {', '.join(invalid_types)}")

        results = await asyncio.gather(
            *(
                self._index_pending_graph_vector_type(
                    kb_id=kb_id,
                    embedding_model_spec=kb.embedding_model_spec,
                    record_type=record_type,
                    limit=bounded_limit,
                    graph_vector_store=graph_vector_store,
                    evidence_summary=evidence_summary,
                )
                for record_type in record_types
            )
        )
        by_type = dict(zip(record_types, results, strict=True))
        if any(item["claimed"] for item in results):
            await self.graph_repo.finalize_graph_indexed_chunks(kb_id)
        return by_type

    async def drain_pending_graph_vectors(
        self,
        kb_id: str,
        *,
        context: Any | None = None,
        limit: int = GRAPH_VECTOR_BATCH_SIZE,
    ) -> dict[str, Any]:
        """只排空权威记录的向量投影队列，不触发抽取或文档增强。"""

        totals = {
            "entity": {"claimed": 0, "indexed": 0, "failed": 0},
            "triple": {"claimed": 0, "indexed": 0, "failed": 0},
        }
        batches = 0
        while True:
            if context is not None:
                await context.raise_if_cancelled()
            batch = await self.index_pending_graph_vectors(kb_id, limit=limit)
            claimed = 0
            for record_type in ("entity", "triple"):
                for metric in ("claimed", "indexed", "failed"):
                    totals[record_type][metric] += int(batch[record_type][metric])
                claimed += int(batch[record_type]["claimed"])
            if claimed:
                batches += 1
                continue

            vector_counts = await self.graph_repo.count_vector_statuses_by_kb_id(kb_id)
            if int(vector_counts.get("failed") or 0):
                raise RuntimeError(f"图谱向量投影失败：failed={vector_counts['failed']} kb_id={kb_id}")
            if int(vector_counts.get("pending") or 0) or int(vector_counts.get("processing") or 0):
                await asyncio.sleep(GRAPH_VECTOR_FLUSH_INTERVAL_SECONDS)
                continue

            finalized_chunks = await self.graph_repo.finalize_graph_indexed_chunks(kb_id)
            return {
                "kb_id": kb_id,
                "batches": batches,
                "entity": totals["entity"],
                "triple": totals["triple"],
                "finalized_chunks": finalized_chunks,
                "vector_counts": vector_counts,
            }

    async def _index_pending_graph_vector_type(
        self,
        *,
        kb_id: str,
        embedding_model_spec: str,
        record_type: str,
        limit: int,
        graph_vector_store: MilvusGraphVectorStore,
        evidence_summary: dict[str, Any],
    ) -> dict[str, int]:
        lock_token, records = await self.graph_repo.claim_vector_records(
            kb_id=kb_id,
            record_type=record_type,
            limit=limit,
            lease_seconds=GRAPH_VECTOR_LEASE_SECONDS,
            include_evidence_rows=record_type == "entity" and evidence_summary.get("enabled") is True,
        )
        if not records:
            return {"claimed": 0, "indexed": 0, "failed": 0}

        record_ids = [record["id"] for record in records]
        try:
            if record_type == "entity" and evidence_summary.get("enabled"):
                selector = self._evidence_summary_selector_factory(evidence_summary)
                try:
                    records = await selector.enhance_records(records)
                finally:
                    await selector.aclose()
            await graph_vector_store.upsert_graph_records(
                kb_id=kb_id,
                embedding_model_spec=embedding_model_spec,
                record_type=record_type,
                records=records,
            )
            indexed_record_ids = await self.graph_repo.mark_vector_records_indexed(
                record_type=record_type,
                record_ids=record_ids,
                lock_token=lock_token,
            )
            indexed_record_ids = list(indexed_record_ids or [])
            if record_type == "triple":
                stale_record_ids = sorted(set(record_ids) - set(indexed_record_ids))
                if stale_record_ids:
                    await graph_vector_store.delete_graph_records(
                        kb_id,
                        entity_ids=[],
                        triple_ids=stale_record_ids,
                    )
            return {
                "claimed": len(records),
                "indexed": len(indexed_record_ids),
                "failed": 0,
            }
        except asyncio.CancelledError as exc:
            await self.graph_repo.mark_vector_records_failed(
                record_type=record_type,
                record_ids=record_ids,
                lock_token=lock_token,
                error=str(exc) or "cancelled",
            )
            raise
        except Exception as exc:  # noqa: BLE001
            await self.graph_repo.mark_vector_records_failed(
                record_type=record_type,
                record_ids=record_ids,
                lock_token=lock_token,
                error=str(exc),
            )
            logger.error(f"图谱向量索引失败 kb_id={kb_id} type={record_type} count={len(records)}: {exc}")
            return {"claimed": len(records), "indexed": 0, "failed": len(records)}

    @property
    def driver(self):
        return self.connection.driver

    async def get_status(self, kb_id: str, *, tasker: Any = None) -> dict[str, Any]:
        kb = await self._get_milvus_kb(kb_id)
        params = dict(kb.additional_params or {})
        config = params.get(GRAPH_CONFIG_KEY) or {}
        projection_status_reader = getattr(self.graph_repo, "count_projection_statuses", None)
        projection_status = (
            projection_status_reader(kb_id)
            if projection_status_reader is not None
            else asyncio.sleep(
                0,
                result={"pending": 0, "processing": 0, "completed": 0, "failed": 0},
            )
        )
        status_values = await asyncio.gather(
            self.chunk_repo.count_by_kb_id(kb_id),
            self.chunk_repo.count_graph_pending_by_kb_id(kb_id),
            self.chunk_repo.count_graph_indexed_by_kb_id(kb_id),
            self.chunk_repo.count_graph_structure_indexed_by_kb_id(kb_id),
            self.chunk_repo.count_graph_extraction_statuses_by_kb_id(kb_id),
            self.graph_repo.count_by_kb_id(kb_id),
            self.graph_repo.count_vector_statuses_by_kb_id(kb_id),
            projection_status,
        )
        (
            total_chunks,
            pending_chunks,
            indexed_chunks,
            structured_chunks,
            extraction_counts,
            graph_counts,
            vector_counts,
            projection_counts,
        ) = status_values
        entity_count, relationship_count = graph_counts

        build_task_status = None
        build_task_progress = 0
        if tasker is not None:
            latest_task = await tasker.find_task_by_payload(
                task_type=GRAPH_TASK_TYPE,
                payload_match={"kb_id": kb_id},
                statuses=None,
            )
            if latest_task and latest_task.status in {"pending", "running"}:
                build_task_status = latest_task.status
                build_task_progress = round(latest_task.progress)
            elif latest_task and latest_task.status == "success":
                build_task_status = "completed"
                build_task_progress = 100
            elif latest_task and latest_task.status in {"failed", "cancelled"}:
                build_task_status = "failed"

        pipeline_stages = build_graph_pipeline_stages(
            configured=bool(config),
            total_chunks=total_chunks,
            pending_chunks=pending_chunks,
            indexed_chunks=indexed_chunks,
            structured_chunks=structured_chunks,
            extraction_counts=extraction_counts,
            vector_counts=vector_counts,
            projection_counts=projection_counts,
            entity_count=entity_count,
            relationship_count=relationship_count,
            build_task_status=build_task_status,
            build_task_progress=build_task_progress,
        )

        return {
            "kb_id": kb_id,
            "kb_type": kb.kb_type,
            "configured": bool(config),
            "locked": bool(config.get("locked")),
            "config": self._public_config(config),
            "runtime": self._graph_extraction_runtime(config),
            "total_chunks": total_chunks,
            "pending_chunks": pending_chunks,
            "indexed_chunks": indexed_chunks,
            "structured_chunks": structured_chunks,
            "extraction_counts": extraction_counts,
            "vector_counts": vector_counts,
            "projection_counts": projection_counts,
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "build_task_status": build_task_status,
            "build_task_progress": build_task_progress,
            "pipeline_stages": pipeline_stages,
        }

    async def configure(
        self,
        kb_id: str,
        extractor_type: str,
        extractor_options: dict[str, Any],
        created_by: str,
    ) -> dict:
        kb = await self._get_milvus_kb(kb_id)
        additional_params = dict(kb.additional_params or {})
        existing_config = additional_params.get(GRAPH_CONFIG_KEY) or {}
        normalized_extractor_type = (extractor_type or "").lower()
        if existing_config.get("locked"):
            existing_extractor_type = (existing_config.get("extractor_type") or "").lower()
            if normalized_extractor_type != existing_extractor_type:
                raise ValueError("图谱抽取器类型已锁定，只能修改模型、Schema 等抽取参数")

        extractor_options = extractor_options or {}
        if normalized_extractor_type == "llm" and extractor_options.get("prompt"):
            raise ValueError("LLM 图谱抽取器不支持自定义完整 Prompt，请使用 schema 配置抽取约束")
        GraphExtractorFactory.create(normalized_extractor_type, extractor_options)
        semantic_fingerprint = semantic_config_fingerprint(normalized_extractor_type, extractor_options)
        if existing_config.get("locked"):
            existing_fingerprint = str(existing_config.get("semantic_fingerprint") or "")
            if not existing_fingerprint:
                existing_fingerprint = semantic_config_fingerprint(
                    str(existing_config.get("extractor_type") or ""),
                    existing_config.get("extractor_options") or {},
                )
            if semantic_fingerprint != existing_fingerprint:
                structured_chunks, indexed_chunks = await asyncio.gather(
                    self.chunk_repo.count_graph_structure_indexed_by_kb_id(kb_id),
                    self.chunk_repo.count_graph_indexed_by_kb_id(kb_id),
                )
                if structured_chunks or indexed_chunks:
                    raise ValueError(
                        "图谱已有权威入库知识，语义配置已锁定；"
                        "请通过显式图谱重建创建新 revision，不能静默复用或覆盖旧抽取结果"
                    )
        config = {
            "locked": True,
            "extractor_type": normalized_extractor_type,
            "extractor_options": extractor_options or {},
            "semantic_fingerprint": semantic_fingerprint,
            "created_at": existing_config.get("created_at") or utc_isoformat(),
            "created_by": existing_config.get("created_by") or created_by,
        }
        if existing_config.get("locked"):
            config["updated_at"] = utc_isoformat()
            config["updated_by"] = created_by
        additional_params[GRAPH_CONFIG_KEY] = config
        await self.kb_repo.update(kb_id, {"additional_params": additional_params})
        return config

    async def get_build_configuration(self, kb_id: str) -> dict[str, Any]:
        """读取已锁定的构建配置，供应用层固定运行谱系。"""
        kb = await self._get_milvus_kb(kb_id)
        config = self._get_locked_config(kb.additional_params or {})
        return self._public_config(config) or {}

    async def ensure_projection_target(self, kb_id: str) -> None:
        """在删除现有投影前校验知识库和向量模型均可用于重建。"""

        kb = await self._get_milvus_kb(kb_id)
        if not str(kb.embedding_model_spec or "").strip():
            raise ValueError("图谱投影重建需要知识库配置 embedding_model_spec")

    async def align_document_entity_records(
        self,
        *,
        kb_id: str,
        entities: list[dict[str, Any]],
        triples: list[dict[str, Any]],
        entity_alignment_options: dict[str, Any] | None = None,
    ) -> None:
        """让文档级漏抽候选复用热路径的精确、向量和受约束 LLM 对齐。"""
        if not entities:
            return
        kb = await self._get_milvus_kb(kb_id)
        options = dict(entity_alignment_options or {})
        enhancer = LightRAGEntityAlignmentEnhancer(options) if options.get("enabled") else None
        try:
            await self._align_entity_records(
                kb_id=kb_id,
                embedding_model_spec=kb.embedding_model_spec,
                entities=entities,
                triples=triples,
                llm_enhancer=enhancer,
            )
        finally:
            if enhancer is not None:
                await enhancer.aclose()

    async def get_failed_chunk_samples(self, kb_id: str, limit: int = 10) -> dict[str, Any]:
        await self._get_milvus_kb(kb_id)
        samples = await self.chunk_repo.list_graph_extraction_failed_samples(kb_id, limit)
        return {"kb_id": kb_id, "samples": samples}

    async def build_pending_chunks(
        self,
        kb_id: str,
        *,
        context=None,
        failed_only: bool = False,
        chunk_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """构建待处理 Chunk；可将范围收窄为仅重跑抽取失败项。"""
        kb = await self._get_milvus_kb(kb_id)
        config = self._get_locked_config(kb.additional_params or {})
        extractor_options = self._runtime_extractor_options(config)
        extractor = GraphExtractorFactory.create(config["extractor_type"], extractor_options)
        entity_alignment_options = dict(extractor_options.get("entity_alignment") or {})
        entity_alignment_enhancer = (
            LightRAGEntityAlignmentEnhancer(entity_alignment_options)
            if entity_alignment_options.get("enabled")
            else None
        )
        worker_count = self._get_worker_count(config)
        runtime_policy = self._graph_extraction_runtime(config)
        scoped_chunks = None
        if chunk_ids is not None:
            scoped_chunks = [
                chunk
                for chunk in await self.chunk_repo.list_by_chunk_ids(chunk_ids)
                if chunk.kb_id == kb_id
                and chunk.graph_indexed is not True
                and chunk.graph_excluded is not True
                and (
                    not failed_only
                    or str((chunk.graph_extraction_details or {}).get("status") or "pending") == "failed"
                )
            ]
            total_pending = len(scoped_chunks)
        elif failed_only:
            total_pending = await self.chunk_repo.count_graph_extraction_failed_by_kb_id(kb_id)
        else:
            total_pending = await self.chunk_repo.count_graph_pending_by_kb_id(kb_id)
        initially_indexed = await self.chunk_repo.count_graph_indexed_by_kb_id(kb_id)
        processed = 0
        extraction_failed = 0
        write_failed = 0
        extraction_completed = 0
        write_completed = 0
        active_extractions = 0
        verified_facts = 0
        evidence_review_required = 0
        extraction_batch_size = self._get_extraction_batch_size(config)
        fetch_size = max(GRAPH_BUILD_FETCH_MIN_SIZE, min(worker_count * 2, GRAPH_BUILD_FETCH_MAX_SIZE))
        extraction_queue: asyncio.Queue[list[Any] | None] = asyncio.Queue(maxsize=max(worker_count * 2, 1))
        write_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=max(worker_count * 2, 1))
        reporter_stop = asyncio.Event()
        structure_done = asyncio.Event()
        vector_wakeup = asyncio.Event()
        started_at = time.monotonic()

        logger.info(
            f"图谱构建开始 kb_id={kb_id} scope={'failed' if failed_only else 'pending'} "
            f"pending={total_pending} "
            f"extraction_concurrency={worker_count} batch_size={extraction_batch_size} fetch_size={fetch_size} "
            f"parallelism_strategy={(runtime_policy or {}).get('parallelism_strategy') or 'worker_pool'} "
            f"agent_parallelism={(runtime_policy or {}).get('agent_parallelism_effective') or 1}"
        )
        if runtime_policy and runtime_policy["concurrency_capped"]:
            logger.warning(
                f"图谱抽取并发已自动收敛 kb_id={kb_id} "
                f"configured={runtime_policy['configured_concurrency_count']} "
                f"effective={runtime_policy['effective_concurrency_count']} "
                f"provider={runtime_policy['provider_id'] or 'unknown'}"
            )

        async def put_queue_item(queue: asyncio.Queue, item) -> None:
            while True:
                if context is not None:
                    await context.raise_if_cancelled()
                try:
                    await asyncio.wait_for(queue.put(item), timeout=0.5)
                    return
                except TimeoutError:
                    continue

        async def extraction_worker(worker_index: int) -> None:
            nonlocal active_extractions, extraction_completed, extraction_failed
            nonlocal verified_facts, evidence_review_required
            while True:
                chunks = await extraction_queue.get()
                try:
                    if chunks is None:
                        return
                    if context is not None:
                        await context.raise_if_cancelled()
                    active_extractions += len(chunks)
                    extraction_started_at = time.monotonic()
                    try:
                        results = await self._get_chunk_extraction_results(kb_id, chunks, extractor)
                        for chunk, result in zip(chunks, results, strict=True):
                            if isinstance(result, Exception):
                                extraction_failed += 1
                                logger.error(
                                    f"Chunk 图谱抽取失败 kb_id={kb_id} chunk_id={chunk.chunk_id} "
                                    f"worker={worker_index}: {result}"
                                )
                                continue
                            evidence = result.get("metadata", {}).get("evidence_verification", {})
                            verified_facts += evidence.get("verified_facts", 0)
                            evidence_review_required += evidence.get("reclassified_facts", 0)
                            await put_queue_item(write_queue, chunk.chunk_id)
                    except Exception as exc:
                        extraction_failed += len(chunks)
                        chunk_ids = ",".join(chunk.chunk_id for chunk in chunks)
                        logger.error(
                            f"Chunk 批量图谱抽取失败 kb_id={kb_id} chunk_ids={chunk_ids} worker={worker_index}: {exc}"
                        )
                    finally:
                        active_extractions -= len(chunks)
                        extraction_completed += len(chunks)
                        logger.debug(
                            f"Chunk 批量图谱抽取结束 kb_id={kb_id} batch_count={len(chunks)} "
                            f"worker={worker_index} duration={time.monotonic() - extraction_started_at:.2f}s"
                        )
                finally:
                    extraction_queue.task_done()

        async def write_worker() -> None:
            nonlocal processed, write_failed, write_completed
            while True:
                chunk_id = await write_queue.get()
                try:
                    if chunk_id is None:
                        return
                    if context is not None:
                        await context.raise_if_cancelled()
                    chunk = await self.chunk_repo.get_by_chunk_id(chunk_id)
                    if chunk is None:
                        raise ValueError(f"图谱写入找不到 chunk: {chunk_id}")
                    extraction_result = await self._get_chunk_extraction_result(kb_id, chunk, extractor)
                    write_started_at = time.monotonic()
                    graph_payload, entities, triples = self.prepare_chunk_graph_records(
                        kb_id,
                        extraction_result,
                    )
                    await self._align_entity_records(
                        kb_id=kb_id,
                        embedding_model_spec=kb.embedding_model_spec,
                        entities=entities,
                        triples=triples,
                        llm_enhancer=entity_alignment_enhancer,
                    )
                    hydrate_lifecycle = getattr(self.graph_repo, "hydrate_triple_lifecycle", None)
                    if hydrate_lifecycle is not None:
                        await hydrate_lifecycle(kb_id=kb_id, triples=triples)
                    projection_event = build_projection_event(
                        kb_id=kb_id,
                        chunk=chunk,
                        graph_payload=graph_payload,
                        entity_records=entities,
                        triple_records=triples,
                    )
                    await self.graph_repo.upsert_chunk_graph(
                        kb_id=kb_id,
                        file_id=chunk.file_id,
                        chunk_id=chunk.chunk_id,
                        entities=entities,
                        triples=triples,
                        projection_event=projection_event,
                    )
                    # Neo4j 是 PostgreSQL 的可重建投影，只能由 outbox 消费者写入。
                    # 这里若同步投影，后台消费者可能在事件提交后同时领取同一事件；
                    # Neo4j 在没有全局唯一约束时会让并发 MERGE 生成重复节点和边。
                    # 权威提交与投影解耦后，事件租约成为唯一写入边界，也保留失败重试语义。
                    await self.chunk_repo.mark_graph_structure_indexed(
                        chunk.chunk_id,
                        ent_ids=[entity["entity_id"] for entity in entities],
                    )
                    vector_wakeup.set()
                    processed += 1
                    logger.debug(
                        f"Chunk 图谱写入结束 kb_id={kb_id} chunk_id={chunk.chunk_id} "
                        f"entities={len(entities)} triples={len(triples)} "
                        f"duration={time.monotonic() - write_started_at:.2f}s"
                    )
                except Exception as exc:
                    write_failed += 1
                    logger.error(f"Chunk 图谱写入失败 kb_id={kb_id} chunk_id={chunk_id}: {exc}")
                finally:
                    if chunk_id is not None:
                        write_completed += 1
                    write_queue.task_done()

        async def vector_worker() -> None:
            while True:
                if context is not None:
                    await context.raise_if_cancelled()
                vector_batch = await self.index_pending_graph_vectors(
                    kb_id,
                    limit=GRAPH_VECTOR_BATCH_SIZE,
                )
                entity_count = vector_batch["entity"]["claimed"]
                triple_count = vector_batch["triple"]["claimed"]
                if entity_count or triple_count:
                    continue

                vector_counts = await self.graph_repo.count_vector_statuses_by_kb_id(kb_id)
                if structure_done.is_set() and not vector_counts["pending"] and not vector_counts["processing"]:
                    await self.graph_repo.finalize_graph_indexed_chunks(kb_id)
                    return
                vector_wakeup.clear()
                try:
                    await asyncio.wait_for(vector_wakeup.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                if vector_wakeup.is_set():
                    await asyncio.sleep(GRAPH_VECTOR_FLUSH_INTERVAL_SECONDS)

        async def report_progress() -> None:
            while True:
                try:
                    await asyncio.wait_for(reporter_stop.wait(), timeout=GRAPH_BUILD_LOG_INTERVAL_SECONDS)
                except TimeoutError:
                    pass

                elapsed = max(time.monotonic() - started_at, 0.001)
                extraction_rate = extraction_completed / elapsed
                vector_counts = await self.graph_repo.count_vector_statuses_by_kb_id(kb_id)
                message = (
                    f"图谱构建：抽取 {extraction_completed}/{total_pending} "
                    f"(活跃 {active_extractions}/{worker_count})，写入 {write_completed}/{total_pending}，"
                    f"向量待处理 {vector_counts['pending'] + vector_counts['processing']}，"
                    f"向量失败 {vector_counts['failed']}，抽取失败 {extraction_failed}，"
                    f"写入失败 {write_failed}，抽取吞吐 {extraction_rate:.2f} chunk/s，"
                    f"事实引用已核验 {verified_facts}，证据待复核 {evidence_review_required}"
                )
                logger.info(f"kb_id={kb_id} {message}")
                if context is not None:
                    extraction_progress = extraction_completed / max(total_pending, 1) * 40.0
                    structure_progress = write_completed / max(total_pending, 1) * 20.0
                    indexed_chunks = await self.chunk_repo.count_graph_indexed_by_kb_id(kb_id)
                    newly_indexed = max(indexed_chunks - initially_indexed, 0)
                    vector_progress = newly_indexed / max(total_pending, 1) * 35.0
                    await context.set_progress(
                        5.0 + min(extraction_progress + structure_progress + vector_progress, 95.0), message
                    )
                if reporter_stop.is_set():
                    return

        extraction_workers = [
            asyncio.create_task(extraction_worker(index + 1), name=f"graph-extractor-{index + 1}")
            for index in range(worker_count)
        ]
        writer_task = asyncio.create_task(write_worker(), name="graph-writer")
        vector_task = asyncio.create_task(vector_worker(), name="graph-vector-indexer")
        reporter_task = asyncio.create_task(report_progress(), name="graph-progress-reporter")

        async def enqueue_chunks(chunks: list[Any]) -> None:
            nonlocal extraction_completed, write_completed
            extraction_batch = []
            for chunk in chunks:
                if getattr(chunk, "graph_structure_indexed", False):
                    extraction_completed += 1
                    write_completed += 1
                    vector_wakeup.set()
                elif (
                    chunk.extraction_result
                    and extractor.extractor_type == "llm"
                    and not _has_extraction_cache_metadata(chunk.extraction_result)
                ):
                    extraction_completed += 1
                    await put_queue_item(write_queue, chunk.chunk_id)
                else:
                    extraction_batch.append(chunk)
                    if len(extraction_batch) >= extraction_batch_size:
                        await put_queue_item(extraction_queue, extraction_batch)
                        extraction_batch = []
            if extraction_batch:
                await put_queue_item(extraction_queue, extraction_batch)

        try:
            if scoped_chunks is not None:
                for offset in range(0, len(scoped_chunks), fetch_size):
                    if context is not None:
                        await context.raise_if_cancelled()
                    await enqueue_chunks(scoped_chunks[offset : offset + fetch_size])
            else:
                after_id = 0
                while True:
                    if context is not None:
                        await context.raise_if_cancelled()
                    if failed_only:
                        chunks = await self.chunk_repo.list_graph_extraction_failed_by_kb_id(
                            kb_id,
                            fetch_size,
                            after_id=after_id,
                        )
                    else:
                        chunks = await self.chunk_repo.list_graph_pending_by_kb_id(
                            kb_id,
                            fetch_size,
                            after_id=after_id,
                        )
                    if not chunks:
                        break
                    after_id = chunks[-1].id
                    await enqueue_chunks(chunks)

            for _ in extraction_workers:
                await put_queue_item(extraction_queue, None)
            await asyncio.gather(*extraction_workers)
            await put_queue_item(write_queue, None)
            await writer_task
            structure_done.set()
            vector_wakeup.set()
            await vector_task
        except BaseException:
            for task in [*extraction_workers, writer_task, vector_task]:
                task.cancel()
            await asyncio.gather(*extraction_workers, writer_task, vector_task, return_exceptions=True)
            raise
        finally:
            reporter_stop.set()
            await asyncio.gather(reporter_task, return_exceptions=True)
            close = getattr(extractor, "aclose", None)
            try:
                if close is not None:
                    await close()
            finally:
                if entity_alignment_enhancer is not None:
                    await entity_alignment_enhancer.aclose()

        if scoped_chunks is None:
            if failed_only:
                scoped_remaining = await self.chunk_repo.count_graph_extraction_failed_by_kb_id(kb_id)
            else:
                scoped_remaining = await self.chunk_repo.count_graph_pending_by_kb_id(kb_id)
            scoped_failed = 0
        else:
            refreshed_chunks = await self.chunk_repo.list_by_chunk_ids([chunk.chunk_id for chunk in scoped_chunks])
            scoped_remaining_chunks = [
                chunk
                for chunk in refreshed_chunks
                if chunk.graph_indexed is not True and chunk.graph_excluded is not True
            ]
            scoped_remaining = len(scoped_remaining_chunks)
            scoped_failed = sum(
                str((chunk.graph_extraction_details or {}).get("status") or "pending") == "failed"
                for chunk in scoped_remaining_chunks
            )
        remaining = (
            await self.chunk_repo.count_graph_extraction_failed_by_kb_id(kb_id)
            if failed_only
            else await self.chunk_repo.count_graph_pending_by_kb_id(kb_id)
        )
        extraction_counts = await self.chunk_repo.count_graph_extraction_statuses_by_kb_id(kb_id)
        vector_counts = await self.graph_repo.count_vector_statuses_by_kb_id(kb_id)
        logger.info(
            f"图谱构建结束 kb_id={kb_id} success={processed} extraction_failed={extraction_failed} "
            f"write_failed={write_failed} remaining={remaining} "
            f"duration={time.monotonic() - started_at:.2f}s"
        )
        incomplete = (
            max(remaining - extraction_counts["failed"], 0)
            if scoped_chunks is None
            else max(scoped_remaining - scoped_failed, 0)
        )
        retryable_remaining = max(remaining - extraction_counts["failed"], 0)
        result = {
            "kb_id": kb_id,
            "success": max(total_pending - scoped_remaining, 0),
            "failed": extraction_failed + write_failed,
            "extraction_failed": extraction_failed,
            "write_failed": write_failed,
            "remaining": remaining,
            "batch_remaining": scoped_remaining,
            "retryable_remaining": retryable_remaining,
            "vector_failed": vector_counts["failed"],
            "verified_facts": verified_facts,
            "evidence_review_required": evidence_review_required,
        }
        if incomplete or write_failed or vector_counts["failed"]:
            raise RuntimeError(
                f"图谱构建执行异常：chunk_incomplete={incomplete}, "
                f"write_failed={write_failed}, vector_failed={vector_counts['failed']}"
            )
        return result

    @classmethod
    def _get_worker_count(cls, config: dict[str, Any]) -> int:
        runtime = cls._graph_extraction_runtime(config)
        if not runtime:
            return 1
        return int(runtime.get("extraction_worker_count") or runtime["effective_concurrency_count"])

    @staticmethod
    def _graph_extraction_runtime(config: dict[str, Any]) -> dict[str, Any] | None:
        extractor_type = (config.get("extractor_type") or "").lower()
        if extractor_type not in {"llm", "lightrag_primary"}:
            return None
        options = config.get("extractor_options") or {}
        lightrag_primary = extractor_type == "lightrag_primary"
        if lightrag_primary:
            llm_options = options.get("llm_enhancement") or {}
            raw_concurrency = llm_options.get("concurrency_count") or GRAPH_LIGHTRAG_DEFAULT_AGENT_PARALLELISM
            model_spec = str(llm_options.get("model_spec") or "")
        else:
            raw_concurrency = options.get("concurrency_count") or DEFAULT_EXTRACTION_CONCURRENCY
            model_spec = str(options.get("model_spec") or "")
        try:
            configured = int(raw_concurrency)
        except (TypeError, ValueError):
            configured = 1 if lightrag_primary else DEFAULT_EXTRACTION_CONCURRENCY
        configured = max(1, configured)
        provider_id = model_spec.partition(":")[0].lower() if ":" in model_spec else ""
        limit = GRAPH_EXTRACTION_PROVIDER_CONCURRENCY_LIMITS.get(
            provider_id,
            GRAPH_EXTRACTION_MAX_RUNTIME_CONCURRENCY,
        )
        if lightrag_primary:
            limit = min(limit, GRAPH_LIGHTRAG_MAX_AGENT_PARALLELISM)
        effective = min(configured, limit)
        runtime = {
            "configured_concurrency_count": configured,
            "effective_concurrency_count": effective,
            "concurrency_limit": limit,
            "concurrency_capped": effective < configured,
            "provider_id": provider_id or None,
        }
        if lightrag_primary:
            runtime.update(
                {
                    "parallelism_strategy": "bounded_chunk_fanout",
                    "extraction_worker_count": 1,
                    "agent_parallelism_configured": configured,
                    "agent_parallelism_effective": effective,
                    "chunk_batch_size": effective,
                }
            )
        return runtime

    @staticmethod
    def _runtime_extractor_options(config: dict[str, Any]) -> dict[str, Any]:
        options = dict(config.get("extractor_options") or {})
        options.pop("prompt", None)
        return options

    @staticmethod
    def _get_extraction_batch_size(config: dict[str, Any]) -> int:
        """读取 IE 推理批大小；LightRAG 主抽按 Agent 槽位聚合 Chunk。"""
        extractor_type = str(config.get("extractor_type") or "").lower()
        if extractor_type != "lightrag_primary":
            return 1
        options = dict(config.get("extractor_options") or {})
        raw_parallelism = (options.get("llm_enhancement") or {}).get(
            "concurrency_count",
            GRAPH_LIGHTRAG_DEFAULT_AGENT_PARALLELISM,
        )
        if isinstance(raw_parallelism, bool):
            raise ValueError("llm_enhancement.concurrency_count 必须是整数")
        try:
            parallelism = int(raw_parallelism)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("llm_enhancement.concurrency_count 必须是整数") from exc
        return max(1, min(parallelism, GRAPH_LIGHTRAG_MAX_AGENT_PARALLELISM))

    async def _get_chunk_extraction_result(self, kb_id: str, chunk, extractor: GraphExtractor) -> dict[str, Any]:
        coordinator = self._chunk_extraction_coordinator()
        return await coordinator.get_result(kb_id, chunk, extractor)

    async def _get_chunk_extraction_results(
        self,
        kb_id: str,
        chunks: list[Any],
        extractor: GraphExtractor,
    ) -> list[dict[str, Any] | Exception]:
        coordinator = self._chunk_extraction_coordinator()
        return await coordinator.get_results(kb_id, chunks, extractor)

    def _chunk_extraction_coordinator(self) -> ChunkExtractionBatchCoordinator:
        """组装高内聚的 Chunk 抽取编排器。"""
        return ChunkExtractionBatchCoordinator(
            chunk_repo=self.chunk_repo,
            context_loader=self._load_preceding_context,
            max_attempts=GRAPH_EXTRACTION_MAX_ATTEMPTS,
            retry_delays_seconds=GRAPH_EXTRACTION_RETRY_DELAYS_SECONDS,
        )

    async def _load_preceding_context(self, chunk, extractor: GraphExtractor) -> list[dict[str, Any]]:
        """加载相邻前文并按字符预算裁剪，供跨 Chunk 抽取使用。"""
        options = getattr(extractor, "options", None)
        if options is None:
            return []

        if getattr(extractor, "extractor_type", "") == "lightrag_primary":
            enhancement_options = dict(options.get("llm_enhancement") or {})
            if not enhancement_options.get("enabled"):
                return []
            options = enhancement_options

        window_size = int(options.get("context_window_size", DEFAULT_CONTEXT_WINDOW_SIZE))
        if window_size <= 0 or int(chunk.chunk_index) <= 0:
            return []
        max_chars = int(options.get("context_max_chars", DEFAULT_CONTEXT_MAX_CHARS))
        chunks = await self.chunk_repo.list_preceding_chunks(
            chunk.file_id,
            int(chunk.chunk_index),
            window_size,
        )

        selected_reversed: list[dict[str, Any]] = []
        remaining = max_chars
        for context_chunk in reversed(chunks):
            if remaining <= 0:
                break
            content = str(context_chunk.content or "")
            if len(content) > remaining:
                content = content[-remaining:]
            if content:
                selected_reversed.append(
                    {
                        "chunk_id": context_chunk.chunk_id,
                        "chunk_index": context_chunk.chunk_index,
                        "content": content,
                    }
                )
                remaining -= len(content)

        return list(reversed(selected_reversed))

    def prepare_chunk_graph_records(
        self,
        kb_id: str,
        normalized_result: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """将抽取结果转换成权威记录与可重放图投影。"""
        graph_payload = build_graph_payload(normalized_result)
        entities = graph_payload["entities"]
        relations = graph_payload["relations"]
        entity_records = self._build_entity_records(kb_id, entities, graph_payload)
        entity_record_by_local_id = {
            entity["id"]: record for entity, record in zip(entities, entity_records, strict=True)
        }
        triple_records = self._build_triple_records(kb_id, relations, entity_record_by_local_id, graph_payload)
        return graph_payload, entity_records, triple_records

    async def _align_entity_records(
        self,
        *,
        kb_id: str,
        embedding_model_spec: str | None,
        entities: list[dict[str, Any]],
        triples: list[dict[str, Any]],
        llm_enhancer: LightRAGEntityAlignmentEnhancer | None = None,
    ) -> None:
        """组合精确对齐与可降级的语义候选消歧。"""
        align_records = getattr(self.graph_repo, "align_graph_records", None)
        if align_records is None:
            return
        exact_result = await align_records(kb_id=kb_id, entities=entities, triples=triples)
        unresolved = set(exact_result.get("unresolved_entity_ids") or [])
        exact_ambiguities = exact_result.get("ambiguous_candidates") or {}
        type_conflict_decisions = []
        if unresolved:
            try:
                type_conflict_decisions = await resolve_entity_type_conflicts(
                    kb_id=kb_id,
                    entities=entities,
                    unresolved_entity_ids=unresolved,
                    profile_loader=self.graph_repo,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"同名实体跨类型治理降级为原类型分配 kb_id={kb_id}: {exc}")
        if type_conflict_decisions and llm_enhancer is not None:
            type_conflict_decisions = await llm_enhancer.adjudicate_type_conflicts(
                entities=entities,
                triples=triples,
                decisions=type_conflict_decisions,
            )
        type_linked_incoming_ids = apply_entity_type_conflict_decisions(
            entities=entities,
            triples=triples,
            decisions=type_conflict_decisions,
        )
        unresolved -= type_linked_incoming_ids
        decisions = []
        if unresolved and embedding_model_spec:
            try:
                vector_store = await self.get_graph_vector_store()
                decisions = await resolve_semantic_entity_alignments(
                    kb_id=kb_id,
                    embedding_model_spec=embedding_model_spec,
                    entities=entities,
                    triples=triples,
                    unresolved_entity_ids=unresolved,
                    searcher=vector_store,
                    profile_loader=self.graph_repo,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"实体语义对齐降级为精确匹配 kb_id={kb_id}: {exc}")
        if decisions and llm_enhancer is not None:
            decisions = await llm_enhancer.adjudicate(
                entities=entities,
                triples=triples,
                decisions=decisions,
            )
        apply_entity_alignment_decisions(
            entities=entities,
            triples=triples,
            decisions=decisions,
            exact_ambiguities=exact_ambiguities,
        )
        linked_incoming_ids = {decision.incoming_entity_id for decision in decisions if decision.status == "linked"}
        provisional_ids = unresolved - linked_incoming_ids
        allocate_entity_ids = getattr(self.graph_repo, "allocate_entity_ids", None)
        allocated = {}
        if allocate_entity_ids is not None and provisional_ids:
            allocated = await allocate_entity_ids(
                kb_id=kb_id,
                entities=entities,
                triples=triples,
                provisional_entity_ids=provisional_ids,
            )
        if type_linked_incoming_ids or linked_incoming_ids or allocated:
            await align_records(kb_id=kb_id, entities=entities, triples=triples)

    def project_chunk_graph(
        self,
        kb_id: str,
        chunk,
        graph_payload: dict[str, Any],
        entity_records: list[dict[str, Any]],
        triple_records: list[dict[str, Any]],
    ) -> None:
        """把 PostgreSQL 已提交的权威记录投影到 Neo4j。"""
        label = safe_neo4j_label(kb_id)
        relation_extractor_type = graph_payload["metadata"].get("extractor_type", "unknown")
        entities = graph_payload["entities"]
        relations = graph_payload["relations"]
        entity_record_by_local_id = {
            entity["id"]: record for entity, record in zip(entities, entity_records, strict=True)
        }
        triple_record_by_key = {
            (record["source_entity_id"], record["target_entity_id"], record["relation_type"]): record
            for record in triple_records
        }
        triple_record_by_id = {str(record["triple_id"]): record for record in triple_records}
        content_preview = str(getattr(chunk, "content_preview", None) or getattr(chunk, "content", ""))[:300]

        # 预构建 Cypher 模板（同一 chunk 内复用）
        merge_chunk_cypher = cypher_merge_chunk(label)
        merge_entity_cypher = cypher_merge_entity_mention(label)
        merge_relation_cypher = cypher_merge_relation(label)

        def query(tx):
            # 1. MERGE Chunk 节点
            tx.run(
                merge_chunk_cypher,
                chunk_id=chunk.chunk_id,
                file_id=chunk.file_id,
                kb_id=kb_id,
                chunk_index=chunk.chunk_index,
                content_preview=content_preview,
                start_char_pos=chunk.start_char_pos,
                end_char_pos=chunk.end_char_pos,
                document_version=int(getattr(chunk, "document_version", None) or 1),
                page_number=getattr(chunk, "page_number", None),
                block_type=getattr(chunk, "block_type", None),
                heading_path=getattr(chunk, "heading_path", None) or [],
                bbox=getattr(chunk, "bbox", None),
                parser_name=getattr(chunk, "parser_name", None),
                parser_version=getattr(chunk, "parser_version", None),
            )

            # 2. MERGE Entity 节点 + Chunk→Entity (MENTIONS)
            for entity in entities:
                entity_record = entity_record_by_local_id[entity["id"]]
                tx.run(
                    merge_entity_cypher,
                    chunk_id=chunk.chunk_id,
                    file_id=chunk.file_id,
                    kb_id=kb_id,
                    entity_id=entity_record["entity_id"],
                    normalized_name=entity_record["normalized_name"],
                    entity_label=entity_record["label"],
                    name=entity_record["name"],
                    attributes=json.dumps(entity.get("attributes") or [], ensure_ascii=False),
                    lifecycle_status=entity_record.get("lifecycle_status") or "active",
                    superseded_by_entity_id=entity_record.get("superseded_by_entity_id"),
                    entity_version=int(entity_record.get("entity_version") or 1),
                    review_status=entity_record.get("review_status") or "pending",
                    confidence=entity_record.get("confidence"),
                    start_char=entity_record.get("start_char"),
                    end_char=entity_record.get("end_char"),
                    model_version=entity_record.get("model_version"),
                    ontology_version=entity_record.get("ontology_version"),
                    has_mention=bool(entity_record.get("has_mention", True)),
                )

            # 3. MERGE Entity→Entity (RELATION) 边
            for relation in relations:
                source_record = entity_record_by_local_id[relation["source"]]
                target_record = entity_record_by_local_id[relation["target"]]
                relation_type = relation.get("label") or "RELATED_TO"
                triple_record = triple_record_by_id.get(str(relation.get("triple_id") or ""))
                if triple_record is None:
                    triple_record = triple_record_by_key.get(
                        (source_record["entity_id"], target_record["entity_id"], relation_type)
                    )
                if triple_record is None:
                    raise ValueError(f"投影关系缺少权威三元组记录: {relation_type}")
                tx.run(
                    merge_relation_cypher,
                    kb_id=kb_id,
                    chunk_id=chunk.chunk_id,
                    file_id=chunk.file_id,
                    source_name=source_record["normalized_name"],
                    source_label=source_record["label"],
                    source_entity_id=source_record["entity_id"],
                    target_name=target_record["normalized_name"],
                    target_label=target_record["label"],
                    target_entity_id=target_record["entity_id"],
                    relation_type=relation_type,
                    triple_id=triple_record["triple_id"],
                    text=relation["text"],
                    extractor_type=relation.get("extractor_type") or relation_extractor_type,
                    claim_level=relation.get("claim_level") or "Inference",
                    confidence=float(relation.get("confidence") or 0.0),
                    evidence_quote=relation.get("evidence_quote") or "",
                    reasoning_basis=relation.get("reasoning_basis") or "",
                    applicable_conditions=relation.get("applicable_conditions") or [],
                    secondary_review_verdict=str((triple_record.get("secondary_review") or {}).get("verdict") or ""),
                    secondary_review_basis=str((triple_record.get("secondary_review") or {}).get("basis") or ""),
                    secondary_review_revision=str((triple_record.get("secondary_review") or {}).get("revision") or ""),
                    military_value_dimensions=relation.get("military_value_dimensions") or [],
                    expected_capability_gain=relation.get("expected_capability_gain") or "",
                    application_direction=relation.get("application_direction") or "",
                    uncertainty=relation.get("uncertainty") or "",
                    expert_review_required=bool(relation.get("expert_review_required")),
                    review_status=triple_record.get("review_status") or "pending",
                    model_version=triple_record.get("model_version"),
                    ontology_version=triple_record.get("ontology_version"),
                    pipeline_revision=triple_record.get("pipeline_revision"),
                    lifecycle_status=triple_record.get("lifecycle_status") or "active",
                    superseded_by_triple_id=triple_record.get("superseded_by_triple_id"),
                    relation_version=int(triple_record.get("relation_version") or 1),
                )

        neo4j_write(self.driver, query)

    def project_projection_payload(self, payload: dict[str, Any]) -> None:
        """校验并重放一条持久化 Neo4j 投影事件。"""
        if payload.get("event_type") == "review_status":
            self._project_review_status(ReviewStatusProjectionPayload.model_validate(payload))
            return
        if payload.get("event_type") == "entity_redirect":
            self._project_entity_redirect(EntityRedirectProjectionPayload.model_validate(payload))
            return
        if payload.get("event_type") == "relation_lifecycle":
            self._project_relation_lifecycle(RelationLifecycleProjectionPayload.model_validate(payload))
            return
        projection = GraphProjectionPayload.model_validate(payload)
        self.project_chunk_graph(
            projection.kb_id,
            projection.chunk,
            projection.graph_payload,
            projection.entity_records,
            projection.triple_records,
        )

    def _project_review_status(self, projection: ReviewStatusProjectionPayload) -> None:
        """把已提交的人工审核状态更新到 Neo4j 投影边。"""
        label = safe_neo4j_label(projection.kb_id)

        def query(tx):
            if projection.target_type == "entity_mention":
                result = tx.run(
                    f"""
                    MATCH (:Chunk:MilvusKB:`{label}` {{chunk_id: $chunk_id}})
                        -[m:MENTIONS]->
                        (:Entity:MilvusKB:`{label}` {{entity_id: $entity_id}})
                    SET m.review_status = $review_status,
                        m.review_decision_id = $decision_id
                    RETURN count(m) AS updated
                    """,
                    chunk_id=projection.chunk_id,
                    entity_id=projection.entity_id,
                    review_status=projection.review_status,
                    decision_id=projection.decision_id,
                ).single()
            else:
                result = tx.run(
                    f"""
                    MATCH (:Entity:MilvusKB:`{label}`)
                        -[r:RELATION {{chunk_id: $chunk_id, triple_id: $triple_id}}]->
                        (:Entity:MilvusKB:`{label}`)
                    SET r.review_status = $review_status,
                        r.review_decision_id = $decision_id
                    RETURN count(r) AS updated
                    """,
                    chunk_id=projection.chunk_id,
                    triple_id=projection.triple_id,
                    review_status=projection.review_status,
                    decision_id=projection.decision_id,
                ).single()
            if result is None or int(result["updated"] or 0) != 1:
                raise ValueError(f"审核投影未唯一命中 target={projection.target_type} chunk_id={projection.chunk_id}")

        neo4j_write(self.driver, query)

    def _project_entity_redirect(self, projection: EntityRedirectProjectionPayload) -> None:
        """把实体生命周期和 merge/split redirect 投影到 Neo4j。"""
        label = safe_neo4j_label(projection.kb_id)

        def query(tx):
            result = tx.run(
                f"""
                MATCH (source:Entity:MilvusKB:`{label}` {{entity_id: $source_entity_id}})
                SET source.lifecycle_status = $lifecycle_status,
                    source.superseded_by_entity_id = $primary_target_entity_id,
                    source.redirect_id = $redirect_id
                WITH source
                UNWIND $target_entity_ids AS target_entity_id
                MATCH (target:Entity:MilvusKB:`{label}` {{entity_id: target_entity_id}})
                MERGE (source)-[redirect:ENTITY_REDIRECT {{redirect_id: $redirect_id}}]->(target)
                SET redirect.operation = $operation,
                    redirect.reason = $reason,
                    redirect.governance_edge = true
                RETURN count(redirect) AS updated
                """,
                source_entity_id=projection.source_entity_id,
                target_entity_ids=projection.target_entity_ids,
                primary_target_entity_id=projection.target_entity_ids[0],
                lifecycle_status="redirected" if projection.operation == "merge" else "split",
                redirect_id=projection.redirect_id,
                operation=projection.operation,
                reason=projection.reason,
            ).single()
            if result is None or int(result["updated"] or 0) != len(projection.target_entity_ids):
                raise ValueError(
                    f"实体 redirect 投影未完整命中 source={projection.source_entity_id} "
                    f"targets={len(projection.target_entity_ids)}"
                )

        neo4j_write(self.driver, query)

    def _project_relation_lifecycle(self, projection: RelationLifecycleProjectionPayload) -> None:
        """把关系失效或替代状态投影到全部对应 Neo4j 关系 mention。"""
        label = safe_neo4j_label(projection.kb_id)

        def query(tx):
            result = tx.run(
                f"""
                MATCH (:Entity:MilvusKB:`{label}`)
                    -[relation:RELATION {{triple_id: $triple_id}}]->
                    (:Entity:MilvusKB:`{label}`)
                SET relation.lifecycle_status = $lifecycle_status,
                    relation.superseded_by_triple_id = $superseded_by_triple_id,
                    relation.relation_version = $relation_version,
                    relation.valid_to = $valid_to,
                    relation.lifecycle_reason = $reason
                RETURN count(relation) AS updated
                """,
                triple_id=projection.triple_id,
                lifecycle_status=projection.lifecycle_status,
                superseded_by_triple_id=projection.superseded_by_triple_id,
                relation_version=projection.relation_version,
                valid_to=projection.valid_to,
                reason=projection.reason,
            ).single()
            if result is None or int(result["updated"] or 0) < 1:
                raise ValueError(f"关系生命周期投影未命中 triple_id={projection.triple_id}")

        neo4j_write(self.driver, query)

    async def replay_projection_outbox(self, kb_id: str | None, *, limit: int = 20) -> dict[str, int]:
        """领取并重放待处理投影；空知识库范围供后台消费者使用。"""
        token, events = await self.graph_repo.claim_projection_events(
            kb_id=kb_id,
            limit=limit,
            lease_seconds=GRAPH_VECTOR_LEASE_SECONDS,
        )
        completed = 0
        failed = 0
        vector_refresh_kb_ids: set[str] = set()
        for event in events:
            try:
                await asyncio.to_thread(self.project_projection_payload, event["payload"])
                event_type = event["payload"].get("event_type")
                if event_type == "relation_lifecycle":
                    projection = RelationLifecycleProjectionPayload.model_validate(event["payload"])
                    vector_store = await self.get_graph_vector_store()
                    await vector_store.delete_graph_records(
                        projection.kb_id,
                        entity_ids=[],
                        triple_ids=[projection.triple_id],
                    )
                elif event_type == "entity_redirect":
                    projection = EntityRedirectProjectionPayload.model_validate(event["payload"])
                    vector_store = await self.get_graph_vector_store()
                    await vector_store.delete_graph_records(
                        projection.kb_id,
                        entity_ids=[projection.source_entity_id],
                        triple_ids=[],
                    )
                elif event_type == "review_status":
                    projection = ReviewStatusProjectionPayload.model_validate(event["payload"])
                    if projection.target_type == "relation_mention" and projection.review_status != "accepted":
                        vector_store = await self.get_graph_vector_store()
                        await vector_store.delete_graph_records(
                            projection.kb_id,
                            entity_ids=[],
                            triple_ids=[str(projection.triple_id)],
                        )
                await self.graph_repo.mark_projection_event_completed(
                    event_id=event["event_id"],
                    lock_token=token,
                )
                vector_refresh_kb_ids.add(str(event["kb_id"]))
                completed += 1
            except Exception as exc:
                await self.graph_repo.mark_projection_event_failed(
                    event_id=event["event_id"],
                    lock_token=token,
                    error=str(exc),
                )
                failed += 1
                logger.error(f"图谱投影重放失败 kb_id={event['kb_id']} event_id={event['event_id']}: {exc}")
        for refresh_kb_id in sorted(vector_refresh_kb_ids):
            try:
                await self.index_pending_graph_vectors(refresh_kb_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"审核投影后的图向量刷新失败 kb_id={refresh_kb_id}: {exc}")
        return {"claimed": len(events), "completed": completed, "failed": failed}

    def write_chunk_graph(
        self,
        kb_id: str,
        chunk,
        normalized_result: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """兼容旧调用：准备记录并立即投影；新流水线先提交 PostgreSQL。"""
        graph_payload, entity_records, triple_records = self.prepare_chunk_graph_records(kb_id, normalized_result)
        self.project_chunk_graph(kb_id, chunk, graph_payload, entity_records, triple_records)
        return entity_records, triple_records

    def _build_entity_records(
        self,
        kb_id: str,
        entities: list[dict[str, Any]],
        graph_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        records = []
        metadata = graph_payload["metadata"]
        for entity in entities:
            label = entity.get("label") or "Entity"
            mention_text = str(entity["text"])
            naming = resolve_entity_naming(
                mention_text,
                canonical_name=entity.get("canonical_name"),
                aliases=entity.get("aliases"),
                naming_rationale=entity.get("naming_rationale"),
            )
            canonical_name = naming["canonical_name"]
            normalized_name = normalize_entity_name(canonical_name)
            entity_id = new_entity_uuid(kb_id, normalized_name, label)
            semantic_role = core_role_for_entity_type(label) or "other"
            content_parts = [
                f"实体名称：{canonical_name}",
                f"实体类型：{label}",
                f"语义角色：{semantic_role}",
            ]
            if naming["aliases"]:
                content_parts.append(f"别名：{'、'.join(naming['aliases'][:12])}")
            if naming["naming_rationale"]:
                content_parts.append(f"命名依据：{naming['naming_rationale']}")
            attributes = entity.get("attributes") or []
            attribute_text = [
                f"{item.get('label') or '属性'}={item.get('text')}"
                for item in attributes[:12]
                if isinstance(item, dict) and item.get("text")
            ]
            if attribute_text:
                content_parts.append(f"实体属性：{'、'.join(attribute_text)}")
            records.append(
                {
                    "entity_id": entity_id,
                    "kb_id": kb_id,
                    "normalized_name": normalized_name,
                    "label": label,
                    "name": canonical_name,
                    "attributes": entity.get("attributes") or [],
                    "content": "；".join(content_parts)[:8000],
                    "mention_text": mention_text,
                    "aliases": naming["aliases"],
                    "naming_rationale": naming["naming_rationale"],
                    "start_char": entity.get("start"),
                    "end_char": entity.get("end"),
                    "confidence": entity.get("confidence"),
                    "model_version": metadata.get("model_version") or metadata.get("primary_model_version"),
                    "ontology_version": metadata.get("ontology_version"),
                    "review_status": entity.get("review_status") or "pending",
                }
            )
        return records

    def _build_triple_records(
        self,
        kb_id: str,
        relations: list[dict[str, Any]],
        entity_record_by_local_id: dict[str, dict[str, Any]],
        graph_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        records = []
        seen_triple_ids: set[str] = set()
        extractor_type = graph_payload["metadata"].get("extractor_type", "unknown")
        for relation in relations:
            source_record = entity_record_by_local_id[relation["source"]]
            target_record = entity_record_by_local_id[relation["target"]]
            relation_type = relation.get("label") or "RELATED_TO"
            triple_id = relation_uuid(
                kb_id,
                source_record["entity_id"],
                relation_type,
                target_record["entity_id"],
            )
            if triple_id in seen_triple_ids:
                continue
            seen_triple_ids.add(triple_id)
            claim_level = relation.get("claim_level") or "Inference"
            content_parts = [
                f"{source_record['normalized_name']} → {relation_type} → {target_record['normalized_name']}",
                (
                    f"源实体：{source_record['name']}；类型：{source_record['label']}；"
                    f"角色：{core_role_for_entity_type(source_record['label']) or 'other'}"
                ),
                (
                    f"目标实体：{target_record['name']}；类型：{target_record['label']}；"
                    f"角色：{core_role_for_entity_type(target_record['label']) or 'other'}"
                ),
            ]
            relation_text = str(relation.get("text") or "").strip()
            if relation_text:
                content_parts.append(f"关系语义：{relation_text}")
            if relation.get("reasoning_basis"):
                content_parts.append(f"关系依据：{relation['reasoning_basis']}")
            dimensions = relation.get("military_value_dimensions") or []
            if dimensions:
                content_parts.append(f"军事价值维度：{'、'.join(dimensions)}")
            if relation.get("expected_capability_gain"):
                content_parts.append(f"预期能力收益：{relation['expected_capability_gain']}")
            if relation.get("application_direction"):
                content_parts.append(f"应用方向：{relation['application_direction']}")
            if relation.get("applicable_conditions"):
                content_parts.append(f"适用条件：{'、'.join(relation['applicable_conditions'])}")
            if claim_level == "Hypothesis":
                content_parts.append("探索性假设，需专家复核，不作为事实")
            content = "；".join(content_parts)[:12000]
            secondary_review = relation.get("secondary_review") or None
            records.append(
                {
                    "triple_id": triple_id,
                    "kb_id": kb_id,
                    "source_entity_id": source_record["entity_id"],
                    "target_entity_id": target_record["entity_id"],
                    "relation_type": relation_type,
                    "content": content,
                    "text": relation["text"],
                    "extractor_type": extractor_type,
                    "claim_level": claim_level,
                    "confidence": float(relation.get("confidence") or 0.0),
                    "evidence_quote": relation.get("evidence_quote") or "",
                    "evidence_spans": relation.get("evidence_spans") or [],
                    "reasoning_basis": relation.get("reasoning_basis") or "",
                    "applicable_conditions": relation.get("applicable_conditions") or [],
                    "secondary_review": secondary_review,
                    "uncertainty": relation.get("uncertainty") or "",
                    "expert_review_required": bool(relation.get("expert_review_required")),
                    "review_status": relation.get("review_status") or "pending",
                    "model_version": graph_payload["metadata"].get("model_version")
                    or graph_payload["metadata"].get("primary_model_version"),
                    "ontology_version": graph_payload["metadata"].get("ontology_version"),
                    "pipeline_revision": graph_payload["metadata"].get("pipeline_revision"),
                    "lifecycle_status": "active",
                    "superseded_by_triple_id": None,
                    "relation_version": 1,
                }
            )
        return records

    async def reset(self, kb_id: str, *, clear_extraction_result: bool, clear_config: bool) -> dict[str, Any]:
        kb = await self._get_milvus_kb(kb_id)
        await asyncio.to_thread(self.delete_graph, kb_id)
        await self.graph_repo.delete_by_kb_id(kb_id)
        reset_chunks = await self.chunk_repo.reset_graph_state_by_kb_id(kb_id, clear_extraction_result)
        if clear_config:
            additional_params = dict(kb.additional_params or {})
            additional_params.pop(GRAPH_CONFIG_KEY, None)
            await self.kb_repo.update(kb_id, {"additional_params": additional_params})
        return {
            "message": "图谱构建状态已重置",
            "status": "success",
            "reset_chunks": reset_chunks,
            "clear_extraction_result": clear_extraction_result,
            "clear_config": clear_config,
        }

    async def reconcile_vectors(self, kb_id: str, *, all_vectors: bool) -> dict[str, Any]:
        await self._get_milvus_kb(kb_id)
        reset_records = await self.graph_repo.reconcile_vector_records(kb_id, all_vectors=all_vectors)
        if all_vectors:
            graph_vector_store = await self.get_graph_vector_store()
            await asyncio.to_thread(graph_vector_store.drop_graph_collections, kb_id)
        return {
            "kb_id": kb_id,
            "mode": "all_vectors" if all_vectors else "failed",
            "reset_records": reset_records,
        }

    def delete_graph(self, kb_id: str) -> None:
        label = safe_neo4j_label(kb_id)

        def query(tx):
            tx.run(f"MATCH (n:MilvusKB:`{label}`) DETACH DELETE n")

        neo4j_write(self.driver, query)
        self.graph_vector_store.drop_graph_collections(kb_id)

    async def delete_file_graph(self, kb_id: str, file_id: str) -> None:
        orphan_entity_ids, orphan_triple_ids = await self.graph_repo.delete_file_references(file_id)
        await self.graph_vector_store.delete_graph_records(
            kb_id,
            entity_ids=orphan_entity_ids,
            triple_ids=orphan_triple_ids,
        )
        await asyncio.to_thread(self._delete_file_graph_from_neo4j, kb_id, file_id)

    def _delete_file_graph_from_neo4j(self, kb_id: str, file_id: str) -> None:
        label = safe_neo4j_label(kb_id)

        def query(tx):
            tx.run(
                f"""
                MATCH (:Entity:MilvusKB:`{label}`)-[r:RELATION {{kb_id: $kb_id, file_id: $file_id}}]->
                    (:Entity:MilvusKB:`{label}`)
                DELETE r
                """,
                kb_id=kb_id,
                file_id=file_id,
            )
            tx.run(
                f"""
                MATCH (:Chunk:MilvusKB:`{label}` {{kb_id: $kb_id, file_id: $file_id}})-[m:MENTIONS]->
                    (e:Entity:MilvusKB:`{label}`)
                DELETE m
                WITH DISTINCT e
                WHERE NOT ()-[:MENTIONS]->(e)
                DETACH DELETE e
                """,
                kb_id=kb_id,
                file_id=file_id,
            )
            tx.run(
                f"""
                MATCH (c:Chunk:MilvusKB:`{label}` {{kb_id: $kb_id, file_id: $file_id}})
                DETACH DELETE c
                """,
                kb_id=kb_id,
                file_id=file_id,
            )

        neo4j_write(self.driver, query)

    async def query_nodes(
        self,
        kb_id: str | None = None,
        *,
        keyword: str = "",
        max_depth: int = 1,
        max_nodes: int = 50,
        exclude_chunk: bool = False,
        review_scope: str = GRAPH_REVIEW_SCOPE_ALL,
    ) -> dict[str, Any]:
        effective_kb_id = kb_id or self.kb_id
        if not effective_kb_id:
            return {"nodes": [], "edges": []}

        label = safe_neo4j_label(effective_kb_id)
        limit = max_nodes
        review_scope = self._normalize_review_scope(review_scope)
        try:
            return await _run_neo4j_query_io(
                self._query_nodes_sync,
                effective_kb_id,
                label,
                keyword,
                limit,
                max_depth,
                exclude_chunk,
                review_scope,
            )
        except Exception as e:
            logger.error(f"Milvus graph query failed: {e}")
            return {"nodes": [], "edges": []}

    async def discover_paths(
        self,
        kb_id: str | None = None,
        *,
        query: str,
        mode: str = "auto",
        max_hops: int = 5,
        max_paths: int = 10,
        include_combinations: bool = True,
        retrieval_mode: str = "mix",
        review_scope: str = GRAPH_REVIEW_SCOPE_ALL,
        query_enhancement: dict[str, Any] | None = None,
        path_reranking: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """从语义锚点出发发现有证据、可解释的研发知识链路。"""
        effective_kb_id = kb_id or self.kb_id
        query = query.strip()
        if not effective_kb_id or not query:
            return {"query": query, "mode": mode, "paths": [], "summary": {"returned_path_count": 0}}

        max_hops = max(1, min(int(max_hops), 6))
        max_paths = max(1, min(int(max_paths), 10))
        review_scope = self._normalize_review_scope(review_scope)
        path_reranking = dict(path_reranking or {})
        candidate_path_limit = min(max_paths * 3, 30) if path_reranking.get("enabled") else max_paths
        requested_retrieval_mode = normalize_retrieval_mode(retrieval_mode)
        planner = self._query_planner_factory(query_enhancement or {})
        try:
            query_plan = await planner.plan(query)
        finally:
            await planner.aclose()
        local_query, global_query = retrieval_queries(query_plan)
        keyword_queries = graph_keyword_queries(query_plan)
        kb = await self._get_milvus_kb(effective_kb_id)
        graph = {"nodes": [], "edges": []}
        entity_hits: list[dict[str, Any]] = []
        triple_hits: list[dict[str, Any]] = []
        chunk_hits: list[dict[str, Any]] = []
        chunk_entity_hits: list[dict[str, Any]] = []
        fusion = {
            "entity_ids": [],
            "relevance_by_entity_id": {},
            "sources_by_entity_id": {},
            "fusion_method": "none",
        }
        retrieval_mode = "keyword"
        keyword_graph = {"nodes": [], "edges": []}
        keyword_entity_hits: list[dict[str, Any]] = []
        retrieval_failures: list[dict[str, str]] = []
        if kb.embedding_model_spec:
            try:
                vector_store = await self.get_graph_vector_store()
                search_requests: list[tuple[str, Any]] = []
                if requested_retrieval_mode in {"local", "hybrid", "mix"}:
                    search_requests.append(
                        (
                            "entity",
                            vector_store.search_entities(
                                kb_id=effective_kb_id,
                                query_text=local_query,
                                embedding_model_spec=kb.embedding_model_spec,
                                top_k=6,
                            ),
                        )
                    )
                if requested_retrieval_mode in {"global", "hybrid", "mix"}:
                    search_requests.append(
                        (
                            "triple",
                            vector_store.search_triples(
                                kb_id=effective_kb_id,
                                query_text=global_query,
                                embedding_model_spec=kb.embedding_model_spec,
                                top_k=6,
                            ),
                        )
                    )
                if requested_retrieval_mode in {"naive", "mix"} and self._chunk_retriever is not None:
                    search_requests.append(
                        (
                            "chunk",
                            self._retrieve_mix_chunk_anchors(
                                kb_id=effective_kb_id,
                                query=query,
                                top_k=6,
                                review_scope=review_scope,
                            ),
                        )
                    )
                if requested_retrieval_mode == "mix":
                    search_requests.append(
                        (
                            "keyword",
                            self._query_planned_keyword_graph(
                                effective_kb_id,
                                keywords=keyword_queries,
                                max_depth=min(max_hops, 3),
                                max_nodes=300,
                                exclude_chunk=True,
                                review_scope=review_scope,
                            ),
                        )
                    )
                search_results = await asyncio.gather(
                    *(search for _channel, search in search_requests), return_exceptions=True
                )
                for (channel, _search), search_result in zip(search_requests, search_results, strict=True):
                    if isinstance(search_result, asyncio.CancelledError):
                        raise search_result
                    if isinstance(search_result, Exception):
                        retrieval_failures.append({"channel": channel, "failure_type": type(search_result).__name__})
                        logger.warning(
                            f"Graph {channel} vector anchoring failed for {effective_kb_id}: {search_result}"
                        )
                    elif channel == "entity":
                        entity_hits = search_result
                    elif channel == "triple":
                        triple_hits = search_result
                    elif channel == "chunk":
                        chunk_hits = search_result["chunk_hits"]
                        chunk_entity_hits = search_result["entity_hits"]
                    else:
                        keyword_graph = search_result
                keyword_entity_hits = graph_keyword_entity_hits(keyword_graph, keyword_queries)
                fusion = reciprocal_rank_fuse_graph_hits(
                    entity_hits,
                    triple_hits,
                    chunk_entity_hits,
                    keyword_entity_hits,
                )
                if fusion["entity_ids"]:
                    graph = await self.query_seed_subgraph(
                        effective_kb_id,
                        entity_ids=fusion["entity_ids"],
                        max_nodes=300,
                        max_depth=max_hops,
                        entity_only=True,
                    )
                    if requested_retrieval_mode == "naive" and chunk_hits:
                        retrieval_mode = "naive"
                    elif entity_hits and triple_hits:
                        retrieval_mode = "hybrid"
                    elif triple_hits:
                        retrieval_mode = "global"
                    else:
                        retrieval_mode = "local"
            except Exception as exc:  # noqa: BLE001
                retrieval_failures.append({"channel": "vector_store", "failure_type": type(exc).__name__})
                logger.warning(f"Graph path semantic anchoring failed for {effective_kb_id}: {exc}")

        if requested_retrieval_mode == "mix":
            if not keyword_graph.get("nodes"):
                keyword_graph = await self._query_planned_keyword_graph(
                    effective_kb_id,
                    keywords=keyword_queries,
                    max_depth=min(max_hops, 3),
                    max_nodes=300,
                    exclude_chunk=True,
                    review_scope=review_scope,
                )
            graph = merge_graph_subgraphs(graph, keyword_graph)
            if graph.get("nodes"):
                retrieval_mode = "mix"

        if not graph.get("nodes"):
            if not keyword_graph.get("nodes"):
                keyword_graph = await self._query_planned_keyword_graph(
                    effective_kb_id,
                    keywords=keyword_queries,
                    max_depth=min(max_hops, 3),
                    max_nodes=300,
                    exclude_chunk=True,
                    review_scope=review_scope,
                )
            graph = keyword_graph
            retrieval_mode = "keyword"

        keyword_entity_hits = graph_keyword_entity_hits(keyword_graph, keyword_queries)
        fusion = reciprocal_rank_fuse_graph_hits(
            entity_hits,
            triple_hits,
            chunk_entity_hits,
            keyword_entity_hits,
        )
        for node in graph.get("nodes") or []:
            properties = dict(node.get("properties") or {})
            entity_id = properties.get("entity_id")
            if entity_id in fusion["relevance_by_entity_id"]:
                properties["query_relevance"] = fusion["relevance_by_entity_id"][entity_id]
                properties["query_retrieval_sources"] = fusion["sources_by_entity_id"].get(entity_id, [])
                node["properties"] = properties

        result = discover_graph_paths(
            graph,
            query,
            PathQueryOptions(
                mode=mode,
                max_hops=max_hops,
                max_paths=candidate_path_limit,
                include_combinations=include_combinations,
            ),
        )
        candidate_path_count = len(result.get("paths") or [])
        reranker = self._path_reranker_factory(path_reranking)
        try:
            reranking = await reranker.rerank(
                query=query,
                mode=str(result.get("mode") or mode),
                paths=result.get("paths") or [],
            )
        finally:
            await reranker.aclose()
        result["paths"] = reranking["paths"][:max_paths]
        result["path_reranking"] = reranking["provenance"]
        result["summary"]["returned_path_count"] = len(result["paths"])
        result["summary"]["path_reranker_status"] = reranking["provenance"]["status"]
        result["summary"]["path_reranker_version"] = reranking["provenance"]["reranker_version"]
        result["summary"]["retrieval_mode"] = retrieval_mode
        result["summary"]["requested_retrieval_mode"] = requested_retrieval_mode
        result["summary"]["entity_hit_count"] = len(entity_hits)
        result["summary"]["triple_hit_count"] = len(triple_hits)
        result["summary"]["relationship_vector_hit_count"] = len(triple_hits)
        result["summary"]["chunk_hit_count"] = len(chunk_hits)
        result["summary"]["chunk_anchor_entity_count"] = len(chunk_entity_hits)
        result["summary"]["fusion_method"] = fusion["fusion_method"]
        result["summary"]["retrieval_degraded"] = bool(retrieval_failures)
        result["summary"]["retrieval_failures"] = retrieval_failures
        result["summary"]["query_planner_status"] = query_plan["provenance"]["status"]
        result["summary"]["subgraph_node_count"] = len(graph.get("nodes") or [])
        result["summary"]["subgraph_edge_count"] = len(graph.get("edges") or [])
        result["summary"]["review_scope"] = review_scope
        result["summary"]["keyword_query_count"] = len(keyword_queries)
        result["summary"]["keyword_entity_hit_count"] = len(keyword_entity_hits)
        result["summary"]["pending_evidence_path_count"] = sum(
            bool(path.get("pending_evidence")) for path in result["paths"]
        )
        result["query_plan"] = query_plan
        normalized_original_query = normalize_entity_name(query)
        explicit_query_anchor_hits = [
            hit
            for hit in keyword_entity_hits
            if normalize_entity_name(str(hit["keyword"])) in normalized_original_query
            or normalize_entity_name(str(hit["name"])) in normalized_original_query
        ]
        result["query_anchors"] = [
            {
                **dict(hit["node"]),
                "semantic_role": core_role_for_entity_type(str(hit["node"].get("type") or "")) or "other",
                "matched_keyword": hit["keyword"],
            }
            for hit in explicit_query_anchor_hits
        ]
        result["summary"]["explicit_query_anchor_count"] = len(explicit_query_anchor_hits)
        discovery_mode = "top_down" if result.get("mode") == "requirement_driven" else "bottom_up"
        result["query_analysis"] = analyze_requirement_query(
            query,
            result,
            discovery_mode=discovery_mode,
        )
        result["pipeline_trace"] = build_query_pipeline_trace(
            requested_retrieval_mode=requested_retrieval_mode,
            query_plan=query_plan,
            entity_hits=entity_hits,
            triple_hits=triple_hits,
            chunk_hits=chunk_hits,
            fusion=fusion,
            retrieval_failures=retrieval_failures,
            subgraph_node_count=len(graph.get("nodes") or []),
            subgraph_edge_count=len(graph.get("edges") or []),
            candidate_path_count=candidate_path_count,
            returned_path_count=len(result["paths"]),
            reranking=reranking,
            semantic_retrieval_available=bool(kb.embedding_model_spec),
            chunk_retrieval_available=bool(kb.embedding_model_spec and self._chunk_retriever is not None),
        )
        return result

    async def _query_planned_keyword_graph(
        self,
        kb_id: str,
        *,
        keywords: list[str],
        max_depth: int,
        max_nodes: int,
        exclude_chunk: bool,
        review_scope: str,
    ) -> dict[str, Any]:
        """并行检索短实体词，避免把整句需求作为唯一 CONTAINS 条件。"""
        bounded_keywords = list(dict.fromkeys(item.strip() for item in keywords if item.strip()))[:8]
        if not bounded_keywords:
            return {"nodes": [], "edges": []}
        per_term_limit = max(20, max_nodes // len(bounded_keywords))
        query_options: dict[str, Any] = {}
        if review_scope != GRAPH_REVIEW_SCOPE_ALL:
            query_options["review_scope"] = review_scope
        subgraphs = await asyncio.gather(
            *(
                self.query_nodes(
                    kb_id,
                    keyword=keyword,
                    max_depth=max_depth,
                    max_nodes=per_term_limit,
                    exclude_chunk=exclude_chunk,
                    **query_options,
                )
                for keyword in bounded_keywords
            )
        )
        return merge_graph_subgraphs(*subgraphs)

    async def _retrieve_mix_chunk_anchors(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int,
        review_scope: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """把 Chunk 语义命中转换为统一关系图的实体锚点。"""
        chunks = await self._chunk_retriever(kb_id=kb_id, query=query, top_k=top_k)
        chunk_hits = [item for item in chunks if isinstance(item, dict)]
        chunk_ids = [str((item.get("metadata") or {}).get("chunk_id") or "").strip() for item in chunk_hits]
        chunk_ids = [item for item in chunk_ids if item]
        accepted = await self.graph_repo.list_entity_ids_by_chunk_ids(
            kb_id=kb_id,
            chunk_ids=chunk_ids,
            review_statuses=("accepted", "pending"),
        )
        entity_hits = []
        seen = set()
        maximum_rank = max((len(accepted.get(chunk_id, [])) for chunk_id in chunk_ids), default=0)
        for rank in range(maximum_rank):
            for chunk_id in chunk_ids:
                values = accepted.get(chunk_id, [])
                if rank >= len(values):
                    continue
                entity_id = values[rank]
                normalized = str(entity_id or "").strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                entity_hits.append({"id": normalized, "chunk_id": chunk_id, "chunk_rank": rank + 1})
                if len(entity_hits) >= GRAPH_MIX_MAX_CHUNK_ENTITY_ANCHORS:
                    return {"chunk_hits": chunk_hits, "entity_hits": entity_hits}
        return {"chunk_hits": chunk_hits, "entity_hits": entity_hits}

    def _query_nodes_sync(
        self,
        kb_id: str,
        label: str,
        keyword: str,
        limit: int,
        max_depth: int,
        exclude_chunk: bool,
        review_scope: str = GRAPH_REVIEW_SCOPE_ALL,
    ) -> dict[str, Any]:
        with self.driver.session() as session:
            query_params: dict[str, Any] = {
                "keyword": keyword,
                "limit": limit,
            }
            if max_depth > 0:
                max_depth = min(max_depth, 3)
                query_params["path_limit"] = max(limit, 1) * 10
            result = session.run(
                self._build_query(
                    label,
                    keyword,
                    limit,
                    max_depth,
                    exclude_chunk,
                    review_scope=review_scope,
                ),
                **query_params,
            )
            if max_depth <= 0:
                return self._process_query_result(result, limit, kb_id, exclude_chunk)
            record = result.single()
            if not record:
                return {"nodes": [], "edges": []}
            return self._process_subgraph_record(record, limit, kb_id)

    async def query_seed_subgraph(
        self,
        kb_id: str,
        *,
        entity_ids: list[str],
        max_nodes: int,
        max_depth: int = 2,
        entity_only: bool = False,
        review_scope: str = GRAPH_REVIEW_SCOPE_ALL,
    ) -> dict[str, Any]:
        if not entity_ids:
            return {"nodes": [], "edges": []}
        seed_entity_ids = list(dict.fromkeys(entity_ids))
        label = safe_neo4j_label(kb_id)
        max_depth = max(1, min(int(max_depth), 6))
        review_scope = self._normalize_review_scope(review_scope)
        relationship_pattern = ":RELATION" if entity_only else ""
        target_pattern = f"Entity:MilvusKB:`{label}`" if entity_only else f"MilvusKB:`{label}`"
        relation_predicate = self._relation_review_predicate("path_rel", review_scope)
        cypher = f"""
        MATCH (seed:Entity:MilvusKB:`{label}`)
        WHERE seed.entity_id IN $entity_ids
          AND {self._visible_node_predicate("seed", review_scope)}
        MATCH p = (seed)-[{relationship_pattern}*1..{max_depth}]-(n:{target_pattern})
        WHERE all(path_rel IN relationships(p) WHERE {relation_predicate}
          AND coalesce(path_rel.lifecycle_status, 'active') = 'active')
          AND all(path_node IN nodes(p) WHERE {self._visible_node_predicate("path_node", review_scope)})
          {"AND all(path_node IN nodes(p) WHERE path_node:Entity)" if entity_only else ""}
        WITH p LIMIT $path_limit
        WITH collect(p) AS paths
        UNWIND paths AS node_path
        UNWIND nodes(node_path) AS node
        WITH paths, collect(DISTINCT node) AS graph_nodes
        UNWIND paths AS rel_path
        UNWIND relationships(rel_path) AS rel
        RETURN graph_nodes AS nodes, collect(DISTINCT rel) AS edges
        """
        try:
            return await _run_neo4j_query_io(
                self._query_seed_subgraph_sync,
                kb_id,
                cypher,
                seed_entity_ids,
                max_nodes,
            )
        except Exception as e:
            logger.error(f"Milvus seed subgraph query failed: {e}")
            return {"nodes": [], "edges": []}

    def _query_seed_subgraph_sync(
        self,
        kb_id: str,
        cypher: str,
        entity_ids: list[str],
        max_nodes: int,
    ) -> dict[str, Any]:
        with self.driver.session() as session:
            record = session.run(
                cypher,
                entity_ids=entity_ids,
                path_limit=max(max_nodes, 1) * 4,
            ).single()
            if not record:
                return {"nodes": [], "edges": []}
            return self._process_subgraph_record(record, max_nodes, kb_id)

    async def query_and_rank_chunks_by_ppr(
        self,
        kb_id: str,
        seed_weights: dict[str, float],
        *,
        max_nodes: int,
        top_k: int,
        damping: float,
    ) -> list[tuple[str, float]]:
        if not seed_weights:
            return []
        subgraph = await self.query_seed_subgraph(
            kb_id,
            entity_ids=list(seed_weights.keys()),
            max_nodes=max_nodes,
        )
        return self.rank_chunks_by_ppr(subgraph, seed_weights, top_k=top_k, damping=damping)

    @staticmethod
    def rank_chunks_by_ppr(
        subgraph: dict[str, Any],
        seed_weights: dict[str, float],
        *,
        top_k: int,
        damping: float,
    ) -> list[tuple[str, float]]:
        nodes = subgraph.get("nodes") or []
        edges = subgraph.get("edges") or []
        if not nodes:
            return []

        import networkx as nx

        node_ids = [node["id"] for node in nodes]
        index_by_id = {node_id: index for index, node_id in enumerate(node_ids)}
        edge_indices = [
            (index_by_id[edge["source_id"]], index_by_id[edge["target_id"]])
            for edge in edges
            if edge.get("source_id") in index_by_id and edge.get("target_id") in index_by_id
        ]
        if not edge_indices:
            return []

        # networkx 节点 id 直接用节点索引（与 igraph 的 reset 向量语义对齐）。
        graph = nx.Graph()
        graph.add_nodes_from(range(len(nodes)))
        graph.add_edges_from(edge_indices)
        reset = [0.0] * len(nodes)
        chunk_node_indexes: list[tuple[int, str]] = []
        for index, node in enumerate(nodes):
            properties = node.get("properties") or {}
            if node.get("type") == "Chunk" and properties.get("chunk_id"):
                chunk_node_indexes.append((index, properties["chunk_id"]))
                continue
            entity_id = properties.get("entity_id")
            if entity_id in seed_weights:
                reset[index] = seed_weights[entity_id]

        reset_total = sum(reset)
        if reset_total <= 0 or not chunk_node_indexes:
            return []
        reset = [value / reset_total for value in reset]
        # networkx 的 personalization 必须覆盖全部节点（缺节点会抛错），0 值节点贡献为 0；
        # 默认 dangling=None 时跳转分布使用 personalization，与 igraph 的 reset 语义一致。
        personalization = {index: value for index, value in enumerate(reset)}
        scores = nx.pagerank(graph, alpha=min(max(damping, 0.1), 0.99), personalization=personalization)
        ranked = sorted(
            ((chunk_id, float(scores[index])) for index, chunk_id in chunk_node_indexes),
            key=lambda item: item[1],
            reverse=True,
        )
        return ranked[:top_k]

    async def get_labels(self, kb_id: str | None = None) -> list[str]:
        effective_kb_id = kb_id or self.kb_id
        if not effective_kb_id:
            return []
        label = safe_neo4j_label(effective_kb_id)

        cypher = f"""
        MATCH (n:MilvusKB:`{label}`)
        WHERE {self._visible_node_predicate("n", GRAPH_REVIEW_SCOPE_ALL)}
        UNWIND labels(n) AS node_label
        WITH DISTINCT node_label
        WHERE node_label <> 'MilvusKB' AND node_label <> $kb_id
        RETURN node_label
        ORDER BY node_label
        """
        try:
            records = await _run_neo4j_query_io(self._get_labels_sync, cypher, effective_kb_id)
            return [record["node_label"] for record in records]
        except Exception as e:
            logger.error(f"Failed to get Milvus graph labels: {e}")
            return []

    def _get_labels_sync(self, cypher: str, kb_id: str) -> list[Any]:
        return neo4j_read(self.driver, cypher, kb_id=kb_id)

    async def get_stats(self, kb_id: str | None = None) -> dict[str, Any]:
        effective_kb_id = kb_id or self.kb_id
        if not effective_kb_id:
            return {"total_nodes": 0, "total_edges": 0, "entity_types": []}
        label = safe_neo4j_label(effective_kb_id)

        stats_cypher = f"""
        MATCH (n:MilvusKB:`{label}`)
        WHERE {self._visible_node_predicate("n", GRAPH_REVIEW_SCOPE_ALL)}
        WITH count(n) AS node_count
        OPTIONAL MATCH (:MilvusKB:`{label}`)-[r]->(:MilvusKB:`{label}`)
        WHERE coalesce(r.review_status, 'pending') IN ['accepted', 'pending']
          AND coalesce(r.lifecycle_status, 'active') = 'active'
        RETURN node_count, count(r) AS edge_count
        """
        label_cypher = f"""
        MATCH (n:Entity:MilvusKB:`{label}`)
        WHERE {self._visible_node_predicate("n", GRAPH_REVIEW_SCOPE_ALL)}
        WITH n.label AS entity_label, count(*) AS count
        RETURN entity_label, count
        ORDER BY count DESC
        """
        try:
            return await _run_neo4j_query_io(self._get_stats_sync, stats_cypher, label_cypher)
        except Exception as e:
            logger.error(f"Failed to get Milvus graph stats: {e}")
            return {"total_nodes": 0, "total_edges": 0, "entity_types": []}

    def _get_stats_sync(self, stats_cypher: str, label_cypher: str) -> dict[str, Any]:
        with self.driver.session() as session:
            stats = session.run(stats_cypher).single()
            label_stats = session.run(label_cypher)
            return {
                "total_nodes": stats["node_count"] if stats else 0,
                "total_edges": stats["edge_count"] if stats else 0,
                "entity_types": [{"type": row["entity_label"], "count": row["count"]} for row in label_stats],
            }

    async def _get_milvus_kb(self, kb_id: str):
        kb = await self.kb_repo.get_by_kb_id(kb_id)
        if kb is None:
            raise ValueError(f"知识库 {kb_id} 不存在")
        if (kb.kb_type or "").lower() != "milvus":
            raise ValueError("仅 Milvus 知识库支持独立图谱构建")
        return kb

    def _get_locked_config(self, additional_params: dict[str, Any]) -> dict[str, Any]:
        config = additional_params.get(GRAPH_CONFIG_KEY) or {}
        if not config.get("locked"):
            raise ValueError("请先确认并锁定图谱抽取配置")
        if not config.get("extractor_type"):
            raise ValueError("图谱抽取配置缺少 extractor_type")
        return config

    def _public_config(self, config: dict[str, Any]) -> dict[str, Any] | None:
        if not config:
            return None
        return {
            "locked": bool(config.get("locked")),
            "extractor_type": config.get("extractor_type"),
            "extractor_options": self._runtime_extractor_options(config),
            "semantic_fingerprint": config.get("semantic_fingerprint")
            or semantic_config_fingerprint(
                str(config.get("extractor_type") or ""),
                config.get("extractor_options") or {},
            ),
            "created_at": config.get("created_at"),
            "created_by": config.get("created_by"),
            "updated_at": config.get("updated_at"),
            "updated_by": config.get("updated_by"),
        }

    @staticmethod
    def _build_where(
        exclude_chunk: bool,
        keyword: str,
        review_scope: str = GRAPH_REVIEW_SCOPE_ALL,
    ) -> str:
        clauses = [MilvusGraphService._visible_node_predicate("n", review_scope)]
        if exclude_chunk:
            clauses.append("NOT n:Chunk")
        if keyword and keyword != "*":
            clauses.append(
                "(toLower(coalesce(n.name, '')) CONTAINS toLower($keyword)"
                " OR toLower(coalesce(n.content_preview, '')) CONTAINS toLower($keyword)"
                " OR toLower(coalesce(n.chunk_id, '')) CONTAINS toLower($keyword))"
            )
        return "WHERE " + " AND ".join(clauses) if clauses else ""

    @staticmethod
    def _visible_node_predicate(variable: str, review_scope: str) -> str:
        """统一查询 active 图节点；旧审核范围参数不再改变可见性。"""
        MilvusGraphService._normalize_review_scope(review_scope)
        return (
            f"(({variable}:Entity AND coalesce({variable}.lifecycle_status, 'active') = 'active' "
            f"AND EXISTS {{ MATCH (:Chunk:MilvusKB)-[mention:MENTIONS]->({variable}) "
            "WHERE coalesce(mention.review_status, 'pending') IN ['accepted', 'pending'] }) "
            f"OR ({variable}:Chunk AND EXISTS {{ MATCH ({variable})-[mention:MENTIONS]->(:Entity:MilvusKB) "
            "WHERE coalesce(mention.review_status, 'pending') IN ['accepted', 'pending'] }))"
        )

    @staticmethod
    def _relation_review_predicate(variable: str, review_scope: str) -> str:
        MilvusGraphService._normalize_review_scope(review_scope)
        return f"coalesce({variable}.review_status, 'pending') IN ['accepted', 'pending']"

    @staticmethod
    def _normalize_review_scope(review_scope: str) -> str:
        normalized = str(review_scope or GRAPH_REVIEW_SCOPE_ALL).strip().lower()
        if normalized not in {
            GRAPH_REVIEW_SCOPE_ALL,
            GRAPH_REVIEW_SCOPE_ACCEPTED,
            GRAPH_REVIEW_SCOPE_PENDING_PREVIEW,
        }:
            raise ValueError("review_scope 必须是 all；accepted 和 pending_preview 仅作为兼容别名")
        return GRAPH_REVIEW_SCOPE_ALL

    def _build_query(
        self,
        label: str,
        keyword: str,
        limit: int,
        max_depth: int,
        exclude_chunk: bool = False,
        *,
        review_scope: str = GRAPH_REVIEW_SCOPE_ALL,
    ) -> str:
        review_scope = self._normalize_review_scope(review_scope)
        where = self._build_where(exclude_chunk, keyword, review_scope)

        if max_depth <= 0:
            return f"""
            MATCH (n:MilvusKB:`{label}`)
            {where}
            RETURN n AS h, null AS r, null AS t
            LIMIT $limit
            """

        path_node_filter = f"path_node:MilvusKB AND path_node:`{label}`"
        if exclude_chunk:
            path_node_filter += " AND NOT path_node:Chunk"
        relation_predicate = self._relation_review_predicate("path_rel", review_scope)

        return f"""
        MATCH (n:MilvusKB:`{label}`)
        {where}
        WITH n LIMIT $limit
        WITH collect(n) AS seeds
        UNWIND seeds AS seed
        OPTIONAL MATCH p = (seed)-[*1..{max_depth}]-(m:MilvusKB:`{label}`)
        WHERE p IS NULL OR (
            all(path_node IN nodes(p) WHERE {path_node_filter}
                AND {self._visible_node_predicate("path_node", review_scope)})
            AND all(path_rel IN relationships(p) WHERE {relation_predicate}
                AND coalesce(path_rel.lifecycle_status, 'active') = 'active')
        )
        WITH seeds, p
        LIMIT $path_limit
        WITH seeds, collect(p) AS paths
        RETURN reduce(path_nodes = [], path IN paths | path_nodes + nodes(path)) + seeds AS nodes,
               reduce(path_edges = [], path IN paths | path_edges + relationships(path)) AS edges
        """

    def _process_query_result(self, result, limit: int, kb_id: str, exclude_chunk: bool = False) -> dict[str, Any]:
        nodes = []
        edges = []
        node_ids = set()
        edges_by_identity: dict[str, dict[str, Any]] = {}

        for record in result:
            for key in ("h", "t"):
                raw_node = record.get(key)
                if raw_node is None:
                    continue
                node = self._normalize_node(raw_node, kb_id)
                if not node or node["id"] in node_ids:
                    continue
                if exclude_chunk and node.get("type") == "Chunk":
                    continue
                nodes.append(node)
                node_ids.add(node["id"])
            raw_edge = record.get("r")
            if raw_edge is not None:
                edge = self._normalize_edge(raw_edge)
                edge_identity = self._edge_identity(edge)
                if edge and edge_identity not in edges_by_identity:
                    self._initialize_edge_evidence(edge)
                    edges.append(edge)
                    edges_by_identity[edge_identity] = edge
                elif edge and edge_identity:
                    self._merge_edge_evidence(edges_by_identity[edge_identity], edge)
            if len(nodes) >= limit:
                break

        return self._finalize_subgraph_result(nodes, edges, limit)

    def _process_subgraph_record(self, record: Any, limit: int, kb_id: str) -> dict[str, Any]:
        nodes = []
        edges = []
        node_ids = set()
        edges_by_identity: dict[str, dict[str, Any]] = {}

        for raw_node in record.get("nodes") or []:
            node = self._normalize_node(raw_node, kb_id)
            if not node or node["id"] in node_ids:
                continue
            nodes.append(node)
            node_ids.add(node["id"])
            if len(nodes) >= limit:
                break

        for raw_edge in record.get("edges") or []:
            edge = self._normalize_edge(raw_edge)
            edge_identity = self._edge_identity(edge)
            if not edge:
                continue
            if edge["source_id"] not in node_ids or edge["target_id"] not in node_ids:
                continue
            if edge_identity in edges_by_identity:
                self._merge_edge_evidence(edges_by_identity[edge_identity], edge)
                continue
            self._initialize_edge_evidence(edge)
            edges.append(edge)
            edges_by_identity[edge_identity] = edge

        return self._finalize_subgraph_result(nodes, edges, limit)

    @staticmethod
    def _finalize_subgraph_result(
        nodes: list[dict[str, Any]], edges: list[dict[str, Any]], limit: int
    ) -> dict[str, Any]:
        limit = max(0, limit)
        final_nodes = nodes[:limit]
        node_ids = {node["id"] for node in final_nodes}
        final_edges = [
            edge for edge in edges if edge.get("source_id") in node_ids and edge.get("target_id") in node_ids
        ]
        return {"nodes": final_nodes, "edges": final_edges[: limit * 2]}

    def _normalize_node(self, raw_node: Any, kb_id: str | None = None) -> dict[str, Any]:
        if hasattr(raw_node, "element_id"):
            node_id = raw_node.element_id
            labels = list(raw_node.labels)
            properties = dict(raw_node.items())
        elif isinstance(raw_node, dict):
            node_id = raw_node.get("id") or raw_node.get("element_id")
            labels = raw_node.get("labels", [])
            properties = raw_node.get("properties") or {k: v for k, v in raw_node.items() if k not in {"id", "labels"}}
        else:
            return {}

        effective_kb_id = kb_id or self.kb_id
        db_label = properties.get("kb_id") or effective_kb_id
        filtered_labels = [label for label in labels if label not in {"MilvusKB", db_label}]
        entity_type = "Chunk" if "Chunk" in labels else properties.get("label", "Entity")
        name = properties.get("name") or properties.get("content_preview") or properties.get("chunk_id") or "Unknown"
        return {
            "id": node_id,
            "name": name,
            "original_id": node_id,
            "type": entity_type,
            "labels": filtered_labels,
            "properties": properties,
            "normalized": {
                "name": name,
                "type": entity_type,
                "source": "milvus",
            },
            "graph_type": "milvus",
        }

    def _normalize_edge(self, raw_edge: Any) -> dict[str, Any]:
        if hasattr(raw_edge, "element_id"):
            edge_id = raw_edge.element_id
            edge_type = raw_edge.type
            source_id = raw_edge.start_node.element_id
            target_id = raw_edge.end_node.element_id
            properties = dict(raw_edge.items())
            edge_type = properties.get("type") or edge_type
        elif isinstance(raw_edge, dict):
            edge_id = raw_edge.get("id")
            edge_type = raw_edge.get("type")
            source_id = raw_edge.get("source_id")
            target_id = raw_edge.get("target_id")
            properties = raw_edge.get("properties", {})
        else:
            return {}

        return {
            "id": edge_id,
            "source_id": source_id,
            "target_id": target_id,
            "type": edge_type,
            "properties": properties,
            "normalized": {
                "type": edge_type,
                "direction": "directed",
            },
        }

    @staticmethod
    def _edge_identity(edge: dict[str, Any]) -> str | None:
        """同一三元组可被多个 Chunk 命中，图谱展示时按稳定三元组 ID 去重。"""
        if not edge:
            return None
        return (
            (edge.get("properties") or {}).get("triple_id")
            or edge.get("id")
            or f"{edge.get('source_id')}:{edge.get('type')}:{edge.get('target_id')}"
        )

    @staticmethod
    def _initialize_edge_evidence(edge: dict[str, Any]) -> None:
        """将单条 Neo4j 关系规范为可累加的证据集合。"""
        properties = edge.setdefault("properties", {})
        chunk_ids = [str(value) for value in properties.get("evidence_chunk_ids") or [] if value]
        file_ids = [str(value) for value in properties.get("evidence_file_ids") or [] if value]
        evidence_texts = [str(value) for value in properties.get("evidence_texts") or [] if value]
        if properties.get("chunk_id"):
            chunk_ids.append(str(properties["chunk_id"]))
        if properties.get("file_id"):
            file_ids.append(str(properties["file_id"]))
        if properties.get("text"):
            evidence_texts.append(str(properties["text"]))
        properties["evidence_chunk_ids"] = list(dict.fromkeys(chunk_ids))
        properties["evidence_file_ids"] = list(dict.fromkeys(file_ids))
        properties["evidence_texts"] = list(dict.fromkeys(evidence_texts))
        properties["evidence_count"] = max(
            int(properties.get("evidence_count") or 0),
            len(properties["evidence_chunk_ids"]),
            1,
        )
        dimensions = properties.get("military_value_dimensions") or []
        properties["military_value_dimensions"] = (
            list(dict.fromkeys(str(value) for value in dimensions if value)) if isinstance(dimensions, list) else []
        )
        conditions = properties.get("applicable_conditions") or []
        properties["applicable_conditions"] = (
            list(dict.fromkeys(str(value) for value in conditions if value)) if isinstance(conditions, list) else []
        )

    @classmethod
    def _merge_edge_evidence(cls, existing: dict[str, Any], duplicate: dict[str, Any]) -> None:
        """按稳定三元组 ID 去重时合并所有 Chunk 与文件来源。"""
        cls._initialize_edge_evidence(existing)
        cls._initialize_edge_evidence(duplicate)
        existing_properties = existing["properties"]
        duplicate_properties = duplicate["properties"]
        for key in ("evidence_chunk_ids", "evidence_file_ids", "evidence_texts"):
            existing_properties[key] = list(
                dict.fromkeys([*existing_properties.get(key, []), *duplicate_properties.get(key, [])])
            )
        existing_properties["evidence_count"] = max(
            len(existing_properties["evidence_chunk_ids"]),
            int(existing_properties.get("evidence_count") or 0) + int(duplicate_properties.get("evidence_count") or 0),
        )
        existing_properties["military_value_dimensions"] = list(
            dict.fromkeys(
                [
                    *existing_properties.get("military_value_dimensions", []),
                    *duplicate_properties.get("military_value_dimensions", []),
                ]
            )
        )
        existing_properties["applicable_conditions"] = list(
            dict.fromkeys(
                [
                    *existing_properties.get("applicable_conditions", []),
                    *duplicate_properties.get("applicable_conditions", []),
                ]
            )
        )
        claim_priority = {"Fact": 0, "Inference": 1, "Hypothesis": 2}
        claim_levels = [
            str(value).strip().title()
            for value in (
                existing_properties.get("claim_level"),
                duplicate_properties.get("claim_level"),
            )
            if str(value or "").strip().title() in claim_priority
        ]
        if claim_levels:
            existing_properties["claim_level"] = max(claim_levels, key=claim_priority.get)
        confidences = []
        for properties in (existing_properties, duplicate_properties):
            try:
                confidences.append(float(properties["confidence"]))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        if confidences:
            existing_properties["confidence"] = max(0.0, min(min(confidences), 1.0))
        for key in (
            "evidence_quote",
            "reasoning_basis",
            "expected_capability_gain",
            "application_direction",
            "uncertainty",
        ):
            values = [
                str(value).strip()
                for value in (existing_properties.get(key), duplicate_properties.get(key))
                if str(value or "").strip()
            ]
            if values:
                existing_properties[key] = "；".join(dict.fromkeys(values))
        existing_properties["expert_review_required"] = bool(
            existing_properties.get("expert_review_required")
            or duplicate_properties.get("expert_review_required")
            or existing_properties.get("claim_level") == "Hypothesis"
        )
