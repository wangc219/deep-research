from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from server.utils.auth_middleware import get_admin_user, get_required_user
from server.utils.knowledge_permissions import require_knowledge_base_manage, require_knowledge_base_read
from server.utils.knowledge_response import serialize_knowledge_base
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.knowledge.runtime import knowledge_base
from platform_core.knowledge.training.annotation_workflow import AnnotationCampaignSpec
from platform_core.services.knowledge_graph_acceptance_service import KnowledgeGraphAcceptanceService
from platform_core.services.knowledge_graph_annotation_service import KnowledgeGraphAnnotationService
from platform_core.services.knowledge_graph_document_audit_service import KnowledgeGraphDocumentAuditService
from platform_core.services.knowledge_graph_evolution_service import KnowledgeGraphEvolutionService
from platform_core.services.knowledge_graph_governance_service import KnowledgeGraphGovernanceService
from platform_core.services.knowledge_graph_innovation_service import KnowledgeGraphInnovationService
from platform_core.services.knowledge_graph_multihop_service import KnowledgeGraphMultiHopService
from platform_core.services.knowledge_graph_query_service import KnowledgeGraphQueryService
from platform_core.services.knowledge_graph_retrieval_adapter import retrieve_graph_mix_chunks
from platform_core.services.knowledge_graph_solution_service import KnowledgeGraphSolutionService
from platform_core.services.equipment_model_adapter import default_chat_model_spec
from platform_core.storage.postgres.models_business import User
from platform_core.utils.logging_config import logger

graph = APIRouter(prefix="/graph", tags=["graph"])


class GraphReviewDecisionRequest(BaseModel):
    target_type: str = Field(pattern="^(entity_mention|relation_mention)$")
    target_id: str = Field(min_length=1, max_length=128)
    decision: str = Field(pattern="^(accepted|rejected|disputed|superseded)$")
    reason: str = Field(default="", max_length=4000)
    decided_payload: dict | None = None


class GraphConflictRequest(BaseModel):
    conflict_type: str = Field(min_length=1, max_length=64)
    left_target_type: str = Field(pattern="^(entity_mention|relation_mention|entity|relation)$")
    left_target_id: str = Field(min_length=1, max_length=128)
    right_target_type: str | None = Field(
        default=None,
        pattern="^(entity_mention|relation_mention|entity|relation)$",
    )
    right_target_id: str | None = Field(default=None, min_length=1, max_length=128)
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    summary: str = Field(min_length=1, max_length=4000)
    details: dict = Field(default_factory=dict)


class GraphConflictResolutionRequest(BaseModel):
    status: str = Field(pattern="^(resolved|dismissed|superseded)$")
    resolution: str = Field(min_length=1, max_length=4000)


class InnovationDiscoveryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    discovery_mode: str = Field(pattern="^(top_down|bottom_up)$")
    max_hops: int = Field(default=5, ge=2, le=6)
    max_candidates: int = Field(default=10, ge=1, le=50)
    persist: bool = True
    retrieval_mode: str = Field(default="mix", pattern="^(naive|local|global|hybrid|mix)$")
    evidence_scope: str = Field(default="any", pattern="^(any|cross_document)$")
    query_enhancement_enabled: bool = False
    query_model_spec: str | None = Field(default=None, max_length=256)
    query_enhancement_strict: bool = False
    path_reranking_enabled: bool = False
    path_reranking_model_spec: str | None = Field(default=None, max_length=256)
    path_reranking_strict: bool = False
    innovation_llm_enabled: bool = False
    innovation_model_spec: str | None = Field(default=None, max_length=256)
    innovation_llm_strict: bool = False
    innovation_llm_concurrency: int = Field(default=2, ge=1, le=8)


class SolutionGenerationRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    discovery_mode: str = Field(pattern="^(top_down|bottom_up)$")
    llm_enabled: bool = False
    model_spec: str | None = Field(default=None, max_length=256)
    max_hops: int = Field(default=5, ge=2, le=6)
    max_paths: int = Field(default=5, ge=1, le=10)
    retrieval_mode: str = Field(default="mix", pattern="^(naive|local|global|hybrid|mix)$")
    evidence_scope: str = Field(default="any", pattern="^(any|cross_document)$")
    query_enhancement_enabled: bool = False
    query_model_spec: str | None = Field(default=None, max_length=256)
    query_enhancement_strict: bool = False
    path_reranking_enabled: bool = False
    path_reranking_model_spec: str | None = Field(default=None, max_length=256)
    path_reranking_strict: bool = False


