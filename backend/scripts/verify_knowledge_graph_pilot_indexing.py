"""核验 Pilot 入库文件、PostgreSQL Chunk 与 MinIO 原文的一致性。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path

from pymilvus import Collection, connections, db

from platform_core.knowledge.training.pilot_index_validation import (
    summarize_index_validation,
    validate_indexed_document,
)
from platform_core.knowledge.utils.kb_utils import parse_minio_url
from platform_core.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from platform_core.repositories.knowledge_file_repository import KnowledgeFileRepository
from platform_core.repositories.task_repository import TaskRepository
from platform_core.storage.minio import get_minio_client


async def verify(args: argparse.Namespace) -> dict:
    """按任务闭集或知识库全量文件执行只读核验。"""
    file_repository = KnowledgeFileRepository()
    task = None
    if args.all_kb_files:
        if args.expected_file_count is None:
            raise ValueError("--all-kb-files 必须同时提供 --expected-file-count")
        files = [record for record in await file_repository.list_by_kb_id(args.kb_id) if record.is_folder is not True]
        file_ids = sorted(record.file_id for record in files)
        files_by_id = {record.file_id: record for record in files}
    else:
        task = await TaskRepository().get_by_id(args.task_id)
        if task is None:
            raise ValueError(f"任务不存在: {args.task_id}")
        payload = dict(task.payload or {})
        if payload.get("kb_id") != args.kb_id:
            raise ValueError("任务 kb_id 与命令参数不一致")
        file_ids = [str(file_id) for file_id in payload.get("file_ids") or []]
        if not file_ids:
            raise ValueError("任务载荷没有固定 file_ids，不能据此执行闭集核验")
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("任务载荷包含重复 file_id")

        files = await file_repository.list_by_file_ids(file_ids)
        files_by_id = {record.file_id: record for record in files if record.kb_id == args.kb_id}

    chunks = await KnowledgeChunkRepository().list_by_file_ids(file_ids)
    chunks_by_file: dict[str, list] = {file_id: [] for file_id in file_ids}
    for chunk in chunks:
        chunks_by_file.setdefault(chunk.file_id, []).append(chunk)

    storage = get_minio_client()
    documents = []
    for file_id in file_ids:
        record = files_by_id.get(file_id)
        if record is None:
            documents.append(
                {
                    "file_id": file_id,
                    "status": "missing",
                    "chunk_count": 0,
                    "rebuildable_chunks": 0,
                    "ready": False,
                    "issues": [{"code": "file_missing"}],
                }
            )
            continue
        if not record.markdown_file:
            documents.append(
                {
                    "file_id": file_id,
                    "status": record.status,
                    "chunk_count": len(chunks_by_file[file_id]),
                    "rebuildable_chunks": 0,
                    "ready": False,
                    "issues": [{"code": "markdown_missing"}],
                }
            )
            continue
        bucket_name, object_name = parse_minio_url(record.markdown_file)
        source_text = (await storage.adownload_file(bucket_name, object_name)).decode("utf-8")
        documents.append(
            validate_indexed_document(
                file_id=file_id,
                status=record.status,
                declared_chunk_count=int(record.chunk_count or 0),
                source_text=source_text,
                chunks=chunks_by_file[file_id],
            )
        )

    vector_count = await asyncio.to_thread(_count_milvus_vectors, args.kb_id, file_ids) if args.verify_milvus else None
    report = {
        "contract_version": "defense-kg-pilot-index-validation-v1",
        "kb_id": args.kb_id,
        "scope": "all_kb_files" if args.all_kb_files else "task_file_ids",
        "task_id": args.task_id,
        "task_status": task.status if task is not None else None,
        "summary": summarize_index_validation(
            documents,
            expected_file_count=args.expected_file_count,
            vector_count=vector_count,
        ),
        "documents": documents,
    }
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _count_milvus_vectors(kb_id: str, file_ids: list[str]) -> int:
    """以 Strong consistency 统计指定文件集合的真实 Milvus 行数。"""
    alias = f"pilot-index-validation-{uuid.uuid4().hex}"
    connections.connect(
        alias=alias,
        uri=os.getenv("MILVUS_URI") or "http://localhost:19530",
        token=os.getenv("MILVUS_TOKEN") or "",
    )
    try:
        database = os.getenv("MILVUS_DATABASE") or "deep_research"
        db.using_database(database, using=alias)
        collection = Collection(name=kb_id, using=alias)
        collection.load()
        escaped = [file_id.replace("\\", "\\\\").replace('"', '\\"') for file_id in file_ids]
        joined_file_ids = '", "'.join(escaped)
        expression = f'file_id in ["{joined_file_ids}"]'
        rows = collection.query(
            expr=expression,
            output_fields=["count(*)"],
            consistency_level="Strong",
            timeout=30,
        )
        return int(rows[0]["count(*)"]) if rows else 0
    finally:
        connections.disconnect(alias)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-id", required=True)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--task-id", help="载荷中必须包含固定 file_ids 的持久任务")
    scope.add_argument(
        "--all-kb-files",
        action="store_true",
        help="核验知识库内全部非文件夹记录；必须同时声明预期文件数",
    )
    parser.add_argument("--expected-file-count", type=int)
    parser.add_argument("--output")
    parser.add_argument("--verify-milvus", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    report = asyncio.run(verify(args))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.require_ready and not report["summary"]["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
