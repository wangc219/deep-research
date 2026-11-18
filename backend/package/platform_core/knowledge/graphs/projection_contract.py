"""PostgreSQL 到图投影适配器之间的稳定事件契约。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ProjectionChunk(BaseModel):
    """重放 Neo4j 投影所需的最小 Chunk 快照。"""

    chunk_id: str = Field(min_length=1, max_length=128)
    file_id: str = Field(min_length=1, max_length=64)
    chunk_index: int = Field(ge=0)
    content_preview: str = Field(default="", max_length=300)
    start_char_pos: int | None = Field(default=None, ge=0)
    end_char_pos: int | None = Field(default=None, ge=0)
    document_version: int = Field(default=1, ge=1)
    page_number: int | None = Field(default=None, ge=1)
    block_type: str | None = Field(default=None, max_length=64)
    heading_path: list[str] = Field(default_factory=list)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    parser_name: str | None = Field(default=None, max_length=128)
    parser_version: str | None = Field(default=None, max_length=128)


class GraphProjectionPayload(BaseModel):
    """可持久化、可重放且与运行时对象解耦的图投影负载。"""

    event_type: Literal["chunk_graph"] = "chunk_graph"
    version: Literal[1] = 1
    kb_id: str = Field(min_length=1, max_length=80)
    chunk: ProjectionChunk
    graph_payload: dict[str, Any]
    entity_records: list[dict[str, Any]]
    triple_records: list[dict[str, Any]]


class ReviewStatusProjectionPayload(BaseModel):
    """人工审核提交后同步 Neo4j 边状态的最小负载。"""

    event_type: Literal["review_status"] = "review_status"
    version: Literal[1] = 1
    kb_id: str = Field(min_length=1, max_length=80)
    chunk_id: str = Field(min_length=1, max_length=128)
    target_type: Literal["entity_mention", "relation_mention"]
    entity_id: str | None = Field(default=None, max_length=64)
    triple_id: str | None = Field(default=None, max_length=64)
    review_status: Literal["accepted", "rejected", "disputed", "superseded"]
    decision_id: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_target_identity(self):
        """审核目标必须携带且只携带对应的权威 ID。"""
        if self.target_type == "entity_mention":
            if not self.entity_id or self.triple_id:
                raise ValueError("entity_mention 必须只携带 entity_id")
        elif not self.triple_id or self.entity_id:
            raise ValueError("relation_mention 必须只携带 triple_id")
        return self


class EntityRedirectProjectionPayload(BaseModel):
    """实体 merge/split 后同步 Neo4j 生命周期与 redirect 边。"""

    event_type: Literal["entity_redirect"] = "entity_redirect"
    version: Literal[1] = 1
    kb_id: str = Field(min_length=1, max_length=80)
    source_entity_id: str = Field(min_length=1, max_length=64)
    target_entity_ids: list[str] = Field(min_length=1, max_length=50)
    operation: Literal["merge", "split"]
    redirect_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_redirect(self):
        """redirect 目标必须唯一且不能指向源实体。"""
        if len(set(self.target_entity_ids)) != len(self.target_entity_ids):
            raise ValueError("target_entity_ids 不能重复")
        if self.source_entity_id in self.target_entity_ids:
            raise ValueError("redirect 不能指向源实体")
        if self.operation == "merge" and len(self.target_entity_ids) != 1:
            raise ValueError("merge 必须且只能包含一个目标实体")
        if self.operation == "split" and len(self.target_entity_ids) < 2:
            raise ValueError("split 至少需要两个目标实体")
        return self


class RelationLifecycleProjectionPayload(BaseModel):
    """关系失效或被替代后同步 Neo4j 与 Milvus 投影。"""

    event_type: Literal["relation_lifecycle"] = "relation_lifecycle"
    version: Literal[1] = 1
    kb_id: str = Field(min_length=1, max_length=80)
    triple_id: str = Field(min_length=1, max_length=64)
    lifecycle_status: Literal["invalid", "superseded"]
    superseded_by_triple_id: str | None = Field(default=None, max_length=64)
    relation_version: int = Field(ge=2)
    valid_to: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_supersession(self):
        """仅 superseded 状态允许且要求替代关系。"""
        if self.lifecycle_status == "superseded" and not self.superseded_by_triple_id:
            raise ValueError("superseded 关系必须指定替代关系")
        if self.lifecycle_status == "invalid" and self.superseded_by_triple_id:
            raise ValueError("invalid 关系不能指定替代关系")
        if self.triple_id == self.superseded_by_triple_id:
            raise ValueError("关系不能替代自身")
        return self


def build_projection_event(
    *,
    kb_id: str,
    chunk: Any,
    graph_payload: dict[str, Any],
    entity_records: list[dict[str, Any]],
    triple_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """从一次权威写入生成确定性的 revision 与 outbox 事件。"""
    payload = GraphProjectionPayload(
        kb_id=kb_id,
        chunk=ProjectionChunk(
            chunk_id=chunk.chunk_id,
            file_id=chunk.file_id,
            chunk_index=int(chunk.chunk_index),
            content_preview=str(chunk.content or "")[:300],
            start_char_pos=chunk.start_char_pos,
            end_char_pos=chunk.end_char_pos,
            document_version=int(getattr(chunk, "document_version", None) or 1),
            page_number=getattr(chunk, "page_number", None),
            block_type=getattr(chunk, "block_type", None),
            heading_path=list(getattr(chunk, "heading_path", None) or []),
            bbox=getattr(chunk, "bbox", None),
            parser_name=getattr(chunk, "parser_name", None),
            parser_version=getattr(chunk, "parser_version", None),
        ),
        graph_payload=graph_payload,
        entity_records=entity_records,
        triple_records=triple_records,
    ).model_dump(mode="json")
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    revision = hashlib.sha256(f"graph-revision:{canonical}".encode()).hexdigest()[:32]
    event_id = hashlib.sha256(f"projection-event:{kb_id}:{chunk.chunk_id}:{revision}".encode()).hexdigest()[:32]
    metadata = graph_payload.get("metadata") or {}
    return {
        "event_id": event_id,
        "graph_revision": revision,
        "ontology_version": str(metadata.get("ontology_version") or "legacy-unversioned"),
        "reason": "chunk_graph_upsert",
        "summary": {
            "chunk_id": chunk.chunk_id,
            "entity_count": len(entity_records),
            "relation_count": len(triple_records),
            "pipeline_revision": metadata.get("pipeline_revision"),
        },
        "payload": payload,
    }


def build_review_projection_event(
    *,
    kb_id: str,
    chunk_id: str,
    target_type: str,
    entity_id: str | None,
    triple_id: str | None,
    review_status: str,
    decision_id: str,
    ontology_version: str | None,
) -> dict[str, Any]:
    """为一次不可变人工审核决定生成可重放投影事件。"""
    payload = ReviewStatusProjectionPayload(
        kb_id=kb_id,
        chunk_id=chunk_id,
        target_type=target_type,
        entity_id=entity_id,
        triple_id=triple_id,
        review_status=review_status,
        decision_id=decision_id,
    ).model_dump(mode="json")
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    revision = hashlib.sha256(f"review-revision:{canonical}".encode()).hexdigest()[:32]
    event_id = hashlib.sha256(f"review-projection:{canonical}".encode()).hexdigest()[:32]
    return {
        "event_id": event_id,
        "graph_revision": revision,
        "ontology_version": str(ontology_version or "legacy-unversioned"),
        "reason": "review_status_changed",
        "summary": {
            "chunk_id": chunk_id,
            "target_type": target_type,
            "review_status": review_status,
            "decision_id": decision_id,
        },
        "payload": payload,
    }


def build_entity_redirect_projection_event(
    *,
    kb_id: str,
    source_entity_id: str,
    target_entity_ids: list[str],
    operation: str,
    redirect_id: str,
    reason: str,
    graph_revision: str,
) -> dict[str, Any]:
    """为实体 merge/split 生成确定性、可重放的图投影事件。"""
    payload = EntityRedirectProjectionPayload(
        kb_id=kb_id,
        source_entity_id=source_entity_id,
        target_entity_ids=target_entity_ids,
        operation=operation,
        redirect_id=redirect_id,
        reason=reason,
    ).model_dump(mode="json")
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    event_id = hashlib.sha256(f"entity-redirect-projection:{graph_revision}:{canonical}".encode()).hexdigest()[:32]
    return {
        "event_id": event_id,
        "graph_revision": graph_revision,
        "payload": payload,
    }


def build_relation_lifecycle_projection_event(
    *,
    kb_id: str,
    triple_id: str,
    lifecycle_status: str,
    superseded_by_triple_id: str | None,
    relation_version: int,
    valid_to: str,
    reason: str,
    graph_revision: str,
) -> dict[str, Any]:
    """为关系失效或替代生成确定性、可重放的投影事件。"""
    payload = RelationLifecycleProjectionPayload(
        kb_id=kb_id,
        triple_id=triple_id,
        lifecycle_status=lifecycle_status,
        superseded_by_triple_id=superseded_by_triple_id,
        relation_version=relation_version,
        valid_to=valid_to,
        reason=reason,
    ).model_dump(mode="json")
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    event_id = hashlib.sha256(f"relation-lifecycle-projection:{graph_revision}:{canonical}".encode()).hexdigest()[:32]
    return {
        "event_id": event_id,
        "graph_revision": graph_revision,
        "payload": payload,
    }