def _query_enhancement_options(*, enabled: bool, model_spec: str | None, strict: bool) -> dict:
    """组装默认关闭的 LLM 查询规划配置。"""
    normalized_model_spec = str(model_spec or "").strip()
    if enabled and not normalized_model_spec:
        raise ValueError("启用 LLM 查询规划时必须配置 query_model_spec")
    return {
        "enabled": enabled,
        "model_spec": normalized_model_spec,
        "strict": strict,
    }


def _path_reranking_options(*, enabled: bool, model_spec: str | None, strict: bool) -> dict:
    """组装默认关闭、只允许重排封闭候选的 LLM 路径配置。"""
    normalized_model_spec = str(model_spec or "").strip()
    if enabled and not normalized_model_spec:
        raise ValueError("启用 LLM 多跳路径重排时必须配置 path_reranking_model_spec")
    return {
        "enabled": enabled,
        "model_spec": normalized_model_spec,
        "strict": strict,
    }


def _multihop_narrative_options(*, enabled: bool, model_spec: str | None, strict: bool) -> dict:
    """组装只解释封闭证据路径的多跳结论撰述配置。"""
    normalized_model_spec = str(model_spec or "").strip()
    if enabled and not normalized_model_spec:
        raise ValueError("启用 LLM 多跳结论撰述时必须配置 narrative_model_spec")
    return {
        "enabled": enabled,
        "model_spec": normalized_model_spec,
        "strict": strict,
    }


async def _project_model_spec(
    *,
    enabled: bool,
    model_spec: str | None,
    field: str,
    default_model_spec: str | None = None,
) -> str:
    """启用轻量化 RAG 的 LLM 阶段时默认复用项目模型设置。"""
    if not enabled:
        return str(model_spec or "").strip()
    resolved = str(model_spec or "").strip() or str(default_model_spec or "").strip()
    if not resolved:
        resolved = await default_chat_model_spec(None)
    if not resolved:
        raise ValueError(f"启用 {field} 时项目模型设置必须配置 default_model")
    provider_id = resolved.partition(":")[0].casefold()
    if provider_id in {"local-lightrag", "local-lightrag-eval"}:
        raise ValueError(f"{field} 不再支持本地 7B/MLX 模型，请使用项目模型设置中的通用模型")
    return resolved


class HypothesisReviewRequest(BaseModel):
    decision: str = Field(pattern="^(accepted|rejected|disputed|superseded)$")
    reason: str = Field(min_length=1, max_length=4000)


class EntityRedirectRequest(BaseModel):
    operation: str = Field(pattern="^(merge|split)$")
    target_entity_ids: list[str] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=4000)


class RelationLifecycleRequest(BaseModel):
    lifecycle_status: str = Field(pattern="^(invalid|superseded)$")
    superseded_by_triple_id: str | None = Field(default=None, min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=4000)


class GraphEvaluationRequest(BaseModel):
    pipeline_revision: str = Field(min_length=1, max_length=128)
    gold_manifest_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    prediction_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    report: dict


class GraphAnnotationPayloadRequest(BaseModel):
    payload: dict


class GraphAnnotationDraftRequest(BaseModel):
    payload: dict
    source_kind: str = Field(default="manual", pattern="^(ai_prelabel|manual)$")
    provenance: dict = Field(default_factory=dict)


class GraphBulkAnnotationSubmissionRequest(BaseModel):
    confirm_submission: bool
    expected_draft_count: int = Field(ge=1, le=10000)


class OntologyVersionRegistrationRequest(BaseModel):
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    name: str = Field(min_length=1, max_length=255)
    entity_types: list[dict] = Field(min_length=1, max_length=256)
    relation_types: list[dict] = Field(default_factory=list, max_length=512)
    previous_version: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    change_reason: str = Field(min_length=1, max_length=4000)


async def _get_graph_service(kb_id: str) -> MilvusGraphService:
    db_info = await knowledge_base.get_database_info(kb_id)
    if not db_info:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    kb_type = db_info.kb_type.lower()
    if kb_type != "milvus":
        raise HTTPException(status_code=404, detail="Graph API only supports Milvus knowledge bases")

    return MilvusGraphService(kb_id=kb_id, chunk_retriever=retrieve_graph_mix_chunks)


@graph.get("/list")
async def get_graphs(current_user: User = Depends(get_admin_user)):
    """获取支持图谱能力的 Milvus 知识库列表"""
    try:
        databases = await knowledge_base.get_databases_by_uid(current_user.uid)
        graphs = []
        for db in databases:
            if db.kb_type.lower() != "milvus":
                continue
            serialized = serialize_knowledge_base(db)
            graphs.append(
                {
                    "id": db.kb_id,
                    "name": db.name,
                    "type": "milvus",
                    "description": db.description,
                    "status": "已连接",
                    "created_at": serialized["created_at"],
                    "metadata": serialized,
                }
            )
        return {"success": True, "data": graphs}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to list graphs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list graphs: {str(e)}")


