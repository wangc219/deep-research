"""Pilot 标注清单到权威文档版本的只读预检与显式登记。"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from platform_core.knowledge.training.pilot_campaign import (
    AuthoritativeDocumentBinding,
    PILOT_CAMPAIGN_PREFLIGHT_VERSION,
    PilotSelectionManifest,
    pilot_manifest_coverage_blockers,
    safe_manifest_summary,
)
from platform_core.repositories.knowledge_graph_source_repository import KnowledgeGraphSourceRepository
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    KnowledgeFile,
    KnowledgeGraphAnnotationCampaign,
    KnowledgeSourceDocument,
)


@dataclass(frozen=True)
class PilotCampaignPreflightResult:
    """预检公开报告、可生成任务的绑定及显式登记输入。"""

    report: dict[str, Any]
    bindings: list[AuthoritativeDocumentBinding]
    registerable_metadata_by_file_id: dict[str, dict[str, Any]]


class KnowledgeGraphAnnotationPreparationRepository:
    """隔离 Pilot 清单解析、数据库匹配和来源登记职责。"""

    async def preflight(
        self,
        manifest: PilotSelectionManifest,
        *,
        kb_id: str | None = None,
    ) -> PilotCampaignPreflightResult:
        """按内容哈希核对文件、权威版本和 Block，只返回脱敏计数报告。"""
        content_hashes = [item.content_sha256 for item in manifest.entries]
        file_conditions = [
            KnowledgeFile.content_hash.in_(content_hashes),
            KnowledgeFile.is_folder.is_not(True),
        ]
        if kb_id:
            file_conditions.append(KnowledgeFile.kb_id == kb_id)

        async with pg_manager.get_async_session_context() as session:
            files = list(await session.scalars(select(KnowledgeFile).where(*file_conditions)))
            file_ids = [item.file_id for item in files]
            sources = (
                list(
                    await session.scalars(
                        select(KnowledgeSourceDocument).where(KnowledgeSourceDocument.file_id.in_(file_ids))
                    )
                )
                if file_ids
                else []
            )
            source_document_ids = [item.document_id for item in sources]
            versions = (
                (
                    await session.execute(
                        select(KnowledgeDocumentVersion.document_id, KnowledgeDocumentVersion.version).where(
                            KnowledgeDocumentVersion.document_id.in_(source_document_ids)
                        )
                    )
                ).all()
                if source_document_ids
                else []
            )
            chunk_rows = (
                (
                    await session.execute(
                        select(KnowledgeChunk.file_id, KnowledgeChunk.document_version, func.count())
                        .where(KnowledgeChunk.file_id.in_(file_ids))
                        .group_by(KnowledgeChunk.file_id, KnowledgeChunk.document_version)
                    )
                ).all()
                if file_ids
                else []
            )

            resolved_kb_ids = {item.kb_id for item in files}
            campaign_kb_id = kb_id or (next(iter(resolved_kb_ids)) if len(resolved_kb_ids) == 1 else None)
            campaign_count = 0
            if campaign_kb_id:
                campaign_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(KnowledgeGraphAnnotationCampaign)
                        .where(KnowledgeGraphAnnotationCampaign.kb_id == campaign_kb_id)
                    )
                    or 0
                )

        files_by_hash: dict[str, list[KnowledgeFile]] = defaultdict(list)
        for file in files:
            files_by_hash[str(file.content_hash)].append(file)
        sources_by_file_id = {item.file_id: item for item in sources}
        version_keys = {(str(document_id), int(version)) for document_id, version in versions}
        chunk_counts = {(str(file_id), int(version)): int(count) for file_id, version, count in chunk_rows}

        status_counts: Counter[str] = Counter()
        bindings = []
        registerable_metadata_by_file_id = {}
        for entry in manifest.entries:
            matching_files = files_by_hash.get(entry.content_sha256, [])
            if not matching_files:
                status_counts["missing_knowledge_file"] += 1
                continue
            if len(matching_files) > 1:
                status_counts["ambiguous_knowledge_file"] += 1
                continue

            file = matching_files[0]
            available_chunk_versions = {
                version for (file_id, version), count in chunk_counts.items() if file_id == file.file_id and count > 0
            }
            if not available_chunk_versions:
                status_counts["missing_blocks"] += 1
                continue
            source = sources_by_file_id.get(file.file_id)
            registration_metadata = {
                "source_type": entry.source_type,
                "language": entry.language,
                "domain": entry.domain,
                "pilot_manifest_document_id": entry.document_id,
                "pilot_manifest_sha256": manifest.manifest_sha256,
            }
            if source is None:
                status_counts["missing_authoritative_document"] += 1
                registerable_metadata_by_file_id[file.file_id] = registration_metadata
                continue
            if source.content_hash != entry.content_sha256:
                status_counts["source_hash_mismatch"] += 1
                registerable_metadata_by_file_id[file.file_id] = registration_metadata
                continue
            if (source.source_type, source.language, source.domain) != (
                entry.source_type,
                entry.language,
                entry.domain,
            ):
                status_counts["source_metadata_mismatch"] += 1
                registerable_metadata_by_file_id[file.file_id] = registration_metadata
                continue
            current_version = int(source.current_version)
            if (source.document_id, current_version) not in version_keys:
                status_counts["missing_document_version"] += 1
                registerable_metadata_by_file_id[file.file_id] = registration_metadata
                continue
            if not chunk_counts.get((file.file_id, current_version)):
                status_counts["missing_version_blocks"] += 1
                registerable_metadata_by_file_id[file.file_id] = registration_metadata
                continue
            status_counts["ready"] += 1
            bindings.append(
                AuthoritativeDocumentBinding(
                    manifest_document_id=entry.document_id,
                    authoritative_document_id=source.document_id,
                    document_version=current_version,
                )
            )

        knowledge_base_count = len(resolved_kb_ids)
        if kb_id and files:
            knowledge_base_count = 1
        blockers = sorted(key for key, count in status_counts.items() if key != "ready" and count)
        blockers.extend(pilot_manifest_coverage_blockers(manifest))
        if not kb_id and knowledge_base_count != 1:
            blockers.append("knowledge_base_not_unambiguous")
        ready = status_counts["ready"] == len(manifest.entries) and not blockers
        report = {
            "contract_version": PILOT_CAMPAIGN_PREFLIGHT_VERSION,
            "manifest": safe_manifest_summary(manifest),
            "database": {
                "selected_knowledge_base": bool(kb_id),
                "resolved_knowledge_base_count": knowledge_base_count,
                "existing_campaign_count": campaign_count,
            },
            "mapping": {
                "status_counts": dict(sorted(status_counts.items())),
                "manifest_documents_with_file_match": sum(
                    count for status, count in status_counts.items() if status != "missing_knowledge_file"
                ),
                "authoritative_bindings": len(bindings),
                "registerable_authoritative_documents": len(registerable_metadata_by_file_id),
            },
            "blockers": sorted(set(blockers)),
            "campaign_spec_ready": ready,
        }
        return PilotCampaignPreflightResult(
            report=report,
            bindings=bindings,
            registerable_metadata_by_file_id=registerable_metadata_by_file_id,
        )

    async def register_authoritative_documents(
        self,
        *,
        kb_id: str,
        result: PilotCampaignPreflightResult,
    ) -> int:
        """仅在调用方显式请求时，幂等登记预检确认可映射的来源版本。"""
        metadata_by_file_id = result.registerable_metadata_by_file_id
        registered = await KnowledgeGraphSourceRepository().register_knowledge_files(
            kb_id=kb_id,
            file_ids=metadata_by_file_id,
            metadata_by_file_id=metadata_by_file_id,
        )
        return len(registered)
