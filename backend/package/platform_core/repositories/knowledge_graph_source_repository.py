"""图谱权威来源文档和不可变版本的 PostgreSQL 仓储。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    KnowledgeFile,
    KnowledgeSourceDocument,
)


class KnowledgeGraphSourceRepository:
    """集中登记可由 KnowledgeFile 与 Block 重建的权威来源版本。"""

    async def register_knowledge_files(
        self,
        *,
        kb_id: str,
        file_ids: Collection[str] | None = None,
        metadata_by_file_id: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """幂等登记指定知识文件；未指定时登记知识库全部非目录文件。"""
        async with pg_manager.get_async_session_context() as session:
            return await self.register_in_session(
                session,
                kb_id=kb_id,
                file_ids=file_ids,
                metadata_by_file_id=metadata_by_file_id,
            )

    async def register_in_session(
        self,
        session: AsyncSession,
        *,
        kb_id: str,
        file_ids: Collection[str] | None = None,
        metadata_by_file_id: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """复用调用方事务登记来源，供构建运行和标注准备共同使用。"""
        conditions = [KnowledgeFile.kb_id == kb_id, KnowledgeFile.is_folder.is_not(True)]
        if file_ids is not None:
            normalized_file_ids = sorted({str(item) for item in file_ids if str(item)})
            if not normalized_file_ids:
                return []
            conditions.append(KnowledgeFile.file_id.in_(normalized_file_ids))

        rows = (
            await session.execute(
                select(
                    KnowledgeFile.file_id,
                    KnowledgeFile.file_type,
                    KnowledgeFile.content_hash,
                    KnowledgeFile.processing_params,
                    func.coalesce(func.max(KnowledgeChunk.document_version), 1),
                    func.max(KnowledgeChunk.parser_name),
                    func.max(KnowledgeChunk.parser_version),
                )
                .outerjoin(KnowledgeChunk, KnowledgeChunk.file_id == KnowledgeFile.file_id)
                .where(*conditions)
                .group_by(
                    KnowledgeFile.file_id,
                    KnowledgeFile.file_type,
                    KnowledgeFile.content_hash,
                    KnowledgeFile.processing_params,
                )
                .order_by(KnowledgeFile.file_id.asc())
            )
        ).all()

        registered = []
        for file_id, file_type, content_hash, processing_params, version, parser_name, parser_version in rows:
            metadata = dict(processing_params or {})
            metadata.update(dict((metadata_by_file_id or {}).get(str(file_id)) or {}))
            actual_hash = str(content_hash or _canonical_sha256({"legacy_file_id": file_id, "version": version}))
            if not content_hash:
                metadata["content_hash_fallback"] = True
            existing_document_id = await session.scalar(
                select(KnowledgeSourceDocument.document_id).where(
                    KnowledgeSourceDocument.kb_id == kb_id,
                    KnowledgeSourceDocument.file_id == file_id,
                )
            )
            proposed_document_id = str(existing_document_id or file_id)
            source_statement = insert(KnowledgeSourceDocument).values(
                document_id=proposed_document_id,
                kb_id=kb_id,
                file_id=file_id,
                source_type=_source_type(str(file_type or ""), metadata),
                language=str(metadata.get("language") or "unknown")[:32],
                domain=str(metadata.get("domain") or "")[:256],
                content_hash=actual_hash,
                current_version=int(version or 1),
                source_metadata=metadata,
            )
            await session.execute(
                source_statement.on_conflict_do_update(
                    index_elements=["kb_id", "file_id"],
                    set_={
                        "source_type": source_statement.excluded.source_type,
                        "language": source_statement.excluded.language,
                        "domain": source_statement.excluded.domain,
                        "content_hash": source_statement.excluded.content_hash,
                        "current_version": source_statement.excluded.current_version,
                        "source_metadata": source_statement.excluded.source_metadata,
                        "updated_at": func.now(),
                    },
                )
            )
            document_id = await session.scalar(
                select(KnowledgeSourceDocument.document_id).where(
                    KnowledgeSourceDocument.kb_id == kb_id,
                    KnowledgeSourceDocument.file_id == file_id,
                )
            )
            if not document_id:
                raise RuntimeError(f"来源文件 {file_id} 登记后无法回读权威 document_id")
            version_input = {
                "document_id": str(document_id),
                "version": int(version or 1),
                "content_hash": actual_hash,
                "parser_name": parser_name,
                "parser_version": parser_version,
            }
            expected_input_hash = _canonical_sha256(version_input)
            version_statement = insert(KnowledgeDocumentVersion).values(
                **version_input,
                input_hash=expected_input_hash,
                source_metadata=metadata,
            )
            await session.execute(version_statement.on_conflict_do_nothing(index_elements=["document_id", "version"]))
            persisted_input_hash = await session.scalar(
                select(KnowledgeDocumentVersion.input_hash).where(
                    KnowledgeDocumentVersion.document_id == document_id,
                    KnowledgeDocumentVersion.version == int(version or 1),
                )
            )
            if persisted_input_hash != expected_input_hash:
                raise ValueError(f"来源文档 {document_id} v{int(version or 1)} 与不可变版本记录冲突")
            registered.append({"file_id": str(file_id), **version_input})
        return registered


def _source_type(file_type: str, metadata: dict[str, Any]) -> str:
    explicit = str(metadata.get("source_type") or "").strip().lower()
    if explicit in {"paper", "patent"}:
        return explicit
    normalized = file_type.strip().lower()
    if normalized in {"paper", "patent"}:
        return normalized
    return "unknown"


def _canonical_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