@graph.get("/ontology")
async def get_graph_ontology(
    version: str | None = Query(default=None, max_length=128),
    current_user: User = Depends(get_required_user),
):
    """供已登录标注员读取版本化实体、关系类型和端点约束。"""
    try:
        definition = await KnowledgeGraphGovernanceService().get_ontology(version)
        return {"success": True, "data": definition}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@graph.post("/ontology/register-default")
async def register_default_graph_ontology(current_user: User = Depends(get_admin_user)):
    """幂等注册代码中固定的默认军事领域本体。"""
    try:
        definition = await KnowledgeGraphGovernanceService().ensure_default_ontology(created_by=current_user.uid)
        return {"success": True, "data": definition}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@graph.get("/ontology/versions")
async def list_graph_ontology_versions(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_admin_user),
):
    """列出本体版本、生效时间、创建人和变更原因。"""
    items = await KnowledgeGraphGovernanceService().list_ontology_versions(limit=limit, offset=offset)
    return {"success": True, "data": {"items": items, "count": len(items)}}


@graph.get("/ontology/versions/{version}")
async def get_graph_ontology_version(
    version: str,
    current_user: User = Depends(get_admin_user),
):
    """读取不可变本体快照及相对前序版本的差异映射。"""
    try:
        result = await KnowledgeGraphGovernanceService().get_ontology_version(version)
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@graph.post("/ontology/versions")
async def register_graph_ontology_version(
    data: OntologyVersionRegistrationRequest,
    current_user: User = Depends(get_admin_user),
):
    """注册经过完整约束校验的多领域扩展本体版本。"""
    try:
        result = await KnowledgeGraphGovernanceService().register_ontology_version(
            definition={
                "version": data.version,
                "name": data.name,
                "entity_types": data.entity_types,
                "relation_types": data.relation_types,
            },
            previous_version=data.previous_version,
            change_reason=data.change_reason,
            created_by=current_user.uid,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.get("/review-queue")
async def get_graph_review_queue(
    kb_id: str = Query(..., min_length=1, max_length=80),
    status: str = Query("pending", pattern="^(pending|accepted|rejected|disputed|superseded)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_knowledge_base_read),
):
    """返回带原文、Span、模型版本和置信度的审核队列。"""
    items = await KnowledgeGraphGovernanceService().list_review_queue(
        kb_id=kb_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": {"items": items, "count": len(items)}}


@graph.post("/databases/{kb_id}/review-decisions")
async def decide_graph_candidate(
    kb_id: str,
    data: GraphReviewDecisionRequest,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """接受、拒绝、争议或废弃一个实体/关系 mention。"""
    try:
        result = await KnowledgeGraphGovernanceService().decide(
            kb_id=kb_id,
            target_type=data.target_type,
            target_id=data.target_id,
            decision=data.decision,
            reviewer_uid=current_user.uid,
            reason=data.reason,
            decided_payload=data.decided_payload,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.get("/databases/{kb_id}/conflicts")
async def list_graph_conflicts(
    kb_id: str,
    status: str = Query("open", pattern="^(open|resolved|dismissed|superseded)$"),
    severity: str | None = Query(default=None, pattern="^(low|medium|high|critical)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取独立的知识冲突治理队列。"""
    try:
        items = await KnowledgeGraphGovernanceService().list_conflicts(
            kb_id=kb_id,
            status=status,
            severity=severity,
            limit=limit,
            offset=offset,
        )
        return {"success": True, "data": {"items": items, "count": len(items)}}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/conflicts")
async def register_graph_conflict(
    kb_id: str,
    data: GraphConflictRequest,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """登记人工或规则检测到的知识冲突。"""
    try:
        result = await KnowledgeGraphGovernanceService().register_conflict(
            kb_id=kb_id,
            conflict_type=data.conflict_type,
            left_target_type=data.left_target_type,
            left_target_id=data.left_target_id,
            right_target_type=data.right_target_type,
            right_target_id=data.right_target_id,
            severity=data.severity,
            summary=data.summary,
            details=data.details,
            detected_by=current_user.uid,
        )
        return {"success": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/conflicts/{conflict_id}/resolve")
async def resolve_graph_conflict(
    kb_id: str,
    conflict_id: str,
    data: GraphConflictResolutionRequest,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """裁决并关闭一个知识冲突。"""
    try:
        result = await KnowledgeGraphGovernanceService().resolve_conflict(
            kb_id=kb_id,
            conflict_id=conflict_id,
            status=data.status,
            resolution=data.resolution,
            resolved_by=current_user.uid,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/projections/replay")
async def replay_graph_projections(
    kb_id: str = Query(..., min_length=1, max_length=80),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_knowledge_base_manage),
):
    """仅重放 PostgreSQL outbox，不重新调用抽取模型。"""
    service = await _get_graph_service(kb_id)
    result = await service.replay_projection_outbox(kb_id, limit=limit)
    return {"success": True, "data": result}


@graph.get("/databases/{kb_id}/acceptance/status")
async def get_graph_acceptance_status(
    kb_id: str,
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取 PostgreSQL 权威统计和最近一次已登记验收结论。"""
    result = await KnowledgeGraphAcceptanceService().get_status(kb_id)
    return {"success": True, "data": result}


@graph.get("/databases/{kb_id}/build-runs")
async def list_graph_build_runs(
    kb_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取可复现图谱构建运行摘要。"""
    items = await KnowledgeGraphAcceptanceService().list_build_runs(
        kb_id=kb_id,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": {"items": items, "count": len(items)}}


@graph.get("/databases/{kb_id}/build-runs/{run_id}")
async def get_graph_build_run(
    kb_id: str,
    run_id: str,
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取构建运行、输入输出哈希与阶段日志。"""
    try:
        result = await KnowledgeGraphAcceptanceService().get_build_run(kb_id=kb_id, run_id=run_id)
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/acceptance/evaluations")
async def record_graph_evaluation(
    kb_id: str,
    data: GraphEvaluationRequest,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """登记由可复现 CLI 生成的密封测试与 Pilot 验收报告。"""
    try:
        result = await KnowledgeGraphAcceptanceService().record_evaluation(
            kb_id=kb_id,
            pipeline_revision=data.pipeline_revision,
            gold_manifest_sha256=data.gold_manifest_sha256,
            prediction_sha256=data.prediction_sha256,
            report=data.report,
            created_by=current_user.uid,
        )
        return {"success": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/annotation-campaigns")
async def create_annotation_campaign(
    kb_id: str,
    data: AnnotationCampaignSpec,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """创建固定本体、文档版本和角色分工的双标活动。"""
    try:
        result = await KnowledgeGraphAnnotationService().create_campaign(
            kb_id=kb_id,
            spec=data,
            created_by=current_user.uid,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.get("/databases/{kb_id}/annotation-campaigns")
async def list_annotation_campaigns(
    kb_id: str,
    current_user: User = Depends(get_required_user),
):
    """读取当前账号实际参与的活动及 train/dev/test 完成进度。"""
    items = await KnowledgeGraphAnnotationService().list_user_campaigns(
        kb_id=kb_id,
        user_id=current_user.uid,
    )
    return {"success": True, "data": {"items": items, "count": len(items)}}


@graph.post("/databases/{kb_id}/annotation-campaigns/{campaign_id}/submissions/bulk")
async def bulk_submit_independent_annotations(
    kb_id: str,
    campaign_id: str,
    data: GraphBulkAnnotationSubmissionRequest,
    current_user: User = Depends(get_required_user),
):
    """经当前标注员一次显式确认，批量追加本人全部有变化的草稿。"""
    if data.confirm_submission is not True:
        raise HTTPException(status_code=422, detail="批量提交必须显式确认")
    try:
        result = await KnowledgeGraphAnnotationService().bulk_submit_annotations(
            kb_id=kb_id,
            campaign_id=campaign_id,
            user_id=current_user.uid,
            expected_draft_count=data.expected_draft_count,
        )
        return {"success": True, "data": result}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.get("/databases/{kb_id}/annotation-assignments/mine")
async def list_my_annotation_assignments(
    kb_id: str,
    campaign_id: str | None = Query(default=None, max_length=64),
    current_user: User = Depends(get_required_user),
):
    """只返回当前用户被明确分配的标注或仲裁任务。"""
    items = await KnowledgeGraphAnnotationService().list_user_assignments(
        kb_id=kb_id,
        user_id=current_user.uid,
        campaign_id=campaign_id,
    )
    return {"success": True, "data": {"items": items, "count": len(items)}}


@graph.get("/databases/{kb_id}/annotation-assignments/{assignment_id}")
async def get_annotation_assignment(
    kb_id: str,
    assignment_id: str,
    current_user: User = Depends(get_required_user),
):
    """读取权威 Block；双方提交前对另一份初稿保持隔离。"""
    try:
        result = await KnowledgeGraphAnnotationService().get_assignment(
            kb_id=kb_id,
            assignment_id=assignment_id,
            user_id=current_user.uid,
        )
        return {"success": True, "data": result}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/annotation-assignments/{assignment_id}/submissions")
async def submit_independent_annotation(
    kb_id: str,
    assignment_id: str,
    data: GraphAnnotationPayloadRequest,
    current_user: User = Depends(get_required_user),
):
    """由指定标注员追加自己的不可变初稿 revision。"""
    try:
        result = await KnowledgeGraphAnnotationService().submit_annotation(
            kb_id=kb_id,
            assignment_id=assignment_id,
            user_id=current_user.uid,
            payload=data.payload,
        )
        return {"success": True, "data": result}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/annotation-assignments/{assignment_id}/draft")
async def save_annotation_draft(
    kb_id: str,
    assignment_id: str,
    data: GraphAnnotationDraftRequest,
    current_user: User = Depends(get_required_user),
):
    """保存本人草稿，不产生正式 revision，也不要求逐篇确认状态。"""
    try:
        result = await KnowledgeGraphAnnotationService().save_annotation_draft(
            kb_id=kb_id,
            assignment_id=assignment_id,
            user_id=current_user.uid,
            payload=data.payload,
            source_kind=data.source_kind,
            provenance=data.provenance,
        )
        return {"success": True, "data": result}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/annotation-assignments/{assignment_id}/adjudication")
async def adjudicate_annotation_assignment(
    kb_id: str,
    assignment_id: str,
    data: GraphAnnotationPayloadRequest,
    current_user: User = Depends(get_required_user),
):
    """由任务指定的第三名专家提交唯一仲裁终稿。"""
    try:
        result = await KnowledgeGraphAnnotationService().adjudicate(
            kb_id=kb_id,
            assignment_id=assignment_id,
            user_id=current_user.uid,
            payload=data.payload,
        )
        return {"success": True, "data": result}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.get("/databases/{kb_id}/annotation-campaigns/{campaign_id}/export")
async def export_annotation_campaign(
    kb_id: str,
    campaign_id: str,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """仅导出全部完成仲裁且通过 GoldDocument 校验的活动。"""
    try:
        result = await KnowledgeGraphAnnotationService().export_campaign(
            kb_id=kb_id,
            campaign_id=campaign_id,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@graph.get("/databases/{kb_id}/entities/{entity_id}")
async def get_graph_entity_detail(
    kb_id: str,
    entity_id: str,
    evidence_limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取标准实体、别名、已接受证据和版本历史。"""
    try:
        result = await KnowledgeGraphQueryService().get_entity_detail(
            kb_id=kb_id,
            entity_id=entity_id,
            evidence_limit=evidence_limit,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@graph.get("/databases/{kb_id}/relations/{triple_id}")
async def get_graph_relation_detail(
    kb_id: str,
    triple_id: str,
    evidence_limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取关系端点、已接受 Fact/Inference 证据和适用条件。"""
    try:
        result = await KnowledgeGraphQueryService().get_relation_detail(
            kb_id=kb_id,
            triple_id=triple_id,
            evidence_limit=evidence_limit,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@graph.get("/databases/{kb_id}/revisions")
async def list_graph_revisions(
    kb_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取 PostgreSQL 权威图谱 revision。"""
    result = await KnowledgeGraphQueryService().list_revisions(kb_id=kb_id, limit=limit, offset=offset)
    return {"success": True, "data": result}


@graph.get("/databases/{kb_id}/changes")
async def list_graph_change_events(
    kb_id: str,
    graph_revision: str | None = Query(default=None, max_length=64),
    target_type: str | None = Query(default=None, max_length=32, pattern="^[A-Za-z_]+$"),
    target_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_knowledge_base_read),
):
    """按 revision 或知识目标读取不可变变更事件。"""
    result = await KnowledgeGraphQueryService().list_changes(
        kb_id=kb_id,
        graph_revision=graph_revision,
        target_type=target_type,
        target_id=target_id,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": result}


@graph.get("/subgraph")
async def get_subgraph(
    kb_id: str = Query(..., description="Milvus 知识库ID"),
    node_label: str = Query("*", description="节点标签或查询关键词"),
    max_depth: int = Query(2, description="最大深度", ge=1, le=5),
    max_nodes: int = Query(100, description="最大节点数", ge=1, le=1000),
    exclude_chunk: bool = Query(False, description="是否排除 Chunk 节点"),
    current_user: User = Depends(require_knowledge_base_read),
):
    """查询 Milvus 知识库图谱子图"""
    try:
        logger.info(f"Querying subgraph - kb_id: {kb_id}, label: {node_label}")
        service = await _get_graph_service(kb_id)
        result_data = await service.query_nodes(
            keyword=node_label,
            max_depth=max_depth,
            max_nodes=max_nodes,
            exclude_chunk=exclude_chunk,
        )
        return {"success": True, "data": result_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get subgraph: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get subgraph: {str(e)}")


@graph.get("/labels")
async def get_graph_labels(
    kb_id: str = Query(..., description="Milvus 知识库ID"),
    current_user: User = Depends(require_knowledge_base_read),
):
    """获取 Milvus 知识库图谱的所有标签"""
    try:
        service = await _get_graph_service(kb_id)
        labels = await service.get_labels()
        return {"success": True, "data": {"labels": labels}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get labels: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get labels: {str(e)}")


@graph.get("/paths")
async def discover_graph_paths(
    kb_id: str = Query(..., description="Milvus 知识库ID"),
    query: str = Query(..., description="研发需求或实体", min_length=1, max_length=500),
    mode: str = Query("auto", description="top_down、bottom_up 或 auto；兼容旧模式名称"),
    max_hops: int = Query(5, description="最大关系跳数", ge=1, le=6),
    max_paths: int = Query(10, description="最大返回链路数", ge=1, le=10),
    include_combinations: bool = Query(False, description="是否显式包含探索性组合关联"),
    retrieval_mode: str = Query("mix", pattern="^(naive|local|global|hybrid|mix)$"),
    query_enhancement_enabled: bool = Query(False),
    query_model_spec: str | None = Query(default=None, max_length=256),
    query_enhancement_strict: bool = Query(False),
    path_reranking_enabled: bool = Query(False),
    path_reranking_model_spec: str | None = Query(default=None, max_length=256),
    path_reranking_strict: bool = Query(False),
    narrative_enabled: bool = Query(False),
    narrative_model_spec: str | None = Query(default=None, max_length=256),
    narrative_strict: bool = Query(False),
    current_user: User = Depends(require_knowledge_base_read),
):
    """发现有证据支撑的技术链路与明确标记的探索性组合。"""
    if mode not in {"auto", "top_down", "bottom_up", "requirement_driven", "entity_expansion"}:
        raise HTTPException(
            status_code=422,
            detail="mode 必须是 auto、top_down、bottom_up、requirement_driven 或 entity_expansion",
        )
    try:
        if query_enhancement_enabled or path_reranking_enabled or narrative_enabled:
            await require_knowledge_base_manage(kb_id, current_user=current_user)
        project_default_model = None
        if (
            (query_enhancement_enabled and not query_model_spec)
            or (path_reranking_enabled and not path_reranking_model_spec)
            or (narrative_enabled and not narrative_model_spec)
        ):
            project_default_model = await default_chat_model_spec(None)
        query_model_spec = await _project_model_spec(
            enabled=query_enhancement_enabled,
            model_spec=query_model_spec,
            field="LLM 查询规划",
            default_model_spec=project_default_model,
        )
        path_reranking_model_spec = await _project_model_spec(
            enabled=path_reranking_enabled,
            model_spec=path_reranking_model_spec,
            field="LLM 多跳路径重排",
            default_model_spec=project_default_model,
        )
        narrative_model_spec = await _project_model_spec(
            enabled=narrative_enabled,
            model_spec=narrative_model_spec,
            field="LLM 多跳结论撰述",
            default_model_spec=project_default_model,
        )
        query_enhancement = _query_enhancement_options(
            enabled=query_enhancement_enabled,
            model_spec=query_model_spec,
            strict=query_enhancement_strict,
        )
        path_reranking = _path_reranking_options(
            enabled=path_reranking_enabled,
            model_spec=path_reranking_model_spec,
            strict=path_reranking_strict,
        )
        narrative = _multihop_narrative_options(
            enabled=narrative_enabled,
            model_spec=narrative_model_spec,
            strict=narrative_strict,
        )
        service = KnowledgeGraphMultiHopService(graph_service=await _get_graph_service(kb_id))
        result_data = await service.discover(
            kb_id=kb_id,
            query=query,
            discovery_mode=mode,
            max_hops=max_hops,
            max_paths=max_paths,
            include_combinations=include_combinations,
            retrieval_mode=retrieval_mode,
            query_enhancement=query_enhancement,
            path_reranking=path_reranking,
            narrative=narrative,
        )
        return {"success": True, "data": result_data}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as e:
        logger.exception(f"Failed to discover graph paths: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to discover graph paths: {str(e)}")


@graph.get("/stats")
async def get_graph_stats(
    kb_id: str = Query(..., description="Milvus 知识库ID"),
    current_user: User = Depends(require_knowledge_base_read),
):
    """获取 Milvus 知识库图谱统计信息"""
    try:
        service = await _get_graph_service(kb_id)
        stats_data = await service.get_stats()
        return {"success": True, "data": stats_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@graph.post("/databases/{kb_id}/innovation/discover")
async def discover_innovation_opportunities(
    kb_id: str,
    data: InnovationDiscoveryRequest,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """执行自上而下或自下而上的 GraphRAG 创新关联发现。"""
    try:
        project_default_model = None
        if any(
            (
                data.query_enhancement_enabled and not data.query_model_spec,
                data.path_reranking_enabled and not data.path_reranking_model_spec,
                data.innovation_llm_enabled and not data.innovation_model_spec,
            )
        ):
            project_default_model = await default_chat_model_spec(None)
        query_model_spec = await _project_model_spec(
            enabled=data.query_enhancement_enabled,
            model_spec=data.query_model_spec,
            field="LLM 查询规划",
            default_model_spec=project_default_model,
        )
        path_reranking_model_spec = await _project_model_spec(
            enabled=data.path_reranking_enabled,
            model_spec=data.path_reranking_model_spec,
            field="LLM 多跳路径重排",
            default_model_spec=project_default_model,
        )
        innovation_model_spec = await _project_model_spec(
            enabled=data.innovation_llm_enabled,
            model_spec=data.innovation_model_spec,
            field="LLM 创新增强",
            default_model_spec=project_default_model,
        )
        query_enhancement = _query_enhancement_options(
            enabled=data.query_enhancement_enabled,
            model_spec=query_model_spec,
            strict=data.query_enhancement_strict,
        )
        path_reranking = _path_reranking_options(
            enabled=data.path_reranking_enabled,
            model_spec=path_reranking_model_spec,
            strict=data.path_reranking_strict,
        )
        service = KnowledgeGraphInnovationService(graph_service=await _get_graph_service(kb_id))
        result = await service.discover(
            kb_id=kb_id,
            query=data.query,
            discovery_mode=data.discovery_mode,
            max_hops=data.max_hops,
            max_candidates=data.max_candidates,
            persist=data.persist,
            retrieval_mode=data.retrieval_mode,
            evidence_scope=data.evidence_scope,
            query_enhancement=query_enhancement,
            path_reranking=path_reranking,
            llm_enhancement={
                "enabled": data.innovation_llm_enabled,
                "model_spec": innovation_model_spec,
                "strict": data.innovation_llm_strict,
                "concurrency_count": data.innovation_llm_concurrency,
            },
        )
        return {"success": True, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.get("/databases/{kb_id}/document-cards")
async def list_document_knowledge_cards(
    kb_id: str,
    governance_status: str | None = Query(
        default=None,
        pattern="^(pending|accepted|rejected|disputed|superseded)$",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_knowledge_base_read),
):
    """列出由权威实体、关系与证据归纳的文档知识卡。"""
    items = await KnowledgeGraphDocumentAuditService().list_cards(
        kb_id=kb_id,
        governance_status=governance_status,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": {"items": items, "count": len(items)}}


@graph.get("/databases/{kb_id}/document-cards/{card_id}")
async def get_document_knowledge_card(
    kb_id: str,
    card_id: str,
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取知识卡、研究主辅线及可定位证据 Span。"""
    try:
        result = await KnowledgeGraphDocumentAuditService().get_card(kb_id=kb_id, card_id=card_id)
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/innovation/solution")
async def generate_innovation_solution(
    kb_id: str,
    data: SolutionGenerationRequest,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """用已接受图路径与原文 Chunk 约束可选 LLM 技术方案生成。"""
    try:
        project_default_model = None
        if any(
            (
                data.query_enhancement_enabled and not data.query_model_spec,
                data.path_reranking_enabled and not data.path_reranking_model_spec,
                data.llm_enabled and not data.model_spec,
            )
        ):
            project_default_model = await default_chat_model_spec(None)
        query_model_spec = await _project_model_spec(
            enabled=data.query_enhancement_enabled,
            model_spec=data.query_model_spec,
            field="LLM 查询规划",
            default_model_spec=project_default_model,
        )
        path_reranking_model_spec = await _project_model_spec(
            enabled=data.path_reranking_enabled,
            model_spec=data.path_reranking_model_spec,
            field="LLM 多跳路径重排",
            default_model_spec=project_default_model,
        )
        solution_model_spec = await _project_model_spec(
            enabled=data.llm_enabled,
            model_spec=data.model_spec,
            field="LLM 技术方案生成",
            default_model_spec=project_default_model,
        )
        query_enhancement = _query_enhancement_options(
            enabled=data.query_enhancement_enabled,
            model_spec=query_model_spec,
            strict=data.query_enhancement_strict,
        )
        path_reranking = _path_reranking_options(
            enabled=data.path_reranking_enabled,
            model_spec=path_reranking_model_spec,
            strict=data.path_reranking_strict,
        )
        service = KnowledgeGraphSolutionService(graph_service=await _get_graph_service(kb_id))
        result = await service.generate(
            kb_id=kb_id,
            query=data.query,
            discovery_mode=data.discovery_mode,
            llm_enabled=data.llm_enabled,
            model_spec=solution_model_spec,
            max_hops=data.max_hops,
            max_paths=data.max_paths,
            retrieval_mode=data.retrieval_mode,
            evidence_scope=data.evidence_scope,
            query_enhancement=query_enhancement,
            path_reranking=path_reranking,
        )
        return {"success": True, "data": result}
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if "拒绝生成" in detail else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc


@graph.get("/databases/{kb_id}/innovation/candidates")
async def list_innovation_candidates(
    kb_id: str,
    status: str = Query("pending", pattern="^(pending|accepted|rejected|disputed|superseded)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取预测创新边，默认只返回待审核 Hypothesis。"""
    try:
        items = await KnowledgeGraphInnovationService().list_candidates(
            kb_id=kb_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {"success": True, "data": {"items": items, "count": len(items)}}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/innovation/candidates/{hypothesis_id}/review")
async def review_innovation_candidate(
    kb_id: str,
    hypothesis_id: str,
    data: HypothesisReviewRequest,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """审核预测边；接受结果仍保持 Hypothesis，不自动进入事实查询。"""
    try:
        result = await KnowledgeGraphInnovationService().review_candidate(
            kb_id=kb_id,
            hypothesis_id=hypothesis_id,
            decision=data.decision,
            reviewer_uid=current_user.uid,
            reason=data.reason,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/entities/{entity_id}/evolution/analyze")
async def analyze_entity_evolution(
    kb_id: str,
    entity_id: str,
    persist: bool = Query(True),
    current_user: User = Depends(require_knowledge_base_manage),
):
    """基于已接受证据生成可复现的前沿度、成熟度与爆发趋势快照。"""
    result = await KnowledgeGraphEvolutionService().analyze_entity(
        kb_id=kb_id,
        entity_id=entity_id,
        persist=persist,
    )
    return {"success": True, "data": result}


@graph.get("/databases/{kb_id}/entities/{entity_id}/evolution")
async def list_entity_evolution(
    kb_id: str,
    entity_id: str,
    limit: int = Query(24, ge=1, le=120),
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取技术演化历史快照。"""
    items = await KnowledgeGraphEvolutionService().list_snapshots(
        kb_id=kb_id,
        entity_id=entity_id,
        limit=limit,
    )
    return {"success": True, "data": {"items": items, "count": len(items)}}


@graph.get("/databases/{kb_id}/entities/{entity_id}/history")
async def get_entity_history(
    kb_id: str,
    entity_id: str,
    current_user: User = Depends(require_knowledge_base_read),
):
    """读取实体版本、redirect 与不可变变更历史。"""
    try:
        result = await KnowledgeGraphEvolutionService().entity_history(kb_id=kb_id, entity_id=entity_id)
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/entities/{entity_id}/redirect")
async def redirect_entity(
    kb_id: str,
    entity_id: str,
    data: EntityRedirectRequest,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """以可追溯 redirect 记录实体 merge/split，保留原稳定 ID。"""
    try:
        result = await KnowledgeGraphEvolutionService().redirect_entity(
            kb_id=kb_id,
            source_entity_id=entity_id,
            target_entity_ids=data.target_entity_ids,
            operation=data.operation,
            reason=data.reason,
            created_by=current_user.uid,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@graph.post("/databases/{kb_id}/relations/{triple_id}/lifecycle")
async def update_relation_lifecycle(
    kb_id: str,
    triple_id: str,
    data: RelationLifecycleRequest,
    current_user: User = Depends(require_knowledge_base_manage),
):
    """失效或替代一条关系，并保留 revision、事件和投影谱系。"""
    try:
        result = await KnowledgeGraphEvolutionService().update_relation_lifecycle(
            kb_id=kb_id,
            triple_id=triple_id,
            lifecycle_status=data.lifecycle_status,
            superseded_by_triple_id=data.superseded_by_triple_id,
            reason=data.reason,
            created_by=current_user.uid,
        )
        return {"success": True, "data": result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
