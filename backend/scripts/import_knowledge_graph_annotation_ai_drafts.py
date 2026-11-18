"""把受约束的 AI 候选幂等写入本人草稿区，不创建正式 revision。"""

from __future__ import annotations

import argparse
import asyncio
import json
import unicodedata
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from platform_core.repositories.knowledge_graph_annotation_repository import (
    KnowledgeGraphAnnotationRepository,
)
from platform_core.services.knowledge_graph_annotation_service import KnowledgeGraphAnnotationService
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeGraphAnnotationAssignment,
    KnowledgeGraphAnnotationSubmission,
    KnowledgeSourceDocument,
)


async def run(args: argparse.Namespace) -> int:
    """校验归属、权威 Block 与本体后写入持久草稿。"""
    rows = []
    for path in args.draft_files:
        rows.extend(_read_jsonl(path))
    if len(rows) != args.expect_count:
        raise ValueError(f"候选数量应为 {args.expect_count}，实际为 {len(rows)}")
    manifest_document_ids = [str(row.get("document_id") or "") for row in rows]
    if any(not item for item in manifest_document_ids):
        raise ValueError("AI 候选缺少 document_id")
    if len(set(manifest_document_ids)) != len(manifest_document_ids):
        raise ValueError("AI 候选 document_id 重复")

    repository = KnowledgeGraphAnnotationRepository()
    assignments = await repository.list_user_assignments(
        kb_id=args.kb_id,
        user_id=args.annotator_uid,
        campaign_id=args.campaign_id,
    )
    annotator_assignments = [item for item in assignments if item["role"] == "annotator"]
    assignment_by_document = {item["document_id"]: item for item in annotator_assignments}
    if len(assignment_by_document) != args.expect_count:
        raise ValueError(
            f"活动内本人独立标注任务应为 {args.expect_count}，实际为 {len(assignment_by_document)}"
        )
    assignment_document_by_manifest = await _assignment_document_ids_by_manifest(args.campaign_id)
    if set(manifest_document_ids) != set(assignment_document_by_manifest):
        missing = sorted(set(assignment_document_by_manifest) - set(manifest_document_ids))
        extra = sorted(set(manifest_document_ids) - set(assignment_document_by_manifest))
        raise ValueError(f"候选与任务文档集合不一致: missing={missing[:5]}, extra={extra[:5]}")

    submissions_before = await _submission_count(args.campaign_id, args.annotator_uid)
    service = KnowledgeGraphAnnotationService(repository=repository)
    entity_count = 0
    relation_count = 0
    for index, row in enumerate(rows, start=1):
        provenance = dict(row.get("draft_provenance") or {})
        _validate_import_provenance(provenance, args.annotator_uid, index)
        assignment_document_id = assignment_document_by_manifest[str(row["document_id"])]
        assignment = assignment_by_document[assignment_document_id]
        authoritative_assignment = await repository.get_assignment(assignment["assignment_id"])
        if authoritative_assignment is None:
            raise LookupError(f"标注任务不存在: {assignment['assignment_id']}")
        blocks, entities, relations, rebase_report = _rebase_to_authoritative_blocks(
            row,
            authoritative_assignment["blocks"],
        )
        if rebase_report:
            provenance["authoritative_rebase"] = rebase_report
        payload = {
            "document_id": assignment["document_id"],
            "title": row.get("title") or assignment["title"],
            "split": row["split"],
            "language": row["language"],
            "source_type": row["source_type"],
            "domain": row.get("domain") or "",
            "source_version": str(assignment["document_version"]),
            "blocks": blocks,
            "entities": entities,
            "relations": relations,
        }
        try:
            await service.save_annotation_draft(
                kb_id=args.kb_id,
                assignment_id=assignment["assignment_id"],
                user_id=args.annotator_uid,
                payload=payload,
                source_kind="ai_prelabel",
                provenance=provenance,
            )
        except (LookupError, PermissionError, ValueError) as exc:
            raise ValueError(
                f"第 {index} 个候选 {row['document_id']} 无法写入任务 {assignment['assignment_id']}: {exc}"
            ) from exc
        entity_count += len(payload["entities"])
        relation_count += len(payload["relations"])

    drafts = await repository.list_drafts(
        kb_id=args.kb_id,
        campaign_id=args.campaign_id,
        annotator_uid=args.annotator_uid,
    )
    submissions_after = await _submission_count(args.campaign_id, args.annotator_uid)
    if len(drafts) != args.expect_count:
        raise RuntimeError(f"持久草稿应为 {args.expect_count}，实际为 {len(drafts)}")
    if submissions_after != submissions_before:
        raise RuntimeError("导入草稿期间正式 submission 数量发生变化")

    report = {
        "campaign_id": args.campaign_id,
        "annotator_uid": args.annotator_uid,
        "draft_count": len(drafts),
        "entity_count": entity_count,
        "relation_count": relation_count,
        "formal_submission_count_before": submissions_before,
        "formal_submission_count_after": submissions_after,
        "created_formal_revisions": 0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


async def _submission_count(campaign_id: str, annotator_uid: str) -> int:
    async with pg_manager.get_async_session_context() as session:
        value = await session.scalar(
            select(func.count())
            .select_from(KnowledgeGraphAnnotationSubmission)
            .join(
                KnowledgeGraphAnnotationAssignment,
                KnowledgeGraphAnnotationAssignment.assignment_id
                == KnowledgeGraphAnnotationSubmission.assignment_id,
            )
            .where(
                KnowledgeGraphAnnotationAssignment.campaign_id == campaign_id,
                KnowledgeGraphAnnotationSubmission.annotator_uid == annotator_uid,
            )
        )
        return int(value or 0)


async def _assignment_document_ids_by_manifest(campaign_id: str) -> dict[str, str]:
    async with pg_manager.get_async_session_context() as session:
        rows = (
            await session.execute(
                select(KnowledgeGraphAnnotationAssignment.document_id, KnowledgeSourceDocument.source_metadata)
                .join(
                    KnowledgeSourceDocument,
                    KnowledgeSourceDocument.document_id == KnowledgeGraphAnnotationAssignment.document_id,
                )
                .where(KnowledgeGraphAnnotationAssignment.campaign_id == campaign_id)
            )
        ).all()
    result = {}
    for assignment_document_id, metadata in rows:
        manifest_document_id = str((metadata or {}).get("pilot_manifest_document_id") or "")
        if not manifest_document_id:
            raise ValueError(f"任务文档 {assignment_document_id} 缺少 pilot_manifest_document_id")
        if manifest_document_id in result:
            raise ValueError(f"pilot_manifest_document_id 重复: {manifest_document_id}")
        result[manifest_document_id] = str(assignment_document_id)
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _rebase_to_authoritative_blocks(
    row: dict[str, Any],
    authoritative_blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    blocks = [
        {"block_id": block["block_id"], "text": block["text"], "page": block["page"]}
        for block in authoritative_blocks
    ]
    candidate_blocks = list(row.get("blocks") or [])
    if candidate_blocks == blocks:
        return blocks, list(row.get("entities") or []), list(row.get("relations") or []), None

    old_block_index = {str(block["block_id"]): index for index, block in enumerate(candidate_blocks)}
    rebased_entities = []
    entity_ids = set()
    for entity in row.get("entities") or []:
        location = _locate_text(
            str(entity.get("text") or ""),
            blocks,
            preferred_index=old_block_index.get(str(entity.get("block_id") or "")),
            preferred_start=int(entity.get("start") or 0),
        )
        if location is None:
            continue
        block, start, end = location
        rebased_entities.append(
            {
                **entity,
                "block_id": block["block_id"],
                "start": start,
                "end": end,
                "text": block["text"][start:end],
            }
        )
        entity_ids.add(str(entity["entity_id"]))

    entity_by_id = {str(entity["entity_id"]): entity for entity in rebased_entities}
    rebased_relations = []
    for relation in row.get("relations") or []:
        if (
            str(relation.get("source_entity_id") or "") not in entity_ids
            or str(relation.get("target_entity_id") or "") not in entity_ids
        ):
            continue
        evidence_spans = []
        for span in relation.get("evidence_spans") or []:
            location = _locate_text(
                str(span.get("text") or ""),
                blocks,
                preferred_index=old_block_index.get(str(span.get("block_id") or "")),
                preferred_start=int(span.get("start") or 0),
            )
            if location is None:
                continue
            block, start, end = location
            evidence_spans.append(
                {
                    "block_id": block["block_id"],
                    "start": start,
                    "end": end,
                    "text": block["text"][start:end],
                }
            )
        if relation.get("claim_level") == "Fact" and not evidence_spans:
            source = entity_by_id[str(relation["source_entity_id"])]
            target = entity_by_id[str(relation["target_entity_id"])]
            if source["block_id"] == target["block_id"]:
                block = next(item for item in blocks if item["block_id"] == source["block_id"])
                start = min(int(source["start"]), int(target["start"]))
                end = max(int(source["end"]), int(target["end"]))
                evidence_spans.append(
                    {
                        "block_id": block["block_id"],
                        "start": start,
                        "end": end,
                        "text": block["text"][start:end],
                    }
                )
        if relation.get("claim_level") == "Fact" and not evidence_spans:
            continue
        rebased_relations.append(
            {
                **relation,
                "evidence_block_ids": sorted({span["block_id"] for span in evidence_spans}),
                "evidence_spans": evidence_spans,
            }
        )

    return (
        blocks,
        rebased_entities,
        rebased_relations,
        {
            "reason": "candidate_blocks_differed_from_postgresql_authority",
            "original_entity_count": len(row.get("entities") or []),
            "rebased_entity_count": len(rebased_entities),
            "original_relation_count": len(row.get("relations") or []),
            "rebased_relation_count": len(rebased_relations),
        },
    )


def _locate_text(
    text: str,
    blocks: list[dict[str, Any]],
    *,
    preferred_index: int | None,
    preferred_start: int,
) -> tuple[dict[str, Any], int, int] | None:
    if not text:
        return None
    if preferred_index is not None and preferred_index < len(blocks):
        preferred = blocks[preferred_index]
        if preferred["text"][preferred_start : preferred_start + len(text)] == text:
            return preferred, preferred_start, preferred_start + len(text)
        start = preferred["text"].find(text)
        if start >= 0:
            return preferred, start, start + len(text)
        normalized = _normalized_location(text, preferred["text"])
        if normalized:
            return preferred, *normalized
    for block in blocks:
        start = block["text"].find(text)
        if start >= 0:
            return block, start, start + len(text)
        normalized = _normalized_location(text, block["text"])
        if normalized:
            return block, *normalized
    return None


def _normalized_location(needle: str, haystack: str) -> tuple[int, int] | None:
    normalized_needle = "".join(
        character
        for source in needle
        for character in unicodedata.normalize("NFKC", source)
        if not character.isspace()
    )
    if not normalized_needle:
        return None
    normalized_haystack = []
    source_indexes = []
    for source_index, source in enumerate(haystack):
        for character in unicodedata.normalize("NFKC", source):
            if character.isspace():
                continue
            normalized_haystack.append(character)
            source_indexes.append(source_index)
    start = "".join(normalized_haystack).find(normalized_needle)
    if start < 0:
        return None
    end = start + len(normalized_needle) - 1
    return source_indexes[start], source_indexes[end] + 1


def _validate_import_provenance(provenance: dict[str, Any], annotator_uid: str, line: int) -> None:
    if (
        provenance.get("annotation_kind") != "ai_prelabel"
        or provenance.get("formal_gold_eligible") is not False
        or provenance.get("human_confirmed") is not False
        or provenance.get("intended_human_reviewer") != annotator_uid
    ):
        raise ValueError(f"第 {line} 个候选的 AI 谱系或目标标注员不合法")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--annotator-uid", required=True)
    parser.add_argument("--expect-count", type=int, default=300)
    parser.add_argument("draft_files", type=Path, nargs="+")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
