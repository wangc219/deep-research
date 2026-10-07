from fastapi import APIRouter, Depends, HTTPException, Query

from server.utils.auth_middleware import get_admin_user
from server.utils.knowledge_permissions import require_knowledge_base_read
from server.utils.knowledge_response import serialize_knowledge_base
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.knowledge.runtime import knowledge_base
from platform_core.storage.postgres.models_business import User
from platform_core.utils.logging_config import logger

graph = APIRouter(prefix="/graph", tags=["graph"])


async def _get_graph_service(kb_id: str) -> MilvusGraphService:
    db_info = await knowledge_base.get_database_info(kb_id)
    if not db_info:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    kb_type = db_info.kb_type.lower()
    if kb_type != "milvus":
        raise HTTPException(status_code=404, detail="Graph API only supports Milvus knowledge bases")

    return MilvusGraphService(kb_id=kb_id)


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
    mode: str = Query("auto", description="auto、requirement_driven 或 entity_expansion"),
    max_hops: int = Query(5, description="最大关系跳数", ge=1, le=6),
    max_paths: int = Query(10, description="最大返回链路数", ge=1, le=10),
    include_combinations: bool = Query(True, description="是否包含探索性组合关联"),
    current_user: User = Depends(require_knowledge_base_read),
):
    """发现有证据支撑的技术链路与明确标记的探索性组合。"""
    if mode not in {"auto", "requirement_driven", "entity_expansion"}:
        raise HTTPException(status_code=422, detail="mode 必须是 auto、requirement_driven 或 entity_expansion")
    try:
        service = await _get_graph_service(kb_id)
        result_data = await service.discover_paths(
            query=query,
            mode=mode,
            max_hops=max_hops,
            max_paths=max_paths,
            include_combinations=include_combinations,
        )
        return {"success": True, "data": result_data}
    except HTTPException:
        raise
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
